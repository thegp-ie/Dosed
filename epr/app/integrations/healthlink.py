"""Healthlink (national GP message broker) integration.

Transport: Healthlink is reached through its web services once a vendor is GPIT
certified and onboarded (RFC_2022 s.2.0). Until then, and in many practices anyway, a
file-drop bridge is used: inbound HL7 files land in a folder and outbound files are
written to another. DirectoryTransport implements that. A web-service transport can be
added behind the same two methods once Healthlink issues credentials and the WSDL.

Inbound flow (RFC DC.1.8.3): message -> parsed -> matched to a patient -> shown in the
clinician inbox *before* being filed into the record -> reviewed with an action ->
filed. Unmatched messages wait in a queue for manual matching. An ACK is written for
every message received.
"""
from __future__ import annotations

import os
import shutil
from datetime import date
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..config import settings
from ..crypto import blind_index
from ..irish import name_key
from ..models import InboxMessage, LabResult, OutboundMessage, Patient
from . import hl7


class DirectoryTransport:
    def __init__(self, inbound: str, outbound: str, archive: str):
        self.inbound, self.outbound, self.archive = Path(inbound), Path(outbound), Path(archive)

    def ensure(self) -> None:
        for d in (self.inbound, self.outbound, self.archive, self.archive / "failed"):
            d.mkdir(parents=True, exist_ok=True)

    def pending(self) -> list[Path]:
        self.ensure()
        return sorted(p for p in self.inbound.iterdir() if p.is_file() and not p.name.startswith("."))

    def done(self, path: Path, failed: bool = False) -> None:
        dest = (self.archive / "failed" if failed else self.archive) / path.name
        shutil.move(str(path), str(dest))

    def send(self, name: str, content: str) -> Path:
        self.ensure()
        tmp = self.outbound / f".{name}.tmp"
        tmp.write_text(content, encoding="utf-8")
        final = self.outbound / name
        os.replace(tmp, final)  # atomic, so the bridge never picks up a half-written file
        return final


def transport() -> DirectoryTransport | None:
    if settings.healthlink_mode != "directory":
        return None
    return DirectoryTransport(settings.healthlink_inbound_dir, settings.healthlink_outbound_dir,
                              settings.healthlink_archive_dir)


def match_patient(db: Session, info: dict) -> tuple[Patient | None, str]:
    """Match on PPSN (blind index) first, then exact surname + first name + DOB.

    Only a single unambiguous match is accepted; anything else goes to manual matching.
    IHI matching is added when IHIs are present (they are encrypted, so compare in Python
    for the small candidate set from name/DOB).
    """
    for i in info.get("ids", []):
        t = (i.get("type") or "").upper()
        if t in ("PPSN", "PPS", "SS") and i.get("id"):
            hits = db.execute(select(Patient).where(Patient.ppsn_index == blind_index(i["id"]))).scalars().all()
            if len(hits) == 1:
                return hits[0], "matched"
    if info.get("family") and info.get("dob"):
        q = select(Patient).where(
            Patient.last_name_key == name_key(info["family"]),
            Patient.dob == info["dob"],
            Patient.record_status == "active",
        )
        hits = db.execute(q).scalars().all()
        ihis = {i["id"] for i in info.get("ids", []) if (i.get("type") or "").upper() == "IHI"}
        if ihis:
            by_ihi = [p for p in hits if p.ihi and p.ihi in ihis]
            if len(by_ihi) == 1:
                return by_ihi[0], "matched"
        given = name_key(info.get("given"))
        if given:
            hits = [p for p in hits if p.first_name_key == given]
        if len(hits) == 1:
            return hits[0], "matched"
    return None, "unmatched"


def ingest(db: Session, raw: str, source: str = "healthlink") -> tuple[InboxMessage | None, str]:
    """Store one inbound message. Returns (message, ack_code). Duplicates are ignored."""
    msg = hl7.parse(raw)
    mtype = msg.message_type
    if mtype.startswith("ACK"):
        handle_ack(db, msg)
        return None, "AA"
    cid = msg.control_id or None
    if cid and db.execute(select(InboxMessage).where(
            InboxMessage.source == source, InboxMessage.control_id == cid)).scalar_one_or_none():
        return None, "AA"  # already received; re-ACK so the sender stops retrying
    info = hl7.patient_from(msg)
    patient, status = match_patient(db, info)
    results = hl7.results_from(msg)
    narrative = hl7.narrative_from(msg)
    msh = msg.first("MSH")
    summary = hl7.summarise(msg)
    if narrative:
        summary = summary + "\n\n" + narrative
    m = InboxMessage(
        source=source, message_type=mtype or "unknown", control_id=cid,
        sender=msh.get(4, 1) if msh else None, raw=raw, summary=summary,
        patient_id=patient.id if patient else None, match_status=status,
        match_hint=f"{info.get('family', '')}, {info.get('given', '')} DOB {info.get('dob')} {info.get('address', '')}",
        assigned_to=patient.usual_gp_id if patient else None,
        abnormal=any(r["flag"] and r["flag"].upper() not in ("N",) for r in results),
    )
    for r in results:
        m.results.append(LabResult(
            patient_id=m.patient_id, test_code=r["code"], test_name=r["name"] or r["code"] or "result",
            value=r["value"], units=r["units"], reference_range=r["range"], abnormal_flag=r["flag"] or None,
            observed_at=r["observed_at"],
        ))
    db.add(m)
    db.flush()
    audit.record(db, "inbox.receive", patient_id=m.patient_id, entity="inbox", entity_id=m.id,
                 detail={"type": mtype, "match": status, "source": source}, commit=False)
    db.commit()
    return m, "AA"


def handle_ack(db: Session, msg: hl7.Message) -> None:
    info = hl7.ack_info(msg)
    if not info["control_id"]:
        return
    out = db.execute(select(OutboundMessage).where(OutboundMessage.subject == info["control_id"])).scalar_one_or_none()
    if out:
        out.status = "accepted" if info["code"] in ("AA", "CA") else "rejected"
        out.error = "; ".join(info["errors"]) or info["text"] or None
        audit.record(db, "healthlink.ack", patient_id=out.patient_id, entity="outbound", entity_id=out.id,
                     detail=info, commit=False)
        db.commit()


def poll(db: Session) -> dict:
    t = transport()
    if not t:
        return {"enabled": False}
    received, failed = 0, 0
    for path in t.pending():
        try:
            raw = path.read_text(encoding="utf-8", errors="replace")
            msg = hl7.parse(raw)
            _, code = ingest(db, raw)
            t.send(f"ACK_{path.stem}.hl7", hl7.build_ack_er7(
                msg, code, sending_facility=settings.practice_healthlink_id))
            t.done(path)
            received += 1
        except Exception as exc:  # keep going; bad files are quarantined
            db.rollback()
            audit.record(db, "inbox.receive_failed", detail={"file": path.name, "error": str(exc)[:300]})
            t.done(path, failed=True)
            failed += 1
    return {"enabled": True, "received": received, "failed": failed, "checked_on": date.today().isoformat()}
