"""Patient register, demographics and summary lists (GPIT DC.1.1, DC.1.4, IN.2.7, 2.7)."""
from __future__ import annotations

import csv
import io
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .. import audit, irish
from ..crypto import blind_index
from ..db import get_db
from ..models import (
    Allergy, Appointment, Carer, CdmReview, Consultation, Immunisation, InboxMessage, Observation,
    Patient, Prescription, Problem, SickCert, User,
)
from ..security import client_ip, current_user, has_perm, require
from .common import get_patient, parse_date, to_dict

router = APIRouter(prefix="/api/patients", tags=["patients"])

EDITABLE = {
    "title", "first_name", "middle_name", "last_name", "former_family_name", "birth_surname",
    "mothers_maiden_name", "alias", "dob", "sex", "eligibility", "gms_number", "gms_expiry",
    "gms_doctor_number", "gms_distance_code", "gms_dispensing", "pcrs_category", "dps_number",
    "dps_expiry", "insurer", "insurer_membership", "insurer_cover", "company_scheme", "address1",
    "address2", "town", "county", "eircode", "country", "phone_home", "phone_mobile", "email",
    "occupation", "marital_status", "religion", "ethnicity", "preferred_language",
    "interpreter_required", "transport_needs", "advocacy_needs", "nok_name", "nok_relationship",
    "nok_phone", "nok_address", "registered_gp_id", "usual_gp_id", "branch_surgery",
    "mother_patient_id", "preferred_pharmacy", "preferred_pharmacy_healthmail", "consent_sms",
    "consent_email", "consent_video", "hospital_ids",
}
DATE_FIELDS = {"dob", "gms_expiry", "dps_expiry"}
# GPIT RFC_2022 Table 5: a record is not accepted without these.
MINIMUM = ["last_name", "first_name", "dob", "sex", "address1", "address2", "registered_gp_id"]
# Fields reported as "incomplete" though not mandatory (DC.1.1.1.14).
DESIRABLE = ["phone_mobile", "eircode", "ppsn", "eligibility", "email"]


def _apply(p: Patient, data: dict, user: User) -> dict:
    changes = {}
    for k, v in data.items():
        if k == "ppsn":
            if not has_perm(user, "patient.ppsn"):
                raise HTTPException(403, "Your role cannot enter or change PPS numbers")
            v = irish.normalise_ppsn(v) if v else None
            if v and not irish.valid_ppsn(v):
                raise HTTPException(400, "PPS number is not valid (check letter does not match)")
            if v != p.ppsn:
                changes["ppsn"] = "changed"
                p.ppsn, p.ppsn_index = v, blind_index(v)
            continue
        if k == "ihi":
            v = "".join((v or "").split()) or None
            if v:
                chk = irish.validate_ihi(v)
                if not chk["valid"]:
                    raise HTTPException(400, chk["error"])
            if v != p.ihi:
                if p.ihi:
                    p.ihi_previous = p.ihi
                p.ihi = v
                changes["ihi"] = "changed"
            continue
        if k not in EDITABLE:
            continue
        if k in DATE_FIELDS:
            v = parse_date(v)
        if k == "eircode" and v:
            norm = irish.normalise_eircode(v)
            if not norm:
                raise HTTPException(400, "Eircode is not valid")
            v = norm
        if k == "ethnicity" and v and v not in irish.ETHNICITY:
            raise HTTPException(400, "Ethnicity must be one of the census categories")
        if k == "eligibility" and v not in irish.PATIENT_TYPES:
            raise HTTPException(400, "Unknown patient type")
        if k == "preferred_pharmacy_healthmail" and v:
            from ..integrations.healthmail import is_secure_recipient
            if not is_secure_recipient(v):
                raise HTTPException(400, "Pharmacy address must be a Healthmail address")
        old = getattr(p, k)
        if old != v:
            # Demographic history: old and new values go to the audit trail (DC.1.1.2.6).
            changes[k] = {"from": old, "to": v} if k not in ("nok_name", "nok_phone", "nok_address") else "changed"
            setattr(p, k, v)
    return changes


def _summary(p: Patient) -> dict:
    d = to_dict(p, exclude={"ppsn", "ihi", "ihi_previous", "nok_name", "nok_phone", "nok_address",
                            "cause_of_death", "hospital_ids"})
    d["age"] = irish.age_on(p.dob)
    d["ihi_display"] = irish.ihi_display(p.ihi) if p.ihi else None
    return d


