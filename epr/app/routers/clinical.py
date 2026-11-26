"""Consultations, prescribing, referrals, sick certs, CDM reviews, Healthmail and tasks."""
from __future__ import annotations

import base64
import json
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit, irish
from ..config import settings
from ..db import get_db
from ..integrations import healthlink, healthmail, hl7
from ..integrations.documents import prescription_pdf, sick_cert_pdf
from ..models import (
    Addendum, Allergy, CdmReview, Claim, Consultation, Observation, OutboundMessage, Prescription,
    PrescriptionItem, Problem, SickCert, Task, User,
)
from ..security import PRESCRIBER_ROLES, client_ip, current_user, require
from .common import get_patient, parse_date, to_dict

router = APIRouter(prefix="/api", tags=["clinical"])

EDIT_WINDOW = timedelta(hours=12)  # RFC DC.1.1.1.18


def _aware(d: datetime) -> datetime:
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _touch(p):
    p.last_contact_at = datetime.now(timezone.utc)


# ----------------------------------------------------------------- consultations

NOTE_FIELDS = ("subjective", "objective", "assessment", "plan", "icpc2_code", "mode",
               "remote_consent_recorded", "remote_identity_verified")


def _check_remote(c: Consultation) -> None:
    if c.mode in ("phone", "video") and c.signed_at and not (c.remote_consent_recorded and c.remote_identity_verified):
        raise HTTPException(400, "For a remote consultation, record the patient's consent and that you confirmed their identity")


@router.post("/patients/{patient_id}/consultations")
def new_consultation(patient_id: int, data: dict, request: Request, user: User = Depends(require("clinical.write")),
                     db: Session = Depends(get_db)):
    p = get_patient(db, patient_id)
    code = (data.get("icpc2_code") or "").upper() or None
    if code and code not in irish.ICPC2:
        raise HTTPException(400, "Unknown ICPC-2 code")
    c = Consultation(patient_id=p.id, clinician_id=user.id, appointment_id=data.get("appointment_id"))
    for k in NOTE_FIELDS:
        if k in data:
            setattr(c, k, data[k])
    c.icpc2_code = code
    if data.get("sign"):
        c.signed_at = datetime.now(timezone.utc)
        _check_remote(c)
    db.add(c)
    db.flush()
    if data.get("add_problem") and code:
        db.add(Problem(patient_id=p.id, icpc2_code=code, description=irish.ICPC2[code], recorded_by=user.id))
    _touch(p)
    audit.record(db, "consultation.create", user=user, patient_id=p.id, entity="consultation", entity_id=c.id,
                 detail={"mode": c.mode}, ip=client_ip(request), commit=False)
    db.commit()
    return to_dict(c)


@router.patch("/consultations/{cid}")
def edit_consultation(cid: int, data: dict, request: Request, user: User = Depends(require("clinical.write")),
                      db: Session = Depends(get_db)):
    c = db.get(Consultation, cid)
    if not c:
        raise HTTPException(404)
    if c.clinician_id != user.id:
        raise HTTPException(403, "Only the author can edit a note; add an addendum instead")
    if c.signed_at or datetime.now(timezone.utc) - _aware(c.started_at) > EDIT_WINDOW:
        raise HTTPException(409, "This note is locked; add an addendum instead")
    for k in NOTE_FIELDS:
        if k in data:
            setattr(c, k, data[k])
    if c.icpc2_code:
        c.icpc2_code = c.icpc2_code.upper()
        if c.icpc2_code not in irish.ICPC2:
            raise HTTPException(400, "Unknown ICPC-2 code")
    if data.get("sign"):
        c.signed_at = datetime.now(timezone.utc)
        _check_remote(c)
    audit.record(db, "consultation.edit", user=user, patient_id=c.patient_id, entity="consultation", entity_id=c.id,
                 detail={"signed": bool(c.signed_at)}, ip=client_ip(request), commit=False)
    db.commit()
    return to_dict(c)


