// background.js — SkillMate Sourcing extension service worker.
//
// SkillMate's "Source from Naukri" button reaches us through bridge.js as
// {type:'MH_SKILLMATE', payload}. A run:
//   1. check the ResDex login (background tab on the ResDex home page; no credit spent)
//   2. find the ResDex results tab (automatic search is pending a sample URL — see
//      runResdexSearch)
//   3. tell naukri.js to crawl pages pageFrom..pageTo
//   4. POST the profiles to SkillMate, and report progress to the SkillMate tab.
// Selecting a candidate in SkillMate triggers a contact reveal: open that one profile,
// read phone/email (one ResDex credit), POST it to SkillMate.
//
// The current run lives in chrome.storage.session: Chrome stops this worker when idle,
// and a crawl takes a minute or more.

importScripts('config.js', 'core.js');

// After install, update or a reload in chrome://extensions, the scripts already running in open
// SkillMate / ResDex tabs are cut off from the extension. Put fresh copies in so those tabs
// work without being reloaded (the old copies notice and go quiet).
chrome.runtime.onInstalled.addListener(async () => {
  const base = SMConfig.SKILLMATE_URL.replace(/\/$/, '');
  const targets = [
    { urls: [`${base}/*`], files: ['config.js', 'core.js', 'bridge.js'] },
    { urls: ['https://resdex.naukri.com/*'], files: ['core.js', 'naukri.js'] },
  ];
  for (const { urls, files } of targets) {
    for (const tab of await chrome.tabs.query({ url: urls })) {
      try { await chrome.scripting.executeScript({ target: { tabId: tab.id }, files }); }
      catch (e) { console.warn('[SkillMate · background] could not refresh tab', tab.url, e.message); }
    }
  }
});

const LOG = '[SkillMate · background]';
const JOB_KEY = 'skillmateJob';
const LAST_KEY = 'skillmateLastRun';       // last finished run, shown in the popup
const REVEAL_PACE_MS = 1200;
const FAIL_REASONS = ['not_logged_in', 'captcha', 'cancelled'];

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

// Tell the SkillMate tab (and remember it for the popup).
async function emit(job, stage, extra = {}) {
  if (!job) return;
  const cur = await getJob();
  if (cur && cur.runId === job.runId) await setJob({ ...cur, stage, ...extra });
  if (!job.pageTabId) return;
  try {
    await chrome.tabs.sendMessage(job.pageTabId, {
      type: 'MH_SKILLMATE_EVENT',
      event: { type: 'SKILLMATE_PROGRESS', runId: job.runId, stage, ...extra },
    });
  } catch (e) { /* SkillMate tab closed — the backend run still finishes */ }
}

// ── SkillMate API ────────────────────────────────────────────────────────────────

async function api(job, path, body) {
  const res = await fetch(SkillmateCore.apiUrl(job.apiBase, path), {
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
  const res = await fetch(SkillmateCore.apiUrl(job.apiBase, path), {
    headers: { Authorization: `Bearer ${job.token}` },
  });
  if (res.status === 401) throw new Error('skillmate_auth');
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const body = await res.json();
  return body && 'data' in body ? body.data : body;  // SkillMate wraps responses as {success, data}
}

// Fail the run on SkillMate and tell the page. Never throws.
async function failRun(job, reason, detail = '') {
  console.warn(LOG, `run ${job.runId} failed: ${reason}`, detail);
  try {
    await api(job, `/sourcing/runs/${job.runId}/fail`, {
      reason: FAIL_REASONS.includes(reason) ? reason : 'error',
      detail: FAIL_REASONS.includes(reason) ? detail : `${reason}${detail ? ': ' + detail : ''}`,
    });
  } catch (e) { /* the SkillMate page also fails the run when it sees the error event */ }
  await emit(job, 'error', { reason });
  await clearJob({ stage: 'error', reason });
}

// ── Tabs ─────────────────────────────────────────────────────────────────────────

function waitForTabComplete(tabId, timeoutMs = 25000) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      chrome.tabs.onUpdated.removeListener(onUpdated);
      reject(new Error('page timed out'));
    }, timeoutMs);
    function onUpdated(id, info) {
      if (id !== tabId || info.status !== 'complete') return;
      clearTimeout(timer);
      chrome.tabs.onUpdated.removeListener(onUpdated);
      setTimeout(resolve, 900); // let the client-side render settle
    }
    chrome.tabs.onUpdated.addListener(onUpdated);
  });
}

