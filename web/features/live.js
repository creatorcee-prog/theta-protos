/* live: Theta's screen (server/live.py). Three parts:
   1. While a turn uses the browser, a small live picture floats above the composer ("casting"), refreshing about
      twice a second. Tap it to open the full screen.
   2. The full screen ("Theta's screen" sheet, also in the "..." menu): the real page, sharp, ~3 frames a second.
      You're in control while it's open: tap to tap, swipe to scroll, type into the focused field, Back, Reload, an
      address bar. Double-tap zooms. If the page asks "Are you sure?", you're asked here, and only OK goes ahead.
   3. A reply from a turn that browsed shows where the browser ended up (meta.screen): a thumbnail you can tap.
   Settings > Security > Theta's browser lists the sites it's signed in to, with "Sign out everywhere".
   DOM nodes only, never innerHTML. Demo mode draws a sample page and fetches nothing. */
(() => {
  "use strict";
  const T = window.Theta;
  if (!T) return;
  const {el} = T;
  const EVERY = 333, PIP_EVERY = 500, STATE_EVERY = 2000;

  const style = document.createElement("style");
  style.textContent = `
.live-banner { font-size: 13.5px; line-height: 1.35; color: var(--muted); background: #1d1d1d; border: 1px solid var(--line);
  border-radius: 14px; padding: 10px 12px; margin: 4px 0 10px; }
.live-url { display: flex; gap: 8px; align-items: center; margin-bottom: 8px; }
.live-url input { flex: 1; min-width: 0; background: #2a2a2a; border: 0; border-radius: 12px; padding: 9px 12px; font-size: 16px; color: var(--text); }
.live-title { font-size: 13px; color: var(--muted); margin: -2px 2px 8px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.live-screen { position: relative; width: 100%; margin: 0 auto; border-radius: 16px; overflow: auto; background: #0d0d0d;
  border: 1px solid var(--line); touch-action: pan-x pan-y; max-height: 64vh; -webkit-overflow-scrolling: touch; }
.live-screen img { width: 100%; display: block; user-select: none; -webkit-user-drag: none; -webkit-touch-callout: none; }
.live-screen.zoom img { width: 220%; max-width: none; }
.live-empty { padding: 60px 24px; text-align: center; color: var(--muted); font-size: 15px; line-height: 1.4; }
.live-dot { position: absolute; width: 26px; height: 26px; margin: -13px 0 0 -13px; border-radius: 50%; border: 2px solid var(--accent);
  pointer-events: none; animation: live-ping .5s ease-out forwards; }
@keyframes live-ping { from { transform: scale(.5); opacity: 1; } to { transform: scale(1.4); opacity: 0; } }
.live-bar { display: flex; gap: 8px; align-items: center; margin-top: 10px; flex-wrap: wrap; }
.live-bar .live-keys { flex: 1 1 150px; min-width: 0; background: #2a2a2a; border: 0; border-radius: 12px; padding: 9px 12px; font-size: 16px; color: var(--text); }
.live-note { min-height: 18px; margin-top: 8px; font-size: 13.5px; color: var(--muted); }
.live-note.bad { color: var(--danger, #ff8a80); }
.live-pip { position: fixed; right: 12px; bottom: calc(env(safe-area-inset-bottom, 0px) + 86px); width: 128px; z-index: 40;
  border-radius: 14px; overflow: hidden; background: #0d0d0d; border: 1px solid #3a3a3a; box-shadow: 0 8px 28px rgba(0,0,0,.55);
  cursor: pointer; transition: opacity .25s, transform .25s; padding: 0; color: var(--text); text-align: left; }
.live-pip[hidden] { display: none; }
.live-pip.out { opacity: 0; transform: translateY(8px) scale(.96); }
.live-pip img { width: 100%; display: block; min-height: 80px; background: #151515; }
.live-pip .lp-tag { position: absolute; left: 6px; top: 6px; font-size: 10.5px; font-weight: 700; letter-spacing: .04em;
  background: rgba(0,0,0,.7); border-radius: 999px; padding: 2px 7px 2px 16px; }
.live-pip .lp-tag::before { content: ""; position: absolute; left: 6px; top: 50%; width: 6px; height: 6px; margin-top: -3px;
  border-radius: 50%; background: #ff4d4d; animation: lp-blink 1.2s infinite; }
@keyframes lp-blink { 50% { opacity: .25; } }
.live-pip .lp-host { display: block; font-size: 11px; color: var(--muted); padding: 4px 7px 5px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.live-shot { display: flex; gap: 10px; align-items: center; margin-top: 6px; padding: 8px; border-radius: 14px; background: #1b1b1b;
  border: 1px solid var(--line); max-width: 300px; cursor: pointer; text-align: left; color: var(--text); width: 100%; }
.live-shot img { width: 64px; height: 64px; object-fit: cover; object-position: top; border-radius: 9px; flex: none; background: #111; }
.live-shot b { display: block; font-size: 14px; font-weight: 600; }
.live-shot span { display: block; font-size: 12.5px; color: var(--muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 200px; }
.activity-line.browse { cursor: pointer; }
.activity-line.browse .al-txt::after { content: " · Watch"; color: var(--accent); }
.live-sites { font-size: 13.5px; color: var(--muted); padding: 4px 0 10px; line-height: 1.45; }
`;
  document.head.append(style);

  const host = u => { try { return new URL(u).hostname.replace(/^www\./, ""); } catch (e) { return ""; } };
  const visibleDoc = () => document.visibilityState === "visible";
  const frameW = box => Math.max(360, Math.min(1280, Math.round((box || 360) * Math.min(3, window.devicePixelRatio || 1))));

  // a sample frame for demo mode: drawn here, so nothing is fetched
  function demoFrame() {
    const c = document.createElement("canvas"); c.width = 512; c.height = 640;
    const g = c.getContext("2d");
    g.fillStyle = "#f4f4f6"; g.fillRect(0, 0, 512, 640);
    g.fillStyle = "#1d4ed8"; g.fillRect(0, 0, 512, 56);
    g.fillStyle = "#fff"; g.font = "bold 22px -apple-system, system-ui, sans-serif"; g.fillText("Luigi's · Reservations", 20, 36);
    g.fillStyle = "#111"; g.font = "bold 26px -apple-system, system-ui, sans-serif"; g.fillText("Book a table", 24, 110);
    g.font = "17px -apple-system, system-ui, sans-serif";
    [["Party size", "2 people"], ["Date", "Fri, Nov 27"], ["Time", "7:00 PM"]].forEach(([k, v], i) => {
      const y = 150 + i * 78; g.fillStyle = "#555"; g.fillText(k, 24, y);
      g.fillStyle = "#fff"; g.fillRect(24, y + 10, 464, 44); g.strokeStyle = "#ccc"; g.strokeRect(24, y + 10, 464, 44);
      g.fillStyle = "#111"; g.fillText(v, 38, y + 39);
    });
    g.fillStyle = "#1d4ed8"; g.fillRect(24, 400, 464, 52); g.fillStyle = "#fff"; g.font = "bold 18px -apple-system, system-ui, sans-serif";
    g.fillText("Find a table", 200, 433);
    return c.toDataURL("image/jpeg", 0.75);
  }

  // ---------------------------------------------------------------- the full screen (sheet)
  const {root, body} = T.sheet("live", "Theta's screen", () => start());
  const banner = el("div", "live-banner", "Theta's own browser. You're in control while this is open: tap, swipe and type. Theta picks up from wherever you leave it.");
  const urlForm = el("form", "live-url"), url = el("input");
  url.type = "url"; url.inputMode = "url"; url.placeholder = "No page open"; url.setAttribute("aria-label", "Page address");
  url.autocomplete = "off"; url.spellcheck = false;
  urlForm.append(url);
  const title = el("div", "live-title");
  const screen = el("div", "live-screen"), img = el("img"), empty = el("div", "live-empty", "Theta isn't using its browser right now.");
  img.alt = "Theta's browser"; img.hidden = true; img.draggable = false;
  screen.append(img, empty);
  const bar = el("form", "live-bar");
  const back = el("button", "btn-dark", "Back"), reload = el("button", "btn-dark", "Reload");
  back.type = reload.type = "button";
  const keys = el("input", "live-keys"); keys.placeholder = "Type into the page"; keys.setAttribute("aria-label", "Type into the page");
  keys.autocomplete = "off"; keys.enterKeyHint = "send";
  const typeBtn = el("button", "btn-dark", "Type"), enter = el("button", "btn-dark", "Enter"), tab = el("button", "btn-dark", "Tab");
  enter.type = tab.type = "button";
  bar.append(back, reload, keys, typeBtn, tab, enter);
  const note = el("div", "live-note"); note.setAttribute("role", "status");
  body.append(banner, urlForm, title, screen, bar, note);

  let running = false, timer = 0, stateTimer = 0, objUrl = null, busy = false, demoShown = false, fallback = null;
  const sheetVisible = () => !root.hidden && visibleDoc();
  const say = (t, bad) => { note.textContent = t || ""; note.classList.toggle("bad", !!bad); };
  function showEmpty(on, text) {
    empty.hidden = !on; img.hidden = on && !fallback;
    if (on) { empty.textContent = text || "Theta isn't using its browser right now."; if (fallback) { img.src = fallback.src; empty.textContent = "That page has closed. This is how it looked."; } }
  }
  function setState(s) {
    if (!s || !s.active) { showEmpty(true); return; }
    if (document.activeElement !== url) url.value = s.url || "";
    title.textContent = s.title || "";
  }
  async function refreshState() {
    try { const r = await T.http("/api/live", {cache: "no-store"}); if (r.ok) setState(await r.json()); } catch (e) {}
  }
  async function frame() {
    if (!running || !sheetVisible()) { stop(); return; }
    try {
      const r = await T.http(`/api/live/frame.jpg?w=${frameW(screen.clientWidth)}&ts=${Date.now()}`, {cache: "no-store"});
      if (r.status === 404) showEmpty(true);
      else if (r.status === 401) { stop(); say("Sign in again to see Theta's screen.", true); return; }
      else if (r.ok) {
        const next = URL.createObjectURL(await r.blob()), old = objUrl;
        objUrl = next; img.src = next; fallback = null; showEmpty(false);
        if (old) setTimeout(() => URL.revokeObjectURL(old), 1000); // after the new one has painted
      }
    } catch (e) {}
    if (running) timer = setTimeout(frame, EVERY);
  }
  function start() {
    say("");
    if (T.state.demo) {
      if (!demoShown) { img.src = demoFrame(); demoShown = true; }
      showEmpty(false); url.value = "https://luigis.example/reserve"; title.textContent = "Book a table (demo)";
      return;
    }
    if (running) return;
    running = true; refreshState();
    stateTimer = setInterval(() => { if (sheetVisible()) refreshState(); }, STATE_EVERY);
    frame();
  }
  function stop() { running = false; clearTimeout(timer); clearInterval(stateTimer); timer = stateTimer = 0; }

  async function act(body, what) {
    if (T.state.demo) { say("Demo: on your server this " + what + " on Theta's page."); return; }
    if (busy) return;
    busy = true;
    try {
      const r = await T.http("/api/live/act", {method: "POST", headers: {"content-type": "application/json"}, body: JSON.stringify(body)});
      let j = {}; try { j = await r.json(); } catch (e) {}
      if (r.ok && j.ok) {
        say(""); setState(Object.assign({active: true}, j));
        // the page asked "Are you sure?": it was answered No; ask the person, and only OK does it again with a yes
        const ask = (j.dialogs || []).find(d => /^confirm /.test(d) && /dismissed\)$/.test(d));
        if (ask && !body.accept && window.confirm("The page asks: " + ask.replace(/^confirm '|' \(dismissed\)$/g, ""))) {
          busy = false; return act(Object.assign({}, body, {accept: true}), what);
        }
      } else if (r.status === 404) { setState({active: false}); say(j.error || "Theta isn't using its browser right now."); }
      else say(j.error || "That didn't work.", true);
    } catch (e) { say("Couldn't reach Theta's browser.", true); }
    finally { busy = false; clearTimeout(timer); if (running) timer = setTimeout(frame, 60); }
  }

  // tap = tap; a swipe = scroll (unless zoomed, when the picture pans); double-tap = zoom
  let down = null, lastTap = 0;
  screen.addEventListener("pointerdown", e => { if (!img.hidden) down = {x: e.clientX, y: e.clientY, sx: screen.scrollLeft, sy: screen.scrollTop}; });
  screen.addEventListener("pointerup", e => {
    if (!down || img.hidden) return;
    const box = img.getBoundingClientRect(), dy = e.clientY - down.y, dx = e.clientX - down.x;
    const zoomed = screen.classList.contains("zoom"), moved = Math.abs(screen.scrollLeft - down.sx) + Math.abs(screen.scrollTop - down.sy);
    const s0 = down; down = null;
    if (zoomed && moved > 6) return; // panning the zoomed picture
    if (!zoomed && Math.abs(dy) > 18 && Math.abs(dy) > Math.abs(dx)) { act({type: "scroll", dy: Math.max(-3, Math.min(3, -dy / box.height * 1.5))}, "scrolls"); return; }
    const now = Date.now();
    if (now - lastTap < 280) { lastTap = 0; screen.classList.toggle("zoom"); return; }
    lastTap = now;
    const x = (s0.x - box.left) / box.width, y = (s0.y - box.top) / box.height;
    if (x < 0 || x > 1 || y < 0 || y > 1) return;
    setTimeout(() => {
      if (lastTap !== now) return; // it became a double-tap
      const sb = screen.getBoundingClientRect(), dot = el("span", "live-dot");
      dot.style.left = (s0.x - sb.left + screen.scrollLeft) + "px"; dot.style.top = (s0.y - sb.top + screen.scrollTop) + "px";
      screen.append(dot); setTimeout(() => dot.remove(), 520);
      act({type: "tap", x: +x.toFixed(4), y: +y.toFixed(4)}, "taps");
    }, 290);
  });
  screen.addEventListener("pointercancel", () => { down = null; });
  back.addEventListener("click", () => act({type: "back"}, "goes back"));
  reload.addEventListener("click", () => act({type: "reload"}, "reloads"));
  enter.addEventListener("click", () => act({type: "key", key: "Enter"}, "presses Enter"));
  tab.addEventListener("click", () => act({type: "key", key: "Tab"}, "moves to the next field"));
  bar.addEventListener("submit", e => { e.preventDefault(); const t = keys.value; if (!t) return; keys.value = ""; act({type: "type", text: t}, "types"); });
  urlForm.addEventListener("submit", e => { e.preventDefault(); const u = url.value.trim(); if (!u) return; url.blur(); act({type: "goto", url: u}, "opens the page"); });
  new MutationObserver(() => { if (root.hidden) stop(); else { start(); hidePip(true); } }).observe(root, {attributes: true, attributeFilter: ["hidden"]});
  document.addEventListener("visibilitychange", () => { if (!sheetVisible()) stop(); else if (!root.hidden) start(); });
  T.menu("Theta's screen", "i-image", "live");
  // tapping the status line while Theta browses ("Clicking “Showtimes”") opens its screen
  document.addEventListener("click", e => { const a = e.target.closest && e.target.closest(".activity-line.browse"); if (a) { hidePip(true); T.open("live"); } });

  // ---------------------------------------------------------------- the floating live picture while Theta browses
  const pip = el("button", "live-pip"); pip.type = "button"; pip.hidden = true; pip.setAttribute("aria-label", "Theta's screen, live. Tap to watch or take over.");
  const pimg = el("img"), ptag = el("span", "lp-tag", "LIVE"), phost = el("span", "lp-host", "");
  pimg.alt = ""; pip.append(pimg, ptag, phost);
  document.body.append(pip);
  let pipOn = false, pipTimer = 0, pipUrl = null, pipEnd = 0;
  pip.addEventListener("click", () => { hidePip(true); T.open("live"); });
  async function pipFrame() {
    pipTimer = 0;
    if (!pipOn) return;
    if (visibleDoc() && root.hidden) {
      try {
        const r = await T.http(`/api/live/frame.jpg?w=360&ts=${Date.now()}`, {cache: "no-store"});
        if (r.ok) {
          const next = URL.createObjectURL(await r.blob()), old = pipUrl;
          pipUrl = next; pimg.src = next; pip.hidden = false; requestAnimationFrame(() => pip.classList.remove("out"));
          if (old) setTimeout(() => URL.revokeObjectURL(old), 1000);
          fetchHost();
        }
      } catch (e) {}
    }
    if (pipOn) pipTimer = setTimeout(pipFrame, PIP_EVERY);
  }
  let hostAt = 0;
  async function fetchHost() {
    if (Date.now() - hostAt < 1500) return; hostAt = Date.now();
    try { const s = await T.api("/api/live"); phost.textContent = s.active ? host(s.url) : ""; } catch (e) {}
  }
  function showPip() {
    if (T.state.demo || !root.hidden) return;
    clearTimeout(pipEnd);
    if (!pipOn) { pipOn = true; pip.classList.add("out"); pipFrame(); }
  }
  function hidePip(now) {
    pipOn = false; clearTimeout(pipTimer); clearTimeout(pipEnd);
    const go = () => { pip.classList.add("out"); setTimeout(() => { if (!pipOn) pip.hidden = true; }, 260); };
    if (now) go(); else pipEnd = setTimeout(go, 1200);
  }
  T.on("tool", d => { if (d && /^browse_/.test(d.name || "") && d.state === "running") showPip(); });
  // the turn is over: the reply carries the last picture, so the floating one goes (it would cover the reply's cards)
  T.on("done", () => hidePip(true));
  T.on("error", () => hidePip(true));

  // ---------------------------------------------------------------- where the browser ended up, on the reply
  T.decorate((m, row) => {
    const sc = m && m.role === "assistant" && m.meta && m.meta.screen;
    if (!sc || !/^[0-9a-f]{32}$/.test(String(sc.id || ""))) return;
    const b = el("button", "live-shot"); b.type = "button";
    const im = el("img"); im.alt = ""; im.loading = "lazy"; im.src = `/api/media/${sc.id}.png`;
    const tx = el("div"); tx.append(el("b", null, "Theta's screen"), el("span", null, sc.title || host(sc.url) || "the page"), el("span", null, host(sc.url)));
    b.append(im, tx);
    b.setAttribute("aria-label", "Open Theta's screen: " + (sc.title || host(sc.url)));
    b.addEventListener("click", () => { fallback = {src: im.src}; T.open("live"); });
    const stamp = row.querySelector(".stamp");
    row.insertBefore(b, stamp || null);
  });

  // ---------------------------------------------------------------- Settings > Security > Theta's browser
  const g = T.settings("Theta's browser", "security");
  const sites = el("div", "live-sites", "");
  const row = el("div", "row-set"), txt = el("div", "txt");
  txt.append(el("b", null, "Sign out everywhere"), el("span", null, "Theta's browser stays signed in to sites you or Theta signed in to, like your own browser. This forgets all of them."));
  const out = el("button", "btn-dark", "Sign out"); out.type = "button";
  row.append(txt, out); g.append(sites, row);
  async function loadSites() {
    if (T.state.demo) { sites.textContent = "Signed in to: luigis.example (demo)"; return; }
    try {
      const j = await T.api("/api/live/signins");
      const list = (j.sites || []).filter((h, i, a) => !a.some((o, k) => k !== i && h.endsWith("." + o)));
      sites.textContent = list.length ? "Has cookies for: " + list.slice(0, 12).join(", ") + (list.length > 12 ? ` and ${list.length - 12} more` : "") : "Not signed in anywhere yet.";
    } catch (e) { sites.textContent = ""; }
  }
  out.addEventListener("click", async () => {
    if (T.state.demo) { T.toast("Demo: on Theta this signs its browser out everywhere."); return; }
    try { await T.http("/api/live/signins", {method: "DELETE"}); T.toast("Theta's browser is signed out everywhere."); loadSites(); }
    catch (e) { T.toast("Couldn't sign out. Try again.", 3000); }
  });
  const sheet = document.getElementById("settings");
  if (sheet) new MutationObserver(() => { if (!sheet.hidden) loadSites(); }).observe(sheet, {attributes: true, attributeFilter: ["hidden"]});
})();
