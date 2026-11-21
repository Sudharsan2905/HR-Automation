// core.js — pure helpers for the SkillMate Sourcing extension.
//
// Loaded by the SkillMate bridge, the Naukri content script, background.js (importScripts)
// and the popup. Also `require`-able from Node for unit tests
// (tests/core.test.js, run with `node --test tests/`). No chrome.* calls here.

(function (root) {
  'use strict';

  const REQUEST_TYPES = [
    'SKILLMATE_PING',
    'SKILLMATE_CHECK_LOGIN',
    'SKILLMATE_SOURCE',
    'SKILLMATE_REVEAL',
    'SKILLMATE_CANCEL',
  ];

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
      && data.source === 'skillmate-page'
      && typeof data.type === 'string'
      && REQUEST_TYPES.includes(data.type)
      && typeof data.requestId === 'string';
  }

  // The SkillMate token is only ever sent to an API base whose origin is on the allow-list.
  function isAllowedApiBase(apiBase, allowedOrigins) {
    const o = originOf(apiBase);
    return !!o && (allowedOrigins || []).map(originOf).includes(o);
  }

  // Naukri bounces a logged-out recruiter to a login page. Search/results pages never match.
  function isResdexLoginUrl(url) {
    let u;
    try { u = new URL(url); } catch (e) { return false; }
    const host = u.hostname.toLowerCase();
    if (!(host === 'naukri.com' || host.endsWith('.naukri.com'))) return false;
    if (host.startsWith('login.')) return true;
    return /\/(n?login|logout)(\/|\.|\?|$)|session-?expired/i.test(u.pathname + u.search);
  }

  function isCaptchaText(text) {
    return /captcha|unusual (traffic|activity)|are you a robot/i.test(text || '');
  }

  function apiUrl(apiBase, path) {
    return String(apiBase).replace(/\/+$/, '') + '/' + String(path).replace(/^\/+/, '');
  }

  const ERROR_TEXT = {
    not_logged_in: 'Login with Naukri ResDex to continue extraction.',
    captcha: 'Stopped: Naukri is showing a CAPTCHA',
    no_results: 'Stopped: no ResDex results on the open tab',
    search_not_configured: 'Stopped: open a ResDex results page first',
    search_form_not_found: 'Stopped: could not fill the ResDex search form (the page layout may have changed)',
    search_failed: 'Stopped: ResDex did not run the search — check the ResDex tab',
    search_changed: 'Stopped: the ResDex search was changed mid-run',
    skillmate_auth: 'Stopped: SkillMate session expired — refresh SkillMate',
    cancelled: 'Stopped by you',
  };

  // One line describing a run's progress, for the popup.
  function stageLabel(stage, page, pageTo, reason) {
    switch (stage) {
      case 'searching': return 'Searching ResDex for this JD…';
      case 'scraping': return page ? `Reading ResDex page ${page}…` : 'Reading ResDex results…';
      case 'screening': return page ? `SkillMate is screening page ${page}…` : 'SkillMate is screening…';
      case 'done': return 'Done — matches are in SkillMate';
      case 'error': return ERROR_TEXT[reason] || `Stopped: ${reason || 'unknown error'}`;
      default: return 'Idle';
    }
  }

  // The recruiter's most recently used ResDex tab (not a login or profile-preview page), or null.
  function pickResdexTab(tabs) {
    const usable = (tabs || []).filter((t) => {
      let u;
      try { u = new URL(t.url); } catch (e) { return false; }
      return u.hostname === 'resdex.naukri.com' && !u.pathname.includes('/preview') && !isResdexLoginUrl(t.url);
    });
    usable.sort((a, b) => (b.lastAccessed || 0) - (a.lastAccessed || 0));
    return usable[0] || null;
  }

  // ResDex pages can carry hidden password inputs (dialogs); only a visible one means a login form.
  function hasVisibleLoginForm(passwordInputs) {
    return Array.from(passwordInputs || []).some(
      (el) => el.offsetParent !== null && el.getClientRects().length > 0,
    );
  }

  // The keyword string to type into ResDex for this search plan.
  function searchKeywords(plan) {
    if (!plan) return '';
    const narrowed = (plan.narrowed_keywords || '').trim();
    if (plan.use_narrowed && narrowed) return narrowed;
    return (plan.primary_keywords || '').trim();
  }

  // ResDex's search form (as opposed to a results page).
  function isResdexSearchFormUrl(url) {
    let u;
    try { u = new URL(url); } catch (e) { return false; }
    if (u.hostname !== 'resdex.naukri.com') return false;
    return /^\/v3\/?$/.test(u.pathname) || u.searchParams.get('activeTab') === 'advSrch';
  }

  const api = {
    REQUEST_TYPES, isAllowedOrigin, isPageRequest, isAllowedApiBase, isResdexLoginUrl, isCaptchaText, apiUrl,
    stageLabel, pickResdexTab, hasVisibleLoginForm, searchKeywords, isResdexSearchFormUrl,
  };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  root.SkillmateCore = api;
})(typeof self !== 'undefined' ? self : this);
