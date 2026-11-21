// Drives background.js with a mocked chrome + SkillMate API: login check, paging, screening wait, failures,
// cancel and contact reveal. Uses real (short) timers, so it takes ~15 s.
const test = require('node:test');
const vm = require('vm');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const EXT = path.join(__dirname, '..');
const read = (f) => fs.readFileSync(path.join(EXT, f), 'utf8');
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function makeEnv(scn) {
  const log = { posts: [], fails: [], contacts: [], events: [], navigations: [], closed: [], activated: [] };
  const store = new Map();
  const tabs = new Map();
  let nextTab = 100;
  const updatedListeners = [];
  let runPolls = 0;

  const chrome = {
    runtime: { onInstalled: { addListener() {} }, onMessage: { addListener(fn) { chrome._onMessage = fn; } }, id: 'x', getManifest: () => ({ version: '1.1.0' }) },
    storage: { session: {
      async get(k) { return k in Object.fromEntries(store) ? { [k]: store.get(k) } : {}; },
      async set(o) { for (const [k, v] of Object.entries(o)) store.set(k, JSON.parse(JSON.stringify(v))); },
      async remove(k) { store.delete(k); },
    } },
    scripting: { executeScript: async () => {} },
    tabs: {
      onUpdated: { addListener: (fn) => updatedListeners.push(fn), removeListener: (fn) => { const i = updatedListeners.indexOf(fn); if (i >= 0) updatedListeners.splice(i, 1); } },
      async query() { return []; },
      async create({ url }) { const t = { id: nextTab++, url, status: 'complete' }; tabs.set(t.id, t); return t; },
      async get(id) { const t = tabs.get(id); if (!t) throw new Error('no tab'); return { ...t }; },
      async remove(id) { log.closed.push(id); tabs.delete(id); },
      async update(id, props) {
        const t = tabs.get(id);
        if (!t) throw new Error('no tab');
        if (props.active) log.activated.push(id);
        if (props.url) {
          let url = props.url;
          log.navigations.push(url);
          if (url.startsWith('https://www.linkedin.com/feed') && scn.notLoggedIn) url = 'https://www.linkedin.com/login';
          t.url = url;
          setTimeout(() => updatedListeners.slice().forEach((l) => l(id, { status: 'loading' })), 5);
          setTimeout(() => updatedListeners.slice().forEach((l) => l(id, { status: 'complete' })), 20);
        }
        return t;
      },
      async sendMessage(id, msg) {
        if (id === 99) { if (msg.type === 'LI_SKILLMATE_EVENT') log.events.push(msg.event); return; }
        const t = tabs.get(id);
        if (!t) throw new Error('no tab');
        if (msg.type === 'LI_PROBE') return { ok: true, url: t.url, loginForm: false, block: null };
        if (msg.type === 'LI_READ_PAGE') {
          const page = Number(new URL(t.url).searchParams.get('page'));
          return scn.pages(page, t.url);
        }
        if (msg.type === 'LI_EXTRACT_CONTACT') return typeof scn.contact === 'function' ? scn.contact(t.url) : scn.contact;
        throw new Error('unexpected message ' + msg.type);
      },
    },
  };

  const run = scn.run;
  async function fetchMock(url, opts = {}) {
    const method = opts.method || 'GET';
    const u = new URL(url);
    const body = opts.body ? JSON.parse(opts.body) : null;
    const json = (data, status = 200) => ({ ok: status < 400, status, json: async () => data });
    if (method === 'POST' && u.pathname.endsWith('/profiles')) { log.posts.push(body); return json({ accepted: body.profiles.length }, 202); }
    if (method === 'POST' && u.pathname.endsWith('/fail')) { log.fails.push(body); return json({}); }
    if (method === 'POST' && u.pathname.includes('/contact')) { log.contacts.push({ path: u.pathname, body }); return json({ data: { candidate_error: null } }); }
    if (method === 'GET' && u.pathname.includes('/sourcing/runs/')) {
      runPolls += 1;
      return json({ success: true, data: scn.runState(log.posts.length, runPolls, log) });
    }
    throw new Error('unexpected fetch ' + method + ' ' + url);
  }

  const ctx = vm.createContext({
    chrome, fetch: fetchMock, console: { log() {}, info() {}, warn() {}, error: console.error }, setTimeout, clearTimeout, URL, JSON, Date, Math, Promise, Error, Object, Array, Set, Map,
    importScripts(...files) { files.forEach((f) => vm.runInContext(read(f), ctx)); },
  });
  ctx.self = ctx;
  vm.runInContext(read('background.js'), ctx);
  ctx.SMLinkedinConfig.PAGE_PAUSE_SECONDS = [0.01, 0.02];
  ctx.SMLinkedinConfig.PROFILE_PAUSE_SECONDS = [0.01, 0.02];
  // The older scenarios exercise paging and failures, not contact reading: they run with EMAIL_ONLY off. The scenarios
  // at the end of this file switch it on (scn.emailOnly) and cover the default behaviour.
  ctx.SMLinkedinConfig.EMAIL_ONLY = scn.emailOnly === true;

  async function send(payload) {
    return new Promise((resolve) => chrome._onMessage({ type: 'LI_SKILLMATE', payload }, { tab: { id: 99 } }, resolve));
  }
  const popup = (type) => new Promise((resolve) => chrome._onMessage({ type }, {}, resolve));
  return { log, send, popup, store, tabs, setPauses: (r) => { ctx.SMLinkedinConfig.PROFILE_PAUSE_SECONDS = r; } };
}

