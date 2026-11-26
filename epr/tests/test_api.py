from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import text

from app import irish
from app.db import SessionLocal, engine
from app.integrations import healthmail
from app.main import app
from tests.test_hl7 import ER7


# ----------------------------------------------------------------- auth & access

def test_login_requires_mfa_and_csrf(gp):
    c = TestClient(app)
    r = c.post("/api/auth/login", json={"username": "gp", "password": "correct-horse-battery"})
    assert r.status_code == 200 and r.json()["mfa_passed"] is False
    assert c.get("/api/patients").status_code == 401  # MFA not done yet
    # Fully signed-in client: a write without the CSRF header is refused.
    assert gp.c.post("/api/patients", json={}).status_code == 403


def test_lockout_after_failed_logins():
    c = TestClient(app)
    for _ in range(5):
        assert c.post("/api/auth/login", json={"username": "gp", "password": "wrong"}).status_code == 401
    assert c.post("/api/auth/login", json={"username": "gp", "password": "correct-horse-battery"}).status_code == 423


def test_security_headers():
    r = TestClient(app).get("/healthz")
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert r.headers["x-frame-options"] == "DENY"


# ---------------------------------------------------------------------- patients

def test_minimum_registration_data(gp):
    r = gp.post("/api/patients", json={"first_name": "A", "last_name": "B", "dob": "2000-01-01", "sex": "female"})
    assert r.status_code == 400 and "address1" in r.json()["detail"]


def test_ppsn_validation_and_permission(gp, reception, patient):
    assert gp.patch(f"/api/patients/{patient['id']}", json={"ppsn": "1234567A"}).status_code == 400
    assert reception.patch(f"/api/patients/{patient['id']}", json={"ppsn": "1234567T"}).status_code == 403
    # Reception sees PPSN masked
    assert reception.get(f"/api/patients/{patient['id']}").json()["patient"]["ppsn"].startswith("•")
    assert gp.get(f"/api/patients/{patient['id']}").json()["patient"]["ppsn"] == "1234567T"


def test_ppsn_encrypted_at_rest_and_searchable(gp, patient):
    with engine.connect() as conn:
        raw = conn.execute(text("select ppsn from patients where id=:i"), {"i": patient["id"]}).scalar()
    assert raw.startswith("v1:") and "1234567" not in raw
    hits = gp.get("/api/patients", params={"q": "1234567t"}).json()
    assert [h["id"] for h in hits] == [patient["id"]]
    assert gp.get("/api/patients", params={"q": "ó bri"}).json()[0]["id"] == patient["id"]
    assert gp.get("/api/patients", params={"q": "14/03/1958"}).json()[0]["id"] == patient["id"]


def test_eircode_normalised_and_ihi(gp, patient):
    assert patient["eircode"] == "H91 AC12"
    ihi = irish.make_test_ihi("987654321")
    r = gp.patch(f"/api/patients/{patient['id']}", json={"ihi": ihi})
    assert r.status_code == 200 and r.json()["ihi_display"] == irish.ihi_display(ihi)
    assert gp.patch(f"/api/patients/{patient['id']}", json={"ihi": "1" * 18}).status_code == 400


def test_chart_view_is_audited(gp, manager, patient):
    gp.get(f"/api/patients/{patient['id']}")
    log = manager.get(f"/api/patients/{patient['id']}/access-log").json()
    assert any(e["action"] == "patient.view" and e["user"] == "gp" for e in log)
    assert manager.get("/api/audit/verify").json()["ok"] is True


def test_audit_chain_detects_tampering(gp, manager, patient):
    gp.get(f"/api/patients/{patient['id']}")
    with engine.begin() as conn:
        conn.execute(text("update audit_log set username='someone-else' where id=(select min(id) from audit_log where action='patient.view')"))
    assert manager.get("/api/audit/verify").json()["ok"] is False


def test_pcrs_listing_import(gp):
    csv_text = ("Distance Code,Age Group,Category,Medical Card,Surname,Firstname,Sex,Date of Birth,Address 1,"
                "Address 2,Address 3,Address 4,PPSN,Dispensing Code,Card Type,Expiry Date\n"
                "A,45 to 64,Not Categorised,654321B,TEST,JOHN,Male,01/02/1970,4 PRIVET DRIVE,FOXROCK,DUBLIN 18,"
                "XXXXX,1234567T,N,MC,31/10/2027\n")
    r = gp.post("/api/patients/import/pcrs-listing", files={"file": ("panel.csv", csv_text, "text/csv")})
    assert r.status_code == 200, r.text
    assert r.json()["created"] == 1
    p = gp.get("/api/patients", params={"q": "654321B"}).json()[0]
    assert p["eligibility"] == "gms" and p["last_name"] == "Test" and p["gms_expiry"] == "2027-10-31"
    # Re-import updates, never duplicates
    assert gp.post("/api/patients/import/pcrs-listing", files={"file": ("p.csv", csv_text, "text/csv")}).json()["updated"] == 1


