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

test('page requests use the LinkedIn namespace, never the Naukri one', () => {
  assert.equal(C.isPageRequest({ source: 'skillmate-li-page', type: 'LINKEDIN_SOURCE', requestId: 'a' }), true);
  assert.equal(C.isPageRequest({ source: 'skillmate-li-page', type: 'LINKEDIN_PING', requestId: 'a' }), true);
  // the Naukri extension's messages must be ignored here (and vice versa)
  assert.equal(C.isPageRequest({ source: 'skillmate-page', type: 'SKILLMATE_SOURCE', requestId: 'a' }), false);
  assert.equal(C.isPageRequest({ source: 'skillmate-li-page', type: 'SKILLMATE_SOURCE', requestId: 'a' }), false);
  assert.equal(C.isPageRequest({ source: 'skillmate-li-page', type: 'LINKEDIN_PING' }), false);
  assert.equal(C.isPageRequest(null), false);
});

test('apiUrl joins cleanly and the token only goes to allowed origins', () => {
  assert.equal(C.apiUrl('http://localhost:3000/api/', '/sourcing/runs/1'), 'http://localhost:3000/api/sourcing/runs/1');
  const allowed = ['http://localhost:3000', 'http://localhost:8000'];
  assert.equal(C.isAllowedApiBase('http://localhost:8000/api', allowed), true);
  assert.equal(C.isAllowedApiBase('https://evil.com/api', allowed), false);
  assert.equal(C.isAllowedApiBase('garbage', allowed), false);
});

test('login and checkpoint urls', () => {
  assert.equal(C.isLinkedinLoginUrl('https://www.linkedin.com/login'), true);
  assert.equal(C.isLinkedinLoginUrl('https://www.linkedin.com/uas/login?session_redirect=x'), true);
  assert.equal(C.isLinkedinLoginUrl('https://www.linkedin.com/authwall?trk=x'), true);
  assert.equal(C.isLinkedinLoginUrl('https://www.linkedin.com/checkpoint/lg/login-submit'), true);
  assert.equal(C.isLinkedinLoginUrl('https://www.linkedin.com/feed/'), false);
  assert.equal(C.isLinkedinLoginUrl('https://www.linkedin.com/search/results/people/?keywords=python'), false);
  assert.equal(C.isLinkedinLoginUrl('https://example.com/login'), false);
  assert.equal(C.isLinkedinCheckpointUrl('https://www.linkedin.com/checkpoint/challenge/abc'), true);
  assert.equal(C.isLinkedinCheckpointUrl('https://www.linkedin.com/checkpoint/lg/login-submit'), false);
  assert.equal(C.isLinkedinLoginUrl('not a url'), false);
});

test('what stops a run', () => {
  assert.equal(C.classifyBlock('https://www.linkedin.com/login', ''), 'not_logged_in');
  assert.equal(C.classifyBlock('https://www.linkedin.com/checkpoint/challenge/x', ''), 'captcha');
  assert.equal(C.classifyBlock('https://www.linkedin.com/search/results/people/', 'Let’s do a quick security check'), 'captcha');
  assert.equal(C.classifyBlock('https://www.linkedin.com/search/results/people/',
    'You’ve reached the commercial use limit on search'), 'restricted');
  assert.equal(C.classifyBlock('https://www.linkedin.com/search/results/people/', 'Your account has been restricted'), 'restricted');
  assert.equal(C.classifyBlock('https://www.linkedin.com/search/results/people/', 'About 1,200 results'), null);
  assert.equal(C.isNoResultsText('No results found'), true);
  assert.equal(C.isNoResultsText('About 1,200 results'), false);
});

test('search keywords come from the plan (narrowed only when the plan says so)', () => {
  const plan = { primary_keywords: ' Python AND AWS ', narrowed_keywords: 'Python AND AWS AND Lambda', use_narrowed: false };
  assert.equal(C.searchKeywords(plan), 'Python AND AWS');
  assert.equal(C.searchKeywords({ ...plan, use_narrowed: true }), 'Python AND AWS AND Lambda');
  assert.equal(C.searchKeywords({ ...plan, use_narrowed: true, narrowed_keywords: '' }), 'Python AND AWS');
  assert.equal(C.searchKeywords(null), '');
});

test('search query adds the JD cities as an OR group', () => {
  const plan = { primary_keywords: '(React OR "React.js") AND Python', narrowed_keywords: '', use_narrowed: false, locations: [] };
  assert.equal(C.buildSearchQuery(plan), '(React OR "React.js") AND Python');
  assert.equal(C.buildSearchQuery({ ...plan, locations: ['Chennai', ' Coimbatore '] }),
    '((React OR "React.js") AND Python) AND ("Chennai" OR "Coimbatore")');
  assert.equal(C.buildSearchQuery({ ...plan, locations: ['Chen"nai'] }), '((React OR "React.js") AND Python) AND ("Chennai")');
  assert.equal(C.buildSearchQuery({ primary_keywords: '' }), '');
});