// Ask a ResDex tab's content script whether it shows a visible login form.
// Returns true/false, or null when the content script isn't there (tab not reloaded yet).
async function probeLoginForm(tabId) {
  try {
    const probe = await chrome.tabs.sendMessage(tabId, { type: 'MH_SKILLMATE_LOGIN_PROBE' });
    return probe ? !!probe.loginForm : null;
  } catch (e) { return null; }
}

// Logged in? First look at the recruiter's own open ResDex tab (opening it already proves the
// session); only if none is open, load ResDex in a background tab. Opens no profile, no credit.
async function checkResdexLogin() {
  const open = SkillmateCore.pickResdexTab(await chrome.tabs.query({ url: ['https://resdex.naukri.com/*'] }));
  if (open) {
    const loginForm = await probeLoginForm(open.id);
    console.info(LOG, 'Login check on open ResDex tab', open.url, '→ login form:', loginForm);
    if (loginForm !== true) return true;
  }

  let tab = null;
  try {
    tab = await chrome.tabs.create({ url: SMConfig.RESDEX_HOME_URL, active: false });
    await waitForTabComplete(tab.id, 30000);
    const landed = await chrome.tabs.get(tab.id).catch(() => null);
    const loginForm = landed?.url ? await probeLoginForm(tab.id) : null;
    console.info(LOG, 'Login check in background tab landed on', landed?.url, '→ login form:', loginForm);
    if (!landed?.url || SkillmateCore.isResdexLoginUrl(landed.url)) return false;
    return loginForm !== true;
  } catch (e) {
    console.warn(LOG, 'ResDex login check failed:', e.message);
    return false;
  } finally {
    if (tab?.id) { try { await chrome.tabs.remove(tab.id); } catch (e) { /* gone */ } }
  }
}

// Wait until the tab leaves the URL it is on now (ResDex moving from the form to results).
async function waitForUrlChange(tabId, fromUrl, timeoutMs) {
  const end = Date.now() + timeoutMs;
  while (Date.now() < end) {
    const t = await chrome.tabs.get(tabId).catch(() => null);
    if (!t) return null;
    if (t.url && t.url !== fromUrl && !SkillmateCore.isResdexSearchFormUrl(t.url)) return t.url;
    await new Promise((r) => setTimeout(r, 500));
  }
  return null;
}

// Automatic search: open ResDex's search form in a background tab, type the JD's Boolean
// keywords and experience range, click "Search candidates", and return the tab once it
// shows results. Throws an Error whose message is a failure reason.
async function runResdexSearch(plan, job) {
  const keywords = SkillmateCore.searchKeywords(plan);
  if (!keywords) throw new Error('search_failed');

  const tab = await chrome.tabs.create({ url: SMConfig.RESDEX_SEARCH_URL, active: false });
  job.tabId = tab.id;  // so Cancel closes out this tab's crawl too
  await setJob({ ...(await getJob()), tabId: tab.id });
  await waitForTabComplete(tab.id, 30000);

  const formTab = await chrome.tabs.get(tab.id);
  if (SkillmateCore.isResdexLoginUrl(formTab.url)) throw new Error('not_logged_in');

  let filled = null;
  for (let i = 0; i < 5 && !filled; i++) {   // the content script may still be loading
    try { filled = await chrome.tabs.sendMessage(tab.id, { type: 'MH_SKILLMATE_FILL_SEARCH', keywords,
      expMin: plan.experience_min, expMax: plan.experience_max,
      locations: plan.locations || [], ctcMaxLacs: plan.ctc_max_lacs }); }
    catch (e) { await new Promise((r) => setTimeout(r, 1000)); }
  }
  console.info(LOG, 'Search form fill:', filled, 'keywords:', keywords);
  if (!filled?.ok) {
    console.warn(LOG, 'Could not fill the ResDex search form:', filled?.error);
    throw new Error('search_form_not_found');
  }

  const resultsUrl = await waitForUrlChange(tab.id, formTab.url, 25000);
  console.info(LOG, 'ResDex results URL:', resultsUrl);
  if (!resultsUrl) throw new Error('search_failed');
  if (SkillmateCore.isResdexLoginUrl(resultsUrl)) throw new Error('not_logged_in');
  await waitForTabComplete(tab.id, 20000).catch(() => {});  // SPA may not fire a load — fine
  return tab.id;
}

// ── Runs ─────────────────────────────────────────────────────────────────────────