@router.get("")
def search(q: str = "", include_inactive: bool = False, user: User = Depends(require("patient.read")),
           db: Session = Depends(get_db)):
    """Search by name, DOB (dd/mm/yyyy or yyyy-mm-dd), GMS number, PPSN or chart id."""
    q = q.strip()
    stmt = select(Patient).where(Patient.record_status != "merged")
    if not include_inactive:
        stmt = stmt.where(Patient.record_status == "active")
    if q:
        conds = []
        if irish.valid_ppsn(q):
            conds.append(Patient.ppsn_index == blind_index(q))
        if q.isdigit():
            conds.append(Patient.id == int(q))
        for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
            try:
                conds.append(Patient.dob == datetime.strptime(q, fmt).date())
            except ValueError:
                pass
        conds.append(func.lower(Patient.gms_number) == q.lower())
        parts = irish.name_key(q.replace(",", " ")).split()
        name_conds = [or_(Patient.last_name_key.contains(t), Patient.first_name_key.startswith(t))
                      for t in parts]
        if name_conds:
            from sqlalchemy import and_
            conds.append(and_(*name_conds))
        stmt = stmt.where(or_(*conds))
    rows = db.execute(stmt.order_by(Patient.last_name, Patient.first_name).limit(50)).scalars().all()
    return [_summary(p) for p in rows]


@router.post("")
def create(data: dict, request: Request, user: User = Depends(require("patient.write")), db: Session = Depends(get_db)):
    missing = [f for f in MINIMUM if data.get(f) in (None, "")]
    if missing:
        raise HTTPException(400, "Minimum registration data missing: " + ", ".join(missing))
    p = Patient(first_name="", last_name="", dob=date.today(), sex="unknown")
    _apply(p, data, user)
    db.add(p)
    db.flush()
    audit.record(db, "patient.create", user=user, patient_id=p.id, entity="patient", entity_id=p.id,
                 ip=client_ip(request), commit=False)
    db.commit()
    return _summary(p)


@router.get("/{patient_id}")
def chart(patient_id: int, request: Request, user: User = Depends(require("patient.read")),
          db: Session = Depends(get_db)):
    """Full chart. Every open is audited (who looked at which record, when)."""
    p = get_patient(db, patient_id)
    audit.record(db, "patient.view", user=user, patient_id=p.id, ip=client_ip(request))
    d = to_dict(p)
    d["age"] = irish.age_on(p.dob)
    d["ihi_display"] = irish.ihi_display(p.ihi) if p.ihi else None
    d.pop("ihi_previous", None)
    if not has_perm(user, "patient.ppsn"):
        d["ppsn"] = ("•••••" + p.ppsn[-2:]) if p.ppsn else None
    d["missing_desirable"] = [f for f in DESIRABLE if not getattr(p, f, None)]
    out = {"patient": d}
    out["allergies"] = [to_dict(a) for a in db.execute(select(Allergy).where(Allergy.patient_id == p.id)).scalars()]
    out["carers"] = [to_dict(c) for c in db.execute(select(Carer).where(Carer.patient_id == p.id)).scalars()]
    out["appointments"] = [to_dict(a) for a in db.execute(
        select(Appointment).where(Appointment.patient_id == p.id).order_by(Appointment.start.desc()).limit(20)).scalars()]
    if has_perm(user, "clinical.read"):
        probs = db.execute(select(Problem).where(Problem.patient_id == p.id).order_by(Problem.status, Problem.recorded_at.desc())).scalars().all()
        out["problems"] = [to_dict(x) for x in probs]
        cons = db.execute(select(Consultation).where(Consultation.patient_id == p.id)
                          .order_by(Consultation.started_at.desc()).limit(100)).scalars().all()
        out["consultations"] = [
            {**to_dict(c), "clinician_name": c.clinician.full_name,
             "addenda": [to_dict(a) for a in c.addenda]} for c in cons]
        rx = db.execute(select(Prescription).where(Prescription.patient_id == p.id)
                        .order_by(Prescription.created_at.desc()).limit(50)).scalars().all()
        out["prescriptions"] = [{**to_dict(r), "prescriber_name": r.prescriber.full_name,
                                 "items": [to_dict(i) for i in r.items]} for r in rx]
        out["observations"] = [to_dict(o) for o in db.execute(
            select(Observation).where(Observation.patient_id == p.id).order_by(Observation.taken_at.desc()).limit(200)).scalars()]
        out["immunisations"] = [to_dict(i) for i in db.execute(
            select(Immunisation).where(Immunisation.patient_id == p.id).order_by(Immunisation.given_at.desc())).scalars()]
        out["results"] = [{**to_dict(m, exclude={"match_hint"}), "results": [to_dict(r) for r in m.results]}
                          for m in db.execute(select(InboxMessage).where(InboxMessage.patient_id == p.id)
                                              .order_by(InboxMessage.received_at.desc()).limit(50)).scalars()]
        out["sick_certs"] = [to_dict(s) for s in db.execute(select(SickCert).where(SickCert.patient_id == p.id)).scalars()]
        out["cdm"] = cdm_status(db, p, probs)
    return out


