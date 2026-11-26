"""Data protection and practice governance: audit, GDPR rights, breaches, retention,
claims, private billing and reports (GDPR, Data Protection Act 2018, RFC IN.2, S.2)."""
from __future__ import annotations

import csv
import io
import json
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit, irish
from ..db import get_db
from ..models import (
    Addendum, Allergy, Appointment, AuditLog, BreachRecord, Carer, CdmReview, Claim, Consultation,
    DataSubjectRequest, Immunisation, InboxMessage, Invoice, LabResult, Observation, OutboundMessage,
    Patient, Prescription, PrescriptionItem, Problem, SickCert, User,
)
from ..security import client_ip, require
from .common import get_patient, parse_date, to_dict

router = APIRouter(prefix="/api", tags=["governance"])


def _aware(d):
    return d if d is None or d.tzinfo else d.replace(tzinfo=timezone.utc)


# --------------------------------------------------------------------------- audit

@router.get("/audit")
def audit_log(patient_id: int | None = None, user_id: int | None = None, action: str | None = None,
              limit: int = 200, user: User = Depends(require("audit.read")), db: Session = Depends(get_db)):
    q = select(AuditLog)
    if patient_id:
        q = q.where(AuditLog.patient_id == patient_id)
    if user_id:
        q = q.where(AuditLog.user_id == user_id)
    if action:
        q = q.where(AuditLog.action.startswith(action))
    return [to_dict(e) for e in db.execute(q.order_by(AuditLog.id.desc()).limit(min(limit, 2000))).scalars()]


@router.get("/audit/verify")
def audit_verify(user: User = Depends(require("audit.read")), db: Session = Depends(get_db)):
    return audit.verify_chain(db)


@router.get("/patients/{patient_id}/access-log")
def access_log(patient_id: int, user: User = Depends(require("governance")), db: Session = Depends(get_db)):
    """Who accessed this record: supports the patient's right of access (Art. 15) to
    information on recipients, and investigations of inappropriate access."""
    rows = db.execute(select(AuditLog).where(AuditLog.patient_id == patient_id).order_by(AuditLog.id.desc())).scalars()
    return [{"at": e.at.isoformat(), "user": e.username, "action": e.action} for e in rows]


# --------------------------------------------------------------- data subject rights

@router.get("/dsr")
def list_requests(user: User = Depends(require("governance")), db: Session = Depends(get_db)):
    out = []
    for r in db.execute(select(DataSubjectRequest).order_by(DataSubjectRequest.due_at)).scalars():
        d = to_dict(r)
        d["overdue"] = r.status in ("open", "extended") and r.due_at < date.today()
        out.append(d)
    return out


@router.post("/dsr")
def new_request(data: dict, request: Request, user: User = Depends(require("governance")), db: Session = Depends(get_db)):
    kind = data.get("request_type")
    if kind not in ("access", "rectification", "restriction", "objection", "portability", "erasure"):
        raise HTTPException(400, "Unknown request type")
    received = parse_date(data.get("received_at")) or date.today()
    # One calendar month (Art. 12(3)); approximated as 30 days, extendable by two months.
    r = DataSubjectRequest(patient_id=data.get("patient_id"), request_type=kind, received_at=received,
                           due_at=received + timedelta(days=30), identity_verified=bool(data.get("identity_verified")),
                           handled_by=user.id)
    db.add(r)
    db.flush()
    if kind == "restriction" and r.patient_id:
        get_patient(db, r.patient_id).processing_restricted = True
    audit.record(db, "dsr.create", user=user, patient_id=r.patient_id, entity="dsr", entity_id=r.id,
                 detail={"type": kind}, ip=client_ip(request), commit=False)
    db.commit()
    return to_dict(r)


@router.post("/dsr/{rid}/close")
def close_request(rid: int, data: dict, request: Request, user: User = Depends(require("governance")),
                  db: Session = Depends(get_db)):
    r = db.get(DataSubjectRequest, rid)
    if not r:
        raise HTTPException(404)
    if data.get("extend"):
        r.status, r.due_at = "extended", r.due_at + timedelta(days=60)
    else:
        r.status = data.get("status", "completed")
        r.outcome, r.closed_at = data.get("outcome"), datetime.now(timezone.utc)
        if r.request_type == "restriction" and r.patient_id:
            get_patient(db, r.patient_id).processing_restricted = False
    audit.record(db, "dsr.update", user=user, patient_id=r.patient_id, entity="dsr", entity_id=r.id,
                 detail={"status": r.status}, ip=client_ip(request), commit=False)
    db.commit()
    return to_dict(r)


