# Dosed Changelog

Newest first. Older notes: `CHANGELOG_v11.md`, `CHANGELOG_v10.md`.

## v12.8 — Backup & restore with reminders
- **Back up now** saves everything (children, records, prescriptions, photos and
  custom barcodes) to one `dosed-backup-YYYY-MM-DD.json` file. On phones it opens
  the share sheet (save to Files, Google Drive, iCloud, email or WhatsApp); elsewhere
  it downloads.
- **Restore from backup** uses the same merge rules as share links: it adds only
  what's missing and never overwrites or duplicates. Restoring the same file twice
  changes nothing.
- **Reminder banner** appears when there are 5 or more records and no backup has
  been made, or when the last backup is over 7 days old and data has changed since.
  "Remind me later" hides it for 2 days.
- Data Management shows when the last backup was made and whether there's new data since.
- The app asks the browser to protect its storage from automatic clearing.
- Photos in shared links and backups are kept only if they are plain image data.
- The header's release date had been stuck on "February 2026". The version and date
  are now set once (`APP_VERSION` / `APP_RELEASE_DATE` near the top of the script),
  and the header and share/backup files use them.

## v12.7 — QR codes fixed, merge-on-import
- **QR codes work again.** The page loaded `qrcode@1.5.3/build/qrcode.min.js`, a file
  that doesn't exist in that version, so the QR library never loaded. The working
  1.4.4 build is now bundled in `vendor/qrcode.min.js` (no CDN needed; it works offline).
- **Importing never duplicates or overwrites.**
  - Children, records and prescriptions keep a stable origin id across devices, so
    repeated shares and sharing back and forth are recognised.
  - If the child already exists (same origin, or same name and date of birth for
    children imported by older versions), only new records and prescriptions are added.
    Anything already present is skipped.
  - Existing profile details are never changed. Blank fields such as weight or date of
    birth may be filled in.
  - The confirm dialog shows how many items are new and how many are skipped. A link with
    nothing new reports "already up to date" and changes nothing.
  - New imports no longer get an "(imported)" suffix.

## v12.6 — Episode-aware charts
- **Latest Episode view.** Readings (temperature, doses, symptoms, heart or
  respiratory rate) with no gap longer than 48 hours are grouped into one illness
  episode. When the most recent episode was in the last 14 days, Health Trends
  opens zoomed to it.
- **Episode summary** above the charts: start → end (or "now" if a reading was taken in
  the last 24h), duration, and for each child the peak temperature and doses given by
  ingredient.
- **Doses on the temperature chart:** triangles mark each dose (blue for paracetamol,
  amber for ibuprofen, grey for other medication). Tap one to see the medicine and amount.
- **Dashed 38°C fever line** on the temperature chart.
- **Separate episodes are no longer joined.** Temperature, heart-rate and
  respiratory-rate lines break at gaps longer than 48h.
- **Time axis adapts to the range:** hourly for Latest Episode and Past Week, days
  or months for longer ranges.
- Any range you pick by hand stays selected until the page is reloaded.

## v12.5 — Safety & Reliability Update

### Release
- **v12.4 is now live.** `index.html` was still serving v12.1, which lacked the v12.4
  fix that counts dosing limits per *active ingredient* (e.g. Calpol + Disprol share one
  paracetamol allowance). The v12.4 build (previously `index-27.html`) is now `index.html`.
- The previous live page is kept as `index-v12.1.html`. A full snapshot of the repo
  before this change is on the `backup/pre-v12.4-cleanup` branch.

### Fixes
- **Offline mode / updates (`sw.js`)**
  - Cache paths are now relative, so the service worker installs correctly under `/Dosed/`
    on GitHub Pages (the old `/` and `/index.html` pointed at the domain root).
  - The app page is loaded network-first, so users get new versions (and safety fixes)
    as soon as they are online; the cached copy is used only when offline.
  - The cache is versioned (`dosed-v12.5`) and old caches are deleted on update.
  - CDN URLs now match the exact versions the page loads.
  - Pages are cached by path only, so legacy `?import=` links never store health data in the cache.
- **Sharing**
  - Links now work with any characters (e.g. "Seán", emoji). Previously `btoa()` threw an error.
  - Share data is compressed, so links and QR codes are much shorter.
  - Data now goes in the link's `#fragment`, which is never sent to the web server, so it
    no longer appears in hosting logs.
  - Photos are no longer included in shares (they made links too large for QR or WhatsApp).
  - Old `?import=` links still import.
  - "Paste share link" now imports directly, and opening a share link while the app is already
    open now works.
- **Security:** imported data is sanitised. Markup characters are stripped from every field
  and photos are dropped, so a crafted share link can no longer inject code into the page.
