// popup.js — status panel. Sourcing itself is started and reviewed in SkillMate; the popup shows whether
// SkillMate and LinkedIn are ready, follows the current run, and can stop it.

(function () {
  'use strict';

  const cfg = self.SMLinkedinConfig;
  const Core = self.SkillmateLinkedinCore;
  const $ = (id) => document.getElementById(id);

  function setBadge(el, text, kind) {
    el.textContent = text;
    el.className = `badge badge--${kind}`;
  }

  function send(type) {
    return new Promise((resolve) => {
      try {
        chrome.runtime.sendMessage({ type }, (res) => resolve(chrome.runtime.lastError ? null : res));
      } catch (e) { resolve(null); }
    });
  }

  // ── SkillMate ─────────────────────────────────────────────────────────────────
  $('version').textContent = `v${chrome.runtime.getManifest().version}`;
  $('sm-url').textContent = cfg.SKILLMATE_URL;

  async function refreshSkillmate() {
    const tabs = await chrome.tabs.query({ url: `${cfg.SKILLMATE_URL.replace(/\/$/, '')}/*` });
    if (tabs.length) setBadge($('sm-badge'), 'Open in a tab', 'success');
    else setBadge($('sm-badge'), 'Not open', 'muted');
  }

  $('btn-open-sm').addEventListener('click', async () => {
    const base = cfg.SKILLMATE_URL.replace(/\/$/, '');
    const [tab] = await chrome.tabs.query({ url: `${base}/*` });
    if (tab) {
      await chrome.tabs.update(tab.id, { active: true, url: tab.url.includes('/hiring') ? undefined : `${base}/hiring` });
      await chrome.windows.update(tab.windowId, { focused: true });
    } else {
      await chrome.tabs.create({ url: `${base}/hiring` });
    }
    window.close();
  });

  // ── LinkedIn ──────────────────────────────────────────────────────────────────
  $('btn-check').addEventListener('click', async () => {
    const btn = $('btn-check');
    btn.disabled = true;
    setBadge($('li-badge'), 'Checking…', 'muted');
    $('li-msg').textContent = 'Opening LinkedIn in a background tab…';
    const res = await send('LI_POPUP_CHECK_LOGIN');
    btn.disabled = false;
    if (res?.loggedIn) {
      setBadge($('li-badge'), 'Logged in', 'success');
      $('li-msg').textContent = 'Ready. SkillMate uses LinkedIn when Naukri can’t be used.';
    } else {
      setBadge($('li-badge'), 'Not logged in', 'error');
      $('li-msg').textContent = Core.stageLabel('error', null, null, 'not_logged_in');
    }
  });

  $('btn-open-li').addEventListener('click', () => {
    chrome.tabs.create({ url: cfg.LINKEDIN_HOME_URL });
    window.close();
  });

  // ── Current run ───────────────────────────────────────────────────────────────
  function renderRun(status) {
    const job = status?.job;
    const active = !!job;
    $('run-active').classList.toggle('hidden', !active);
    $('run-idle').classList.toggle('hidden', active);

    if (active) {
      setBadge($('run-dot'), 'Running', 'live');
      $('run-stage').textContent = Core.stageLabel(job.stage || 'searching', job.page, job.pageTo);
      // Progress toward 5 shortlisted (the run stops early once they're found).
      const found = Math.min(5, job.shortlisted || 0);
      $('run-bar').style.width = `${Math.round((found / 5) * 100)}%`;
      const extra = job.phase === 'prefetch' ? ' · 5 found, reading an extra page for next time' : '';
      $('run-meta').textContent = `${found} of 5 found${extra} · started ${new Date(job.startedAt).toLocaleTimeString()}`;
      return;
    }

    setBadge($('run-dot'), 'Idle', 'muted');
    const last = status?.last;
    const lastEl = $('run-last');
    if (last) {
      const when = new Date(last.at).toLocaleTimeString();
      lastEl.textContent = last.stage === 'done'
        ? `Last run: ${last.shortlisted ?? 0} match(es) added from ${last.profiles ?? 0} profile(s) at ${when}.`
        : `Last run (${when}): ${Core.stageLabel('error', null, null, last.reason)}`;
      lastEl.classList.remove('hidden');
    } else {
      lastEl.classList.add('hidden');
    }
  }

  $('btn-stop').addEventListener('click', async () => {
    $('btn-stop').disabled = true;
    await send('LI_POPUP_STOP');
    $('btn-stop').disabled = false;
    renderRun(await send('LI_POPUP_STATUS'));
  });

  async function tick() {
    renderRun(await send('LI_POPUP_STATUS'));
    refreshSkillmate();
  }
  tick();
  setInterval(tick, 2000);
})();
