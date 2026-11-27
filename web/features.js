/* Loads each feature's screen from web/features/. A missing file is skipped. Each one uses window.Theta (app.js). */
(() => {
  "use strict";
  const FEATURES = ["calendar", "routines", "calls", "browser", "media", "passkeys"];
  FEATURES.push("live"); // Theta's screen: watch its browser work, take over
  FEATURES.push("cards"); // the card kit
  FEATURES.push("onboarding"); // the first-run intro, in the chat
  FEATURES.push("contacts"); // Settings > General > Contacts
  FEATURES.push("approvals"); // approval cards, Settings > Security > Approvals
  FEATURES.push("models"); // Settings > General > Models
  FEATURES.push("bank"); // Settings > Apps > Bank accounts
  FEATURES.push("account", "chips", "look", "home", "chiphub"); // home: the smart stack, finds, chips and top stories // look: theme color, the globe's dots, the opening, on every device // Settings: profile, personalization, memory, usage, data; chips (skills)
  for (const f of FEATURES) {
    const s = document.createElement("script");
    s.src = "/static/features/" + f + ".js"; s.async = false;
    s.onerror = () => s.remove();
    document.body.append(s);
  }
})();
