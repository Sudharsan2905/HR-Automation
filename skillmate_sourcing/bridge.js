// bridge.js — runs ONLY on the SkillMate web app (SMConfig.SKILLMATE_URL).
//
// Relays messages between the SkillMate page and background.js:
//   page ──window.postMessage({source:'skillmate-page', type, requestId, ...})──▶ bridge
//   bridge ──chrome.runtime.sendMessage({type:'MH_SKILLMATE', payload})──▶ background
//   background ──response / MH_SKILLMATE_EVENT──▶ bridge ──window.postMessage({source:'skillmate-ext'})──▶ page
//
// Only messages from this exact window and origin, with a known request type, are relayed.

(function () {
  'use strict';

  const LOG = '[SkillMate · bridge]';
  const Core = self.SkillmateCore;
  const cfg = self.SMConfig || {};
  if (!Core || !cfg.SKILLMATE_URL) {
    console.error(LOG, 'core.js / config.js not loaded before the bridge — check manifest order.');
    return;
  }
  if (!Core.isAllowedOrigin(location.origin, cfg.SKILLMATE_URL)) return; // not the SkillMate app

  const post = (msg) => window.postMessage({ ...msg, source: 'skillmate-ext' }, location.origin);

  // Each copy of the bridge stamps the page. When the extension is reloaded, background.js
  // injects a fresh copy into open SkillMate tabs; the old, disconnected copy then sees a newer
  // stamp and goes quiet instead of answering for an extension it can no longer reach.
  const BRIDGE_ID = Math.random().toString(36).slice(2);
  document.documentElement.dataset.smBridge = BRIDGE_ID;

  function alive() {
    try { return !!(chrome.runtime && chrome.runtime.id); } catch (e) { return false; }
  }

  function onPageMessage(event) {
    if (event.source !== window) return;
    if (!Core.isAllowedOrigin(event.origin, cfg.SKILLMATE_URL)) return;
    const data = event.data;
    if (!Core.isPageRequest(data)) return;

    // After the extension is reloaded or updated, this copy of the bridge stays in the page but
    // is cut off from the extension (chrome.runtime is gone). Say so — the page must be reloaded.
    if (!alive()) {
      if (document.documentElement.dataset.smBridge !== BRIDGE_ID) {
        window.removeEventListener('message', onPageMessage);  // a fresh bridge answers now
        return;
      }
      post({ type: 'SKILLMATE_ERROR', requestId: data.requestId, ok: false, reason: 'extension_reloaded' });
      return;
    }
    if (data.type === 'SKILLMATE_PING') {
      post({ type: 'SKILLMATE_PONG', requestId: data.requestId, version: chrome.runtime.getManifest().version });
      return;
    }
    try {
      chrome.runtime.sendMessage({ type: 'MH_SKILLMATE', payload: data }, (response) => {
        if (chrome.runtime.lastError) {
          post({ type: 'SKILLMATE_ERROR', requestId: data.requestId, ok: false, reason: chrome.runtime.lastError.message });
          return;
        }
        if (response) post({ ...response, requestId: data.requestId });
      });
    } catch (e) {
      post({ type: 'SKILLMATE_ERROR', requestId: data.requestId, ok: false, reason: e.message });
    }
  }
  window.addEventListener('message', onPageMessage);

  // Progress events pushed by background.js during a run.
  chrome.runtime.onMessage.addListener((msg) => {
    if (msg && msg.type === 'MH_SKILLMATE_EVENT' && msg.event) post(msg.event);
  });

  console.log(LOG, 'ready');
})();