@router.post("/consultations/{cid}/addenda")
def add_addendum(cid: int, data: dict, request: Request, user: User = Depends(require("clinical.write")),
                 db: Session = Depends(get_db)):
    c = db.get(Consultation, cid)
    if not c or not data.get("text"):
        raise HTTPException(400, "Text required")
    a = Addendum(consultation_id=c.id, user_id=user.id, text=data["text"])
    db.add(a)
    db.flush()
    audit.record(db, "consultation.addendum", user=user, patient_id=c.patient_id, entity="consultation",
                 entity_id=c.id, ip=client_ip(request), commit=False)
    db.commit()
    return to_dict(a)


@router.post("/consultations/{cid}/entered-in-error")
def consultation_error(cid: int, data: dict, request: Request, user: User = Depends(require("clinical.write")),
                       db: Session = Depends(get_db)):
    """Mark as erroneous (DC.1.1.1.6) and optionally move to the correct patient (DC.1.1.1.7).

    The note is never deleted: it stays visible, struck through, with the reason.
    """
    c = db.get(Consultation, cid)
    if not c:
        raise HTTPException(404)
    reason = (data.get("reason") or "").strip()
    if not reason:
        raise HTTPException(400, "Reason required")
    move_to = data.get("move_to_patient_id")
    if move_to:
        target = get_patient(db, int(move_to))
        old = c.patient_id
        c.patient_id = target.id
        audit.record(db, "consultation.moved", user=user, patient_id=old, entity="consultation", entity_id=c.id,
                     detail={"to_patient": target.id, "reason": reason}, ip=client_ip(request), commit=False)
    else:
        c.entered_in_error, c.error_reason = True, reason
        audit.record(db, "consultation.entered_in_error", user=user, patient_id=c.patient_id, entity="consultation",
                     entity_id=c.id, detail={"reason": reason}, ip=client_ip(request), commit=False)
    db.commit()
    return to_dict(c)


# ------------------------------------------------------------------- prescribing

def _safety_checks(db: Session, patient_id: int, items: list[dict]) -> list[str]:
    """Allergy and duplicate checks.

    Drug-drug interaction checking (RFC DC.2.3.1.1) needs a licensed drug knowledge base
    (e.g. an Irish formulary product). Plug it in here; until then only these checks run.
    """
    warnings = []
    allergies = db.execute(select(Allergy).where(Allergy.patient_id == patient_id)).scalars().all()
    for it in items:
        name = (it.get("drug_name") or "").lower()
        for a in allergies:
            if a.substance and (a.substance.lower() in name or name.split(" ")[0] in a.substance.lower()):
                warnings.append(f"ALLERGY: patient has recorded allergy to {a.substance} ({a.reaction or 'reaction not recorded'})")
    names = [(i.get("drug_name") or "").lower().split(" ")[0] for i in items]
    for n in set(names):
        if n and names.count(n) > 1:
            warnings.append(f"Duplicate item: {n}")
    return warnings


@router.post("/patients/{patient_id}/prescriptions")
def new_prescription(patient_id: int, data: dict, request: Request, user: User = Depends(require("clinical.write")),
                     db: Session = Depends(get_db)):
    """Any clinical user can draft; only a prescriber can issue or send (RFC 2.10)."""
    p = get_patient(db, patient_id)
    items = data.get("items") or []
    if not items:
        raise HTTPException(400, "Add at least one item")
    for i in items:
        if not (i.get("drug_name") and i.get("dose_instructions") and i.get("quantity")):
            raise HTTPException(400, "Each item needs a drug, dose and quantity (RFC 2.10.6)")
        if i.get("cd_schedule") and i["cd_schedule"] not in ("CD1", "CD2", "CD3", "CD4", "CD5"):
            raise HTTPException(400, "Unknown controlled drug schedule")
    warnings = _safety_checks(db, p.id, items)
    if warnings and not data.get("acknowledge_warnings"):
        return {"warnings": warnings, "saved": False}
    prescriber_id = user.id if user.role in PRESCRIBER_ROLES else data.get("prescriber_id")
    if not prescriber_id:
        raise HTTPException(400, "Choose the prescriber who will review this prescription")
    rx = Prescription(patient_id=p.id, prescriber_id=prescriber_id, consultation_id=data.get("consultation_id"),
                      pharmacy_healthmail=data.get("pharmacy_healthmail") or p.preferred_pharmacy_healthmail)
    for i in items:
        rx.items.append(PrescriptionItem(
            drug_name=i["drug_name"], strength=i.get("strength"), form=i.get("form"),
            dose_instructions=i["dose_instructions"], quantity=str(i["quantity"]),
            repeats=int(i.get("repeats") or 0), is_repeat_medication=bool(i.get("is_repeat_medication")),
            cd_schedule=i.get("cd_schedule") or None, is_ost=bool(i.get("is_ost")),
            generic_substitution_allowed=i.get("generic_substitution_allowed", True)))
    db.add(rx)
    db.flush()
    _touch(p)
    audit.record(db, "prescription.draft", user=user, patient_id=p.id, entity="prescription", entity_id=rx.id,
                 detail={"items": [i["drug_name"] for i in items], "warnings_acknowledged": warnings},
                 ip=client_ip(request), commit=False)
    db.commit()
    return {"saved": True, "warnings": warnings, "prescription": {**to_dict(rx), "items": [to_dict(i) for i in rx.items]}}