# -------------------------------------------------------------------- clinical

def test_consultation_lock_and_addendum(gp, nurse, patient):
    r = gp.post(f"/api/patients/{patient['id']}/consultations",
                json={"subjective": "cough 3/7", "icpc2_code": "r05", "add_problem": True})
    assert r.status_code == 200
    cid = r.json()["id"]
    assert nurse.patch(f"/api/consultations/{cid}", json={"plan": "x"}).status_code == 403
    assert gp.patch(f"/api/consultations/{cid}", json={"plan": "fluids", "sign": True}).status_code == 200
    assert gp.patch(f"/api/consultations/{cid}", json={"plan": "changed"}).status_code == 409
    assert gp.post(f"/api/consultations/{cid}/addenda", json={"text": "CXR requested"}).status_code == 200
    chart = gp.get(f"/api/patients/{patient['id']}").json()
    assert chart["consultations"][0]["addenda"][0]["text"] == "CXR requested"
    assert any(p["icpc2_code"] == "R05" for p in chart["problems"])


def test_clinical_text_encrypted_at_rest(gp, patient):
    gp.post(f"/api/patients/{patient['id']}/consultations", json={"subjective": "very private history"})
    with engine.connect() as conn:
        raw = conn.execute(text("select subjective from consultations")).scalar()
    assert "private" not in raw


def test_remote_consultation_needs_consent(gp, patient):
    r = gp.post(f"/api/patients/{patient['id']}/consultations", json={"mode": "video", "sign": True})
    assert r.status_code == 400
    r = gp.post(f"/api/patients/{patient['id']}/consultations",
                json={"mode": "video", "sign": True, "remote_consent_recorded": True, "remote_identity_verified": True})
    assert r.status_code == 200


def test_entered_in_error_and_move(gp, patient):
    other = gp.post("/api/patients", json={"first_name": "Máire", "last_name": "Ní Dhónaill", "dob": "1990-07-02",
                                           "sex": "female", "address1": "2 High St", "address2": "Tuam",
                                           "registered_gp_id": 1}).json()
    cid = gp.post(f"/api/patients/{patient['id']}/consultations", json={"subjective": "wrong patient"}).json()["id"]
    r = gp.post(f"/api/consultations/{cid}/entered-in-error", json={"reason": "wrong chart", "move_to_patient_id": other["id"]})
    assert r.json()["patient_id"] == other["id"]
    cid2 = gp.post(f"/api/patients/{patient['id']}/consultations", json={"subjective": "dup"}).json()["id"]
    assert gp.post(f"/api/consultations/{cid2}/entered-in-error", json={"reason": "duplicate"}).json()["entered_in_error"]


def _rx(client, pid, **item):
    base = {"drug_name": "Amoxicillin", "strength": "500mg", "form": "capsules",
            "dose_instructions": "1 three times daily", "quantity": "21"}
    return client.post(f"/api/patients/{pid}/prescriptions", json={"items": [{**base, **item}], "prescriber_id": 1})


def test_allergy_warning(gp, patient):
    gp.post(f"/api/patients/{patient['id']}/allergies", json={"substance": "Amoxicillin", "reaction": "rash"})
    r = _rx(gp, patient["id"]).json()
    assert r["saved"] is False and "ALLERGY" in r["warnings"][0]


def test_eprescription_rules(gp, nurse, patient, monkeypatch):
    sent = []
    monkeypatch.setattr(healthmail, "send", lambda msg, u, p: sent.append(msg))
    rx = _rx(nurse, patient["id"]).json()["prescription"]  # nurse can draft for GP review
    # Nurse (not a prescriber) cannot send
    assert nurse.post(f"/api/prescriptions/{rx['id']}/send-healthmail", json={}).status_code == 403
    # Non-Healthmail pharmacy address refused
    r = gp.post(f"/api/prescriptions/{rx['id']}/send-healthmail", json={"pharmacy_healthmail": "shop@gmail.com"})
    assert r.status_code == 400 and "secure Healthmail" in r.json()["detail"]
    r = gp.post(f"/api/prescriptions/{rx['id']}/send-healthmail", json={"pharmacy_healthmail": "pharm@healthmail.ie"})
    assert r.status_code == 200 and r.json()["status"] == "sent"
    assert sent[0]["To"] == "pharm@healthmail.ie" and sent[0]["From"] == "gp@healthmail.ie"
    pdf = [p for p in sent[0].iter_attachments()][0].get_content()
    assert pdf[:4] == b"%PDF"
    # OST never by electronic transfer
    ost = _rx(gp, patient["id"], drug_name="Methadone", is_ost=True, cd_schedule="CD2").json()["prescription"]
    r = gp.post(f"/api/prescriptions/{ost['id']}/send-healthmail", json={"pharmacy_healthmail": "pharm@healthmail.ie"})
    assert r.status_code == 400 and "Opiate Substitution" in r.json()["detail"]


