# Medicines formulary and clinical coding: sources and licences

Checked November 2026. Licence terms change, so confirm each one with the publisher before go-live.

## Medicines

| Source | Cost / licence | What it gives you | What it does not | In Dosed EPR |
|---|---|---|---|---|
| **HPRA "Human Medicines – Authorised Products"** (XML on hpra.ie, mirrored on data.gov.ie) | Free, published as open data. Updated frequently | Every medicine authorised in Ireland: product name, licence (PA) number, holder, active substances, form. HPRA also publishes interchangeable-medicines and withdrawn-products lists | Doses, indications, interactions, GMS reimbursement status | `load-formulary hpra_xml`: searchable drug picker, ATC-based allergy class check, CD schedule warning |
| **HSE National Medicinal Product Catalogue (NMPC)** (nmpc.hse.ie) | Under the HSE *Downstream End User Licence Agreement* (v1.0, 23 March 2026). The catalogue is supplied through Dedalus. Contact nmpc@hse.ie about fees and vendor terms | The national catalogue for ePrescribing and ePharmacy: CSV, NDJSON and a FHIR R4 terminology API | Clinical decision support | `load-formulary nmpc_csv` takes its CSV export. A FHIR terminology client is the natural next step |
| **Irish Medicines Formulary (IMF)** | Commercial subscription | Irish monographs, PCRS reimbursement details, HSE Medicines Management Programme preferred drugs | – | Not loaded (licensed product) |
| **MIMS Ireland** | Commercial (Metropolis) | Prescribing guide | – | Not loaded |
| **medicines.ie** | Free to read | SmPCs and patient leaflets | Not licensed as a bulk dataset | Link out only |
| **HSE Medicines Management Programme** | Free | Preferred drugs and best-value lists (PDF) | Machine-readable data | Could become a "preferred" flag later |

**Is the old free formulary still available?** We found no free, complete *clinical* formulary for
Ireland today. The free national sources are the HPRA product register (a list of authorised
products) and the HSE NMPC, which is under its own licence. Clinical content (doses,
interactions, contraindications) still comes from a licensed knowledge base (IMF, or an
international drug-knowledge vendor with Irish mapping). If you remember a specific free
product, tell us its name and we will check its status.

**Drug-drug interaction checking (GPIT DC.2.3.1.1, a SHALL requirement)** needs one of those
licensed knowledge bases. Plug it into `routers/clinical.py::_safety_checks`. What runs now: allergy
checks by name, active substance and ATC drug class (penicillins, cephalosporins,
sulfonamides, NSAIDs, aspirin, opioids), duplicate items, and controlled-drug schedule prompts.

**HPRA file format:** we could not download the current XML from this build environment. The importer
therefore matches element names loosely (ProductName, LicenceNumber, ActiveSubstance, DosageForm,
ATCCode, SupplyStatus and common variants) and refuses a file it cannot recognise. Run it once on the
real file and check a few products before relying on it.

## Clinical coding

| System | Use in Irish general practice | Licence | In Dosed EPR |
|---|---|---|---|
| **ICPC-2** | Primary GP classification (ICGP); used in CDM, sick certs | WONCA. Get the full table under licence | Built-in subset; load the full table to replace it |
| **ICD-10** | Hospitals (HIPE uses ICD-10-AM); accepted in DSP sick certs | WHO copyright. Get the data file under a WHO licence | `load-codes ICD10 file.csv` (columns `code,title`) |
| **ICD-11** | WHO current version; gradual adoption | **Free**, CC BY-ND 3.0 IGO: commercial use allowed, codes must not be adapted. Mappings and crosswalks need a separate WHO agreement | `load-codes ICD11 file.tsv` (WHO linearization TSV), or live search through WHO's **locally deployable ICD-API container** (`EPR_ICD_API_URL`). Only the search text is sent, and it stays on your server |
| **SNOMED CT (Irish Edition)** | National clinical terminology (HIQA recommendation); HSE National Release Centre | **Free affiliate licence** from the HSE NRC (snomed@hse.ie). Read the licence: some international-content conditions apply | `load-codes SNOMED subset.csv` for a practice subset. Full release support (RF2, terminology server) to do |

**Dual coding:** problems and consultations carry an ICPC-2 code plus an optional ICD-10, ICD-11 or SNOMED
code. Once a code list is loaded, codes must exist in it. Before that, only the code format is
checked, and the code is shown as unverified.

**Rule-driven coding assistance (GPIT S.3.2.1):** the AI scribe suggests ICPC-2 and ICD-10 codes, quoting the
words that support each one. Unrecognised codes are removed, and the clinician chooses what to keep.