const PLAN = { primary_keywords: 'Python AND Django', narrowed_keywords: '', use_narrowed: false, locations: ['Chennai'] };
const SOURCE = { type: 'LINKEDIN_SOURCE', requestId: 'r', runId: 'RUN1', apiBase: 'http://localhost:8000/api', token: 'T', plan: PLAN, pageFrom: 1, pageTo: 3 };
const prof = (i) => ({ name: `P${i}`, source_link: `https://www.linkedin.com/in/p${i}`, source: 'LinkedIn', skills: [], experiences: [] });
const waitUntil = async (fn, ms = 20000) => { const end = Date.now() + ms; while (Date.now() < end) { if (await fn()) return true; await sleep(100); } return false; };

const check = (name, fn) => test(name, fn);

  check('happy path: reads pages 1-3 in order, posts each, finishes, closes its tab', async () => {
    const env = makeEnv({
      pages: (p) => ({ ok: true, profiles: [prof(p * 10), prof(p * 10 + 1)], ended: p === 3, diag: { url: `https://www.linkedin.com/search/results/people/?page=${p}` } }),
      runState: (posted) => (posted < 3 ? { status: 'scraping', next_action: 'next_page', profiles_shortlisted: posted, phase: 'hunting' }
        : { status: 'done', next_action: null, profiles_shortlisted: 5 }),
    });
    const ack = await env.send(SOURCE);
    assert.equal(ack.type, 'LINKEDIN_SOURCE_ACK');
    assert.ok(await waitUntil(() => env.log.events.some((e) => e.stage === 'done')), 'run never finished');
    assert.equal(env.log.posts.length, 3);
    assert.deepEqual(env.log.posts.map((p) => p.profiles.length), [2, 2, 2]);
    assert.deepEqual(env.log.posts.map((p) => p.ended), [false, false, true]);
    const pages = env.log.navigations.filter((u) => u.includes('/search/results/people/')).map((u) => new URL(u).searchParams.get('page'));
    assert.deepEqual(pages, ['1', '2', '3']);
    const q = new URL(env.log.navigations.find((u) => u.includes('/search/results/'))).searchParams.get('keywords');
    assert.equal(q, '(Python AND Django) AND ("Chennai")');
    assert.deepEqual(env.log.fails, []);
    assert.equal(env.log.events.filter((e) => e.stage === 'scraping').length >= 3, true);
    assert.equal(env.store.has('skillmateLiJob'), false, 'job should be cleared');
    assert.equal((await env.popup('LI_POPUP_STATUS')).last.stage, 'done');
    assert.equal(env.tabs.size, 0, 'working tab left open');
  });

  check('a search-limit notice on page 2 fails the run as "restricted" and closes the tab', async () => {
    const env = makeEnv({
      pages: (p) => (p === 1 ? { ok: true, profiles: [prof(1)], ended: false } : { ok: true, block: 'restricted', profiles: [] }),
      runState: () => ({ status: 'scraping', next_action: 'next_page', profiles_shortlisted: 0, phase: 'hunting' }),
    });
    await env.send(SOURCE);
    assert.ok(await waitUntil(() => env.log.fails.length > 0));
    assert.equal(env.log.fails[0].reason, 'restricted');
    assert.equal(env.log.posts.length, 1);
    assert.ok(env.log.events.some((e) => e.stage === 'error' && e.reason === 'restricted'));
    assert.equal(env.tabs.size, 0);
  });

  check('a CAPTCHA keeps the tab open and brings it forward', async () => {
    const env = makeEnv({ pages: () => ({ ok: true, block: 'captcha', profiles: [] }), runState: () => ({}) });
    await env.send(SOURCE);
    assert.ok(await waitUntil(() => env.log.fails.length > 0));
    assert.equal(env.log.fails[0].reason, 'captcha');
    assert.equal(env.log.activated.length, 1);
    assert.equal(env.tabs.size, 1, 'the CAPTCHA tab must stay for the recruiter');
  });

  check('an empty first page fails with no_results', async () => {
    const env = makeEnv({ pages: () => ({ ok: true, profiles: [], ended: true, noResults: true }), runState: () => ({}) });
    await env.send(SOURCE);
    assert.ok(await waitUntil(() => env.log.fails.length > 0));
    assert.equal(env.log.fails[0].reason, 'error');
    assert.match(env.log.fails[0].detail, /no_results/);
  });

  check('an empty LATER page ends the results instead of failing', async () => {
    const env = makeEnv({
      pages: (p) => (p === 1 ? { ok: true, profiles: [prof(1)], ended: false } : { ok: true, profiles: [], ended: true }),
      runState: (posted) => (posted < 2 ? { status: 'scraping', next_action: 'next_page', profiles_shortlisted: 0, phase: 'hunting' }
        : { status: 'done', profiles_shortlisted: 1 }),
    });
    await env.send({ ...SOURCE, pageFrom: 1, pageTo: 4 });
    assert.ok(await waitUntil(() => env.log.events.some((e) => e.stage === 'done')));
    assert.equal(env.log.fails.length, 0);
    assert.deepEqual(env.log.posts.map((p) => p.ended), [false, true]);
  });

  check('not logged in: fails with not_logged_in before reading anything', async () => {
    const env = makeEnv({ notLoggedIn: true, pages: () => { throw new Error('must not read'); }, runState: () => ({}) });
    await env.send(SOURCE);
    assert.ok(await waitUntil(() => env.log.fails.length > 0));
    assert.equal(env.log.fails[0].reason, 'not_logged_in');
    assert.equal(env.log.posts.length, 0);
  });

  check('an empty search plan is refused', async () => {
    const env = makeEnv({ pages: () => { throw new Error('must not read'); }, runState: () => ({}) });
    await env.send({ ...SOURCE, plan: { primary_keywords: '', locations: [] } });
    assert.ok(await waitUntil(() => env.log.fails.length > 0));
    assert.match(env.log.fails[0].detail, /search_failed/);
  });

  check('the SkillMate token is refused for an unlisted API origin', async () => {
    const env = makeEnv({ pages: () => ({}), runState: () => ({}) });
    const res = await env.send({ ...SOURCE, apiBase: 'https://evil.example/api' });
    assert.equal(res.reason, 'api_not_allowed');
  });

  check('cancel stops the run, closes the tab and fails it as cancelled', async () => {
    const env = makeEnv({
      pages: (p) => ({ ok: true, profiles: [prof(p)], ended: false }),
      runState: () => ({ status: 'scraping', next_action: null, profiles_shortlisted: 0, phase: 'hunting' }),  // screening never ends
    });
    await env.send(SOURCE);
    assert.ok(await waitUntil(() => env.log.posts.length === 1));
    const res = await env.send({ type: 'LINKEDIN_CANCEL', requestId: 'c', runId: 'RUN1' });
    assert.equal(res.type, 'LINKEDIN_CANCELLED');
    assert.ok(await waitUntil(() => env.log.fails.some((f) => f.reason === 'cancelled')));
    assert.equal(env.store.has('skillmateLiJob'), false);
    await sleep(3500);   // the polling loop must notice and stop: no more posts, no stray tab
    assert.equal(env.log.posts.length, 1);
    assert.equal(env.tabs.size, 0);
  });

  check('reveal: a connection\'s email and phone are saved to SkillMate', async () => {
    const env = makeEnv({ pages: () => ({}), runState: () => ({}), contact: { ok: true, email: 'asha@gmail.com', phone: '9000000001', dialog: true } });
    const r = await env.send({ type: 'LINKEDIN_REVEAL', requestId: 'x', profileId: 'PID', name: 'Asha', sourceLink: 'https://www.linkedin.com/in/asha/?x=1', apiBase: 'http://localhost:8000/api', token: 'T' });
    assert.deepEqual([r.type, r.ok, r.reason], ['LINKEDIN_REVEAL_RESULT', true, undefined]);
    assert.deepEqual(env.log.contacts[0], { path: '/api/sourcing/profiles/PID/contact', body: { email: 'asha@gmail.com', phone: '9000000001' } });
    assert.ok(env.log.navigations.includes('https://www.linkedin.com/in/asha/overlay/contact-info/'));
    assert.equal(env.tabs.size, 0);
  });

  check('reveal: a non-connection has no email -> ok:false no_email, nothing saved', async () => {
    const env = makeEnv({ pages: () => ({}), runState: () => ({}), contact: { ok: true, email: '', phone: '', dialog: true } });
    const r = await env.send({ type: 'LINKEDIN_REVEAL', requestId: 'x', profileId: 'PID', name: 'Ravi', sourceLink: 'https://www.linkedin.com/in/ravi', apiBase: 'http://localhost:8000/api', token: 'T' });
    assert.deepEqual([r.ok, r.reason], [false, 'no_email']);
    assert.equal(env.log.contacts.length, 0);
  });

  check('reveal: a dead run left behind by a crash does not block contact reads', async () => {
  const env = makeEnv({ pages: () => ({}), runState: () => ({}), contact: { ok: true, email: 'asha@gmail.com', phone: '', dialog: true } });
  // a job from a run whose worker was killed an hour ago, never cleaned up
  env.store.set('skillmateLiJob', { runId: 'OLD', startedAt: Date.now() - 60 * 60 * 1000, stage: 'scraping' });
  const r = await env.send({ type: 'LINKEDIN_REVEAL', requestId: 'x', profileId: 'PID', name: 'Asha', sourceLink: 'https://www.linkedin.com/in/asha', apiBase: 'http://localhost:8000/api', token: 'T' });
  assert.deepEqual([r.ok, r.reason], [true, undefined]);
});

