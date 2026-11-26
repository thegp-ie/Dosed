"""Reference data: clinical code lists (ICPC-2, ICD-10, ICD-11, SNOMED) and the medicines dictionary."""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit, formulary, terminology
from ..config import settings
from ..db import get_db
from ..models import MedicinalProduct, TerminologyCode, User
from ..security import client_ip, current_user, require

router = APIRouter(prefix="/api", tags=["reference"])


@router.get("/terminology/search")
def code_search(system: str = "ICPC2", q: str = "", user: User = Depends(current_user), db: Session = Depends(get_db)):
    if system.upper() not in terminology.SYSTEMS:
        raise HTTPException(400, "Unknown classification")
    return terminology.search(db, system, q)


@router.get("/icpc2")
def icpc2(q: str = "", user: User = Depends(current_user), db: Session = Depends(get_db)):
    return [{"code": r["code"], "title": r["title"]} for r in terminology.search(db, "ICPC2", q)]


@router.get("/reference/status")
def ref_status(user: User = Depends(current_user), db: Session = Depends(get_db)):
    codes = dict(db.execute(select(TerminologyCode.system, func.count()).group_by(TerminologyCode.system)).all())
    products = {src: {"count": n, "loaded_at": (at.isoformat() if at else None)} for src, n, at in db.execute(
        select(MedicinalProduct.source, func.count(), func.max(MedicinalProduct.loaded_at)).group_by(MedicinalProduct.source)).all()}
    return {"codes": {"ICPC2": "built-in subset", **codes}, "icd11_api": bool(settings.icd_api_url), "products": products}


@router.post("/terminology/load")
async def code_load(request: Request, system: str = Form(...), file: UploadFile = File(...),
                    user: User = Depends(require("reference.load")), db: Session = Depends(get_db)):
    text = (await file.read()).decode("utf-8-sig", errors="replace")
    try:
        n = terminology.load_codes(db, system, text, source=file.filename or "upload")
    except ValueError as e:
        raise HTTPException(400, str(e))
    audit.record(db, "terminology.load", user=user, detail={"system": system.upper(), "count": n, "file": file.filename},
                 ip=client_ip(request))
    return {"system": system.upper(), "loaded": n}


@router.get("/formulary/search")
def drug_search(q: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return [{"id": p.id, "name": p.name, "active_substances": p.active_substances, "strength": p.strength,
             "dosage_form": p.dosage_form, "route": p.route, "atc_code": p.atc_code,
             "supply_status": p.supply_status, "controlled_schedule": p.controlled_schedule,
             "licence_number": p.licence_number, "source": p.source} for p in formulary.search(db, q)]


@router.post("/formulary/load")
async def drug_load(request: Request, kind: str = Form(...), file: UploadFile = File(...),
                    user: User = Depends(require("reference.load")), db: Session = Depends(get_db)):
    data = await file.read()
    try:
        if kind == "hpra_xml":
            n = formulary.load_hpra_xml(db, data)
        elif kind in ("nmpc_csv", "csv"):
            n = formulary.load_csv(db, data.decode("utf-8-sig", errors="replace"), source="nmpc" if kind == "nmpc_csv" else "csv")
        else:
            raise HTTPException(400, "kind must be hpra_xml, nmpc_csv or csv")
    except Exception as e:  # malformed XML/CSV
        if isinstance(e, HTTPException):
            raise
        raise HTTPException(400, f"Could not read file: {e}")
    if n == 0:
        raise HTTPException(400, "No products found in the file. Check the format (see docs/TERMINOLOGY_AND_FORMULARY.md).")
    audit.record(db, "formulary.load", user=user, detail={"kind": kind, "count": n, "file": file.filename},
                 ip=client_ip(request))
    return {"loaded": n}
