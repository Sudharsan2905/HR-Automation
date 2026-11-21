// background.js — SkillMate LinkedIn Sourcing extension service worker.
//
// SkillMate's "Source candidates" button reaches us through bridge.js as {type:'LI_SKILLMATE', payload}.
// A run:
//   1. check the LinkedIn login (the recruiter's open LinkedIn tab, else a background tab on the feed)
//   2. open ONE background tab and walk the people-search results page by page, by URL
//   3. POST each page to SkillMate, wait while SkillMate screens it, then read the next page only if
//      SkillMate asks for more — with a random pause between pages
//   4. report progress to the SkillMate tab.
// Selecting a candidate in SkillMate triggers a contact read: open that one profile's contact-info
// dialog, read the phone/email the person shared (only people the recruiter is connected to share them),
// POST it to SkillMate.
//
// This extension is independent of the Naukri one ("SkillMate Sourcing"). They share nothing at runtime:
// different message names, different storage, different pages.
//
// The current run lives in chrome.storage.session: Chrome stops this worker when idle. While a run is
// active every wait below touches chrome.storage at least once a second, which keeps the worker alive.

importScripts('config.js', 'core.js');

const Core = self.SkillmateLinkedinCore;
const cfg = self.SMLinkedinConfig;

// After install, update or a reload in chrome://extensions, the scripts already running in open SkillMate /
// LinkedIn tabs are cut off from the extension. Put fresh copies in so those tabs work without a reload.
chrome.runtime.onInstalled.addListener(async () => {
  const base = cfg.SKILLMATE_URL.replace(/\/$/, '');
  const targets = [
    { urls: [`${base}/*`], files: ['config.js', 'core.js', 'bridge.js'] },
    { urls: ['https://www.linkedin.com/*'], files: ['core.js', 'linkedin.js'] },
  ];
  for (const { urls, files } of targets) {
    for (const tab of await chrome.tabs.query({ url: urls })) {
      try { await chrome.scripting.executeScript({ target: { tabId: tab.id }, files }); }
      catch (e) { console.warn('[SkillMate · LinkedIn] could not refresh tab', tab.url, e.message); }
    }
  }
});

const LOG = '[SkillMate · LinkedIn]';
const JOB_KEY = 'skillmateLiJob';
const LAST_KEY = 'skillmateLiLastRun';       // last finished run, shown in the popup
const FAIL_REASONS = ['not_logged_in', 'captcha', 'restricted', 'cancelled'];
const POLL_MS = 3000;
const BUSY_WINDOW_MS = 10 * 60 * 1000;       // a run with no sign of life for this long is treated as dead
const SCREEN_WAIT_MS = 10 * 60 * 1000;       // one page's screening should take ~1 minute

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const randomMs = ([lo, hi]) => Math.round((lo + Math.random() * (hi - lo)) * 1000);

// ── Run state ────────────────────────────────────────────────────────────────────

async function getJob() {
  try { return (await chrome.storage.session.get(JOB_KEY))[JOB_KEY] || null; } catch (e) { return null; }
}
async function setJob(job) { await chrome.storage.session.set({ [JOB_KEY]: job }); }
async function clearJob(outcome) {
  const job = await getJob();
  await chrome.storage.session.remove(JOB_KEY);
  if (job && outcome) {
    await chrome.storage.session.set({ [LAST_KEY]: { runId: job.runId, ...outcome, at: Date.now() } });
  }
}
async function isCurrent(job) { return (await getJob())?.runId === job.runId; }

// Stamp the run as alive. A run that was killed with the browser or the worker leaves its job behind; without a
// recent stamp it must not keep refusing contact reads.
async function touchJob(job) {
  const cur = await getJob();
  if (cur && cur.runId === job.runId) await setJob({ ...cur, updatedAt: Date.now() });
}
async function runIsActive() {
  const job = await getJob();
  return !!job && Date.now() - (job.updatedAt || job.startedAt || 0) < BUSY_WINDOW_MS;
}

