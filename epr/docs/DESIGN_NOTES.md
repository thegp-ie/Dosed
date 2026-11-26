# Design notes: what we took from Irish GP experience

## Sources used

- **GPIT RFC_2022 v1.5** (National GPIT Group, ICGP/HSE): the certification standard. Mapped item by item in `GPIT_REQUIREMENTS.md`.
- **ICGP NEGs *Signposts to Success*** (2nd ed., 2014): handbook for establishing GPs. Its chapters on practice computerisation, practice management and state contracts.
- **Medical Protection (Ireland)** guidance on remote consulting and record keeping, and **Medisec**
  material on patients recording consultations. Medisec has no public guidance on remote
  consulting or retention that we could find, so their member advice should be checked directly.
- **HealthOne user group:** HEALTHone users formed the Health Ireland User Group (HIUG), which once
  held a majority stake in the supplier and was closely involved in product development. No
  recent user-group minutes or surveys were available, so we have not claimed specific HealthOne
  feedback. The lesson we take is about governance: Irish GPs value software shaped by its users.

## Principles that follow

1. **Let users steer the product.** Set up a practice user group from the first pilot. Hold quarterly
   sessions and keep a public backlog ranked by members. RFC_2022 expects a user-group section.
   *Signposts* tells establishing GPs to "contact other users/user groups before making a final
   decision"; make that easy.
2. **Show the daily routine, not the sales features.** *Signposts* advises GPs to ask vendors to demonstrate
   their typical day. So the home screen is Today's list, one click opens the patient, the summary fits
   on one screen, and results get one-click actions.
3. **Keyboard first.** `/` finds a patient, `Alt+C` opens a consultation, `Alt+P` prescribing, `Alt+I` the inbox.
   Search accepts name, DOB, GMS number, PPSN or chart number. It ignores fadas and apostrophes, so
   "o briain" finds "Ó Briain".
4. **Patient identity always visible.** The banner shows name, DOB, IHI, GMS number, chart number, allergies and flags on every screen (DC.1.1.2.7).
5. **Nothing is silently lost or overwritten.** Notes lock with addenda after them, entered-in-error notes stay visible, demographic history goes in the audit trail, records are merged not deleted, and retention reviews need a person.
6. **Moving away is easy.** Full-record and per-patient JSON export, plus a PCRS panel import for new practices. *Signposts* tells GPs to ask about "ease of transfer of current/future patient database to a new system".
7. **Healthlink compatibility is assumed by GPs.** *Signposts* notes that practices take it for granted that accredited systems work with Healthlink. Treat it as core, not optional.
8. **Every consultation counts** (CDM design): data recorded in routine consultations auto-fills CDM returns, so nothing is entered twice.
9. **Practice finances belong in the same system.** *Signposts* lists GMS payment streams (capitation, STCs, vaccination, Primary Childhood Immunisation, maternity, palliative care, Department of Social Protection certification). The system records claims and a private fees day-book (keep financial records 6–7 years for Revenue).

## Note on outdated guidance

*Signposts* (2014) says practices must register with the Data Protection Commissioner. GDPR
removed that requirement in 2018, and RFC_2022 also dropped it. The obligations are now the
GDPR accountability duties in `COMPLIANCE.md`.