def _rx(db, rx_id) -> Prescription:
    rx = db.get(Prescription, rx_id)
    if not rx:
        raise HTTPException(404)
    return rx


@router.post("/prescriptions/{rx_id}/issue")
def issue_prescription(rx_id: int, request: Request, user: User = Depends(require("prescribe")),
                       db: Session = Depends(get_db)):
    rx = _rx(db, rx_id)
    if rx.status not in ("draft",):
        raise HTTPException(409, f"Prescription is {rx.status}")
    rx.prescriber_id, rx.status = user.id, "issued"
    audit.record(db, "prescription.issue", user=user, patient_id=rx.patient_id, entity="prescription",
                 entity_id=rx.id, ip=client_ip(request), commit=False)
    db.commit()
    return to_dict(rx)


@router.get("/prescriptions/{rx_id}/pdf")
def prescription_document(rx_id: int, request: Request, user: User = Depends(require("clinical.read")),
                          db: Session = Depends(get_db)):
    rx = _rx(db, rx_id)
    p = get_patient(db, rx.patient_id)
    pdf = prescription_pdf(prescription=rx, patient=p, prescriber=rx.prescriber, via_healthmail=False)
    audit.record(db, "prescription.print", user=user, patient_id=p.id, entity="prescription", entity_id=rx.id,
                 ip=client_ip(request))
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="prescription-{rx.id}.pdf"'})


@router.post("/prescriptions/{rx_id}/send-healthmail")
def send_prescription(rx_id: int, data: dict, request: Request, user: User = Depends(require("prescription.send")),
                      db: Session = Depends(get_db)):
    """Electronic prescription transfer to a pharmacy (RFC 2.10). Only via Healthmail,
    only by a licensed prescriber who is signed in, never for OST."""
    rx = _rx(db, rx_id)
    p = get_patient(db, rx.patient_id)
    if rx.status not in ("draft", "issued"):
        raise HTTPException(409, f"Prescription is {rx.status}")
    if any(i.is_ost for i in rx.items):
        raise HTTPException(400, "Opiate Substitution Treatment prescriptions cannot be sent by electronic "
                                 "transfer. Write it on the proper pad; a scan may then be sent via Healthmail.")
    if any(i.cd_schedule in ("CD2", "CD3") for i in rx.items) and not data.get("confirm_cd"):
        raise HTTPException(400, "This contains a Schedule 2/3 controlled drug. Confirm that electronic "
                                 "transfer is permitted under current PSI/Department of Health rules.")
    to = data.get("pharmacy_healthmail") or rx.pharmacy_healthmail
    if not to:
        raise HTTPException(400, "Pharmacy Healthmail address required")
    if not (user.healthmail_address and user.healthmail_secret):
        raise HTTPException(400, "Link your own Healthmail account first (Settings)")
    rx.prescriber_id = user.id
    pdf = prescription_pdf(prescription=rx, patient=p, prescriber=user, via_healthmail=True)
    try:
        msg = healthmail.build_message(
            sender=user.healthmail_address, to=[to],
            subject=f"Prescription for {p.first_name} {p.last_name} DOB {p.dob:%d/%m/%Y}",
            body=f"Please find attached a prescription from {user.full_name}"
                 f"{' (IMC ' + user.mcrn + ')' if user.mcrn else ''}, {settings.practice_name}.",
            attachments=[healthmail.Attachment(f"prescription-{rx.id}.pdf", pdf)])
    except healthmail.HealthmailError as e:
        raise HTTPException(400, str(e))
    out = OutboundMessage(channel="healthmail", kind="prescription", recipient=to, subject=msg["Subject"],
                          patient_id=p.id, created_by=user.id)
    db.add(out)
    try:
        healthmail.send(msg, user.healthmail_address, user.healthmail_secret)
        out.status, rx.status, rx.sent_at, rx.sent_via, rx.pharmacy_healthmail = \
            "sent", "sent", datetime.now(timezone.utc), "healthmail", to
    except healthmail.HealthmailError as e:
        out.status, out.error = "failed", str(e)
    db.flush()
    # Auditable trace of who was signed in when the prescription was sent (RFC 2.10.4).
    audit.record(db, "prescription.send_healthmail", user=user, patient_id=p.id, entity="prescription",
                 entity_id=rx.id, detail={"to": to, "status": out.status, "ip": client_ip(request)},
                 ip=client_ip(request), commit=False)
    db.commit()
    if out.status != "sent":
        raise HTTPException(502, out.error)
    return {"ok": True, "status": rx.status}


