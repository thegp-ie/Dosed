# AI scribe (consultation transcription)

Records the consultation with the patient's agreement, transcribes it, and drafts a SOAP note with
suggested ICPC-2 and ICD-10 codes. The clinician edits the draft and accepts it into the note.

## Design: everything stays in the practice

```
browser mic ──► EPR (audio held in RAM, never saved) ──► Whisper server (self-hosted)
                                                          │ transcript
                    clinician reviews ◄── draft JSON ◄─── LLM server (self-hosted Ollama)
                          │ accept
                    consultation note (flagged "AI-assisted draft, reviewed")
```

- No cloud AI. Audio, transcripts and drafts never leave infrastructure the practice controls,
  so the self-hosting and EU-residency requirements still hold, and there is no new processor to
  contract with.
- **Audio** is never written to disk (the container's `/tmp` is RAM-backed) and is discarded after transcription.
- **Transcript and draft** are AES-256-GCM encrypted. They are deleted when the clinician accepts or
  discards, or after `EPR_SCRIBE_RETAIN_DAYS`. Abandoned sessions are purged after 24 hours by an hourly job.
- **Audit:** start (with consent), draft (with model names and length), and accept or discard are all logged.

## Running the models

1. **Speech-to-text:** a Whisper server on a GPU machine in the practice (or an EU host you control),
   such as the whisper.cpp HTTP server (`/inference`) or a faster-whisper server. Set `EPR_STT_URL` to the
   endpoint that accepts a multipart `file` and returns `{"text": ...}`. Large Whisper models handle Irish
   accents and place names noticeably better than small ones, so test with your own voices.
2. **Note drafting:** an Ollama server with an open-weight instruction model that supports structured
   (JSON-schema) output. Set `EPR_LLM_URL` and `EPR_LLM_MODEL`. Pick the model by testing (below), not by name.
3. Restrict both servers to the EPR host (firewall). They must not be reachable from the internet.

## Before using it with patients

- **Evaluate:** run 30–50 consented or simulated consultations covering your case mix (accents,
  interpreters, children, multiple problems). Check every draft for omissions, invented content,
  wrong laterality and wrong doses. Record the error rate and choose the model on that evidence.
- **DPIA update:** add AI scribe processing (voice data, health data, on-premises, retention).
- **Patient information:** a notice in the waiting room and on the website. Patients must be able to say no,
  and recording does not start until the clinician ticks that the patient agreed.
- **EU AI Act:** as the deployer, the practice must tell patients AI is used (Art. 50
  transparency) and keep a person in charge of the output. The clinician reviews and accepts every draft.
- **Medical Device Regulation:** the scribe is a documentation aid. It is told to record only what was
  said and not to diagnose. Adding diagnostic suggestions, treatment advice or risk scores would likely make
  it a medical device needing conformity assessment.
- **Medical Council and indemnity:** the clinician remains responsible for the record. Check with
  Medisec or Medical Protection before rollout.

## What the model is told

See `SYSTEM_PROMPT` in `app/ai_scribe.py`. It must record only what was said, list uncertainties
instead of guessing, leave examination findings blank unless they were spoken, use Irish clinical terms,
suggest codes with supporting quotes, ignore instructions inside the transcript, and leave out identifiers.
Output must match a JSON schema. Codes are checked against ICPC-2 and the loaded ICD list, and invalid ones
are removed and listed for the clinician.

## Cloud models

Not built. A cloud LLM (for example Claude through the Anthropic API) would draft better notes than most
models a practice can run itself. It would also make the provider a processor of health data, which needs
an Art. 28 agreement, a check of where data is processed and of transfer safeguards, and a DPIA update.
That conflicts with the "self-hosted" requirement. If the practice decides otherwise, add it as a second
backend behind `draft_note()`, keep transcription local, and send only the transcript text.
