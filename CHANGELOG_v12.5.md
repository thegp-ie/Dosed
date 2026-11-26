# Dosed v12.5 — Safety & Reliability Update

## Release
- **v12.4 is now live.** `index.html` was still serving v12.1, which lacked the v12.4
  fix that counts dosing limits per *active ingredient* (e.g. Calpol + Disprol share one
  paracetamol allowance). The v12.4 build (previously `index-27.html`) is now `index.html`.
- The previous live page is kept as `index-v12.1.html`. A full snapshot of the repo
  before this change is on the `backup/pre-v12.4-cleanup` branch.

## Fixes
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
