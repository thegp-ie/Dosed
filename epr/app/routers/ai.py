"""AI scribe endpoints."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from sqlalchemy.orm import Session

from .. import ai_scribe, audit, irish, terminology
from ..config import settings
from ..db import get_db
from ..models import Consultation, ScribeSession, User
from ..security import client_ip, current_user, require

router = APIRouter(prefix="/api", tags=["ai-scribe"])

EDIT_WINDOW = timedelta(hours=12)
AUDIO_TYPES = {"audio/webm", "audio/ogg", "audio/wav", "audio/x-wav", "audio/mpeg", "audio/mp4", "audio/m4a",
               "audio/x-m4a", "video/webm", "application/octet-stream"}


def _aware(d):
    return d if d is None or d.tzinfo else d.replace(tzinfo=timezone.utc)


def _view(s: ScribeSession) -> dict:
    return {"id": s.id, "consultation_id": s.consultation_id, "status": s.status, "error": s.error,
            "created_at": s.created_at.isoformat(), "stt_model": s.stt_model, "llm_model": s.llm_model,
            "transcript": s.transcript, "draft": json.loads(s.draft) if s.draft else None}


def _own_session(db: Session, sid: int, user: User) -> ScribeSession:
    s = db.get(ScribeSession, sid)
    if not s or s.user_id != user.id:
        raise HTTPException(404, "Scribe session not found")
    return s


def _editable(c: Consultation, user: User) -> None:
    if c.clinician_id != user.id:
        raise HTTPException(403, "Only the clinician who owns the note can use the scribe on it")
    if c.signed_at or datetime.now(timezone.utc) - _aware(c.started_at) > EDIT_WINDOW:
        raise HTTPException(409, "This note is locked")


@router.get("/scribe/status")
def status(user: User = Depends(current_user)):
    return {"enabled": settings.scribe_enabled, "stt_model": settings.stt_model if settings.stt_url else None,
            "llm_model": settings.llm_model or None, "retain_days": settings.scribe_retain_days}


@router.post("/consultations/{cid}/scribe")
def start(cid: int, data: dict, request: Request, user: User = Depends(require("scribe")), db: Session = Depends(get_db)):
    if not settings.scribe_enabled:
        raise HTTPException(400, "The AI scribe is not set up on this server")
    c = db.get(Consultation, cid)
    if not c:
        raise HTTPException(404)
    _editable(c, user)
    if data.get("patient_consent") is not True:
        raise HTTPException(400, "Ask the patient and record their consent before recording")
    ai_scribe.purge_expired(db)
    s = ScribeSession(consultation_id=c.id, patient_id=c.patient_id, user_id=user.id,
                      patient_consent_at=datetime.now(timezone.utc))
    db.add(s)
    db.flush()
    audit.record(db, "scribe.start", user=user, patient_id=c.patient_id, entity="scribe", entity_id=s.id,
                 detail={"consultation": c.id, "patient_consent": True}, ip=client_ip(request), commit=False)
    db.commit()
    return _view(s)


@router.post("/scribe/{sid}/audio")
async def upload_audio(sid: int, request: Request, file: UploadFile = File(...), seconds: float | None = Form(None),
                       user: User = Depends(require("scribe")), db: Session = Depends(get_db)):
    """Transcribe and draft. The audio is held in memory only and discarded after transcription."""
    s = _own_session(db, sid, user)
    if s.status != "awaiting_audio":
        raise HTTPException(409, f"Session is {s.status}")
    mime = (file.content_type or "application/octet-stream").split(";")[0].strip().lower()
    if mime not in AUDIO_TYPES:
        raise HTTPException(400, "Unsupported audio format")
    audio = await file.read(settings.scribe_max_audio_mb * 1024 * 1024 + 1)
    await file.close()
    if len(audio) > settings.scribe_max_audio_mb * 1024 * 1024:
        raise HTTPException(413, "Recording is too long")
    if not audio:
        raise HTTPException(400, "Empty recording")
    c = db.get(Consultation, s.consultation_id)
    s.audio_seconds = seconds
    s.stt_model, s.llm_model = settings.stt_model, settings.llm_model
    from starlette.concurrency import run_in_threadpool
    try:
        transcript = await run_in_threadpool(ai_scribe.transcribe, audio, file.filename or "audio.webm", mime)
        del audio
        s.transcript = transcript
        draft = await run_in_threadpool(ai_scribe.draft_note, db, transcript, mode=c.mode, clinician_role=user.role)
        s.draft = json.dumps(draft)
        s.status = "drafted"
    except ai_scribe.ScribeError as e:
        s.status, s.error = "failed", str(e)[:500]
    audit.record(db, "scribe.draft", user=user, patient_id=s.patient_id, entity="scribe", entity_id=s.id,
                 detail={"status": s.status, "stt_model": s.stt_model, "llm_model": s.llm_model,
                         "seconds": seconds}, ip=client_ip(request), commit=False)
    db.commit()
    if s.status == "failed":
        raise HTTPException(502, s.error)
    return _view(s)


@router.get("/scribe/{sid}")
def get(sid: int, user: User = Depends(require("scribe")), db: Session = Depends(get_db)):
    return _view(_own_session(db, sid, user))


@router.post("/scribe/{sid}/accept")
def accept(sid: int, data: dict, request: Request, user: User = Depends(require("scribe")), db: Session = Depends(get_db)):
    """Write the clinician-edited draft into the consultation note."""
    s = _own_session(db, sid, user)
    if s.status != "drafted":
        raise HTTPException(409, f"Session is {s.status}")
    c = db.get(Consultation, s.consultation_id)
    _editable(c, user)
    for k in ("subjective", "objective", "assessment", "plan"):
        if k in data:
            setattr(c, k, (data[k] or None))
    code = (data.get("icpc2_code") or "").upper() or None
    if code and code not in irish.ICPC2:
        raise HTTPException(400, "Unknown ICPC-2 code")
    if code:
        c.icpc2_code = code
    if data.get("icd_code"):
        try:
            c.icd_system, c.icd_code, c.icd_title = terminology.validate(db, data.get("icd_system", "ICD10"), data["icd_code"])
        except ValueError as e:
            raise HTTPException(400, str(e))
    c.ai_scribe_used = True
    ai_scribe.close(s, "accepted")
    audit.record(db, "scribe.accept", user=user, patient_id=s.patient_id, entity="consultation", entity_id=c.id,
                 detail={"scribe": s.id, "llm_model": s.llm_model}, ip=client_ip(request), commit=False)
    db.commit()
    return {"ok": True, "consultation_id": c.id}


@router.post("/scribe/{sid}/discard")
def discard(sid: int, request: Request, user: User = Depends(require("scribe")), db: Session = Depends(get_db)):
    s = _own_session(db, sid, user)
    ai_scribe.close(s, "discarded")
    audit.record(db, "scribe.discard", user=user, patient_id=s.patient_id, entity="scribe", entity_id=s.id,
                 ip=client_ip(request), commit=False)
    db.commit()
    return {"ok": True}