def full_record(db: Session, p: Patient) -> dict:
    """Everything held about a patient, as JSON (Art. 15 access, Art. 20 portability,
    RFC IN.2.6 data portability / practice-to-practice transfer)."""
    def rows(model, **order):
        return [to_dict(x) for x in db.execute(select(model).where(model.patient_id == p.id)).scalars()]
    cons = []
    for c in db.execute(select(Consultation).where(Consultation.patient_id == p.id).order_by(Consultation.started_at)).scalars():
        d = to_dict(c)
        d["clinician"] = c.clinician.full_name
        d["addenda"] = [to_dict(a) for a in db.execute(select(Addendum).where(Addendum.consultation_id == c.id)).scalars()]
        cons.append(d)
    rx = []
    for r in db.execute(select(Prescription).where(Prescription.patient_id == p.id)).scalars():
        d = to_dict(r)
        d["items"] = [to_dict(i) for i in db.execute(select(PrescriptionItem).where(PrescriptionItem.prescription_id == r.id)).scalars()]
        rx.append(d)
    msgs = []
    for m in db.execute(select(InboxMessage).where(InboxMessage.patient_id == p.id)).scalars():
        d = to_dict(m, include={"raw"})
        d["results"] = [to_dict(x) for x in db.execute(select(LabResult).where(LabResult.inbox_message_id == m.id)).scalars()]
        msgs.append(d)
    pd = to_dict(p)
    pd["ihi_previous"] = None
    return {
        "format": "dosed-epr-record/1", "exported_at": datetime.now(timezone.utc).isoformat(),
        "patient": pd, "carers": rows(Carer), "allergies": rows(Allergy), "problems": rows(Problem),
        "consultations": cons, "observations": rows(Observation), "prescriptions": rx,
        "immunisations": rows(Immunisation), "appointments": rows(Appointment), "inbound_messages": msgs,
        "outbound_messages": rows(OutboundMessage), "sick_certs": rows(SickCert), "cdm_reviews": rows(CdmReview),
        "claims": rows(Claim),
    }


@router.get("/patients/{patient_id}/export")
def export_record(patient_id: int, request: Request, purpose: str = "access",
                  user: User = Depends(require("governance")), db: Session = Depends(get_db)):
    p = get_patient(db, patient_id)
    payload = full_record(db, p)
    audit.record(db, "patient.export", user=user, patient_id=p.id, detail={"purpose": purpose}, ip=client_ip(request))
    return Response(json.dumps(payload, indent=2, default=str), media_type="application/json",
                    headers={"Content-Disposition": f'attachment; filename="record-{p.id}.json"'})


# ------------------------------------------------------------------------ breaches

@router.get("/breaches")
def list_breaches(user: User = Depends(require("governance")), db: Session = Depends(get_db)):
    out = []
    now = datetime.now(timezone.utc)
    for b in db.execute(select(BreachRecord).order_by(BreachRecord.detected_at.desc())).scalars():
        d = to_dict(b)
        deadline = _aware(b.detected_at) + timedelta(hours=72)
        d["dpc_deadline"] = deadline.isoformat()
        d["dpc_overdue"] = b.dpc_notified_at is None and b.risk not in ("none",) and now > deadline
        out.append(d)
    return out


@router.post("/breaches")
def record_breach(data: dict, request: Request, user: User = Depends(require("governance")), db: Session = Depends(get_db)):
    if not data.get("description"):
        raise HTTPException(400, "Description required")
    detected = datetime.fromisoformat(data["detected_at"]) if data.get("detected_at") else datetime.now(timezone.utc)
    b = BreachRecord(detected_at=_aware(detected), description=data["description"],
                     data_categories=data.get("data_categories"), patients_affected=data.get("patients_affected"),
                     risk=data.get("risk", "unassessed"), actions=data.get("actions"), recorded_by=user.id)
    db.add(b)
    db.flush()
    audit.record(db, "breach.record", user=user, entity="breach", entity_id=b.id, ip=client_ip(request), commit=False)
    db.commit()
    return to_dict(b)


