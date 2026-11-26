"""HL7 v2.4 parsing and building.

Healthlink exchanges HL7 v2.4 messages, mostly in XML encoding (HIQA GP Messaging
Standard); some feeds use classic pipe-delimited (ER7) encoding. Both are parsed into
the same Message model so the rest of the system does not care which arrived.

This is a tolerant reader for the segments a GP system needs (MSH, PID, PV1, ORC, OBR,
OBX, NTE, MSA, ERR). Outbound messages must follow the specific Healthlink message
construction guides; the builders here produce the generic structure and are marked
VERIFY where a Healthlink guide adds constraints.
"""
from __future__ import annotations

import re
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from xml.sax.saxutils import escape as _xml_escape


def escape(v) -> str:
    return _xml_escape(str(v)) if v not in (None, "") else ""

_SEG_RE = re.compile(r"^[A-Z][A-Z0-9]{2}$")


@dataclass
class Segment:
    name: str
    # fields[n] -> list of repetitions -> list of components. fields[0] is the segment name.
    fields: list[list[list[str]]] = field(default_factory=list)

    def get(self, fld: int, comp: int = 1, rep: int = 0) -> str:
        try:
            v = self.fields[fld][rep][comp - 1]
        except IndexError:
            return ""
        return v or ""

    def reps(self, fld: int) -> list[list[str]]:
        try:
            return self.fields[fld]
        except IndexError:
            return []


@dataclass
class Message:
    segments: list[Segment]
    encoding: str  # "er7" | "xml"

    def all(self, name: str) -> list[Segment]:
        return [s for s in self.segments if s.name == name]

    def first(self, name: str) -> Segment | None:
        for s in self.segments:
            if s.name == name:
                return s
        return None

    @property
    def message_type(self) -> str:
        msh = self.first("MSH")
        if not msh:
            return ""
        t, trig = msh.get(9, 1), msh.get(9, 2)
        return f"{t}^{trig}" if trig else t

    @property
    def control_id(self) -> str:
        msh = self.first("MSH")
        return msh.get(10) if msh else ""


# ----------------------------------------------------------------------- parsing

def parse(raw: str) -> Message:
    text = raw.lstrip("﻿").strip()
    if text.startswith("<"):
        return _parse_xml(text)
    return _parse_er7(text)


def _parse_er7(text: str) -> Message:
    lines = [l for l in re.split(r"\r\n|\r|\n", text) if l.strip()]
    if not lines or not lines[0].startswith("MSH"):
        raise ValueError("Not an HL7 v2 message (no MSH segment)")
    fs = lines[0][3]
    enc = lines[0][4:8] if len(lines[0]) >= 8 else "^~\\&"
    cs, rs = enc[0], enc[1]
    segs: list[Segment] = []
    for line in lines:
        parts = line.split(fs)
        name = parts[0]
        if name == "MSH":
            # MSH-1 is the field separator itself; MSH-2 the encoding characters.
            parts = ["MSH", fs, enc] + parts[2:]
            fields = [[[p]] for p in parts[:3]]
            rest = parts[3:]
        else:
            fields = [[[name]]]
            rest = parts[1:]
        for p in rest:
            fields.append([r.split(cs) for r in p.split(rs)] if p else [[""]])
        segs.append(Segment(name, fields))
    return Message(segs, "er7")


def _local(tag: str) -> str:
    return tag.split("}", 1)[-1]


def _parse_xml(text: str) -> Message:
    root = ET.fromstring(text)
    segs: list[Segment] = []

    def walk(el):
        name = _local(el.tag)
        if _SEG_RE.match(name) and "." not in name:
            segs.append(_xml_segment(name, el))
            return
        for child in el:
            walk(child)

    walk(root)
    if not segs or segs[0].name != "MSH":
        raise ValueError("Not an HL7 v2 XML message (no MSH segment)")
    return Message(segs, "xml")


def _xml_segment(name: str, el) -> Segment:
    fields: list[list[list[str]]] = [[[name]]]
    for f in el:
        tag = _local(f.tag)
        m = re.match(rf"^{name}\.(\d+)$", tag)
        if not m:
            continue
        idx = int(m.group(1))
        while len(fields) <= idx:
            fields.append([])
        comps: list[str] = []
        children = list(f)
        if children:
            for c in children:
                cm = re.match(r"^[A-Z0-9]+\.(\d+)$", _local(c.tag))
                if not cm:
                    continue
                ci = int(cm.group(1))
                while len(comps) < ci:
                    comps.append("")
                sub = list(c)
                comps[ci - 1] = "&".join((s.text or "") for s in sub) if sub else (c.text or "")
        else:
            comps = [f.text or ""]
        fields[idx].append(comps)
    fields = [r if r else [[""]] for r in fields]
    return Segment(name, fields)


