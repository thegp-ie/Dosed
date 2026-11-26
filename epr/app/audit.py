"""Append-only, hash-chained audit log (GPIT IN.2.2, GDPR Art. 5(2)/32).

Every row stores the SHA-256 of the previous row plus its own content, so any edit or
deletion of an earlier row breaks the chain and is detected by verify_chain().
For stronger tamper evidence, ship rows off-host (see docs/DEPLOYMENT.md, log shipping).
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from .models import AuditLog, User

GENESIS = "0" * 64


def _digest(prev_hash: str, row: dict) -> str:
    payload = json.dumps(row, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256((prev_hash + payload).encode()).hexdigest()


def _row_dict(e: AuditLog) -> dict:
    at = e.at
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    return {
        "at": at.isoformat(), "user_id": e.user_id, "username": e.username, "action": e.action,
        "patient_id": e.patient_id, "entity": e.entity, "entity_id": e.entity_id,
        "detail": e.detail, "ip": e.ip,
    }


def record(db: Session, action: str, *, user: User | None = None, patient_id: int | None = None,
           entity: str | None = None, entity_id=None, detail: str | dict | None = None,
           ip: str | None = None, commit: bool = True) -> AuditLog:
    if isinstance(detail, dict):
        detail = json.dumps(detail, sort_keys=True, default=str)
    if db.get_bind().dialect.name == "postgresql":
        # Serialise writers so two requests never chain onto the same previous hash.
        db.execute(text("SELECT pg_advisory_xact_lock(727274)"))
    last =db.execute(select(AuditLog).order_by(AuditLog.id.desc()).limit(1)).scalar_one_or_none()
    prev = last.hash if last else GENESIS
    e = AuditLog(
        at=datetime.now(timezone.utc).replace(microsecond=0),
        user_id=user.id if user else None, username=user.username if user else None,
        action=action, patient_id=patient_id, entity=entity,
        entity_id=str(entity_id) if entity_id is not None else None,
        detail=detail, ip=ip, prev_hash=prev, hash="",
    )
    e.hash = _digest(prev, _row_dict(e))
    db.add(e)
    if commit:
        db.commit()
    else:
        db.flush()
    return e


def verify_chain(db: Session) -> dict:
    prev = GENESIS
    count = 0
    for e in db.execute(select(AuditLog).order_by(AuditLog.id)).scalars():
        if e.prev_hash != prev or _digest(prev, _row_dict(e)) != e.hash:
            return {"ok": False, "broken_at_id": e.id, "checked": count}
        prev = e.hash
        count += 1
    return {"ok": True, "checked": count}