def cdm_status(db: Session, p: Patient, problems) -> dict:
    """Green/orange/red CDM status for the summary screen (RFC 2.12.8)."""
    regs = irish.cdm_registers_for([x.icpc2_code for x in problems if x.icpc2_code and x.status == "active"])
    if not regs:
        return {"registers": [], "status": None}
    last = db.execute(select(CdmReview).where(CdmReview.patient_id == p.id)
                      .order_by(CdmReview.review_date.desc()).limit(1)).scalar_one_or_none()
    if last and last.status == "started":
        status = "orange"
    elif last and last.status == "complete" and (not last.next_due or last.next_due > date.today()):
        status = "green"
    else:
        status = "red"
    return {"registers": regs, "status": status, "last_review": to_dict(last) if last else None}


@router.patch("/{patient_id}")
def update(patient_id: int, data: dict, request: Request, user: User = Depends(require("patient.write")),
           db: Session = Depends(get_db)):
    p = get_patient(db, patient_id)
    changes = _apply(p, data, user)
    missing = [f for f in MINIMUM if getattr(p, f) in (None, "")]
    if missing:
        db.rollback()
        raise HTTPException(400, "Minimum registration data missing: " + ", ".join(missing))
    if changes:
        audit.record(db, "patient.update", user=user, patient_id=p.id, detail=changes,
                     ip=client_ip(request), commit=False)
    db.commit()
    return _summary(p)


@router.post("/{patient_id}/deregister")
def deregister(patient_id: int, data: dict, request: Request, user: User = Depends(require("patient.write")),
               db: Session = Depends(get_db)):
    p = get_patient(db, patient_id)
    p.left_practice_at = parse_date(data.get("date")) or date.today()
    p.deregistration_reason = data.get("reason")
    if data.get("deceased_date"):
        p.deceased_date = parse_date(data["deceased_date"])
        p.cause_of_death = data.get("cause_of_death")
    p.record_status = "inactive"
    audit.record(db, "patient.deregister", user=user, patient_id=p.id,
                 detail={"reason": p.deregistration_reason, "deceased": bool(p.deceased_date)},
                 ip=client_ip(request), commit=False)
    db.commit()
    return _summary(p)


@router.post("/{patient_id}/merge-into/{target_id}")
def merge(patient_id: int, target_id: int, request: Request, user: User = Depends(require("patient.write", "clinical.write")),
          db: Session = Depends(get_db)):
    """Controlled merge of a duplicate record into the surviving one (DC.1.1.1.5)."""
    if patient_id == target_id:
        raise HTTPException(400, "Cannot merge a record into itself")
    src, dst = get_patient(db, patient_id), get_patient(db, target_id)
    moved = {}
    for model in (Allergy, Problem, Consultation, Observation, Prescription, Immunisation, Appointment,
                  InboxMessage, SickCert, CdmReview, Carer):
        rows = db.execute(select(model).where(model.patient_id == src.id)).scalars().all()
        for r in rows:
            r.patient_id = dst.id
        moved[model.__tablename__] = len(rows)
    from ..models import LabResult
    for r in db.execute(select(LabResult).where(LabResult.patient_id == src.id)).scalars():
        r.patient_id = dst.id
    src.record_status, src.merged_into_id = "merged", dst.id
    audit.record(db, "patient.merge", user=user, patient_id=dst.id, entity="patient", entity_id=src.id,
                 detail=moved, ip=client_ip(request), commit=False)
    db.commit()
    return {"ok": True, "moved": moved}


# ---------------------------------------------------------------- summary lists