test('search url encodes the query and pages by number', () => {
  const plan = { primary_keywords: 'Python AND "Machine Learning"', locations: [] };
  const url = new URL(C.buildSearchUrl(plan, 3));
  assert.equal(url.origin + url.pathname, 'https://www.linkedin.com/search/results/people/');
  assert.equal(url.searchParams.get('keywords'), 'Python AND "Machine Learning"');
  assert.equal(url.searchParams.get('page'), '3');
  assert.equal(new URL(C.buildSearchUrl(plan, 0)).searchParams.get('page'), '1');
  assert.equal(C.buildSearchUrl({ primary_keywords: '' }, 1), '');
});

test('profile urls are reduced to one canonical form', () => {
  assert.equal(C.normalizeProfileUrl('https://www.linkedin.com/in/asha-kumar-123/?miniProfileUrn=urn%3Ali%3Afs'),
    'https://www.linkedin.com/in/asha-kumar-123');
  assert.equal(C.normalizeProfileUrl('/in/asha-kumar-123/'), 'https://www.linkedin.com/in/asha-kumar-123');
  assert.equal(C.normalizeProfileUrl('https://linkedin.com/in/asha/details/skills/'), 'https://www.linkedin.com/in/asha');
  assert.equal(C.normalizeProfileUrl('https://in.linkedin.com/in/asha'), 'https://www.linkedin.com/in/asha');
  assert.equal(C.normalizeProfileUrl('https://www.linkedin.com/company/zoho/'), '');
  assert.equal(C.normalizeProfileUrl('https://example.com/in/asha'), '');
  assert.equal(C.normalizeProfileUrl('::'), '');
  assert.equal(C.contactInfoUrl('https://www.linkedin.com/in/asha/?x=1'), 'https://www.linkedin.com/in/asha/overlay/contact-info/');
  assert.equal(C.contactInfoUrl('https://www.linkedin.com/company/zoho'), '');
});

test('a result card becomes a profile', () => {
  const p = C.parseResultLines([
    'Asha Kumar', 'Asha Kumar', '• 2nd', 'Senior Python Developer | Django | AWS',
    'Chennai, Tamil Nadu, India', 'Current: Senior Software Engineer at Zoho',
    'Skills: Python, Django, AWS, and 4 more', 'Message', 'Vijaya Kumar and 2 other mutual connections',
  ]);
  assert.equal(p.name, 'Asha Kumar');
  assert.equal(p.degree, '2nd');
  assert.equal(p.headline, 'Senior Python Developer | Django | AWS');
  assert.equal(p.location, 'Chennai, Tamil Nadu, India');
  assert.equal(p.title, 'Senior Software Engineer');
  assert.equal(p.company, 'Zoho');
  assert.deepEqual(p.skills, ['Python', 'Django', 'AWS']);
});

test('a card without a "Current:" line takes the role from the headline, and keeps leftover text as the snippet', () => {
  const p = C.parseResultLines([
    'Ravi S • 1st', 'Full Stack Engineer at Freshworks', 'Bengaluru',
    'Summary: Built React and Node apps for 6 years', 'Past: Developer at TCS',
  ]);
  assert.equal(p.degree, '1st');
  assert.equal(p.title, 'Full Stack Engineer');
  assert.equal(p.company, 'Freshworks');
  assert.equal(p.location, 'Bengaluru');
  assert.match(p.snippet, /Built React and Node apps/);
  assert.match(p.snippet, /Past: Developer at TCS/);
});

test('out-of-network members and empty cards are skipped', () => {
  assert.equal(C.parseResultLines(['LinkedIn Member', 'Software Engineer']), null);
  assert.equal(C.parseResultLines([]), null);
  assert.equal(C.parseResultLines(['Connect', 'Message']), null);
});

test('phone numbers: Indian mobiles and +country numbers only', () => {
  assert.equal(C.validPhone('9000000001 (Mobile)'), '9000000001');
  assert.equal(C.validPhone('+91 90000 00001'), '9000000001');
  assert.equal(C.validPhone('09000000001'), '9000000001');
  assert.equal(C.validPhone('+44 7911 123456'), '+447911123456');
  assert.equal(C.validPhone('044 2345 6789'), '');
  assert.equal(C.validPhone('12345'), '');
  assert.equal(C.validPhone(''), '');
});

test('emails: valid ones only, never LinkedIn’s own', () => {
  assert.equal(C.validEmail(' Asha@Mail.com '), 'asha@mail.com');
  assert.equal(C.validEmail('help@linkedin.com'), '');
  assert.equal(C.validEmail('noreply@x.com'), '');
  assert.equal(C.validEmail('not an email'), '');
});

