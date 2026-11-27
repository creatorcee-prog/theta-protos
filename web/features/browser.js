/* browser: Theta's own headless browser (server/browser.py). Its results come back as ordinary chat text, and
   screenshots as [image:<id>] markers that media.js renders, so this only adds a note in Settings saying whether
   web browsing is available on the server. Builds DOM nodes only; in demo mode it shows a sample note. */
(() => {
  "use strict";
  const T = window.Theta;
  if (!T) return;
  const g = T.settings("Web browsing");
  const r = T.el("div", "row-set"), t = T.el("div", "txt"), s = T.el("span", null, "Checking…");
  t.append(T.el("b", null, "Theta's browser"), s); r.append(t); g.append(r);
  const say = c => {
    s.textContent = c && c.connected
      ? "Available. Theta opens sites, reads them, fills in forms and stays signed in. Buying, booking or sending waits for your OK; passwords come only from 1Password or Bitwarden. Watch or take over from Theta's screen in the ••• menu."
      : "Not available on this server yet (it needs Playwright and Chromium; the repo's Dockerfile installs them).";
  };
  let done = false;
  async function load() {
    if (done) return;
    if (T.state.demo) { say({connected: true}); s.textContent = "Demo: " + s.textContent; done = true; return; }
    try {
      const list = await T.api("/api/connections");
      say((Array.isArray(list) ? list : []).find(c => c.id === "browser"));
      done = true;
    } catch (e) { s.textContent = "Couldn't check right now."; }
  }
  const sheet = document.getElementById("settings");
  if (sheet) {
    new MutationObserver(() => { if (!sheet.hidden) load(); }).observe(sheet, {attributes: true, attributeFilter: ["hidden"]});
    if (!sheet.hidden) load();
  }
})();