@router.post("/prescriptions/{rx_id}/cancel")
def cancel_prescription(rx_id: int, data: dict, request: Request, user: User = Depends(require("prescribe")),
                        db: Session = Depends(get_db)):
    rx = _rx(db, rx_id)
    rx.status = "cancelled"
    rx.entered_in_error = bool(data.get("entered_in_error"))
    audit.record(db, "prescription.cancel", user=user, patient_id=rx.patient_id, entity="prescription",
                 entity_id=rx.id, detail={"reason": data.get("reason")}, ip=client_ip(request), commit=False)
    db.commit()
    return to_dict(rx)


# --------------------------------------------------------------------- Healthmail

@router.post("/patients/{patient_id}/healthmail")
def send_healthmail(patient_id: int, data: dict, request: Request, user: User = Depends(require("healthmail.send")),
                    db: Session = Depends(get_db)):
    """Secure letter from within the patient record (RFC 2.9). Attachments as base64."""
    p = get_patient(db, patient_id)
    if not (user.healthmail_address and user.healthmail_secret):
        raise HTTPException(400, "Link your own Healthmail account first (Settings)")
    to = [t.strip() for t in (data.get("to") or "").split(",") if t.strip()]
    ident = (f"Patient: {p.first_name} {p.last_name}, DOB {p.dob:%d/%m/%Y}, "
             + ", ".join(x for x in (p.address1, p.address2, p.town, p.eircode) if x)
             + (f", IHI {irish.ihi_display(p.ihi)}" if p.ihi else ""))
    files = []
    for a in data.get("attachments") or []:
        try:
            files.append(healthmail.Attachment(a["filename"], base64.b64decode(a["content_b64"]),
                                               a.get("mime", "application/octet-stream")))
        except (KeyError, ValueError):
            raise HTTPException(400, "Bad attachment")
    try:
        msg = healthmail.build_message(sender=user.healthmail_address, to=to,
                                       subject=data.get("subject") or f"Re: {p.first_name} {p.last_name}",
                                       body=ident + "\n\n" + (data.get("body") or ""), attachments=files)
    except healthmail.HealthmailError as e:
        raise HTTPException(400, str(e))
    out = OutboundMessage(channel="healthmail", kind=data.get("kind", "letter"), recipient=", ".join(to),
                          subject=msg["Subject"], patient_id=p.id, created_by=user.id, payload=data.get("body"))
    db.add(out)
    try:
        healthmail.send(msg, user.healthmail_address, user.healthmail_secret)
        out.status = "sent"
    except healthmail.HealthmailError as e:
        out.status, out.error = "failed", str(e)
    db.flush()
    audit.record(db, "healthmail.send", user=user, patient_id=p.id, entity="outbound", entity_id=out.id,
                 detail={"to": to, "status": out.status, "attachments": [f.filename for f in files]},
                 ip=client_ip(request), commit=False)
    db.commit()
    if out.status != "sent":
        raise HTTPException(502, out.error)
    return to_dict(out)


