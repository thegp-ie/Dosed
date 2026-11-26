"""Clinical inbox: Healthlink results/letters, matching and review (RFC DC.1.8.3, 2.0)."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..db import get_db
from ..integrations import healthlink
from ..models import InboxMessage, Patient, Task, User
from ..security import client_ip, require
from .common import get_patient, to_dict

router = APIRouter(prefix="/api/inbox", tags=["inbox"])

ACTIONS = {"normal", "no_action", "contact_patient", "book_appointment", "repeat_test", "discuss"}


def _patient_label(db, pid):
    if not pid:
        return None
    p = db.get(Patient, pid)
    return f"{p.last_name}, {p.first_name} ({p.dob:%d/%m/%Y})" if p else None


@router.get("")
def list_inbox(status: str = "new", provider: int | None = None, unmatched: bool = False,
               user: User = Depends(require("inbox.read")), db: Session = Depends(get_db)):
    """Filterable by the provider it is assigned to (DC.1.8.3.2)."""
    q = select(InboxMessage)
    if unmatched:
        q = q.where(InboxMessage.match_status == "unmatched")
    else:
        q = q.where(InboxMessage.status == status)
    if provider:
        q = q.where(InboxMessage.assigned_to == provider)
    rows = db.execute(q.order_by(InboxMessage.abnormal.desc(), InboxMessage.received_at.desc()).limit(200)).scalars()
    return [{**to_dict(m, exclude={"summary"}), "patient_label": _patient_label(db, m.patient_id),
             "title": (m.summary or "").split("\n")[0]} for m in rows]


@router.get("/{mid}")
def get_message(mid: int, request: Request, user: User = Depends(require("inbox.read")), db: Session = Depends(get_db)):
    m = db.get(InboxMessage, mid)
    if not m:
        raise HTTPException(404)
    audit.record(db, "inbox.view", user=user, patient_id=m.patient_id, entity="inbox", entity_id=m.id,
                 ip=client_ip(request))
    return {**to_dict(m), "patient_label": _patient_label(db, m.patient_id),
            "results": [to_dict(r) for r in m.results]}


@router.post("/{mid}/match")
def match(mid: int, data: dict, request: Request, user: User = Depends(require("inbox.read")),
          db: Session = Depends(get_db)):
    m = db.get(InboxMessage, mid)
    if not m:
        raise HTTPException(404)
    p = get_patient(db, int(data["patient_id"]))
    m.patient_id, m.match_status = p.id, "manual"
    m.assigned_to = m.assigned_to or p.usual_gp_id
    for r in m.results:
        r.patient_id = p.id
    audit.record(db, "inbox.match", user=user, patient_id=p.id, entity="inbox", entity_id=m.id,
                 ip=client_ip(request), commit=False)
    db.commit()
    return to_dict(m)


@router.post("/{mid}/review")
def review(mid: int, data: dict, request: Request, user: User = Depends(require("inbox.review")),
           db: Session = Depends(get_db)):
    """Clinician reviews and files a message into the record with an action."""
    m = db.get(InboxMessage, mid)
    if not m:
        raise HTTPException(404)
    if not m.patient_id:
        raise HTTPException(400, "Match this message to a patient first")
    action = data.get("action")
    if action not in ACTIONS:
        raise HTTPException(400, "Choose an action")
    m.action, m.review_comment = action, data.get("comment")
    m.reviewed_by, m.reviewed_at, m.status = user.id, datetime.now(timezone.utc), "filed"
    if action in ("contact_patient", "book_appointment", "repeat_test"):
        # Reception gets a task so the patient is actually contacted (DC.3.1).
        db.add(Task(patient_id=m.patient_id, title=f"{action.replace('_', ' ').capitalize()}: {(m.summary or '')[:120]}",
                    detail=data.get("comment"), assigned_to=data.get("assign_to"), created_by=user.id,
                    source=f"inbox:{m.id}"))
    audit.record(db, "inbox.review", user=user, patient_id=m.patient_id, entity="inbox", entity_id=m.id,
                 detail={"action": action}, ip=client_ip(request), commit=False)
    db.commit()
    return to_dict(m)


@router.post("/poll")
def poll(request: Request, user: User = Depends(require("inbox.read")), db: Session = Depends(get_db)):
    result = healthlink.poll(db)
    audit.record(db, "healthlink.poll", user=user, detail=result, ip=client_ip(request))
    return result


@router.post("/upload")
async def upload(request: Request, file: UploadFile = File(...), user: User = Depends(require("inbox.read")),
                 db: Session = Depends(get_db)):
    """Manually import an HL7 file (e.g. downloaded from Healthlink Online)."""
    raw = (await file.read()).decode("utf-8", errors="replace")
    try:
        m, _ = healthlink.ingest(db, raw, source="healthlink")
    except ValueError as e:
        raise HTTPException(400, f"Could not read HL7: {e}")
    return to_dict(m) if m else {"duplicate_or_ack": True}
