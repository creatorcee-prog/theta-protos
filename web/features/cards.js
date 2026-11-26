/* cards: the card kit (server/cards.py). Each card in a reply's meta.cards is {type, ...}; this registers one
 * renderer per type with Theta.card(type, fn(card, message) -> element). app.js adds the outer .card frame (A
 * styles it); everything inside is styled here, prefixed "cards-".
 * Types: weather, stock, link, place, event, email, checklist, table, steps, choice, quote, gallery, file, connect.
 * Rules: DOM nodes only (never innerHTML), links only https:// (or a same-site /api/ path), images only
 * same-site /api/media or /api/uploads paths or data: URLs (the CSP blocks the rest).
 * Demo: /?demo=1&cards=1 adds one sample reply per type, for screenshots. */
(() => {
  "use strict";
  const T = window.Theta;
  if (!T) return;
  const el = T.el;
  const NS = "http://www.w3.org/2000/svg";
  const Q = new URLSearchParams(location.search);

  const style = document.createElement("style");
  style.textContent = `
:where(.card) { align-self: flex-start; width: min(100%, 340px); background: var(--card); border-radius: 22px; overflow: hidden; }
.cards-in { padding: 14px 16px 15px; display: flex; flex-direction: column; gap: 10px; min-width: 0; font-size: 15px; line-height: 1.35; }
.cards-in a { color: inherit; text-decoration: none; }
.cards-kicker { font-size: 12px; font-weight: 600; letter-spacing: .06em; text-transform: uppercase; color: var(--muted); display: flex; align-items: center; gap: 6px; min-width: 0; }
.cards-kicker span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.cards-title { font-size: 17px; font-weight: 600; line-height: 1.25; overflow-wrap: anywhere; }
.cards-sub { color: var(--muted); font-size: 14px; overflow-wrap: anywhere; }
.cards-clamp { display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; }
.cards-row { display: flex; align-items: center; gap: 12px; min-width: 0; }
.cards-row > .cards-grow { flex: 1; min-width: 0; }
.cards-btns { display: flex; flex-wrap: wrap; gap: 8px; }
.cards-btn { display: inline-flex; align-items: center; justify-content: center; gap: 6px; padding: 9px 15px; border-radius: 999px; background: #333; color: var(--text); font-size: 15px; font-weight: 500; white-space: nowrap; }
.cards-btn:active { transform: scale(.97); background: #3c3c3c; }
.cards-btn.primary { background: #fff; color: #111; font-weight: 600; }
.cards-btn.done { background: #1f2a2f; color: var(--accent); }
.cards-btn[disabled] { opacity: .55; }
.cards-btn svg { width: 17px; height: 17px; }
.cards-tile { width: 44px; height: 44px; border-radius: 12px; flex: none; display: grid; place-items: center; font-weight: 700; font-size: 20px; color: #fff;
  background: linear-gradient(140deg, var(--accent), var(--accent-2)); }
.cards-tile svg { width: 24px; height: 24px; }
.cards-note { font-size: 13px; color: var(--muted); }

/* weather */
.cards-weather { color: #fff; background: linear-gradient(165deg, #2f6fd1 0%, #2a4fa8 55%, #283a7a 100%); }
.cards-weather.w-cloud, .cards-weather.w-fog { background: linear-gradient(165deg, #4b5a70, #2c3646); }
.cards-weather.w-rain, .cards-weather.w-storm { background: linear-gradient(165deg, #33435c, #1d2433); }
.cards-weather.w-snow { background: linear-gradient(165deg, #6c7fa0, #3b4763); }
.cards-weather.w-night { background: linear-gradient(165deg, #1d2552, #121633); }
.cards-weather .cards-kicker { color: rgba(255,255,255,.8); }
.cards-wnow { display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; }
.cards-wtemp { font-size: 52px; font-weight: 250; line-height: 1; letter-spacing: -.02em; }
.cards-wcond { text-align: right; font-size: 15px; font-weight: 500; display: flex; flex-direction: column; align-items: flex-end; gap: 4px; }
.cards-wcond svg { width: 34px; height: 34px; }
.cards-whl { color: rgba(255,255,255,.85); font-size: 14px; font-weight: 500; }
.cards-whours { display: flex; gap: 4px; overflow-x: auto; scrollbar-width: none; border-top: 1px solid rgba(255,255,255,.16); padding-top: 10px; margin: 0 -4px; }
.cards-whours::-webkit-scrollbar { display: none; }
.cards-wh { flex: 1 0 44px; display: flex; flex-direction: column; align-items: center; gap: 5px; font-size: 13px; color: rgba(255,255,255,.9); }
.cards-wh svg { width: 22px; height: 22px; }
.cards-wh b { font-size: 15px; font-weight: 600; color: #fff; }

/* stock */
.cards-quote-row { display: flex; align-items: baseline; justify-content: space-between; gap: 10px; }
.cards-price { font-size: 30px; font-weight: 600; letter-spacing: -.01em; font-variant-numeric: tabular-nums; }
.cards-chg { padding: 4px 9px; border-radius: 8px; font-weight: 600; font-size: 14px; font-variant-numeric: tabular-nums; white-space: nowrap; }
.cards-chg.up { background: rgba(52, 199, 89, .16); color: #4cd964; }
.cards-chg.down { background: rgba(255, 106, 92, .16); color: #ff6a5c; }
.cards-chg.flat { background: #2c2c2c; color: var(--muted); }
.cards-spark { width: 100%; height: 56px; display: block; }

/* link */
.cards-link { padding: 0; gap: 0; }
.cards-link img { width: 100%; max-height: 170px; object-fit: cover; display: block; background: #1b1b1b; }
.cards-link .cards-body { padding: 12px 16px 14px; display: flex; flex-direction: column; gap: 5px; }
.cards-fav { width: 18px; height: 18px; border-radius: 5px; background: #3a3a3a; color: #fff; display: grid; place-items: center; font-size: 11px; font-weight: 700; flex: none; }

/* place */
.cards-pin { background: linear-gradient(140deg, #ff7a6b, #e0455c); }
.cards-stars { color: #ffcc4d; letter-spacing: 1px; font-size: 13px; }

/* event */
.cards-date { width: 52px; flex: none; border-radius: 12px; background: #2c2c2c; overflow: hidden; text-align: center; align-self: flex-start; }
.cards-date i { display: block; font-style: normal; font-size: 11px; font-weight: 700; letter-spacing: .08em; padding: 3px 0 2px; background: var(--accent); color: #062430; }
.cards-date b { display: block; font-size: 24px; font-weight: 600; padding: 2px 0 5px; }
.cards-meta { display: flex; flex-direction: column; gap: 3px; color: var(--muted); font-size: 14px; }
.cards-meta span { display: flex; gap: 6px; align-items: center; min-width: 0; overflow-wrap: anywhere; }
.cards-meta svg { width: 15px; height: 15px; flex: none; }
.cards-cal { display: inline-block; width: 8px; height: 8px; border-radius: 50%; background: var(--accent-2); flex: none; }

/* email */
.cards-av { width: 40px; height: 40px; border-radius: 50%; flex: none; display: grid; place-items: center; font-weight: 600; font-size: 17px; color: #fff; }
.cards-unread { width: 9px; height: 9px; border-radius: 50%; background: var(--accent); flex: none; }
.cards-subj { font-weight: 600; font-size: 16px; overflow-wrap: anywhere; }

/* checklist */
.cards-bar { height: 5px; border-radius: 3px; background: #333; overflow: hidden; }
.cards-bar i { display: block; height: 100%; border-radius: 3px; background: linear-gradient(90deg, var(--accent), var(--accent-2)); transition: width .3s var(--ease); }
.cards-items { display: flex; flex-direction: column; margin: 0 -4px; }
.cards-item { display: flex; align-items: center; gap: 12px; padding: 9px 4px; text-align: left; border-top: 1px solid #2c2c2c; width: 100%; font-size: 16px; }
.cards-item:first-child { border-top: 0; }
.cards-check { width: 24px; height: 24px; border-radius: 50%; border: 2px solid #555; flex: none; display: grid; place-items: center; transition: background .2s, border-color .2s; }
.cards-check svg { width: 14px; height: 14px; opacity: 0; color: #062430; }
.cards-item.on .cards-check { background: var(--accent); border-color: var(--accent); }
.cards-item.on .cards-check svg { opacity: 1; }
.cards-item.on .cards-itxt { color: var(--muted); text-decoration: line-through; text-decoration-color: #666; }
.cards-itxt { flex: 1; min-width: 0; overflow-wrap: anywhere; }

/* table */
.cards-scroll { overflow-x: auto; margin: 0 -16px; padding: 0 16px; -webkit-overflow-scrolling: touch; }
.cards-table { border-collapse: separate; border-spacing: 0; font-size: 14px; min-width: 100%; font-variant-numeric: tabular-nums; }
.cards-table th { text-align: left; font-weight: 600; color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: .04em; padding: 0 14px 8px 0; white-space: nowrap; }
.cards-table td { padding: 9px 14px 9px 0; border-top: 1px solid #2e2e2e; white-space: nowrap; max-width: 220px; overflow: hidden; text-overflow: ellipsis; }
.cards-table td.num, .cards-table th.num { text-align: right; }
.cards-table tr > :first-child { position: sticky; left: -16px; background: var(--card); padding-left: 0; font-weight: 500; }

/* steps */
.cards-steps { display: flex; flex-direction: column; gap: 0; position: relative; }
.cards-step { display: flex; gap: 12px; align-items: flex-start; padding: 6px 0; position: relative; }
.cards-step:not(:last-child)::after { content: ""; position: absolute; left: 11px; top: 30px; bottom: -6px; width: 2px; background: #333; }
.cards-step.done:not(:last-child)::after { background: rgba(79, 211, 255, .45); }
.cards-dot { width: 24px; height: 24px; border-radius: 50%; flex: none; display: grid; place-items: center; background: #2c2c2c; border: 2px solid #444; z-index: 1; }
.cards-dot svg { width: 13px; height: 13px; }
.cards-step.done .cards-dot { background: var(--accent); border-color: var(--accent); color: #062430; }
.cards-step.active .cards-dot { border-color: var(--accent); background: #10262e; }
.cards-step.active .cards-dot::before { content: ""; width: 8px; height: 8px; border-radius: 50%; background: var(--accent); animation: cardsPulse 1.4s ease-in-out infinite; }
.cards-step.failed .cards-dot { background: #3a1d1b; border-color: var(--danger); color: var(--danger); }
.cards-step.skipped .cards-stxt { color: var(--muted); text-decoration: line-through; }
.cards-step.pending .cards-stxt { color: #bdbdbd; }
.cards-stxt { padding-top: 2px; min-width: 0; overflow-wrap: anywhere; }
.cards-stxt small { display: block; color: var(--muted); font-size: 13px; }
@keyframes cardsPulse { 50% { transform: scale(.55); opacity: .6; } }
@media (prefers-reduced-motion: reduce) { .cards-step.active .cards-dot::before { animation: none; } }

/* choice */
.cards-opts { display: flex; flex-direction: column; margin: 0 -16px -15px; }
.cards-opt { display: flex; align-items: center; gap: 10px; padding: 13px 16px; border-top: 1px solid #2e2e2e; text-align: left; width: 100%; font-size: 16px; color: var(--accent); }
.cards-opt:active { background: #2a2a2a; }
.cards-opt span { flex: 1; min-width: 0; }
.cards-opt small { display: block; color: var(--muted); font-size: 13px; }
.cards-opt svg { width: 16px; height: 16px; color: #666; }
.cards-opts.used .cards-opt { color: var(--muted); pointer-events: none; }
.cards-opts.used .cards-opt.picked { color: var(--text); }
.cards-opts.used .cards-opt.picked svg { color: var(--accent); }

/* quote */
.cards-q { position: relative; padding-left: 16px; border-left: 3px solid var(--accent-2); font-size: 17px; line-height: 1.45; white-space: pre-wrap; overflow-wrap: anywhere; }
.cards-qsrc { color: var(--muted); font-size: 14px; }

/* gallery */
.cards-gal { padding: 4px; gap: 4px; }
.cards-grid { display: grid; gap: 3px; border-radius: 18px; overflow: hidden; }
.cards-grid.n1 { grid-template-columns: 1fr; }
.cards-grid.n2, .cards-grid.n4 { grid-template-columns: 1fr 1fr; }
.cards-grid.n3, .cards-grid.many { grid-template-columns: 1fr 1fr 1fr; }
.cards-grid img { width: 100%; aspect-ratio: 1; object-fit: cover; display: block; background: #1b1b1b; }
.cards-grid.n1 img { aspect-ratio: 4 / 3; }
.cards-gal .cards-kicker { padding: 8px 12px 6px; }

/* file */
.cards-ftile { width: 42px; height: 52px; border-radius: 8px; flex: none; background: #f2f2f2; color: #222; position: relative; display: grid; place-items: end center; padding-bottom: 7px; font-size: 10px; font-weight: 800; letter-spacing: .04em; }
.cards-ftile::after { content: ""; position: absolute; top: 0; right: 0; border-style: solid; border-width: 0 12px 12px 0; border-color: transparent var(--card) #c8c8c8 transparent; }
.cards-ftile.pdf { background: #ff6a5c; color: #fff; }
.cards-ftile.doc { background: #5b7cff; color: #fff; }
.cards-ftile.sheet { background: #34c759; color: #fff; }
.cards-ftile.slides { background: #ffb340; color: #3a2400; }

/* connect */
.cards-connect .cards-tile { font-size: 21px; }
.cards-connect ol { margin: 0; padding: 0 0 0 20px; display: flex; flex-direction: column; gap: 7px; font-size: 14.5px; color: #dcdcdc; }
.cards-connect ol li::marker { color: var(--accent); font-weight: 600; }
.cards-connect code { font: 13px ui-monospace, SFMono-Regular, Menlo, monospace; background: #2c2c2c; border-radius: 5px; padding: 1px 5px; color: #fff; overflow-wrap: anywhere; }
`;
  document.head.append(style);

  // ---------------------------------------------------------------- helpers
  const s = (tag, attrs, kids) => {
    const n = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs || {})) n.setAttribute(k, String(v));
    for (const k of kids || []) n.append(k);
    return n;
  };
  const icon = (paths, opts) => {
    opts = opts || {};
    const v = s("svg", {viewBox: "0 0 24 24", "aria-hidden": "true", fill: "none", stroke: "currentColor", "stroke-width": opts.w || 2,
      "stroke-linecap": "round", "stroke-linejoin": "round"});
    for (const p of paths) v.append(typeof p === "string" ? s("path", {d: p}) : p);
    return v;
  };
  const I = {
    check: () => icon(["M5 12.5l4.5 4.5L19 7.5"], {w: 3}),
    x: () => icon(["M7 7l10 10M17 7L7 17"], {w: 3}),
    chev: () => icon(["M9 5l7 7-7 7"], {w: 2.4}),
    pin: () => icon(["M12 21s-6.5-6.1-6.5-11a6.5 6.5 0 0113 0c0 4.9-6.5 11-6.5 11z", s("circle", {cx: 12, cy: 10, r: 2.3})]),
    clock: () => icon([s("circle", {cx: 12, cy: 12, r: 8}), "M12 8v4.5l3 2"]),
    nav: () => icon(["M4 11.5L20 4l-7.5 16-1.8-6.7z"]),
    out: () => icon(["M14 5h5v5M19 5l-8 8", "M18 14v4.5a1.5 1.5 0 01-1.5 1.5h-11A1.5 1.5 0 014 18.5v-11A1.5 1.5 0 015.5 6H10"]),
    reply: () => icon(["M10 8L5 12.5l5 4.5", "M5.5 12.5H14a5 5 0 015 5V19"]),
    plus: () => icon(["M12 5v14M5 12h14"], {w: 2.4}),
    globe: () => icon([s("circle", {cx: 12, cy: 12, r: 8.5}), "M3.5 12h17M12 3.5c2.5 2.6 3.6 5.4 3.6 8.5s-1.1 5.9-3.6 8.5c-2.5-2.6-3.6-5.4-3.6-8.5S9.5 6.1 12 3.5z"]),
    phone: () => icon(["M6.5 4h3l1.5 4-2 1.3a10 10 0 005.7 5.7L16 13l4 1.5v3a2 2 0 01-2.2 2A16 16 0 014.5 6.2 2 2 0 016.5 4z"]),
  };
  // weather glyphs, drawn in a 24 box
  const CLOUD = "M7 18.5h10a4 4 0 00.4-8 5.5 5.5 0 00-10.6 1.2A3.4 3.4 0 007 18.5z";
  const sunRays = (cx, cy, r) => { const out = []; for (let i = 0; i < 8; i++) { const a = i * Math.PI / 4, x1 = cx + Math.cos(a) * (r + 2.2), y1 = cy + Math.sin(a) * (r + 2.2), x2 = cx + Math.cos(a) * (r + 4), y2 = cy + Math.sin(a) * (r + 4); out.push(`M${x1.toFixed(1)} ${y1.toFixed(1)}L${x2.toFixed(1)} ${y2.toFixed(1)}`); } return out; };
  function wkind(cond) {
    const c = String(cond || "").toLowerCase();
    if (/thunder|storm|lightning/.test(c)) return "storm";
    if (/snow|sleet|flurr|blizzard|ice/.test(c)) return "snow";
    if (/rain|drizzle|shower/.test(c)) return "rain";
    if (/fog|mist|haze|smoke/.test(c)) return "fog";
    if (/night|moon|clear night/.test(c)) return "night";
    if (/partly|mostly sunny|some sun|intervals|scattered/.test(c)) return "partly";
    if (/cloud|overcast|grey|gray/.test(c)) return "cloud";
    if (/wind|breez|gust/.test(c)) return "wind";
    return "sun";
  }
  function wicon(kind) {
    const fill = {fill: "currentColor", stroke: "none"};
    const sunC = s("circle", Object.assign({cx: 12, cy: 12, r: 4.6}, {fill: "#ffd54a", stroke: "none"}));
    if (kind === "sun") { const v = icon(sunRays(12, 12, 4.6)); v.setAttribute("stroke", "#ffd54a"); v.prepend(sunC); return v; }
    if (kind === "night") return icon([s("path", Object.assign({d: "M15.5 4.5a7.5 7.5 0 104 13.6A8 8 0 0115.5 4.5z"}, {fill: "#e9edff", stroke: "none"}))]);
    if (kind === "partly") {
      const v = s("svg", {viewBox: "0 0 24 24", "aria-hidden": "true"});
      v.append(s("circle", {cx: 9, cy: 8.5, r: 3.6, fill: "#ffd54a"}));
      for (const d of sunRays(9, 8.5, 3.6).slice(4, 8)) v.append(s("path", {d, stroke: "#ffd54a", "stroke-width": 1.8, "stroke-linecap": "round"}));
      v.append(s("path", {d: CLOUD, fill: "#f4f6fb", transform: "translate(1.5 1.5) scale(.92)"}));
      return v;
    }
    const v = s("svg", {viewBox: "0 0 24 24", "aria-hidden": "true"});
    if (kind === "fog") { for (const [y, w] of [[8, 16], [12, 13], [16, 16]]) v.append(s("path", {d: `M${12 - w / 2} ${y}h${w}`, stroke: "#e6e9f0", "stroke-width": 2, "stroke-linecap": "round"})); return v; }
    if (kind === "wind") { v.append(s("path", {d: "M3.5 9h11a2.5 2.5 0 10-2.5-2.5M3.5 13h15a2.5 2.5 0 11-2.5 2.5M3.5 17h7", fill: "none", stroke: "#e6e9f0", "stroke-width": 2, "stroke-linecap": "round"})); return v; }
    v.append(s("path", {d: CLOUD, fill: "#f4f6fb", transform: kind === "cloud" ? "" : "translate(0 -3)"}));
    if (kind === "rain") for (const x of [8.5, 12, 15.5]) v.append(s("path", {d: `M${x} 18l-1 3`, stroke: "#7cc7ff", "stroke-width": 2, "stroke-linecap": "round"}));
    if (kind === "snow") for (const x of [8.5, 12, 15.5]) v.append(s("circle", {cx: x, cy: 19.5, r: 1.2, fill: "#fff"}));
    if (kind === "storm") v.append(s("path", Object.assign({d: "M12.5 15l-2.5 4h3l-1.5 3.5"}, {stroke: "#ffd54a", "stroke-width": 2, fill: "none", "stroke-linecap": "round", "stroke-linejoin": "round"})));
    void fill;
    return v;
  }

  // https:// anywhere, or a same-site /api/ path; anything else -> null (never javascript:, data:, http:)
  function href(u) {
    if (!u) return null;
    try {
      const x = new URL(String(u), location.href);
      if (x.protocol === "https:") return x.href;
      if (x.origin === location.origin && x.pathname.startsWith("/api/")) return x.pathname + x.search;
    } catch (e) {}
    return null;
  }
  function imgSrc(u) {
    const v = String(u || "");
    if (/^\/api\/(media|uploads)\/[A-Za-z0-9._-]{1,80}$/.test(v) && !v.includes("..")) return v;
    if (/^data:image\/(png|jpeg|gif|webp);base64,[A-Za-z0-9+/=]+$/.test(v)) return v;
    return null;
  }
  function link(url, cls, kids) {
    const h = href(url);
    const a = el(h ? "a" : "div", cls);
    if (h) { a.href = h; if (/^https:/.test(h)) { a.target = "_blank"; a.rel = "noopener noreferrer"; } }
    for (const k of kids || []) if (k) a.append(k);
    return a;
  }
  function btn(label, opts) {
    opts = opts || {};
    const h = opts.href ? href(opts.href) : null;
    const b = el(h ? "a" : "button", "cards-btn" + (opts.primary ? " primary" : ""));
    if (h) { b.href = h; if (/^https:/.test(h)) { b.target = "_blank"; b.rel = "noopener noreferrer"; } }
    else b.type = "button";
    if (opts.icon) b.append(opts.icon);
    b.append(document.createTextNode(label));
    if (opts.onClick) b.addEventListener("click", opts.onClick);
    return b;
  }
  const wrap = (cls, kids) => { const n = el("div", "cards-in " + (cls || "")); for (const k of kids) if (k) n.append(k); return n; };
  const kicker = (text, lead) => { const k = el("div", "cards-kicker"); if (lead) k.append(lead); k.append(el("span", null, text)); return k; };
  const num = (v, d) => (typeof v === "number" && isFinite(v) ? v : d);
  const fmt = (v, digits) => Number(v).toLocaleString(undefined, {minimumFractionDigits: digits, maximumFractionDigits: digits});
  const demoNote = () => T.toast("Demo mode: nothing was saved.");
  const sendText = (text, show) => { if (T.state.demo && !T.state.authed) return; T.send(text, show ? {show} : undefined); };
  const hue = str => { let h = 0; for (const c of String(str)) h = (h * 31 + c.charCodeAt(0)) >>> 0; return 190 + (h % 70); }; // cyan..indigo

  // ---------------------------------------------------------------- the renderers
  const R = {};

  R.weather = c => {
    const kind = wkind(c.condition), unit = c.unit === "C" ? "°C" : "°";
    const n = wrap("cards-weather w-" + (kind === "partly" || kind === "sun" || kind === "wind" ? "sun" : kind));
    n.append(kicker(c.place, I.pin()));
    const now = el("div", "cards-wnow"), cond = el("div", "cards-wcond");
    now.append(el("div", "cards-wtemp", Math.round(num(c.temp, 0)) + "°"));
    cond.append(wicon(kind), el("span", null, c.condition || ""));
    if (c.hi != null || c.lo != null) cond.append(el("span", "cards-whl", [c.hi != null ? "H:" + Math.round(c.hi) + unit : "", c.lo != null ? "L:" + Math.round(c.lo) + unit : ""].filter(Boolean).join("  ")));
    now.append(cond); n.append(now);
    if (Array.isArray(c.hourly) && c.hourly.length) {
      const row = el("div", "cards-whours");
      for (const h of c.hourly.slice(0, 8)) { const x = el("div", "cards-wh"); x.append(el("span", null, h.time), wicon(wkind(h.condition || c.condition)), el("b", null, Math.round(num(h.temp, 0)) + "°")); row.append(x); }
      n.append(row);
    }
    if (c.as_of) { const a = el("div", "cards-note", c.as_of); a.style.color = "rgba(255,255,255,.7)"; n.append(a); }
    n.setAttribute("aria-label", `Weather in ${c.place}: ${Math.round(num(c.temp, 0))} degrees, ${c.condition || ""}`);
    return n;
  };

  let gid = 0;
  function spark(points, up) {
    const W = 300, H = 56, pad = 3, lo = Math.min(...points), hi = Math.max(...points), span = hi - lo || 1;
    const xy = points.map((p, i) => [pad + i * (W - 2 * pad) / (points.length - 1), pad + (H - 2 * pad) * (1 - (p - lo) / span)]);
    const line = xy.map((p, i) => (i ? "L" : "M") + p[0].toFixed(1) + " " + p[1].toFixed(1)).join("");
    const color = up ? "#4cd964" : "#ff6a5c", id = "cards-g" + (++gid);
    const v = s("svg", {class: "cards-spark", viewBox: `0 0 ${W} ${H}`, preserveAspectRatio: "none", "aria-hidden": "true"});
    const grad = s("linearGradient", {id, x1: 0, y1: 0, x2: 0, y2: 1}, [s("stop", {offset: "0", "stop-color": color, "stop-opacity": ".32"}), s("stop", {offset: "1", "stop-color": color, "stop-opacity": "0"})]);
    v.append(s("defs", {}, [grad]), s("path", {d: line + `L${xy[xy.length - 1][0].toFixed(1)} ${H}L${xy[0][0].toFixed(1)} ${H}Z`, fill: `url(#${id})`}),
      s("path", {d: line, fill: "none", stroke: color, "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round", "vector-effect": "non-scaling-stroke"}));
    return v;
  }
  R.stock = c => {
    const pct = typeof c.change_pct === "number" ? c.change_pct : null;
    const pts = Array.isArray(c.points) ? c.points.filter(p => typeof p === "number" && isFinite(p)) : [];
    const up = pct != null ? pct >= 0 : pts.length > 1 ? pts[pts.length - 1] >= pts[0] : true;
    const head = el("div", "cards-row"), t = el("div", "cards-grow");
    t.append(el("div", "cards-title", c.symbol), el("div", "cards-sub", c.name || ""));
    head.append(t);
    if (c.as_of) head.append(el("div", "cards-note", c.as_of));
    const row = el("div", "cards-quote-row"), cur = c.currency && c.currency !== "USD" ? " " + c.currency : "";
    row.append(el("div", "cards-price", (c.currency === "USD" || !c.currency ? "$" : "") + fmt(c.price, Math.abs(c.price) < 1 ? 4 : 2) + cur));
    if (pct != null || c.change != null) {
      const txt = [c.change != null ? (c.change >= 0 ? "+" : "−") + fmt(Math.abs(c.change), 2) : "", pct != null ? "(" + (pct >= 0 ? "+" : "−") + fmt(Math.abs(pct), 2) + "%)" : ""].filter(Boolean).join(" ");
      row.append(el("span", "cards-chg " + (pct === 0 ? "flat" : up ? "up" : "down"), txt));
    }
    const n = wrap("cards-stock", [head, row, pts.length > 1 ? spark(pts, up) : null]);
    n.setAttribute("aria-label", `${c.symbol} ${c.price}${pct != null ? ", " + pct + " percent" : ""}`);
    return n;
  };

  R.link = c => {
    const src = imgSrc(c.image), body = el("div", "cards-body");
    const fav = el("span", "cards-fav", (c.site || "?").replace(/^www\./, "").slice(0, 1).toUpperCase());
    body.append(kicker(c.site || "", fav), el("div", "cards-title", c.title));
    if (c.summary) body.append(el("div", "cards-sub cards-clamp", c.summary));
    let img = null;
    if (src) { img = document.createElement("img"); img.src = src; img.alt = ""; img.loading = "lazy"; img.addEventListener("error", () => img.remove(), {once: true}); }
    const a = link(c.url, "cards-in cards-link", [img, body]);
    a.setAttribute("aria-label", `${c.title}, ${c.site || ""}`);
    return a;
  };

  R.place = c => {
    const head = el("div", "cards-row"), tile = el("div", "cards-tile cards-pin"), t = el("div", "cards-grow");
    tile.append(I.pin());
    t.append(el("div", "cards-title", c.name));
    const sub = [];
    if (c.category) sub.push(c.category);
    const line = el("div", "cards-sub", sub.join(" · "));
    if (typeof c.rating === "number") { const st = el("span", "cards-stars", "★★★★★".slice(0, Math.round(c.rating)) + "☆☆☆☆☆".slice(0, 5 - Math.round(c.rating))); line.append(sub.length ? " · " : "", st, " " + fmt(c.rating, 1)); }
    if (line.textContent) t.append(line);
    head.append(tile, t);
    const meta = el("div", "cards-meta");
    if (c.address) { const x = el("span"); x.append(I.pin(), document.createTextNode(c.address)); meta.append(x); }
    if (c.hours) { const x = el("span"); x.append(I.clock(), document.createTextNode(c.hours)); meta.append(x); }
    const btns = el("div", "cards-btns");
    btns.append(btn("Directions", {primary: true, href: c.directions, icon: I.nav()}));
    if (c.url) btns.append(btn("Website", {href: c.url, icon: I.globe()}));
    return wrap("cards-place", [head, meta.children.length ? meta : null, btns]);
  };

  function when(c) {
    const st = new Date(c.start), en = c.end ? new Date(c.end) : null;
    if (isNaN(st)) return {month: "", day: "", text: c.start};
    if (c.all_day) {
      const d = new Date(c.start + "T12:00:00");
      return {month: d.toLocaleDateString([], {month: "short"}).toUpperCase(), day: String(d.getDate()), text: d.toLocaleDateString([], {weekday: "long", month: "long", day: "numeric"}) + " · all day"};
    }
    const tm = d => d.toLocaleTimeString([], {hour: "numeric", minute: "2-digit"});
    return {month: st.toLocaleDateString([], {month: "short"}).toUpperCase(), day: String(st.getDate()),
      text: st.toLocaleDateString([], {weekday: "short", month: "short", day: "numeric"}) + " · " + tm(st) + (en && !isNaN(en) ? " – " + tm(en) : "")};
  }
  R.event = (c, m) => {
    const w = when(c), head = el("div", "cards-row"), tile = el("div", "cards-date"), t = el("div", "cards-grow");
    tile.append(el("i", null, w.month), el("b", null, w.day));
    t.append(el("div", "cards-title", c.title));
    const meta = el("div", "cards-meta");
    const tl = el("span"); tl.append(I.clock(), document.createTextNode(w.text)); meta.append(tl);
    if (c.location) { const x = el("span"); x.append(I.pin(), document.createTextNode(c.location)); meta.append(x); }
    if (c.calendar) { const x = el("span"); x.append(el("i", "cards-cal"), document.createTextNode(c.calendar)); meta.append(x); }
    t.append(meta);
    head.append(tile, t);
    const btns = el("div", "cards-btns");
    const key = "cards:added:" + (m && m.id) + ":" + c.title + c.start;
    if (c.add) {
      const b = btn("Add to calendar", {primary: true, icon: I.plus()});
      const added = () => { b.replaceChildren(I.check(), document.createTextNode("Added")); b.classList.remove("primary"); b.classList.add("done"); b.disabled = true; };
      if (T.store(key)) added();
      b.addEventListener("click", async () => {
        if (b.disabled) return;
        if (T.state.demo) { demoNote(); added(); return; }
        b.disabled = true;
        try { const r = await T.post("/api/calendar/events", c.add); T.store(key, "1"); added(); T.toast(r && r.where === "google" ? "Added to Google Calendar." : "Added to your calendar in Theta."); }
        catch (e) { b.disabled = false; T.toast("Couldn't add it: " + (e.status ? "HTTP " + e.status : e.message || e)); }
      });
      btns.append(b);
    }
    if (c.url) btns.append(btn("Open", {href: c.url, icon: I.out()}));
    return wrap("cards-event", [head, btns.children.length ? btns : null]);
  };

  R.email = c => {
    const who = (c.from || c.to || "?").replace(/<.*?>/, "").replace(/"/g, "").trim() || "?";
    const av = el("div", "cards-av", who.slice(0, 1).toUpperCase());
    av.style.background = `linear-gradient(140deg, hsl(${hue(who)} 70% 52%), hsl(${hue(who) + 30} 65% 42%))`;
    const head = el("div", "cards-row"), t = el("div", "cards-grow");
    t.append(el("div", "cards-title", who), el("div", "cards-sub", [c.to && c.from ? "to " + c.to.replace(/<.*?>/, "").trim() : "", c.date || ""].filter(Boolean).join(" · ")));
    head.append(av, t);
    if (c.unread) head.append(el("span", "cards-unread"));
    const body = el("div");
    body.append(el("div", "cards-subj", c.subject));
    if (c.snippet) body.append(el("div", "cards-sub cards-clamp", c.snippet));
    const btns = el("div", "cards-btns");
    const desc = `the email from ${who} about "${c.subject}"`;
    btns.append(c.url ? btn("Open", {href: c.url, icon: I.out()}) : btn("Open", {icon: I.out(), onClick: () => sendText(`Open ${desc}${c.id ? " (id " + c.id + ")" : ""} and show me all of it.`, "Open the email")}));
    btns.append(btn("Reply", {primary: true, icon: I.reply(), onClick: () => sendText(`Help me reply to ${desc}${c.id ? " (id " + c.id + ")" : ""}.`, "Reply to " + who)}));
    return wrap("cards-email", [head, body, btns]);
  };

  R.checklist = (c, m) => {
    const items = (c.items || []).map(x => ({text: x.text, done: !!x.done}));
    const ci = m && m.meta && Array.isArray(m.meta.cards) ? m.meta.cards.indexOf(c) : 0;
    const head = el("div", "cards-row"), t = el("div", "cards-grow"), count = el("div", "cards-note");
    t.append(el("div", "cards-title", c.title || "Checklist"));
    head.append(t, count);
    const bar = el("div", "cards-bar"), fill = el("i"); bar.append(fill);
    const list = el("div", "cards-items");
    const sync = () => { const n = items.filter(x => x.done).length; count.textContent = `${n} of ${items.length}`; fill.style.width = (items.length ? 100 * n / items.length : 0) + "%"; };
    items.forEach((it, i) => {
      const row = el("button", "cards-item" + (it.done ? " on" : "")); row.type = "button";
      row.setAttribute("role", "checkbox"); row.setAttribute("aria-checked", String(it.done));
      const box = el("span", "cards-check"); box.append(I.check());
      row.append(box, el("span", "cards-itxt", it.text));
      row.addEventListener("click", async () => {
        it.done = !it.done; row.classList.toggle("on", it.done); row.setAttribute("aria-checked", String(it.done)); sync();
        if (T.state.demo || !m || m.id == null) return;
        try { await T.post("/api/cards/checklist", {message_id: m.id, card: Math.max(0, ci), item: i, done: it.done}); if (m.meta.cards[ci]) m.meta.cards[ci].items[i].done = it.done; }
        catch (e) { it.done = !it.done; row.classList.toggle("on", it.done); row.setAttribute("aria-checked", String(it.done)); sync(); T.toast("Couldn't save that tick. Try again."); }
      });
      list.append(row);
    });
    sync();
    return wrap("cards-checklist", [head, bar, list]);
  };

  R.table = c => {
    const cols = c.columns || [], rows = c.rows || [];
    const numeric = cols.map((_, j) => rows.length && rows.every(r => typeof r[j] === "number" || /^[-+−$€£]?[\d.,]+%?$/.test(String(r[j] || "").trim()) || r[j] === ""));
    const tb = el("table", "cards-table"), thead = el("thead"), hr = el("tr");
    cols.forEach((h, j) => hr.append(el("th", numeric[j] && j ? "num" : null, h)));
    thead.append(hr); tb.append(thead);
    const body = el("tbody");
    for (const r of rows) { const tr = el("tr"); cols.forEach((_, j) => { const v = r[j]; tr.append(el("td", numeric[j] && j ? "num" : null, typeof v === "number" ? v.toLocaleString() : String(v == null ? "" : v))); }); body.append(tr); }
    tb.append(body);
    const sc = el("div", "cards-scroll"); sc.append(tb);
    return wrap("cards-tablecard", [c.title ? el("div", "cards-title", c.title) : null, sc, c.caption ? el("div", "cards-note", c.caption) : null]);
  };

  R.steps = c => {
    const steps = c.steps || [], n = steps.filter(x => x.state === "done" || x.state === "skipped").length;
    const failed = steps.some(x => x.state === "failed"), active = steps.some(x => x.state === "active");
    const head = el("div", "cards-row"), t = el("div", "cards-grow");
    t.append(el("div", "cards-title", c.title));
    head.append(t, el("div", "cards-note", failed ? "Stopped" : n === steps.length ? "Done" : active ? `${n} of ${steps.length}` : `${n} of ${steps.length}`));
    const bar = el("div", "cards-bar"), fill = el("i"); fill.style.width = (steps.length ? 100 * n / steps.length : 0) + "%"; bar.append(fill);
    const list = el("div", "cards-steps");
    for (const st of steps) {
      const row = el("div", "cards-step " + st.state), dot = el("span", "cards-dot");
      if (st.state === "done") dot.append(I.check()); else if (st.state === "failed") dot.append(I.x());
      const tx = el("div", "cards-stxt", st.text); if (st.detail) tx.append(el("small", null, st.detail));
      row.append(dot, tx); list.append(row);
    }
    return wrap("cards-stepscard", [head, bar, list, c.note ? el("div", "cards-note", c.note) : null]);
  };

  R.choice = (c, m) => {
    const key = "cards:choice:" + (m && m.id) + ":" + c.question, used = T.store(key);
    const list = el("div", "cards-opts" + (used ? " used" : ""));
    for (const o of c.options || []) {
      const b = el("button", "cards-opt" + (used === o.label ? " picked" : "")); b.type = "button";
      const tx = el("span", null, o.label); if (o.detail) tx.append(el("small", null, o.detail));
      b.append(tx, used === o.label ? I.check() : I.chev());
      b.addEventListener("click", () => {
        if (list.classList.contains("used") || T.state.streaming) return;
        list.classList.add("used"); b.classList.add("picked"); b.lastChild.replaceWith(I.check()); T.store(key, o.label);
        sendText(o.value || o.label, o.label);
      });
      list.append(b);
    }
    return wrap("cards-choice", [el("div", "cards-title", c.question), list]);
  };

  R.quote = c => {
    const src = el("div", "cards-qsrc");
    if (c.source) { const h = href(c.url); if (h) src.append("— ", link(c.url, null, [document.createTextNode(c.source)])); else src.textContent = "— " + c.source; }
    return wrap("cards-quotecard", [el("blockquote", "cards-q", c.text), c.source ? src : null]);
  };
  // blockquote default margins
  style.textContent += ".cards-q { margin: 0; }";

  R.gallery = c => {
    const imgs = (c.images || []).map(x => ({src: imgSrc(x.src), alt: x.alt || ""})).filter(x => x.src);
    if (!imgs.length) return null;
    const grid = el("div", "cards-grid " + (imgs.length <= 4 ? "n" + imgs.length : "many"));
    for (const x of imgs.slice(0, 12)) {
      const img = document.createElement("img"); img.src = x.src; img.alt = x.alt; img.loading = "lazy"; img.decoding = "async";
      img.addEventListener("error", () => { img.style.visibility = "hidden"; }, {once: true});
      grid.append(/^\/api\//.test(x.src) ? link(x.src, null, [img]) : img);
    }
    return wrap("cards-gal", [c.title ? kicker(c.title) : null, grid]);
  };

  function size(b) {
    if (typeof b !== "number") return "";
    const u = ["B", "KB", "MB", "GB"]; let i = 0, v = b;
    while (v >= 1000 && i < u.length - 1) { v /= 1024; i++; }
    return (i ? v.toFixed(v < 10 ? 1 : 0) : v) + " " + u[i];
  }
  R.file = c => {
    const ext = (c.name.match(/\.([a-z0-9]{1,5})$/i) || [, ""])[1].toLowerCase();
    const k = String(c.kind || "").toLowerCase();
    const cls = ext === "pdf" || /pdf/.test(k) ? "pdf" : /doc|word|txt|md/.test(ext + k) ? "doc" : /xls|csv|sheet/.test(ext + k) ? "sheet" : /ppt|key|slide/.test(ext + k) ? "slides" : "";
    const tile = el("div", "cards-ftile " + cls, (ext || (c.kind || "file")).slice(0, 4).toUpperCase());
    const t = el("div", "cards-grow");
    t.append(el("div", "cards-title", c.name), el("div", "cards-sub", [c.kind, size(c.size), c.note].filter(Boolean).join(" · ")));
    const row = el("div", "cards-row"); row.append(tile, t);
    if (href(c.url)) row.append(I.chev());
    const a = link(c.url, "cards-in cards-file", [row]);
    a.setAttribute("aria-label", "File: " + c.name);
    return a;
  };

  // `code` spans for env var names inside a step (FOO_BAR=...), plain text otherwise
  function stepText(text) {
    const li = el("li");
    const parts = String(text).split(/(\b[A-Z][A-Z0-9]*_[A-Z0-9_]+(?:=[^\s,)]*)?)/);
    parts.forEach((p, i) => { if (!p) return; li.append(i % 2 ? el("code", null, p) : document.createTextNode(p)); });
    return li;
  }
  R.connect = c => {
    const head = el("div", "cards-row"), tile = el("div", "cards-tile", (c.letter || (c.name || "?")[0] || "?").slice(0, 1)), t = el("div", "cards-grow");
    t.append(el("div", "cards-title", c.title || "Connect " + (c.name || c.service)), el("div", "cards-sub", c.why || ""));
    head.append(tile, t);
    const btns = el("div", "cards-btns"), steps = Array.isArray(c.steps) ? c.steps : [];
    const url = typeof c.action === "string" && /^\/api\/[A-Za-z0-9/_-]+$/.test(c.action) ? c.action : null;
    let ol = null;
    if (url) {
      const b = btn("Connect", {primary: true});
      b.addEventListener("click", () => { if (T.state.demo) { T.toast("Demo mode: on Theta this opens " + (c.name || "the service") + "'s sign-in."); return; } location.href = url; });
      btns.append(b);
    }
    if (steps.length) {
      ol = el("ol"); ol.hidden = true; for (const st of steps) ol.append(stepText(st));
      const b = btn(url ? "Setup steps" : "How to set it up", {primary: !url});
      b.setAttribute("aria-expanded", "false");
      b.addEventListener("click", () => { ol.hidden = !ol.hidden; b.setAttribute("aria-expanded", String(!ol.hidden)); b.textContent = ol.hidden ? (url ? "Setup steps" : "How to set it up") : "Hide the steps"; });
      btns.append(b);
    }
    const n = wrap("cards-connect", [head, btns.children.length ? btns : null, ol]);
    n.dataset.service = c.service || "";
    return n;
  };

  for (const [type, fn] of Object.entries(R)) T.card(type, fn);

  // ---------------------------------------------------------------- demo: one reply per card type
  // Adds messages to the demo backend's list (ThetaDemo.add when demo.js offers it; otherwise its own ids) and
  // tells the app to check its inbox, like a push.
  let demoId = 900000;
  const extra = [];
  function demoAdd(role, text, meta) {
    const D = window.ThetaDemo;
    if (D && typeof D.add === "function") return D.add(role, text, meta || {});
    const m = {id: demoId++, bot: "theta", role, text, t: Math.floor(Date.now() / 1000), meta: meta || {}};
    extra.push(m);
    return m;
  }
  function patchDemo() {
    const D = window.ThetaDemo;
    if (!D || D.__cards) return;
    D.__cards = true;
    const orig = D.fetch;
    D.fetch = async (input, init) => {
      const u = new URL(typeof input === "string" ? input : input.url, location.href);
      const r = await orig(input, init);
      if (!extra.length || !/^\/api\/(inbox|messages)$/.test(u.pathname)) return r;
      const j = await r.json(), since = Number(u.searchParams.get("since")) || 0;
      const add = extra.filter(m => u.pathname === "/api/messages" || m.id > since);
      j.messages = (j.messages || []).concat(add.filter(m => !(j.messages || []).some(x => x.id === m.id)));
      return new Response(JSON.stringify(j), {status: 200, headers: {"content-type": "application/json"}});
    };
  }
  T.cards = {href, imgSrc, demoAdd, patchDemo, render: (c, m) => (R[c.type] ? R[c.type](c, m || {meta: {cards: [c]}}) : null)};

  const SAMPLES = [
    ["It's sunny and cold right now, warming up nicely by early afternoon.", {type: "weather", place: "Denver", temp: 31, condition: "Sunny", hi: 44, lo: 22, unit: "F",
      hourly: [{time: "Now", temp: 31, condition: "sunny"}, {time: "11 AM", temp: 35, condition: "sunny"}, {time: "12 PM", temp: 39, condition: "partly cloudy"}, {time: "1 PM", temp: 42, condition: "partly cloudy"}, {time: "2 PM", temp: 44, condition: "cloudy"}, {time: "3 PM", temp: 43, condition: "snow"}]}],
    ["Apple's up a bit today.", {type: "stock", symbol: "AAPL", name: "Apple Inc.", price: 231.42, change: 2.83, change_pct: 1.24, points: [226.1, 227.4, 226.8, 228.9, 228.2, 229.6, 230.1, 229.4, 230.8, 231.42], as_of: "4:00 PM ET"}],
    ["This is the clearest write-up I found.", {type: "link", url: "https://www.weather.gov/bou/", title: "Winter storm watch for the Front Range", site: "weather.gov", summary: "Snow begins Thursday afternoon, with 4 to 8 inches likely above 6,000 feet and gusty north winds."}],
    ["It's ten minutes from you.", {type: "place", name: "Sweet Bloom Coffee", category: "Coffee shop", rating: 4.6, address: "1619 Reed St, Lakewood, CO", hours: "Open until 3 PM", url: "https://sweetbloomcoffee.com", directions: "https://www.google.com/maps/dir/?api=1&destination=Sweet%20Bloom%20Coffee"}],
    ["Want it on your calendar?", {type: "event", title: "Dentist", start: "2026-11-27T10:30:00-07:00", end: "2026-11-27T11:15:00-07:00", location: "Colfax Dental, 1200 E Colfax Ave", calendar: "Personal", add: {title: "Dentist", date: "2026-11-27", time: "10:30", duration: 45, location: "Colfax Dental"}}],
    ["One that looks like it needs you.", {type: "email", from: "Sam Rivera <sam@example.com>", subject: "Hub install on Saturday?", snippet: "Hey! Are we still on for the hub install this Saturday? I can bring the ladder and the extra cable.", date: "9:12 AM", unread: true}],
    ["Here's the packing list. Tick things off as you go.", {type: "checklist", id: "demo1", title: "Weekend trip", items: [{text: "Charger and cables", done: true}, {text: "Hiking boots", done: true}, {text: "Rain jacket", done: false}, {text: "Snacks for the drive", done: false}]}],
    ["Side by side:", {type: "table", title: "Mirrorless cameras", columns: ["Model", "Price", "Weight", "Battery"], rows: [["Fujifilm X-T5", "$1,699", "557 g", "580 shots"], ["Sony A7C II", "$2,198", "514 g", "540 shots"], ["Canon R8", "$1,499", "461 g", "290 shots"]], caption: "Prices from the makers' stores today."}],
    ["Here's where the move stands.", {type: "steps", title: "Moving the router", steps: [{text: "Found a new spot", state: "done"}, {text: "Ordered a 10 m cable", state: "done", detail: "Arrives Friday"}, {text: "Set up the mesh point", state: "active"}, {text: "Test speeds upstairs", state: "pending"}]}],
    ["Which works better?", {type: "choice", question: "When should I remind you about the dentist?", options: [{label: "Tonight at 8", value: "Remind me tonight at 8 about the dentist"}, {label: "Tomorrow at 9", value: "Remind me tomorrow at 9 about the dentist"}, {label: "An hour before", value: "Remind me an hour before the dentist"}]}],
    ["The line you were thinking of:", {type: "quote", text: "The best way to get started is to quit talking and begin doing.", source: "Walt Disney"}],
    ["Here are the ones you sent.", {type: "gallery", title: "From your trip", images: [{src: "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAACgAAAAoCAIAAAADnC86AAAA30lEQVR42sXCASoDAABA0X8cpZRSSimllFJqpZRSSilFRDRZExERERFRSimlVtpmjDHGGGOMMZRyEcf4r0dF/7eSysEvJVXDZSXVo59KasY+lNSGSkrqJt6V1E+9KWmYKSppnHtV0rTwoqR5qaCkZeVZSevak5LARl5J29ajkvadByUduzklnXv3Srr275R0H2SV9BzeKumN3CjpO8ooGYhdKxlKXCkZSaaVBFOXSsbTF0rCmZSSyey5kuncmZLZfFLJfOFUyWLxRMlyKaFktXysZP0nrmTzN6Zk+y+q/AcioGqGtB7RAQAAAABJRU5ErkJggg==", alt: "Sky"}, {src: "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAACgAAAAoCAIAAAADnC86AAAA0UlEQVR42sXCaS8CAACA4ffXuc/IfV858p0kSZKkklSSmJmZmZmZmZlZM/Oz/Iz32cPfRouS381WJT+RNiXNrXYl39EOJV/bnUo+Y11KPna6lbzHe5S87fYqeU30KXnZ61fynAwoedofUPKYGlTycBBUcp8eUnJ3OKzkNjOi5OZoVMl1dkxJ43hcST03oaSWn1RSLUwpKZ9MKykVZ5QUT2eVFEpzSnJn80qy5QUlmcqiknR1SUnqPKQkWVtWkrhYURKvryqJXa4piTbCSiJX68p/Fk+GCNHE+L0AAAAASUVORK5CYII=", alt: "Trail"}, {src: "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAACgAAAAoCAIAAAADnC86AAAA2klEQVR42sXCi0YDAABA0fsRPde7td7PtVWrP0mSJEmSJEmSmZmZmZmZmZmZmSRJkiRJkiR9Up9xj0PbelxJ+0ZCScdmUknnVkpJ13ZaSfdORklgN6ukZy+npHc/r6TvoKCk/7CoZOCopGTwuKxk6KSiZPi0qiR4VlMycl5XErpoKBm9bCoZu2opGY9fK5lI3CiZTN4qmUrdKZlO3yuZyTwomc0+KpnLPSmZzz8rWSi8KAkXX5Uslt6URMrvSqKVDyVL1U8ly7UvJSv1byWxxo+S1eavkrXWn/IfCpM92e76JOsAAAAASUVORK5CYII=", alt: "Lake"}]}],
    ["The lease is in your Drive.", {type: "file", name: "Lease agreement 2026.pdf", size: 482133, kind: "PDF", url: "https://drive.google.com/", note: "Edited yesterday"}],
    ["Gmail isn't connected, so I couldn't check your inbox. Nothing was read.", {type: "connect", service: "google", name: "Google", letter: "G", title: "Connect Google", why: "Gmail, Calendar and Drive need your Google sign-in. One sign-in covers all three.", action: "/api/google/start"}],
    ["Phone calls aren't set up on this server, so I didn't call anyone.", {type: "connect", service: "twilio", name: "Phone calls", letter: "T", title: "Set up phone calls", why: "Calls go through Twilio, and this server has no Twilio account yet.", action: "settings",
      steps: ["Make a Twilio account at twilio.com and buy a number with Voice.", "In Railway, open your Theta service, then the Variables tab, and add TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN and TWILIO_FROM=+15551234567.", "Railway stages the change: tap Deploy to apply it."]}],
  ];
  if (Q.get("cards") === "1") {
    const go = () => {
      if (!T.state.demo) return;
      patchDemo();
      for (const [text, card] of SAMPLES) demoAdd("assistant", text, {cards: [card], model: "deepseek-chat", tier: "quick"});
      window.dispatchEvent(new Event("protos:inbox"));
    };
    const wait = () => (T.state.ready ? go() : setTimeout(wait, 150));
    wait();
  }
})();