# ---------------------------------------------------------------------- referrals

@router.post("/patients/{patient_id}/referrals")
def send_referral(patient_id: int, data: dict, request: Request, user: User = Depends(require("referral.send")),
                  db: Session = Depends(get_db)):
    """General eReferral via Healthlink (RFC 2.8). Message built as REF^I12 (HL7 v2.4 XML)."""
    p = get_patient(db, patient_id)
    t = healthlink.transport()
    if not t:
        raise HTTPException(400, "Healthlink is not enabled")
    if not data.get("receiving_facility") or not data.get("reason"):
        raise HTTPException(400, "Hospital and reason for referral required")
    problems = db.execute(select(Problem).where(Problem.patient_id == p.id, Problem.status == "active")).scalars().all()
    allergies = db.execute(select(Allergy).where(Allergy.patient_id == p.id)).scalars().all()
    ids = []
    if p.ihi:
        ids.append({"id": p.ihi, "type": "IHI"})  # full 18 digits when transmitting (RFC 2.7.5)
    if p.ppsn:
        ids.append({"id": p.ppsn, "type": "PPSN"})
    if p.gms_number:
        ids.append({"id": p.gms_number, "type": "GMS"})
    sections = [("Reason for referral", data["reason"])]
    if data.get("history"):
        sections.append(("History", data["history"]))
    sections.append(("Problems", "; ".join(f"{x.icpc2_code or ''} {x.description}".strip() for x in problems) or "None recorded"))
    sections.append(("Allergies", "; ".join(a.substance for a in allergies) or "No known allergies recorded"))
    if data.get("medications"):
        sections.append(("Medications", data["medications"]))
    cid, xml = hl7.build_referral_xml(
        practice={"healthlink_id": settings.practice_healthlink_id},
        gp={"name": user.full_name, "mcrn": user.mcrn or ""},
        patient={"family": p.last_name, "given": p.first_name, "dob": p.dob, "sex": p.sex, "ids": ids,
                 "address1": p.address1, "address2": p.address2, "town": p.town, "county": p.county,
                 "eircode": p.eircode},
        referral={"receiving_facility": data["receiving_facility"], "priority": data.get("priority", "R"),
                  "type": data.get("type", "GEN"), "specialty": data.get("specialty", ""), "sections": sections})
    t.send(f"REF_{cid}.xml", xml)
    out = OutboundMessage(channel="healthlink", kind="referral", recipient=data["receiving_facility"], subject=cid,
                          patient_id=p.id, created_by=user.id, status="sent", payload=xml)
    db.add(out)
    db.flush()
    audit.record(db, "referral.send", user=user, patient_id=p.id, entity="outbound", entity_id=out.id,
                 detail={"to": data["receiving_facility"], "control_id": cid}, ip=client_ip(request), commit=False)
    db.commit()
    return to_dict(out)


@router.get("/patients/{patient_id}/outbound")
def outbound_log(patient_id: int, user: User = Depends(require("clinical.read")), db: Session = Depends(get_db)):
    rows = db.execute(select(OutboundMessage).where(OutboundMessage.patient_id == patient_id)
                      .order_by(OutboundMessage.created_at.desc())).scalars()
    return [to_dict(o, exclude={"payload"}) for o in rows]


# ---------------------------------------------------------------------- sick certs

