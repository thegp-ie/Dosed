"""Admin commands.

    python -m app.cli create-user USERNAME "Full Name" ROLE [--mcrn N]
    python -m app.cli verify-audit
    python -m app.cli gen-keys
    python -m app.cli seed-demo          (development only: fictional patients)
"""
from __future__ import annotations

import argparse
import base64
import getpass
import os
import secrets
import sys
from datetime import date, datetime, timedelta, timezone

from . import audit, irish
from .config import settings
from .crypto import blind_index
from .db import Base, SessionLocal, engine
from .models import Allergy, Appointment, Observation, Patient, Problem, User
from .security import ROLE_PERMISSIONS, hash_password


def create_user(a):
    if a.role not in ROLE_PERMISSIONS:
        sys.exit(f"Role must be one of: {', '.join(ROLE_PERMISSIONS)}")
    pw = a.password or getpass.getpass("Password (min 12 chars): ")
    Base.metadata.create_all(engine)
    db = SessionLocal()
    u = User(username=a.username.lower(), full_name=a.full_name, role=a.role, password_hash=hash_password(pw),
             mcrn=a.mcrn, healthmail_address=a.healthmail)
    db.add(u)
    db.commit()
    audit.record(db, "user.create", detail={"username": u.username, "role": u.role, "via": "cli"})
    print(f"Created {u.username} ({u.role}). Two-factor setup happens at first sign-in.")


def verify(_):
    db = SessionLocal()
    r = audit.verify_chain(db)
    print(r)
    sys.exit(0 if r["ok"] else 1)


def gen_keys(_):
    for name in ("EPR_DATA_KEY", "EPR_INDEX_KEY"):
        print(f"{name}={base64.b64encode(os.urandom(32)).decode()}")
    print(f"EPR_SECRET_KEY={secrets.token_urlsafe(48)}")
    print(f"EPR_JITSI_APP_SECRET={secrets.token_urlsafe(48)}")


def seed_demo(_):
    if settings.is_production:
        sys.exit("Refusing to seed demo data in production")
    Base.metadata.create_all(engine)
    db = SessionLocal()
    users = {}
    for uname, name, role, mcrn in (
        ("drmurphy", "Dr Aoife Murphy", "gp", "412345"), ("nurse.kelly", "Siobhán Kelly RGN", "nurse", None),
        ("reception", "Ciara Byrne", "reception", None), ("manager", "Pádraig Walsh", "practice_manager", None),
    ):
        u = db.query(User).filter_by(username=uname).one_or_none()
        if not u:
            u = User(username=uname, full_name=name, role=role, mcrn=mcrn,
                     password_hash=hash_password("demo-password-123"),
                     healthmail_address=f"{uname}@healthmail.ie" if role in ("gp", "nurse") else None)
            db.add(u)
            db.flush()
        users[role] = u
    gp = users["gp"]
    demo = [
        ("Seán", "Ó Briain", date(1958, 3, 14), "male", "gms", "1234567T", ["T90", "K86"]),
        ("Máire", "Ní Dhónaill", date(1990, 7, 2), "female", "private", None, ["R96"]),
        ("Liam", "Fitzgerald", date(1947, 11, 23), "male", "gms", None, ["K78", "K77"]),
        ("Orla", "Brennan", date(2019, 5, 30), "female", "dvc", None, []),
    ]
    for first, last, dob, sex, elig, ppsn, codes in demo:
        if db.query(Patient).filter_by(first_name=first, last_name=last).first():
            continue
        p = Patient(first_name=first, last_name=last, dob=dob, sex=sex, eligibility=elig,
                    address1="1 Main Street", address2="Ballymore", town="Galway", county="Galway",
                    eircode="H91 AC12", phone_mobile="0871234567", registered_gp_id=gp.id, usual_gp_id=gp.id,
                    consent_video=True, consent_sms=True,
                    gms_number=f"{secrets.randbelow(899999) + 100000}A" if elig in ("gms", "dvc") else None,
                    preferred_pharmacy="Main St Pharmacy", preferred_pharmacy_healthmail="mainstpharmacy@healthmail.ie")
        if ppsn:
            p.ppsn, p.ppsn_index = ppsn, blind_index(ppsn)
        db.add(p)
        db.flush()
        for c in codes:
            db.add(Problem(patient_id=p.id, icpc2_code=c, description=irish.ICPC2[c], recorded_by=gp.id))
        if first == "Liam":
            db.add(Allergy(patient_id=p.id, substance="Penicillin", reaction="Rash", severity="moderate"))
        now = datetime.now(timezone.utc)
        db.add(Observation(patient_id=p.id, kind="bp_systolic", value=138, unit="mmHg", taken_at=now - timedelta(days=30)))
        db.add(Observation(patient_id=p.id, kind="bp_diastolic", value=84, unit="mmHg", taken_at=now - timedelta(days=30)))
        db.add(Appointment(patient_id=p.id, clinician_id=gp.id, mode="video" if first == "Máire" else "surgery",
                           start=now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1 + len(first) % 4)))
    db.commit()
    print("Demo data ready. Users: drmurphy / nurse.kelly / reception / manager, password demo-password-123")


def main():
    ap = argparse.ArgumentParser(prog="python -m app.cli")
    sub = ap.add_subparsers(required=True)
    c = sub.add_parser("create-user")
    c.add_argument("username")
    c.add_argument("full_name")
    c.add_argument("role")
    c.add_argument("--mcrn")
    c.add_argument("--healthmail")
    c.add_argument("--password", help="omit to be prompted")
    c.set_defaults(fn=create_user)
    sub.add_parser("verify-audit").set_defaults(fn=verify)
    sub.add_parser("gen-keys").set_defaults(fn=gen_keys)
    sub.add_parser("seed-demo").set_defaults(fn=seed_demo)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
