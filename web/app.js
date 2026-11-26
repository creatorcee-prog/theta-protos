/* Theta: the phone app. Talks to the HTTP API in docs/SPEC.md; in demo mode (?demo=1, or no API) to demo.js.
 * Views: splash -> home <-> chat, plus full-screen sheets (Connect apps, Settings), the attach sheet, the "..." menu,
 * voice mode, and a login screen when the server answers 401.
 * Theta's status is its globe's motion (orb.js): idle, ack, working, speaking, waiting on you, done. No typing dots.
 */
(() => {
  "use strict";
  const $ = id => document.getElementById(id);
  const Q = new URLSearchParams(location.search);
  const REDUCE = matchMedia("(prefers-reduced-motion: reduce)");
  const HOVER = matchMedia("(hover: hover) and (pointer: fine)");
  // this app's version (the files the phone loaded); the server says its own in /api/health. Keep in step with
  // server/__init__.py (tests/test_web.py checks).
  const APP_VERSION = "0.3.0";
  const BOT = "theta", POLL_MS = 20000, PAGE = 50, EARLIER = 30;
  const store = (k, v) => { try { if (v === undefined) return localStorage.getItem(k); if (v === null) localStorage.removeItem(k); else localStorage.setItem(k, v); } catch (e) { return null; } };
  const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
  const svg = id => { const s = document.createElementNS("http://www.w3.org/2000/svg", "svg"), u = document.createElementNS("http://www.w3.org/2000/svg", "use"); u.setAttribute("href", "#" + id); s.append(u); s.setAttribute("aria-hidden", "true"); return s; };

  const S = {
    demo: Q.get("demo") === "1", demoAuto: false, authed: true, version: "", ready: false,
    msgs: new Map(), lastId: 0, inboxId: 0, oldestId: null, noMore: false, loadingEarlier: false,
    streaming: false, unread: 0, lastProactive: null, routes: new Map(), settings: null, connections: null,
  };

  // ---------------------------------------------------------------- API
  const realFetch = window.fetch.bind(window);
  const http = (path, init) => (S.demo ? window.ThetaDemo.fetch : realFetch)(path, Object.assign({credentials: "same-origin"}, init || {}));
  class AuthError extends Error {}
  async function api(path, init) {
    const r = await http(path, init);
    if (r.status === 401) { needLogin(); throw new AuthError("sign in"); }
    if (!r.ok) { const e = new Error(`HTTP ${r.status}`); e.status = r.status; throw e; }
    return r.json();
  }
  const post = (path, body) => api(path, {method: "POST", headers: {"content-type": "application/json"}, body: JSON.stringify(body || {})});
  const timeout = (p, ms) => Promise.race([p, new Promise((_, no) => setTimeout(() => no(new Error("timeout")), ms))]);

  async function detect() {
    if (S.demo) return;
    try {
      const r = await timeout(realFetch("/api/health", {cache: "no-store", credentials: "same-origin"}), 3500);
      const j = await r.json();
      if (!r.ok || !j || !j.ok) throw new Error("no api");
      S.version = j.version || ""; S.build = j.build || "";
    } catch (e) { S.demo = true; S.demoAuto = true; }
  }

  // SSE over a POST: fetch + a ReadableStream reader, parsing event:/data: frames
  async function readSSE(body, on) {
    const reader = body.getReader(), dec = new TextDecoder();
    let buf = "";
    const handle = frame => {
      let ev = "message"; const data = [];
      for (const line of frame.split(/\r?\n/)) {
        if (!line || line[0] === ":") continue;
        const c = line.indexOf(":"), f = c < 0 ? line : line.slice(0, c);
        let v = c < 0 ? "" : line.slice(c + 1); if (v[0] === " ") v = v.slice(1);
        if (f === "event") ev = v; else if (f === "data") data.push(v);
      }
      if (!data.length) return;
      let d = data.join("\n"); try { d = JSON.parse(d); } catch (e) {}
      on(ev, d);
    };
    try {
      for (;;) {
        const {value, done} = await reader.read();
        if (done) break;
        buf += dec.decode(value, {stream: true});
        let m;
        while ((m = /\r?\n\r?\n/.exec(buf))) { const frame = buf.slice(0, m.index); buf = buf.slice(m.index + m[0].length); handle(frame); }
      }
      buf += dec.decode();
      if (buf.trim()) handle(buf);
    } finally { try { reader.releaseLock(); } catch (e) {} }
  }

  // ---------------------------------------------------------------- markdown subset, built as DOM (never innerHTML)
  // **bold**, *italic*, `code`, [links](https://...) and bare https links, bullets, numbered lists, headings, ``` blocks.
  // [n] (or [1, 2]) right after a claim is a citation of meta.sources[n-1]: a small pill with the site's domain
  const INLINE = /(`[^`\n]+`)|(\*\*[^\n]+?\*\*)|(\[[^\]\n]+\]\([^)\s]+\))|(https:\/\/[^\s<>()"']+[^\s<>()"'.,;:!?])|(\*[^*\s](?:[^*\n]*[^*\s])?\*)|(\n)|(\[\d{1,2}(?:\s*,\s*\d{1,2})*\](?!\())/g;
  function safeHref(href) {
    try { const u = new URL(href); return u.protocol === "https:" ? u.href : null; } catch (e) { return null; }
  }
  // ---- cite: start (pure; tests/test_message_actions.py runs this block in node)
  function domain(href) {
    try { const u = new URL(String(href)); return u.protocol === "https:" && u.hostname ? u.hostname.replace(/^www\./, "") : null; } catch (e) { return null; }
  }
  // "[1]" or "[1, 2]" -> [{n, url, label, title}] when every number has an https source; else null (stays text)
  function citeParts(tok, sources) {
    if (!Array.isArray(sources) || !sources.length) return null;
    const out = [];
    for (const part of tok.slice(1, -1).split(",")) {
      const n = Number(part.trim()), s = sources[n - 1], d = s && typeof s.url === "string" ? domain(s.url) : null;
      if (!d) return null;
      out.push({n, url: new URL(s.url).href, label: d, title: String(s.title || d)});
    }
    return out.length ? out : null;
  }
  // ---- cite: end
  function pill(c) {
    const a = el("a", "cite", c.label); a.href = c.url; a.target = "_blank"; a.rel = "noopener noreferrer";
    a.title = c.title; a.setAttribute("aria-label", `Source ${c.n}: ${c.title} (${c.label})`); return a;
  }
  let mdSources = null; // the sources of the message md() is building
  function inline(parent, text, depth) {
    depth = depth || 0;
    let last = 0, m;
    const re = new RegExp(INLINE.source, "g");
    while ((m = re.exec(text))) {
      if (m.index > last) parent.append(text.slice(last, m.index));
      const tok = m[0];
      if (m[1]) parent.append(el("code", null, tok.slice(1, -1)));
      else if (m[2]) { const b = el("strong"); if (depth < 2) inline(b, tok.slice(2, -2), depth + 1); else b.textContent = tok.slice(2, -2); parent.append(b); }
      else if (m[3]) {
        const mm = /^\[([^\]]+)\]\(([^)\s]+)\)$/.exec(tok), href = mm && safeHref(mm[2]);
        if (href) { const a = el("a", null, mm[1]); a.href = href; a.target = "_blank"; a.rel = "noopener noreferrer"; parent.append(a); }
        else parent.append(mm ? mm[1] : tok);
      } else if (m[4]) {
        const href = safeHref(tok);
        if (href) { const a = el("a", null, tok.replace(/^https:\/\//, "")); a.href = href; a.target = "_blank"; a.rel = "noopener noreferrer"; parent.append(a); }
        else parent.append(tok);
      } else if (m[5]) { const i = el("em"); if (depth < 2) inline(i, tok.slice(1, -1), depth + 1); else i.textContent = tok.slice(1, -1); parent.append(i); }
      else if (m[6]) parent.append(el("br"));
      else if (m[7]) { const cs = citeParts(tok, mdSources); if (cs) cs.forEach(c => parent.append(pill(c))); else parent.append(tok); }
      last = re.lastIndex;
    }
    if (last < text.length) parent.append(text.slice(last));
  }
  function md(src, streaming, sources) {
    mdSources = Array.isArray(sources) ? sources : null;
    src = String(src || "").replace(/\r\n?/g, "\n");
    if (streaming) { // close what's still open, so half-streamed **bold or `code` doesn't flash its markers
      if ((src.match(/\*\*/g) || []).length % 2) src += "**";
      if ((src.match(/`/g) || []).length % 2) src += "`";
    }
    const frag = document.createDocumentFragment();
    let para = [], list = null, code = null;
    const flush = () => { if (para.length) { const p = el("p"); inline(p, para.join("\n")); frag.append(p); para = []; } };
    for (const line of src.split("\n")) {
      if (/^\s*```/.test(line)) {
        if (code) { code = null; continue; }
        flush(); list = null; const pre = el("pre"); code = el("code"); pre.append(code); frag.append(pre); continue;
      }
      if (code) { code.append((code.textContent ? "\n" : "") + line); continue; }
      const b = /^\s*[-*•]\s+(.*)$/.exec(line), n = /^\s*(\d{1,3})[.)]\s+(.*)$/.exec(line), h = /^\s*#{1,6}\s+(.*)$/.exec(line);
      if (b || n) {
        flush();
        const type = b ? "ul" : "ol";
        if (!list || list.tagName.toLowerCase() !== type) { list = el(type); if (n && n[1] !== "1") list.start = Number(n[1]); frag.append(list); }
        const li = el("li"); inline(li, b ? b[1] : n[2]); list.append(li); continue;
      }
      if (!line.trim()) { flush(); list = null; continue; }
      if (list && /^\s{2,}\S/.test(line)) { list.lastChild.append(" "); inline(list.lastChild, line.trim()); continue; }
      if (h) { flush(); list = null; const e = el("h4"); inline(e, h[1]); frag.append(e); continue; }
      list = null; para.push(line);
    }
    flush();
    mdSources = null;
    return frag;
  }

  // ---------------------------------------------------------------- views and history
  const views = ["splash", "login", "home", "chat"];
  let view = "splash";
  function show(name) {
    if (view === name) return;
    view = name;
    for (const v of views) { const e = $(v); if (v === "splash") continue; e.hidden = v !== name; }
    const e = $(name); e.classList.remove("enter"); void e.offsetWidth; e.classList.add("enter");
    if (name === "chat") { markRead(); requestAnimationFrame(() => { toBottom(false); }); }
    if (name === "home") renderHome();
  }
  const SHEETS = ["connect", "settings"];
  function render(st) {
    st = st || {v: "home"};
    if (!S.authed) return;
    show(st.v === "chat" ? "chat" : "home");
    for (const s of SHEETS) { const open = st.sheet === s, e = $(s); if (open && e.hidden) openSheet(s); else if (!open && !e.hidden) closeSheetEl(e); }
  }
  const go = st => { history.pushState(st, "", location.href); render(st); };
  const cur = () => history.state || {v: view === "chat" ? "chat" : "home"};
  addEventListener("popstate", e => { hideMenu(); closeAttach(); render(e.state); });

  // ---------------------------------------------------------------- toast, hint, dock
  let toastT = 0;
  function toast(msg, ms) {
    const t = $("toast"); t.textContent = msg; t.hidden = false; t.style.animation = "none"; void t.offsetWidth; t.style.animation = "";
    clearTimeout(toastT); toastT = setTimeout(() => { t.hidden = true; }, ms || 2800);
  }
  // cards docked above the composer: outages, limits, retries. Never a modal, never in the transcript.
  function dock(key, opts) {
    const d = $("dock"); let card = d.querySelector(`[data-key="${key}"]`);
    if (!opts) { if (card) card.remove(); return; }
    if (!card) { card = el("div", "sys"); card.dataset.key = key; d.append(card); }
    card.className = "sys" + (opts.err ? " err" : "");
    card.replaceChildren(svg(opts.icon || "i-bell"), el("b", null, opts.title));
    if (opts.text) card.append(el("p", null, opts.text));
    if (opts.actions) {
      const acts = el("div", "acts");
      for (const [label, fn, white] of opts.actions) { const b = el("button", white ? "btn-white" : "btn-dark", label); b.type = "button"; b.addEventListener("click", fn); acts.append(b); }
      card.append(acts);
    }
  }

  // ---------------------------------------------------------------- orbs
  const orbs = {};
  orbs.home = ThetaOrb.mount($("home-orb"), {dots: 520, scale: 1});
  orbs.head = ThetaOrb.mount($("head-orb"), {dots: 170, scale: 1.75, dotK: 1.6, glow: 0.7, maxDpr: 3});
  const both = (fn, ...a) => { orbs.head[fn](...a); orbs.home[fn](...a); };
  const setStatus = s => { orbs.head.setState(s); orbs.home.setState(s === "speaking" ? "speaking" : s); };

  // ---------------------------------------------------------------- chat thread
  const scroller = $("scroller"), thread = $("thread"), jump = $("jump");
  let stick = true, autoScroll = 0;
  const distBottom = () => scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight;
  function toBottom(smooth) {
    autoScroll = performance.now() + (smooth ? 500 : 60);
    scroller.scrollTo({top: scroller.scrollHeight, behavior: smooth && !REDUCE.matches ? "smooth" : "auto"});
    jump.hidden = true; stick = true;
  }
  function follow(smooth) { if (view !== "chat") return; if (stick) toBottom(smooth); else jump.hidden = false; }
  scroller.addEventListener("scroll", () => {
    if (performance.now() > autoScroll) { stick = distBottom() < 90; if (stick) jump.hidden = true; }
    if (scroller.scrollTop < 160) loadEarlier();
    hideHint();
  }, {passive: true});
  for (const ev of ["touchstart", "wheel"]) scroller.addEventListener(ev, () => { autoScroll = 0; }, {passive: true});
  jump.addEventListener("click", () => toBottom(true));

  const fmtTime = t => new Date(t * 1000).toLocaleTimeString([], {hour: "numeric", minute: "2-digit"});
  const SOURCES = {vantage: "an alert near you", brief: "your brief", reminder: "a reminder"};

  function bubble(m, streaming) {
    const b = el("div", "msg " + (m.role === "user" ? "u" : "a"));
    if (m.role === "user") b.textContent = m.text; else b.append(md(m.text, streaming, (m.meta || {}).sources));
    if (m.id != null) {
      b.dataset.id = m.id;
      // on a mouse, a small "..." beside the bubble opens the same bar a long-press does
      if (!streaming) { const mb = el("button", "more-btn"); mb.type = "button"; mb.setAttribute("aria-label", "Message actions"); mb.setAttribute("aria-haspopup", "dialog"); mb.append(svg("i-more")); b.append(mb); }
    }
    return b;
  }
  // "1,234 in · 210 out · $0.0004": the finished reply's token use (meta.usage), never while streaming
  const fmtN = n => Number(n || 0).toLocaleString();
  const fmtUsd = c => c >= 1 ? c.toFixed(2) : c >= 0.01 ? c.toFixed(3) : c.toFixed(4);
  function usageLine(u) {
    const parts = [`${fmtN(u.in)} in`, `${fmtN(u.out)} out`];
    if (Number(u.cost_usd) > 0) parts.push("$" + fmtUsd(Number(u.cost_usd)));
    const d = el("div", "usage"), t = el("span", "u-txt", parts.join(" · ")); d.append(t);
    const full = `${fmtN(u.in)} tokens in${u.cached ? ` (${fmtN(u.cached)} cached)` : ""}, ${fmtN(u.out)} out` + (Number(u.cost_usd) > 0 ? `, about $${fmtUsd(Number(u.cost_usd))}` : "") + (u.model ? ` · ${u.model}` : "");
    t.title = full; t.setAttribute("aria-label", "Token use: " + full);
    return d;
  }
  function voteMark(v) {
    const i = el("span", "voted " + (v > 0 ? "up" : "down")); i.setAttribute("role", "img");
    i.setAttribute("aria-label", v > 0 ? "You liked this" : "You disliked this"); i.append(svg(v > 0 ? "i-like" : "i-dislike")); return i;
  }
  function sourcesRow(sources) {
    const seen = new Set(), row = el("div", "srcs"); row.setAttribute("role", "group"); row.setAttribute("aria-label", "Sources");
    row.append(el("span", "srcs-h", "Sources"));
    sources.forEach((s, i) => { const c = s && citeParts(`[${i + 1}]`, sources); if (c && !seen.has(c[0].url)) { seen.add(c[0].url); row.append(pill(c[0])); } });
    return seen.size ? row : null;
  }
  function taskCard(m) {
    const t = m.meta.task, state = t.state || "working", c = el("div", "task " + state);
    const cv = el("canvas"); cv.setAttribute("aria-hidden", "true");
    const txt = el("div", "t-txt"); txt.append(el("b", null, t.title || m.text || "Working on it"), el("span", null, {working: "Working on it…", done: "Done", failed: "Didn't finish", waiting: "Needs you"}[state] || state));
    c.append(cv, txt);
    requestAnimationFrame(() => { const o = ThetaOrb.mount(cv, {dots: 150, scale: 1.7, dotK: 1.6, glow: 0.6, maxDpr: 3}); o.setState(state === "working" ? "working" : state === "waiting" ? "waiting" : "idle"); });
    return c;
  }
  // one message as a row: (the "Theta texted you" line) + bubble or task card + (choice chips)
  function item(m, opts) {
    opts = opts || {};
    const row = el("div", "item"); row.dataset.key = m.id != null ? "m" + m.id : m.cid;
    const meta = m.meta || {};
    if (meta.proactive && m.role === "assistant") {
      const t = el("div", "texted" + (opts.fresh ? " fresh" : ""), "Theta texted you · " + fmtTime(m.t || Date.now() / 1000));
      row.append(t);
    }
    let main;
    if (meta.task && typeof meta.task === "object") main = taskCard(m);
    else main = bubble(m);
    if (opts.pending) main.classList.add("pending");
    if (opts.fresh) { main.classList.add("fresh"); setTimeout(() => main.classList.add("settled"), 2500); }
    else if (opts.anim) main.classList.add("new");
    row.append(main);
    if (Array.isArray(meta.actions) && meta.actions.length && m.role === "assistant") row.append(actionChips(meta.actions, m));
    if (m.role === "assistant" && !meta.ack && !meta.task) {
      const src = Array.isArray(meta.sources) && meta.sources.length ? sourcesRow(meta.sources) : null;
      if (src) row.append(src);
      if (meta.note) row.append(el("div", "note", String(meta.note)));
      const hasUse = meta.usage && typeof meta.usage === "object" && (meta.usage.in || meta.usage.out);
      if (hasUse || meta.vote) {
        const u = hasUse ? usageLine(meta.usage) : el("div", "usage bare");
        if (meta.vote) u.prepend(voteMark(meta.vote));
        row.append(u);
      }
    }
    if (m.role === "user" && meta.edited) row.append(el("div", "usage edited", "Edited"));
    if (Array.isArray(meta.cards) && m.role === "assistant") {
      for (const c of meta.cards) {
        const fn = c && cardKinds[c.type];
        if (!fn) continue;
        try { const node = fn(c, m); if (node) { node.classList.add("card"); row.append(node); } } catch (err) { console.error(err); }
      }
    }
    for (const d of decorators) { try { d(m, row, main); } catch (err) { console.error(err); } }
    return row;
  }
  const decorators = []; // features add things to a message (images, call transcripts): Theta.decorate(fn)
  const cardKinds = {};  // meta.cards [{type, ...}] -> Theta.card(type, fn(card, message) -> element)
  const listeners = {};  // live chat stream events (user, route, ack, tool, activity, delta, done...): Theta.on(ev, fn)
  function actionChips(actions, m) {
    const wrap = el("div", "actions"); wrap.setAttribute("role", "group"); wrap.setAttribute("aria-label", "Reply options");
    const usedKey = "protos:acted:" + m.id, used = store(usedKey);
    for (const a of actions.slice(0, 4)) {
      if (!a || !a.label) continue;
      const b = el("button", "act", String(a.label)); b.type = "button";
      if (used && used === String(a.label)) b.classList.add("picked");
      b.addEventListener("click", () => {
        if (wrap.classList.contains("used") || S.streaming) return;
        wrap.classList.add("used"); b.classList.add("picked"); store(usedKey, String(a.label));
        send(String(a.value != null ? a.value : a.label), {show: String(a.label)});
      });
      wrap.append(b);
    }
    if (used) wrap.classList.add("used");
    return wrap;
  }
  function remember(m) {
    if (m.id == null) return;
    S.msgs.set(m.id, m);
    if (m.id > S.lastId) S.lastId = m.id;
    if (S.oldestId == null || m.id < S.oldestId) S.oldestId = m.id;
    if (m.meta && m.meta.proactive && (!S.lastProactive || m.id > S.lastProactive.id)) S.lastProactive = m;
  }
  function appendMsg(m, opts) {
    if (m.id != null && S.msgs.has(m.id) && thread.querySelector(`[data-key="m${m.id}"]`)) return null;
    remember(m);
    const row = item(m, opts);
    // keep id order: a message that arrives late (e.g. from the inbox) goes before any newer one already shown
    const later = m.id == null ? null : [...thread.querySelectorAll('[data-key^="m"]')].find(n => +n.dataset.key.slice(1) > m.id);
    if (later) thread.insertBefore(row, later); else thread.append(row);
    return row;
  }
  function emptyState() {
    if (thread.children.length) return;
    const c = el("div", "sys");
    c.append(svg("i-bell"), el("b", null, "Say hi to Theta"), el("p", null, "It picks the right model for each message, answers in one voice, and texts you first when something matters."));
    c.dataset.key = "welcome"; thread.append(c);
  }

  // ---------------------------------------------------------------- history
  async function loadHistory() {
    const d = await api(`/api/messages?bot=${BOT}&limit=${PAGE}`);
    const list = d.messages || [];
    thread.replaceChildren();
    for (const m of list) appendMsg(m);
    S.inboxId = list.length ? list[list.length - 1].id : 0;
    S.noMore = list.length < PAGE;
    $("earlier").textContent = S.noMore && list.length ? "This is the start of your chat with Theta." : "";
    emptyState();
  }
  async function loadEarlier() {
    if (S.noMore || S.loadingEarlier || S.oldestId == null || view !== "chat") return;
    S.loadingEarlier = true; $("earlier").textContent = "Loading earlier…";
    try {
      const d = await api(`/api/messages?bot=${BOT}&before=${S.oldestId}&limit=${EARLIER}`), list = (d.messages || []).filter(m => !S.msgs.has(m.id));
      const h0 = scroller.scrollHeight, top0 = scroller.scrollTop, frag = document.createDocumentFragment();
      for (const m of list) { remember(m); frag.append(item(m)); }
      thread.prepend(frag);
      scroller.scrollTop = top0 + (scroller.scrollHeight - h0); // keep the view where it was
      S.noMore = (d.messages || []).length < EARLIER;
      $("earlier").textContent = S.noMore ? "This is the start of your chat with Theta." : "";
    } catch (e) { $("earlier").textContent = ""; }
    finally { S.loadingEarlier = false; }
  }

  // ---------------------------------------------------------------- inbox: new messages, incl. Theta texting first
  async function poll() {
    if (S.streaming) { S.pollAfter = true; return; } // checked again as soon as the reply is in
    if (!S.authed || !S.ready || document.visibilityState !== "visible") return;
    try {
      // the cursor moves only with what the inbox (or history) returned: a proactive text stored while a reply was
      // streaming has a lower id than that reply, and must not be skipped
      const d = await api(`/api/inbox?since=${S.inboxId}`);
      dock("offline", null);
      for (const m of d.messages || []) { if (m.id > S.inboxId) S.inboxId = m.id; if (!S.msgs.has(m.id)) incoming(m); }
    } catch (e) {
      if (!(e instanceof AuthError) && !e.status) dock("offline", {err: true, icon: "i-bell", title: "Can't reach Theta right now", text: "Your messages are safe. I'll keep trying."});
    }
  }
  function incoming(m) {
    const w = thread.querySelector('[data-key="welcome"]'); if (w) w.remove();
    const fresh = m.role === "assistant";
    appendMsg(m, {fresh, anim: !fresh});
    if (m.role === "assistant") {
      orbs.head.ack(); orbs.home.ack();
      if (view !== "chat") { S.unread++; renderHome(); }
      if (Array.isArray((m.meta || {}).actions) || /\?\s*$/.test(m.text || "")) setStatus("waiting");
    }
    follow(true);
  }
  setInterval(poll, POLL_MS);
  document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible") poll(); });
  addEventListener("protos:inbox", () => poll());
  addEventListener("online", () => poll());

  // ---------------------------------------------------------------- sending
  const SHORT_CHARS = 220, SHORT_MS = 700; // short replies land whole, like a text; long ones stream
  async function send(text, opts) {
    opts = opts || {};
    text = String(text || "").trim();
    if (!text) return null;
    if (S.streaming) { toast("One sec, Theta's still answering."); return null; }
    if (view !== "chat") go({v: "chat"});
    const w = thread.querySelector('[data-key="welcome"]'); if (w) w.remove();
    dock("retry", null);
    const cid = "c" + Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
    const editId = opts.edit != null ? Number(opts.edit) : null, before = editId != null ? S.msgs.get(editId) : null;
    let row = editId != null ? thread.querySelector(`[data-key="m${editId}"]`) : null, userMsg = null;
    if (editId != null && !row) { toast("That message isn't on screen anymore."); return null; }
    if (row) { // editing: the same bubble takes the new words; the replies under it go when the server says so
      const ub0 = row.querySelector(".msg"); ub0.textContent = text; ub0.classList.add("pending");
    } else {
      const local = {id: null, cid, role: "user", text: opts.show || text, t: Date.now() / 1000, meta: {}};
      row = item(local, {pending: true, anim: true}); thread.append(row);
    }
    let ub = row.querySelector(".msg");
    toBottom(true);
    S.streaming = true;
    // acknowledged: one pulse; then working: the swirl, also where the reply will appear
    orbs.head.ack(); setStatus("working");
    const pend = el("div", "pending-orb"), pcv = el("canvas"); pcv.setAttribute("aria-hidden", "true"); pend.append(pcv);
    pend.setAttribute("role", "status"); pend.setAttribute("aria-label", "Theta is working on it");
    thread.append(pend);
    const porb = ThetaOrb.mount(pcv, {dots: 200, scale: 1.55, dotK: 1.5, glow: 0.8, maxDpr: 3}); porb.ack(); porb.setState("working");
    follow(true);

    let route = null, reply = null, buf = "", shown = null, firstAt = 0, frame = 0, timer = 0;
    const draw = () => { frame = 0; if (!shown) return; shown.replaceChildren(md(buf, true)); follow(false); };
    const startShow = () => {
      if (shown || reply) return;
      pend.remove(); porb.destroy();
      shown = el("div", "msg a streaming new"); thread.append(shown);
      setStatus("speaking"); draw();
    };
    try {
      const r = await http(editId != null ? "/api/messages/edit" : "/api/chat", {method: "POST", headers: {"content-type": "application/json", accept: "text/event-stream"},
        body: JSON.stringify(editId != null ? {bot: BOT, id: editId, text} : {bot: BOT, text, client_id: cid})});
      if (r.status === 401) { needLogin(); throw new AuthError("sign in"); }
      if (r.status === 409 && editId != null) throw Object.assign(new Error("Only your latest message can be edited."), {status: 409, edit409: true});
      if (!r.ok || !r.body) throw Object.assign(new Error(`HTTP ${r.status}`), {status: r.status});
      await readSSE(r.body, (ev, data) => {
        for (const fn of (listeners[ev] || [])) { try { fn(data, {text, reply: () => reply}); } catch (err) { console.error(err); } }
        if (ev === "user" && data && data.id != null) {
          remember(data); userMsg = data; row.dataset.key = "m" + data.id; ub.dataset.id = data.id; ub.classList.remove("pending");
        } else if (ev === "deleted" && data && Array.isArray(data.ids)) {
          // an edit: Theta's earlier replies to this message go (other texts stay)
          for (const id of data.ids) { S.msgs.delete(id); const n = thread.querySelector(`[data-key="m${id}"]`); if (n) n.replaceWith(); }
        } else if (ev === "route") route = data;
        else if (ev === "ack" && data && data.id != null) {
          // "On it." is its own message, above the working globe and the reply that follows
          if (!S.msgs.has(data.id)) { remember(data); thread.insertBefore(item(data, {anim: true}), pend.isConnected ? pend : null); }
        } else if (ev === "tool" && data) {
          pend.setAttribute("aria-label", data.state === "running" ? `Theta is using ${data.name}` : "Theta is working on it");
        } else if (ev === "delta") {
          buf += (data && data.text) || "";
          orbs.head.pulse(Math.min(0.5, ((data && data.text) || "").length / 30));
          if (shown) { if (!frame) frame = requestAnimationFrame(draw); }
          else if (buf.length > SHORT_CHARS) startShow();
          else if (!firstAt) { firstAt = performance.now(); timer = setTimeout(startShow, SHORT_MS); }
        } else if (ev === "done") reply = data;
        else if (ev === "error") throw new Error((data && data.error) || "Theta hit an error");
      });
      clearTimeout(timer);
      if (!reply || reply.id == null) throw new Error("The reply was cut off");
      if (route) S.routes.set(reply.id, route);
      reply.meta = Object.assign({}, reply.meta || {});
      if (route && !reply.meta.model) Object.assign(reply.meta, {model: route.model, tier: route.tier});
      if (route && route.why && !reply.meta.why) reply.meta.why = route.why;
      if (frame) cancelAnimationFrame(frame);
      pend.remove(); porb.destroy();
      remember(reply);
      const final = item(reply, {anim: !shown});
      if (shown) shown.replaceWith(final); else thread.append(final);
      if (userMsg && row.isConnected) { const nr = item(userMsg); row.replaceWith(nr); row = nr; ub = nr.querySelector(".msg"); } // its "..." and "Edited"
      orbs.head.done(); orbs.home.done();
      if (Array.isArray(reply.meta.actions) || /\?\s*$/.test(reply.text || "")) setTimeout(() => { if (!S.streaming) setStatus("waiting"); }, 600);
      follow(true);
      return reply;
    } catch (e) {
      clearTimeout(timer); if (frame) cancelAnimationFrame(frame);
      pend.remove(); porb.destroy();
      if (shown) { shown.classList.remove("streaming"); if (!buf) shown.remove(); }
      setStatus("idle");
      if (e instanceof AuthError) return null;
      if (e.edit409) { // a newer message came in (another device): put the old words back
        if (before) { const nr = item(before); row.replaceWith(nr); } else ub.classList.remove("pending");
        toast(e.message, 3600); return null;
      }
      ub.classList.remove("pending"); ub.classList.add("failed");
      const offline = !navigator.onLine || !e.status;
      dock("retry", {err: true, icon: "i-bell", title: offline && !e.message.startsWith("HTTP") ? "Theta didn't answer" : "Theta couldn't answer just now",
        text: e.message && !/^HTTP|fetch|network/i.test(e.message) ? e.message : "The message didn't go through. Nothing was lost.",
        actions: [["Dismiss", () => dock("retry", null)], ["Try again", () => { if (editId == null) row.replaceWith(); dock("retry", null); send(text, opts); }, true]]});
      return null;
    } finally { S.streaming = false; if (S.pollAfter) { S.pollAfter = false; setTimeout(poll, 300); } }
  }

  // ---------------------------------------------------------------- composer
  const form = $("composer"), ta = $("c-text");
  function sizeTa() { ta.style.height = "auto"; ta.style.height = Math.min(140, ta.scrollHeight) + "px"; form.classList.toggle("has-text", !!ta.value.trim());
    $("c-send").setAttribute("aria-label", ta.value.trim() ? "Send" : "Voice mode"); }
  ta.addEventListener("input", () => { sizeTa(); if (orbs.head.state === "waiting") setStatus("idle"); });
  ta.addEventListener("keydown", e => { if (e.key === "Enter" && !e.shiftKey && !e.isComposing && HOVER.matches) { e.preventDefault(); form.requestSubmit(); } });
  form.addEventListener("submit", e => {
    e.preventDefault();
    const text = ta.value.trim();
    if (!text) { voiceMode(); return; }
    if (S.streaming) { toast("One sec, Theta's still answering."); return; }
    const editing = S.editing; endEdit(false);
    stopMic(); ta.value = ""; sizeTa(); send(text, editing != null ? {edit: editing} : undefined);
  });
  // editing your last message: the composer holds its words, with an "Editing" chip to cancel
  function startEdit(m) {
    S.editing = m.id; ta.value = m.text; sizeTa();
    const chip = $("edit-chip"); chip.replaceChildren(svg("i-edit"), el("b", null, "Editing"), el("span", null, "Sending replaces your message and Theta answers again."));
    const x = el("button"); x.type = "button"; x.setAttribute("aria-label", "Cancel editing"); x.append(svg("i-close"));
    x.addEventListener("click", () => endEdit(true)); chip.append(x); chip.hidden = false;
    setTimeout(() => { ta.focus(); try { ta.setSelectionRange(ta.value.length, ta.value.length); } catch (e) {} }, 30);
  }
  function endEdit(clear) { if (S.editing == null) return; S.editing = null; $("edit-chip").hidden = true; if (clear) { ta.value = ""; sizeTa(); } }
  ta.addEventListener("keydown", e => { if (e.key === "Escape" && S.editing != null) { e.preventDefault(); endEdit(true); } });

  // mic: the Web Speech API, when the browser has it
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  let rec = null;
  function stopMic() { if (rec) { try { rec.stop(); } catch (e) {} } }
  $("c-mic").addEventListener("click", () => {
    if (!SR) { toast("Dictation isn't available in this browser. Try the keyboard's mic."); return; }
    if (rec) { stopMic(); return; }
    const base = ta.value ? ta.value.replace(/\s*$/, " ") : "";
    rec = new SR(); rec.lang = navigator.language || "en-US"; rec.interimResults = true; rec.continuous = false;
    $("c-mic").classList.add("on");
    rec.onresult = e => { let s = ""; for (let i = 0; i < e.results.length; i++) s += e.results[i][0].transcript; ta.value = base + s; sizeTa(); };
    rec.onerror = e => { if (e.error === "not-allowed") toast("Microphone access is off for this site."); };
    rec.onend = () => { rec = null; $("c-mic").classList.remove("on"); };
    try { rec.start(); } catch (e) { rec = null; $("c-mic").classList.remove("on"); }
  });

  // voice mode: listen, send, read the reply aloud, listen again
  let voiceOn = false, vrec = null, vorb = null;
  function voiceMode() {
    if (!SR) { toast("Voice mode needs speech recognition, which this browser doesn't have."); return; }
    $("voice").hidden = false; voiceOn = true;
    if (!vorb) vorb = ThetaOrb.mount($("voice-orb"), {dots: 520, scale: 1.2});
    listen();
  }
  function listen() {
    if (!voiceOn) return;
    vorb.setState("waiting"); $("voice-cap").textContent = "Listening…";
    vrec = new SR(); vrec.lang = navigator.language || "en-US"; vrec.interimResults = true;
    let said = "";
    vrec.onresult = e => { said = ""; for (let i = 0; i < e.results.length; i++) said += e.results[i][0].transcript; $("voice-cap").textContent = said; vorb.pulse(0.2); };
    vrec.onend = async () => {
      vrec = null; if (!voiceOn) return;
      if (!said.trim()) { $("voice-cap").textContent = "Tap the X when you're done."; return; }
      vorb.ack(); vorb.setState("working");
      const reply = await send(said);
      if (!voiceOn) return;
      if (reply && window.speechSynthesis) {
        const u = new SpeechSynthesisUtterance(reply.text.replace(/[*`#_]/g, "").replace(/\[([^\]]+)\]\([^)]+\)/g, "$1"));
        vorb.setState("speaking"); $("voice-cap").textContent = reply.text.replace(/[*`#]/g, "").slice(0, 160);
        u.onboundary = () => vorb.pulse(0.4);
        u.onend = () => { vorb.done(); setTimeout(listen, 400); };
        speechSynthesis.speak(u);
      } else { vorb.done(); setTimeout(listen, 600); }
    };
    try { vrec.start(); } catch (e) { $("voice-cap").textContent = "The microphone isn't available."; }
  }
  $("voice-close").addEventListener("click", () => {
    voiceOn = false; $("voice").hidden = true;
    if (vrec) { try { vrec.abort(); } catch (e) {} vrec = null; }
    if (window.speechSynthesis) speechSynthesis.cancel();
  });

  // ---------------------------------------------------------------- message actions: long-press (or "..." on a mouse)
  // A compact bar: Copy; on replies Copy with prompt, Like, Dislike, Sources; on your latest message Edit. Its small
  // "Model" line is the old route hint (which model answered), so long-press stays one gesture.
  let pressT = 0, pressAt = null, barFor = null, barFrom = null;
  const bar = $("msgbar");
  const cleanCopy = t => String(t || "").replace(/\n*\[image:[^\]]+\]/g, "").trim();
  function copyText(text) {
    const fallback = () => {
      const t = el("textarea"); t.value = text; t.setAttribute("readonly", ""); t.setAttribute("aria-hidden", "true");
      t.style.cssText = "position:fixed;top:0;left:0;width:1px;height:1px;opacity:0;pointer-events:none";
      document.body.append(t); t.select(); try { t.setSelectionRange(0, text.length); } catch (e) {}
      let ok = false; try { ok = document.execCommand("copy"); } catch (e) {}
      t.replaceWith(); return ok;
    };
    const done = ok => toast(ok ? "Copied" : "Couldn't copy. Select the text instead.", 1600);
    // called straight from the tap, so the browser counts it as the user's action
    if (navigator.clipboard && navigator.clipboard.writeText && window.isSecureContext) {
      navigator.clipboard.writeText(text).then(() => done(true), () => done(fallback()));
    } else done(fallback());
  }
  function promptBefore(m) {
    let best = null;
    for (const x of S.msgs.values()) if (x.role === "user" && x.id < m.id && (!best || x.id > best.id)) best = x;
    return best;
  }
  const latestUser = () => { let best = null; for (const x of S.msgs.values()) if (x.role === "user" && (!best || x.id > best.id)) best = x; return best; };
  function modelLine(m) {
    const meta = m.meta || {}, r = S.routes.get(m.id) || {}, line = el("div", "mb-model");
    if (m.role === "user") line.append(meta.edited ? "You · edited · " : "You · ", fmtTime(m.t || 0));
    else if (meta.proactive) line.append("Theta texted first, from ", el("b", null, SOURCES[meta.source] || "something it noticed"), " · " + fmtTime(m.t || 0));
    else if (meta.model || r.model) {
      const why = meta.why || r.why, tier = meta.tier || r.tier;
      line.append("Model: ", el("b", null, meta.model || r.model), tier ? ` · ${tier}` : "", why ? ` · ${why}` : "", " · " + fmtTime(m.t || 0));
    } else line.append("Theta · " + fmtTime(m.t || 0));
    return line;
  }
  function barBtn(label, icon, fn, opts) {
    const b = el("button", "mb-btn"); b.type = "button"; b.append(svg(icon), el("span", null, label));
    b.setAttribute("aria-label", (opts && opts.aria) || label);
    if (opts && opts.pressed != null) b.setAttribute("aria-pressed", String(!!opts.pressed));
    b.addEventListener("click", e => { e.stopPropagation(); fn(b); }); return b;
  }
  function refreshRow(m) {
    const old = thread.querySelector(`[data-key="m${m.id}"]`); if (old) old.replaceWith(item(m));
  }
  async function vote(m, v, reason) {
    const prev = (m.meta || {}).vote;
    m.meta = Object.assign({}, m.meta || {}, {vote: v || undefined}); refreshRow(m);
    try { await post("/api/feedback", {message_id: m.id, vote: v, reason: reason || ""}); return true; }
    catch (e) { m.meta.vote = prev; refreshRow(m); if (!(e instanceof AuthError)) toast("Couldn't save that. Try again in a moment."); return false; }
  }
  const REASONS = ["Too long", "Wrong", "Not what I asked", "Tone"];
  function askWhy(m) {
    bar.replaceChildren();
    const h = el("div", "mb-head"); h.append(el("b", null, "What was off?"), el("span", null, "Theta learns from this."));
    const chips = el("div", "mb-chips"); chips.setAttribute("role", "group"); chips.setAttribute("aria-label", "What was off");
    for (const r of REASONS) {
      const c = el("button", "mb-chip", r); c.type = "button";
      c.addEventListener("click", async e => { e.stopPropagation(); closeBar(); if (await vote(m, -1, r)) toast("Thanks. Theta will keep that in mind."); });
      chips.append(c);
    }
    const f = el("form", "mb-why"), inp = el("input"); inp.type = "text"; inp.maxLength = 280; inp.placeholder = "Something else (optional)"; inp.setAttribute("aria-label", "What was off, in your words");
    const go = el("button", "mb-send"); go.type = "submit"; go.setAttribute("aria-label", "Send feedback"); go.append(svg("i-up"));
    f.append(inp, go);
    f.addEventListener("submit", async e => { e.preventDefault(); const t = inp.value.trim(); closeBar(); if (!t) return; if (await vote(m, -1, t)) toast("Thanks. Theta will keep that in mind."); });
    bar.append(h, chips, f);
    place();
    const first = chips.querySelector("button"); if (first) first.focus({preventScroll: true});
  }
  function showSources(m) {
    const list = el("div", "mb-srcs"); list.setAttribute("role", "list");
    for (const [i, s] of (m.meta.sources || []).entries()) {
      const c = citeParts(`[${i + 1}]`, m.meta.sources); if (!c) continue;
      const a = el("a", "mb-src"); a.href = c[0].url; a.target = "_blank"; a.rel = "noopener noreferrer"; a.setAttribute("role", "listitem");
      a.append(el("span", "n", String(i + 1)), el("b", null, c[0].title), el("small", null, c[0].label)); list.append(a);
    }
    const old = bar.querySelector(".mb-srcs"); if (old) { old.replaceWith(); place(); return; }
    bar.insertBefore(list, bar.querySelector(".mb-model")); place();
  }
  function openBar(b, from) {
    const m = S.msgs.get(Number(b.dataset.id)); if (!m) return;
    if (barFor === m.id && !bar.hidden) return;
    closeBar(); barFor = m.id; barFrom = from || null;
    const meta = m.meta || {}, acts = el("div", "mb-acts");
    acts.setAttribute("role", "toolbar"); acts.setAttribute("aria-label", "Message actions");
    acts.append(barBtn("Copy", "i-copy", () => { closeBar(); copyText(cleanCopy(m.text)); }));
    if (m.role === "assistant" && !meta.ack && !meta.task) {
      acts.append(barBtn("With prompt", "i-copy2", () => {
        closeBar(); const u = promptBefore(m);
        copyText((u ? `You: ${cleanCopy(u.text)}\n\n` : "") + `Theta: ${cleanCopy(m.text)}`);
      }, {aria: "Copy with prompt"}));
      acts.append(barBtn(meta.vote > 0 ? "Liked" : "Like", "i-like", async () => {
        const on = meta.vote > 0; closeBar(); if (await vote(m, on ? 0 : 1)) toast(on ? "Like removed." : "Thanks. Theta will do more like this.");
      }, {pressed: meta.vote > 0, aria: "Like"}));
      acts.append(barBtn(meta.vote < 0 ? "Disliked" : "Dislike", "i-dislike", async () => {
        if (meta.vote < 0) { closeBar(); if (await vote(m, 0)) toast("Dislike removed."); return; }
        vote(m, -1); askWhy(m); // the tap is the vote; a reason is one more (optional) tap
      }, {pressed: meta.vote < 0, aria: "Dislike"}));
      if (Array.isArray(meta.sources) && meta.sources.length) acts.append(barBtn("Sources", "i-link", () => showSources(m), {aria: `Sources (${meta.sources.length})`}));
    }
    const lu = latestUser();
    if (m.role === "user" && lu && lu.id === m.id && !meta.tap && !meta.images) {
      acts.append(barBtn("Edit", "i-edit", () => {
        closeBar(); if (S.streaming) { toast("One sec, Theta's still answering."); return; } startEdit(m);
      }, {aria: "Edit message"}));
    }
    bar.replaceChildren(acts, modelLine(m));
    bar.hidden = false; b.classList.add("held");
    place();
    if (navigator.vibrate && !from) try { navigator.vibrate(8); } catch (e) {}
    if (from) acts.querySelector("button").focus({preventScroll: true});
  }
  function place() {
    const b = barFor != null && thread.querySelector(`.msg[data-id="${barFor}"]`); if (!b) return;
    const rb = b.getBoundingClientRect(), ra = $("app").getBoundingClientRect(), w = Math.min(344, ra.width - 32);
    bar.style.width = w + "px";
    const left = b.classList.contains("u") ? rb.right - ra.left - w : rb.left - ra.left;
    bar.style.left = Math.max(16, Math.min(ra.width - w - 16, left)) + "px";
    const above = rb.top - ra.top - bar.offsetHeight - 8, below = rb.bottom - ra.top + 8;
    bar.style.top = (above > 64 || below + bar.offsetHeight > ra.height - 80 ? Math.max(64, above) : below) + "px";
  }
  function closeBar(restore) {
    if (bar.hidden) return;
    bar.hidden = true; bar.replaceChildren();
    thread.querySelectorAll(".msg.held").forEach(x => x.classList.remove("held"));
    const from = barFrom; barFor = null; barFrom = null;
    if (restore && from && from.isConnected) from.focus({preventScroll: true});
  }
  const hideHint = () => closeBar(); // scrolling closes it
  thread.addEventListener("pointerdown", e => {
    if (e.target.closest(".more-btn, a, button")) return;
    const b = e.target.closest(".msg"); if (!b || !b.dataset.id) return;
    pressAt = [e.clientX, e.clientY]; clearTimeout(pressT);
    pressT = setTimeout(() => { pressAt = null; openBar(b); }, 480);
  });
  const cancelPress = e => { if (pressAt && (!e || e.type !== "pointermove" || Math.hypot(e.clientX - pressAt[0], e.clientY - pressAt[1]) > 8)) { clearTimeout(pressT); pressAt = null; } };
  for (const ev of ["pointerup", "pointercancel", "pointermove"]) thread.addEventListener(ev, cancelPress);
  thread.addEventListener("contextmenu", e => {
    const b = e.target.closest(".msg"); if (!b || !b.dataset.id || e.target.closest("a")) return;
    e.preventDefault(); clearTimeout(pressT); openBar(b);
  });
  thread.addEventListener("click", e => {
    const mb = e.target.closest(".more-btn"); if (!mb) return;
    e.stopPropagation(); const b = mb.closest(".msg");
    if (barFor != null && barFor === Number(b.dataset.id)) closeBar(); else openBar(b, mb);
  });
  document.addEventListener("pointerdown", e => { if (!e.target.closest("#msgbar") && !e.target.closest(".more-btn")) closeBar(); }, true);
  document.addEventListener("keydown", e => { if (e.key === "Escape" && !bar.hidden) { e.preventDefault(); e.stopPropagation(); closeBar(true); } }, true);
  addEventListener("resize", () => closeBar());

  // ---------------------------------------------------------------- home
  function markRead() { S.unread = 0; renderHome(); }
  function renderHome() {
    const badge = $("home-badge"); badge.hidden = !S.unread; badge.textContent = S.unread > 9 ? "9+" : String(S.unread);
    const last = [...S.msgs.values()].sort((a, b) => b.id - a.id)[0];
    $("home-sub").textContent = last ? (last.role === "user" ? "You: " : "") + last.text.replace(/[*`#]/g, "").replace(/\s+/g, " ").slice(0, 80) : "Your own assistant";
    // the banner slot: something Theta texted you that you haven't seen, else an offer to turn on notifications
    const bn = $("home-banner"); bn.replaceChildren();
    if (S.unread && S.lastProactive) {
      const m = S.lastProactive, t = el("div", "b-txt");
      t.append(el("small", null, "Theta texted you · " + fmtTime(m.t)), el("span", null, m.text.replace(/[*`#]/g, "")));
      const b = el("button", "btn-white", "Open"); b.addEventListener("click", () => openChat(m.id));
      bn.append(svg("i-bell"), t, b); bn.hidden = false;
    } else if (!pushOn() && store("protos:banner-off") !== "1") {
      const t = el("div", "b-txt"); t.append(el("span", null, "Let Theta text you when it matters."));
      const b = el("button", "btn-white", "Turn on");
      b.addEventListener("click", async () => { if (await enablePush()) { renderHome(); syncSettingsUi(); } });
      const x = el("button", "round"); x.style.cssText = "width:34px;height:34px;border:0;background:none"; x.setAttribute("aria-label", "Not now"); x.append(svg("i-close"));
      x.addEventListener("click", () => { store("protos:banner-off", "1"); renderHome(); });
      bn.append(svg("i-bell"), t, b, x); bn.hidden = false;
    } else bn.hidden = true;
  }
  function openChat(id) {
    if (view !== "chat") go({v: "chat"});
    if (id != null) focusMsg(id);
  }
  async function focusMsg(id) {
    for (let i = 0; i < 6 && !thread.querySelector(`.msg[data-id="${id}"]`) && !S.noMore; i++) { await loadEarlier(); }
    const b = thread.querySelector(`[data-key="m${id}"] .msg, [data-key="m${id}"] .task`);
    if (!b) return;
    stick = false; autoScroll = performance.now() + 600;
    b.scrollIntoView({block: "center", behavior: REDUCE.matches ? "auto" : "smooth"});
    b.classList.add("target"); setTimeout(() => b.classList.remove("target"), 2200);
  }
  $("home-bot").addEventListener("click", () => openChat());
  $("home-new").addEventListener("click", () => { openChat(); setTimeout(() => ta.focus(), 50); });
  $("home-me").addEventListener("click", () => go(Object.assign({}, cur(), {sheet: "settings"})));
  $("home-apps").addEventListener("click", () => go(Object.assign({}, cur(), {sheet: "connect"})));

  // search what's loaded of the chat
  let searchT = 0;
  $("home-search").addEventListener("input", () => { clearTimeout(searchT); searchT = setTimeout(runSearch, 120); });
  $("home-search").addEventListener("keydown", e => { if (e.key === "Escape") { e.target.value = ""; runSearch(); } });
  function runSearch() {
    const q = $("home-search").value.trim().toLowerCase(), box = $("home-results");
    box.replaceChildren();
    $("home").querySelector(".home-mid").hidden = !!q;
    if (!q) { box.hidden = true; return; }
    const hits = [...S.msgs.values()].filter(m => (m.text || "").toLowerCase().includes(q)).sort((a, b) => b.id - a.id).slice(0, 30);
    if (!hits.length) box.append(el("p", "empty", "Nothing in your chat matches that."));
    for (const m of hits) {
      const r = el("button", "result"); r.setAttribute("role", "listitem");
      r.append(el("small", null, (m.role === "user" ? "You" : "Theta") + " · " + new Date(m.t * 1000).toLocaleDateString([], {month: "short", day: "numeric"}) + " " + fmtTime(m.t)));
      const s = el("span"), text = m.text.replace(/[*`#]/g, ""), i = text.toLowerCase().indexOf(q), from = Math.max(0, i - 40);
      s.append((from ? "…" : "") + text.slice(from, i), el("mark", null, text.slice(i, i + q.length)), text.slice(i + q.length, i + q.length + 120));
      r.append(s);
      r.addEventListener("click", () => { $("home-search").value = ""; runSearch(); openChat(m.id); });
      box.append(r);
    }
    box.hidden = false;
  }

  // ---------------------------------------------------------------- chat header
  $("chat-back").addEventListener("click", () => { if (history.state && history.state.v === "chat") history.back(); else go({v: "home"}); });
  $("chat-name").addEventListener("click", () => toBottom(true));
  function hideMenu() { $("menu").hidden = true; }
  $("chat-more").addEventListener("click", e => { e.stopPropagation(); $("menu").hidden = !$("menu").hidden; });
  document.addEventListener("click", e => { if (!e.target.closest("#menu")) hideMenu(); });
  $("menu").addEventListener("click", e => {
    const b = e.target.closest("button"); if (!b) return; hideMenu();
    if (b.dataset.act === "connect" || b.dataset.act === "settings") go(Object.assign({}, cur(), {sheet: b.dataset.act}));
    if (b.dataset.act === "refresh") { poll(); toast("Checked. You're up to date."); }
    if (b.dataset.sheet) go(Object.assign({}, cur(), {sheet: b.dataset.sheet}));
  });

  // ---------------------------------------------------------------- sheets
  const sheetOpeners = {};
  function openSheet(name) {
    const e = $(name); e.classList.remove("closing"); e.hidden = false;
    if (name === "connect") loadConnections();
    if (name === "settings") loadSettings();
    if (sheetOpeners[name]) { try { sheetOpeners[name](e); } catch (err) { console.error(err); } }
  }
  function closeSheetEl(e) {
    if (REDUCE.matches) { e.hidden = true; return; }
    e.classList.add("closing"); setTimeout(() => { e.hidden = true; e.classList.remove("closing"); }, 250);
  }
  document.querySelectorAll(".sheet.full [data-close]").forEach(b => b.addEventListener("click", () => {
    if (history.state && history.state.sheet) history.back(); else render({v: view});
  }));

  // attach (bottom sheet): photos are stubbed in v0
  function openAttach() { $("attach").hidden = false; $("scrim").hidden = false; }
  function closeAttach() { $("attach").hidden = true; $("scrim").hidden = true; }
  $("c-plus").addEventListener("click", openAttach);
  $("scrim").addEventListener("click", closeAttach);
  for (const id of ["att-photo", "att-camera", "att-file"]) $(id).addEventListener("change", e => {
    const f = e.target.files && e.target.files[0]; closeAttach(); if (!f) return;
    const chip = $("attach-chip"); chip.replaceChildren(svg(id === "att-file" ? "i-file" : "i-image"),
      el("span", null, `${f.name}: Theta can't see attachments yet, so this one stays on your phone.`));
    const x = el("button", null); x.type = "button"; x.setAttribute("aria-label", "Remove"); x.append(svg("i-close")); x.addEventListener("click", () => { chip.hidden = true; });
    chip.append(x); chip.hidden = false; e.target.value = "";
  });

  // ---------------------------------------------------------------- Connect apps
  const CAT = {gmail: "Google", gcal: "Google", calendar: "Google", gdrive: "Google", drive: "Google", google: "Google",
    vantage: "Theta", obsidian: "Notes", notion: "Notes", plex: "Media", spotify: "Media", youtube: "Media",
    homeassistant: "Home", hue: "Home", github: "Developer", vercel: "Developer"};
  let connFilter = "All";
  async function loadConnections() {
    const list = $("connect-list");
    if (!S.connections) list.replaceChildren(el("p", "empty", "Loading…"));
    try { S.connections = await api("/api/connections"); }
    catch (e) {
      if (e instanceof AuthError) return;
      const r = await window.ThetaDemo.fetch("/api/connections"); S.connections = await r.json(); // a mock list until the server has one
      S.connMock = true;
    }
    if (!Array.isArray(S.connections)) S.connections = (S.connections && S.connections.connections) || [];
    renderConnections();
  }
  function renderConnections() {
    const all = S.connections || [], q = $("connect-search").value.trim().toLowerCase();
    $("connect-count").textContent = all.filter(c => c.connected).length + " connected";
    const cats = ["All", "Connected", ...new Set(all.map(c => CAT[c.id] || "Other"))];
    const chips = $("connect-chips"); chips.replaceChildren();
    for (const c of cats) { const b = el("button", "chip", c); b.type = "button"; b.setAttribute("role", "tab"); b.setAttribute("aria-selected", String(c === connFilter));
      b.addEventListener("click", () => { connFilter = c; renderConnections(); }); chips.append(b); }
    const pass = c => (connFilter === "All" || (connFilter === "Connected" ? c.connected : (CAT[c.id] || "Other") === connFilter))
      && (!q || (c.name + " " + (c.what || "")).toLowerCase().includes(q));
    const shown = all.filter(pass), list = $("connect-list"); list.replaceChildren();
    const section = (title, items) => {
      if (!items.length) return;
      const h = el("h3", "sec", title); h.append(svg("i-chev")); list.append(h);
      for (const c of items) list.append(appRow(c));
    };
    section("Connected", shown.filter(c => c.connected));
    section("Suggested for you", shown.filter(c => !c.connected));
    if (!shown.length) list.append(el("p", "empty", q ? "No apps match that." : "Nothing here yet."));
    if (S.connMock) list.append(el("p", "fine center", "Sample list: the server doesn't list connections yet."));
  }
  function appRow(c) {
    const row = el("div", "app-row"), ic = el("div", "app-ic", (c.name || "?").trim()[0].toUpperCase());
    let h = 0; for (const ch of c.id || c.name) h = (h * 31 + ch.charCodeAt(0)) % 360;
    ic.style.background = `linear-gradient(145deg, hsl(${h} 45% 34%), hsl(${(h + 30) % 360} 50% 22%))`;
    const t = el("div", "app-txt"); t.append(el("b", null, c.name), el("span", null, c.what || ""));
    const b = el("button", "btn-dark" + (c.connected ? " on" : ""), c.connected ? "Connected" : "Connect"); b.type = "button";
    b.setAttribute("aria-label", (c.connected ? "Connected: " : "Connect ") + c.name);
    b.addEventListener("click", async () => {
      if (S.demo) { try { await post("/api/connections/" + encodeURIComponent(c.id), {}); c.connected = !c.connected; renderConnections(); } catch (e) {} return; }
      if (c.connect_url && !c.connected && /^\/api\//.test(c.connect_url)) { location.href = c.connect_url; return; }
      if (c.note && !c.connected) { toast(c.note, 5000); return; }
      toast(c.connected ? `${c.name} is connected on Theta.` : `Connecting ${c.name} from the phone comes later. Set it up on Theta for now.`, 3600);
    });
    row.append(ic, t, b);
    return row;
  }
  $("connect-search").addEventListener("input", renderConnections);

  // ---------------------------------------------------------------- Settings
  const pushOn = () => store("protos:push") === "1";
  function b64u(s) { const p = "=".repeat((4 - s.length % 4) % 4), raw = atob((s + p).replace(/-/g, "+").replace(/_/g, "/")); return Uint8Array.from(raw, c => c.charCodeAt(0)); }
  const canPush = () => "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
  async function enablePush() {
    if (!canPush()) { toast(/iPhone|iPad/.test(navigator.userAgent) ? "On iPhone, add Theta to your Home Screen first, then turn this on." : "This browser can't get push notifications.", 4000); return false; }
    try {
      const perm = await Notification.requestPermission();
      if (perm !== "granted") { toast("Notifications are blocked for this site in your settings."); return false; }
      if (S.demo) { store("protos:push", "1"); toast("Notifications on (demo)."); return true; }
      const {key} = await api("/api/push/key");
      if (!key) { toast("Push isn't set up on Theta's server yet."); return false; }
      const reg = await navigator.serviceWorker.ready;
      const sub = (await reg.pushManager.getSubscription()) || await reg.pushManager.subscribe({userVisibleOnly: true, applicationServerKey: b64u(key)});
      await post("/api/push/subscribe", {subscription: sub.toJSON()});
      store("protos:push", "1"); toast("Notifications on."); return true;
    } catch (e) { if (!(e instanceof AuthError)) toast("Couldn't turn on notifications: " + (e.message || e)); return false; }
  }
  async function disablePush() {
    store("protos:push", "0");
    try { const reg = await navigator.serviceWorker.ready, sub = await reg.pushManager.getSubscription(); if (sub) await sub.unsubscribe(); } catch (e) {}
  }
  for (const id of ["set-quiet-from", "set-quiet-to"]) for (let h = 0; h < 24; h++) {
    const o = el("option", null, new Date(2000, 0, 1, h).toLocaleTimeString([], {hour: "numeric"})); o.value = h; $(id).append(o); }
  for (const s of ThetaOrb.shapes) { const o = el("option", null, s[0].toUpperCase() + s.slice(1) + "s"); o.value = s; $("set-dot").append(o); }
  let setOrb = null;
  function syncSettingsUi() {
    const st = S.settings || {};
    $("set-push").checked = pushOn();
    $("set-proactive").checked = st.proactive !== false;
    const q = Array.isArray(st.quiet) ? st.quiet : [22, 7];
    $("set-quiet-from").value = q[0]; $("set-quiet-to").value = q[1];
    $("set-loc").checked = !!st.loc;
    $("set-loc-note").textContent = st.loc ? `Shared, rounded to about 10 km (${st.loc.lat}, ${st.loc.lon}). Used only for alerts near you.` : "Rounded to about 10 km. Used only for alerts near you.";
    $("set-dot").value = ThetaOrb.shape;
    $("set-opening").value = store("theta:opening") || "converge";
    $("set-usage").checked = showUsage();
    $("settings-mode").textContent = S.demo ? "Demo" : "";
    $("set-about").textContent = `${versionLine()}${S.demo ? " · demo mode: nothing leaves this page" : ""} · times in ${st.tz || Intl.DateTimeFormat().resolvedOptions().timeZone}`;
  }
  async function loadSettings() {
    if (!setOrb) setOrb = ThetaOrb.mount($("set-orb"), {dots: 520});
    syncSettingsUi();
    loadLessons();
    try { S.settings = await api("/api/settings"); syncSettingsUi(); } catch (e) {}
  }
  // token use under replies: a per-phone choice, default on
  const showUsage = () => store("protos:show-usage") !== "0";
  const applyUsage = () => document.documentElement.classList.toggle("no-usage", !showUsage());
  applyUsage();
  $("set-usage").addEventListener("change", e => { store("protos:show-usage", e.target.checked ? "1" : "0"); applyUsage(); });
  // what Theta learned from your likes and dislikes (it's in Theta's instructions; remove any you disagree with)
  function renderLessons(list) {
    const box = $("set-lessons"); box.replaceChildren();
    if (!list.length) {
      const r = el("div", "row-set"), t = el("div", "txt"); t.append(el("b", null, "Nothing yet"), el("span", null, "Long-press a reply and tap Like or Dislike. What Theta takes from it shows up here."));
      r.append(t); box.append(r); return;
    }
    for (const l of list) {
      const r = el("div", "row-set lesson"), t = el("div", "txt"); t.append(el("b", null, l.text));
      if (l.n > 1) t.append(el("span", null, `From ${l.n} replies`));
      const x = el("button", "btn-dark", "Remove"); x.type = "button"; x.setAttribute("aria-label", "Remove lesson: " + l.text);
      x.addEventListener("click", async () => {
        x.disabled = true;
        try { const j = await api("/api/feedback/summary?id=" + encodeURIComponent(l.id), {method: "DELETE"}); renderLessons(j.lessons || []); toast("Removed. Theta won't use that one."); }
        catch (e) { x.disabled = false; if (!(e instanceof AuthError)) toast("Couldn't remove that. Try again in a moment."); }
      });
      r.append(t, x); box.append(r);
    }
  }
  async function loadLessons() {
    try { const j = await api("/api/feedback/summary"); renderLessons(j.lessons || []); $("set-export").hidden = !(j.likes > 0) || S.demo; }
    catch (e) { if (!(e instanceof AuthError)) $("set-lessons").replaceChildren(el("p", "fine", "Couldn't load these right now.")); }
  }
  async function saveSetting(patch) {
    S.settings = Object.assign({}, S.settings || {}, patch);
    try { const r = await post("/api/settings", patch); if (r && typeof r === "object" && !Array.isArray(r)) S.settings = Object.assign(S.settings, r.settings || r); }
    catch (e) { if (!(e instanceof AuthError)) toast("Couldn't save that. Try again in a moment."); }
    syncSettingsUi();
  }
  $("set-push").addEventListener("change", async e => {
    if (e.target.checked) { if (!(await enablePush())) e.target.checked = false; } else await disablePush();
    renderHome();
  });
  $("set-push-test").addEventListener("click", async () => {
    if (S.demo) { toast("In demo mode a test is just this toast. On Theta it pushes to your phone."); return; }
    try { await post("/api/push/test"); toast("Sent. It should land in a few seconds."); } catch (e) { if (!(e instanceof AuthError)) toast("The test didn't send: " + (e.status || e.message)); }
  });
  $("set-proactive").addEventListener("change", e => saveSetting({proactive: e.target.checked}));
  for (const id of ["set-quiet-from", "set-quiet-to"]) $(id).addEventListener("change", () => saveSetting({quiet: [Number($("set-quiet-from").value), Number($("set-quiet-to").value)]}));
  $("set-loc").addEventListener("change", e => {
    if (!e.target.checked) { saveSetting({loc: null}); return; }
    if (!navigator.geolocation) { e.target.checked = false; toast("This browser can't share location."); return; }
    $("set-loc-note").textContent = "Finding you…";
    navigator.geolocation.getCurrentPosition(p => {
      // one decimal place is about 11 km north–south: Theta never gets your exact spot
      const r1 = v => Math.round(v * 10) / 10;
      saveSetting({loc: {lat: r1(p.coords.latitude), lon: r1(p.coords.longitude)}});
    }, () => { e.target.checked = false; syncSettingsUi(); toast("Location is off for this site."); }, {enableHighAccuracy: false, timeout: 15000, maximumAge: 600000});
  });
  $("set-dot").addEventListener("change", e => ThetaOrb.setShape(e.target.value));
  $("set-opening").addEventListener("change", e => store("theta:opening", e.target.value));

  // ---------------------------------------------------------------- login
  let loginOrb = null;
  function needLogin() {
    if (!S.authed && view === "login") return;
    S.authed = false;
    if (view === "splash") return; // shown when the splash ends
    showLogin();
  }
  // "Theta 0.3.0 · server 0.3.0 (aaad836)": if the two differ, the phone is on old files
  function versionLine() {
    const srv = S.version ? `server ${S.version}${S.build ? " (" + S.build + ")" : ""}` : "server not reached";
    return `Theta ${APP_VERSION} · ${srv}` + (S.version && S.version !== APP_VERSION ? " · update pending: close and reopen" : "");
  }
  function showLogin() {
    for (const s of SHEETS) $(s).hidden = true;
    show("login");
    if (!loginOrb) loginOrb = ThetaOrb.mount($("login-orb"), {dots: 420, scale: 1.1});
    if ($("login-ver")) $("login-ver").textContent = versionLine();
    setTimeout(() => $("login-key").focus(), 300);
  }
  $("login-form").addEventListener("submit", async e => {
    e.preventDefault();
    const key = $("login-key").value.trim(); if (!key) return;
    $("login-err").textContent = "";
    try {
      const r = await http("/api/login", {method: "POST", headers: {"content-type": "application/json"}, body: JSON.stringify({key})});
      if (!r.ok) { $("login-err").textContent = r.status === 401 || r.status === 403 ? "That key didn't work." : `Theta answered ${r.status}. Try again.`; loginOrb && loginOrb.ring(8); return; }
      S.authed = true; $("login-key").value = "";
      await loadAll();
      history.replaceState({v: "home"}, "", location.href); show("home");
    } catch (err) { $("login-err").textContent = "Can't reach Theta right now."; }
  });

  // ---------------------------------------------------------------- service worker
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/sw.js", {scope: "/", updateViaCache: "none"}).then(reg => {
      reg.update().catch(() => {});  // look for a new version every time the app opens
      document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible") reg.update().catch(() => {}); });
    }).catch(() => navigator.serviceWorker.register("/static/sw.js").catch(() => {}));
    // when a new version takes over, reload once so you're on it right away (not on the open after next)
    const hadController = !!navigator.serviceWorker.controller;
    let reloaded = false;
    navigator.serviceWorker.addEventListener("controllerchange", () => {
      if (!hadController || reloaded || S.streaming) return;
      reloaded = true; location.reload();
    });
    navigator.serviceWorker.addEventListener("message", e => {
      const d = e.data || {};
      if (d.type === "push") poll();
      if (d.type === "open") { poll().then(() => openChat(d.id != null ? Number(d.id) : undefined)); }
    });
  }

  // keep the layout above the keyboard on iPhone
  // iOS doesn't shrink the page for the keyboard: it scrolls the visible part down by visualViewport.offsetTop and
  // leaves the page full height, so a full-screen app slides up and leaves a blank gap. So the app sizes itself to
  // what's visible, follows that scroll, and drops the home-bar padding while the keyboard is up.
  if (window.visualViewport) {
    // iOS, keyboard open: the page isn't shrunk; Safari scrolls the document (window.scrollY) and/or the visible
    // part (visualViewport.offsetTop), and while the keyboard is up it moves "fixed" elements with that scroll,
    // which slid the whole app up and left a blank gap. So: never let the document scroll (it's pinned in CSS and
    // put back here), size the app to the visible part, and follow any visible-part offset that remains.
    const root = document.documentElement, appEl = document.getElementById("app");
    let raf = 0;
    const fit = () => {
      raf = 0;
      if (window.scrollY || window.scrollX) window.scrollTo(0, 0);
      const v = window.visualViewport, top = Math.max(0, Math.round(v.offsetTop));
      root.style.setProperty("--vh", Math.round(v.height) + "px");
      if (appEl) appEl.style.transform = top ? `translateY(${top}px)` : "";
      root.classList.toggle("kb", window.innerHeight - v.height > 120 || screen.height - v.height > 200);
    };
    const later = () => { if (!raf) raf = requestAnimationFrame(fit); };
    visualViewport.addEventListener("resize", later);
    visualViewport.addEventListener("scroll", later);
    addEventListener("scroll", later, {passive: true});
    // the keyboard slides in over ~300 ms: check a few times while it moves
    const settle = () => { for (const ms of [0, 60, 160, 320, 600]) setTimeout(later, ms); };
    addEventListener("focusin", settle);
    addEventListener("focusout", settle);
    fit();
  }

  // ---------------------------------------------------------------- boot
  async function loadAll() {
    await loadHistory();
    S.ready = true;
    if (S.demo && S.demoAuto) dock("demo", {icon: "i-bell", title: "Demo mode", text: "Theta's server isn't reachable, so this is a built-in demo. Nothing you type leaves this page.",
      actions: [["OK", () => dock("demo", null)]]});
    renderHome();
  }
  async function boot() {
    history.replaceState({v: "home"}, "", location.href);
    const splash = $("splash"), sorb = ThetaOrb.mount($("splash-orb"), {dots: 520, radiusPx: 53});
    let skip;
    // the full opening (about 3 s) once a day; every other open plays it 3x faster (about 1 s)
    const today = new Date().toDateString(), full = store("theta:opened") !== today;
    store("theta:opened", today);
    const opening = new Promise(res => { skip = res; sorb.opening(store("theta:opening") || "converge", res, full ? 1 : 3); });
    splash.addEventListener("click", () => skip(), {once: true});
    const ready = (async () => { await detect(); try { await loadAll(); } catch (e) { if (!(e instanceof AuthError)) { S.demo = true; S.demoAuto = true; await loadAll().catch(() => {}); } } })();
    await Promise.all([Promise.race([opening, new Promise(r => setTimeout(r, full ? 4000 : 1500))]), ready]);
    const target = Q.get("m");
    if (!S.authed) showLogin();
    else if (target) { show("home"); openChat(Number(target)); }
    else show("home");
    splash.classList.add("out");
    setTimeout(() => { splash.hidden = true; sorb.destroy(); }, 480);
    if (target) { const u = new URL(location.href); u.searchParams.delete("m"); history.replaceState(history.state, "", u.href); }
  }
  window.ThetaApp = {send, poll, state: S, md}; // for tests and the console

  // ---- for feature screens (web/features/*.js; the list is in web/features.js). They build their own sheets
  // with Theta.sheet(), add rows to Settings and items to the "..." menu, and call the API through Theta.api.
  window.Theta = {
    api, post, http, toast, send, el, svg, store, md, state: S,
    open(id) { go(Object.assign({}, cur(), {sheet: id})); },
    // fn(message, rowEl, bubbleEl) runs for every message shown; add to rowEl, build DOM nodes only (no innerHTML)
    decorate(fn) { decorators.push(fn); },
    // a renderer for one kind of card in meta.cards (weather, link, event, connect...): fn(card, msg) -> element
    card(type, fn) { cardKinds[type] = fn; },
    // listen to the reply stream while Theta answers: fn(data, {text}) for "tool", "activity", "delta", "done"...
    on(ev, fn) { (listeners[ev] = listeners[ev] || []).push(fn); },
    close() { if (history.state && history.state.sheet) history.back(); else render({v: view}); },
    // a full-screen sheet like Settings: returns {root, body, foot}; onOpen(root) runs each time it opens
    sheet(id, title, onOpen) {
      if (!$(id)) {
        const root = el("section", "sheet full"); root.id = id; root.hidden = true;
        root.setAttribute("role", "dialog"); root.setAttribute("aria-modal", "true"); root.setAttribute("aria-label", title);
        const head = el("header", "sheet-head"), x = el("button", "round"); x.setAttribute("aria-label", "Close"); x.append(svg("i-close"));
        x.addEventListener("click", () => Theta.close());
        head.append(x, el("h2", null, title), el("span", "count-pill"));
        root.append(head, el("div", "sheet-body"), el("div", "sheet-foot"));
        root.querySelector(".sheet-foot").hidden = true;
        $("app").append(root);
        if (!SHEETS.includes(id)) SHEETS.push(id);
      }
      if (onOpen) sheetOpeners[id] = onOpen;
      const root = $(id);
      return {root, body: root.querySelector(".sheet-body"), foot: root.querySelector(".sheet-foot"), pill: root.querySelector(".count-pill")};
    },
    // a button in the chat "..." menu that opens a sheet (or runs fn)
    menu(label, icon, sheetOrFn) {
      const b = el("button"); b.setAttribute("role", "menuitem"); b.append(svg(icon || "i-grid"), document.createTextNode(label));
      if (typeof sheetOrFn === "function") b.addEventListener("click", sheetOrFn); else b.dataset.sheet = sheetOrFn;
      $("menu").append(b); return b;
    },
    // a section in Settings, above the "about" line: returns the group element to fill with .row-set rows
    settings(title) {
      const body = $("settings").querySelector(".settings-body"), about = $("set-about");
      const h = el("h3", "sec", title), g = el("div", "group"); body.insertBefore(h, about); body.insertBefore(g, about); return g;
    },
  };
  window.dispatchEvent(new Event("theta:ready"));
  boot();
})();