@router.post("/patients/{patient_id}/sick-certs")
def new_sick_cert(patient_id: int, data: dict, request: Request, user: User = Depends(require("sickcert.write")),
                  db: Session = Depends(get_db)):
    p = get_patient(db, patient_id)
    try:
        weeks = int(data.get("weeks"))
    except (TypeError, ValueError):
        raise HTTPException(400, "Number of weeks required")
    if not 1 <= weeks <= 52:
        raise HTTPException(400, "Weeks must be 1-52")
    if not data.get("illness_text"):
        raise HTTPException(400, "Illness required")
    cert = SickCert(patient_id=p.id, clinician_id=user.id, cert_type=data.get("cert_type", "first"),
                    illness_code_system=data.get("illness_code_system", "ICPC2"),
                    illness_code=data.get("illness_code"), illness_text=data["illness_text"],
                    date_from=parse_date(data.get("date_from")) or date.today(), weeks=weeks,
                    message_status="queued")
    db.add(cert)
    db.flush()
    end = cert.date_from + timedelta(weeks=weeks) - timedelta(days=1)
    # Log in the clinical notes (RFC 2.11.5).
    db.add(Consultation(patient_id=p.id, clinician_id=user.id, mode="surgery", signed_at=datetime.now(timezone.utc),
                        plan=f"Medical certificate ({cert.cert_type}) {cert.date_from:%d/%m/%Y}–{end:%d/%m/%Y}: "
                             f"{cert.illness_text}", icpc2_code=cert.illness_code if cert.illness_code_system == "ICPC2" and cert.illness_code in irish.ICPC2 else None))
    audit.record(db, "sickcert.create", user=user, patient_id=p.id, entity="sick_cert", entity_id=cert.id,
                 ip=client_ip(request), commit=False)
    db.commit()
    return to_dict(cert)


@router.get("/sick-certs/{cert_id}/pdf")
def sick_cert_document(cert_id: int, request: Request, user: User = Depends(require("clinical.read")),
                       db: Session = Depends(get_db)):
    cert = db.get(SickCert, cert_id)
    if not cert:
        raise HTTPException(404)
    p = get_patient(db, cert.patient_id)
    pdf = sick_cert_pdf(cert=cert, patient=p, clinician=db.get(User, cert.clinician_id))
    audit.record(db, "sickcert.print", user=user, patient_id=p.id, entity="sick_cert", entity_id=cert.id,
                 ip=client_ip(request))
    return Response(pdf, media_type="application/pdf")


# ----------------------------------------------------------------------------- CDM

@router.get("/patients/{patient_id}/cdm/prefill")
def cdm_prefill(patient_id: int, user: User = Depends(require("clinical.read")), db: Session = Depends(get_db)):
    """Auto-populate a review from data recorded in the last 6 months (RFC 2.12.3-4)."""
    p = get_patient(db, patient_id)
    since = datetime.now(timezone.utc) - timedelta(days=183)
    probs = db.execute(select(Problem).where(Problem.patient_id == p.id, Problem.status == "active")).scalars().all()
    regs = irish.cdm_registers_for([x.icpc2_code for x in probs if x.icpc2_code])
    data: dict = {}
    obs = db.execute(select(Observation).where(Observation.patient_id == p.id)
                     .order_by(Observation.taken_at.desc())).scalars().all()
    for o in obs:
        if o.kind in irish.CDM_AUTOPOPULATE and o.kind not in data and _aware(o.taken_at) >= since:
            data[o.kind] = o.value
    if data.get("weight_kg") and data.get("height_cm"):
        try:
            data["bmi"] = irish.bmi(data["weight_kg"], data["height_cm"])
        except ValueError:
            pass
    if "af" in regs:
        codes = {x.icpc2_code for x in probs}
        data["cha2ds2_vasc"] = irish.cha2ds2_vasc(
            age=irish.age_on(p.dob), sex=p.sex, chf="K77" in codes, hypertension=bool(codes & {"K86", "K87"}),
            stroke_tia=bool(codes & {"K89", "K90"}), vascular=bool(codes & {"K74", "K75", "K76"}),
            diabetes=bool(codes & {"T89", "T90"}))
    return {"registers": regs, "register_titles": [irish.CDM_REGISTERS[r]["title"] for r in regs], "required": irish.cdm_required_fields(regs), "data": data,
            "missing": irish.cdm_missing_fields(regs, data), "eligible": p.eligibility in ("gms", "dvc")}


