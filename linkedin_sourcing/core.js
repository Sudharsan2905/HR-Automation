// core.js — pure helpers for the SkillMate LinkedIn Sourcing extension.
//
// Loaded by the SkillMate bridge, the LinkedIn content script, background.js (importScripts)
// and the popup. Also `require`-able from Node for unit tests
// (tests/core.test.js, run with `node --test tests/`). No chrome.* or DOM calls here, so
// everything that reads LinkedIn's text (result cards, the contact-info dialog) is testable.

(function (root) {
  'use strict';

  // Message namespace. Deliberately different from the Naukri extension's ("skillmate-page" /
  // "SKILLMATE_*") so both extensions can sit on the same SkillMate page without answering each other.
  const PAGE_SOURCE = 'skillmate-li-page';
  const EXT_SOURCE = 'skillmate-li-ext';
  const REQUEST_TYPES = [
    'LINKEDIN_PING',
    'LINKEDIN_CHECK_LOGIN',
    'LINKEDIN_SOURCE',
    'LINKEDIN_REVEAL',
    'LINKEDIN_CANCEL',
  ];

  // ── Origins and URLs ──────────────────────────────────────────────────────────

  function originOf(url) {
    try { return new URL(url).origin; } catch (e) { return ''; }
  }

  // The page that sent a message must be exactly the configured SkillMate origin.
  function isAllowedOrigin(origin, skillmateUrl) {
    if (!origin) return false;
    return origin === originOf(skillmateUrl);
  }

  function isPageRequest(data) {
    return !!data
      && data.source === PAGE_SOURCE
      && typeof data.type === 'string'
      && REQUEST_TYPES.includes(data.type)
      && typeof data.requestId === 'string';
  }

  // The SkillMate token is only ever sent to an API base whose origin is on the allow-list.
  function isAllowedApiBase(apiBase, allowedOrigins) {
    const o = originOf(apiBase);
    return !!o && (allowedOrigins || []).map(originOf).includes(o);
  }

  function apiUrl(apiBase, path) {
    return String(apiBase).replace(/\/+$/, '') + '/' + String(path).replace(/^\/+/, '');
  }

  function linkedinPath(url) {
    let u;
    try { u = new URL(url); } catch (e) { return null; }
    const host = u.hostname.toLowerCase();
    if (!(host === 'linkedin.com' || host.endsWith('.linkedin.com'))) return null;
    return u.pathname;
  }

  // LinkedIn bounces a logged-out visitor to a login or "authwall" page.
  function isLinkedinLoginUrl(url) {
    const path = linkedinPath(url);
    return path !== null && /^\/(login|uas\/|checkpoint\/lg\/|authwall|signup)/i.test(path);
  }

  // Security checks after login (CAPTCHA, "verify it's you") live under /checkpoint/ — except its login pages.
  function isLinkedinCheckpointUrl(url) {
    const path = linkedinPath(url);
    return path !== null && /^\/checkpoint\//i.test(path) && !/^\/checkpoint\/lg\//i.test(path);
  }

  const CAPTCHA_RE = /quick security check|verify (that )?you(?:'|’)?re (a )?(human|not a robot)|security verification|are you a robot|solve (this|the) puzzle/i;
  const RESTRICTED_RE = /commercial use limit|reached the (monthly )?(search|commercial)|temporarily restricted|account (has been|is) (temporarily )?restricted|we(?:'|’)ve restricted your account/i;

  // What, if anything, stops a run on this page: 'not_logged_in' | 'captcha' | 'restricted' | null.
  function classifyBlock(url, text) {
    if (isLinkedinLoginUrl(url)) return 'not_logged_in';
    if (isLinkedinCheckpointUrl(url)) return 'captcha';
    const t = String(text || '').slice(0, 6000);
    if (RESTRICTED_RE.test(t)) return 'restricted';
    if (CAPTCHA_RE.test(t)) return 'captcha';
    return null;
  }

  function isNoResultsText(text) {
    return /no results found|no matching (results|people)|couldn(?:'|’)t find anything/i.test(String(text || '').slice(0, 6000));
  }

  // ── The search ────────────────────────────────────────────────────────────────

  // The keyword string for this search plan (narrowed only when the plan says so).
  function searchKeywords(plan) {
    if (!plan) return '';
    const narrowed = (plan.narrowed_keywords || '').trim();
    if (plan.use_narrowed && narrowed) return narrowed;
    return (plan.primary_keywords || '').trim();
  }

  // Split a Boolean string on a top-level operator (AND / OR): not inside brackets, not inside "quotes".
  function splitTopLevel(query, op) {
    const text = String(query || '');
    const sep = new RegExp(`\\s+${op}\\s+`, 'y');
    const parts = [];
    let depth = 0;
    let inQuote = false;
    let start = 0;
    for (let i = 0; i < text.length; i++) {
      const ch = text[i];
      if (ch === '"') inQuote = !inQuote;
      else if (!inQuote && ch === '(') depth++;
      else if (!inQuote && ch === ')') depth = Math.max(0, depth - 1);
      else if (!inQuote && depth === 0 && /\s/.test(ch)) {
        sep.lastIndex = i;
        const m = sep.exec(text);
        if (m) { parts.push(text.slice(start, i)); i += m[0].length - 1; start = i + 1; }
      }
    }
    parts.push(text.slice(start));
    return parts.map((s) => s.trim()).filter(Boolean);
  }

  // Soft skills and personal traits can't be searched for ("Communication skills" in quotes matches almost no
  // profile). Mirrors backend/app/components/sourcing/agents.py › _SOFT_SKILL, which strips them when a JD is
  // analysed; this catches plans built before that, and ones edited by hand.
  const SOFT_SKILL = new RegExp(
    '^(?:(?:good|strong|excellent|effective)\\s+)?(?:(?:verbal|written|oral|interpersonal)\\s+)?communication(?:\\s+skills?)?$'
    + '|^(?:good\\s+)?problem[\\s-]*solving(?:\\s+(?:skills?|abilit(?:y|ies)))?$'
    + '|^(?:team[\\s-]*work|team\\s+player|collaboration|collaborative|leadership|interpersonal\\s+skills?'
    + '|critical\\s+thinking|analytical\\s+(?:thinking|skills?)|time\\s+management|adaptability|work\\s+ethic'
    + '|self[\\s-]*motivat(?:ed|ion)|attention\\s+to\\s+detail|creativity|ownership|fast\\s+learner|ability\\s+to\\s+learn'
    + '|decision[\\s-]*making|presentation\\s+skills?)$', 'i');

  // Do the first "(" and the last ")" belong together, i.e. does one pair of brackets wrap the whole text?
  function wrapsWhole(text) {
    let depth = 0;
    let inQuote = false;
    for (let i = 0; i < text.length; i++) {
      const ch = text[i];
      if (ch === '"') inQuote = !inQuote;
      else if (!inQuote && ch === '(') depth++;
      else if (!inQuote && ch === ')') {
        depth--;
        if (depth === 0 && i < text.length - 1) return false;
      }
    }
    return depth === 0;
  }

  function stripOuterBrackets(text) {
    let s = String(text || '').trim();
    while (s.startsWith('(') && s.endsWith(')') && wrapsWhole(s)) s = s.slice(1, -1).trim();
    return s;
  }

  // A group like ("Problem-solving") or ("Teamwork" OR "Team player"): every alternative is a soft skill.
  function isSoftGroup(group) {
    const alternatives = splitTopLevel(stripOuterBrackets(group), 'OR');
    if (!alternatives.length) return false;
    return alternatives.every((alt) => SOFT_SKILL.test(
      stripOuterBrackets(alt).replace(/^"|"$/g, '').replace(/\s+/g, ' ').trim().replace(/[.,;:-]+$/, '')));
  }

  const LADDER_GROUP_CAPS = [5, 3, 2];

  // The searches to try, narrowest first. LinkedIn ANDs everything, so a long list of skills (or a city on top)
  // often matches nobody; each later step is broader than the one before:
  //   0  the plan's keywords without soft-skill groups, plus the JD's cities
  //   1  the same without the cities
  //   2+ only the first 5, then 3, then 2 skill groups (the plan lists the most central skills first)
  // Steps that would repeat the one before are left out, so an index always means the same search for a plan.
  function searchLevels(plan) {
    const keywords = searchKeywords(plan);
    if (!keywords) return [];
    let groups = splitTopLevel(keywords, 'AND');
    const technical = groups.filter((g) => !isSoftGroup(g));
    if (technical.length) groups = technical;                     // never strip a plan down to nothing
    const cities = ((plan && plan.locations) || []).map((c) => String(c).trim().replace(/"/g, '')).filter(Boolean).slice(0, 5);
    const join = (gs) => gs.join(' AND ');
    const levels = [];
    const add = (q) => { if (q && !levels.includes(q)) levels.push(q); };
    add(cities.length ? `(${join(groups)}) AND (${cities.map((c) => `"${c}"`).join(' OR ')})` : join(groups));
    if (cities.length) add(join(groups));
    for (const cap of LADDER_GROUP_CAPS) if (groups.length > cap) add(join(groups.slice(0, cap)));
    return levels;
  }

  // What is typed into LinkedIn's keyword box at a given step of the ladder (0 = the narrowest).
  function buildSearchQuery(plan, level) {
    const levels = searchLevels(plan);
    if (!levels.length) return '';
    return levels[Math.min(Math.max(0, Math.round(Number(level) || 0)), levels.length - 1)];
  }

  // People-search results page n. Paging by URL is how LinkedIn's own pager works.
  function buildSearchUrl(plan, page, level) {
    const q = buildSearchQuery(plan, level);
    if (!q) return '';
    const n = Math.max(1, Math.round(Number(page) || 1));
    return 'https://www.linkedin.com/search/results/people/?keywords=' + encodeURIComponent(q)
      + '&origin=GLOBAL_SEARCH_HEADER&page=' + n;
  }

  // https://www.linkedin.com/in/<slug> — no query string, fragment, trailing slash or sub-page; '' if not a profile.
  function normalizeProfileUrl(href) {
    let u;
    try { u = new URL(href, 'https://www.linkedin.com'); } catch (e) { return ''; }
    const host = u.hostname.toLowerCase();
    if (!(host === 'linkedin.com' || host.endsWith('.linkedin.com'))) return '';
    const m = u.pathname.match(/^\/in\/([^/]+)/i);
    if (!m || !m[1]) return '';
    return `https://www.linkedin.com/in/${m[1]}`;
  }

  // The contact-info dialog of a profile (opens as an overlay on the profile page).
  function contactInfoUrl(profileUrl) {
    const base = normalizeProfileUrl(profileUrl);
    return base ? `${base}/overlay/contact-info/` : '';
  }

  // ── Reading a result card ─────────────────────────────────────────────────────

  const DEGREE_RE = /^[•·\s]*(1st|2nd|3rd\+?)(?:\s*degree connection)?$/i;
  const NOISE = [
    /^(connect|message|follow|following|pending|save|send|invite|view|more|\.\.\.|…)$/i,
    /^view .+(?:'|’)s? profile$/i,
    /^status is (online|offline|reachable|away)/i,
    /mutual connections?\b/i,
    /^\d[\d,.]*\s*(followers?|connections?)$/i,
    /^(premium|open to work|hiring|verified)$/i,
    /^[•·]$/,
  ];

  function splitRoleCompany(text) {
    const m = String(text || '').match(/^(.*?)\s+(?:at|@)\s+(.+)$/i);
    return m ? { title: m[1].trim(), company: m[2].trim() } : { title: String(text || '').trim(), company: '' };
  }

  function looksLikeLocation(line) {
    return line.length <= 60 && /^[\p{L} .'-]+(,\s*[\p{L} .'-]+){0,3}$/u.test(line) && !/\sat\s/i.test(line);
  }

  function splitSkills(text) {
    return String(text || '').split(/,|•|·/).map((s) => s.trim())
      .filter((s) => s && !/^(and\s+)?\+?\d+\s+more$/i.test(s)).slice(0, 30);
  }

  // The visible text lines of one search-result card -> a profile's fields. A LinkedIn card shows the name, a
  // connection degree, a headline, a location and sometimes "Current: …", "Skills: …" or a summary snippet.
  function parseResultLines(lines) {
    let degree = '';
    const cleaned = [];
    for (const raw of lines || []) {
      let line = String(raw || '').replace(/\s+/g, ' ').trim();
      if (!line) continue;
      const inline = line.match(/\s*[•·]\s*(1st|2nd|3rd\+?)\s*$/i);
      if (inline) { degree = inline[1].toLowerCase(); line = line.slice(0, inline.index).trim(); }
      const d = line.match(DEGREE_RE);
      if (d) { degree = d[1].toLowerCase(); continue; }
      if (!line || NOISE.some((re) => re.test(line))) continue;
      if (cleaned.length && cleaned[cleaned.length - 1] === line) continue;  // LinkedIn repeats the name for screen readers
      cleaned.push(line);
    }
    const name = cleaned[0] || '';
    if (!name || /^linkedin member$/i.test(name)) return null;

    let headline = '';
    let location = '';
    let current = '';
    let skills = [];
    const extra = [];
    for (const line of cleaned.slice(1)) {
      let m = line.match(/^(current|past)\s*:\s*(.+)$/i);
      if (m) { if (m[1].toLowerCase() === 'current') current = m[2]; else extra.push(`Past: ${m[2]}`); continue; }
      m = line.match(/^skills?\s*:\s*(.+)$/i);
      if (m) { skills = splitSkills(m[1]); continue; }
      m = line.match(/^(summary|about)\s*:\s*(.+)$/i);
      if (m) { extra.push(m[2]); continue; }
      if (!headline) headline = line;
      else if (!location && looksLikeLocation(line)) location = line;
      else extra.push(line);
    }
    const role = splitRoleCompany(current || headline);
    return {
      name, degree, headline, location, title: role.title, company: role.company, skills,
      snippet: extra.join(' · ').slice(0, 600),
    };
  }

  // ── Reading the contact-info dialog ───────────────────────────────────────────

  const EMAIL_RE = /[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/i;
  const EMAIL_BLOCKLIST = /@(linkedin|licdn)\.|^(support|info|careers|career|noreply|no-reply|donotreply|help|contact|sales|admin|webmaster)@/i;

  function validEmail(raw) {
    const e = String(raw || '').trim().toLowerCase();
    const m = e.match(EMAIL_RE);
    if (!m) return '';
    return EMAIL_BLOCKLIST.test(m[0]) ? '' : m[0];
  }

  // An Indian mobile (10 digits starting 6-9, optional +91 / 0), or an international number written with a "+".
  // Anything else is not a phone number: an empty field is better than a wrong one.
  function validPhone(raw) {
    const text = String(raw || '').replace(/\(.*?\)/g, ' ').trim();   // "(Mobile)", "(Work)"
    const digits = text.replace(/\D/g, '');
    const indian = digits.match(/^(?:91|0)?([6-9]\d{9})$/);
    if (indian) return indian[1];
    if (text.startsWith('+') && digits.length >= 10 && digits.length <= 15) return `+${digits}`;
    return '';
  }

  const HEADING_RE = /^(.+(?:'|’)s profile|phone|email|websites?|address|birthday|connected since|ims?|twitter|wechat)$/i;

  function sectionAfter(lines, label) {
    const i = lines.findIndex((l) => l.toLowerCase() === label);
    if (i < 0) return [];
    const out = [];
    for (const line of lines.slice(i + 1)) {
      if (HEADING_RE.test(line)) break;
      out.push(line);
    }
    return out;
  }

  // lines: the dialog's visible text lines; mailtos: the dialog's mailto: link targets.
  function parseContactOverlay(lines, mailtos) {
    const clean = (lines || []).map((l) => String(l || '').replace(/\s+/g, ' ').trim()).filter(Boolean);
    let email = '';
    for (const l of sectionAfter(clean, 'email')) { email = validEmail(l); if (email) break; }
    if (!email) for (const h of mailtos || []) { email = validEmail(String(h).replace(/^mailto:/i, '')); if (email) break; }
    let phone = '';
    for (const l of sectionAfter(clean, 'phone')) { phone = validPhone(l); if (phone) break; }
    return { email, phone };
  }

  // ── Popup text and tabs ───────────────────────────────────────────────────────

  const ERROR_TEXT = {
    not_logged_in: 'Log in to LinkedIn to continue sourcing.',
    captcha: 'Stopped: LinkedIn is asking for a security check — complete it in the LinkedIn tab',
    restricted: 'Stopped: LinkedIn limited this account (search limit or restriction). Try again later.',
    no_results: 'Stopped: LinkedIn found no people for this JD, even after broadening the search',
    search_failed: 'Stopped: LinkedIn did not show search results — check the LinkedIn tab',
    skillmate_auth: 'Stopped: SkillMate session expired — refresh SkillMate',
    cancelled: 'Stopped by you',
  };

  // One line describing a run's progress, for the popup.
  function stageLabel(stage, page, pageTo, reason) {
    switch (stage) {
      case 'searching': return 'Searching LinkedIn for this JD…';
      case 'scraping': return page ? `Reading LinkedIn page ${page}…` : 'Reading LinkedIn results…';
      case 'screening': return page ? `SkillMate is screening page ${page}…` : 'SkillMate is screening…';
      case 'done': return 'Done — matches are in SkillMate';
      case 'error': return ERROR_TEXT[reason] || `Stopped: ${reason || 'unknown error'}`;
      default: return 'Idle';
    }
  }

  // The recruiter's most recently used LinkedIn tab (not a login or checkpoint page), or null.
  function pickLinkedinTab(tabs) {
    const usable = (tabs || []).filter((t) => {
      const path = linkedinPath(t.url);
      return path !== null && !isLinkedinLoginUrl(t.url) && !isLinkedinCheckpointUrl(t.url);
    });
    usable.sort((a, b) => (b.lastAccessed || 0) - (a.lastAccessed || 0));
    return usable[0] || null;
  }

  // Pages can carry hidden password inputs; only a visible one means a login form.
  function hasVisibleLoginForm(passwordInputs) {
    return Array.from(passwordInputs || []).some(
      (el) => el.offsetParent !== null && el.getClientRects().length > 0,
    );
  }

  const api = {
    PAGE_SOURCE, EXT_SOURCE, REQUEST_TYPES,
    isAllowedOrigin, isPageRequest, isAllowedApiBase, apiUrl,
    isLinkedinLoginUrl, isLinkedinCheckpointUrl, classifyBlock, isNoResultsText,
    searchKeywords, splitTopLevel, isSoftGroup, searchLevels, buildSearchQuery, buildSearchUrl, normalizeProfileUrl, contactInfoUrl,
    parseResultLines, splitRoleCompany, validEmail, validPhone, parseContactOverlay,
    stageLabel, pickLinkedinTab, hasVisibleLoginForm,
  };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  root.SkillmateLinkedinCore = api;
})(typeof self !== 'undefined' ? self : this);
