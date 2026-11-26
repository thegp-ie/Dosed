from __future__ import annotations

from datetime import date, datetime

from fastapi import HTTPException
from sqlalchemy import inspect
from sqlalchemy.orm import Session

from ..models import Patient

SECRET_FIELDS = {"password_hash", "totp_secret", "healthmail_secret", "ppsn_index", "token_hash",
                 "csrf_token", "patient_link_hash", "raw"}


def to_dict(obj, exclude: set[str] = frozenset(), include: set[str] = frozenset()) -> dict:
    out = {}
    for col in inspect(obj).mapper.column_attrs:
        k = col.key
        if (k in SECRET_FIELDS and k not in include) or k in exclude:
            continue
        v = getattr(obj, k)
        if isinstance(v, (date, datetime)):
            v = v.isoformat()
        out[k] = v
    return out


def get_patient(db: Session, patient_id: int) -> Patient:
    p = db.get(Patient, patient_id)
    if not p or p.record_status == "merged":
        raise HTTPException(404, "Patient not found")
    return p


def parse_date(v) -> date | None:
    if v in (None, ""):
        return None
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        raise HTTPException(400, f"Invalid date: {v}")