@router.post("/patients/{patient_id}/cdm")
def save_cdm(patient_id: int, body: dict, request: Request, user: User = Depends(require("cdm.write")),
             db: Session = Depends(get_db)):
    p = get_patient(db, patient_id)
    conditions = body.get("conditions") or []
    unknown = [c for c in conditions if c not in irish.CDM_REGISTERS]
    if unknown or not conditions:
        raise HTTPException(400, "Choose at least one CDM register")
    data = body.get("data") or {}
    review = db.get(CdmReview, body["id"]) if body.get("id") else None
    if review and review.status == "complete":
        raise HTTPException(409, "This review is complete")
    if not review:
        review = CdmReview(patient_id=p.id, clinician_id=user.id, programme=body.get("programme", "cdm_treatment"),
                           conditions=",".join(conditions), review_date=date.today(), data="{}")
        db.add(review)
    review.conditions = ",".join(conditions)
    review.data = json.dumps(data)
    review.care_plan = body.get("care_plan")
    missing = irish.cdm_missing_fields(conditions, data)
    if body.get("complete"):
        if missing:
            raise HTTPException(400, "Not all required fields are filled: " + ", ".join(missing))
        review.status = "complete"
        review.message_status = "queued"  # sent by the Healthlink CDM builder once certified
        review.next_due = date.today() + timedelta(days=183 if body.get("programme", "cdm_treatment") == "cdm_treatment" else 365)
        db.add(Claim(patient_id=p.id, claim_type=f"cdm_{review.programme}", service_date=date.today(),
                     clinician_id=user.id))
    db.flush()
    _touch(p)
    audit.record(db, "cdm.save", user=user, patient_id=p.id, entity="cdm_review", entity_id=review.id,
                 detail={"status": review.status, "missing": len(missing)}, ip=client_ip(request), commit=False)
    db.commit()
    return {**to_dict(review), "missing": missing}


@router.get("/patients/{patient_id}/cdm/{review_id}/care-plan")
def cdm_care_plan(patient_id: int, review_id: int, user: User = Depends(require("clinical.read")),
                  db: Session = Depends(get_db)):
    r = db.get(CdmReview, review_id)
    if not r or r.patient_id != patient_id:
        raise HTTPException(404)
    p = get_patient(db, patient_id)
    regs = ", ".join(irish.CDM_REGISTERS[c]["title"] for c in r.conditions.split(",") if c in irish.CDM_REGISTERS)
    text = (f"Care plan for {p.first_name} {p.last_name}\nReview date {r.review_date:%d/%m/%Y}\n"
            f"Conditions: {regs}\n\n{r.care_plan or ''}\n\nNext review due: "
            f"{r.next_due.strftime('%d/%m/%Y') if r.next_due else 'to be arranged'}\n")
    return Response(text, media_type="text/plain")


# --------------------------------------------------------------------------- tasks

@router.get("/tasks")
def list_tasks(mine: bool = True, status: str = "open", user: User = Depends(require("tasks")),
               db: Session = Depends(get_db)):
    q = select(Task).where(Task.status == status)
    if mine:
        q = q.where(Task.assigned_to == user.id)
    return [to_dict(t) for t in db.execute(q.order_by(Task.due.is_(None), Task.due, Task.created_at)).scalars()]


@router.post("/tasks")
def create_task(data: dict, request: Request, user: User = Depends(require("tasks")), db: Session = Depends(get_db)):
    if not data.get("title"):
        raise HTTPException(400, "Title required")
    t = Task(title=data["title"], detail=data.get("detail"), patient_id=data.get("patient_id"),
             assigned_to=data.get("assigned_to") or user.id, created_by=user.id, due=parse_date(data.get("due")),
             source=data.get("source"))
    db.add(t)
    db.flush()
    audit.record(db, "task.create", user=user, patient_id=t.patient_id, entity="task", entity_id=t.id,
                 ip=client_ip(request), commit=False)
    db.commit()
    return to_dict(t)


@router.post("/tasks/{task_id}/done")
def complete_task(task_id: int, request: Request, user: User = Depends(require("tasks")), db: Session = Depends(get_db)):
    t = db.get(Task, task_id)
    if not t:
        raise HTTPException(404)
    t.status, t.completed_at = "done", datetime.now(timezone.utc)
    audit.record(db, "task.done", user=user, patient_id=t.patient_id, entity="task", entity_id=t.id,
                 ip=client_ip(request), commit=False)
    db.commit()
    return to_dict(t)


@router.get("/icpc2")
def icpc2(q: str = "", user: User = Depends(current_user)):
    return irish.search_icpc2(q)
