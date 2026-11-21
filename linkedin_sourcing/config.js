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
  root.SMLinkedinConfig = {
    // The SkillMate web app. The bridge only talks to pages on exactly this origin.
    SKILLMATE_URL: 'http://localhost:3000',
    // Origins SkillMate's API may live on. The SkillMate login token is only ever sent here.
    SKILLMATE_API_ORIGINS: ['http://localhost:3000', 'http://localhost:8000'],
    // Opened in a background tab to check the LinkedIn login. Opens no profile.
    LINKEDIN_HOME_URL: 'https://www.linkedin.com/feed/',
    // Take a LinkedIn candidate only if they have an email. LinkedIn cards never show one, so each candidate's
    // contact dialog is opened and only the people whose dialog gives an email are sent to SkillMate. LinkedIn shares
    // an email only with 1st-degree connections, so the search is limited to them and 2nd/3rd-degree people are
    // skipped without opening their profile. Set false to send every card instead (emails are then read at Select).
    EMAIL_ONLY: true,
    // Open the working tab in the foreground. Leave false normally; set true if LinkedIn shows empty cards because
    // it doesn't finish rendering in a background tab (the tab then takes focus for each run and contact read).
    WORK_TAB_ACTIVE: false,
    // Seconds to wait between two result pages (a random value in this range), and before the next profile
    // when contact details are read. LinkedIn limits accounts that read quickly, so keep these generous.
    PAGE_PAUSE_SECONDS: [6, 14],
    PROFILE_PAUSE_SECONDS: [3, 7],
  };
})(typeof self !== 'undefined' ? self : this);