def _add(db, request, user, model, patient_id, data, fields, action):
    p = get_patient(db, patient_id)
    obj = model(patient_id=p.id, **{k: data.get(k) for k in fields if k in data})
    for k in fields:
        if k in ("onset", "expiry", "use_by", "consent_date") and k in data:
            setattr(obj, k, parse_date(data[k]))
        if k in ("taken_at", "given_at") and data.get(k):
            setattr(obj, k, datetime.fromisoformat(data[k]))
    if hasattr(obj, "recorded_by"):
        obj.recorded_by = user.id
    db.add(obj)
    db.flush()
    p.last_contact_at = datetime.now(timezone.utc)
    audit.record(db, action, user=user, patient_id=p.id, entity=model.__tablename__, entity_id=obj.id,
                 ip=client_ip(request), commit=False)
    db.commit()
    return to_dict(obj)


@router.post("/{patient_id}/allergies")
def add_allergy(patient_id: int, data: dict, request: Request, user: User = Depends(require("clinical.write")),
                db: Session = Depends(get_db)):
    if not data.get("substance"):
        raise HTTPException(400, "Substance required")
    return _add(db, request, user, Allergy, patient_id, data, ["substance", "reaction", "severity"], "allergy.add")


@router.post("/{patient_id}/problems")
def add_problem(patient_id: int, data: dict, request: Request, user: User = Depends(require("clinical.write")),
                db: Session = Depends(get_db)):
    code = (data.get("icpc2_code") or "").upper() or None
    if code and code not in irish.ICPC2:
        raise HTTPException(400, "Unknown ICPC-2 code")
    data = {**data, "icpc2_code": code, "description": data.get("description") or irish.ICPC2.get(code or "", "")}
    if data.get("icd_code"):
        from .. import terminology
        try:
            data["icd_system"], data["icd_code"], data["icd_title"] = terminology.validate(
                db, data.get("icd_system") or "ICD10", data["icd_code"])
        except ValueError as e:
            raise HTTPException(400, str(e))
        if not data["description"] and data["icd_title"]:
            data["description"] = data["icd_title"]
    if not data["description"]:
        raise HTTPException(400, "Description required")
    return _add(db, request, user, Problem, patient_id, data,
                ["icpc2_code", "icd_system", "icd_code", "icd_title", "description", "status", "onset", "notes"],
                "problem.add")


@router.patch("/{patient_id}/problems/{problem_id}")
def update_problem(patient_id: int, problem_id: int, data: dict, request: Request,
                   user: User = Depends(require("clinical.write")), db: Session = Depends(get_db)):
    pr = db.get(Problem, problem_id)
    if not pr or pr.patient_id != patient_id:
        raise HTTPException(404)
    for k in ("status", "notes", "description"):
        if k in data:
            setattr(pr, k, data[k])
    audit.record(db, "problem.update", user=user, patient_id=patient_id, entity="problem", entity_id=pr.id,
                 detail={k: data[k] for k in ("status",) if k in data}, ip=client_ip(request), commit=False)
    db.commit()
    return to_dict(pr)


@router.post("/{patient_id}/observations")
def add_observation(patient_id: int, data: dict, request: Request, user: User = Depends(require("clinical.write")),
                    db: Session = Depends(get_db)):
    p = get_patient(db, patient_id)
    try:
        val = float(data["value"])
    except (KeyError, TypeError, ValueError):
        raise HTTPException(400, "Numeric value required")
    kind = data.get("kind", "")
    if kind == "height_cm":
        errs = irish.plausible_height_weight(val, None, irish.age_on(p.dob))
    elif kind == "weight_kg":
        errs = irish.plausible_height_weight(None, val, irish.age_on(p.dob))
    else:
        errs = []
    if errs:
        raise HTTPException(400, "; ".join(errs))
    return _add(db, request, user, Observation, patient_id, {**data, "value": val},
                ["kind", "value", "unit", "taken_at", "consultation_id"], "observation.add")


@router.post("/{patient_id}/immunisations")
def add_immunisation(patient_id: int, data: dict, request: Request, user: User = Depends(require("immunise")),
                     db: Session = Depends(get_db)):
    p = get_patient(db, patient_id)
    if not data.get("vaccine"):
        raise HTTPException(400, "Vaccine required")
    consent = data.get("consent", "given")
    if consent == "given":
        if not data.get("batch"):
            raise HTTPException(400, "Batch number required")
        exp, use_by = parse_date(data.get("expiry")), parse_date(data.get("use_by"))
        today = date.today()
        if exp and exp < today:
            raise HTTPException(400, "Vaccine is past its expiry date")
        if use_by and use_by < today:
            raise HTTPException(400, "Vaccine is past its use-by date")
        if exp and exp > today + timedelta(days=365 * 5):
            raise HTTPException(400, "Expiry date looks wrong (more than 5 years ahead)")
        if not (p.phone_mobile or p.email):
            raise HTTPException(400, "Record a mobile number or email first (needed for vaccination messaging)")
    obj = _add(db, request, user, Immunisation, patient_id, data,
               ["vaccine", "batch", "expiry", "use_by", "site", "route", "dose_number", "dose_kind",
                "dose_volume_ml", "consent", "contraindications", "given_at"],
               "immunisation.refused" if consent == "refused" else "immunisation.add")
    imm = db.get(Immunisation, obj["id"])
    imm.given_by = user.id
    db.commit()
    return to_dict(imm)


