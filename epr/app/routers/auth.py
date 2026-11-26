from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pyotp
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..config import settings
from ..db import get_db
from ..models import User, UserSession
from ..security import (
    LOCKOUT_MINUTES, MAX_FAILED_LOGINS, PRESCRIBER_ROLES, ROLE_PERMISSIONS, SESSION_COOKIE,
    client_ip, create_session, current_user, get_session, hash_password, new_totp_secret,
    require, verify_password, verify_totp,
)
from .common import to_dict

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginIn(BaseModel):
    username: str
    password: str


class CodeIn(BaseModel):
    code: str


def _aware(d):
    return d if d is None or d.tzinfo else d.replace(tzinfo=timezone.utc)


def _set_cookie(resp: Response, token: str) -> None:
    resp.set_cookie(SESSION_COOKIE, token, httponly=True, secure=settings.cookie_secure,
                    samesite="strict", max_age=settings.session_max_hours * 3600, path="/")


def _me(user: User, s: UserSession) -> dict:
    return {
        "user": to_dict(user), "csrf": s.csrf_token, "mfa_passed": s.mfa_passed,
        "mfa_required": settings.require_mfa or user.mfa_enabled,
        "permissions": sorted(ROLE_PERMISSIONS.get(user.role, set())),
        "is_prescriber": user.role in PRESCRIBER_ROLES,
        "practice": {"name": settings.practice_name},
        "idle_minutes": settings.session_idle_minutes,
    }


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    ip = client_ip(request)
    user = db.execute(select(User).where(User.username == body.username.strip().lower())).scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if user and user.locked_until and _aware(user.locked_until) > now:
        audit.record(db, "auth.login_locked", user=user, ip=ip)
        raise HTTPException(423, "Account temporarily locked after failed sign-ins. Try again later.")
    if not user or not user.active or not verify_password(user.password_hash, body.password):
        if user:
            user.failed_logins += 1
            if user.failed_logins >= MAX_FAILED_LOGINS:
                user.locked_until = now + timedelta(minutes=LOCKOUT_MINUTES)
                user.failed_logins = 0
            db.commit()
        audit.record(db, "auth.login_failed", user=user, ip=ip, detail={"username": body.username[:80]})
        raise HTTPException(401, "Incorrect username or password")
    user.failed_logins = 0
    db.commit()
    needs_mfa = settings.require_mfa or user.mfa_enabled
    token, s = create_session(db, user, ip, mfa_passed=not needs_mfa)
    _set_cookie(response, token)
    audit.record(db, "auth.login", user=user, ip=ip, detail={"mfa_pending": needs_mfa})
    return _me(user, s)


@router.post("/mfa/setup")
def mfa_setup(request: Request, s: UserSession = Depends(get_session), db: Session = Depends(get_db)):
    """First sign-in: issue a TOTP secret (shown once as an otpauth URI / QR)."""
    user = s.user
    if user.mfa_enabled:
        raise HTTPException(400, "Two-factor authentication is already set up")
    if request.headers.get("X-EPR-CSRF") != s.csrf_token:
        raise HTTPException(403, "CSRF check failed")
    user.totp_secret = new_totp_secret()
    db.commit()
    uri = pyotp.TOTP(user.totp_secret).provisioning_uri(name=user.username, issuer_name=settings.practice_name)
    return {"otpauth_uri": uri, "secret": user.totp_secret}


@router.post("/mfa/verify")
def mfa_verify(body: CodeIn, request: Request, s: UserSession = Depends(get_session), db: Session = Depends(get_db)):
    if request.headers.get("X-EPR-CSRF") != s.csrf_token:
        raise HTTPException(403, "CSRF check failed")
    user = s.user
    if not user.totp_secret or not verify_totp(user.totp_secret, body.code):
        audit.record(db, "auth.mfa_failed", user=user, ip=client_ip(request))
        raise HTTPException(401, "Code not accepted")
    user.mfa_enabled = True
    s.mfa_passed = True
    db.commit()
    audit.record(db, "auth.mfa_passed", user=user, ip=client_ip(request))
    return _me(user, s)


@router.get("/me")
def me(user: User = Depends(current_user), s: UserSession = Depends(get_session)):
    return _me(user, s)


@router.get("/session")
def session_state(s: UserSession = Depends(get_session)):
    """Used by the UI before MFA is complete."""
    return _me(s.user, s)


@router.post("/logout")
def logout(request: Request, response: Response, s: UserSession = Depends(get_session), db: Session = Depends(get_db)):
    audit.record(db, "auth.logout", user=s.user, ip=client_ip(request))
    db.delete(s)
    db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


# ------------------------------------------------------------------ user admin

class UserIn(BaseModel):
    username: str
    full_name: str
    role: str
    password: str
    mcrn: str | None = None
    nmbi_pin: str | None = None
    gms_doctor_number: str | None = None
    healthmail_address: str | None = None
    work_address: str | None = None


@router.get("/users")
def list_users(user: User = Depends(current_user), db: Session = Depends(get_db)):
    # Any signed-in user can see the staff list (needed for assigning tasks/appointments).
    return [to_dict(u) for u in db.execute(select(User).order_by(User.full_name)).scalars()]


@router.post("/users")
def create_user(body: UserIn, request: Request, admin: User = Depends(require("users.manage")),
                db: Session = Depends(get_db)):
    if body.role not in ROLE_PERMISSIONS:
        raise HTTPException(400, "Unknown role")
    uname = body.username.strip().lower()
    if db.execute(select(User).where(User.username == uname)).scalar_one_or_none():
        raise HTTPException(409, "Username taken")
    u = User(username=uname, full_name=body.full_name, role=body.role,
             password_hash=hash_password(body.password), mcrn=body.mcrn, nmbi_pin=body.nmbi_pin,
             gms_doctor_number=body.gms_doctor_number, healthmail_address=body.healthmail_address,
             work_address=body.work_address)
    db.add(u)
    db.commit()
    audit.record(db, "user.create", user=admin, entity="user", entity_id=u.id,
                 detail={"username": uname, "role": body.role}, ip=client_ip(request))
    return to_dict(u)


class HealthmailCredIn(BaseModel):
    address: str
    password: str


@router.post("/healthmail-account")
def link_healthmail(body: HealthmailCredIn, request: Request, user: User = Depends(current_user),
                    db: Session = Depends(get_db)):
    """Link the signed-in clinician's own Healthmail account (RFC 2.9.1)."""
    from ..integrations.healthmail import is_secure_recipient
    if not is_secure_recipient(body.address):
        raise HTTPException(400, "That is not a Healthmail address")
    user.healthmail_address = body.address
    user.healthmail_secret = body.password
    db.commit()
    audit.record(db, "healthmail.link", user=user, ip=client_ip(request))
    return {"ok": True}


@router.post("/users/{user_id}/deactivate")
def deactivate(user_id: int, request: Request, admin: User = Depends(require("users.manage")),
               db: Session = Depends(get_db)):
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(404)
    u.active = False
    for s in db.execute(select(UserSession).where(UserSession.user_id == u.id)).scalars():
        db.delete(s)
    db.commit()
    audit.record(db, "user.deactivate", user=admin, entity="user", entity_id=u.id, ip=client_ip(request))
    return {"ok": True}
