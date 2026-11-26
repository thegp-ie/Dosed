# GPIT certification: requirements traceability

Source: National GPIT Group, *General Practice Software Management Systems — Requirements for
Certification 2022* (RFC_2022 v1.5, 03/01/2025).

GPIT approval is needed before a vendor can integrate with Healthlink, Healthmail, PCRS or DSP
(RFC_2022 s.2.0). The standard is based on the HL7 EHR-System Functional Model. This table
maps each requirement to the code and records what is still to do.

**Status key:** ✅ done (tested) · 🟡 partly done or needs an external spec/licence · ⬜ not started

## Section 1: general functions (selected; all SHALL items in these areas)

| Ref | Requirement (summary) | Status | Where / notes |
|---|---|---|---|
| DC.1.1.1.1–4 | Single logical record, multiple identifiers, unique identification | ✅ | `models.Patient` (chart no., PPSN, IHI, GMS, hospital IDs) |
| DC.1.1.1.5 | Controlled merge of duplicate records | ✅ | `POST /api/patients/{id}/merge-into/{target}` (audited, record kept as "merged") |
| DC.1.1.1.6–7 | Mark information entered in error; move to correct patient | ✅ | `/api/consultations/{id}/entered-in-error`; prescriptions `cancel` with `entered_in_error` |
| DC.1.1.1.9 | Obsolete/inactive/archive per policy and law | ✅ | `record_status`, deregistration, retention review → archive |
| DC.1.1.1.12–13 | Mandate minimum registration data (Table 5) | ✅ | `patients.MINIMUM` enforced on create and update |
| DC.1.1.1.14 | Report incomplete records | ✅ | `/api/reports/incomplete` |
| DC.1.1.1.16 | Display external unique ID (IHI) on output | ✅ | Patient banner, prescriptions, Healthmail header |
| DC.1.1.1.18 | Edit window after creation (e.g. 12 h) | ✅ | Author can edit for 12 h unless signed; then addenda only |
| DC.1.1.1.10 | Propagate shared demographics to related patients | ⬜ | Family linking UI to do |
| DC.1.1.1.19 | Protocol for unknown/unconscious patient | ⬜ | Add "temporary registration" flow |
| DC.1.1.2 | Demographics as discrete fields; history of changes; Table 6/7/8 | ✅ | All Table 6 fields; NOK; `Carer` (Table 8); old→new values in audit trail |
| DC.1.1.2.16 | PPSN entry/update restricted by permission | ✅ | `patient.ppsn` permission; masked for other roles |
| DC.1.1.2.17 | HIQA National Standard Demographic Dataset | 🟡 | Fields present; check against the current HIQA dataset |
| DC.1.1.3.1 | Incorporate external clinical data (HIQA GP Messaging, HL7 v2.4 XML) | ✅ | `integrations/hl7.py` reads XML and ER7 |
| DC.1.4.1 | Allergy list | ✅ | `Allergy`; shown in banner; checked when prescribing |
| DC.1.4.2 | Medication list | ✅ | Prescriptions and repeat list |
| DC.1.4.3 | Problem list, past history, ICPC-2 | ✅ | `Problem`, ICPC-2 lookup (subset; load full licensed table) |
| DC.1.4.4 / DC.1.8.2 | Immunisation list and administration | ✅ | Batch, expiry, use-by, dose no./type/volume, site, route, consent/refusal |
| DC.1.7.1 | Prescriptions (GMS & private, once-off & repeat) | ✅ | Draft → issue → print/Healthmail; re-prescribe |
| DC.1.7.2.4 | Referrals | ✅ | Healthlink eReferral (see 2.8) and Healthmail letters |
| DC.1.8.3 | Electronic results; filter by provider; show before integrating | ✅ | Inbox: review before filing, filter "assigned to me", actions create tasks |
| DC.1.8.3.1 | Display/trend results | 🟡 | Tables done; trend charts to do |
| DC.1.8.4 | Clinical measurements | ✅ | `Observation` with plausibility checks |
| DC.1.8.5 | Clinical documents and notes, free text | ✅ | SOAP notes (encrypted), addenda |
| DC.1.8.7 | Ante-natal / post-natal care (Table 9) | ⬜ | Maternity & Infant Scheme module to do |
| DC.2.3.1.1 | Drug interaction checking | 🟡 | Allergy checks by name, substance and ATC class done; drug–drug interactions need a licensed knowledge base (see `TERMINOLOGY_AND_FORMULARY.md`) |
| DC.2.3.1.2 | Patient-specific dosing and warnings | 🟡 | Allergy + duplicate checks done; renal/paediatric dosing needs the drug database |
| DC.2.5 | Preventive care alerts | 🟡 | CDM due list and cervical screening list; immunisation schedule alerts to do |
| DC.3.1 | Task creation, routing, linking, tracking | ✅ | `Task` linked to patient and source inbox item |
| DC.3.2.2 | Provider–pharmacy communication | ✅ | Healthmail ePrescription transfer |
| S.1.3.1 | Provider access levels | ✅ | Roles in `security.ROLE_PERMISSIONS` |
| S.1.9 | Appointments | 🟡 | Day list, booking, status; session templates and multi-site to do |
| S.1.10 | Scanned documents | ⬜ | Upload/attach to record to do |
| S.2.2 | Reports | 🟡 | Activity, CDM due, cervical, incomplete, retention; ad hoc query builder to do |
| S.3.1.4 | Support remote healthcare services | ✅ | Video (self-hosted Jitsi) and phone consultations with consent/ID recorded |
| IN.1.1 | Entity authentication | ✅ | Argon2id passwords, mandatory TOTP 2FA, lockout, idle timeout |
| IN.1.2–1.3 | Authorisation and access control | ✅ | Role permissions checked on every endpoint |
| IN.1.5 | Non-repudiation | ✅ | Every action is tied to the signed-in user in the hash-chained audit log |
| IN.1.6–1.7 | Secure data exchange and routing | ✅ | TLS everywhere; Healthmail recipients limited to secure domains |
| IN.1.9 | Patient privacy and confidentiality | ✅ | Field encryption, access log per patient, GDPR restriction flag |
| IN.1.10 | Backup | ✅ | `deploy/backup.sh` (encrypted, EU off-site); restore drill documented |
| IN.2.1 | Retention, availability and destruction | ✅ | Retention calculation and review list; never deleted automatically |
| IN.2.2 | Auditable records | ✅ | `audit.py`: append-only SHA-256 chain, `verify-audit` |
| IN.2.4 | Extraction, including de-identified | 🟡 | Full extraction done; de-identified extract to do |
| IN.2.6 | Data portability: export of all data | ✅ | `/api/patients/{id}/export` (JSON). Practice-wide export to do |
| IN.4.1–4.2 | Standard terminologies and updates | 🟡 | ICPC-2 (subset) + ICD-10/ICD-11/SNOMED code lists loadable and replaceable; ICD-11 via local WHO ICD-API; full SNOMED RF2 support to do |
| S.3.2.1 | Rules-driven clinical coding assistance | ✅ | Code lookup; AI scribe suggests codes with evidence, checked against code lists |
| IN.5 | Standards-based interoperability | 🟡 | HL7 v2.4; FHIR R4 export planned for EHDS |

