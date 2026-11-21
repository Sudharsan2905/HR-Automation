// naukri.js — SkillMate Sourcing extension. Runs ONLY on naukri.com / resdex.naukri.com.
//
// Two jobs, both started by background.js on behalf of SkillMate:
//   1. MH_SKILLMATE_CRAWL — on a ResDex results tab: read every result card, page through
//      pages pageFrom..pageTo with ResDex's own Next control, and hand the profiles back
//      (MH_SKILLMATE_CRAWL_DONE). Paging spends NO ResDex credit.
//   2. MH_EXTRACT_CONTACT — on a /v3/preview profile tab opened by background.js: reveal
//      and read phone/email. This DOES spend one credit, so it only runs for a candidate
//      the recruiter selected in SkillMate.
//
// Nothing is ever rendered into the Naukri page. The card readers and contact reveal are
// carried over unchanged from the Softsuave Hire extension (proven against live ResDex);
// ⚠ the selectors are heuristic — findCandidateCards / extractProfileFromCard /
// findNextControl / scrapeContact are the tuning points if Naukri changes its markup.

(function () {
  'use strict';

  const LOG = '[SkillMate · Naukri]';

  // False once the extension was reloaded: this copy is cut off and must stop working.
  function alive() {
    try { return !!(chrome.runtime && chrome.runtime.id); } catch (e) { return false; }
  }
  const Core = self.SkillmateCore;

  // Contact details already printed on a result card cost nothing to read, so keep both.
  const capturePref = { phone: true, email: true };

  // ── Extraction ────────────────────────────────────────────────────────────────

  // Find each candidate's card WITHOUT relying on class names (ResDex ships obfuscated,
  // frequently-changing markup). Every candidate row contains links of two kinds:
  //   • /v3/preview?tabKey=profile...  → name + headline (also the profile URL)
  //   • /v3/simcv?...                  → that row's "N similar profiles"
  // So: walk up from a preview link until the ancestor holds exactly ONE simcv link.
  // That element is the card boundary — structural, so class renames can't break it.
  const PREVIEW_SEL = 'a[href*="preview?tabKey=profile"]';

  function findCandidateCards() {
    const cards = new Set();
    document.querySelectorAll(PREVIEW_SEL).forEach((a) => {
      let el = a;
      for (let i = 0; i < 12 && el.parentElement; i++) {
        el = el.parentElement;
        if (el.querySelectorAll('a[href*="simcv"]').length === 1) { cards.add(el); break; }
      }
    });
    return [...cards];
  }

  function extractProfiles() {
    const profiles = [];
    try {
      const cards = findCandidateCards();
      cards.forEach((card) => {
        const p = extractProfileFromCard(card);
        if (p && p.name) profiles.push(p);
      });
    } catch (err) {
      console.error(LOG, 'extract error:', err);
    }
    const seen = new Set();
    return profiles.filter((p) => (seen.has(p.name) ? false : seen.add(p.name)));
  }

  function text(el, selector) {
    const node = el.querySelector(selector);
    return node?.textContent?.trim() || '';
  }

  // Pull phone/email from a card, honoring the HR's capture preference. ResDex often
  // hides contact info behind a "view"/credit action; we grab whatever is in the DOM.
  function extractContact(card) {
    const out = { email: '', phone: '' };
    if (capturePref.email) {
      const mailto = card.querySelector('a[href^="mailto:"]');
      if (mailto) out.email = mailto.getAttribute('href').replace(/^mailto:/i, '').trim();
      if (!out.email) {
        const m = (card.textContent || '').match(/[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/i);
        if (m) out.email = m[0];
      }
    }
    if (capturePref.phone) {
      const tel = card.querySelector('a[href^="tel:"]');
      if (tel) out.phone = tel.getAttribute('href').replace(/^tel:/i, '').trim();
      if (!out.phone) {
        // +country / 10-digit Indian mobile, tolerant of spaces/dashes.
        const m = (card.textContent || '').match(/(\+?\d[\d\s-]{8,}\d)/);
        if (m) out.phone = m[0].replace(/\s+/g, ' ').trim();
      }
    }
    return out;
  }

  // ResDex renders "3y 4m", "₹5.50 Lacs" etc. as plain text inside the card, not in
  // labelled elements — so regex over the card's text is far more reliable than any
  // selector. These patterns are the tuning point if the display format changes.
  function parseExperience(cardText) {
    let m = cardText.match(/(\d+)\s*y(?:r|rs|ear|ears)?\s*(\d+)?\s*m(?:o|os|onth|onths)?/i);
    if (m) {
      const years = parseInt(m[1], 10);
      const months = m[2] ? parseInt(m[2], 10) : 0;
      return { text: `${years}y ${months}m`, years, months, totalMonths: years * 12 + months };
    }
    m = cardText.match(/(\d+(?:\.\d+)?)\s*(?:years?|yrs?)/i);
    if (m) {
      const years = parseFloat(m[1]);
      return { text: `${years} years`, years: Math.floor(years), months: 0, totalMonths: Math.round(years * 12) };
    }
    return null;
  }

  function parseCtc(cardText) {
    const m = cardText.match(/(?:₹|Rs\.?|INR)?\s*(\d+(?:\.\d+)?)\s*(?:L|Lac|Lacs|Lakh|Lakhs)\b/i);
    return m ? { text: `${m[1]}L`, lacs: parseFloat(m[1]) } : null;
  }

  function extractProfileFromCard(card) {
    try {
      // Name + headline both come from preview links; the first non-empty one is the
      // name, and the longest distinct one is the headline/designation.
      const previewLinks = [...card.querySelectorAll(PREVIEW_SEL)]
        .map((a) => ({ text: a.textContent.trim(), href: a.href }))
        .filter((l) => l.text);
      if (previewLinks.length === 0) return null;

      const name = previewLinks[0].text;
      const link = previewLinks[0].href; // the candidate's profile URL (used for contact reveal)
      const headline = previewLinks.slice(1).map((l) => l.text).sort((a, b) => b.length - a.length)[0] || '';

      // Designation / company / skills all render as `button.link-button`, in that
      // order: [0] designation, [1] company, [2+] skills.
      const chips = [...card.querySelectorAll('button.link-button, button[class*="link-button"]')]
        .map((b) => b.textContent.trim())
        .filter(Boolean);
      const company = chips[1] || '';
      const skills  = chips.slice(2);

      const cardText = card.textContent || '';
      const exp = parseExperience(cardText);
      const ctc = parseCtc(cardText);

      const location = text(card, '[class*="location"], [class*="city"], [class*="loc"]')
        || (cardText.match(/\b(Chennai|Bengaluru|Bangalore|Hyderabad|Mumbai|Pune|Delhi|Noida|Gurugram|Gurgaon|Kolkata|Coimbatore|Ahmedabad|Jaipur|Trivandrum|Kochi|Indore|Nagpur)\b/i)?.[0] || '');

      const eduText = text(card, '[class*="education"], [class*="degree"], .edu');
      const { email, phone } = extractContact(card);

      const experiences = [];
      if (company || headline) {
        experiences.push({
          company,
          title: chips[0] || headline,
          duration: exp?.text || '',
          is_current: true,
          starts_at: {},
          ends_at: {},
        });
      }
      const education = [];
      if (eduText) education.push({ degree: eduText, field_of_study: '', ends_at: {} });

      return {
        name,
        headline,
        location,
        source: 'Naukri',
        source_link: link,        // → ERP custom_source_link, and the contact-reveal URL
        email,                    // → ERP email_id (only if captured/found)
        phone,                    // → ERP phone_number
        skills,
        experiences,
        education,
        about: '',
        // Surfaced flat so SkillMate can score on them without parsing prose.
        total_experience: exp?.text || '',
        experience_years: exp ? +(exp.totalMonths / 12).toFixed(1) : undefined,
        current_ctc: ctc?.text || '',
        current_ctc_lacs: ctc?.lacs,
        // No match_score from Naukri — SkillMate scores it against the JD.
        match_score: undefined,
        match_reasons: [],
        _raw_experience_text: exp?.text || '',
      };
    } catch (err) {
      console.error(LOG, 'card error:', err);
      return null;
    }
  }

  // ── Page helpers ──────────────────────────────────────────────────────────────

  function currentPageNo() {
    try {
      const u = new URL(location.href);
      for (const p of ['pageNo', 'page', 'pageNumber']) {
        const v = Number(u.searchParams.get(p));
        if (Number.isFinite(v) && v >= 1) return Math.round(v);
      }
    } catch (e) { /* fall through */ }
    // DOM fallback: the selected item in ResDex's own pager, if it's a plain integer.
    const active = document.querySelector(
      '[class*="pagination"] [aria-current="true"], [class*="pagination"] [aria-current="page"], ' +
      '[class*="pagination"] [class*="active"], [class*="pagination"] [class*="selected"]');
    if (active) {
      const n = Number((active.innerText || active.textContent || '').trim());
      if (Number.isFinite(n) && n >= 1) return Math.round(n);
    }
    return null;
  }

  function ssGet(key) {
    try { return JSON.parse(sessionStorage.getItem(key) || 'null'); } catch (e) { return null; }
  }
  function ssSet(key, val) {
    try { sessionStorage.setItem(key, JSON.stringify(val)); } catch (e) { /* blocked — ok */ }
  }

  // The search, independent of which result page we're on — so paging doesn't look like
  // a new search and a genuinely new search starts a fresh crawl.
  function naukriSearchKey() {
    try {
      const u = new URL(location.href);
      ['pageNo', 'page', 'pageNumber', 'start', 'from', 'offset'].forEach((p) => u.searchParams.delete(p));
      return u.pathname + '?' + u.searchParams.toString();
    } catch (e) { return location.pathname; }
  }

  // Find ResDex's own "Next page" control — never synthesise a &pageNo= URL. Prefer
  // semantic hooks (rel/aria) over a text match, and never treat a disabled control as
  // clickable. A leftover last-page "Next" that does nothing is caught by the watchdog.
  function findNextControl() {
    const relNext = document.querySelector('a[rel="next"]');
    if (relNext && relNext.getAttribute('aria-disabled') !== 'true') return relNext;

    const byAria = [...document.querySelectorAll('a[aria-label], button[aria-label], [role="button"][aria-label]')]
      .find((e) => /\bnext\b/i.test(e.getAttribute('aria-label') || '')
        && !e.disabled && e.getAttribute('aria-disabled') !== 'true' && !inPageChrome(e));
    if (byAria) return byAria;

    const byText = [...document.querySelectorAll('a, button, [role="button"]')]
      .find((e) => {
        const t = (e.innerText || e.textContent || '').trim();
        return /^next(\s*page|\s*›|\s*»|\s*>)?$/i.test(t)
          && t.length < 14 && !e.disabled
          && e.getAttribute('aria-disabled') !== 'true' && !inPageChrome(e);
      });
    return byText || null;
  }

  // ── SkillMate crawl ─────────────────────────────────────────────────────────────
  // State lives in sessionStorage because ResDex may reload the tab between result pages.
  const JOB_KEY = 'smCrawlJob';
  const STABILITY_MS = 1500;          // result count must hold this long before reading
  const STALL_MS = 12000;             // Next didn't advance / page stayed empty → wrap up
  const MAX_PAGES_TOUCHED = 24;       // absolute ceiling on pages walked in one run
  const crawlPause = () => 3000 + Math.floor(Math.random() * 5000); // 3–8 s, human-ish

  let stableTimer = null;
  let watchdog = null;
  let lastCount = -1;

  const getJob = () => ssGet(JOB_KEY);
  const setJob = (j) => ssSet(JOB_KEY, j);
  const clearJob = () => { try { sessionStorage.removeItem(JOB_KEY); } catch (e) { /* ok */ } };
  const profileKey = (p) => (p.source_link || p.name || '').trim().toLowerCase();

  function send(msg) {
    try { chrome.runtime.sendMessage(msg); } catch (e) { console.error(LOG, 'send failed:', e.message); }
  }

  function trimProfile(p) {
    const { about, _raw_experience_text, ...rest } = p;
    return rest;
  }

  function hashProfiles(profiles) {
    const key = profiles.map((p) => p.name).join('|');
    let h = 5381;
    for (let i = 0; i < key.length; i++) h = ((h << 5) + h + key.charCodeAt(i)) | 0;
    return String(h);
  }

  function fail(job, reason) {
    clearTimeout(watchdog);
    clearJob();
    console.warn(LOG, `run ${job.runId} stopped: ${reason}`);
    send({ type: 'MH_SKILLMATE_CRAWL_FAIL', runId: job.runId, reason });
  }

  // Hand one page to background.js and wait: SkillMate screens it, then says "next" or "stop".
  function sendPage(job, profiles, ended, page) {
    clearTimeout(watchdog);
    job.waiting = true;
    job.updatedAt = Date.now();
    setJob(job);
    console.log(LOG, `run ${job.runId}: page ${page ?? '?'} → SkillMate (${profiles.length} profile(s))` +
      `${ended ? ' — end of results' : ''}`);
    send({
      type: 'MH_SKILLMATE_CRAWL_PAGE_DATA', runId: job.runId, page,
      profiles: profiles.map(trimProfile), ended: !!ended, sourceUrl: location.href,
    });
  }

  // ResDex has nothing more (Next did nothing / no Next / page went empty after Next).
  function endOfResults(job) {
    sendPage(job, [], true, null);
  }

  function schedule() {
    if (!alive()) { pageObserver.disconnect(); clearTimeout(stableTimer); clearTimeout(watchdog); return; }
    const job = getJob();
    if (!job || job.waiting) return;
    if (location.pathname.includes('/preview')) return; // a profile tab, not results
    clearTimeout(stableTimer);
    stableTimer = setTimeout(tick, STABILITY_MS);
  }

  function tick() {
    if (!alive()) return;
    const job = getJob();
    if (!job || job.waiting) return;

    if (Core && Core.isCaptchaText((document.body?.innerText || '').slice(0, 5000))) {
      fail(job, 'captcha');
      return;
    }

    const profiles = extractProfiles();
    if (profiles.length === 0) {
      // Empty page: wait out the stall window, then either it's past the last page (we already
      // sent pages) or the search never showed results (no matches, or broken selectors).
      if (!job.emptySince) { job.emptySince = Date.now(); setJob(job); }
      if (Date.now() - job.emptySince > STALL_MS) {
        if (job.collected > 0) endOfResults(job);
        else fail(job, 'no_results');
        return;
      }
      setTimeout(schedule, 3000);
      return;
    }
    if (job.emptySince) { job.emptySince = 0; setJob(job); }

    // Stability gate: a changing count means ResDex is still rendering.
    if (profiles.length !== lastCount) {
      lastCount = profiles.length;
      schedule();
      return;
    }

    if (job.key && job.key !== naukriSearchKey()) {
      fail(job, 'search_changed');
      return;
    }

    const pageHash = hashProfiles(profiles);
    if (pageHash === job.lastHash) {
      // Same page as last time: Next didn't move us. After the stall window, that's the end.
      if (Date.now() - (job.updatedAt || 0) > STALL_MS) endOfResults(job);
      return;
    }
    if (job.pagesDone >= MAX_PAGES_TOUCHED) { fail(job, 'error'); return; }

    const cur = currentPageNo(); // null when ResDex hides the page number
    const collecting = cur === null ? true : (cur >= job.pageFrom && cur <= job.pageTo);
    job.lastHash = pageHash;
    job.pagesDone += 1;
    job.updatedAt = Date.now();
    job.key = job.key || naukriSearchKey();

    if (collecting) {
      job.collected += 1;
      const page = cur ?? job.pageFrom + job.collected - 1;
      sendPage(job, profiles, !findNextControl(), page);
      return;
    }
    console.log(LOG, `page ${cur} skipped (before ${job.pageFrom})`);
    setJob(job);
    advance(job);
  }

  // Click ResDex's own Next after a human-ish pause.
  function advance(job) {
    const wait = crawlPause();
    console.log(LOG, `next page in ${Math.round(wait / 1000)}s`);
    lastCount = -1;
    clearTimeout(watchdog);
    setTimeout(() => {
      const j = getJob();
      if (!j || j.runId !== job.runId || j.waiting) return;   // cancelled meanwhile
      if (naukriSearchKey() !== j.key) { fail(j, 'search_changed'); return; }
      const n = findNextControl();
      if (!n) { endOfResults(j); return; }
      try { n.click(); } catch (e) { endOfResults(j); return; }
      // A click that doesn't change the page within the stall window = last page.
      watchdog = setTimeout(() => {
        const j2 = getJob();
        if (j2 && j2.runId === j.runId && !j2.waiting && j2.pagesDone === j.pagesDone) endOfResults(j2);
      }, STALL_MS);
      schedule();
    }, wait);
  }

  // SkillMate wants another page.
  function nextPage(runId) {
    const job = getJob();
    if (!job || job.runId !== runId) return false;
    job.waiting = false;
    job.updatedAt = Date.now();
    setJob(job);
    advance(job);
    return true;
  }

  function startJob(msg) {
    const from = Math.max(1, Math.round(Number(msg.pageFrom) || 1));
    const to = Math.max(from, Math.min(Math.round(Number(msg.pageTo) || from), from + 9));
    setJob({
      runId: msg.runId, pageFrom: from, pageTo: to, key: naukriSearchKey(), waiting: false,
      pagesDone: 0, collected: 0, lastHash: '', updatedAt: 0, emptySince: 0,
    });
    lastCount = -1;
    schedule();
  }

  // ── Contact reveal (runs on a /v3/preview profile page) ─────────────────────────
  // background.js opens a selected candidate's profile URL in a BACKGROUND tab, then
  // asks this script (which also runs there) to reveal + scrape the contact, then
  // closes the tab. Only candidates the recruiter explicitly picked are ever opened,
  // because revealing contact spends ResDex credits.

  // ResDex hides the number behind a "View phone number" control (email is shown
  // outright). It is not necessarily a <button>, so match on text across common
  // clickable tags — but only ever click ONE, since each reveal costs a credit.
  const REVEAL_LABELS = /^(view|show|get|reveal|unlock)\b[\s\S]{0,20}\b(phone|number|mobile|contact)\b/i;
  const CONFIRM_LABELS = /^(confirm|yes|view|ok|okay|proceed|continue)$/i;

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  function findRevealControls() {
    const found = [];
    document.querySelectorAll('button, a, [role="button"], span, div').forEach((el) => {
      const t = (el.innerText || el.textContent || '').trim();
      if (!t || t.length > 32) return;
      if (!REVEAL_LABELS.test(t)) return;
      // Leaf-ish only — skip wrappers that merely contain the real control.
      if (el.querySelector('button, a, [role="button"]')) return;
      if (inPageChrome(el)) return;
      found.push({ el, text: t });
    });
    return found;
  }

  function clickRevealControls() {
    const controls = findRevealControls();
    if (controls.length === 0) return 0;
    try { controls[0].el.click(); } catch (e) { return 0; }
    return 1; // exactly one — never risk spending two credits on one candidate
  }

  // Some reveal flows put a confirmation in the way before charging the credit.
  function clickConfirmIfPresent() {
    for (const el of document.querySelectorAll('button, [role="button"]')) {
      const t = (el.innerText || el.textContent || '').trim();
      if (CONFIRM_LABELS.test(t)) { try { el.click(); return true; } catch (e) { /* ignore */ } }
    }
    return false;
  }

  // Page chrome (Naukri's own header/footer/support links, and the RECRUITER's own
  // company address) must never be mistaken for the candidate's contact. Returning an
  // empty field is always better than returning someone else's — a wrong number in ERP
  // is worse than a blank one.
  const EMAIL_BLOCKLIST = /@(naukri|infoedge|resdex|softsuave)\b|^(support|info|careers|career|hr|noreply|no-reply|donotreply|help|contact|sales|admin|webmaster)@/i;
  const EMAIL_RE = /[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/i;

  // textContent glues adjacent nodes together ("…@gmail.com" + "Verified" →
  // "…@gmail.comverified"), so trim a trailing word back to a known TLD.
  function cleanEmail(e) {
    const m = (e || '').match(/^(.+@[^@\s]+?\.(?:com|in|org|net|co|edu|io|info|biz|me|dev))(?:[a-z]+)?$/i);
    return m ? m[1] : (e || '');
  }

  function validEmail(raw) {
    const e = cleanEmail((raw || '').trim().toLowerCase());
    if (!e || !EMAIL_RE.test(e)) return '';
    if (EMAIL_BLOCKLIST.test(e)) return '';
    return e;
  }

  // Accept only a full Indian mobile (10 digits starting 6-9), optionally +91 prefixed.
  // Anything shorter is page furniture (support numbers, partial matches) — reject it.
  function validPhone(raw) {
    const digits = (raw || '').replace(/\D/g, '');
    const m = digits.match(/(?:0|91)?([6-9]\d{9})$/);
    return m ? m[1] : '';
  }

  // Skip nodes that live in obvious page chrome rather than the candidate's detail area.
  function inPageChrome(el) {
    return !!el.closest('header, nav, footer, [class*="header"], [class*="nav"], [class*="footer"], [class*="gnb"], [class*="support"]');
  }

  function scrapeContact() {
    const out = { phone: '', email: '' };

    // 1) Prefer explicit mailto:/tel: links outside page chrome.
    for (const a of document.querySelectorAll('a[href^="mailto:"]')) {
      if (inPageChrome(a)) continue;
      const e = validEmail(a.getAttribute('href').replace(/^mailto:/i, ''));
      if (e) { out.email = e; break; }
    }
    for (const a of document.querySelectorAll('a[href^="tel:"]')) {
      if (inPageChrome(a)) continue;
      const p = validPhone(a.getAttribute('href').replace(/^tel:/i, ''));
      if (p) { out.phone = p; break; }
    }

    // 2) Otherwise look next to an explicit label. ResDex renders the revealed contact
    //    as plain text (mailto:/tel: links are absent), so read innerText — it keeps
    //    element boundaries as newlines, whereas textContent glues neighbours together.
    if (!out.email || !out.phone) {
      for (const el of document.querySelectorAll('div, span, li, td, p')) {
        if (el.children.length > 4) continue;
        const t = (el.innerText || el.textContent || '').trim();
        if (!t || t.length > 200) continue;
        if (inPageChrome(el)) continue;

        if (!out.email && /e-?mail/i.test(t)) {
          for (const m of t.matchAll(new RegExp(EMAIL_RE, 'gi'))) {
            const e = validEmail(m[0]);
            if (e) { out.email = e; break; }
          }
        }
        if (!out.phone && /phone|mobile|whats\s*app|contact\s*(no|number)/i.test(t)) {
          for (const m of t.matchAll(/(?:\+?91[\s-]?)?[6-9][\d\s-]{9,13}/g)) {
            const p = validPhone(m[0]);
            if (p) { out.phone = p; break; }
          }
        }
        if (out.email && out.phone) break;
      }
    }

    // 3) Last resort for EMAIL only — a whole-page scan is safe there because the
    //    blocklist rejects Naukri's and the recruiter's own addresses.
    //
    //    Deliberately NOT done for phone: the recruiter's own company number lives in
    //    the page chrome (e.g. +91 80151 08933), and a page-wide scan returned it for
    //    every candidate. The phone is only ever read from the revealed area — see
    //    phoneNear() — so a wrong number can never reach ERP.
    if (!out.email) {
      const body = document.body?.innerText || '';
      for (const m of body.matchAll(new RegExp(EMAIL_RE, 'gi'))) {
        const e = validEmail(m[0]);
        if (e) { out.email = e; break; }
      }
    }

    return out;
  }

  // Walk up a few levels to get the block surrounding an element.
  function containerOf(el, levels = 4) {
    let cur = el;
    for (let i = 0; i < levels && cur.parentElement; i++) cur = cur.parentElement;
    return cur;
  }

  // Read a valid mobile ONLY from within the given scope (the revealed contact area).
  function phoneNear(scope) {
    if (!scope) return '';
    const t = scope.innerText || scope.textContent || '';
    for (const m of t.matchAll(/(?:\+?91[\s-]?)?[6-9][\d\s-]{9,13}/g)) {
      const p = validPhone(m[0]);
      if (p) return p;
    }
    return '';
  }

  async function revealContactOnThisPage() {
    // Wait for the profile to render (it is client-side rendered).
    for (let i = 0; i < 24; i++) {
      if ((document.body?.innerText || '').length > 600) break;
      await sleep(250);
    }

    let contact = scrapeContact();
    const revealControls = findRevealControls().map((c) => c.text);
    let clicked = 0;

    if (!contact.phone) {
      const controls = findRevealControls();
      // The revealed number appears where the control was, so remember that block and
      // read the phone ONLY from there — never from the page at large.
      const scope = controls[0] ? containerOf(controls[0].el, 4) : null;

      clicked = clickRevealControls();
      if (clicked) {
        await sleep(700);
        clickConfirmIfPresent();
        // The number arrives via an async request — poll rather than guess a delay.
        for (let i = 0; i < 16; i++) {
          await sleep(500);
          const p = phoneNear(scope) || phoneNear(scope?.parentElement);
          if (p) { contact.phone = p; break; }
          if (i === 3) clickConfirmIfPresent(); // dialog may render late
        }
      }
      console.log(LOG, `reveal: controls=[${revealControls.join(' | ')}] clicked=${clicked} →`,
        `phone=${contact.phone || '(none)'} email=${contact.email || '(none)'}`);
    }

    // The profile tab is opened in the background and closed within ~a second, so its
    // console is unreadable. Ship the diagnostics back so background.js can log them
    // to the service-worker console, which persists.
    const labels = [];
    document.querySelectorAll('div, span, li, td, p').forEach((el) => {
      if (labels.length >= 12 || el.children.length > 3) return;
      const t = (el.textContent || '').trim();
      if (t && t.length < 120 && /e-?mail|phone|mobile|contact/i.test(t)) labels.push(t);
    });

    // Digit runs tell us whether a real 10-digit number is even present after the
    // reveal — distinguishing "our scraper missed it" from "ResDex never showed it".
    const bodyText = document.body?.innerText || '';
    const digitRuns = [...bodyText.matchAll(/[\d][\d\s\-()+]{7,}/g)]
      .slice(0, 8).map((m) => m[0].trim().slice(0, 24));

    contact._diag = {
      url: location.href.slice(0, 120),
      textLen: bodyText.length,
      revealControls,
      clicked,
      digitRuns,
      labels,
    };
    return contact;
  }

  // ── Automatic search (runs on the ResDex search form) ───────────────────────────
  // Found by what the recruiter sees (placeholders, labels, button text), not by class
  // names, which ResDex changes on every release.

  async function waitFor(fn, timeoutMs) {
    const end = Date.now() + timeoutMs;
    while (Date.now() < end) {
      const v = fn();
      if (v) return v;
      await sleep(300);
    }
    return null;
  }

  function isShown(el) { return !!el && el.offsetParent !== null && el.getClientRects().length > 0; }

  function fieldByPlaceholder(re) {
    return [...document.querySelectorAll('input, textarea')]
      .find((el) => isShown(el) && re.test(el.getAttribute('placeholder') || '')) || null;
  }

  // The main keyword box: its placeholder mentions keywords (the header's own search box
  // just says "Search").
  function keywordField() {
    return fieldByPlaceholder(/keyword|boolean|skills,?\s*designation/i);
  }

  // React keeps its own copy of an input's value; set it through the native setter and
  // fire the events React listens for.
  function setFieldValue(el, value) {
    el.focus();
    const proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, value);
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
  }

  function closeSuggestions(el) {
    el.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', code: 'Escape', bubbles: true }));
    el.blur();
  }

  // A "Boolean off / on" switch label. The form has two (Keywords and Designation), so it is
  // looked up inside the smallest block that contains the given field.
  const BOOLEAN_RE = /^boolean\s*(off|on)$/i;
  function booleanLabelIn(root) {
    return [...root.querySelectorAll('label, span, div, p, button')]
      .find((el) => isShown(el) && el.children.length <= 2 && BOOLEAN_RE.test((el.innerText || '').trim())) || null;
  }
  function booleanLabelFor(field) {
    for (let node = field.parentElement; node && node !== document.body; node = node.parentElement) {
      const label = booleanLabelIn(node);
      if (label) return label;
    }
    return null;
  }

  async function turnBooleanOn(field) {
    const label = booleanLabelFor(field);
    if (!label) return false;
    if (/on$/i.test(label.innerText.trim())) return true;
    const targets = [label, label.previousElementSibling, label.parentElement,
      label.querySelector('input[type="checkbox"], [role="switch"]')].filter(Boolean);
    for (const t of targets) {
      t.click();
      await sleep(500);
      const kw = keywordField();
      const now = kw && booleanLabelFor(kw);
      if (now && /on$/i.test(now.innerText.trim())) return true;
    }
    return false;
  }

  function searchButton() {
    return [...document.querySelectorAll('button, [role="button"], input[type="submit"]')]
      .filter((b) => isShown(b) && !b.disabled
        && /^search\s+candidates$/i.test((b.innerText || b.value || '').trim()))
      .pop() || null;  // the tab strip also says "Search candidates"; the submit button comes last
  }

  // Tick a checkbox found by its visible label text.
  function tickByLabel(re) {
    const label = [...document.querySelectorAll('label, span, div, p')]
      .find((el) => isShown(el) && el.children.length <= 3 && re.test((el.innerText || '').trim()));
    if (!label) return false;
    const box = label.querySelector('input[type="checkbox"]')
      || label.parentElement?.querySelector('input[type="checkbox"]');
    if (box && box.checked) return true;
    (box || label).click();
    return true;
  }

  // Location is an autocomplete: type, then click the suggestion that matches.
  async function addLocation(field, city) {
    setFieldValue(field, city);
    const want = city.toLowerCase();
    const option = await waitFor(() => [...document.querySelectorAll('li, [role="option"], .suggestor-item, div')]
      .find((el) => isShown(el) && el !== field && el.children.length <= 2
        && (el.innerText || '').trim().toLowerCase() === want), 4000);
    if (!option) { closeSuggestions(field); return false; }
    option.click();
    await sleep(400);
    return true;
  }

  async function fillSearchForm({ keywords, expMin, expMax, locations, ctcMaxLacs }) {
    if (!keywords) throw new Error('no keywords in the search plan');
    const first = await waitFor(keywordField, 20000);
    if (!first) throw new Error('keyword field not found');

    const booleanOn = await turnBooleanOn(first);
    // Switching Boolean on can re-render the keyword box — look it up again.
    const kw = await waitFor(keywordField, 5000);
    if (!kw) throw new Error('keyword field not found after Boolean switch');
    setFieldValue(kw, keywords);
    await sleep(300);
    closeSuggestions(kw);

    const filled = { booleanOn, experience: false, locations: [], salary: false };

    const minEl = fieldByPlaceholder(/min(imum)?\s*exp/i);
    const maxEl = fieldByPlaceholder(/max(imum)?\s*exp/i);
    if (minEl && expMin != null) { setFieldValue(minEl, String(expMin)); closeSuggestions(minEl); }
    if (maxEl && expMax != null) { setFieldValue(maxEl, String(expMax)); closeSuggestions(maxEl); }
    filled.experience = !!(minEl && maxEl);

    const locEl = fieldByPlaceholder(/add\s*location/i);
    for (const city of (locations || []).slice(0, 5)) {
      if (locEl && await addLocation(locEl, city)) filled.locations.push(city);
    }

    if (ctcMaxLacs != null) {
      const maxSal = fieldByPlaceholder(/max(imum)?\s*salary/i);
      if (maxSal) {
        setFieldValue(maxSal, String(ctcMaxLacs));
        closeSuggestions(maxSal);
        filled.salary = true;
        // Don't drop people who left their CTC blank — screening handles them.
        tickByLabel(/^include candidates who did not mention their current salary$/i);
      }
    }
    await sleep(500);

    const btn = searchButton();
    if (!btn) throw new Error('Search candidates button not found');
    btn.click();
    return filled;
  }

  // ── Messaging ───────────────────────────────────────────────────────────────────

  chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
    if (msg?.type === 'MH_SKILLMATE_CRAWL') {
      startJob(msg);
      sendResponse({ ok: true });
      return true;
    }
    if (msg?.type === 'MH_SKILLMATE_CRAWL_NEXT') {
      sendResponse({ ok: nextPage(msg.runId) });
      return true;
    }
    if (msg?.type === 'MH_SKILLMATE_CRAWL_STOP') {
      clearTimeout(watchdog);
      clearJob();
      sendResponse({ ok: true });
      return true;
    }
    if (msg?.type === 'MH_SKILLMATE_FILL_SEARCH') {
      fillSearchForm(msg)
        .then((r) => sendResponse({ ok: true, ...r }))
        .catch((e) => sendResponse({ ok: false, error: e.message }));
      return true;
    }
    if (msg?.type === 'MH_SKILLMATE_LOGIN_PROBE') {
      sendResponse({
        ok: true,
        url: location.href,
        loginForm: self.SkillmateCore.hasVisibleLoginForm(document.querySelectorAll('input[type="password"]')),
      });
      return true;
    }
    if (msg?.type === 'MH_EXTRACT_CONTACT') {
      revealContactOnThisPage()
        .then((c) => sendResponse({ ok: true, ...c }))
        .catch((e) => sendResponse({ ok: false, error: e.message }));
      return true;
    }
    return false;
  });

  // ── Boot ────────────────────────────────────────────────────────────────────────
  // A run in progress survives ResDex reloading the tab between pages: pick it up again.
  const pageObserver = new MutationObserver(schedule);
  pageObserver.observe(document.documentElement, { childList: true, subtree: true });
  schedule();
})();
