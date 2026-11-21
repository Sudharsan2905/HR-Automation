# SkillMate Sourcing (Chrome extension)

Separate extension for SkillMate's **Sourcing** module. SkillMate does the JD analysis,
search strings, screening, scoring and candidate creation; this extension does the part
that can only happen in the recruiter's logged-in browser: reading Naukri ResDex.

It is independent of the Softsuave Hire extension in the parent folder (Claude / ERP /
LinkedIn flows). Don't run both against SkillMate: only this one talks to SkillMate.

## Install
1. `chrome://extensions` → turn on **Developer mode** → **Load unpacked** → pick this
   `skillmate_sourcing` folder.
2. Log in to Naukri ResDex in the same Chrome profile.
3. Reload any open SkillMate and ResDex tabs.

## Use
- In SkillMate → **Sourcing**, open a JD and click **Source from Naukri**.
- The extension opens ResDex's search form in a background tab, types the JD's Boolean
  keywords, experience, location and max CTC, and clicks **Search candidates** — no searching
  by hand, no credits spent. The tab stays open so you can see what was searched.
- It then works **one result page at a time**: it sends the page to SkillMate, waits while
  SkillMate screens it, and clicks ResDex's Next only if SkillMate asks for more (fewer than 5
  matches so far, or 2 extra pages for the pool once 5 are found).
- You don't need to watch that tab. Don't close it or change its search while a run is going.
- Selecting a candidate in SkillMate opens that one profile to read phone/email
  (**1 ResDex credit**).
- The toolbar popup shows SkillMate/ResDex status and the current run, and can stop it.

## Configure
Edit `config.js` (`SKILLMATE_URL`, `SKILLMATE_API_ORIGINS`), list the same origins in
`manifest.json` (`host_permissions` and the bridge's `content_scripts` matches), then
reload the extension.

## Files
| File | Purpose |
|---|---|
| `bridge.js` | Content script on SkillMate pages; relays page ↔ background messages |
| `background.js` | Login check, runs, posting to SkillMate, contact reveal |
| `naukri.js` | Fills the ResDex search form, reads result cards, pages through results, reveals contact |
| `core.js` | Pure helpers (tested: `node --test tests/`) |
| `popup.*` | Status popup styled like SkillMate |