## Section 2: Irish programmes

| Ref | Requirement | Status | Where / notes |
|---|---|---|---|
| 2.0 | Healthlink: download reports, process ACKs; then referrals; then national programmes | 🟡 | Inbound, ACK out, ACK in, referral out done over a file bridge. The web-service transport and conformance testing come after GPIT approval. GP's MCRN must be checked against the Health Directory before submitting |
| 2.1 | Cervical screening templates and recall | 🟡 | Recall list done; cytology and colposcopy forms (Tables 10–11) to do |
| 2.2 | PCRS eligibility check (web service) and keep eligibility dates | 🟡 | Dates stored; web-service client needs the PCRS WSDL and vendor registration |
| 2.3 | Import PCRS patient listing (Table 15) | ✅ | `/api/patients/import/pcrs-listing` (merge, no duplicates) |
| 2.4 | Heartwatch | n/a | Discontinued December 2024 |
| 2.5 | Under-6s and cycles-of-care returns | 🟡 | Height/weight validation done; message build needs Healthlink specs |
| 2.6 | MN-CMS discharge summaries | 🟡 | Received and displayed as narrative; Healthlink stylesheet and mother–baby linking to do |
| 2.7 | IHI: import, validate (mod 11 + GS1), store 18 digits, show 3-3-4, keep previous, purge | ✅/🟡 | All done. The mod-11 weighting is an assumption, so that check warns rather than blocks until it is confirmed against "IHI GP, GMS Seeding Process". The decryption step needs that spec |
| 2.8 | eReferrals: cancer, general, specialist | 🟡 | General referral (REF^I12) done; cancer and specialist forms per Healthlink guides |
| 2.9 | Healthmail integration: own account, prescribers only for Rx, audit trail, attachments | ✅ | `integrations/healthmail.py`; directory search (2.9.8) to do |
| 2.10 | ePrescription transfer via Healthmail only; content rules; no OST | ✅ | Tested in `test_eprescription_rules` |
| 2.11 | DSP sick certificates (HL7), coding, weeks, employer copy, log | 🟡 | Cert, coding, employer PDF and log done; HL7 submission needs the DSP spec |
| 2.12 | CDM: auto-populate, no partial returns, care plan, calculators, colour status, ACK handling | 🟡 | All done apart from the message itself, which needs the Healthlink "GP contract" spec. QRISK3 needs a licensed implementation; CHA₂DS₂-VASc done |
| 2.13 | Vaccination messaging (COVID/flu/pneumo) | 🟡 | Required data captured (PPSN, batch, use-by, dose no., consent, mobile/email); message build per Healthlink spec |

## Non-functional items from the certification process

- **Source code escrow, help desk, documentation, training, SLA** (pre-integration items): these are
  organisational. Set them up before applying.
- **User group:** RFC_2022 expects one. See `DESIGN_NOTES.md`.
- **Re-testing every five years.**
