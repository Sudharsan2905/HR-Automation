// config.js — the only settings this extension has. Loaded by background.js (importScripts),
// the SkillMate bridge, and the popup.
//
// To point at a live SkillMate:
//   1. change SKILLMATE_URL (and SKILLMATE_API_ORIGINS if the API lives elsewhere) here;
//   2. put the same origins in manifest.json — "host_permissions" and the bridge's
//      content_scripts "matches" (Chrome can't read this file from the manifest);
//   3. reload the extension at chrome://extensions.

(function (root) {
  'use strict';
  root.SMConfig = {
    // The SkillMate web app. The bridge only talks to pages on exactly this origin.
    SKILLMATE_URL: 'http://localhost:3000',
    // Origins SkillMate's API may live on. The SkillMate login token is only ever sent here.
    SKILLMATE_API_ORIGINS: ['http://localhost:3000', 'http://localhost:8000'],
    // Opened in a background tab to check the ResDex login. Opens no profile, spends no credit.
    RESDEX_HOME_URL: 'https://resdex.naukri.com/',
    // ResDex's search form. Each run opens it, fills in the JD's search and clicks Search.
    RESDEX_SEARCH_URL: 'https://resdex.naukri.com/v3?activeTab=advSrch',
  };
})(typeof self !== 'undefined' ? self : this);
