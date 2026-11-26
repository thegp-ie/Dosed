"""Appointments and remote (video/phone) consultations (RFC S.1.9, S.3.1.4)."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..config import settings
from ..db import get_db
from ..integrations import telehealth
from ..models import Appointment, Consultation, User
from ..security import client_ip, require
from .common import get_patient, parse_date, to_dict

router = APIRouter(tags=["appointments"])


def _aware(d):
    return d if d is None or d.tzinfo else d.replace(tzinfo=timezone.utc)


def _row(a: Appointment) -> dict:
    d = to_dict(a)
    d["patient_name"] = f"{a.patient.last_name}, {a.patient.first_name}"
    d["clinician_name"] = a.clinician.full_name
    return d


@router.get("/api/appointments")
def day_list(day: str | None = None, clinician_id: int | None = None,
             user: User = Depends(require("appointment.read")), db: Session = Depends(get_db)):
    d = parse_date(day) or date.today()
    start = datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
    q = select(Appointment).where(Appointment.start >= start, Appointment.start < start + timedelta(days=1))
    if clinician_id:
        q = q.where(Appointment.clinician_id == clinician_id)
    return [_row(a) for a in db.execute(q.order_by(Appointment.start)).scalars()]


@router.post("/api/appointments")
def book(data: dict, request: Request, user: User = Depends(require("appointment.write")), db: Session = Depends(get_db)):
    p = get_patient(db, int(data["patient_id"]))
    try:
        start = datetime.fromisoformat(data["start"])
    except (KeyError, ValueError):
        raise HTTPException(400, "Start time required")
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    mode = data.get("mode", "surgery")
    if mode not in ("surgery", "phone", "video"):
        raise HTTPException(400, "Mode must be surgery, phone or video")
    if mode == "video" and not p.consent_video:
        raise HTTPException(400, "Record the patient's consent to video consultations on their record first")
    if mode == "video" and not (p.phone_mobile or p.email):
        raise HTTPException(400, "Patient needs a mobile number or email to receive the video link")
    a = Appointment(patient_id=p.id, clinician_id=int(data.get("clinician_id") or user.id), start=start,
                    duration_minutes=int(data.get("duration_minutes") or 15), mode=mode, reason=data.get("reason"))
    db.add(a)
    db.flush()
    audit.record(db, "appointment.book", user=user, patient_id=p.id, entity="appointment", entity_id=a.id,
                 detail={"mode": mode}, ip=client_ip(request), commit=False)
    db.commit()
    db.refresh(a)
    return _row(a)


@router.post("/api/appointments/{aid}/status")
def set_status(aid: int, data: dict, request: Request, user: User = Depends(require("appointment.write")),
               db: Session = Depends(get_db)):
    a = db.get(Appointment, aid)
    if not a:
        raise HTTPException(404)
    if data.get("status") not in ("booked", "arrived", "in_progress", "done", "dna", "cancelled"):
        raise HTTPException(400, "Bad status")
    a.status = data["status"]
    audit.record(db, "appointment.status", user=user, patient_id=a.patient_id, entity="appointment", entity_id=a.id,
                 detail={"status": a.status}, ip=client_ip(request), commit=False)
    db.commit()
    return _row(a)


@router.post("/api/appointments/{aid}/video")
def start_video(aid: int, request: Request, user: User = Depends(require("telehealth.host")),
                db: Session = Depends(get_db)):
    """Create the room and a single-use patient link; return the clinician's join URL.

    The patient link is shown so reception or the clinician can send it by SMS/email
    using the patient's recorded consent. The link expires after the slot (+2h).
    """
    a = db.get(Appointment, aid)
    if not a or a.mode != "video":
        raise HTTPException(400, "Not a video appointment")
    if not a.video_room:
        a.video_room = telehealth.new_room_name()
    token, token_hash = telehealth.new_patient_link()
    a.patient_link_hash = token_hash
    a.patient_link_expires = _aware(a.start) + timedelta(minutes=a.duration_minutes) + timedelta(hours=2)
    a.status = "in_progress"
    try:
        clinician_url = telehealth.room_url(a.video_room, telehealth.jitsi_token(a.video_room, user.full_name, True))
    except RuntimeError as e:
        raise HTTPException(500, str(e))
    # Pre-open a consultation note marked as video.
    c = db.execute(select(Consultation).where(Consultation.appointment_id == a.id)).scalar_one_or_none()
    if not c:
        c = Consultation(patient_id=a.patient_id, clinician_id=user.id, appointment_id=a.id, mode="video")
        db.add(c)
    db.flush()
    audit.record(db, "telehealth.start", user=user, patient_id=a.patient_id, entity="appointment", entity_id=a.id,
                 ip=client_ip(request), commit=False)
    db.commit()
    return {"clinician_url": clinician_url, "patient_url": telehealth.patient_join_url(token),
            "consultation_id": c.id, "expires": a.patient_link_expires.isoformat()}


_JOIN_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Video consultation</title>
<style>body{{font-family:system-ui,sans-serif;max-width:34rem;margin:3rem auto;padding:0 1rem;line-height:1.5;color:#1b2733}}
a.btn{{display:inline-block;background:#0b5c7a;color:#fff;padding:.8rem 1.4rem;border-radius:8px;text-decoration:none}}
.small{{color:#4b5b6b;font-size:.9rem}}</style></head><body>
<h1>{practice}</h1><p>Your video consultation is ready.</p>
<ul><li>Find a private, quiet place.</li><li>Have your medication and any questions to hand.</li>
<li>You will wait in a lobby until the doctor or nurse lets you in.</li></ul>
<p class="small">By continuing you agree to a video consultation. It is not recorded. If you would prefer a phone call or
to be seen in person, please ring the practice. In an emergency call 999 or 112.</p>
<p><a class="btn" href="{url}">Join the consultation</a></p></body></html>"""


@router.get("/v/{token}", response_class=HTMLResponse)
def patient_join(token: str, request: Request, db: Session = Depends(get_db)):
    a = db.execute(select(Appointment).where(Appointment.patient_link_hash == telehealth.hash_link_token(token))).scalar_one_or_none()
    if not a or not a.patient_link_expires or _aware(a.patient_link_expires) < datetime.now(timezone.utc):
        return HTMLResponse("<p>This link has expired. Please contact the practice.</p>", status_code=410)
    a.patient_joined_at = datetime.now(timezone.utc)
    audit.record(db, "telehealth.patient_join", patient_id=a.patient_id, entity="appointment", entity_id=a.id,
                 ip=client_ip(request), commit=False)
    db.commit()
    url = telehealth.room_url(a.video_room, telehealth.jitsi_token(a.video_room, a.patient.first_name, False))
    return HTMLResponse(_JOIN_PAGE.format(practice=settings.practice_name, url=url.replace("&", "&amp;")),
                        headers={"Referrer-Policy": "no-referrer", "Cache-Control": "no-store",
                                 "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; "
                                                            "frame-ancestors 'none'"})
