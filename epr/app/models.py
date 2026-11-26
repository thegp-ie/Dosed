"""Database schema.

Encrypted columns use EncryptedText (AES-256-GCM, see crypto.py). Columns needed for
searching and sorting (names, date of birth) are stored in clear and must be protected
by disk encryption and database access controls.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import (
    Boolean, event, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .crypto import EncryptedText
from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(200))
    # gp | nurse | reception | practice_manager | sysadmin
    role: Mapped[str] = mapped_column(String(30))
    mcrn: Mapped[str | None] = mapped_column(String(20))  # Medical Council registration number
    nmbi_pin: Mapped[str | None] = mapped_column(String(20))  # Nursing & Midwifery Board PIN
    gms_doctor_number: Mapped[str | None] = mapped_column(String(20))
    healthmail_address: Mapped[str | None] = mapped_column(String(200))
    # The user's own Healthmail password, encrypted; used only while they are signed in (RFC 2.9.1, 2.9.4).
    healthmail_secret: Mapped[str | None] = mapped_column(EncryptedText)
    work_address: Mapped[str | None] = mapped_column(String(300))
    password_hash: Mapped[str] = mapped_column(String(255))
    totp_secret: Mapped[str | None] = mapped_column(EncryptedText)
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class UserSession(Base):
    __tablename__ = "user_sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    csrf_token: Mapped[str] = mapped_column(String(64))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    mfa_passed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ip: Mapped[str | None] = mapped_column(String(64))
    user: Mapped[User] = relationship()


class Patient(Base):
    """Patient record. Fields follow GPIT RFC_2022 Table 5 (minimum registration data,
    enforced in the API) and Table 6 (patient demographic data)."""
    __tablename__ = "patients"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str | None] = mapped_column(String(20))
    first_name: Mapped[str] = mapped_column(String(100), index=True)
    middle_name: Mapped[str | None] = mapped_column(String(100))
    last_name: Mapped[str] = mapped_column(String(100), index=True)
    # Normalised copies for fada-insensitive search (set automatically, see below).
    first_name_key: Mapped[str] = mapped_column(String(100), index=True, default="")
    last_name_key: Mapped[str] = mapped_column(String(100), index=True, default="")
    former_family_name: Mapped[str | None] = mapped_column(String(100))
    birth_surname: Mapped[str | None] = mapped_column(String(100))
    mothers_maiden_name: Mapped[str | None] = mapped_column(String(100))
    alias: Mapped[str | None] = mapped_column(String(200))  # e.g. Irish-language form of name
    dob: Mapped[date] = mapped_column(Date, index=True)
    sex: Mapped[str] = mapped_column(String(10))  # female | male | other | unknown
    # Identifiers
    ppsn: Mapped[str | None] = mapped_column(EncryptedText)
    ppsn_index: Mapped[str | None] = mapped_column(String(64), index=True)
    ihi: Mapped[str | None] = mapped_column(EncryptedText)  # full 18-digit Individual Health Identifier
    ihi_previous: Mapped[str | None] = mapped_column(EncryptedText)  # kept when replaced (RFC 2.7.4)
    hospital_ids: Mapped[str | None] = mapped_column(EncryptedText)  # JSON list of {source, id}
    # Eligibility: private | gms | dvc | other
    eligibility: Mapped[str] = mapped_column(String(20), default="private")
    gms_number: Mapped[str | None] = mapped_column(String(30))
    gms_expiry: Mapped[date | None] = mapped_column(Date)
    gms_doctor_number: Mapped[str | None] = mapped_column(String(20))
    gms_distance_code: Mapped[str | None] = mapped_column(String(1))
    gms_dispensing: Mapped[bool] = mapped_column(Boolean, default=False)
    pcrs_category: Mapped[str | None] = mapped_column(String(60))
    dps_number: Mapped[str | None] = mapped_column(String(30))
    dps_expiry: Mapped[date | None] = mapped_column(Date)
    insurer: Mapped[str | None] = mapped_column(String(100))
    insurer_membership: Mapped[str | None] = mapped_column(String(60))
    insurer_cover: Mapped[str | None] = mapped_column(String(100))
    company_scheme: Mapped[str | None] = mapped_column(String(60))  # An Post, Garda ...
    # Address and contact
    address1: Mapped[str | None] = mapped_column(String(200))
    address2: Mapped[str | None] = mapped_column(String(200))
    town: Mapped[str | None] = mapped_column(String(100))
    county: Mapped[str | None] = mapped_column(String(50))
    eircode: Mapped[str | None] = mapped_column(String(10))
    country: Mapped[str] = mapped_column(String(60), default="Ireland")
    phone_home: Mapped[str | None] = mapped_column(String(30))
    phone_mobile: Mapped[str | None] = mapped_column(String(30))
    email: Mapped[str | None] = mapped_column(String(200))
    # Social
    occupation: Mapped[str | None] = mapped_column(String(100))
    marital_status: Mapped[str | None] = mapped_column(String(30))
    religion: Mapped[str | None] = mapped_column(String(60))
    ethnicity: Mapped[str | None] = mapped_column(String(40))  # census 2016 list, see irish.ETHNICITY
    preferred_language: Mapped[str | None] = mapped_column(String(40))
    interpreter_required: Mapped[bool] = mapped_column(Boolean, default=False)
    transport_needs: Mapped[str | None] = mapped_column(Text)
    advocacy_needs: Mapped[str | None] = mapped_column(Text)
    # Next of kin (RFC Table 7)
    nok_name: Mapped[str | None] = mapped_column(EncryptedText)
    nok_relationship: Mapped[str | None] = mapped_column(String(60))
    nok_phone: Mapped[str | None] = mapped_column(EncryptedText)
    nok_address: Mapped[str | None] = mapped_column(EncryptedText)
    # Practice relationship
    registered_gp_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    usual_gp_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    branch_surgery: Mapped[str | None] = mapped_column(String(100))
    mother_patient_id: Mapped[int | None] = mapped_column(ForeignKey("patients.id"))
    preferred_pharmacy: Mapped[str | None] = mapped_column(String(200))
    preferred_pharmacy_healthmail: Mapped[str | None] = mapped_column(String(200))
    consent_sms: Mapped[bool] = mapped_column(Boolean, default=False)
    consent_email: Mapped[bool] = mapped_column(Boolean, default=False)
    consent_video: Mapped[bool] = mapped_column(Boolean, default=False)
    deceased_date: Mapped[date | None] = mapped_column(Date)
    cause_of_death: Mapped[str | None] = mapped_column(EncryptedText)
    # GDPR Art. 18: processing restricted while a dispute is resolved.
    processing_restricted: Mapped[bool] = mapped_column(Boolean, default=False)
    registered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    left_practice_at: Mapped[date | None] = mapped_column(Date)
    deregistration_reason: Mapped[str | None] = mapped_column(String(200))
    # active | inactive | merged | archived
    record_status: Mapped[str] = mapped_column(String(20), default="active")
    merged_into_id: Mapped[int | None] = mapped_column(ForeignKey("patients.id"))
    last_contact_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retention_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


@event.listens_for(Patient, "before_insert")
@event.listens_for(Patient, "before_update")
def _patient_name_keys(mapper, connection, target):
    from .irish import name_key
    target.first_name_key = name_key(target.first_name)
    target.last_name_key = name_key(target.last_name)


class Carer(Base):
    """RFC Table 8. Consent date records when the carer agreed to their details being held."""
    __tablename__ = "carers"
    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(EncryptedText)
    relationship_to_patient: Mapped[str | None] = mapped_column(String(60))
    phone: Mapped[str | None] = mapped_column(EncryptedText)
    address: Mapped[str | None] = mapped_column(EncryptedText)
    carer_patient_id: Mapped[int | None] = mapped_column(ForeignKey("patients.id"))
    consent_date: Mapped[date | None] = mapped_column(Date)


class Allergy(Base):
    __tablename__ = "allergies"
    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"), index=True)
    substance: Mapped[str] = mapped_column(String(200))
    reaction: Mapped[str | None] = mapped_column(String(300))
    severity: Mapped[str] = mapped_column(String(20), default="unknown")  # mild|moderate|severe|unknown
    recorded_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Problem(Base):
    __tablename__ = "problems"
    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"), index=True)
    icpc2_code: Mapped[str | None] = mapped_column(String(10), index=True)
    description: Mapped[str] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(20), default="active")  # active | past
    onset: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(EncryptedText)
    recorded_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Consultation(Base):
    __tablename__ = "consultations"
    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"), index=True)
    clinician_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    appointment_id: Mapped[int | None] = mapped_column(ForeignKey("appointments.id"))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    mode: Mapped[str] = mapped_column(String(20), default="surgery")  # surgery|phone|video|home|nursing_home
    subjective: Mapped[str | None] = mapped_column(EncryptedText)
    objective: Mapped[str | None] = mapped_column(EncryptedText)
    assessment: Mapped[str | None] = mapped_column(EncryptedText)
    plan: Mapped[str | None] = mapped_column(EncryptedText)
    icpc2_code: Mapped[str | None] = mapped_column(String(10))
    remote_consent_recorded: Mapped[bool] = mapped_column(Boolean, default=False)
    remote_identity_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    # Once signed the note is read-only; corrections go in addenda.
    signed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    entered_in_error: Mapped[bool] = mapped_column(Boolean, default=False)
    error_reason: Mapped[str | None] = mapped_column(String(300))
    clinician: Mapped[User] = relationship(foreign_keys=[clinician_id])
    addenda: Mapped[list["Addendum"]] = relationship(order_by="Addendum.created_at")


class Addendum(Base):
    __tablename__ = "addenda"
    id: Mapped[int] = mapped_column(primary_key=True)
    consultation_id: Mapped[int] = mapped_column(ForeignKey("consultations.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    text: Mapped[str] = mapped_column(EncryptedText)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Observation(Base):
    __tablename__ = "observations"
    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"), index=True)
    consultation_id: Mapped[int | None] = mapped_column(ForeignKey("consultations.id"))
    kind: Mapped[str] = mapped_column(String(40), index=True)  # bp_systolic, weight_kg, hba1c ...
    value: Mapped[float] = mapped_column(Float)
    unit: Mapped[str | None] = mapped_column(String(20))
    taken_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    recorded_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))


class Prescription(Base):
    __tablename__ = "prescriptions"
    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"), index=True)
    prescriber_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    consultation_id: Mapped[int | None] = mapped_column(ForeignKey("consultations.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft|issued|sent|cancelled
    pharmacy_healthmail: Mapped[str | None] = mapped_column(String(200))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_via: Mapped[str | None] = mapped_column(String(20))  # print | healthmail
    entered_in_error: Mapped[bool] = mapped_column(Boolean, default=False)
    items: Mapped[list["PrescriptionItem"]] = relationship(cascade="all, delete-orphan")
    prescriber: Mapped[User] = relationship()


class PrescriptionItem(Base):
    __tablename__ = "prescription_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    prescription_id: Mapped[int] = mapped_column(ForeignKey("prescriptions.id", ondelete="CASCADE"), index=True)
    drug_name: Mapped[str] = mapped_column(String(200))
    strength: Mapped[str | None] = mapped_column(String(60))
    form: Mapped[str | None] = mapped_column(String(60))
    dose_instructions: Mapped[str] = mapped_column(String(300))
    quantity: Mapped[str] = mapped_column(String(60))
    repeats: Mapped[int] = mapped_column(Integer, default=0)
    is_repeat_medication: Mapped[bool] = mapped_column(Boolean, default=False)
    # Misuse of Drugs Regulations schedule: None, "CD1".."CD5"
    cd_schedule: Mapped[str | None] = mapped_column(String(5))
    # Opiate Substitution Treatment cannot go by electronic transfer (RFC 2.10.9).
    is_ost: Mapped[bool] = mapped_column(Boolean, default=False)
    generic_substitution_allowed: Mapped[bool] = mapped_column(Boolean, default=True)


class Immunisation(Base):
    __tablename__ = "immunisations"
    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"), index=True)
    vaccine: Mapped[str] = mapped_column(String(120))
    batch: Mapped[str | None] = mapped_column(String(60))
    expiry: Mapped[date | None] = mapped_column(Date)
    site: Mapped[str | None] = mapped_column(String(60))
    dose_number: Mapped[int | None] = mapped_column(Integer)
    dose_kind: Mapped[str | None] = mapped_column(String(20))  # primary | booster
    dose_volume_ml: Mapped[float | None] = mapped_column(Float)
    use_by: Mapped[date | None] = mapped_column(Date)  # mRNA: from thaw date, not vial expiry
    consent: Mapped[str] = mapped_column(String(20), default="given")  # given | refused
    contraindications: Mapped[str | None] = mapped_column(Text)
    route: Mapped[str | None] = mapped_column(String(30))
    message_status: Mapped[str | None] = mapped_column(String(20))  # none|queued|sent|acked|rejected
    given_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    given_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))


class Appointment(Base):
    __tablename__ = "appointments"
    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"), index=True)
    clinician_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    start: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    duration_minutes: Mapped[int] = mapped_column(Integer, default=15)
    mode: Mapped[str] = mapped_column(String(20), default="surgery")  # surgery|phone|video
    reason: Mapped[str | None] = mapped_column(EncryptedText)
    status: Mapped[str] = mapped_column(String(20), default="booked")  # booked|arrived|in_progress|done|dna|cancelled
    video_room: Mapped[str | None] = mapped_column(String(80))
    patient_link_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    patient_link_expires: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    patient_joined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    patient: Mapped[Patient] = relationship()
    clinician: Mapped[User] = relationship()


class InboxMessage(Base):
    """Inbound clinical messages: Healthlink HL7 results/letters, Healthmail, scanned post."""
    __tablename__ = "inbox_messages"
    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(20))  # healthlink | healthmail | manual
    message_type: Mapped[str] = mapped_column(String(30))  # ORU^R01, ADT^A03, REF^I12, letter ...
    control_id: Mapped[str | None] = mapped_column(String(80), index=True)
    sender: Mapped[str | None] = mapped_column(String(200))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    raw: Mapped[str | None] = mapped_column(EncryptedText)
    summary: Mapped[str | None] = mapped_column(EncryptedText)
    patient_id: Mapped[int | None] = mapped_column(ForeignKey("patients.id"), index=True)
    match_status: Mapped[str] = mapped_column(String(20), default="unmatched")  # matched|unmatched|manual
    match_hint: Mapped[str | None] = mapped_column(EncryptedText)  # name/dob from the message
    assigned_to: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(20), default="new")  # new | reviewed | filed
    action: Mapped[str | None] = mapped_column(String(40))  # normal|no_action|contact_patient|book_appointment|repeat_test
    review_comment: Mapped[str | None] = mapped_column(EncryptedText)
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    abnormal: Mapped[bool] = mapped_column(Boolean, default=False)
    results: Mapped[list["LabResult"]] = relationship(cascade="all, delete-orphan")
    __table_args__ = (UniqueConstraint("source", "control_id", name="uq_inbox_source_control"),)


class LabResult(Base):
    __tablename__ = "lab_results"
    id: Mapped[int] = mapped_column(primary_key=True)
    inbox_message_id: Mapped[int] = mapped_column(ForeignKey("inbox_messages.id", ondelete="CASCADE"), index=True)
    patient_id: Mapped[int | None] = mapped_column(ForeignKey("patients.id"), index=True)
    test_code: Mapped[str | None] = mapped_column(String(60))
    test_name: Mapped[str] = mapped_column(String(200))
    value: Mapped[str | None] = mapped_column(String(200))
    units: Mapped[str | None] = mapped_column(String(40))
    reference_range: Mapped[str | None] = mapped_column(String(60))
    abnormal_flag: Mapped[str | None] = mapped_column(String(10))  # H, L, HH, LL, A
    observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OutboundMessage(Base):
    """Every clinical message that leaves the practice, for audit and resend."""
    __tablename__ = "outbound_messages"
    id: Mapped[int] = mapped_column(primary_key=True)
    channel: Mapped[str] = mapped_column(String(20))  # healthmail | healthlink | print
    kind: Mapped[str] = mapped_column(String(30))  # prescription | referral | letter
    recipient: Mapped[str] = mapped_column(String(300))
    subject: Mapped[str | None] = mapped_column(String(300))
    patient_id: Mapped[int | None] = mapped_column(ForeignKey("patients.id"), index=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    status: Mapped[str] = mapped_column(String(20), default="queued")  # queued|sent|failed
    error: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[str | None] = mapped_column(EncryptedText)


class Claim(Base):
    """PCRS claims (STCs, CDM, vaccinations). Records only; submission is a PCRS integration."""
    __tablename__ = "claims"
    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"), index=True)
    claim_type: Mapped[str] = mapped_column(String(40))  # stc_X | cdm_review | oc_finding | vaccination ...
    service_date: Mapped[date] = mapped_column(Date)
    clinician_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|submitted|paid|rejected
    reference: Mapped[str | None] = mapped_column(String(80))
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditLog(Base):
    """Append-only, hash-chained audit trail. Each row hashes the previous one."""
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    user_id: Mapped[int | None] = mapped_column(Integer, index=True)
    username: Mapped[str | None] = mapped_column(String(80))
    action: Mapped[str] = mapped_column(String(60), index=True)
    patient_id: Mapped[int | None] = mapped_column(Integer, index=True)
    entity: Mapped[str | None] = mapped_column(String(40))
    entity_id: Mapped[str | None] = mapped_column(String(40))
    detail: Mapped[str | None] = mapped_column(Text)
    ip: Mapped[str | None] = mapped_column(String(64))
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64))


class DataSubjectRequest(Base):
    """GDPR Arts. 15-22 requests. Statutory deadline is one month from receipt (Art. 12(3))."""
    __tablename__ = "data_subject_requests"
    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int | None] = mapped_column(ForeignKey("patients.id"))
    request_type: Mapped[str] = mapped_column(String(20))  # access|rectification|restriction|objection|portability|erasure
    received_at: Mapped[date] = mapped_column(Date)
    due_at: Mapped[date] = mapped_column(Date)
    identity_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(20), default="open")  # open|extended|completed|refused
    outcome: Mapped[str | None] = mapped_column(Text)
    handled_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BreachRecord(Base):
    """GDPR Art. 33: notify the Data Protection Commission within 72 hours unless unlikely to cause risk."""
    __tablename__ = "breach_records"
    id: Mapped[int] = mapped_column(primary_key=True)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    description: Mapped[str] = mapped_column(Text)
    data_categories: Mapped[str | None] = mapped_column(Text)
    patients_affected: Mapped[int | None] = mapped_column(Integer)
    risk: Mapped[str] = mapped_column(String(20), default="unassessed")  # none|low|risk|high|unassessed
    dpc_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    patients_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    actions: Mapped[str | None] = mapped_column(Text)
    recorded_by: Mapped[int] = mapped_column(ForeignKey("users.id"))


class SickCert(Base):
    """Department of Social Protection medical certificate (RFC 2.11)."""
    __tablename__ = "sick_certs"
    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"), index=True)
    clinician_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    cert_type: Mapped[str] = mapped_column(String(20), default="first")  # first | intermediate | final
    illness_code_system: Mapped[str] = mapped_column(String(10), default="ICPC2")  # ICPC2 | ICD10 | SNOMED
    illness_code: Mapped[str | None] = mapped_column(String(20))
    illness_text: Mapped[str] = mapped_column(EncryptedText)
    date_from: Mapped[date] = mapped_column(Date)
    weeks: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    message_status: Mapped[str] = mapped_column(String(20), default="draft")  # draft|queued|accepted|rejected
    ack_detail: Mapped[str | None] = mapped_column(Text)


class CdmReview(Base):
    """Chronic Disease Management programme review (RFC 2.12, GP contract 2019).

    programme: cdm_treatment | prevention | ocf (opportunistic case finding)
    status: started (orange) -> complete (green); a due follow-up shows red.
    The return is only queued once every required field is filled (RFC 2.12.5).
    """
    __tablename__ = "cdm_reviews"
    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"), index=True)
    clinician_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    programme: Mapped[str] = mapped_column(String(20))
    conditions: Mapped[str] = mapped_column(String(200))  # comma-separated register codes
    review_date: Mapped[date] = mapped_column(Date)
    data: Mapped[str] = mapped_column(EncryptedText)  # JSON dataset
    care_plan: Mapped[str | None] = mapped_column(EncryptedText)
    status: Mapped[str] = mapped_column(String(20), default="started")  # started | complete
    message_status: Mapped[str] = mapped_column(String(20), default="none")  # none|queued|accepted|rejected
    ack_detail: Mapped[str | None] = mapped_column(Text)
    next_due: Mapped[date | None] = mapped_column(Date)


class Task(Base):
    """Clinical/admin workflow task (RFC DC.3.1), optionally linked to a patient and source item."""
    __tablename__ = "tasks"
    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int | None] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(300))
    detail: Mapped[str | None] = mapped_column(EncryptedText)
    assigned_to: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    due: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="open")  # open | done | cancelled
    source: Mapped[str | None] = mapped_column(String(40))  # e.g. inbox:12
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Invoice(Base):
    """Private fees day-book. Financial records: keep 6 years for Revenue."""
    __tablename__ = "invoices"
    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    description: Mapped[str] = mapped_column(String(200))
    amount_cents: Mapped[int] = mapped_column(Integer)
    paid_cents: Mapped[int] = mapped_column(Integer, default=0)
    method: Mapped[str | None] = mapped_column(String(20))  # cash | card | transfer
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