def test_prescription_pdf(gp, patient):
    rx = _rx(gp, patient["id"]).json()["prescription"]
    r = gp.get(f"/api/prescriptions/{rx['id']}/pdf")
    assert r.status_code == 200 and r.content[:4] == b"%PDF"


def test_vaccination_checks(nurse, patient):
    pid = patient["id"]
    assert nurse.post(f"/api/patients/{pid}/immunisations", json={"vaccine": "Influenza"}).status_code == 400
    r = nurse.post(f"/api/patients/{pid}/immunisations",
                   json={"vaccine": "Influenza", "batch": "AB12", "expiry": "2020-01-01"})
    assert r.status_code == 400 and "expiry" in r.json()["detail"]
    future = (datetime.now() + timedelta(days=90)).date().isoformat()
    r = nurse.post(f"/api/patients/{pid}/immunisations",
                   json={"vaccine": "Influenza", "batch": "AB12", "expiry": future, "dose_number": 1})
    assert r.status_code == 200
    assert nurse.post(f"/api/patients/{pid}/immunisations", json={"vaccine": "COVID-19", "consent": "refused"}).status_code == 200


def test_cdm_flow(gp, patient):
    pid = patient["id"]
    gp.post(f"/api/patients/{pid}/problems", json={"icpc2_code": "T90"})
    gp.post(f"/api/patients/{pid}/observations", json={"kind": "weight_kg", "value": 90, "unit": "kg"})
    gp.post(f"/api/patients/{pid}/observations", json={"kind": "height_cm", "value": 180, "unit": "cm"})
    assert gp.post(f"/api/patients/{pid}/observations", json={"kind": "height_cm", "value": 1.8}).status_code == 400
    pre = gp.get(f"/api/patients/{pid}/cdm/prefill").json()
    assert pre["registers"] == ["t2dm"] and pre["data"]["bmi"] == 27.8
    assert gp.get(f"/api/patients/{pid}").json()["cdm"]["status"] == "red"
    r = gp.post(f"/api/patients/{pid}/cdm", json={"conditions": ["t2dm"], "data": pre["data"], "complete": True})
    assert r.status_code == 400  # incomplete returns are not allowed
    r = gp.post(f"/api/patients/{pid}/cdm", json={"conditions": ["t2dm"], "data": pre["data"]})
    assert r.json()["status"] == "started"
    assert gp.get(f"/api/patients/{pid}").json()["cdm"]["status"] == "orange"
    full = {f: "x" for f in irish.cdm_required_fields(["t2dm"])}
    r = gp.post(f"/api/patients/{pid}/cdm", json={"id": r.json()["id"], "conditions": ["t2dm"], "data": full, "complete": True})
    assert r.status_code == 200 and r.json()["status"] == "complete"
    assert gp.get(f"/api/patients/{pid}").json()["cdm"]["status"] == "green"
    assert len(gp.get("/api/claims").json()) == 1


def test_sick_cert(gp, patient):
    r = gp.post(f"/api/patients/{patient['id']}/sick-certs",
                json={"illness_text": "Lower back pain", "illness_code": "L03", "weeks": 2})
    assert r.status_code == 200
    assert gp.get(f"/api/sick-certs/{r.json()['id']}/pdf").content[:4] == b"%PDF"
    notes = gp.get(f"/api/patients/{patient['id']}").json()["consultations"]
    assert "Medical certificate" in notes[0]["plan"]


# ------------------------------------------------------------- Healthlink inbox

def test_healthlink_inbox_flow(gp, reception, patient, tmpdir_path):
    inbound = tmpdir_path / "hl" / "in"
    inbound.mkdir(parents=True, exist_ok=True)
    (inbound / "result1.hl7").write_text(ER7, encoding="utf-8")
    (inbound / "garbage.hl7").write_text("not hl7", encoding="utf-8")
    r = gp.post("/api/inbox/poll").json()
    assert r == {**r, "received": 1, "failed": 1}
    assert any(p.name.startswith("ACK_result1") for p in (tmpdir_path / "hl" / "out").iterdir())
    items = gp.get("/api/inbox").json()
    assert len(items) == 1 and items[0]["patient_id"] == patient["id"] and items[0]["abnormal"]
    mid = items[0]["id"]
    # Duplicate delivery is ignored
    (inbound / "again.hl7").write_text(ER7, encoding="utf-8")
    gp.post("/api/inbox/poll")
    assert len(gp.get("/api/inbox").json()) == 1
    # Reception cannot review results; GP can, which creates a task
    assert reception.post(f"/api/inbox/{mid}/review", json={"action": "normal"}).status_code == 403
    r = gp.post(f"/api/inbox/{mid}/review", json={"action": "book_appointment", "comment": "review HbA1c", "assign_to": 3})
    assert r.status_code == 200 and r.json()["status"] == "filed"
    assert len(reception.get("/api/tasks").json()) == 1
    chart = gp.get(f"/api/patients/{patient['id']}").json()
    assert chart["results"][0]["results"][0]["test_name"] == "HbA1c"