@router.post("/{patient_id}/carers")
def add_carer(patient_id: int, data: dict, request: Request, user: User = Depends(require("patient.write")),
              db: Session = Depends(get_db)):
    if not data.get("name"):
        raise HTTPException(400, "Name required")
    return _add(db, request, user, Carer, patient_id, data,
                ["name", "relationship_to_patient", "phone", "address", "carer_patient_id", "consent_date"], "carer.add")


# --------------------------------------------------------------- PCRS and IHI

@router.post("/import/pcrs-listing")
async def import_pcrs(request: Request, file: UploadFile = File(...), gp_id: int | None = None,
                      user: User = Depends(require("patient.write", "patient.ppsn")), db: Session = Depends(get_db)):
    """Import a GMS panel from the PCRS patient listing CSV (RFC 2.3, Table 15).

    Existing patients (same GMS number, or same surname + DOB) are updated with
    eligibility details only; new ones are created.
    """
    text = (await file.read()).decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    created = updated = skipped = 0
    errors = []
    for n, row in enumerate(reader, start=2):
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
        try:
            dob = datetime.strptime(row["date of birth"], "%d/%m/%Y").date()
            expiry = datetime.strptime(row["expiry date"], "%d/%m/%Y").date() if row.get("expiry date") else None
        except (KeyError, ValueError):
            errors.append(f"row {n}: bad date")
            skipped += 1
            continue
        mc = row.get("medical card", "")
        p = db.execute(select(Patient).where(Patient.gms_number == mc)).scalar_one_or_none() if mc else None
        if not p:
            p = db.execute(select(Patient).where(Patient.last_name_key == irish.name_key(row.get("surname", "")),
                                                 Patient.dob == dob)).scalar_one_or_none()
        is_new = p is None
        if is_new:
            p = Patient(
                first_name=row.get("firstname", "").title(), last_name=row.get("surname", "").title(),
                dob=dob, sex={"male": "male", "female": "female"}.get(row.get("sex", "").lower(), "unknown"),
                address1=row.get("address 1", "").title(), address2=row.get("address 2", "").title(),
                town=row.get("address 3", "").title(), registered_gp_id=gp_id or user.id,
            )
            a4 = row.get("address 4", "")
            if a4 and a4.upper() != "XXXXX":
                p.county = a4.title()
            db.add(p)
        p.eligibility = "dvc" if row.get("card type", "").upper() == "DVC" else "gms"
        p.gms_number, p.gms_expiry = mc or p.gms_number, expiry
        p.gms_distance_code = row.get("distance code") or None
        p.gms_dispensing = row.get("dispensing code", "").upper() == "Y"
        p.pcrs_category = row.get("category") or None
        pps = irish.normalise_ppsn(row.get("ppsn", ""))
        if pps and irish.valid_ppsn(pps) and not p.ppsn:
            p.ppsn, p.ppsn_index = pps, blind_index(pps)
        created += is_new
        updated += not is_new
    audit.record(db, "pcrs.import", user=user, detail={"created": created, "updated": updated, "skipped": skipped},
                 ip=client_ip(request), commit=False)
    db.commit()
    return {"created": created, "updated": updated, "skipped": skipped, "errors": errors[:50]}


@router.get("/tools/ihi-check/{value}")
def ihi_check(value: str, user: User = Depends(current_user)):
    return irish.validate_ihi(value)


@router.post("/tools/ihi-purge")
def ihi_purge(request: Request, user: User = Depends(require("governance")), db: Session = Depends(get_db)):
    """Clear all seeded IHIs (RFC 2.7.8)."""
    n = 0
    for p in db.execute(select(Patient).where(Patient.ihi.is_not(None))).scalars():
        p.ihi_previous, p.ihi = p.ihi, None
        n += 1
    audit.record(db, "ihi.purge", user=user, detail={"count": n}, ip=client_ip(request), commit=False)
    db.commit()
    return {"purged": n}