check('reveal: a security check is reported, nothing saved', async () => {
    const env = makeEnv({ pages: () => ({}), runState: () => ({}), contact: { ok: false, block: 'captcha' } });
    const r = await env.send({ type: 'LINKEDIN_REVEAL', requestId: 'x', profileId: 'PID', name: 'Ravi', sourceLink: 'https://www.linkedin.com/in/ravi', apiBase: 'http://localhost:8000/api', token: 'T' });
    assert.deepEqual([r.ok, r.reason], [false, 'captcha']);
  });

  check('reveal: refused for a link that is not a LinkedIn profile, or while a run is active', async () => {
    const env = makeEnv({ pages: (p) => ({ ok: true, profiles: [prof(p)], ended: false }), runState: () => ({ status: 'scraping', next_action: null }), contact: { ok: true, email: 'a@b.com' } });
    let r = await env.send({ type: 'LINKEDIN_REVEAL', requestId: 'x', profileId: 'P', name: 'X', sourceLink: 'https://resdex.naukri.com/p/1', apiBase: 'http://localhost:8000/api', token: 'T' });
    assert.deepEqual([r.ok, r.reason], [false, 'bad_link']);
    await env.send(SOURCE);
    assert.ok(await waitUntil(() => env.log.posts.length === 1));
    r = await env.send({ type: 'LINKEDIN_REVEAL', requestId: 'x', profileId: 'P', name: 'X', sourceLink: 'https://www.linkedin.com/in/x', apiBase: 'http://localhost:8000/api', token: 'T' });
    assert.deepEqual([r.ok, r.reason], [false, 'busy']);
    await env.send({ type: 'LINKEDIN_CANCEL', requestId: 'c', runId: 'RUN1' });
  });