test('the contact-info dialog gives phone and email', () => {
  const lines = [
    'Contact info', 'Asha’s profile', 'linkedin.com/in/asha', 'Phone', '9000000001 (Mobile)',
    'Email', 'asha@gmail.com', 'Connected since', 'Oct 9, 2026',
  ];
  assert.deepEqual(C.parseContactOverlay(lines, []), { email: 'asha@gmail.com', phone: '9000000001' });
  // email only, found through its mailto link
  assert.deepEqual(C.parseContactOverlay(['Contact info', 'Email'], ['mailto:Ravi@Mail.com']), { email: 'ravi@mail.com', phone: '' });
  // a non-connection's dialog shows only the profile link
  assert.deepEqual(C.parseContactOverlay(['Contact info', 'Asha’s profile', 'linkedin.com/in/asha'], []), { email: '', phone: '' });
  // a number printed outside the Phone section is never taken
  assert.deepEqual(C.parseContactOverlay(['Contact info', 'Call 9876543210 now'], []), { email: '', phone: '' });
});

test('progress text for the popup', () => {
  assert.equal(C.stageLabel('searching'), 'Searching LinkedIn for this JD…');
  assert.equal(C.stageLabel('scraping', 2, 7), 'Reading LinkedIn page 2…');
  assert.equal(C.stageLabel('screening', 2), 'SkillMate is screening page 2…');
  assert.equal(C.stageLabel('done'), 'Done — matches are in SkillMate');
  assert.match(C.stageLabel('error', null, null, 'captcha'), /security check/);
  assert.match(C.stageLabel('error', null, null, 'restricted'), /limited/);
  assert.equal(C.stageLabel('error', null, null, 'weird'), 'Stopped: weird');
});

test('picks the most recently used LinkedIn tab, skipping login and checkpoint tabs', () => {
  const tabs = [
    { id: 1, url: 'https://www.linkedin.com/feed/', lastAccessed: 10 },
    { id: 2, url: 'https://www.linkedin.com/in/asha/', lastAccessed: 30 },
    { id: 3, url: 'https://www.linkedin.com/login', lastAccessed: 50 },
    { id: 4, url: 'https://www.linkedin.com/checkpoint/challenge/x', lastAccessed: 60 },
    { id: 5, url: 'https://example.com/', lastAccessed: 70 },
  ];
  assert.equal(C.pickLinkedinTab(tabs).id, 2);
  assert.equal(C.pickLinkedinTab([]), null);
  assert.equal(C.pickLinkedinTab([{ id: 3, url: 'https://www.linkedin.com/login' }]), null);
});

test('only a visible password field counts as a login form', () => {
  const hidden = { offsetParent: null, getClientRects: () => [] };
  const visible = { offsetParent: {}, getClientRects: () => [{}] };
  assert.equal(C.hasVisibleLoginForm([]), false);
  assert.equal(C.hasVisibleLoginForm([hidden]), false);
  assert.equal(C.hasVisibleLoginForm([hidden, visible]), true);
});

// ── The search ladder: soft skills out, then broaden step by step when LinkedIn finds nobody ──────────────────────

// The real plan of the JD that failed with no_results: ten groups ANDed, two of them soft skills.
const FULL_STACK_PLAN = {
  primary_keywords: '(HTML5 OR HTML) AND (CSS3 OR CSS) AND (JavaScript OR JS) AND (Angular OR React) AND (Node.js OR NodeJS OR Node) '
    + 'AND (MySQL OR PostgreSQL) AND Git AND ("API security" OR authentication OR authorization) AND "Problem-solving" AND "Communication skills"',
  narrowed_keywords: '', use_narrowed: false, locations: [],
};

test('Boolean strings split on top-level AND only', () => {
  assert.deepEqual(C.splitTopLevel('(A OR B) AND "x AND y" AND C', 'AND'), ['(A OR B)', '"x AND y"', 'C']);
  assert.deepEqual(C.splitTopLevel('(A AND (B OR C)) AND D', 'AND'), ['(A AND (B OR C))', 'D']);
  assert.deepEqual(C.splitTopLevel('Python OR Java', 'AND'), ['Python OR Java']);
  assert.deepEqual(C.splitTopLevel('"Teamwork" OR "Team player"', 'OR'), ['"Teamwork"', '"Team player"']);
  assert.deepEqual(C.splitTopLevel('', 'AND'), []);
});

test('only groups made entirely of soft skills are soft', () => {
  for (const g of ['"Problem-solving"', '("Problem-solving")', '"Communication skills"', '(("Teamwork" OR "Team player"))', '(Leadership)']) {
    assert.equal(C.isSoftGroup(g), true, g);
  }
  for (const g of ['Git', '(Node.js OR Node)', '(Python OR "Problem-solving")', '("API security" OR authentication)', '"Communication protocols"', '(A) AND (B)']) {
    assert.equal(C.isSoftGroup(g), false, g);
  }
});