async function startRun(p, pageTabId) {
  const job = {
    runId: p.runId, apiBase: p.apiBase, token: p.token, pageTabId, tabId: null,
    pageFrom: p.pageFrom, pageTo: p.pageTo, stage: 'searching', startedAt: Date.now(),
  };
  await setJob(job);
  await emit(job, 'searching');

  const loggedIn = await checkResdexLogin();
  if ((await getJob())?.runId !== job.runId) return;  // cancelled during the check
  if (!loggedIn) return failRun(job, 'not_logged_in');

  const SEARCH_REASONS = ['not_logged_in', 'search_form_not_found', 'search_failed'];
  let tabId;
  try { tabId = await runResdexSearch(p.plan, job); }
  catch (e) {
    if ((await getJob())?.runId !== job.runId) return;  // cancelled meanwhile
    return failRun(job, SEARCH_REASONS.includes(e.message) ? e.message : 'error', e.message);
  }
  if ((await getJob())?.runId !== job.runId) return;  // cancelled meanwhile
  job.tabId = tabId;
  await setJob({ ...(await getJob()), tabId });

  try {
    await chrome.tabs.sendMessage(tabId, {
      type: 'MH_SKILLMATE_CRAWL', runId: job.runId, pageFrom: job.pageFrom, pageTo: job.pageTo,
    });
  } catch (e) {
    return failRun(job, 'error', 'The ResDex tab is not ready — reload it and try again.');
  }
  await emit(job, 'scraping', { page: job.pageFrom, pageTo: job.pageTo });
}

const POLL_MS = 3000;
const SCREEN_WAIT_MS = 10 * 60 * 1000;  // one page's screening should take ~1 minute

// One ResDex page from the content script: post it, wait while SkillMate screens it, then
// tell the tab to read the next page or stop.
async function crawlPage(runId, page, profiles, ended, sourceUrl) {
  let job = await getJob();
  if (!job || job.runId !== runId) return;
  await emit(job, 'screening', { page, pageTo: job.pageTo });
  try {
    await api(job, `/sourcing/runs/${runId}/profiles`, { profiles: profiles || [], ended: !!ended, source_url: sourceUrl || '' });
    job.pagesSent = (job.pagesSent || 0) + 1;
    job.profilesSent = (job.profilesSent || 0) + (profiles || []).length;
    await setJob({ ...(await getJob()), pagesSent: job.pagesSent, profilesSent: job.profilesSent });

    const deadline = Date.now() + SCREEN_WAIT_MS;
    while (Date.now() < deadline) {
      await new Promise((r) => setTimeout(r, POLL_MS));
      job = await getJob();
      if (!job || job.runId !== runId) return;  // cancelled meanwhile
      const run = await apiGet(job, `/sourcing/runs/${runId}`);
      if (run.status === 'scraping' && run.next_action === 'next_page') {
        const next = (page || job.pageFrom) + 1;
        await emit(job, 'scraping', { page: next, pageTo: job.pageTo, shortlisted: run.profiles_shortlisted, phase: run.phase });
        await chrome.tabs.sendMessage(job.tabId, { type: 'MH_SKILLMATE_CRAWL_NEXT', runId });
        return;
      }
      if (['done', 'failed', 'cancelled'].includes(run.status)) {
        try { await chrome.tabs.sendMessage(job.tabId, { type: 'MH_SKILLMATE_CRAWL_STOP' }); } catch (e) { /* closed */ }
        await emit(job, 'done', { shortlisted: run.profiles_shortlisted });
        await clearJob({ stage: 'done', profiles: job.profilesSent || 0, shortlisted: run.profiles_shortlisted });
        return;
      }
    }
    await failRun(job, 'error', 'SkillMate took too long to screen a page');
  } catch (e) {
    await failRun(job, e.message === 'skillmate_auth' ? 'skillmate_auth' : 'error', e.message);
  }
}

async function cancelRun(runId) {
  const job = await getJob();
  if (!job || (runId && job.runId !== runId)) return false;
  if (job.tabId) {
    try { await chrome.tabs.sendMessage(job.tabId, { type: 'MH_SKILLMATE_CRAWL_STOP' }); } catch (e) { /* gone */ }
  }
  await failRun(job, 'cancelled');
  return true;
}

// ── Contact reveal (one selected candidate, one credit) ──────────────────────────

