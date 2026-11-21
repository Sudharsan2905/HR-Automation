# SkillMate LinkedIn Sourcing (Chrome extension)

A **separate** extension for SkillMate's Sourcing module, next to the Naukri one (`../skillmate_sourcing`).
SkillMate does the JD analysis, search strings, screening, scoring and candidate creation; this extension
does the part that can only happen in the recruiter's logged-in browser: reading LinkedIn people search.

It shares nothing with the Naukri extension at runtime — different message names (`LINKEDIN_*` /
`skillmate-li-*`), different storage, different pages — so each can be installed, updated or removed on its
own, and a problem in one cannot break the other. Install both; SkillMate uses LinkedIn when Naukri can't be
used (see below).

## Install
1. `chrome://extensions` → turn on **Developer mode** → **Load unpacked** → pick this `linkedin_sourcing` folder.
2. Log in to LinkedIn in the same Chrome profile (a plan with people search; see "Limits").
3. Reload any open SkillMate and LinkedIn tabs.

## How SkillMate uses it
On **Hiring → a JD → Source candidates**, SkillMate uses **both** sources when it can:

1. **Naukri first.** It reads ResDex (or serves matches it had already found) and shortlists up to 5.
2. **Then LinkedIn, in the same click.** When the Naukri run finishes, SkillMate says "Naukri is done. Checking LinkedIn too…"
   and starts a LinkedIn run that **reads LinkedIn's own site** (it is not answered from what Naukri left in the pool) and
   shortlists up to 5 of **LinkedIn's own** people. So one click can add up to 5 from each source.
3. **LinkedIn is skipped, with a note,** when its extension isn't installed or logged in, or LinkedIn has no more results for
   the search. Naukri-only and LinkedIn-only use work exactly as before.

LinkedIn also takes over when Naukri can't be used: the Naukri extension isn't installed, ResDex isn't logged in or has no more
results, or a Naukri run fails (CAPTCHA, form not found, nothing found). Then you see "Naukri failed — switching to LinkedIn".

**One copy of a person.** The same person can appear on both. If an email is already known for both, the second copy is dropped
on arrival; otherwise, when you select one copy, the other undecided copies with the same email are rejected as
"Duplicate: same email as …" (visible under Rejected), and the invite goes out once either way.

## What a run does
1. Checks the LinkedIn login (your open LinkedIn tab, otherwise a background tab on the feed). No profile is opened.
2. Opens **one** background tab and loads the people-search results page by page by URL:
   `…/search/results/people/?keywords=<the JD's Boolean string, plus its cities>&page=N`.
   **The search is broadened automatically when LinkedIn finds nobody.** LinkedIn ANDs every skill, so a long list matches
   no one. The extension first drops soft-skill groups ("Problem-solving", "Communication skills"…), then tries, narrowest
   first: all technical groups + the JD's cities → without the cities → the first 5 groups → 3 → 2 (the plan lists the most
   central skills first). The step that found people is reported to SkillMate and reused by later runs, so paging continues
   on the same search. Only the first page of a JD's first LinkedIn run is retried this way; an empty later page just means
   the results ran out. If even the broadest step finds nobody the run stops with "no people… even after broadening".
3. Reads each result card (name, headline, location, "Current:" / "Skills:" line, snippet), then reads each card's contact
   dialog (see "Only candidates with an email") and sends the page to SkillMate with only the people who have one.
4. Waits while SkillMate screens it, and loads the next page only if SkillMate asks (fewer than 5 matches so far,
   or one extra page for the pool once 5 are found). Between pages it pauses a random 6–14 s.
5. Stops on a CAPTCHA / security check (the tab is brought forward so you can complete it), a login page, a
   search-limit or restriction notice, or no results.

LinkedIn result cards don't show a full skills list, so SkillMate marks a mandatory skill it can't see on the
card as **unverified** (never "absent"): the profile is still scored and the recruiter sees a "verify" note.

