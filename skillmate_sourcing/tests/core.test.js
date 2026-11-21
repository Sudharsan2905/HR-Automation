const test = require('node:test');
const assert = require('node:assert');
const C = require('../core.js');

test('origin must match exactly', () => {
  assert.equal(C.isAllowedOrigin('http://localhost:3000', 'http://localhost:3000'), true);
  assert.equal(C.isAllowedOrigin('http://localhost:3000', 'http://localhost:3000/'), true);
  assert.equal(C.isAllowedOrigin('http://localhost:3001', 'http://localhost:3000'), false);
  assert.equal(C.isAllowedOrigin('https://evil.com', 'http://localhost:3000'), false);
  assert.equal(C.isAllowedOrigin('', 'http://localhost:3000'), false);
});

test('page request shape', () => {
  assert.equal(C.isPageRequest({ source: 'skillmate-page', type: 'SKILLMATE_SOURCE', requestId: 'a' }), true);
  assert.equal(C.isPageRequest({ source: 'skillmate-page', type: 'MH_SEND_TO_API', requestId: 'a' }), false);
  assert.equal(C.isPageRequest({ type: 'SKILLMATE_SOURCE', requestId: 'a' }), false);
  assert.equal(C.isPageRequest({ source: 'skillmate-page', type: 'SKILLMATE_PING' }), false);
  assert.equal(C.isPageRequest(null), false);
});

test('resdex login detection', () => {
  assert.equal(C.isResdexLoginUrl('https://login.naukri.com/nLogin/Login.php'), true);
  assert.equal(C.isResdexLoginUrl('https://resdex.naukri.com/v2/nlogin?URL=x'), true);
  assert.equal(C.isResdexLoginUrl('https://www.naukri.com/recruit/login'), true);
  assert.equal(C.isResdexLoginUrl('https://resdex.naukri.com/v3/search?keyword=python'), false);
  assert.equal(C.isResdexLoginUrl('https://www.google.com/login'), false);
  assert.equal(C.isResdexLoginUrl('not a url'), false);
});

test('captcha text', () => {
  assert.equal(C.isCaptchaText('We detected unusual traffic from your network'), true);
  assert.equal(C.isCaptchaText('Please complete the CAPTCHA'), true);
  assert.equal(C.isCaptchaText('Showing 1-40 of 2,345 profiles'), false);
});

test('apiUrl joins cleanly', () => {
  assert.equal(C.apiUrl('http://localhost:3000/api/', '/sourcing/runs/1'), 'http://localhost:3000/api/sourcing/runs/1');
  assert.equal(C.apiUrl('http://localhost:8000/api', 'sourcing/runs/1'), 'http://localhost:8000/api/sourcing/runs/1');
});

test('apiBase must be an allowed API origin', () => {
  const allowed = ['http://localhost:3000', 'http://localhost:8000'];
  assert.equal(C.isAllowedApiBase('http://localhost:8000/api', allowed), true);
  assert.equal(C.isAllowedApiBase('https://evil.com/api', allowed), false);
  assert.equal(C.isAllowedApiBase('garbage', allowed), false);
});

test('progress text for the popup', () => {
  assert.equal(C.stageLabel('searching'), 'Searching ResDex for this JD…');
  assert.equal(C.stageLabel('scraping', 2, 7), 'Reading ResDex page 2…');
  assert.equal(C.stageLabel('scraping'), 'Reading ResDex results…');
  assert.equal(C.stageLabel('screening', 2), 'SkillMate is screening page 2…');
  assert.equal(C.stageLabel('done'), 'Done — matches are in SkillMate');
  assert.equal(C.stageLabel('error', null, null, 'not_logged_in'), 'Login with Naukri ResDex to continue extraction.');
  assert.equal(C.stageLabel('error', null, null, 'captcha'), 'Stopped: Naukri is showing a CAPTCHA');
  assert.equal(C.stageLabel('error', null, null, 'weird'), 'Stopped: weird');
});

test('picks the most recently used open ResDex tab, skipping login and preview tabs', () => {
  const tabs = [
    { id: 1, url: 'https://resdex.naukri.com/v3/search?k=a', lastAccessed: 10 },
    { id: 2, url: 'https://resdex.naukri.com/v3/search?k=b', lastAccessed: 30 },
    { id: 3, url: 'https://resdex.naukri.com/v2/nlogin?URL=x', lastAccessed: 50 },
    { id: 4, url: 'https://resdex.naukri.com/preview/123', lastAccessed: 60 },
    { id: 5, url: 'https://www.naukri.com/jobs', lastAccessed: 70 },
  ];
  assert.equal(C.pickResdexTab(tabs).id, 2);
  assert.equal(C.pickResdexTab([]), null);
  assert.equal(C.pickResdexTab([{ id: 3, url: 'https://login.naukri.com/nLogin/Login.php' }]), null);
});

test('only a visible password field counts as a login form', () => {
  const hidden = { offsetParent: null, getClientRects: () => [] };
  const visible = { offsetParent: {}, getClientRects: () => [{}] };
  assert.equal(C.hasVisibleLoginForm([]), false);
  assert.equal(C.hasVisibleLoginForm([hidden]), false);
  assert.equal(C.hasVisibleLoginForm([hidden, visible]), true);
});

test('search keywords come from the plan (narrowed only when the plan says so)', () => {
  const plan = { primary_keywords: ' Python AND AWS ', narrowed_keywords: 'Python AND AWS AND Lambda', use_narrowed: false };
  assert.equal(C.searchKeywords(plan), 'Python AND AWS');
  assert.equal(C.searchKeywords({ ...plan, use_narrowed: true }), 'Python AND AWS AND Lambda');
  assert.equal(C.searchKeywords({ ...plan, use_narrowed: true, narrowed_keywords: '' }), 'Python AND AWS');
  assert.equal(C.searchKeywords(null), '');
});

test('search form vs results page', () => {
  assert.equal(C.isResdexSearchFormUrl('https://resdex.naukri.com/v3?activeTab=advSrch'), true);
  assert.equal(C.isResdexSearchFormUrl('https://resdex.naukri.com/v3'), true);
  assert.equal(C.isResdexSearchFormUrl('https://resdex.naukri.com/v3/search?sid=1'), false);
  assert.equal(C.isResdexSearchFormUrl('https://www.google.com/v3?activeTab=advSrch'), false);
});

test('new failure reasons have recruiter-facing text', () => {
  assert.match(C.stageLabel('error', null, null, 'search_form_not_found'), /search form/i);
  assert.match(C.stageLabel('error', null, null, 'search_failed'), /search/i);
});
