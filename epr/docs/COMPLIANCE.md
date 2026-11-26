# Legal and regulatory compliance

This explains how the system supports a GP practice in meeting its obligations. The **practice
is the data controller**. The software is a tool: compliance also depends on how it is hosted,
configured and used. This is not legal advice. Have the DPIA and contracts reviewed by the
practice's adviser (e.g. ICGP data protection resources, Medisec or Medical Protection).

## 1. Laws and guidance that apply

| Instrument | What it requires | How the system helps |
|---|---|---|
| **GDPR** (EU 2016/679) | Lawful basis for health data (Art. 6(1)(e)/(c) with 9(2)(h)); security (Art. 32); records of processing (Art. 30); data subject rights (Arts. 15–22); breach notification (Arts. 33–34); DPIA (Art. 35) | Encryption, access control, audit trail, rights workflow with deadlines, breach log with 72-hour clock, full-record export |
| **Data Protection Act 2018** (Ireland) | Irish supplement to GDPR; s.52 safeguards for health data; Data Protection Commission (DPC) is the regulator | Role-based access, logging of every record access, training prompts |
| **Data Protection Act 2018 (s.36(2)) (Health Research) Regulations 2018** | Explicit consent or a Health Research Consent Declaration for research use | No research extract without a separate de-identified export (to do) |
| **Medical Council Guide to Professional Conduct and Ethics, 9th ed. (from 1 Jan 2024)** | Confidentiality, accurate records, telemedicine to the same standard as in-person care | Locked notes with addenda, remote consent/ID fields, record of who did what |
| **HSE record retention guidance** (as summarised by Medical Protection Ireland) | Keep GP records at least 8 years after last contact or death; children until age 25 or 8 years, whichever is later | `irish.retention_until`, retention review list; never deleted automatically |
| **Misuse of Drugs Regulations; S.I. 98/2020 and later amendments** | Electronic transfer of prescriptions via Healthmail; OST not by electronic transfer | Enforced in `send_prescription` |
| **NIS2 Directive** (EU 2022/2555) and the Irish transposition | Cyber-security risk management for health-sector entities above the size thresholds; most single practices fall below them | Security controls below match NIS2 Art. 21 measures in any case |
| **European Health Data Space Regulation** (EU 2025/327) | EHR systems will need harmonised interoperability and logging components, a CE-style self-certification and EU database registration. Applies in phases from 2029 (patient summaries, ePrescriptions) | Audit logging and portable export now; FHIR-based patient summary planned |
| **Medical Device Regulation** (EU 2017/745) | Software that calculates doses or gives diagnostic advice can be a medical device | Calculators are limited to published scores (CHA₂DS₂-VASc, BMI). Dose calculation would need an MDR assessment first |
| **EU AI Act** (EU 2024/1689) | Obligations for AI systems; medical-device AI is high-risk | No AI features. Any future AI assistant needs a separate assessment |

## 2. Hosting PII: what "self-hosted and compliant" means here

- **Location:** run the server, database and backups in Ireland or the EEA. Do not use a
  provider that can be compelled to transfer data outside the EEA without Chapter V safeguards.
  Hosting on practice premises or with an Irish colocation provider is the simplest.
- **Processors:** if a hosting company or IT support provider can reach the server, they are
  a processor. Put an Art. 28 data processing agreement in place and list them in the
  Art. 30 record.
- **Encryption at rest, in two layers:** (1) full-disk encryption (LUKS) on the host; (2)
  AES-256-GCM field-level encryption of clinical notes, identifiers (PPSN, IHI), next-of-kin
  details and inbound messages (`app/crypto.py`). Keys are held in `.env`, never in the
  database or its backups.
- **Encryption in transit:** TLS 1.2+ via Caddy, HSTS, cookies marked Secure, HttpOnly and SameSite=Strict.
- **Searching encrypted identifiers:** PPSN lookup uses an HMAC "blind index" with a separate key.
- **Backups:** encrypted with an `age` public key before leaving the server, stored in the
  EEA, 35-day rotation, restore tested quarterly.
- **No third-party scripts:** the web client loads nothing from CDNs. The Content-Security-Policy
  is `'self'` only.
- **Video:** self-hosted Jitsi with JWT authentication, lobby on, recording off, third-party
  requests disabled. Media stays on infrastructure the practice controls.

## 3. Security controls (GDPR Art. 32; GPIT IN.1)

| Control | Implementation |
|---|---|
| Unique user accounts | No shared logins; deactivation ends all of that user's sessions |
| Strong authentication | Argon2id hashes, 12-character minimum, mandatory TOTP 2FA, 5-attempt lockout |
| Session security | 15-minute idle timeout (server and browser), 10-hour maximum, CSRF token on every change |
| Least privilege | Roles: GP, nurse, nurse prescriber, reception, practice manager, sysadmin |
| Accountability | Every view, create, change, print, send and export is logged with user, time and IP, in a SHA-256 hash chain; `python -m app.cli verify-audit` detects tampering |
| Patient-level access log | `/api/patients/{id}/access-log` shows who opened a record |
| Error handling | No stack traces or patient data in error responses |
| Secure email only | Healthmail recipients limited to configured secure domains |

Recommended for the host: automatic OS security updates, firewall allowing 443 only (or VPN), off-host log shipping, EDR/antivirus on workstations, a UPS, and two-person control of the encryption keys.

## 4. Data subject rights workflow

| Right | How it is handled |
|---|---|
| Access (Art. 15) | Log the request, verify identity, export the full record (JSON) plus the access log. Due within one month; can be extended by two months |
| Rectification (Art. 16) | Edit demographics (old→new values kept in the audit trail). Clinical notes are corrected by addendum, not overwritten |
| Erasure (Art. 17) | Usually refused for medical records under Art. 17(3)(c) and the retention rules; log the request and the reason |
| Restriction (Art. 18) | Logging a restriction request sets `processing_restricted`, shown as a red flag on the banner |
| Portability (Art. 20) | Same JSON export; also used for patient transfer between practices |
| Objection (Art. 21) | Logged and handled case by case |

## 5. Breaches (Arts. 33–34)

Record every incident in Data protection → Breaches. The system shows the 72-hour deadline to notify
the DPC and flags overdue cases. Notify patients without undue delay where the risk to them is high.

## 6. Remote consultations (Medical Council; Medical Protection Ireland guidance)

- Use remote consultations mainly for patients already known to the practice, with access to their full record.
- Record that the consultation was remote, that the patient consented, and how their identity was confirmed. The note cannot be signed until both are ticked.
- The patient's video consent is a field on the record. A video appointment can't be booked without it.
- Calls are not recorded. If a patient asks to record, follow Medisec/MPS guidance. A recording held by the practice becomes part of the record.
- The patient join page tells them to call 999/112 in an emergency and offers an in-person or phone alternative.

## 7. DPIA outline (complete before go-live)

1. Description: GP EPR, categories of data (health, identifiers, contact), data subjects (patients, carers, staff), recipients (hospitals via Healthlink, pharmacies and clinicians via Healthmail, PCRS, DSP).
2. Necessity and proportionality: Art. 9(2)(h) provision of health care; retention per HSE policy.
3. Risks: unauthorised access, loss, ransomware, misdirected messages, wrong-patient filing, video interception.
4. Measures: sections 2–6 above; staff training; acceptable use policy; key management.
5. Residual risk and sign-off by the GP principal; review every year and after major changes.
