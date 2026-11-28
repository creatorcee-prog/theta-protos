/* look: Theta's look on every device (server: GET/POST /api/look {accent, style, dot, opening}). The accent color is
   the --accent CSS variable and tints the globe; the style, dots and opening are ThetaOrb's (kept on this phone too).
   T.lookRow(key, ...) is a row of live mini-globes to swipe through and tap (the intro's "Make it yours" card and
   Settings > General > Theta's look both use it), so each choice is seen, not guessed from a name.
   T.applyLook(look) applies one. DOM nodes only. */
(() => {
  "use strict";
  const T = window.Theta;
  if (!T) return;
  const {el} = T;
  const OPTS = {
    accent: [["Sky", "#4fd3ff"], ["Violet", "#a78bfa"], ["Mint", "#4ade80"], ["Amber", "#fbbf24"], ["Rose", "#fb7185"], ["White", "#f4f4f5"]],
    style: [["Urchin", "urchin"], ["Precision", "precision"], ["Lumen", "lumen"], ["Flow", "flow"], ["Signal", "signal"], ["Rings", "rings"],
      ["Ribbons", "ribbons"], ["Horizon", "horizon"], ["Plasma", "plasma"], ["Liquid", "liquid"], ["Nebula", "nebula"]],  // the last five: light in glass (orb8.js)
    dot: [["Circles", "circle"], ["Stars", "star"], ["Diamonds", "diamond"], ["Hexagons", "hexagon"], ["Triangles", "triangle"], ["Squares", "square"], ["Pentagons", "pentagon"]],
    opening: [["Converge", "converge"], ["Signal", "signal"]],
  };
  const css = document.createElement("style");
  css.textContent = `
.lk-row { display: flex; gap: 10px; overflow-x: auto; scroll-snap-type: x proximity; scrollbar-width: none; padding: 2px 2px 4px; margin: 0 -2px; }
.lk-row::-webkit-scrollbar { display: none; }
.lk-tile { flex: none; width: 86px; scroll-snap-align: start; display: grid; justify-items: center; gap: 4px; padding: 6px 4px 8px; border-radius: 18px;
  background: #1a1a1c; border: 2px solid transparent; color: var(--muted); font-size: 0.7647rem; }
.lk-tile.on { border-color: var(--accent); color: var(--text); }
.lk-tile canvas { width: 70px; height: 70px; display: block; }
.lk-tile .lk-dot { width: 46px; height: 46px; border-radius: 50%; margin: 12px; }
.lk-sec { display: block; color: var(--muted); font-size: 0.7647rem; margin: 12px 2px 6px; text-transform: uppercase; letter-spacing: .03em; }
`;
  document.head.append(css);

  const cur = () => ({accent: T.store("theta:accent") || "#4fd3ff", style: (window.ThetaOrb && ThetaOrb.style) || "urchin",
                      dot: (window.ThetaOrb && ThetaOrb.shape) || "circle", opening: T.store("theta:opening") || "converge"});

  // one live preview per option; the other three choices come from get() so every tile shows the whole look
  function lookRow(key, value, onPick, get) {
    const row = el("div", "lk-row"); row.setAttribute("role", "radiogroup");
    const tiles = [];
    for (const [label, v] of OPTS[key] || []) {
      const b = el("button", "lk-tile" + (v === value ? " on" : "")); b.type = "button";
      b.setAttribute("role", "radio"); b.setAttribute("aria-checked", String(v === value)); b.setAttribute("aria-label", label);
      const cv = el("canvas"); cv.setAttribute("aria-hidden", "true");
      b.append(cv, el("span", null, label)); row.append(b);
      let orb = null;
      const opt = () => { const l = Object.assign({}, get ? get() : cur(), {[key]: v}); return {color: l.accent, style: l.style, shape: l.dot}; };
      if (window.ThetaOrb) orb = ThetaOrb.mount(cv, Object.assign({dots: 160, scale: 1.3, glow: 0.9, maxDpr: 2}, opt()));
      if (orb && key === "opening") {  // play the opening over and over while it's on screen
        const play = () => { if (!cv.isConnected) { clearInterval(iv); return; } if (cv.getBoundingClientRect().width) orb.opening(v, null, 1.2); };
        const iv = setInterval(play, 4200); setTimeout(play, 200);
      }
      b.addEventListener("click", () => {
        tiles.forEach(t => { t.b.classList.toggle("on", t.b === b); t.b.setAttribute("aria-checked", String(t.b === b)); });
        onPick(v);
      });
      tiles.push({b, orb, opt});
    }
    row.refresh = () => { for (const t of tiles) if (t.orb) { Object.assign(t.orb.opt, t.opt()); t.orb._lk = null; } };
    return row;
  }
  T.lookRow = lookRow;
  T.lookOptions = OPTS;

  function applyLook(l, save) {
    if (!l) return;
    if (l.accent) { document.documentElement.style.setProperty("--accent", l.accent); T.store("theta:accent", l.accent); if (window.ThetaOrb && ThetaOrb.setColor) ThetaOrb.setColor(l.accent); }
    if (l.style && window.ThetaOrb && ThetaOrb.setStyle) ThetaOrb.setStyle(l.style);
    if (l.dot && window.ThetaOrb && ThetaOrb.shape !== l.dot) ThetaOrb.setShape(l.dot);
    if (l.opening) T.store("theta:opening", l.opening);
    if (save && !T.state.demo) T.post("/api/look", l).catch(() => {});
    document.dispatchEvent(new CustomEvent("theta:look"));
  }
  T.applyLook = applyLook;
  const local = T.store("theta:accent"); if (local) document.documentElement.style.setProperty("--accent", local);

  // Settings > General > Theta's look: the same live rows (the old dot and opening menus stay for app.js, hidden)
  const dotSel = document.getElementById("set-dot"), grp = dotSel && dotSel.closest(".group");
  if (grp) {
    for (const id of ["set-dot", "set-opening"]) { const r = document.getElementById(id); if (r && r.closest(".row-set")) r.closest(".row-set").hidden = true; }
    const box = el("div"); box.style.padding = "4px 14px 10px";
    const rows = [];
    const build = () => {
      const l = cur(); box.replaceChildren(); rows.length = 0;
      for (const [k, label] of [["accent", "Color"], ["style", "Style"], ["dot", "Dots"], ["opening", "Opening"]]) {
        const row = lookRow(k, l[k], v => {
          applyLook({[k]: v}, true);
          if (k === "dot" && dotSel) dotSel.value = v;
          const op = document.getElementById("set-opening"); if (k === "opening" && op) op.value = v;
          rows.forEach(r => r.refresh());
        }, cur);
        rows.push(row); box.append(el("span", "lk-sec", label), row);
      }
    };
    grp.prepend(box);
    let built = false;
    T.on("settings-page", d => { if (d && d.page === "general" && !built) { built = true; build(); } });
    document.addEventListener("theta:look", () => rows.forEach(r => r.refresh()));
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