## Only candidates with an email
**A LinkedIn candidate is taken only if they have an email.** A LinkedIn result card never shows one, and LinkedIn
shares a phone/email only with your **1st-degree connections** (it appears in the profile's contact-info dialog). So
with `EMAIL_ONLY` on (the default, in `config.js`):

1. The search is limited to your 1st-degree connections (LinkedIn's "Connections: 1st" filter). Any 2nd or 3rd-degree
   card that still appears is skipped without opening its profile.
2. For every remaining card the extension opens that person's **profile** in a work tab and clicks **Contact info**, the same
   as you would, then reads the email from the dialog (with a pause of a few seconds between profiles). It does not load the
   dialog's own address (`/in/<name>/overlay/contact-info/`) directly: LinkedIn shows the profile without the dialog when
   that address is opened in a fresh tab, which is why v1.4.0 and older read nothing.
3. **Only the people whose dialog gave an email are sent to SkillMate.** Everyone else is left out, and SkillMate refuses a
   LinkedIn profile without an email even if some other build sent it. The page is still reported (`scanned`), so a page
   where nobody shared an email counts as read and the run moves on.
4. **Each person is sent the moment their email is read** (`POST /sourcing/runs/{id}/profile`, v1.5.0+), not when the
   whole page is done. SkillMate stores and screens them at once, so they appear in the Candidates table one by one while
   the page is still being read, and the page's own post at the end only closes the page. If SkillMate does not have that
   endpoint (an older backend) or a send fails, the person is sent with the page as before.

Because every shortlisted LinkedIn candidate has an email, **they are not auto-selected**: no invite goes out until you
click **Select** (see `HIRING_AUTO_SELECT_LINKEDIN` in the backend settings). A run that reads people but finds no
emails ends with a message saying how many connections were checked and how many shared one.

This is slower and touches more LinkedIn pages than before: roughly one profile view per 1st-degree card, ~10 per page,
about 4 pages per click. If LinkedIn shows a CAPTCHA or a limit notice while contacts are read, the run stops and the
tab stays in front. Set `EMAIL_ONLY: false` to send every card again (emails are then read when you click Select).

## Only the JD's experience is applied (not location, not CTC)
LinkedIn's standard people search has **no years-of-experience filter**, so the JD's experience range is applied by the
extension itself (`FILTER_BY_EXPERIENCE`, default on). The profile page sits behind the contact dialog, so the extension
reads its **Experience** section, adds up the date ranges (overlapping jobs are counted once) and sends the total as
`experience_years`. Someone outside the range is left out, and SkillMate's scorer enforces the same range. If LinkedIn shows
only some positions ("Show all N experiences") the total is a floor: it can prove someone too senior, never too junior. If
no dates can be read the person is kept.

**Location and CTC are not used for LinkedIn candidates:** the search carries no city, no card is skipped for its location,
and salary is never shown on LinkedIn. (Naukri still applies both.)

## Reading the contact dialog reliably
"0 shared an email" must mean the dialogs were read and held no email, never that they could not be read. So:
- The reader waits for the dialog's **contact rows**, not just the dialog: its title and an InMail promo appear first and the
  email arrives a moment later. It finds the dialog by its markup (`role="dialog"`, `<dialog>`, `aria-modal`, shadow roots) or,
  failing that, by its "Contact info" heading, and accepts any valid address in it.
- If LinkedIn does not render in a background tab (three unreadable dialogs in a row) the work tab is brought to the front
  once and the people it could not read are read again.
- If dialogs still cannot be read the run **fails with "could not read LinkedIn's contact dialogs"** instead of reporting an
  empty result.
- Every page leaves a one-line record on the run (`debug`): cards, connection degrees, dialogs opened and really read,
  emails found, people over the experience range, and a masked sample of any dialog it could not read. No email or phone
  number is ever stored in it.

## One email per person
If the same person is found on Naukri and on LinkedIn they get **one** Level 1 invite. A LinkedIn card never shows an
email, so both copies can appear in the shortlist; the duplicate is caught when they are selected: both resolve to the
same SkillMate candidate (candidates are created by email) and SkillMate reuses the first hiring row, so there is one
invite and one result email. (A copy whose page already shows an email that was found before is dropped on arrival.)

## Limits and risks — read before using
- **LinkedIn's terms forbid automated collection.** This extension reads pages the way a person would, slowly and
  only in your own session, but LinkedIn may still warn, restrict or ban the account. Use a recruiter account the
  company is prepared to risk, keep volumes low, and stop when LinkedIn shows a warning.
- Free accounts hit LinkedIn's monthly **commercial use limit** quickly (the run stops with "search limit").
  Recruiter Lite / Recruiter / Sales Navigator are far more usable.
- Cards come from LinkedIn's own markup, which changes. If a run says it found no results while the LinkedIn tab
  shows people, the card finder in `linkedin.js` (`findCards`) is the one place to adjust; the text parsing
  (`core.js › parseResultLines`) is unit-tested.
- LinkedIn lists your nearest connections first. A results page made only of hidden "LinkedIn Member" cards (people
  outside your network) is treated as the end of the useful results.
- LinkedIn fills in the lower result cards only when they scroll into view, and a background tab may not render
  them. The extension scrolls each page once; if cards still come back empty set `WORK_TAB_ACTIVE: true` in `config.js`
  (the work tab then opens in the foreground).
- A run lives in the browser's service worker. If Chrome is closed mid-run, SkillMate times the run out after
  20 minutes and the next click starts a fresh one.

## Configure
Edit `config.js` (`SKILLMATE_URL`, `SKILLMATE_API_ORIGINS`, the pause ranges), list the same origins in
`manifest.json` (`host_permissions` and the bridge's `content_scripts` matches), then reload the extension.

## Files
| File | Purpose |
|---|---|
| `bridge.js` | Content script on SkillMate pages; relays page ↔ background messages |
| `background.js` | Login check, runs, posting to SkillMate, contact read |
| `linkedin.js` | Content script on linkedin.com: reads result cards, the contact dialog, and detects blocks |
| `core.js` | Pure helpers: URLs, search query, card and dialog parsing |
| `tests/` | Run with `node --test` in this folder: `core.test.js` (parsing) and `background.test.js` (a run end to end against a mocked Chrome and SkillMate API, ~15 s) |
| `popup.*` | Status popup styled like SkillMate |