// ── the search ladder: when LinkedIn finds nobody the search is broadened, step by step ──────────────────────────────

const LADDER_PLAN = {
  primary_keywords: '(HTML5 OR HTML) AND (CSS3 OR CSS) AND (JavaScript OR JS) AND (Angular OR React) AND (Node.js OR NodeJS OR Node) '
    + 'AND (MySQL OR PostgreSQL) AND Git AND ("API security" OR authentication OR authorization) AND "Problem-solving" AND "Communication skills"',
  narrowed_keywords: '', use_narrowed: false, locations: [],
};
const groupsIn = (url) => new URL(url).searchParams.get('keywords').split(' AND ').length;   // (every group here has no inner AND)
const searchNavs = (env) => env.log.navigations.filter((u) => u.includes('/search/results/people/'));
const nobody = { ok: true, profiles: [], ended: true, noResults: true, diag: { cards: 0, anchors: 0, title: 'Search | LinkedIn', text: 'No results found', noResults: true } };
const somebody = (p) => ({ ok: true, profiles: [prof(p * 10), prof(p * 10 + 1)], ended: false, diag: { cards: 2 } });

check('a search nobody matches is broadened until LinkedIn returns people, and the step is reported back', async () => {
  // 8 technical groups -> steps of 8, 5, 3 and 2 groups; only the 3-group search finds anyone
  const env = makeEnv({
    pages: (p, url) => (groupsIn(url) > 3 ? nobody : somebody(p)),
    runState: (posted) => (posted < 2 ? { status: 'scraping', next_action: 'next_page', profiles_shortlisted: 0, phase: 'hunting' }
      : { status: 'done', profiles_shortlisted: 4 }),
  });
  await env.send({ ...SOURCE, plan: LADDER_PLAN, pageFrom: 1, pageTo: 2 });
  assert.ok(await waitUntil(() => env.log.events.some((e) => e.stage === 'done')), 'run never finished');
  const navs = searchNavs(env);
  assert.deepEqual(navs.map(groupsIn), [8, 5, 3, 3]);                       // 8 -> 5 -> 3 (people!) -> page 2 stays on 3
  assert.deepEqual(navs.map((u) => new URL(u).searchParams.get('page')), ['1', '1', '1', '2']);
  assert.ok(!navs.some((u) => /Problem-solving|Communication/.test(decodeURIComponent(u))), 'a soft skill was searched');
  assert.deepEqual(env.log.posts.map((p) => p.search_level), [2, 2]);       // SkillMate remembers step 2
  assert.deepEqual(env.log.fails, []);
});

