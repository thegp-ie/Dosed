"""Authentication, sessions, MFA and role-based access control (GPIT IN.1.1-IN.1.3)."""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .models import User, UserSession

SESSION_COOKIE = "epr_session"
CSRF_HEADER = "X-EPR-CSRF"
MAX_FAILED_LOGINS = 5
LOCKOUT_MINUTES = 15

_ph = PasswordHasher()

# Permissions per role. Prescribing and Healthmail ePrescription transfer are limited to
# licensed prescribers (RFC 2.9.2, 2.10.3). PPSN edits limited to designated users (DC.1.1.2.16).
ROLE_PERMISSIONS: dict[str, set[str]] = {
    "gp": {
        "patient.read", "patient.write", "patient.ppsn", "clinical.read", "clinical.write",
        "prescribe", "prescription.send", "inbox.read", "inbox.review", "healthmail.send",
        "referral.send", "appointment.read", "appointment.write", "telehealth.host",
        "claims.write", "sickcert.write", "cdm.write", "tasks", "reports",
    },
    "nurse": {
        "patient.read", "patient.write", "clinical.read", "clinical.write", "inbox.read",
        "healthmail.send", "appointment.read", "appointment.write", "telehealth.host",
        "claims.write", "cdm.write", "immunise", "tasks", "reports",
    },
    "nurse_prescriber": set(),  # filled below: nurse + prescribing
    "reception": {
        "patient.read", "patient.write", "appointment.read", "appointment.write",
        "inbox.file", "tasks", "billing",
    },
    "practice_manager": {
        "patient.read", "patient.write", "patient.ppsn", "appointment.read",
        "appointment.write", "inbox.file", "claims.write", "billing", "reports", "tasks",
        "governance", "users.manage", "audit.read",
    },
    "sysadmin": {"users.manage", "audit.read", "governance", "system"},
}
ROLE_PERMISSIONS["gp"] |= {"immunise", "billing", "scribe", "reference.load"}
ROLE_PERMISSIONS["nurse"] |= {"scribe"}
ROLE_PERMISSIONS["practice_manager"] |= {"reference.load"}
ROLE_PERMISSIONS["sysadmin"] |= {"reference.load"}
ROLE_PERMISSIONS["nurse_prescriber"] = ROLE_PERMISSIONS["nurse"] | {"prescribe", "prescription.send"}

PRESCRIBER_ROLES = {"gp", "nurse_prescriber"}


def hash_password(pw: str) -> str:
    if len(pw) < 12:
        raise HTTPException(400, "Password must be at least 12 characters")
    return _ph.hash(pw)


def verify_password(hash_: str, pw: str) -> bool:
    try:
        return _ph.verify(hash_, pw)
    except (VerifyMismatchError, InvalidHashError):
        return False


def new_totp_secret() -> str:
    return pyotp.random_base32()


def verify_totp(secret: str, code: str) -> bool:
    return pyotp.TOTP(secret).verify(code.strip(), valid_window=1)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(d: datetime) -> datetime:
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def create_session(db: Session, user: User, ip: str | None, mfa_passed: bool) -> tuple[str, UserSession]:
    token = secrets.token_urlsafe(32)
    s = UserSession(
        token_hash=_hash_token(token), csrf_token=secrets.token_urlsafe(24), user_id=user.id,
        mfa_passed=mfa_passed, ip=ip,
        expires_at=_now() + timedelta(hours=settings.session_max_hours),
    )
    db.add(s)
    db.commit()
    return token, s


def client_ip(request: Request) -> str | None:
    # Behind the bundled Caddy proxy; trust X-Forwarded-For's first hop only from it.
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else None


def _load_session(request: Request, db: Session) -> UserSession | None:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    s = db.execute(select(UserSession).where(UserSession.token_hash == _hash_token(token))).scalar_one_or_none()
    if not s:
        return None
    now = _now()
    if _aware(s.expires_at) < now or _aware(s.last_seen) < now - timedelta(minutes=settings.session_idle_minutes):
        db.delete(s)
        db.commit()
        return None
    return s


def get_session(request: Request, db: Session = Depends(get_db)) -> UserSession:
    s = _load_session(request, db)
    if not s:
        raise HTTPException(401, "Not signed in")
    return s


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    s = _load_session(request, db)
    if not s or not s.user.active:
        raise HTTPException(401, "Not signed in")
    if not s.mfa_passed and (settings.require_mfa or s.user.mfa_enabled):
        raise HTTPException(401, "Two-factor authentication required")
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        if not secrets.compare_digest(request.headers.get(CSRF_HEADER, ""), s.csrf_token):
            raise HTTPException(403, "CSRF check failed")
    s.last_seen = _now()
    db.commit()
    request.state.user = s.user
    return s.user


def require(*perms: str):
    def dep(user: User = Depends(current_user)) -> User:
        granted = ROLE_PERMISSIONS.get(user.role, set())
        missing = [p for p in perms if p not in granted]
        if missing:
            raise HTTPException(403, f"Your role cannot do this ({', '.join(missing)})")
        return user
    return dep


def has_perm(user: User, perm: str) -> bool:
    return perm in ROLE_PERMISSIONS.get(user.role, set())