# -------------------------------------------------------------------- extraction

def hl7_date(v: str) -> date | None:
    v = (v or "").strip()
    if len(v) >= 8 and v[:8].isdigit():
        try:
            return date(int(v[:4]), int(v[4:6]), int(v[6:8]))
        except ValueError:
            return None
    return None


def hl7_datetime(v: str) -> datetime | None:
    v = (v or "").strip()
    m = re.match(r"^(\d{4})(\d{2})(\d{2})(\d{2})?(\d{2})?(\d{2})?", v)
    if not m:
        return None
    parts = [int(x) if x else 0 for x in m.groups()]
    try:
        return datetime(*parts, tzinfo=timezone.utc)
    except ValueError:
        return None


def patient_from(msg: Message) -> dict:
    pid = msg.first("PID")
    if not pid:
        return {}
    ids = []
    for rep in pid.reps(3) + pid.reps(2) + pid.reps(4):
        if rep and rep[0]:
            ids.append({"id": rep[0], "type": rep[4] if len(rep) > 4 else "",
                        "authority": rep[3] if len(rep) > 3 else ""})
    addr = pid.reps(11)[0] if pid.reps(11) else []
    return {
        "family": pid.get(5, 1), "given": pid.get(5, 2), "dob": hl7_date(pid.get(7)),
        "sex": {"F": "female", "M": "male"}.get(pid.get(8).upper(), "unknown"),
        "ids": ids, "address": ", ".join(a for a in addr[:5] if a),
    }


def results_from(msg: Message) -> list[dict]:
    out = []
    current_obr = None
    for s in msg.segments:
        if s.name == "OBR":
            current_obr = s
        elif s.name == "OBX":
            vtype = s.get(2)
            if vtype in ("TX", "FT", "ST") and not s.get(6) and not s.get(7):
                continue  # narrative lines are handled by narrative_from
            out.append({
                "code": s.get(3, 1), "name": s.get(3, 2) or s.get(3, 1),
                "value": "^".join(c for c in s.reps(5)[0] if c) if s.reps(5) else "",
                "units": s.get(6, 1), "range": s.get(7), "flag": s.get(8),
                "observed_at": hl7_datetime(s.get(14)) or (hl7_datetime(current_obr.get(7)) if current_obr else None),
                "panel": current_obr.get(4, 2) if current_obr else "",
            })
    return out


def narrative_from(msg: Message) -> str:
    lines = []
    for s in msg.segments:
        if s.name == "OBX" and s.get(2) in ("TX", "FT", "ST") and not s.get(6):
            for rep in s.reps(5):
                lines.append("^".join(c for c in rep if c))
        elif s.name == "NTE":
            for rep in s.reps(3):
                lines.append("^".join(c for c in rep if c))
    return "\n".join(l.replace("\\.br\\", "\n") for l in lines).strip()


def summarise(msg: Message) -> str:
    msh = msg.first("MSH")
    sender = msh.get(4, 1) if msh else ""
    obr = msg.first("OBR")
    title = (obr.get(4, 2) or obr.get(4, 1)) if obr else ""
    abn = sum(1 for r in results_from(msg) if r["flag"] and r["flag"].upper() not in ("N", ""))
    bits = [msg.message_type, title or "", f"from {sender}" if sender else ""]
    if abn:
        bits.append(f"{abn} abnormal")
    return " · ".join(b for b in bits if b)


def ack_info(msg: Message) -> dict:
    """Read an ACK (MSA/ERR) for a message we sent: AA accept, AE error, AR reject."""
    msa = msg.first("MSA")
    errs = []
    for e in msg.all("ERR"):
        errs.append(" ".join(x for x in (e.get(3, 2), e.get(8), e.get(1, 4)) if x) or "error")
    return {"code": msa.get(1) if msa else "", "control_id": msa.get(2) if msa else "",
            "text": msa.get(3) if msa else "", "errors": errs}


# ---------------------------------------------------------------------- building

def _ts(d: datetime | None = None) -> str:
    return (d or datetime.now(timezone.utc)).strftime("%Y%m%d%H%M%S")


def build_ack_er7(msg: Message, code: str = "AA", text: str = "", sending_app: str = "EPR",
                  sending_facility: str = "") -> str:
    msh = msg.first("MSH")
    segs = [
        "|".join(["MSH", "^~\\&", sending_app, sending_facility, msh.get(3) if msh else "",
                  msh.get(4) if msh else "", _ts(), "", "ACK", uuid.uuid4().hex[:20], "P", "2.4"]),
        "|".join(["MSA", code, msg.control_id, text]),
    ]
    return "\r".join(segs) + "\r"