check('later runs start from the step earlier runs settled on, and an empty later page ends the results', async () => {
  const env = makeEnv({
    pages: () => nobody,
    runState: () => ({ status: 'done', profiles_shortlisted: 0 }),
  });
  await env.send({ ...SOURCE, plan: LADDER_PLAN, pageFrom: 3, pageTo: 5, searchLevel: 2 });
  assert.ok(await waitUntil(() => env.log.events.some((e) => e.stage === 'done')));
  const navs = searchNavs(env);
  assert.equal(navs.length, 1, 'page 3 being empty means "no more results", not "search too narrow"');
  assert.equal(groupsIn(navs[0]), 3);
  assert.deepEqual([env.log.posts[0].ended, env.log.posts[0].search_level], [true, 2]);
  assert.deepEqual(env.log.fails, []);
});

check('when even the broadest search finds nobody the run fails with no_results after trying every step', async () => {
  const env = makeEnv({ pages: () => nobody, runState: () => ({}) });
  await env.send({ ...SOURCE, plan: LADDER_PLAN, pageFrom: 1, pageTo: 3 });
  assert.ok(await waitUntil(() => env.log.fails.length > 0));
  assert.match(env.log.fails[0].detail, /no_results/);
  assert.deepEqual(searchNavs(env).map(groupsIn), [8, 5, 3, 2]);
  // the failure carries what LinkedIn showed at every step, so "no results" can be explained afterwards
  const debug = env.log.fails[0].debug;
  assert.equal(debug.split(' ; ').length, 4);
  assert.match(debug, /^L0@p1 v1\.1\.0: cards=0 profiles=0 no-results-page anchors=0 title="Search \| LinkedIn" text="No results found"/);
  assert.match(debug, /L3@p1/);
  assert.equal(env.log.posts.length, 0);
  assert.equal(env.tabs.size, 0);
});

check('a page that never rendered is a search_failed, not a reason to broaden the search', async () => {
  const env = makeEnv({ pages: () => ({ ok: true, profiles: [], ended: false, diag: { cards: 0, timedOut: true } }), runState: () => ({}) });
  await env.send({ ...SOURCE, plan: LADDER_PLAN, pageFrom: 1, pageTo: 3 });
  assert.ok(await waitUntil(() => env.log.fails.length > 0));
  assert.match(env.log.fails[0].detail, /search_failed/);
  assert.equal(searchNavs(env).length, 1);
});

