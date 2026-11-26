/* Loads each feature's screen from web/features/. A missing file is skipped. Each one uses window.Theta (app.js). */
(() => {
  "use strict";
  const FEATURES = ["calendar", "routines", "calls", "browser", "media"];
  for (const f of FEATURES) {
    const s = document.createElement("script");
    s.src = "/static/features/" + f + ".js"; s.async = false;
    s.onerror = () => s.remove();
    document.body.append(s);
  }
})();
