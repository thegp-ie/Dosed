# Integrations

## Healthlink (national message broker)

**What it is:** Healthlink moves HL7 v2.4 messages, mostly in XML encoding, between hospitals,
labs, PCRS, DSP and GP systems. Message types include lab and radiology results, discharge
summaries (including MN-CMS), OPD letters, eReferrals and responses, CDM, vaccination and
sick-cert returns.

**Onboarding order (RFC_2022 s.2.0):** (1) GPIT approval → (2) basic functionality: download
reports and process ACKs → (3) referrals → (4) national programmes. Healthlink tests every
release against its web services before it goes to practices.

**What is built:**

| Piece | File | Notes |
|---|---|---|
| HL7 v2 parser (XML and ER7) | `app/integrations/hl7.py` | MSH, PID, OBR, OBX, NTE, MSA, ERR |
| Patient matching | `healthlink.match_patient` | PPSN (blind index), then IHI, then surname + DOB + first name, fada-insensitive. Only one unambiguous match is accepted; everything else waits for manual matching |
| Inbox workflow | `routers/inbox.py` | Review before filing; actions; tasks for reception; duplicates ignored and re-ACKed |
| ACK out / ACK in | `build_ack_er7`, `handle_ack` | ACK in updates the outbound message status (accepted or rejected, with errors) |
| eReferral out | `build_referral_xml` (REF^I12) | Generic structure, to be checked against *General Referral Message Construction v1.10+* |
| Transport | `DirectoryTransport` | Folder bridge (in / out / archive / failed). Atomic writes |

**Still to do before go-live:** the Healthlink web-service transport (needs the WSDL and
credentials, which follow GPIT approval), a Health Directory check of the GP's MCRN, and message
builders for CDM, under-6s, vaccinations and sick certs from the current Healthlink specs. HL7
licensing: the organisation must be an HL7 member to use the standard documents.

## Healthmail (HSE secure email)

- Each clinician links **their own** Healthmail account (Settings). The password is stored
  encrypted and used only for that clinician's requests while they are signed in (RFC 2.9.1, 2.9.4).
- Recipients must be on `EPR_HEALTHMAIL_ALLOWED_DOMAINS` (default `healthmail.ie,hse.ie`).
  Anything else is refused, so patient data never goes out over ordinary email.
- **Letters:** sent from the patient record with name, DOB, address and IHI header lines and any
  attachments (RFC 2.9.6–2.9.7).
- **ePrescription transfer (RFC 2.10):** Healthmail only; GP or nurse prescriber only; PDF shows
  date, patient name, address and GMS number, items with quantity and dose, single or repeat,
  and prescriber name, address and IMC number. OST is blocked. Schedule 2/3 CDs need an explicit
  confirmation. Every send is logged with the signed-in user and IP.
- SMTP (STARTTLS) and IMAP (TLS) host names come from the HSE onboarding pack, set in `.env`.
- Still to do: polling the Healthmail inbox into the clinical inbox (`healthmail.fetch_unseen`
  exists; the UI wiring does not), and the Healthmail directory search.

## PCRS

- **Patient listing import (RFC 2.3):** done. Upload the CSV from the PCRS portal under
  Patients → Import GMS panel. Matches on GMS number, then surname + DOB. Never duplicates.
- **Eligibility web service (RFC 2.2):** needs vendor registration with PCRS and their WSDL.
  Until then eligibility dates are stored locally. If they disagree with PCRS, PCRS is correct.
- **Claims:** STC, CDM and vaccination claims are recorded and exported as CSV for the portal.
  Electronic claiming via Healthlink follows the national programme specs.

## IHI (Individual Health Identifier)

- Stored as the full 18 digits, encrypted; the previous IHI is kept when one is replaced.
- Displayed everywhere as the 3-3-4 core number (positions 8–17).
- Validation: the GS1 check digit (position 18) is enforced. The mod-11 check (position 17) is
  computed with assumed weights and reported, but not enforced until confirmed against
  *IHI GP, GMS Seeding Process*.
- Purge-all is available to the governance role (RFC 2.7.8).

## Remote consultations (self-hosted Jitsi Meet)

1. Reception books a **video** appointment. This needs the patient's recorded video consent and a mobile number or email.
2. The clinician clicks **Start video**. The EPR creates an unguessable room name (no patient
   data in it), opens the clinician's moderator link and returns a single-use patient link that
   expires 2 hours after the slot.
3. The patient opens `/v/<token>`, sees the privacy and emergency notice, and joins the lobby. The clinician admits them.
4. A video consultation note is pre-opened. It can't be signed until consent and identity checks are ticked.

Jitsi settings are in `deploy/jitsi.env.example`: JWT auth, lobby, no recording, no third-party requests.

Sending the link: copy it into Healthmail, email or SMS. An SMS gateway adapter (an Irish/EU
provider under a DPA) is a natural next step. The patient's SMS consent is already recorded.
