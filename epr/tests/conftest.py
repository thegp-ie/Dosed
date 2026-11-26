import os
import sys
import tempfile
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="epr-test-")
os.environ.update({
    "EPR_ENV": "test",
    "EPR_DATABASE_URL": f"sqlite:///{_tmp}/test.db",
    "EPR_COOKIE_SECURE": "false",
    "EPR_REQUIRE_MFA": "true",
    "EPR_HEALTHLINK_MODE": "directory",
    "EPR_HEALTHLINK_INBOUND_DIR": f"{_tmp}/hl/in",
    "EPR_HEALTHLINK_OUTBOUND_DIR": f"{_tmp}/hl/out",
    "EPR_HEALTHLINK_ARCHIVE_DIR": f"{_tmp}/hl/archive",
    "EPR_JITSI_APP_SECRET": "test-secret",
    "EPR_JITSI_BASE_URL": "https://meet.test.ie",
    "EPR_PUBLIC_BASE_URL": "https://epr.test.ie",
    "EPR_HEALTHMAIL_SMTP_HOST": "smtp.invalid",
})
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pyotp  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import User  # noqa: E402
from app.security import hash_password  # noqa: E402

PW = "correct-horse-battery"


@pytest.fixture(scope="session")
def tmpdir_path():
    return Path(_tmp)


@pytest.fixture(autouse=True)
def fresh_db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    db = SessionLocal()
    for uname, role, mcrn in (("gp", "gp", "400001"), ("nurse", "nurse", None), ("reception", "reception", None),
                              ("manager", "practice_manager", None)):
        db.add(User(username=uname, full_name=uname.title(), role=role, mcrn=mcrn, password_hash=hash_password(PW),
                    healthmail_address=f"{uname}@healthmail.ie", healthmail_secret="hm-pass"))
    db.commit()
    db.close()
    yield


class Client:
    """Signed-in test client that handles MFA and the CSRF header."""

    def __init__(self, username: str):
        self.c = TestClient(app)
        r = self.c.post("/api/auth/login", json={"username": username, "password": PW})
        assert r.status_code == 200, r.text
        self.csrf = r.json()["csrf"]
        r = self.c.post("/api/auth/mfa/setup", headers={"X-EPR-CSRF": self.csrf})
        assert r.status_code == 200, r.text
        code = pyotp.TOTP(r.json()["secret"]).now()
        r = self.c.post("/api/auth/mfa/verify", json={"code": code}, headers={"X-EPR-CSRF": self.csrf})
        assert r.status_code == 200, r.text

    def get(self, url, **kw):
        return self.c.get(url, **kw)

    def post(self, url, **kw):
        return self.c.post(url, headers={"X-EPR-CSRF": self.csrf}, **kw)

    def patch(self, url, **kw):
        return self.c.patch(url, headers={"X-EPR-CSRF": self.csrf}, **kw)


@pytest.fixture
def gp():
    return Client("gp")


@pytest.fixture
def nurse():
    return Client("nurse")


@pytest.fixture
def reception():
    return Client("reception")


@pytest.fixture
def manager():
    return Client("manager")


@pytest.fixture
def patient(gp):
    r = gp.post("/api/patients", json={
        "first_name": "Seán", "last_name": "Ó Briain", "dob": "1958-03-14", "sex": "male",
        "address1": "1 Main St", "address2": "Ballymore", "town": "Galway", "eircode": "h91ac12",
        "registered_gp_id": 1, "usual_gp_id": 1, "ppsn": "1234567T", "eligibility": "gms", "gms_number": "123456A",
        "phone_mobile": "0871234567", "consent_video": True,
    })
    assert r.status_code == 200, r.text
    return r.json()