check('a plan with a single step is not retried: no results fails straight away', async () => {
  const env = makeEnv({ pages: () => nobody, runState: () => ({}) });
  await env.send({ ...SOURCE, plan: { primary_keywords: 'Python AND Django', locations: [] }, pageFrom: 1, pageTo: 2 });
  assert.ok(await waitUntil(() => env.log.fails.length > 0));
  assert.equal(searchNavs(env).length, 1);
});

check('a page that never rendered records what it looked like', async () => {
  const env = makeEnv({
    pages: () => ({ ok: true, profiles: [], ended: false, diag: { cards: 0, timedOut: true, anchors: 3, title: 'Search | LinkedIn', text: 'Loading…' } }),
    runState: () => ({}),
  });
  await env.send({ ...SOURCE, plan: LADDER_PLAN, pageFrom: 1, pageTo: 3 });
  assert.ok(await waitUntil(() => env.log.fails.length > 0));
  assert.match(env.log.fails[0].debug, /timed-out anchors=3 title="Search \| LinkedIn" text="Loading…"/);
});

check('failures that have no page to describe send an empty debug string', async () => {
  const env = makeEnv({ pages: () => ({}), runState: () => ({}) });
  await env.send({ ...SOURCE, plan: { primary_keywords: '', locations: [] } });
  assert.ok(await waitUntil(() => env.log.fails.length > 0));
  assert.equal(env.log.fails[0].debug, '');
});

// -- candidates are taken only with an email -----------------------------------------------------------------------

