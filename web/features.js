/* Loads each feature's screen from web/features/. A missing file is skipped. Each one uses window.Theta (app.js). */
(() => {
  "use strict";
  const FEATURES = ["calendar", "routines", "calls", "browser", "media", "passkeys"];
  // paused (stage 5 B, kept in commit 75eb145): FEATURES.push("activity", "live");
  FEATURES.push("cards"); // the card kit
  FEATURES.push("onboarding"); // the first-run intro, in the chat
  FEATURES.push("contacts"); // Settings > General > Contacts
  FEATURES.push("approvals"); // approval cards, Settings > Security > Approvals
  for (const f of FEATURES) {
    const s = document.createElement("script");
    s.src = "/static/features/" + f + ".js"; s.async = false;
    s.onerror = () => s.remove();
    document.body.append(s);
  }
})();