test('the failing JD: soft-skill groups are removed, then each step is broader than the last', () => {
  const levels = C.searchLevels(FULL_STACK_PLAN);
  assert.equal(levels.length, 4);
  assert.ok(!levels.some((q) => /Problem-solving|Communication skills/.test(q)), 'a soft skill reached the search');
  assert.equal(levels[0], '(HTML5 OR HTML) AND (CSS3 OR CSS) AND (JavaScript OR JS) AND (Angular OR React) AND (Node.js OR NodeJS OR Node) '
    + 'AND (MySQL OR PostgreSQL) AND Git AND ("API security" OR authentication OR authorization)');
  assert.equal(levels[1], '(HTML5 OR HTML) AND (CSS3 OR CSS) AND (JavaScript OR JS) AND (Angular OR React) AND (Node.js OR NodeJS OR Node)');
  assert.equal(levels[2], '(HTML5 OR HTML) AND (CSS3 OR CSS) AND (JavaScript OR JS)');
  assert.equal(levels[3], '(HTML5 OR HTML) AND (CSS3 OR CSS)');
  for (let i = 1; i < levels.length; i++) assert.ok(levels[i].length < levels[i - 1].length);
});

test('cities are the first thing dropped', () => {
  const levels = C.searchLevels({ ...FULL_STACK_PLAN, locations: ['Chennai', 'Coimbatore'] });
  assert.match(levels[0], /\) AND \("Chennai" OR "Coimbatore"\)$/);
  assert.ok(!/Chennai/.test(levels[1]));
  assert.equal(levels[1].split(' AND ').length, 8);          // all technical groups, no cities
  assert.equal(levels.length, 5);
});

test('a short plan has a single step, and steps never repeat', () => {
  assert.deepEqual(C.searchLevels({ primary_keywords: 'Python AND Django' }), ['Python AND Django']);
  assert.deepEqual(C.searchLevels({ primary_keywords: 'Python' }), ['Python']);
  assert.equal(new Set(C.searchLevels(FULL_STACK_PLAN)).size, 4);
  assert.deepEqual(C.searchLevels({ primary_keywords: '' }), []);
});

test('a plan of only soft skills is not stripped to nothing', () => {
  assert.deepEqual(C.searchLevels({ primary_keywords: '"Teamwork" AND "Leadership"' }), ['"Teamwork" AND "Leadership"']);
});

test('the url follows the chosen step and clamps out-of-range steps', () => {
  const kw = (level) => new URL(C.buildSearchUrl(FULL_STACK_PLAN, 2, level)).searchParams.get('keywords');
  assert.equal(kw(0), C.searchLevels(FULL_STACK_PLAN)[0]);
  assert.equal(kw(2), '(HTML5 OR HTML) AND (CSS3 OR CSS) AND (JavaScript OR JS)');
  assert.equal(kw(99), C.searchLevels(FULL_STACK_PLAN)[3]);
  assert.equal(kw(undefined), kw(0));
  assert.equal(new URL(C.buildSearchUrl(FULL_STACK_PLAN, 2, 1)).searchParams.get('page'), '2');
});

// -- candidates are taken only with an email ---------------------------------------------------------------------------

test('the search can be limited to 1st-degree connections, the only people who share an email', () => {
  const plan = { primary_keywords: 'Python AND Django' };
  const limited = new URL(C.buildSearchUrl(plan, 2, 0, { firstDegreeOnly: true }));
  assert.equal(limited.searchParams.get('network'), '["F"]');
  assert.equal(limited.searchParams.get('page'), '2');
  assert.equal(limited.searchParams.get('keywords'), 'Python AND Django');
  assert.equal(new URL(C.buildSearchUrl(plan, 2, 0)).searchParams.has('network'), false);
  assert.equal(new URL(C.buildSearchUrl(plan, 2, 0, { firstDegreeOnly: false })).searchParams.has('network'), false);
});

test('only people who could share an email are worth opening', () => {
  assert.equal(C.canShareEmail({ connection_degree: '1st' }), true);
  assert.equal(C.canShareEmail({ connection_degree: '2nd' }), false);
  assert.equal(C.canShareEmail({ connection_degree: '3rd+' }), false);
  assert.equal(C.canShareEmail({ connection_degree: '' }), true);        // unknown: try rather than lose them
  assert.equal(C.canShareEmail({}), true);
  assert.equal(C.canShareEmail(null), true);
});

test('progress text while contact details are read', () => {
  assert.equal(C.stageLabel('contacts', 2), 'Checking contact details on page 2\u2026');
  assert.equal(C.stageLabel('contacts'), 'Checking contact details\u2026');
});