def test_unmatched_message_manual_match(gp, patient):
    raw = ER7.replace("Ó Briain^Seán", "Unknown^Person").replace("1234567T", "").replace("MSG0001", "MSG0002")
    gp.post("/api/inbox/upload", files={"file": ("x.hl7", raw, "text/plain")})
    um = gp.get("/api/inbox", params={"unmatched": True}).json()
    assert len(um) == 1
    assert gp.post(f"/api/inbox/{um[0]['id']}/review", json={"action": "normal"}).status_code == 400
    gp.post(f"/api/inbox/{um[0]['id']}/match", json={"patient_id": patient["id"]})
    assert gp.post(f"/api/inbox/{um[0]['id']}/review", json={"action": "normal"}).status_code == 200


def test_referral_written_to_healthlink(gp, patient, tmpdir_path):
    r = gp.post(f"/api/patients/{patient['id']}/referrals",
                json={"receiving_facility": "GUH", "reason": "Chest pain", "specialty": "Cardiology"})
    assert r.status_code == 200
    files = [p for p in (tmpdir_path / "hl" / "out").iterdir() if p.name.startswith("REF_")]
    assert files and "REF" in files[0].read_text()


# -------------------------------------------------------------- remote consults

def test_video_consultation_flow(gp, reception, patient):
    start = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
    a = reception.post("/api/appointments", json={"patient_id": patient["id"], "start": start, "mode": "video",
                                                  "clinician_id": 1}).json()
    assert reception.post(f"/api/appointments/{a['id']}/video").status_code == 403
    r = gp.post(f"/api/appointments/{a['id']}/video").json()
    assert r["clinician_url"].startswith("https://meet.test.ie/c-") and "jwt=" in r["clinician_url"]
    token = r["patient_url"].rsplit("/", 1)[1]
    page = TestClient(app).get(f"/v/{token}")
    assert page.status_code == 200 and "Join the consultation" in page.text and "not recorded" in page.text
    assert TestClient(app).get("/v/not-a-token").status_code == 410


def test_video_requires_consent(gp, patient):
    gp.patch(f"/api/patients/{patient['id']}", json={"consent_video": False})
    r = gp.post("/api/appointments", json={"patient_id": patient["id"], "start": datetime.now(timezone.utc).isoformat(),
                                           "mode": "video"})
    assert r.status_code == 400


# ------------------------------------------------------------------ governance

def test_subject_access_export(manager, gp, patient):
    gp.post(f"/api/patients/{patient['id']}/consultations", json={"subjective": "note"})
    r = manager.post("/api/dsr", json={"patient_id": patient["id"], "request_type": "access", "identity_verified": True})
    assert r.status_code == 200
    exp = manager.get(f"/api/patients/{patient['id']}/export").json()
    assert exp["patient"]["ppsn"] == "1234567T" and exp["consultations"][0]["subjective"] == "note"
    assert gp.get(f"/api/patients/{patient['id']}/export").status_code == 403  # governance role only


def test_breach_72h_deadline(manager):
    old = (datetime.now(timezone.utc) - timedelta(hours=80)).isoformat()
    manager.post("/api/breaches", json={"description": "Letter sent to wrong address", "detected_at": old, "risk": "risk"})
    assert manager.get("/api/breaches").json()[0]["dpc_overdue"] is True


def test_retention_report(manager, gp, patient):
    gp.post(f"/api/patients/{patient['id']}/deregister", json={"reason": "died", "deceased_date": "2010-01-01"})
    rows = manager.get("/api/reports/retention").json()
    assert rows and rows[0]["id"] == patient["id"]


def test_reports(gp, patient):
    assert gp.get("/api/reports/incomplete").status_code == 200
    gp.post("/api/patients", json={"first_name": "Orla", "last_name": "Brennan", "dob": "1985-05-30", "sex": "female",
                                   "address1": "3 Quay St", "address2": "Galway", "registered_gp_id": 1})
    assert any(r["name"] == "Brennan, Orla" for r in gp.get("/api/reports/cervical-screening").json())
