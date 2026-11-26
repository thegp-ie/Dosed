"""Irish identifiers, reference lists and clinical rules.

Sources are noted per function. Anything marked VERIFY depends on a specification we
have not seen in full and must be checked against it before certification.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime

# --------------------------------------------------------------------------- PPSN

_PPSN_RE = re.compile(r"^(\d{7})([A-W])([A-IW]?)$")
_PPSN_LETTERS = "WABCDEFGHIJKLMNOPQRSTUV"  # index 0 = W


def normalise_ppsn(value: str) -> str:
    return "".join(value.split()).upper()


def valid_ppsn(value: str) -> bool:
    """Personal Public Service Number: 7 digits, check letter, optional second letter.

    Check character = weighted sum (8..2 over the digits, plus 9 x value of the second
    letter, where A=1 and W=0) mod 23, mapped W,A,B,...,V.
    """
    m = _PPSN_RE.match(normalise_ppsn(value))
    if not m:
        return False
    digits, check, second = m.groups()
    total = sum(int(d) * w for d, w in zip(digits, range(8, 1, -1)))
    if second and second != "W":
        total += 9 * (ord(second) - ord("A") + 1)
    return _PPSN_LETTERS[total % 23] == check


def name_key(value: str | None) -> str:
    """Search key for names: fadas removed, lower case, apostrophes/hyphens dropped.
    So "Ó Briain", "o briain" and "O'Briain" all match."""
    if not value:
        return ""
    v = unicodedata.normalize("NFKD", value)
    v = "".join(ch for ch in v if not unicodedata.combining(ch)).lower()
    v = re.sub(r"[\'’`\-]", "", v)
    return " ".join(v.split())


# ------------------------------------------------------------------------ Eircode

_EIRCODE_RE = re.compile(r"^([AC-FHKNPRTV-Y]\d{2}|D6W)\s?([0-9AC-FHKNPRTV-Y]{4})$")


def normalise_eircode(value: str) -> str | None:
    m = _EIRCODE_RE.match(value.strip().upper())
    return f"{m.group(1)} {m.group(2)}" if m else None


# ------------------------------------------------------------------------- IHI

def _gs1_check_digit(body: str) -> int:
    """GS1 mod-10: weights 3,1,3,1... starting from the rightmost digit of the body."""
    total = sum(int(d) * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(body)))
    return (10 - total % 10) % 10


def _mod11_check_digit(core9: str) -> int | None:
    # VERIFY against "IHI GP, GMS Seeding Process" spec: weights assumed 10..2 (as in
    # other national health identifiers). Returns None where the remainder makes no digit.
    total = sum(int(d) * w for d, w in zip(core9, range(10, 1, -1)))
    check = 11 - (total % 11)
    if check == 11:
        return 0
    if check == 10:
        return None
    return check


def validate_ihi(value: str) -> dict:
    """Individual Health Identifier (GPIT RFC_2022 s.2.7).

    18 digits; position 17 is a modulus 11 check digit over the core number and
    position 18 a GS1 check digit. The GS1 check is enforced. The modulus 11 check is
    reported but not enforced until its weighting is confirmed (see _mod11_check_digit).
    """
    v = "".join(value.split())
    result = {"valid": False, "gs1_ok": False, "mod11_ok": None, "display": None, "error": None}
    if not re.fullmatch(r"\d{18}", v):
        result["error"] = "IHI must be 18 digits"
        return result
    result["gs1_ok"] = _gs1_check_digit(v[:17]) == int(v[17])
    m11 = _mod11_check_digit(v[7:16])
    result["mod11_ok"] = (m11 == int(v[16])) if m11 is not None else False
    result["display"] = ihi_display(v)
    result["valid"] = result["gs1_ok"]
    if not result["gs1_ok"]:
        result["error"] = "GS1 check digit (position 18) does not match"
    return result


def ihi_display(full18: str) -> str:
    """On-screen/print form: positions 8-17 (core + mod 11 digit) as 3-3-4 (RFC 2.7.6)."""
    core = full18[7:17]
    return f"{core[0:3]}-{core[3:6]}-{core[6:10]}"


def make_test_ihi(core9: str, prefix7: str = "3720000") -> str:
    """Build a structurally valid IHI for tests and demo data."""
    m11 = _mod11_check_digit(core9)
    if m11 is None:
        raise ValueError("core gives no mod 11 digit")
    body = prefix7 + core9 + str(m11)
    return body + str(_gs1_check_digit(body))


# --------------------------------------------------------------- reference lists

# Census 2016 ethnic groups, as listed in GPIT RFC_2022 Table 6.
ETHNICITY = [
    "White Irish", "Irish Traveller", "Other White", "Black Irish or African",
    "Other Black", "Chinese", "Other Asian", "Other", "Not stated",
]

PATIENT_TYPES = {"private": "Private", "gms": "GMS medical card", "dvc": "GP visit card", "other": "Other"}

# PCRS patient listing categories (RFC Table 16).
PCRS_CATEGORIES = [
    "Not Categorised", "Asylum Seeker", "Discretionary Medical Card", "New 70+",
    "70+ PN.Home", "70+ SM", "New 70+ PN.Home",
]

# A working subset of ICPC-2 (WONCA). Load the full licensed table in production.
ICPC2 = {
    "A03": "Fever", "A04": "Weakness/tiredness general", "A97": "No disease",
    "A98": "Health maintenance/prevention",
    "D01": "Abdominal pain/cramps general", "D11": "Diarrhoea",
    "D73": "Gastroenteritis presumed infection", "D84": "Oesophagus disease",
    "F70": "Conjunctivitis infectious", "H71": "Acute otitis media/myringitis",
    "K74": "Ischaemic heart disease with angina", "K75": "Acute myocardial infarction",
    "K76": "Ischaemic heart disease without angina", "K77": "Heart failure",
    "K78": "Atrial fibrillation/flutter", "K85": "Elevated blood pressure",
    "K86": "Hypertension uncomplicated", "K87": "Hypertension complicated",
    "K89": "Transient cerebral ischaemia", "K90": "Stroke/cerebrovascular accident",
    "L03": "Low back symptom/complaint", "L86": "Back syndrome with radiating pain",
    "L89": "Osteoarthrosis of hip", "L90": "Osteoarthrosis of knee",
    "N01": "Headache", "N89": "Migraine",
    "P06": "Sleep disturbance", "P74": "Anxiety disorder/anxiety state",
    "P76": "Depressive disorder",
    "R05": "Cough", "R74": "Upper respiratory infection acute", "R75": "Sinusitis acute/chronic",
    "R76": "Tonsillitis acute", "R78": "Acute bronchitis/bronchiolitis", "R80": "Influenza",
    "R81": "Pneumonia", "R95": "Chronic obstructive pulmonary disease", "R96": "Asthma",
    "S87": "Dermatitis/atopic eczema", "S88": "Dermatitis contact/allergic", "S96": "Acne",
    "T82": "Obesity", "T86": "Hypothyroidism/myxoedema", "T89": "Diabetes insulin dependent",
    "T90": "Diabetes non-insulin dependent", "T93": "Lipid disorder",
    "U71": "Cystitis/urinary infection other",
    "W11": "Family planning/oral contraceptive", "W78": "Pregnancy",
}


def search_icpc2(q: str, limit: int = 20) -> list[dict]:
    q = q.strip().lower()
    out = [
        {"code": c, "title": t} for c, t in ICPC2.items()
        if not q or q in c.lower() or q in t.lower()
    ]
    return out[:limit]


# ------------------------------------------------------- Chronic Disease Management

# Disease registers in the HSE structured CDM treatment programme (GP contract 2019,
# RFC 2.12) with the ICPC-2 codes that put a patient on each register.
CDM_REGISTERS = {
    "t2dm": {"title": "Type 2 diabetes", "icpc2": ["T90"]},
    "asthma": {"title": "Asthma", "icpc2": ["R96"]},
    "copd": {"title": "COPD", "icpc2": ["R95"]},
    "hf": {"title": "Heart failure", "icpc2": ["K77"]},
    "ihd": {"title": "Ischaemic heart disease", "icpc2": ["K74", "K75", "K76"]},
    "cvd": {"title": "Cerebrovascular disease", "icpc2": ["K89", "K90"]},
    "af": {"title": "Atrial fibrillation", "icpc2": ["K78"]},
}

# Fields every review must contain before the return can be queued (RFC 2.12.5).
# VERIFY against the Healthlink "GP contract" message specification before go-live.
CDM_COMMON_FIELDS = [
    "smoking_status", "alcohol_units_week", "physical_activity", "weight_kg", "height_cm",
    "bmi", "waist_cm", "pulse_rate", "pulse_rhythm", "bp_systolic", "bp_diastolic",
    "flu_vaccine_this_season", "pneumococcal_vaccine", "medication_review_done",
    "self_management_reviewed", "care_plan_agreed",
]
CDM_CONDITION_FIELDS = {
    "t2dm": ["hba1c", "total_cholesterol", "egfr", "urine_acr", "foot_exam", "retinopathy_screening"],
    "asthma": ["peak_flow", "inhaler_technique_checked", "asthma_control"],
    "copd": ["mrc_dyspnoea", "inhaler_technique_checked", "exacerbations_12m"],
    "hf": ["nyha_class", "egfr"],
    "ihd": ["total_cholesterol", "angina_symptoms"],
    "cvd": ["total_cholesterol"],
    "af": ["cha2ds2_vasc", "anticoagulated"],
}
# Observation kinds that can auto-populate a review if recorded in the last 6 months (RFC 2.12.3-4).
CDM_AUTOPOPULATE = {
    "weight_kg", "height_cm", "waist_cm", "pulse_rate", "bp_systolic", "bp_diastolic",
    "hba1c", "total_cholesterol", "egfr", "urine_acr", "peak_flow", "alcohol_units_week",
}


def cdm_registers_for(icpc2_codes: list[str]) -> list[str]:
    codes = set(icpc2_codes)
    return [k for k, v in CDM_REGISTERS.items() if codes.intersection(v["icpc2"])]


def cdm_required_fields(conditions: list[str]) -> list[str]:
    fields = list(CDM_COMMON_FIELDS)
    for c in conditions:
        for f in CDM_CONDITION_FIELDS.get(c, []):
            if f not in fields:
                fields.append(f)
    return fields


def cdm_missing_fields(conditions: list[str], data: dict) -> list[str]:
    return [f for f in cdm_required_fields(conditions) if data.get(f) in (None, "")]


# --------------------------------------------------------------- calculators

def age_on(dob: date, on: date | None = None) -> int:
    on = on or date.today()
    return on.year - dob.year - ((on.month, on.day) < (dob.month, dob.day))


def bmi(weight_kg: float, height_cm: float) -> float:
    if not (20 <= height_cm <= 250 and 1 <= weight_kg <= 400):
        raise ValueError("height/weight outside plausible range")
    return round(weight_kg / (height_cm / 100) ** 2, 1)


def plausible_height_weight(height_cm: float | None, weight_kg: float | None, age: int) -> list[str]:
    """Input validation required for under-6 and cycle-of-care returns (RFC 2.5.5)."""
    errs = []
    if height_cm is not None and not (30 <= height_cm <= 250):
        errs.append("height must be 30-250 cm")
    if weight_kg is not None and not (0.4 <= weight_kg <= 400):
        errs.append("weight must be 0.4-400 kg")
    if age >= 18 and height_cm is not None and height_cm < 100:
        errs.append("adult height under 100 cm: check units")
    return errs


def cha2ds2_vasc(*, age: int, sex: str, chf: bool, hypertension: bool, stroke_tia: bool,
                 vascular: bool, diabetes: bool) -> int:
    score = 0
    score += 1 if chf else 0
    score += 1 if hypertension else 0
    score += 2 if age >= 75 else (1 if age >= 65 else 0)
    score += 1 if diabetes else 0
    score += 2 if stroke_tia else 0
    score += 1 if vascular else 0
    score += 1 if sex == "female" else 0
    return score


# -------------------------------------------------------------------- retention

def retention_until(*, dob: date, last_contact: date | None, deceased: date | None,
                    min_years_after: int = 8) -> date:
    """Earliest date a record may be *reviewed* for destruction.

    Based on HSE record-retention guidance as summarised by Medical Protection (Ireland):
    adults 8 years after last contact; children until their 25th birthday or 8 years
    after last contact, whichever is later; deceased 8 years after death. Records are
    never destroyed automatically: a GP must review each one (and may keep it longer
    where that is in the patient's interest, e.g. litigation, mental health, genetics).
    """
    def add_years(d: date, n: int) -> date:
        try:
            return d.replace(year=d.year + n)
        except ValueError:  # 29 Feb
            return d.replace(year=d.year + n, day=28)

    if deceased:
        return add_years(deceased, min_years_after)
    last = last_contact or date.today()
    candidates = [add_years(last, min_years_after)]
    if age_on(dob, last) < 18:
        candidates.append(add_years(dob, 25))
    return max(candidates)


def to_date(v) -> date | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.date()
    return v