@router.patch("/breaches/{bid}")
def update_breach(bid: int, data: dict, request: Request, user: User = Depends(require("governance")),
                  db: Session = Depends(get_db)):
    b = db.get(BreachRecord, bid)
    if not b:
        raise HTTPException(404)
    for k in ("risk", "actions", "data_categories", "patients_affected"):
        if k in data:
            setattr(b, k, data[k])
    for k in ("dpc_notified_at", "patients_notified_at"):
        if data.get(k):
            setattr(b, k, _aware(datetime.fromisoformat(data[k])))
    audit.record(db, "breach.update", user=user, entity="breach", entity_id=b.id, ip=client_ip(request), commit=False)
    db.commit()
    return to_dict(b)


# ------------------------------------------------------------------------- reports

@router.get("/reports/retention")
def retention_report(user: User = Depends(require("governance")), db: Session = Depends(get_db)):
    """Inactive records past their minimum retention date, for GP review (RFC IN.2.1).
    Nothing is deleted automatically."""
    today = date.today()
    out = []
    for p in db.execute(select(Patient).where(Patient.record_status == "inactive")).scalars():
        until = irish.retention_until(dob=p.dob, last_contact=irish.to_date(p.last_contact_at) or p.left_practice_at,
                                      deceased=p.deceased_date)
        if until <= today:
            out.append({"id": p.id, "name": f"{p.last_name}, {p.first_name}", "dob": p.dob.isoformat(),
                        "retain_until": until.isoformat(), "deceased": bool(p.deceased_date)})
    return out


@router.post("/patients/{patient_id}/archive")
def archive(patient_id: int, data: dict, request: Request, user: User = Depends(require("governance")),
            db: Session = Depends(get_db)):
    """Mark a reviewed record as archived after the GP's retention decision."""
    p = get_patient(db, patient_id)
    if p.record_status != "inactive":
        raise HTTPException(400, "Only inactive records can be archived")
    p.record_status, p.retention_reviewed_at = "archived", datetime.now(timezone.utc)
    audit.record(db, "patient.archive", user=user, patient_id=p.id, detail={"note": data.get("note")},
                 ip=client_ip(request), commit=False)
    db.commit()
    return {"ok": True}


@router.get("/reports/incomplete")
def incomplete(user: User = Depends(require("reports")), db: Session = Depends(get_db)):
    """Records with minimum data but missing useful fields (DC.1.1.1.14)."""
    out = []
    for p in db.execute(select(Patient).where(Patient.record_status == "active")).scalars():
        missing = [f for f in ("phone_mobile", "eircode", "ppsn", "email") if not getattr(p, f)]
        if p.eligibility in ("gms", "dvc") and not p.gms_number:
            missing.append("gms_number")
        if missing:
            out.append({"id": p.id, "name": f"{p.last_name}, {p.first_name}", "missing": missing})
    return out


@router.get("/reports/cervical-screening")
def cervical(user: User = Depends(require("reports")), db: Session = Depends(get_db)):
    """Women 25-65 with no recorded cervical screening (RFC 2.1.3). Screening is
    recognised by an inbox result or observation mentioning cervical/HPV/smear."""
    today = date.today()
    out = []
    for p in db.execute(select(Patient).where(Patient.record_status == "active", Patient.sex == "female")).scalars():
        age = irish.age_on(p.dob, today)
        if not 25 <= age <= 65:
            continue
        screened = db.execute(select(func.count()).select_from(LabResult).where(
            LabResult.patient_id == p.id,
            func.lower(LabResult.test_name).like("%cervical%") | func.lower(LabResult.test_name).like("%hpv%")
            | func.lower(LabResult.test_name).like("%smear%"))).scalar()
        if not screened:
            out.append({"id": p.id, "name": f"{p.last_name}, {p.first_name}", "age": age,
                        "phone_mobile": p.phone_mobile})
    return out