async function revealContact(p) {
  const out = (ok, reason, candidateError = null) =>
    ({ type: 'SKILLMATE_REVEAL_RESULT', profileId: p.profileId, ok, reason, candidateError });
  if (!(await checkResdexLogin())) return out(false, 'not_logged_in');

  let tab = null;
  let found = {};
  try {
    tab = await chrome.tabs.create({ url: p.sourceLink, active: false });
    await waitForTabComplete(tab.id);
    const landed = await chrome.tabs.get(tab.id).catch(() => null);
    if (landed?.url && SkillmateCore.isResdexLoginUrl(landed.url)) return out(false, 'not_logged_in');
    found = (await chrome.tabs.sendMessage(tab.id, { type: 'MH_EXTRACT_CONTACT' })) || {};
    console.log(LOG, `contact · ${p.name}: phone=${found.phone || '(none)'} email=${found.email || '(none)'}`);
  } catch (e) {
    return out(false, e.message);
  } finally {
    if (tab?.id) { try { await chrome.tabs.remove(tab.id); } catch (e) { /* gone */ } }
    await new Promise((r) => setTimeout(r, REVEAL_PACE_MS));
  }

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
  return out(!!found.email, found.email ? undefined : 'no_email', candidateError);
}

// ── Requests from SkillMate (via bridge.js) ──────────────────────────────────────

async function handleSkillmate(p, sender) {
  const needsApi = p.type === 'SKILLMATE_SOURCE' || p.type === 'SKILLMATE_REVEAL';
  if (needsApi && (!p.token || !SkillmateCore.isAllowedApiBase(p.apiBase, SMConfig.SKILLMATE_API_ORIGINS))) {
    return { type: 'SKILLMATE_ERROR', ok: false, reason: 'api_not_allowed' };
  }
  switch (p.type) {
    case 'SKILLMATE_CHECK_LOGIN':
      return { type: 'SKILLMATE_LOGIN_STATE', loggedIn: await checkResdexLogin() };
    case 'SKILLMATE_SOURCE': {
      const running = await getJob();
      if (running && running.runId !== p.runId) {
        // A leftover from a run SkillMate already expired: stop its crawl, then start fresh.
        if (running.tabId) {
          try { await chrome.tabs.sendMessage(running.tabId, { type: 'MH_SKILLMATE_CRAWL_STOP' }); } catch (e) { /* gone */ }
        }
        await clearJob({ stage: 'error', reason: 'replaced' });
      }
      startRun(p, sender.tab?.id).catch((e) => console.error(LOG, e));
      return { type: 'SKILLMATE_SOURCE_ACK', ok: true };
    }
    case 'SKILLMATE_REVEAL':
      return revealContact(p);
    case 'SKILLMATE_CANCEL':
      await cancelRun(p.runId);
      return { type: 'SKILLMATE_CANCELLED', ok: true };
    default:
      return { type: 'SKILLMATE_ERROR', ok: false, reason: 'unknown_request' };
  }
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  switch (message?.type) {
    case 'MH_SKILLMATE':
      if (!message.payload) return false;
      handleSkillmate(message.payload, sender)
        .then((r) => sendResponse(r))
        .catch((err) => sendResponse({ type: 'SKILLMATE_ERROR', ok: false, reason: err.message }));
      return true;

    case 'MH_SKILLMATE_CRAWL_PAGE_DATA':
      crawlPage(message.runId, message.page, message.profiles, message.ended, message.sourceUrl)
        .catch((e) => console.error(LOG, e));
      sendResponse({ ok: true });
      return false;

    case 'MH_SKILLMATE_CRAWL_FAIL':
      getJob().then(async (job) => {
        if (job && job.runId === message.runId) await failRun(job, message.reason || 'error', message.detail || '');
        sendResponse({ ok: true });
      });
      return true;

    // From the popup
    case 'SM_POPUP_STATUS':
      Promise.all([getJob(), chrome.storage.session.get(LAST_KEY)])
        .then(([job, last]) => sendResponse({ job: job ? { ...job, token: undefined } : null, last: last[LAST_KEY] || null }));
      return true;
    case 'SM_POPUP_CHECK_LOGIN':
      checkResdexLogin().then((loggedIn) => sendResponse({ loggedIn }));
      return true;
    case 'SM_POPUP_STOP':
      getJob().then((job) => (job ? cancelRun(job.runId) : false)).then((ok) => sendResponse({ ok }));
      return true;

    default:
      return false;
  }
});

// A logged-out recruiter is bounced to login.naukri.com, where naukri.js can't see the run
// (different origin). Watch the crawl tab's address here instead.
chrome.tabs.onUpdated.addListener(async (tabId, changeInfo) => {
  if (!changeInfo.url || !SkillmateCore.isResdexLoginUrl(changeInfo.url)) return;
  const job = await getJob();
  if (job && job.tabId === tabId) await failRun(job, 'not_logged_in');
});
