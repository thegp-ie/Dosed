from datetime import date

from app import irish
from app.crypto import blind_index, decrypt, encrypt


def test_ppsn():
    assert irish.valid_ppsn("1234567T")
    assert irish.valid_ppsn("1234567 t")
    assert not irish.valid_ppsn("1234567A")
    assert not irish.valid_ppsn("123456T")
    # Second-letter (post-2013) format: 1234567 + ?A: 112 + 9*1 = 121 % 23 = 6 -> F
    assert irish.valid_ppsn("1234567FA")
    assert not irish.valid_ppsn("1234567TA")


def test_eircode():
    assert irish.normalise_eircode("d02x285") == "D02 X285"
    assert irish.normalise_eircode("D6W 1234") == "D6W 1234"
    assert irish.normalise_eircode("B12 3456") is None  # B is not a routing letter
    assert irish.normalise_eircode("H91 AB1") is None


def test_ihi():
    ihi = irish.make_test_ihi("987654321")
    r = irish.validate_ihi(ihi)
    assert r["valid"] and r["gs1_ok"] and r["mod11_ok"]
    assert len(ihi) == 18
    assert r["display"] == f"{ihi[7:10]}-{ihi[10:13]}-{ihi[13:17]}"
    bad = ihi[:17] + str((int(ihi[17]) + 1) % 10)
    assert not irish.validate_ihi(bad)["valid"]
    assert not irish.validate_ihi("123")["valid"]


def test_cdm_rules():
    assert irish.cdm_registers_for(["T90", "K86", "R96"]) == ["t2dm", "asthma"]
    fields = irish.cdm_required_fields(["t2dm"])
    assert "hba1c" in fields and "bp_systolic" in fields
    assert "hba1c" in irish.cdm_missing_fields(["t2dm"], {"bp_systolic": 130})


def test_cha2ds2_vasc():
    assert irish.cha2ds2_vasc(age=78, sex="female", chf=True, hypertension=True, stroke_tia=False,
                              vascular=False, diabetes=True) == 6


def test_retention():
    # Adult: 8 years after last contact
    assert irish.retention_until(dob=date(1960, 1, 1), last_contact=date(2020, 6, 1), deceased=None) == date(2028, 6, 1)
    # Child: until 25th birthday if later
    assert irish.retention_until(dob=date(2015, 1, 1), last_contact=date(2020, 6, 1), deceased=None) == date(2040, 1, 1)
    # Deceased: 8 years after death
    assert irish.retention_until(dob=date(1930, 1, 1), last_contact=date(2020, 1, 1), deceased=date(2021, 3, 3)) == date(2029, 3, 3)


def test_height_weight_validation():
    assert irish.plausible_height_weight(17.5, None, 40)  # metres entered as cm
    assert irish.plausible_height_weight(170, 70, 40) == []


def test_field_encryption():
    ct = encrypt("confidential note")
    assert "confidential" not in ct
    assert decrypt(ct) == "confidential note"
    assert encrypt("x") != encrypt("x")  # random nonce
    assert blind_index("1234567 t") == blind_index("1234567T")
