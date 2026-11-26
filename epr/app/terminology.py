"""Clinical code lists: ICD-10, ICD-11 and SNOMED CT subsets (alongside ICPC-2 in irish.py).

Licensing (see docs/TERMINOLOGY_AND_FORMULARY.md):
- ICD-11: free under CC BY-ND 3.0 IGO, commercial use allowed, no adaptation of the codes.
  WHO also publishes a locally deployable ICD-API container, so search stays on-premises.
- ICD-10: WHO copyright; obtain the data file under a WHO licence (or via the HSE/HPO).
- SNOMED CT Irish Edition: free affiliate licence from the HSE National Release Centre.
Nothing is bundled; the practice loads files it is licensed to use.
"""
from __future__ import annotations

import csv
import io
import re

import httpx
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .config import settings
from .irish import ICPC2, name_key
from .models import TerminologyCode

SYSTEMS = ("ICPC2", "ICD10", "ICD11", "SNOMED")

_FORMAT = {
    "ICD10": re.compile(r"^[A-Z][0-9][0-9A-Z](\.[0-9A-Z]{1,4})?$"),
    "ICD11": re.compile(r"^[0-9A-Z]{4}(\.[0-9A-Z]{1,2})?$|^X[A-Z0-9]{3,6}$"),
    "SNOMED": re.compile(r"^\d{6,18}$"),
}


def load_codes(db: Session, system: str, text: str, source: str) -> int:
    """Load a code list from CSV/TSV text, replacing earlier codes for that system.

    Accepts a header with a code column (code / Code / theCode) and a title column
    (title / Title / description / term). WHO ICD-11 "linearization mini output" TSVs work:
    leading "- " depth markers in titles are stripped and rows without a code are skipped.
    """
    system = system.upper()
    if system not in ("ICD10", "ICD11", "SNOMED"):
        raise ValueError("system must be ICD10, ICD11 or SNOMED")
    sample = text[:4096]
    dialect = "excel-tab" if sample.count("\t") > sample.count(",") else "excel"
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    cols = {c.lower().strip(): c for c in (reader.fieldnames or [])}
    code_col = next((cols[c] for c in ("code", "thecode", "conceptid", "id") if c in cols), None)
    title_col = next((cols[c] for c in ("title", "description", "term", "label") if c in cols), None)
    if not code_col or not title_col:
        raise ValueError("File needs a code column and a title/description column")
    db.execute(delete(TerminologyCode).where(TerminologyCode.system == system))
    seen, n = set(), 0
    for row in reader:
        code = (row.get(code_col) or "").strip().upper()
        title = re.sub(r"^[-\s]+", "", (row.get(title_col) or "").strip())
        if not code or not title or code in seen:
            continue
        seen.add(code)
        db.add(TerminologyCode(system=system, code=code, title=title[:400], title_key=name_key(title)[:400],
                               source=source))
        n += 1
    db.commit()
    return n


def _api_search(q: str, limit: int) -> list[dict]:
    """Search ICD-11 on the practice's own WHO ICD-API container (no PII is sent: only the search text)."""
    url = f"{settings.icd_api_url.rstrip('/')}/icd/release/11/{settings.icd11_release}/mms/search"
    r = httpx.get(url, params={"q": q, "flatResults": "true"}, timeout=10,
                  headers={"Accept": "application/json", "API-Version": "v2", "Accept-Language": "en"})
    r.raise_for_status()
    out = []
    for e in (r.json().get("destinationEntities") or [])[:limit]:
        if e.get("theCode"):
            out.append({"system": "ICD11", "code": e["theCode"],
                        "title": re.sub(r"<[^>]+>", "", e.get("title") or "")})
    return out


def search(db: Session, system: str, q: str, limit: int = 20) -> list[dict]:
    system = system.upper()
    q = q.strip()
    if system == "ICPC2":
        k = name_key(q)
        return [{"system": "ICPC2", "code": c, "title": t} for c, t in ICPC2.items()
                if not q or q.upper() in c or k in name_key(t)][:limit]
    if system == "ICD11" and settings.icd_api_url and q:
        try:
            return _api_search(q, limit)
        except httpx.HTTPError:
            pass  # fall back to any loaded codes
    stmt = select(TerminologyCode).where(TerminologyCode.system == system)
    if q:
        tokens = name_key(q).split()
        code_like = q.upper().replace(" ", "")
        from sqlalchemy import and_, or_
        stmt = stmt.where(or_(TerminologyCode.code.startswith(code_like),
                              and_(*[TerminologyCode.title_key.contains(t) for t in tokens])))
    rows = db.execute(stmt.order_by(TerminologyCode.code).limit(limit)).scalars()
    return [{"system": system, "code": r.code, "title": r.title} for r in rows]


def validate(db: Session, system: str | None, code: str | None) -> tuple[str | None, str | None, str | None]:
    """Return (system, code, title). Raises ValueError for a bad code.

    If a code list is loaded for the system, the code must be in it. Otherwise only the
    format is checked and the title comes back as None (shown as "unverified").
    """
    if not code:
        return None, None, None
    system = (system or "").upper()
    code = code.strip().upper()
    if system not in ("ICD10", "ICD11", "SNOMED"):
        raise ValueError("Classification must be ICD10, ICD11 or SNOMED")
    if not _FORMAT[system].match(code):
        raise ValueError(f"{code} is not a valid {system} code format")
    loaded = db.execute(select(TerminologyCode.id).where(TerminologyCode.system == system).limit(1)).first()
    if loaded:
        row = db.execute(select(TerminologyCode).where(TerminologyCode.system == system,
                                                       TerminologyCode.code == code)).scalar_one_or_none()
        if not row:
            raise ValueError(f"{code} is not in the loaded {system} code list")
        return system, code, row.title
    return system, code, None
