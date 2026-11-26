"""PDF documents: prescriptions (RFC 2.10.5-2.10.8) and DSP sick certificates for employers."""
from __future__ import annotations

import io
from datetime import date, timedelta

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

from ..config import settings


def _wrap(c: canvas.Canvas, text: str, x: float, y: float, width: float, size: int = 10) -> float:
    c.setFont("Helvetica", size)
    words, line = text.split(), ""
    for w in words:
        trial = (line + " " + w).strip()
        if c.stringWidth(trial, "Helvetica", size) > width:
            c.drawString(x, y, line)
            y -= size + 3
            line = w
        else:
            line = trial
    if line:
        c.drawString(x, y, line)
        y -= size + 3
    return y


def prescription_pdf(*, prescription, patient, prescriber, via_healthmail: bool) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    w, h = A4
    x, y = 20 * mm, h - 20 * mm
    c.setFont("Helvetica-Bold", 14)
    c.drawString(x, y, settings.practice_name)
    y -= 6 * mm
    y = _wrap(c, settings.practice_address, x, y, w - 40 * mm, 9)
    y -= 4 * mm
    c.setFont("Helvetica-Bold", 11)
    c.drawString(x, y, "Prescriber")
    y -= 5 * mm
    pres_line = f"{prescriber.full_name}"
    if prescriber.mcrn:
        pres_line += f"   IMC no. {prescriber.mcrn}"
    if prescriber.nmbi_pin:
        pres_line += f"   NMBI PIN {prescriber.nmbi_pin}"
    if prescriber.gms_doctor_number:
        pres_line += f"   GMS doctor no. {prescriber.gms_doctor_number}"
    y = _wrap(c, pres_line, x, y, w - 40 * mm)
    y = _wrap(c, prescriber.work_address or settings.practice_address, x, y, w - 40 * mm, 9)
    y -= 4 * mm
    c.setFont("Helvetica-Bold", 11)
    c.drawString(x, y, "Patient")
    y -= 5 * mm
    addr = ", ".join(p for p in (patient.address1, patient.address2, patient.town, patient.county, patient.eircode) if p)
    y = _wrap(c, f"{patient.first_name} {patient.last_name}   DOB {patient.dob:%d/%m/%Y}", x, y, w - 40 * mm)
    y = _wrap(c, addr, x, y, w - 40 * mm)
    if patient.eligibility == "gms" and patient.gms_number:
        y = _wrap(c, f"GMS number: {patient.gms_number}", x, y, w - 40 * mm)
    y = _wrap(c, f"Date: {prescription.created_at:%d/%m/%Y}", x, y, w - 40 * mm)
    y -= 4 * mm
    any_repeat = any(i.repeats > 0 for i in prescription.items)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(x, y, "REPEAT PRESCRIPTION" if any_repeat else "SINGLE PRESCRIPTION")
    y -= 7 * mm
    for n, item in enumerate(prescription.items, start=1):
        c.setFont("Helvetica-Bold", 10)
        name = " ".join(p for p in (item.drug_name, item.strength, item.form) if p)
        c.drawString(x, y, f"{n}. {name}")
        y -= 5 * mm
        y = _wrap(c, f"Dose: {item.dose_instructions}", x + 5 * mm, y, w - 50 * mm)
        y = _wrap(c, f"Quantity: {item.quantity}" + (f"   Repeats: {item.repeats}" if item.repeats else ""),
                  x + 5 * mm, y, w - 50 * mm)
        if not item.generic_substitution_allowed:
            y = _wrap(c, "Do not substitute", x + 5 * mm, y, w - 50 * mm)
        y -= 2 * mm
    y -= 6 * mm
    note = ("Sent electronically via Healthmail by the prescriber." if via_healthmail
            else "Signature: ______________________________")
    _wrap(c, note, x, y, w - 40 * mm, 9)
    c.setFont("Helvetica", 7)
    c.drawString(x, 12 * mm, f"Prescription ref {prescription.id}")
    c.showPage()
    c.save()
    return buf.getvalue()


def sick_cert_pdf(*, cert, patient, clinician) -> bytes:
    """Employer copy: dates only, no clinical details (RFC 2.11.4)."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    w, h = A4
    x, y = 20 * mm, h - 25 * mm
    c.setFont("Helvetica-Bold", 14)
    c.drawString(x, y, "Medical certificate")
    y -= 10 * mm
    end = cert.date_from + timedelta(weeks=cert.weeks) - timedelta(days=1)
    for line in (
        f"I certify that {patient.first_name} {patient.last_name} (DOB {patient.dob:%d/%m/%Y})",
        f"is unfit for work from {cert.date_from:%d/%m/%Y} to {end:%d/%m/%Y} inclusive.",
        "",
        f"{clinician.full_name}" + (f", IMC no. {clinician.mcrn}" if clinician.mcrn else ""),
        settings.practice_name,
        f"Date: {date.today():%d/%m/%Y}",
    ):
        y = _wrap(c, line, x, y, w - 40 * mm, 11)
    c.showPage()
    c.save()
    return buf.getvalue()