const slugOf = (url) => (url.match(/\/in\/([^/]+)\//) || [])[1];
const overlayNavs = (env) => env.log.navigations.filter((u) => u.includes('/overlay/contact-info/'));
const person = (i, degree) => ({ name: `P${i}`, source_link: `https://www.linkedin.com/in/p${i}`, source: 'LinkedIn', skills: [], experiences: [], connection_degree: degree });
const pageOf = (people) => ({ ok: true, profiles: people, ended: false, diag: { cards: people.length, anchors: people.length, title: 'Search | LinkedIn' } });
// p1, p3 share an email; p2 has a dialog with nothing in it; p4 would, but is never opened
const EMAILS = { p1: 'one@example.com', p3: 'three@example.com' };
const dialogFor = (url) => ({ ok: true, email: EMAILS[slugOf(url)] || '', phone: slugOf(url) === 'p1' ? '9000000001' : '', dialog: true });

check('email-only: only 1st-degree people are opened, only those with an email are sent, and the count of people seen goes along', async () => {
  const env = makeEnv({
    emailOnly: true,
    pages: () => pageOf([person(1, '1st'), person(2, '1st'), person(3, '1st'), person(4, '2nd'), person(5, '3rd+')]),
    contact: dialogFor,
    runState: () => ({ status: 'done', profiles_shortlisted: 2 }),
  });
  await env.send({ ...SOURCE, plan: { primary_keywords: 'Python AND Django', locations: [] }, pageFrom: 1, pageTo: 1 });
  assert.ok(await waitUntil(() => env.log.events.some((e) => e.stage === 'done')), 'run never finished');
  assert.deepEqual(overlayNavs(env).map(slugOf), ['p1', 'p2', 'p3']);            // the 2nd and 3rd-degree people were never opened
  const post = env.log.posts[0];
  assert.deepEqual(post.profiles.map((x) => [x.name, x.email]), [['P1', 'one@example.com'], ['P3', 'three@example.com']]);
  assert.equal(post.profiles[0].phone, '9000000001');
  assert.equal(post.scanned, 5);                                                   // five people were looked at, two kept
  assert.ok(searchNavs(env).every((u) => new URL(u).searchParams.get('network') === '["F"]'), 'search is not limited to 1st-degree connections');
  assert.deepEqual(env.log.fails, []);
  assert.equal(env.tabs.size, 0, 'a working tab was left open');
  assert.ok(env.log.events.some((e) => e.stage === 'contacts' && e.total === 3), 'no progress was reported while reading contacts');
});

check('email-only: a page where nobody shares an email is still posted, so SkillMate counts it and asks for the next one', async () => {
  const env = makeEnv({
    emailOnly: true,
    pages: (p) => pageOf([person(10 * p + 1, '1st'), person(10 * p + 2, '2nd')]),
    contact: () => ({ ok: true, email: '', phone: '', dialog: true }),
    runState: (posted) => (posted < 2 ? { status: 'scraping', next_action: 'next_page', profiles_shortlisted: 0, phase: 'hunting' }
      : { status: 'done', profiles_shortlisted: 0 }),
  });
  await env.send({ ...SOURCE, plan: { primary_keywords: 'Python AND Django', locations: [] }, pageFrom: 1, pageTo: 2 });
  assert.ok(await waitUntil(() => env.log.events.some((e) => e.stage === 'done')));
  assert.deepEqual(env.log.posts.map((x) => [x.profiles.length, x.scanned, x.ended]), [[0, 2, false], [0, 2, false]]);
  assert.deepEqual(env.log.fails, []);
});

check('email-only: a card with no degree is tried rather than lost', async () => {
  const env = makeEnv({
    emailOnly: true, pages: () => pageOf([person(1, '')]), contact: dialogFor,
    runState: () => ({ status: 'done', profiles_shortlisted: 1 }),
  });
  await env.send({ ...SOURCE, plan: { primary_keywords: 'Python AND Django', locations: [] }, pageFrom: 1, pageTo: 1 });
  assert.ok(await waitUntil(() => env.log.events.some((e) => e.stage === 'done')));
  assert.deepEqual(env.log.posts[0].profiles.map((x) => x.email), ['one@example.com']);
});

check('email-only: a security check while reading contacts fails the run and leaves that tab open, in front', async () => {
  const env = makeEnv({
    emailOnly: true, pages: () => pageOf([person(1, '1st'), person(3, '1st')]),
    contact: (url) => (slugOf(url) === 'p1' ? dialogFor(url) : { ok: false, block: 'captcha' }),
    runState: () => ({}),
  });
  await env.send({ ...SOURCE, plan: { primary_keywords: 'Python AND Django', locations: [] }, pageFrom: 1, pageTo: 2 });
  assert.ok(await waitUntil(() => env.log.fails.length > 0));
  assert.equal(env.log.fails[0].reason, 'captcha');
  assert.match(env.log.fails[0].detail, /reading contact details/);
  assert.equal(env.log.posts.length, 0, 'half a page must not be posted');
  assert.ok(env.log.activated.length >= 1, 'the challenge tab was not brought forward');
});

check('email-only: stopping the run stops the contact reads straight away', async () => {
  const env = makeEnv({
    emailOnly: true, pages: () => pageOf([1, 2, 3, 4, 5, 6].map((i) => person(i, '1st'))), contact: dialogFor, runState: () => ({}),
  });
  env.setPauses([0.4, 0.4]);                                                        // slow enough to cancel in the middle of a page
  await env.send({ ...SOURCE, plan: { primary_keywords: 'Python AND Django', locations: [] }, pageFrom: 1, pageTo: 2 });
  assert.ok(await waitUntil(() => overlayNavs(env).length >= 1));
  await env.send({ type: 'LINKEDIN_CANCEL', requestId: 'c', runId: 'RUN1' });
  assert.ok(await waitUntil(() => env.log.fails.some((f) => f.reason === 'cancelled')));
  const seen = overlayNavs(env).length;
  await sleep(1500);
  assert.equal(overlayNavs(env).length, seen, 'contact reads carried on after cancel');
  assert.ok(seen < 6);
  assert.equal(env.log.posts.length, 0);
});

check('with EMAIL_ONLY off nothing changes: every card is sent, no contact dialog is opened, no connection filter', async () => {
  const env = makeEnv({
    emailOnly: false, pages: () => pageOf([person(1, '1st'), person(2, '2nd')]), contact: dialogFor,
    runState: () => ({ status: 'done', profiles_shortlisted: 1 }),
  });
  await env.send({ ...SOURCE, plan: { primary_keywords: 'Python AND Django', locations: [] }, pageFrom: 1, pageTo: 1 });
  assert.ok(await waitUntil(() => env.log.events.some((e) => e.stage === 'done')));
  assert.equal(overlayNavs(env).length, 0);
  assert.deepEqual(env.log.posts[0].profiles.map((x) => x.name), ['P1', 'P2']);
  assert.ok(searchNavs(env).every((u) => !new URL(u).searchParams.has('network')));
});