@router.get("/reports/cdm-due")
def cdm_due(user: User = Depends(require("reports")), db: Session = Depends(get_db)):
    """Patients on a CDM register who are due a review (RFC 2.5.10, 2.12.12)."""
    out = []
    probs = db.execute(select(Problem).where(Problem.status == "active", Problem.icpc2_code.is_not(None))).scalars().all()
    by_patient: dict[int, list[str]] = {}
    for x in probs:
        by_patient.setdefault(x.patient_id, []).append(x.icpc2_code)
    for pid, codes in by_patient.items():
        regs = irish.cdm_registers_for(codes)
        if not regs:
            continue
        p = db.get(Patient, pid)
        if not p or p.record_status != "active" or irish.age_on(p.dob) < 18:
            continue
        last = db.execute(select(CdmReview).where(CdmReview.patient_id == pid)
                          .order_by(CdmReview.review_date.desc()).limit(1)).scalar_one_or_none()
        if last and last.status == "started":
            status = "orange"
        elif last and last.next_due and last.next_due > date.today():
            continue
        else:
            status = "red"
        out.append({"id": pid, "name": f"{p.last_name}, {p.first_name}", "registers": regs, "status": status,
                    "eligibility": p.eligibility})
    return out


@router.get("/reports/activity")
def activity(start: str | None = None, end: str | None = None, user: User = Depends(require("reports")),
             db: Session = Depends(get_db)):
    """Consultations by clinician and mode (S.2.1.2)."""
    s = parse_date(start) or date.today().replace(day=1)
    e = parse_date(end) or date.today()
    rows = db.execute(
        select(User.full_name, Consultation.mode, func.count())
        .join(User, User.id == Consultation.clinician_id)
        .where(Consultation.started_at >= datetime(s.year, s.month, s.day, tzinfo=timezone.utc),
               Consultation.started_at < datetime(e.year, e.month, e.day, tzinfo=timezone.utc) + timedelta(days=1),
               Consultation.entered_in_error.is_(False))
        .group_by(User.full_name, Consultation.mode)).all()
    return [{"clinician": r[0], "mode": r[1], "count": r[2]} for r in rows]


# -------------------------------------------------------------- claims and billing

@router.get("/claims")
def list_claims(status: str = "pending", user: User = Depends(require("claims.write")), db: Session = Depends(get_db)):
    return [to_dict(c) for c in db.execute(select(Claim).where(Claim.status == status).order_by(Claim.service_date)).scalars()]


@router.post("/claims")
def add_claim(data: dict, request: Request, user: User = Depends(require("claims.write")), db: Session = Depends(get_db)):
    p = get_patient(db, int(data["patient_id"]))
    c = Claim(patient_id=p.id, claim_type=data["claim_type"], service_date=parse_date(data.get("service_date")) or date.today(),
              clinician_id=int(data.get("clinician_id") or user.id), notes=data.get("notes"))
    db.add(c)
    db.flush()
    audit.record(db, "claim.add", user=user, patient_id=p.id, entity="claim", entity_id=c.id, ip=client_ip(request), commit=False)
    db.commit()
    return to_dict(c)


@router.get("/claims/export.csv")
def export_claims(user: User = Depends(require("claims.write")), db: Session = Depends(get_db)):
    """Pending claims as CSV for entry on the PCRS portal until claims are submitted
    electronically via Healthlink."""
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["claim_id", "type", "service_date", "gms_number", "surname", "first_name", "dob", "clinician"])
    for c in db.execute(select(Claim).where(Claim.status == "pending")).scalars():
        p = db.get(Patient, c.patient_id)
        w.writerow([c.id, c.claim_type, c.service_date.isoformat(), p.gms_number or "", p.last_name, p.first_name,
                    p.dob.strftime("%d/%m/%Y"), db.get(User, c.clinician_id).full_name])
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="claims.csv"'})


@router.post("/patients/{patient_id}/invoices")
def add_invoice(patient_id: int, data: dict, request: Request, user: User = Depends(require("billing")),
                db: Session = Depends(get_db)):
    p = get_patient(db, patient_id)
    try:
        cents = round(float(data["amount"]) * 100)
    except (KeyError, ValueError):
        raise HTTPException(400, "Amount required")
    inv = Invoice(patient_id=p.id, description=data.get("description") or "Consultation", amount_cents=cents,
                  paid_cents=round(float(data.get("paid") or 0) * 100), method=data.get("method"), created_by=user.id)
    db.add(inv)
    db.flush()
    audit.record(db, "invoice.add", user=user, patient_id=p.id, entity="invoice", entity_id=inv.id,
                 ip=client_ip(request), commit=False)
    db.commit()
    return to_dict(inv)
