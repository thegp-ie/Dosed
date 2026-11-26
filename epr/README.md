# Dosed EPR: self-hosted electronic patient record for Irish general practice

A working foundation for a GP practice EPR built for the Irish market:

- **Patient register** to the GPIT RFC_2022 dataset: PPSN (validated, encrypted, permission-controlled),
  IHI (18-digit, check digits, 3-3-4 display), GMS/GP visit card, DPS, Eircode validation, census ethnicity,
  next of kin, carers, fada-insensitive search, PCRS GMS panel import, merge, deregistration.
- **Clinical record:** SOAP consultations with ICPC-2 coding, a 12-hour edit window then addenda, entered-in-error
  and move-to-correct-patient, problems, allergies, measurements, immunisations (batch, expiry, use-by,
  dose, consent or refusal), CDM reviews with auto-population, colour status and CHA₂DS₂-VASc, sick
  certificates, tasks.
- **Prescribing:** draft, issue, PDF and **ePrescription transfer via Healthmail** with the RFC 2.10 rules
  (prescribers only, Healthmail only, OST blocked, CD2/3 confirmation, full audit trail), allergy and duplicate checks.
- **Healthlink:** HL7 v2.4 (XML and pipe) inbox with patient matching, review-before-filing, actions that
  create tasks, ACKs, and outbound eReferral (REF^I12).
- **Healthmail:** secure letters with attachments from the patient record, sent from the clinician's own
  account, to secure domains only.
- **Remote consultations:** video on **self-hosted Jitsi** (JWT, lobby, no recording) with single-use patient
  links, plus phone consultations. The note can't be signed until consent and identity are recorded.
- **AI scribe (self-hosted):** records with patient consent, transcribes on a local Whisper server, drafts a
  SOAP note and suggested codes on a local LLM; the clinician edits and accepts it. Audio is never stored,
  and the transcript is purged on accept.
- **Coding and medicines:** ICPC-2 plus ICD-10, ICD-11 (including WHO's local ICD-API) and SNOMED CT dual coding, and a
  medicines dictionary loaded from the free HPRA product listing or the HSE NMPC export, with drug-class allergy checks.
- **Data protection:** AES-256-GCM field encryption, Argon2id and mandatory TOTP 2FA, role-based access, idle
  timeout, CSRF protection and a strict CSP, a **hash-chained audit log** of every record access, a per-patient
  access log, GDPR request tracking with deadlines, full-record export, a breach log with the 72-hour DPC
  clock, retention review (no automatic deletion), and encrypted EEA backups.

## Documentation

| Doc | Contents |
|---|---|
| [docs/GPIT_REQUIREMENTS.md](docs/GPIT_REQUIREMENTS.md) | Each RFC_2022 requirement → code, with status and gaps |
| [docs/COMPLIANCE.md](docs/COMPLIANCE.md) | GDPR, DPA 2018, Medical Council, retention, NIS2, EHDS, MDR, AI Act; hosting PII; DPIA outline |
| [docs/INTEGRATIONS.md](docs/INTEGRATIONS.md) | Healthlink, Healthmail, PCRS, IHI, Jitsi |
| [docs/AI_SCRIBE.md](docs/AI_SCRIBE.md) | AI scribe design, setup, evaluation, AI Act/MDR position |
| [docs/TERMINOLOGY_AND_FORMULARY.md](docs/TERMINOLOGY_AND_FORMULARY.md) | Irish medicines data sources and ICD/SNOMED licensing |
| [docs/DESIGN_NOTES.md](docs/DESIGN_NOTES.md) | What we took from *Signposts to Success*, MPS/Medisec guidance and the HealthOne user group |
| [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) | Install, keys, backups, Jitsi, development |

## Stack

Python 3.12 / FastAPI / SQLAlchemy / PostgreSQL 16, a vanilla-JS client with no CDN dependencies, and Caddy for TLS,
all run with Docker Compose. 55 automated tests (`python -m pytest -q`).

## Status: not yet for live patient data

This is the core of a system, not a certified product. Before clinical use it needs: GPIT certification
and Healthlink onboarding; a licensed drug knowledge base (interactions, dosing), the full ICPC-2 table and licensed ICD-10 file; evaluation of the AI scribe models on local consultations; the
national programme message builders (CDM, vaccinations, sick certs, under-6s) from current Healthlink
specs; the PCRS eligibility web service; database migrations; a clinical safety case; penetration testing;
and the practice's DPIA. The full list of gaps is in `docs/GPIT_REQUIREMENTS.md`.
