/* live: Theta's screen. Shows the real page in Theta's own browser on the server (server/live.py) and lets you
   drive it: tap the picture to tap the page, swipe to scroll, type into the focused field, Back and Reload.
   Opens from the "..." menu ("Theta's screen") or when the status line of a turn that used the browser is tapped
   (Theta.emit("activity-tap", {message, live: true}) from app.js). Frames refresh ~3x a second while the sheet is
   showing and stop when it's hidden. The server still refuses typing into passwords and anything that submits,
   buys, sends or deletes. DOM nodes only, never innerHTML. Demo mode shows a sample frame. */
(() => {
  "use strict";
  const T = window.Theta;
  if (!T) return;
  const EVERY = 333, STATE_EVERY = 2000;

  const style = document.createElement("style");
  style.textContent = `
.live-banner { font-size: 13.5px; line-height: 1.35; color: var(--muted); background: #1d1d1d; border: 1px solid var(--line);
  border-radius: 14px; padding: 10px 12px; margin: 4px 0 10px; }
.live-url { display: flex; gap: 8px; align-items: center; margin-bottom: 10px; }
.live-url input { flex: 1; min-width: 0; background: #2a2a2a; border: 0; border-radius: 12px; padding: 9px 12px; font-size: 15px; color: var(--text); }
.live-title { font-size: 13px; color: var(--muted); margin: -4px 2px 8px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.live-screen { position: relative; width: 100%; max-width: 390px; margin: 0 auto; aspect-ratio: 390 / 844; max-height: 62vh;
  border-radius: 18px; overflow: hidden; background: #0d0d0d; border: 1px solid var(--line); touch-action: none; }
.live-screen img { width: 100%; height: 100%; object-fit: contain; display: block; user-select: none; -webkit-user-drag: none; }
.live-empty { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; text-align: center;
  padding: 24px; color: var(--muted); font-size: 15px; line-height: 1.4; }
.live-dot { position: absolute; width: 26px; height: 26px; margin: -13px 0 0 -13px; border-radius: 50%; border: 2px solid var(--accent);
  pointer-events: none; animation: live-ping .5s ease-out forwards; }
@keyframes live-ping { from { transform: scale(.5); opacity: 1; } to { transform: scale(1.4); opacity: 0; } }
.live-bar { display: flex; gap: 8px; align-items: center; margin-top: 12px; flex-wrap: wrap; }
.live-bar .live-keys { flex: 1 1 160px; min-width: 0; background: #2a2a2a; border: 0; border-radius: 12px; padding: 9px 12px; font-size: 15px; color: var(--text); }
.live-note { min-height: 18px; margin-top: 8px; font-size: 13.5px; color: var(--muted); }
.live-note.bad { color: var(--danger); }
`;
  document.head.append(style);

  const {root, body} = T.sheet("live", "Theta's screen", () => start());
  const banner = T.el("div", "live-banner", "This is Theta's own browser on the server. You're in control while this is open.");
  const urlForm = T.el("form", "live-url"), url = T.el("input");
  url.type = "url"; url.inputMode = "url"; url.placeholder = "No page open"; url.setAttribute("aria-label", "Page address");
  url.autocomplete = "off"; url.spellcheck = false;
  urlForm.append(url);
  const title = T.el("div", "live-title");
  const screen = T.el("div", "live-screen"), img = T.el("img"), empty = T.el("div", "live-empty", "Theta isn't using its browser right now.");
  img.alt = "Theta's browser"; img.hidden = true; img.draggable = false;
  screen.append(img, empty);
  const bar = T.el("form", "live-bar");
  const back = T.el("button", "btn-dark", "Back"), reload = T.el("button", "btn-dark", "Reload");
  back.type = reload.type = "button";
  const keys = T.el("input", "live-keys"); keys.placeholder = "Type into the page"; keys.setAttribute("aria-label", "Type into the page");
  keys.autocomplete = "off"; keys.enterKeyHint = "send";
  const typeBtn = T.el("button", "btn-dark", "Type"), enter = T.el("button", "btn-dark", "Enter");
  enter.type = "button";
  bar.append(back, reload, keys, typeBtn, enter);
  const note = T.el("div", "live-note"); note.setAttribute("role", "status");
  body.append(banner, urlForm, title, screen, bar, note);

  let running = false, timer = 0, stateTimer = 0, objUrl = null, active = false, busy = false, demoShown = false;
  const visible = () => !root.hidden && document.visibilityState === "visible";
  const say = (t, bad) => { note.textContent = t || ""; note.classList.toggle("bad", !!bad); };
  function showEmpty(on) { empty.hidden = !on; img.hidden = on; if (on) { url.value = ""; title.textContent = ""; } }
  function setState(s) {
    active = !!(s && s.active);
    if (!active) { showEmpty(true); return; }
    if (document.activeElement !== url) url.value = s.url || "";
    title.textContent = s.title || "";
  }

  // a sample frame for demo mode: drawn here, so nothing is fetched
  function demoFrame() {
    const c = document.createElement("canvas"); c.width = 390; c.height = 844;
    const g = c.getContext("2d");
    g.fillStyle = "#f0f0f2"; g.fillRect(0, 0, 390, 844);
    g.fillStyle = "#fdfdff"; g.fillRect(24, 140, 342, 260);
    g.fillStyle = "#111"; g.font = "bold 28px -apple-system, system-ui, sans-serif"; g.fillText("Example Domain", 44, 196);
    g.font = "16px -apple-system, system-ui, sans-serif"; g.fillStyle = "#333";
    ["This domain is for use in documentation", "examples without needing permission.", "Avoid use in operations."]
      .forEach((l, i) => g.fillText(l, 44, 240 + i * 24));
    g.fillStyle = "#3858c8"; g.fillText("Learn more", 44, 350);
    g.fillRect(44, 354, 82, 1);
    return c.toDataURL("image/jpeg", 0.7);
  }

  async function refreshState() {
    try {
      const r = await T.http("/api/live", {cache: "no-store"});
      if (r.ok) setState(await r.json());
    } catch (e) {}
  }

  async function frame() {
    if (!running || !visible()) { stop(); return; }
    try {
      const r = await T.http("/api/live/frame.jpg?ts=" + Date.now(), {cache: "no-store"});
      if (r.status === 404) { active = false; showEmpty(true); }
      else if (r.status === 401) { stop(); say("Sign in again to see Theta's screen.", true); return; }
      else if (r.ok) {
        const blob = await r.blob();
        const next = URL.createObjectURL(blob), old = objUrl;
        objUrl = next; img.src = next; showEmpty(false); active = true;
        if (old) setTimeout(() => URL.revokeObjectURL(old), 1000); // after the new one has painted
      }
    } catch (e) {}
    if (running) timer = setTimeout(frame, EVERY);
  }

  function start() {
    say("");
    if (T.state.demo) {
      if (!demoShown) { img.src = demoFrame(); demoShown = true; }
      showEmpty(false); active = true; url.value = "https://example.com/"; title.textContent = "Example Domain (demo)";
      return;
    }
    if (running) return;
    running = true;
    refreshState();
    stateTimer = setInterval(() => { if (visible()) refreshState(); }, STATE_EVERY);
    frame();
  }
  function stop() {
    running = false; clearTimeout(timer); clearInterval(stateTimer); timer = stateTimer = 0;
  }

  async function act(body, what) {
    if (T.state.demo) { say("Demo: on your server this " + what + " on Theta's page."); return; }
    if (busy) return;
    busy = true;
    try {
      const r = await T.http("/api/live/act", {method: "POST", headers: {"content-type": "application/json"}, body: JSON.stringify(body)});
      let j = {}; try { j = await r.json(); } catch (e) {}
      if (r.ok && j.ok) { say(""); setState(Object.assign({active: true}, j)); }
      else if (r.status === 404) { setState({active: false}); say(j.error || "Theta isn't using its browser right now."); }
      else say(j.error || "That didn't work.", true);
    } catch (e) { say("Couldn't reach Theta's browser.", true); }
    finally { busy = false; clearTimeout(timer); if (running) timer = setTimeout(frame, 60); }
  }

  // tap = tap; a vertical swipe = scroll
  let down = null;
  screen.addEventListener("pointerdown", e => { if (!img.hidden) { down = {x: e.clientX, y: e.clientY}; screen.setPointerCapture(e.pointerId); } });
  screen.addEventListener("pointerup", e => {
    if (!down || img.hidden) return;
    const box = img.getBoundingClientRect(), dy = e.clientY - down.y, dx = e.clientX - down.x;
    const start0 = down; down = null;
    if (Math.abs(dy) > 18 && Math.abs(dy) > Math.abs(dx)) { act({type: "scroll", dy: Math.max(-3, Math.min(3, -dy / box.height * 1.5))}, "scrolls"); return; }
    const x = (start0.x - box.left) / box.width, y = (start0.y - box.top) / box.height;
    if (x < 0 || x > 1 || y < 0 || y > 1) return;
    const dot = T.el("span", "live-dot"); dot.style.left = (start0.x - screen.getBoundingClientRect().left) + "px";
    dot.style.top = (start0.y - screen.getBoundingClientRect().top) + "px"; screen.append(dot); setTimeout(() => dot.remove(), 520);
    act({type: "tap", x: +x.toFixed(4), y: +y.toFixed(4)}, "taps");
  });
  screen.addEventListener("pointercancel", () => { down = null; });
  back.addEventListener("click", () => act({type: "back"}, "goes back"));
  reload.addEventListener("click", () => act({type: "reload"}, "reloads"));
  enter.addEventListener("click", () => act({type: "key", key: "Enter"}, "presses Enter"));
  bar.addEventListener("submit", e => {
    e.preventDefault();
    const t = keys.value; if (!t) return;
    keys.value = ""; act({type: "type", text: t}, "types");
  });
  urlForm.addEventListener("submit", e => {
    e.preventDefault();
    const u = url.value.trim(); if (!u) return;
    url.blur(); act({type: "goto", url: u}, "opens the page");
  });

  new MutationObserver(() => { if (root.hidden) stop(); else start(); }).observe(root, {attributes: true, attributeFilter: ["hidden"]});
  document.addEventListener("visibilitychange", () => { if (!visible()) stop(); else if (!root.hidden) start(); });

  T.menu("Theta's screen", "i-image", "live");
  T.on("activity-tap", d => { if (d && d.live) T.open("live"); });
})();
