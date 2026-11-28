# Dosed Roadmap

Possible future improvements. Nothing here is scheduled until it's picked up.

## Ideas
- **Optional Fahrenheit display.** Show temperatures in °F as a setting, while
  keeping Celsius as the default and the stored unit.
- **Recognise a bottle from its label** (no barcode needed): read the product name
  and strength from a photo with on-device text recognition (e.g. Tesseract.js,
  ~10 MB). Barcode learning (v12.10) covers most of this more reliably.
- **Bundle remaining CDN libraries** (Tailwind, Lucide, Chart.js) locally, so the app
  loads fully offline and doesn't depend on outside servers.
- **Red-flag guidance:** link abnormal readings to NICE fever traffic-light advice
  (e.g. fever in a baby under 3 months: seek care).
- **One-page summary for a GP or ED visit:** temperature chart, doses in the last
  24–48 hours and symptoms.
- **Accessibility:** labels for icon-only buttons; replace browser `alert()` pop-ups
  with in-page messages.
- **Reminders on a locked phone:** dose reminders currently only fire while the
  app is open.
- **Verify pack dosing tables against current Irish packs** for Calpol Infant,
  Disprol, Calpol Six Plus and Piriton (Nurofen was checked against the pack).
