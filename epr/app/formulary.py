"""Medicines dictionary for prescribing.

Sources:
- HPRA "Human Medicines - Authorised Products" XML listing: free (published by the HPRA and on
  data.gov.ie). Every medicine authorised in Ireland: names, licence numbers, substances,
  forms. It is a product register, not a clinical formulary: no doses, interactions or GMS
  reimbursement status.
- HSE National Medicinal Product Catalogue (NMPC): national catalogue (CSV / NDJSON / FHIR
  terminology) under the NMPC downstream user licence. Load its CSV export through
  load_csv() once the practice or vendor holds that licence.
- Irish Medicines Formulary, MIMS Ireland: commercial; not loaded here.

The HPRA XML element names are matched loosely (case-insensitive, several aliases)
because we could not inspect the current file. VERIFY the mapping against a downloaded
copy before go-live; unmatched files load zero products and say so.
"""
from __future__ import annotations

import csv
import io
import xml.etree.ElementTree as ET
from collections import Counter

from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from .irish import name_key
from .models import MedicinalProduct

FIELD_ALIASES = {
    "name": ("productname", "tradename", "medicinename", "name"),
    "licence_number": ("licencenumber", "licensenumber", "authorisationnumber", "panumber", "pa_number", "pano"),
    "licence_holder": ("licenceholder", "licenseholder", "marketingauthorisationholder", "mah", "holder"),
    "active_substances": ("activesubstances", "activesubstance", "activeingredients", "activeingredient",
                          "substancename", "ingredient", "substance"),
    "strength": ("strength", "strengths", "productstrength"),
    "dosage_form": ("dosageform", "pharmaceuticalform", "doseform", "form"),
    "route": ("routeofadministration", "routesofadministration", "route", "routes"),
    "atc_code": ("atccode", "atc", "atccodes"),
    "supply_status": ("supplystatus", "legalstatus", "dispensingstatus", "prescriptionstatus", "supplytype"),
    "controlled_schedule": ("controlleddrugschedule", "cdschedule", "controlleddrug", "schedule"),
}


def _local(tag: str) -> str:
    return tag.split("}", 1)[-1].lower().replace("-", "").replace("_", "").replace(" ", "")


def _flatten(el) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for d in el.iter():
        if d is el:
            continue
        text = (d.text or "").strip()
        if text and len(d) == 0:
            out.setdefault(_local(d.tag), []).append(text)
        for k, v in d.attrib.items():
            if v.strip():
                out.setdefault(_local(k), []).append(v.strip())
    return out


def _pick(flat: dict[str, list[str]], field: str) -> str | None:
    for alias in FIELD_ALIASES[field]:
        vals = flat.get(alias.replace("_", ""))
        if vals:
            uniq = list(dict.fromkeys(vals))
            return (" + " if field == "active_substances" else ", ").join(uniq)[:500]
    return None


def _normalise_cd(v: str | None) -> str | None:
    if not v:
        return None
    digits = "".join(ch for ch in v if ch.isdigit())
    return f"CD{digits[0]}" if digits and digits[0] in "12345" else None


def parse_hpra_xml(data: bytes) -> list[dict]:
    root = ET.fromstring(data)
    # The product record is the most common element that has child elements.
    counts = Counter(_local(e.tag) for e in root.iter() if len(e) > 0 and e is not root)
    if not counts:
        return []
    record_tag = counts.most_common(1)[0][0]
    rows = []
    for el in root.iter():
        if _local(el.tag) != record_tag:
            continue
        flat = _flatten(el)
        row = {f: _pick(flat, f) for f in FIELD_ALIASES}
        if row["name"]:
            row["controlled_schedule"] = _normalise_cd(row["controlled_schedule"])
            rows.append(row)
    return rows


def _store(db: Session, rows: list[dict], source: str) -> int:
    db.execute(delete(MedicinalProduct).where(MedicinalProduct.source == source))
    seen = set()
    n = 0
    for r in rows:
        key = (r.get("licence_number"), r["name"])
        if key in seen:
            continue
        seen.add(key)
        db.add(MedicinalProduct(
            name=r["name"][:300], name_key=name_key(r["name"])[:300],
            active_substances=r.get("active_substances"), strength=(r.get("strength") or None),
            dosage_form=r.get("dosage_form"), route=r.get("route"),
            atc_code=(r.get("atc_code") or "").split(",")[0].strip().upper() or None,
            licence_number=r.get("licence_number"), licence_holder=r.get("licence_holder"),
            supply_status=r.get("supply_status"), controlled_schedule=r.get("controlled_schedule"),
            interchangeable_group=r.get("interchangeable_group"), source=source))
        n += 1
    db.commit()
    return n


