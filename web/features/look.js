/* look: Theta's look on every device (server: GET/POST /api/look {accent, dot, opening}). The accent color is the
   --accent CSS variable; the globe's dots and the opening are ThetaOrb's own settings (kept on this phone too).
   Theta.applyLook(look) applies one (the intro's "Make it yours" card uses it); Settings > General gets
   "Theme color". DOM nodes only. */
(() => {
  "use strict";
  const T = window.Theta;
  if (!T) return;
  const {el} = T;
  const ACCENTS = [["Sky", "#4fd3ff"], ["Violet", "#a78bfa"], ["Mint", "#4ade80"], ["Amber", "#fbbf24"], ["Rose", "#fb7185"], ["White", "#f4f4f5"]];
  const css = document.createElement("style");
  css.textContent = `
.look-sw { display: flex; gap: 10px; flex-wrap: wrap; }
.look-sw button { width: 30px; height: 30px; border-radius: 50%; border: 2px solid transparent; box-shadow: inset 0 0 0 2px #141414; }
.look-sw button.on { border-color: #fff; }
`;
  document.head.append(css);

  function applyLook(l, save) {
    if (!l) return;
    if (l.accent) { document.documentElement.style.setProperty("--accent", l.accent); T.store("theta:accent", l.accent); paint(l.accent); }
    if (l.dot && window.ThetaOrb && ThetaOrb.shape !== l.dot) ThetaOrb.setShape(l.dot);
    if (l.opening) T.store("theta:opening", l.opening);
    if (save && !T.state.demo) T.post("/api/look", l).catch(() => {});
  }
  T.applyLook = applyLook;
  const local = T.store("theta:accent"); if (local) document.documentElement.style.setProperty("--accent", local);

  // Settings > General > Theme color
  const g = T.settings("Theme", "general");
  const row = el("div", "row-set"), tx = el("div", "txt"), sw = el("div", "look-sw");
  tx.append(el("b", null, "Theme color"), el("span", null, "Buttons, switches and highlights."));
  const btns = ACCENTS.map(([n, c]) => {
    const b = el("button"); b.type = "button"; b.style.background = c; b.setAttribute("aria-label", n); b.title = n;
    b.addEventListener("click", () => { applyLook({accent: c}, true); T.toast(n + "."); });
    sw.append(b); return [c, b];
  });
  function paint(cur) { for (const [c, b] of btns) b.classList.toggle("on", c === cur); }
  paint(local || "#4fd3ff");
  row.append(tx, sw); g.append(row);

  // Settings > General's Dots and Opening (app.js) save on this phone; keep the server's copy in step
  for (const [id, k] of [["set-dot", "dot"], ["set-opening", "opening"]]) {
    const n = document.getElementById(id);
    if (n) n.addEventListener("change", () => { if (!T.state.demo) T.post("/api/look", {[k]: n.value}).catch(() => {}); });
  }

  // the server's look wins once signed in (set on another device, or in the intro)
  let synced = false;
  const sync = async () => {
    if (synced || T.state.demo || !T.state.authed) return;
    synced = true;
    try { const l = await T.api("/api/look"); applyLook(l, false); } catch (e) { synced = false; }
  };
  const t = setInterval(() => { sync(); if (synced) clearInterval(t); }, 700);
  setTimeout(() => clearInterval(t), 30000);
})();