def _x(tag: str, value: str | None) -> str:
    return f"<{tag}>{escape(value)}</{tag}>" if value else ""


def build_referral_xml(*, practice: dict, gp: dict, patient: dict, referral: dict) -> tuple[str, str]:
    """Generic REF^I12 referral in HL7 v2.4 XML encoding. Returns (control_id, xml).

    VERIFY against Healthlink "General Referral Message Construction" (v1.10 or later):
    Healthlink defines required receiving-facility codes, the GP's Medical Council number
    lookup against the Health Directory, and specific OBX codes per referral type.
    """
    cid = uuid.uuid4().hex[:20]
    dob = patient.get("dob")
    dob_s = dob.strftime("%Y%m%d") if isinstance(dob, date) else ""
    obx = []
    for i, (label, text) in enumerate(referral.get("sections", []), start=1):
        obx.append(
            f"<OBX><OBX.1>{i}</OBX.1><OBX.2>TX</OBX.2><OBX.3><CE.1>{escape(label)}</CE.1>"
            f"<CE.2>{escape(label)}</CE.2></OBX.3><OBX.5>{escape(text)}</OBX.5><OBX.11>F</OBX.11></OBX>"
        )
    ids = "".join(
        f"<PID.3><CX.1>{escape(i['id'])}</CX.1><CX.5>{escape(i['type'])}</CX.5></PID.3>"
        for i in patient.get("ids", []) if i.get("id")
    )
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<REF_I12 xmlns="urn:hl7-org:v2xml">'
        "<MSH><MSH.1>|</MSH.1><MSH.2>^~\\&amp;</MSH.2>"
        f"<MSH.3><HD.1>EPR</HD.1></MSH.3><MSH.4><HD.1>{escape(practice.get('healthlink_id', ''))}</HD.1></MSH.4>"
        f"<MSH.6><HD.1>{escape(referral.get('receiving_facility', ''))}</HD.1></MSH.6>"
        f"<MSH.7><TS.1>{_ts()}</TS.1></MSH.7>"
        "<MSH.9><MSG.1>REF</MSG.1><MSG.2>I12</MSG.2></MSH.9>"
        f"<MSH.10>{cid}</MSH.10><MSH.11><PT.1>P</PT.1></MSH.11><MSH.12><VID.1>2.4</VID.1></MSH.12></MSH>"
        f"<RF1><RF1.1><CE.1>A</CE.1></RF1.1><RF1.2><CE.1>{escape(referral.get('priority', 'R'))}</CE.1></RF1.2>"
        f"<RF1.3><CE.1>{escape(referral.get('type', 'GEN'))}</CE.1><CE.2>{escape(referral.get('specialty', ''))}</CE.2></RF1.3>"
        f"<RF1.6><EI.1>{cid}</EI.1></RF1.6></RF1>"
        "<REF_I12.PROVIDER_CONTACT><PRD><PRD.1><CE.1>RP</CE.1></PRD.1>"
        f"<PRD.2><XPN.1><FN.1>{escape(gp.get('name', ''))}</FN.1></XPN.1></PRD.2>"
        f"<PRD.7><PI.1>{escape(gp.get('mcrn', ''))}</PI.1><PI.2>MCRN</PI.2></PRD.7></PRD></REF_I12.PROVIDER_CONTACT>"
        f"<PID><PID.1>1</PID.1>{ids}"
        f"<PID.5><XPN.1><FN.1>{escape(patient.get('family', ''))}</FN.1></XPN.1><XPN.2>{escape(patient.get('given', ''))}</XPN.2></PID.5>"
        f"<PID.7><TS.1>{dob_s}</TS.1></PID.7>{_x('PID.8', {'female': 'F', 'male': 'M'}.get(patient.get('sex', ''), 'U'))}"
        f"<PID.11><XAD.1><SAD.1>{escape(patient.get('address1', ''))}</SAD.1></XAD.1>"
        f"<XAD.2>{escape(patient.get('address2', ''))}</XAD.2><XAD.3>{escape(patient.get('town', ''))}</XAD.3>"
        f"<XAD.4>{escape(patient.get('county', ''))}</XAD.4><XAD.5>{escape(patient.get('eircode', ''))}</XAD.5></PID.11>"
        "</PID>"
        f"<REF_I12.OBSERVATION>{''.join(obx)}</REF_I12.OBSERVATION>"
        "</REF_I12>"
    )
    return cid, xml