def load_hpra_xml(db: Session, data: bytes) -> int:
    return _store(db, parse_hpra_xml(data), "hpra")


CSV_COLUMNS = ["name", "active_substances", "strength", "dosage_form", "route", "atc_code",
               "licence_number", "licence_holder", "supply_status", "controlled_schedule",
               "interchangeable_group"]


def load_csv(db: Session, text: str, source: str = "csv") -> int:
    """CSV with a header using (some of) CSV_COLUMNS; 'name' is required."""
    reader = csv.DictReader(io.StringIO(text))
    rows = []
    for raw in reader:
        r = {k.strip().lower(): (v or "").strip() for k, v in raw.items() if k}
        if not r.get("name"):
            continue
        row = {c: (r.get(c) or None) for c in CSV_COLUMNS}
        row["controlled_schedule"] = _normalise_cd(row["controlled_schedule"])
        rows.append(row)
    return _store(db, rows, source)


def search(db: Session, q: str, limit: int = 25) -> list[MedicinalProduct]:
    tokens = name_key(q).split()
    if not tokens:
        return []
    from sqlalchemy import and_
    stmt = select(MedicinalProduct).where(or_(
        and_(*[MedicinalProduct.name_key.contains(t) for t in tokens]),
        func.lower(MedicinalProduct.active_substances).contains(tokens[0])))
    return list(db.execute(stmt.order_by(MedicinalProduct.name).limit(limit)).scalars())


def find_by_name(db: Session, drug_name: str) -> MedicinalProduct | None:
    k = name_key(drug_name)
    if not k:
        return None
    return db.execute(select(MedicinalProduct).where(MedicinalProduct.name_key == k).limit(1)).scalar_one_or_none() \
        or db.execute(select(MedicinalProduct).where(MedicinalProduct.name_key.startswith(k)).limit(1)).scalar_one_or_none()


# Drug classes for allergy cross-checking. ATC prefixes are WHO ATC; names are a fallback
# for when no dictionary is loaded. A licensed knowledge base should replace this.
ALLERGY_CLASSES = {
    "penicillin": {"atc": ("J01C",), "names": ("amoxicillin", "amoxycillin", "co-amoxiclav", "flucloxacillin",
                   "phenoxymethylpenicillin", "benzylpenicillin", "piperacillin", "ampicillin", "pivmecillinam",
                   "augmentin", "penicillin")},
    "cephalosporin": {"atc": ("J01D",), "names": ("cefalexin", "cephalexin", "cefuroxime", "cefaclor", "ceftriaxone",
                      "cefradine", "cefixime", "cefotaxime")},
    "sulfonamide": {"atc": ("J01E",), "names": ("trimethoprim/sulfamethoxazole", "co-trimoxazole", "sulfamethoxazole")},
    "nsaid": {"atc": ("M01A",), "names": ("ibuprofen", "naproxen", "diclofenac", "mefenamic", "etoricoxib",
              "celecoxib", "ketoprofen", "indometacin", "piroxicam")},
    "aspirin": {"atc": ("B01AC06", "N02BA01"), "names": ("aspirin", "acetylsalicylic")},
    "opioid": {"atc": ("N02A",), "names": ("codeine", "morphine", "oxycodone", "tramadol", "tapentadol",
               "fentanyl", "dihydrocodeine", "buprenorphine")},
}
_CLASS_ALIASES = {"penicillins": "penicillin", "pcn": "penicillin", "cephalosporins": "cephalosporin",
                  "sulpha": "sulfonamide", "sulfa": "sulfonamide", "sulphonamide": "sulfonamide",
                  "nsaids": "nsaid", "anti-inflammatories": "nsaid", "opiates": "opioid", "opioids": "opioid"}


def allergy_matches(allergy: str, drug_name: str, product: MedicinalProduct | None) -> bool:
    a = name_key(allergy)
    d = name_key(drug_name)
    if not a or not d:
        return False
    if a in d or d.split(" ")[0] in a:
        return True
    if product and product.active_substances and a in name_key(product.active_substances):
        return True
    cls = ALLERGY_CLASSES.get(_CLASS_ALIASES.get(a, a))
    if not cls:
        # e.g. allergy recorded as "amoxicillin": treat as the whole class it belongs to
        for c in ALLERGY_CLASSES.values():
            if any(name_key(n) in a for n in c["names"]):
                cls = c
                break
    if not cls:
        return False
    if any(name_key(n) in d for n in cls["names"]):
        return True
    return bool(product and product.atc_code and product.atc_code.startswith(cls["atc"]))
