// linkedin.js — SkillMate LinkedIn Sourcing extension. Runs ONLY on www.linkedin.com.
//
// background.js drives it with three requests; this script only ever reads the page in front of it:
//   LI_PROBE            is the visitor logged in, and is anything blocking the page?
//   LI_READ_PAGE        on a people-search results page: read every result card
//   LI_EXTRACT_CONTACT  on a profile's contact-info dialog: read the phone and email the person shared
//
// Nothing is ever rendered into, clicked on, or typed into the LinkedIn page. The search itself is a plain
// URL that background.js opens, and paging is a plain URL too.
//
// ⚠ LinkedIn's markup changes often, so cards are found by structure (a link to /in/<name> inside a list
// item) and read as visible text lines (core.js › parseResultLines), never by class name. If LinkedIn
// changes its layout, findCards() and extractContact() are the tuning points; the line parsing is tested
// in tests/core.test.js.

(function () {
  'use strict';

  const LOG = '[SkillMate · LinkedIn]';
  const Core = self.SkillmateLinkedinCore;
  if (!Core) return;

  // False once the extension was reloaded: this copy is cut off and must stop working.
  function alive() {
    try { return !!(chrome.runtime && chrome.runtime.id); } catch (e) { return false; }
  }

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const pageText = () => (document.body?.innerText || '').slice(0, 6000);
  const blockNow = () => Core.classifyBlock(location.href, pageText());

  // What the page in front of us shows, for a failed run's record (the recruiter can't read our console, and
  // "no results" is only useful if we can say what LinkedIn actually displayed). Taken from <main>: the top
  // navigation carries the viewer's own name and is left out.
  function snapshot() {
    const main = document.querySelector('main, [role="main"]');
    const text = ((main || document.body)?.innerText || '').replace(/\s+/g, ' ').trim();
    return {
      url: location.href.slice(0, 200),
      title: (document.title || '').slice(0, 80),
      hasMain: !!main,
      anchors: document.querySelectorAll('a[href*="/in/"]').length,
      text: text.slice(0, 200),
    };
  }

  // ── Result cards ──────────────────────────────────────────────────────────────

  const CARD_SEL = 'li, [role="listitem"], [data-view-name*="search-result"], [data-chameleon-result-urn]';
  const CHROME_SEL = 'header, nav, footer, aside, [role="navigation"], [role="banner"], #global-nav, .global-nav';

  function distinctProfiles(el) {
    const s = new Set();
    el.querySelectorAll('a[href*="/in/"]').forEach((a) => { const u = Core.normalizeProfileUrl(a.href); if (u) s.add(u); });
    return s.size;
  }

  // The element that holds one whole result. Prefer the outermost list item under <main> (a card also contains
  // smaller list items and a "mutual connections" link to somebody else); if the page has no list items, climb
  // while the parent still holds only one person.
  function cardFor(a, root) {
    let card = a.closest(CARD_SEL);
    if (card && root.contains(card)) {
      for (let up = card.parentElement && card.parentElement.closest(CARD_SEL); up && root.contains(up);
        up = card.parentElement && card.parentElement.closest(CARD_SEL)) card = up;
      return card;
    }
    let el = a;
    for (let i = 0; i < 12; i++) {
      const p = el.parentElement;
      if (!p || p === root || /^(UL|OL|MAIN|BODY)$/.test(p.tagName) || distinctProfiles(p) > 1) break;
      el = p;
    }
    return el;
  }

  function findCards() {
    const root = document.querySelector('main, [role="main"]') || document.body;
    const cards = new Map();   // card element -> the person's profile link (the first link in the card is the name)
    root.querySelectorAll('a[href*="/in/"]').forEach((a) => {
      if (a.closest(CHROME_SEL)) return;
      const link = Core.normalizeProfileUrl(a.href);
      if (!link) return;
      const card = cardFor(a, root);
      if (card && !cards.has(card)) cards.set(card, link);
    });
    return [...cards.entries()].map(([card, link]) => ({ card, link }));
  }

  function toProfile({ card, link }) {
    const p = Core.parseResultLines((card.innerText || '').split('\n'));
    if (!p) return null;
    const experiences = (p.title || p.company)
      ? [{ company: p.company, title: p.title, duration: '', is_current: true, starts_at: {}, ends_at: {} }]
      : [];
    return {
      name: p.name,
      headline: p.headline,
      snippet: p.snippet,
      location: p.location,
      source: 'LinkedIn',
      source_link: link,        // → the contact-info dialog is opened from this URL
      email: '',                // LinkedIn never shows contact details on a result card
      phone: '',
      skills: p.skills,
      experiences,
      education: [],
      total_experience: '',     // not shown on a card; SkillMate screens on the headline and snippet
      current_ctc: '',
      connection_degree: p.degree,
    };
  }

  // Is there a next page? true/false when LinkedIn's pager says so, null when it shows no pager at all.
  function hasNextPage() {
    const next = [...document.querySelectorAll('button[aria-label], a[aria-label]')]
      .find((e) => /\bnext\b/i.test(e.getAttribute('aria-label') || '') && !e.closest(CHROME_SEL));
    if (!next) return null;
    return !(next.disabled || next.getAttribute('aria-disabled') === 'true');
  }

  // LinkedIn fills in the lower cards only once they scroll into view: scroll the page through once.
  async function loadLazyCards() {
    try {
      const step = Math.max(400, Math.floor(window.innerHeight * 0.8));
      for (let y = 0; y <= document.documentElement.scrollHeight; y += step) {
        window.scrollTo(0, y);
        await sleep(250);
      }
      window.scrollTo(0, 0);
    } catch (e) { /* not scrollable: nothing to load */ }
  }

  // Wait for the results to render and stop changing, then read them.
  async function readPage() {
    const start = Date.now();
    let last = -1;
    let stableSince = 0;
    let timedOut = true;
    let scrolled = false;
    while (Date.now() - start < 25000) {
      if (!alive()) return { ok: false, error: 'extension_reloaded' };
      const block = blockNow();
      if (block) return { ok: true, block, profiles: [], ended: false };
      if (Core.isNoResultsText(pageText())) {
        return { ok: true, profiles: [], ended: true, noResults: true, diag: { ...snapshot(), cards: 0, noResults: true } };
      }
      const count = findCards().length;
      if (count && !scrolled) {
        scrolled = true;
        await loadLazyCards();
        continue;   // count again after the scroll
      }
      if (count) {
        if (count !== last) { last = count; stableSince = Date.now(); }
        else if (Date.now() - stableSince >= 1500) { timedOut = false; break; }
      }
      await sleep(600);
    }
    const block = blockNow();
    if (block) return { ok: true, block, profiles: [], ended: false };

    const cards = findCards();
    const seen = new Set();
    const profiles = cards.map(toProfile).filter((p) => p && !seen.has(p.source_link) && seen.add(p.source_link));
    const next = hasNextPage();
    // No pager and a short page = the only page; an empty page after a render timeout is not "the end".
    const ended = next === false || (next === null && cards.length > 0 && cards.length < 10)
      || (!timedOut && cards.length === 0);
    console.log(LOG, `read ${profiles.length} of ${cards.length} card(s); next=${next}; timedOut=${timedOut}`);
    return { ok: true, profiles, ended, diag: { ...snapshot(), cards: cards.length, timedOut, next } };
  }

  // ── Contact-info dialog ───────────────────────────────────────────────────────

  // The contact-info dialog opens on top of the profile page, so the profile's Experience section is already in the
  // page. Scroll down once (LinkedIn fills lower sections in as they come into view), then read that section.
  async function readExperience() {
    const find = () => [...document.querySelectorAll('section')]
      .filter((s) => /^experience$/i.test(((s.innerText || '').split('\n')[0] || '').trim()))
      .sort((a, b) => (a.innerText || '').length - (b.innerText || '').length)[0];
    let section = find();
    if (!section) {
      try {
        for (let y = 400; y <= 2400 && !section; y += 400) { window.scrollTo(0, y); await sleep(350); section = find(); }
        window.scrollTo(0, 0);
      } catch (e) { /* not scrollable */ }
    }
    return section ? Core.parseExperience((section.innerText || '').split('\n'), new Date()) : null;
  }

  // Every document root on the page: the document, and each open shadow root (LinkedIn renders some overlays in one).
  function openRoots() {
    const roots = [document];
    const visit = (root) => {
      root.querySelectorAll('*').forEach((el) => { if (el.shadowRoot) { roots.push(el.shadowRoot); visit(el.shadowRoot); } });
    };
    visit(document);
    return roots;
  }

  const DIALOG_SEL = '[role="dialog"], dialog[open], [aria-modal="true"], .artdeco-modal, [data-test-modal]';
  const textOf = (el) => (el.innerText || el.textContent || '');

  // The contact-info dialog: by its usual markup, or failing that by its "Contact info" heading and the nearest container
  // around it that also holds its rows.
  function findContactDialog() {
    const roots = openRoots();
    for (const root of roots) {
      for (const el of root.querySelectorAll(DIALOG_SEL)) {
        if (/contact info/i.test(textOf(el))) return { el, via: 'dialog-markup' };
      }
    }
    for (const root of roots) {
      const heading = [...root.querySelectorAll('h1, h2, h3, [role="heading"]')].find((h) => /^contact info$/i.test(textOf(h).trim()));
      if (heading) {
        let el = heading;
        for (let i = 0; i < 6 && el.parentElement; i++) {
          el = el.parentElement;
          if (Core.contactRowsLoaded(textOf(el).split('\n'))) break;
        }
        return { el, via: 'heading' };
      }
    }
    return null;
  }

  // The "Contact info" link in the profile's top card. LinkedIn only shows the dialog when this link is clicked on the profile:
  // loading the dialog's own address (/in/<name>/overlay/contact-info/) in a fresh tab shows the profile without it.
  function findContactLink() {
    for (const root of openRoots()) {
      const byId = root.querySelector('#top-card-text-details-contact-info');
      if (byId) return byId;
      const byHref = root.querySelector('a[href*="/overlay/contact-info"]');
      if (byHref) return byHref;
      const byText = [...root.querySelectorAll('a, button')].find((el) => /^contact info$/i.test(textOf(el).trim()));
      if (byText) return byText;
    }
    return null;
  }

  // Read one candidate's contact dialog. With `open` (the tab is on the profile page) this does what a person does: wait for the
  // profile's top card, read the Experience section, then click "Contact info" and wait for the dialog AND its rows (its title and
  // an InMail promo appear first; the email arrives a moment later). If the rows are up and hold no email for a couple of seconds,
  // the person does not share one. Without `open` the dialog is expected to be on the page already.
  async function extractContact(open) {
    const started = Date.now();
    const deadline = started + 22000;
    let found = null;
    let parsed = { email: '', phone: '' };
    let rows = false;
    let rowsAt = 0;
    let linkSeen = false;
    let clicks = 0;
    let clickedAt = 0;
    let experience = null;

    if (open) {
      // the profile renders after the page "loads": wait for its top card, then read the Experience section while no dialog covers it
      while (Date.now() < started + 10000 && !findContactDialog() && !(linkSeen = !!findContactLink())) {
        if (!alive()) return { ok: false, error: 'extension_reloaded' };
        const block = blockNow();
        if (block) return { ok: false, block };
        await sleep(400);
      }
      experience = await readExperience();
      try { window.scrollTo(0, 0); } catch (e) { /* not scrollable */ }
    }

    while (Date.now() < deadline) {
      if (!alive()) return { ok: false, error: 'extension_reloaded' };
      const block = blockNow();
      if (block) return { ok: false, block };
      found = findContactDialog();
      if (!found && open && clicks < 2 && (clicks === 0 || Date.now() - clickedAt > 4500)) {
        const link = findContactLink();
        if (link) { linkSeen = true; link.click(); clicks++; clickedAt = Date.now(); }
      }
      if (found) {
        const lines = textOf(found.el).split('\n');
        const mailtos = [...found.el.querySelectorAll('a[href^="mailto:"]')].map((a) => a.getAttribute('href'));
        parsed = Core.parseContactOverlay(lines, mailtos);
        if (Core.contactRowsLoaded(lines)) { rows = true; rowsAt = rowsAt || Date.now(); }
        if (parsed.email) break;                                  // got it
        if (rows && Date.now() - rowsAt > 2500) break;            // rows have been up a while and hold no email: not shared
      } else if (open && !linkSeen && Date.now() - started > 12000) {
        break;                                                    // no "Contact info" link on this page: nothing to open
      }
      await sleep(400);
    }
    if (!open) experience = await readExperience();
    const text = found ? textOf(found.el) : '';
    const diag = {
      found: !!found, via: found ? found.via : '', rows, ms: Date.now() - started, visible: document.visibilityState,
      link: linkSeen, clicks, textLen: text.length, sample: found && !parsed.email ? Core.redact(text, 140) : '',
    };
    console.log(LOG, `contact dialog: link=${linkSeen} clicks=${clicks} found=${diag.found} rows=${rows} email=${parsed.email ? 'yes' : 'no'} experience=${experience ? experience.text : 'unknown'} (${diag.ms} ms, ${diag.visible})`);
    return { ok: true, ...parsed, dialog: !!found, rows, experience, diag };
  }

  // ── Messaging ─────────────────────────────────────────────────────────────────

  chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
    if (msg?.type === 'LI_PROBE') {
      sendResponse({
        ok: true,
        url: location.href,
        loginForm: Core.hasVisibleLoginForm(document.querySelectorAll('input[type="password"]')),
        block: blockNow(),
      });
      return true;
    }
    if (msg?.type === 'LI_READ_PAGE') {
      readPage().then(sendResponse).catch((e) => sendResponse({ ok: false, error: e.message }));
      return true;
    }
    if (msg?.type === 'LI_EXTRACT_CONTACT') {
      extractContact(!!msg.open).then(sendResponse).catch((e) => sendResponse({ ok: false, error: e.message }));
      return true;
    }
    return false;
  });
})();