// Sleep in one-second steps, stopping early (false) when the run was cancelled or replaced.
async function sleepAlive(job, ms) {
  const end = Date.now() + ms;
  while (Date.now() < end) {
    await sleep(Math.min(1000, Math.max(0, end - Date.now())));
    if (!(await isCurrent(job))) return false;
  }
  return true;
}

// Tell the SkillMate tab (and remember it for the popup).
async function emit(job, stage, extra = {}) {
  if (!job) return;
  const cur = await getJob();
  if (cur && cur.runId === job.runId) await setJob({ ...cur, stage, ...extra, updatedAt: Date.now() });
  if (!job.pageTabId) return;
  try {
    await chrome.tabs.sendMessage(job.pageTabId, {
      type: 'LI_SKILLMATE_EVENT',
      event: { type: 'LINKEDIN_PROGRESS', runId: job.runId, stage, ...extra },
    });
  } catch (e) { /* SkillMate tab closed — the backend run still finishes */ }
}

// ── SkillMate API ────────────────────────────────────────────────────────────────

async function api(job, path, body) {
  const res = await fetch(Core.apiUrl(job.apiBase, path), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${job.token}` },
    body: JSON.stringify(body),
  });
  if (res.status === 401) throw new Error('skillmate_auth');
  if (!res.ok) {
    let msg = `HTTP ${res.status}`;
    try { msg = (await res.json())?.message || msg; } catch (e) { /* not JSON */ }
    throw new Error(msg);
  }
  return res.json().catch(() => ({}));
}

async function apiGet(job, path) {
  const res = await fetch(Core.apiUrl(job.apiBase, path), {
    headers: { Authorization: `Bearer ${job.token}` },
  });
  if (res.status === 401) throw new Error('skillmate_auth');
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const body = await res.json();
  return body && 'data' in body ? body.data : body;  // SkillMate wraps responses as {success, data}
}

// ── Tabs ─────────────────────────────────────────────────────────────────────────

async function closeTab(tabId) {
  if (!tabId) return;
  try { await chrome.tabs.remove(tabId); } catch (e) { /* already gone */ }
}

// Load `url` in the tab and resolve once the new page has finished loading.
function navigate(tabId, url, timeoutMs = 35000) {
  return new Promise((resolve, reject) => {
    let sawLoading = false;
    const timer = setTimeout(() => { cleanup(); reject(new Error('page timed out')); }, timeoutMs);
    function cleanup() {
      clearTimeout(timer);
      chrome.tabs.onUpdated.removeListener(onUpdated);
    }
    function onUpdated(id, info) {
      if (id !== tabId) return;
      if (info.status === 'loading') sawLoading = true;
      if (info.status === 'complete' && sawLoading) { cleanup(); setTimeout(resolve, 900); }  // let it render
    }
    chrome.tabs.onUpdated.addListener(onUpdated);
    chrome.tabs.update(tabId, { url }).catch((e) => { cleanup(); reject(e); });
  });
}

// The content script may still be loading right after a navigation: retry a few times.
async function sendToTab(tabId, message, attempts = 8, gapMs = 1000) {
  let last = null;
  for (let i = 0; i < attempts; i++) {
    try { return await chrome.tabs.sendMessage(tabId, message); }
    catch (e) { last = e; await sleep(gapMs); }
  }
  throw last || new Error('no response from the LinkedIn tab');
}

async function probeTab(tabId) {
  try { return await sendToTab(tabId, { type: 'LI_PROBE' }, 3, 700); } catch (e) { return null; }
}

// Logged in? First look at the recruiter's own open LinkedIn tab (it already proves the session); only if none
// is open, load the feed in a background tab. Opens no profile.
async function checkLinkedinLogin() {
  const open = Core.pickLinkedinTab(await chrome.tabs.query({ url: ['https://www.linkedin.com/*'] }));
  if (open) {
    const probe = await probeTab(open.id);
    console.info(LOG, 'Login check on open tab', open.url, '→', probe);
    if (probe && probe.loginForm !== true && probe.block !== 'not_logged_in') return true;
  }

  let tab = null;
  try {
    tab = await chrome.tabs.create({ url: 'about:blank', active: false });
    await navigate(tab.id, cfg.LINKEDIN_HOME_URL, 30000);
    const landed = await chrome.tabs.get(tab.id).catch(() => null);
    console.info(LOG, 'Login check in background tab landed on', landed?.url);
    if (!landed?.url || Core.isLinkedinLoginUrl(landed.url)) return false;
    const probe = await probeTab(tab.id);
    return !(probe && probe.loginForm === true);
  } catch (e) {
    console.warn(LOG, 'LinkedIn login check failed:', e.message);
    return false;
  } finally {
    await closeTab(tab?.id);
  }
}

// ── Runs ─────────────────────────────────────────────────────────────────────────

// Fail the run on SkillMate and tell the page. Never throws. A CAPTCHA / security check keeps its tab and brings
// it forward, because only the recruiter can complete it; every other failure closes the working tab.
async function failRun(job, reason, detail = '', debug = '') {
  console.warn(LOG, `run ${job.runId} failed: ${reason}`, detail, debug);
  try {
    await api(job, `/sourcing/runs/${job.runId}/fail`, {
      reason: FAIL_REASONS.includes(reason) ? reason : 'error',
      detail: FAIL_REASONS.includes(reason) ? detail : `${reason}${detail ? ': ' + detail : ''}`,
      debug: String(debug || '').slice(0, 900),   // what LinkedIn showed: kept on the run so the failure can be explained
    });
  } catch (e) { /* the SkillMate page also fails the run when it sees the error event */ }
  await emit(job, 'error', { reason });
  const tabId = (await getJob())?.tabId || job.tabId;
  if (reason === 'captcha' && tabId) {
    try { await chrome.tabs.update(tabId, { active: true }); } catch (e) { /* gone */ }
  } else {
    await closeTab(tabId);
  }
  await clearJob({ stage: 'error', reason });
}

async function finishRun(job, run) {
  await closeTab((await getJob())?.tabId || job.tabId);
  if (run.status === 'done') {
    await emit(job, 'done', { shortlisted: run.profiles_shortlisted });
    const cur = (await getJob()) || job;
    await clearJob({ stage: 'done', profiles: cur.profilesSent || 0, shortlisted: run.profiles_shortlisted });
  } else {
    const reason = run.status === 'cancelled' ? 'cancelled' : 'error';
    await emit(job, 'error', { reason });
    await clearJob({ stage: 'error', reason });
  }
}

// One person to SkillMate as soon as their email is read (see collectEmails). True when SkillMate took them; on any failure
// (an older SkillMate without this endpoint, a network blip) false, and the person is sent with the page instead.
async function streamCandidate(job, card) {
  try { await api(job, `/sourcing/runs/${job.runId}/profile`, { profiles: [card] }); }
  catch (e) { return false; }
  const cur = await getJob();
  if (cur && cur.runId === job.runId) await setJob({ ...cur, profilesSent: (cur.profilesSent || 0) + 1 });
  return true;
}

// One results page to SkillMate; wait while it is screened. Returns 'next' | 'finished' | 'stopped' | 'failed'.
async function postPage(job, page, profiles, ended, sourceUrl, scanned, debug) {
  await emit(job, 'screening', { page, pageTo: job.pageTo });
  try {
    await api(job, `/sourcing/runs/${job.runId}/profiles`, {
      profiles, ended: !!ended, source_url: sourceUrl || '', search_level: (await getJob())?.level ?? job.level ?? 0,
      scanned,   // people the page showed; `profiles` holds only those with an email
      debug: String(debug || '').slice(0, 900),   // what was read on this page, kept on the run for support
    });
    const cur = (await getJob()) || job;
    await setJob({ ...cur, pagesSent: (cur.pagesSent || 0) + 1, profilesSent: (cur.profilesSent || 0) + profiles.length });

    const deadline = Date.now() + SCREEN_WAIT_MS;
    while (Date.now() < deadline) {
      if (!(await sleepAlive(job, POLL_MS))) return 'stopped';        // cancelled meanwhile
      await touchJob(job);
      const run = await apiGet(job, `/sourcing/runs/${job.runId}`);
      if (run.status === 'scraping' && run.next_action === 'next_page') {
        await emit(job, 'scraping', { page: page + 1, pageTo: job.pageTo, shortlisted: run.profiles_shortlisted, phase: run.phase });
        return 'next';
      }
      if (['done', 'failed', 'cancelled'].includes(run.status)) {
        await finishRun(job, run);
        return 'finished';
      }
    }
    await failRun(job, 'error', 'SkillMate took too long to screen a page');
    return 'failed';
  } catch (e) {
    await failRun(job, e.message === 'skillmate_auth' ? 'skillmate_auth' : 'error', e.message);
    return 'failed';
  }
}

// One line per page read, for the failed-run record: which search step, how many cards, what the page said.
function describeAttempt(job, page, res) {
  const d = res?.diag || {};
  const text = d.text ? ` text="${d.text.slice(0, 120)}"` : '';
  return `L${job.level}@p${page} v${chrome.runtime.getManifest().version}: cards=${d.cards ?? '?'} profiles=${(res?.profiles || []).length}`
    + `${res?.noResults ? ' no-results-page' : ''}${d.timedOut ? ' timed-out' : ''} anchors=${d.anchors ?? '?'} title="${d.title || ''}"${text}`;
}

// Open one candidate's contact dialog in the tab and read the phone/email they share with the recruiter, and the profile's
// Experience section behind it. Returns {email, phone, experience, dialog, rows, diag}, or {block} when LinkedIn stops us.
// `dialog && rows` means the dialog was really read: its contact rows were up. An empty `email` then means "not shared".
async function readContactIn(tabId, profileUrl) {
  const none = { email: '', phone: '', experience: null, dialog: false, rows: false, diag: null };
  // The profile itself, not the dialog's own address: LinkedIn only shows the dialog when "Contact info" is clicked there.
  const url = Core.normalizeProfileUrl(profileUrl);
  if (!url) return none;
  try {
    await navigate(tabId, url);
    const landed = await chrome.tabs.get(tabId).catch(() => null);
    if (landed?.url && Core.isLinkedinLoginUrl(landed.url)) return { block: 'not_logged_in' };
    const res = (await sendToTab(tabId, { type: 'LI_EXTRACT_CONTACT', open: true }, 6, 1000)) || {};
    if (res.block) return { block: res.block };
    return {
      email: res.email || '', phone: res.phone || '', experience: res.experience || null,
      dialog: !!res.dialog, rows: !!res.rows, diag: res.diag || null,
    };
  } catch (e) {
    console.warn(LOG, 'contact read failed for', profileUrl, e.message);
    return { ...none, diag: { error: String(e.message).slice(0, 80) } };
  }
}

// A candidate is taken only with an email. For every card on this page that could have one (1st-degree connections), open
// the contact dialog and keep the people it gives an email for; 2nd/3rd-degree people are never opened. The JD's experience
// range is applied to what each profile shows.
//
// Counts are kept honestly: `readable` is how many dialogs were really read (rows loaded), so "nobody shared an email" is
// never confused with "the dialogs could not be read". If LinkedIn does not render in a background tab (three unreadable
// dialogs in a row) the tab is brought to the front once and that person is read again; if dialogs still cannot be read
// the page is reported as `unreadable`.
async function collectEmails(job, page, cards) {
  const plan = job.plan || {};
  const todo = cards.filter((c) => Core.canShareEmail(c));
  const degrees = { '1st': 0, '2nd': 0, '3rd': 0, '?': 0 };
  cards.forEach((c) => { const d = String(c.connection_degree || '').slice(0, 3).toLowerCase(); degrees[degrees[d] !== undefined ? d : '?']++; });
  const stats = { degrees, opened: 0, readable: 0, outOfRange: 0, foregrounded: false, samples: [] };
  const kept = [];
  const streamed = new Set();   // source_links already sent to SkillMate one by one
  let sentUpTo = 0;
  // Send each person to SkillMate the moment their email is read, so they show in the table (and are screened) while the rest
  // of the page is still being read. Anyone whose send fails is simply sent with the page, as before.
  const flushKept = async () => {
    while (sentUpTo < kept.length) {
      const card = kept[sentUpTo++];
      if (await streamCandidate(job, card)) streamed.add(card.source_link);
    }
  };
  if (!todo.length) return { kept, asked: 0, stats };
  let tab;
  try { tab = await chrome.tabs.create({ url: 'about:blank', active: !!cfg.WORK_TAB_ACTIVE }); }
  catch (e) { return { kept, asked: 0, stats }; }

  // What one dialog tells us: whether it was really read, and the person it gives (if they share an email and fit the range).
  const consume = (card, found) => {
    const readable = !!(found.dialog && found.rows);
    if (readable) stats.readable++;
    else if (stats.samples.length < 2 && found.diag) stats.samples.push(found.diag);
    if (found.email) {
      const exp = found.experience;
      // The JD's experience range, judged on what the profile's Experience section adds up to.
      if (cfg.FILTER_BY_EXPERIENCE && !Core.experienceFits(plan.experience_min, plan.experience_max, exp)) { stats.outOfRange++; }
      else {
        kept.push({
          ...card, email: found.email, phone: found.phone || '',
          ...(exp ? {
            experience_years: exp.years, total_experience: exp.text, experience_is_lower_bound: exp.lowerBound,
            experiences: exp.positions.length ? exp.positions : card.experiences,
          } : {}),
        });
      }
    }
    return readable;
  };

  let blocked = null;
  let streak = 0;
  let unread = [];   // people whose dialog could not be read yet
  try {
    for (let i = 0; i < todo.length; i++) {
      if (!(await isCurrent(job))) return { stopped: true };
      await emit(job, 'contacts', { page, pageTo: job.pageTo, done: i, total: todo.length });
      const found = await readContactIn(tab.id, todo[i].source_link);
      if (found.block) { blocked = found.block; return { blocked }; }
      stats.opened++;
      if (consume(todo[i], found)) streak = 0;
      else { unread.push(i); streak++; }
      await flushKept();

      if (streak >= 3) {
        if (stats.foregrounded || cfg.WORK_TAB_ACTIVE) {
          if (!stats.readable) return { kept, asked: todo.length, stats, unreadable: true, sent: streamed };   // nothing readable even in front
          streak = 0;
        } else {
          // Three unreadable dialogs in a row: LinkedIn may not render in a background tab. Bring the tab to the front once
          // and read everyone we could not read so far again, so nobody is lost to the first attempts.
          stats.foregrounded = true;
          try { await chrome.tabs.update(tab.id, { active: true }); } catch (e) { /* gone */ }
          const again = unread;
          unread = [];
          streak = 0;
          for (const j of again) {
            if (!(await sleepAlive(job, randomMs(cfg.PROFILE_PAUSE_SECONDS)))) return { stopped: true };
            const retry = await readContactIn(tab.id, todo[j].source_link);
            if (retry.block) { blocked = retry.block; return { blocked }; }
            if (!consume(todo[j], retry)) { unread.push(j); streak++; }
            await flushKept();
          }
          if (streak >= 3 && !stats.readable) return { kept, asked: todo.length, stats, unreadable: true, sent: streamed };
        }
      }
      if (i < todo.length - 1 && !(await sleepAlive(job, randomMs(cfg.PROFILE_PAUSE_SECONDS)))) return { stopped: true };
    }
  } finally {
    if (blocked === 'captcha') { try { await chrome.tabs.update(tab.id, { active: true }); } catch (e) { /* gone */ } }
    else await closeTab(tab.id);   // a CAPTCHA tab stays open and in front: only the recruiter can complete it
  }
  const unreadable = todo.length >= 3 && stats.readable === 0;
  return { kept, asked: todo.length, stats, unreadable, sent: streamed };
}

// One line for the run record: what the page had and what became of it. Samples of an unread dialog are redacted.
function describeContacts(page, cardCount, got) {
  const st = got.stats || {};
  const d = st.degrees || {};
  const samples = (st.samples || []).map((x) => (x.sample ? ` sample="${x.sample}"` : '')
    + ` link=${x.link} clicks=${x.clicks} found=${x.found} rows=${x.rows} via=${x.via || '-'} ${x.visible || ''}${x.error ? ' error=' + x.error : ''}`).join('');
  return `contacts p${page}: cards=${cardCount} degrees=1st:${d['1st'] || 0}/2nd:${d['2nd'] || 0}/3rd:${d['3rd'] || 0}/?:${d['?'] || 0} `
    + `asked=${got.asked} opened=${st.opened || 0} readable=${st.readable || 0} emails=${(got.kept || []).length} streamed=${got.sent ? got.sent.size : 0} `
    + `out-of-range=${st.outOfRange || 0}${st.foregrounded ? ' foregrounded' : ''}${samples}`;
}

// Set the search step for this run and remember it (so a restarted worker and later pages keep using it).
async function setLevel(job, level) {
  job.level = level;
  const cur = await getJob();
  if (cur && cur.runId === job.runId) await setJob({ ...cur, level, updatedAt: Date.now() });
}

// Walk pages pageFrom..pageTo in the one working tab.
async function crawl(job) {
  const tabId = job.tabId;
  const lastLevel = Core.searchLevels(job.plan).length - 1;
  const trail = [];
  const searchOpts = { firstDegreeOnly: !!cfg.EMAIL_ONLY };
  let page = job.pageFrom;
  while (page <= job.pageTo) {
    if (!(await isCurrent(job))) return;

    try { await navigate(tabId, Core.buildSearchUrl(job.plan, page, job.level, searchOpts)); }
    catch (e) { return failRun(job, 'search_failed', e.message); }
    if (!(await isCurrent(job))) return;
    await emit(job, 'scraping', { page, pageTo: job.pageTo });

    let res;
    try { res = await sendToTab(tabId, { type: 'LI_READ_PAGE' }, 10, 1000); }
    catch (e) { return failRun(job, 'search_failed', `The LinkedIn tab did not respond: ${e.message}`); }
    if (!(await isCurrent(job))) return;

    const landed = await chrome.tabs.get(tabId).catch(() => null);
    if (landed?.url && Core.isLinkedinLoginUrl(landed.url)) return failRun(job, 'not_logged_in');
    if (res?.block) return failRun(job, res.block, `page ${page}`);
    if (!res || res.ok === false) return failRun(job, 'error', res?.error || 'could not read the page');

    const profiles = res.profiles || [];
    trail.push(describeAttempt(job, page, res));
    if (!profiles.length && page === 1 && job.pageFrom === 1) {
      if (res.diag?.timedOut) return failRun(job, 'search_failed', '', trail.join(' ; '));
      // LinkedIn found nobody for this search: it was too narrow. Try the next, broader one before giving up.
      if (job.level < lastLevel) {
        console.warn(LOG, `no people at search step ${job.level}: ${Core.buildSearchQuery(job.plan, job.level)}`);
        await setLevel(job, job.level + 1);
        if (!(await sleepAlive(job, randomMs(cfg.PAGE_PAUSE_SECONDS)))) return;
        continue;                                   // same page 1, broader search
      }
      console.warn(LOG, `no people at any search step; last: ${Core.buildSearchQuery(job.plan, job.level)}`);
      return failRun(job, 'no_results', '', trail.join(' ; '));
    }
    // An empty later page just means the results ran out: tell SkillMate, which then stops searching. A page of
    // only hidden "LinkedIn Member" cards ends the useful results too (LinkedIn lists nearest connections first).
    const ended = !!res.ended || !profiles.length;

    // Take only the people who have an email: ask each one's contact dialog before anything reaches SkillMate.
    let outgoing = profiles;
    let record = '';
    if (cfg.EMAIL_ONLY) {
      const got = await collectEmails(job, page, profiles);
      if (got.stopped || !(await isCurrent(job))) return;
      if (got.blocked) return failRun(job, got.blocked, `page ${page}, reading contact details`, trail.join(' ; '));
      record = describeContacts(page, profiles.length, got);
      trail.push(record);
      // Dialogs that could not be read are not "nobody shared an email": say so, instead of reporting an empty result.
      if (got.unreadable) return failRun(job, 'contacts_unreadable', '', trail.join(' ; '));
      outgoing = got.kept.filter((c) => !(got.sent && got.sent.has(c.source_link)));   // the rest went one by one already
    }
    const outcome = await postPage(job, page, outgoing, ended, res.diag?.url || landed?.url, profiles.length, record);
    if (outcome !== 'next') return;

    page += 1;
    if (!(await sleepAlive(job, randomMs(cfg.PAGE_PAUSE_SECONDS)))) return;   // be gentle: LinkedIn limits fast readers
  }
  // The window is used up. SkillMate normally says "done" before this; make sure the run is closed.
  const run = await apiGet(job, `/sourcing/runs/${job.runId}`).catch(() => null);
  if (run) await finishRun(job, run);
}

async function startRun(p, pageTabId) {
  const job = {
    runId: p.runId, apiBase: p.apiBase, token: p.token, pageTabId, tabId: null, plan: p.plan,
    pageFrom: p.pageFrom, pageTo: p.pageTo, stage: 'searching', startedAt: Date.now(),
    level: Math.max(0, Number(p.searchLevel) || 0),   // which step of the search ladder earlier runs settled on
  };
  await setJob(job);
  await emit(job, 'searching');

  if (!Core.searchLevels(job.plan).length) return failRun(job, 'search_failed', 'the search plan has no keywords');

  const loggedIn = await checkLinkedinLogin();
  if (!(await isCurrent(job))) return;  // cancelled during the check
  if (!loggedIn) return failRun(job, 'not_logged_in');

  let tab;
  try { tab = await chrome.tabs.create({ url: 'about:blank', active: !!cfg.WORK_TAB_ACTIVE }); }
  catch (e) { return failRun(job, 'error', e.message); }
  job.tabId = tab.id;  // so Cancel closes this tab too
  await setJob({ ...(await getJob()), tabId: tab.id });
  if (!(await isCurrent(job))) { await closeTab(tab.id); return; }

  await crawl(job);
}

async function cancelRun(runId) {
  const job = await getJob();
  if (!job || (runId && job.runId !== runId)) return false;
  await failRun(job, 'cancelled');
  return true;
}

// ── Contact read (one selected candidate) ────────────────────────────────────────

async function revealContact(p) {
  const out = (ok, reason, candidateError = null) =>
    ({ type: 'LINKEDIN_REVEAL_RESULT', profileId: p.profileId, ok, reason, candidateError });
  const url = Core.normalizeProfileUrl(p.sourceLink);   // the profile: the dialog opens when "Contact info" is clicked there
  if (!url) return out(false, 'bad_link');
  if (await runIsActive()) return out(false, 'busy');   // never read profiles while a search run uses the same session
  if (!(await checkLinkedinLogin())) return out(false, 'not_logged_in');

  let tab = null;
  let found = {};
  let blocked = null;
  try {
    tab = await chrome.tabs.create({ url: 'about:blank', active: !!cfg.WORK_TAB_ACTIVE });
    await navigate(tab.id, url);
    const landed = await chrome.tabs.get(tab.id).catch(() => null);
    if (landed?.url && Core.isLinkedinLoginUrl(landed.url)) return out(false, 'not_logged_in');
    const res = (await sendToTab(tab.id, { type: 'LI_EXTRACT_CONTACT', open: true })) || {};
    if (res.block) blocked = res.block; else found = res;
    console.log(LOG, `contact · ${p.name}: phone=${found.phone || '(none)'} email=${found.email || '(none)'} dialog=${found.dialog}`);
  } catch (e) {
    return out(false, e.message);
  } finally {
    await closeTab(tab?.id);
    await sleep(randomMs(cfg.PROFILE_PAUSE_SECONDS));
  }
  if (blocked) return out(false, blocked);

  const body = {};
  if (found.email) body.email = found.email;
  if (found.phone) body.phone = found.phone;
  let candidateError = null;
  if (Object.keys(body).length) {
    try {
      const res = await api({ apiBase: p.apiBase, token: p.token }, `/sourcing/profiles/${p.profileId}/contact`, body);
      candidateError = res?.data?.candidate_error || null;
    } catch (e) { return out(false, e.message); }
  }
  // LinkedIn only shares an email with connections: no email is an ordinary outcome, not an error.
  return out(!!found.email, found.email ? undefined : 'no_email', candidateError);
}

// ── Requests from SkillMate (via bridge.js) ──────────────────────────────────────

async function handleSkillmate(p, sender) {
  const needsApi = p.type === 'LINKEDIN_SOURCE' || p.type === 'LINKEDIN_REVEAL';
  if (needsApi && (!p.token || !Core.isAllowedApiBase(p.apiBase, cfg.SKILLMATE_API_ORIGINS))) {
    return { type: 'LINKEDIN_ERROR', ok: false, reason: 'api_not_allowed' };
  }
  switch (p.type) {
    case 'LINKEDIN_CHECK_LOGIN':
      return { type: 'LINKEDIN_LOGIN_STATE', loggedIn: await checkLinkedinLogin() };
    case 'LINKEDIN_SOURCE': {
      const running = await getJob();
      if (running && running.runId !== p.runId) {
        // A leftover from a run SkillMate already expired: close its tab, then start fresh.
        await closeTab(running.tabId);
        await clearJob({ stage: 'error', reason: 'replaced' });
      }
      startRun(p, sender.tab?.id).catch((e) => console.error(LOG, e));
      return { type: 'LINKEDIN_SOURCE_ACK', ok: true };
    }
    case 'LINKEDIN_REVEAL':
      return revealContact(p);
    case 'LINKEDIN_CANCEL':
      await cancelRun(p.runId);
      return { type: 'LINKEDIN_CANCELLED', ok: true };
    default:
      return { type: 'LINKEDIN_ERROR', ok: false, reason: 'unknown_request' };
  }
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  switch (message?.type) {
    case 'LI_SKILLMATE':
      if (!message.payload) return false;
      handleSkillmate(message.payload, sender)
        .then((r) => sendResponse(r))
        .catch((err) => sendResponse({ type: 'LINKEDIN_ERROR', ok: false, reason: err.message }));
      return true;

    // From the popup
    case 'LI_POPUP_STATUS':
      Promise.all([getJob(), chrome.storage.session.get(LAST_KEY)])
        .then(([job, last]) => sendResponse({ job: job ? { ...job, token: undefined } : null, last: last[LAST_KEY] || null }));
      return true;
    case 'LI_POPUP_CHECK_LOGIN':
      checkLinkedinLogin().then((loggedIn) => sendResponse({ loggedIn }));
      return true;
    case 'LI_POPUP_STOP':
      getJob().then((job) => (job ? cancelRun(job.runId) : false)).then((ok) => sendResponse({ ok }));
      return true;

    default:
      return false;
  }
});
