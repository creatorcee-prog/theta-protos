/* home: the opening screen's extras under Theta's globe (server/home.py, server/home_extras.py), in the layout the user
   picks (from the Home Lab, generation 1): classic (the feed), dock, bento, sheet, satellites or today, in three sizes.
   The extras are calendar (opens the in-app calendar), Vantage (greyed until it's ready), recommended settings,
   today's reminders, approvals, chips, finds, stories and weather; the server orders them for this person and hides
   empty ones. The globe stays the main button in every layout. Settings > General > Home picks the layout, size and
   extras. Refreshes each time Home shows. DOM nodes only. */
(() => {
  "use strict";
  const T = window.Theta;
  if (!T) return;
  const {el} = T;
  const $ = id => document.getElementById(id);

  const css = document.createElement("style");
  css.textContent = `
#home .home-mid { bottom: 0; overflow-y: auto; overflow-x: hidden; align-content: start; -webkit-overflow-scrolling: touch;
  padding-bottom: calc(var(--home-bottom-h, calc(var(--sab) + 150px)) + 16px); scrollbar-width: none; }
#home .home-mid::-webkit-scrollbar { display: none; }
#home.has-feed .home-bottom { padding-top: 30px; background: linear-gradient(to bottom, transparent, var(--bg) 30px); }
#home.has-feed .home-orb-wrap { width: 170px; height: 170px; margin: -22px 0 -26px; }
#home.lay-dock .home-orb-wrap { width: 205px; height: 205px; margin: -26px 0 -30px; }
#home.lay-bento .home-orb-wrap { width: 165px; height: 165px; }
#home.lay-sheet .home-orb-wrap { width: 250px; height: 250px; margin: -10px 0 -34px; }
#home.lay-satellites .home-orb-wrap { width: 190px; height: 190px; }
#home.lay-today .home-orb-wrap { width: 160px; height: 160px; }
#home.hs-s .home-orb-wrap { transform: scale(1.1); } #home.hs-l .home-orb-wrap { transform: scale(.9); }
/* the three sizes look different, not just hold more or fewer cards: Compact is tight and small, Large roomy and big */
#home.hs-s .hx { padding: 9px 12px; border-radius: var(--r-l); } #home.hs-s .hx b { font-size: var(--fs-m); } #home.hs-s .hx span, #home.hs-s .hx .ev { font-size: var(--fs-s); }
#home.hs-s .hgrid, #home.hs-s .hlist { gap: 7px; } #home.hs-s .hb .c { width: 42px; height: 42px; }
#home.hs-l .hx { padding: 16px 18px; border-radius: var(--r-xl); } #home.hs-l .hx b { font-size: var(--fs-lg); } #home.hs-l .hx span, #home.hs-l .hx .ev { font-size: var(--fs-callout); }
#home.hs-l .hgrid, #home.hs-l .hlist { gap: 14px; } #home.hs-l .hb .c { width: 58px; height: 58px; } #home.hs-l .hb .c svg { width: 26px; height: 26px; }
.hf { width: 100%; max-width: 560px; padding: 0 16px; box-sizing: border-box; display: grid; gap: 4px; margin-top: 10px; }
.hf-hello { text-align: left; padding: 2px 4px 6px; }
.hf-hello small { display: block; color: var(--muted); font-size: var(--fs-s); letter-spacing: .02em; text-transform: uppercase; }
.hf-hello b { font-size: var(--fs-xl); font-weight: 600; }
.hf-sec { display: flex; justify-content: space-between; align-items: baseline; margin: 16px 4px 8px; }
.hf-sec h3 { margin: 0; font-size: var(--fs-body); font-weight: 600; }
.hf-sec span { color: var(--muted); font-size: var(--fs-s); }
.hf-stack { display: flex; overflow-x: auto; scroll-snap-type: x mandatory; gap: 10px; scrollbar-width: none; margin: 0 -16px; padding: 0 16px; }
.hf-stack::-webkit-scrollbar { display: none; }
.hf-card { flex: 0 0 86%; scroll-snap-align: center; text-align: left; background: #1b1b1d; border: 1px solid var(--fill); border-radius: var(--r-xl);
  padding: 14px 16px; color: var(--text); min-height: 86px; }
.hf-card.warn { border-color: #6b5520; } .hf-card.bad { border-color: #6b2525; background: #2a1515; }
.hf-card small { display: block; color: var(--accent); font-size: var(--fs-xs); font-weight: 600; letter-spacing: .02em; text-transform: uppercase; }
.hf-card.bad small { color: var(--bad-text); }
.hf-card b { display: block; font-size: var(--fs-body); font-weight: 600; margin: 4px 0 2px; line-height: 1.3; }
.hf-card span { color: var(--muted); font-size: var(--fs-sm); }
.hf-row { display: flex; overflow-x: auto; gap: 10px; scrollbar-width: none; margin: 0 -16px; padding: 0 16px 2px; }
.hf-row::-webkit-scrollbar { display: none; }
.hf-tile { flex: 0 0 210px; text-align: left; background: #1b1b1d; border-radius: var(--r-l); overflow: hidden; color: var(--text); text-decoration: none;
  display: flex; flex-direction: column; position: relative; }
.hf-tile .img { height: 112px; background: #26262a center/cover no-repeat; }
.hf-tile .img.none { display: grid; place-items: center; color: var(--muted);
  background: radial-gradient(120% 90% at 30% 20%, color-mix(in srgb, var(--accent) 16%, #26262a), #1e1e21); }
.hf-tile .img.none svg { width: 34px; height: 34px; opacity: .85; }
.hf-tile .tx { padding: 10px 12px 12px; }
.hf-tile small { display: block; color: var(--muted); font-size: var(--fs-xs); text-transform: uppercase; letter-spacing: .02em; }
.hf-tile b { display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; font-size: var(--fs-m); font-weight: 500; line-height: 1.3; margin-top: 3px; }
.hf-tile .price { display: inline-block; margin-top: 6px; font-weight: 600; color: var(--accent); }
.hf-tile .x { position: absolute; top: 6px; right: 6px; width: 26px; height: 26px; border-radius: 50%; background: rgba(0,0,0,.55); color: var(--text-2); font-size: var(--fs-m); line-height: 26px; text-align: center; }
.hf-tile .tag { display: inline-block; margin-left: 6px; color: var(--accent); }
.hf-chips { display: flex; flex-wrap: wrap; gap: 8px; }
.hf-chips button { padding: 9px 14px; border-radius: var(--r-pill); background: var(--raised); border: 1px solid var(--fill-2); color: var(--text); font-size: var(--fs-sm); }
.hf-empty { color: var(--muted); font-size: var(--fs-sm); padding: 4px; }
/* the extras, in every non-classic layout */
.hx { display: block; width: 100%; text-align: left; background: #1c1c1e; border: 1px solid var(--fill); border-radius: var(--r-l); padding: 12px 14px; color: var(--text); min-width: 0; }
.hx small { display: block; font-size: var(--fs-xs); font-weight: 600; letter-spacing: .04em; text-transform: uppercase; color: var(--accent); }
.hx b { display: block; font-size: var(--fs-callout); font-weight: 600; line-height: 1.3; margin-top: 3px; }
.hx span { display: block; font-size: var(--fs-sm); color: var(--muted); line-height: 1.35; }
.hx .ev { display: flex; gap: 10px; font-size: var(--fs-sm); margin-top: 4px; color: var(--text); }
.hx .ev em { font-style: normal; color: var(--muted); font-variant-numeric: tabular-nums; width: 70px; flex: none; }
.hx.warn { border-color: #5b4a1d; } .hx.warn small { color: #ffc04d; }
.hx.soon { opacity: .42; filter: grayscale(1); pointer-events: none; position: relative; }
.hx.soon::after { content: "Soon"; position: absolute; right: 12px; top: 12px; font-size: var(--fs-2xs); letter-spacing: .05em; text-transform: uppercase; color: var(--text-2); border: 1px solid #555; border-radius: var(--r-pill); padding: 1px 7px; }
.hx .prog { height: 4px; border-radius: var(--r-xs); background: var(--fill-2); margin-top: 8px; overflow: hidden; } .hx .prog i { display: block; height: 100%; background: var(--accent); }
.hx .pills { display: flex; gap: 8px; overflow-x: auto; scrollbar-width: none; margin-top: 8px; } .hx .pills::-webkit-scrollbar { display: none; }
.hp { flex: none; font-size: var(--fs-sm); border-radius: var(--r-pill); padding: 7px 12px; background: var(--raised); border: 1px solid var(--fill-2); color: var(--text); white-space: nowrap; }
.hp em { font-style: normal; color: var(--accent); margin-right: 4px; }
.hb { display: grid; justify-items: center; gap: 4px; font-size: var(--fs-xs); color: var(--muted); position: relative; min-width: 56px; }
.hb .c { width: 50px; height: 50px; border-radius: 50%; background: #1e1e20; border: 1px solid #2e2e30; display: grid; place-items: center; color: #dcdcdc; }
.hb .c svg { width: 22px; height: 22px; } .hb.soon { opacity: .4; filter: grayscale(1); pointer-events: none; }
.hb .bd { position: absolute; right: 2px; top: -2px; min-width: 19px; height: 19px; border-radius: var(--r-s); background: var(--accent); color: #04121a; font-size: var(--fs-2xs); font-weight: 700; display: grid; place-items: center; padding: 0 5px; }
.hrow { display: flex; gap: 14px; justify-content: center; margin: 6px 0 10px; }
.hgrid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; } .hgrid .wide { grid-column: span 2; }
.hlist { display: grid; gap: 10px; }
.hwhy { color: var(--muted); font-size: var(--fs-xs); padding: 2px 4px; text-align: center; }
#hf-sheet { position: absolute; left: 0; right: 0; bottom: calc(var(--sab) + 80px); z-index: 3; background: #1a1a1c; border-top: 1px solid var(--fill); border-radius: 24px 24px 0 0;
  padding: 8px calc(var(--sar) + 16px) 12px calc(var(--sal) + 16px); transition: max-height .35s var(--ease); overflow: hidden; }
#hf-sheet.open { overflow-y: auto; }
#hf-sheet .hd { display: block; width: 44px; height: 5px; border-radius: var(--r-xs); background: #4a4a4a; margin: 0 auto 10px; }
#hf-sheet .tap { display: block; width: 100%; padding: 0; background: none; }
.hsat { position: absolute; z-index: 2; }
`;
  document.head.append(css);

  const mid = document.querySelector("#home .home-mid"); if (!mid) return;
  const feed = el("div", "hf"); feed.setAttribute("aria-label", "Home"); mid.append(feed);
  const host = u => { try { return new URL(u).hostname.replace(/^www\./, ""); } catch (e) { return ""; } };
  const NS = "http://www.w3.org/2000/svg";
  const PATHS = {
    calendar: ["M5.5 5h13a2 2 0 012 2v11a2 2 0 01-2 2h-13a2 2 0 01-2-2V7a2 2 0 012-2z", "M3.5 10h17M8 3v4M16 3v4"],
    vantage: ["M12 3.5a8.5 8.5 0 110 17 8.5 8.5 0 010-17z", "M3.5 12h17M12 3.5c2.6 2.4 3.9 5.2 3.9 8.5s-1.3 6.1-3.9 8.5c-2.6-2.4-3.9-5.2-3.9-8.5s1.3-6.1 3.9-8.5z"],
    recommended: ["M4 7h10M18 7h2M4 17h4M12 17h8", "M16 5a2 2 0 110 4 2 2 0 010-4zM10 15a2 2 0 110 4 2 2 0 010-4z"],
    chips: ["M6 5h2.5a2.7 2.7 0 010 5.5H6A2.7 2.7 0 016 5zM15.5 5H18a2.7 2.7 0 010 5.5h-2.5a2.7 2.7 0 010-5.5zM6 13.5h4.5a2.7 2.7 0 010 5.5H6a2.7 2.7 0 010-5.5z"],
    // found-tile placeholders, drawn like the other icons (they were emoji, which looked off beside the line icons)
    deal: ["M3.5 12.2V4.5a1 1 0 011-1h7.7a1 1 0 01.7.3l7.8 7.8a1 1 0 010 1.4l-7.7 7.7a1 1 0 01-1.4 0l-7.8-7.8a1 1 0 01-.3-.7z", "M8 7a1 1 0 110 2 1 1 0 010-2z"],
    news: ["M5 4.5h11a1 1 0 011 1V19a1.5 1.5 0 003 0V9h-3", "M5 4.5V18a1.5 1.5 0 001.5 1.5H18.5", "M8 8.5h6M8 12h6M8 15.5h4"],
    watch: ["M4.5 5.5h15a1 1 0 011 1v11a1 1 0 01-1 1h-15a1 1 0 01-1-1v-11a1 1 0 011-1z", "M10 9.2v5.6l4.6-2.8z"],
    place: ["M12 21s-6.5-5.6-6.5-11a6.5 6.5 0 0113 0c0 5.4-6.5 11-6.5 11z", "M12 7.5a2.5 2.5 0 110 5 2.5 2.5 0 010-5z"],
    idea: ["M9 17.5h6M10 20.5h4", "M12 3.5a6 6 0 00-3.6 10.8c.4.3.6.8.6 1.3v1.9h6v-1.9c0-.5.2-1 .6-1.3A6 6 0 0012 3.5z"],
    update: ["M12 3.5a8.5 8.5 0 110 17 8.5 8.5 0 010-17z", "M8.3 12.3l2.5 2.5 5-5.2"],
    found: ["M12 3.5l1.9 5.2 5.6.3-4.4 3.5 1.5 5.4L12 14.8l-4.6 3.1 1.5-5.4L4.5 9l5.6-.3z"],
    weather: ["M12 8a4 4 0 110 8 4 4 0 010-8z", "M12 3v2M12 19v2M3 12h2M19 12h2M5.6 5.6l1.4 1.4M17 17l1.4 1.4M5.6 18.4L7 17M17 7l1.4-1.4"],
  };
  const icon = k => { const s = document.createElementNS(NS, "svg"); s.setAttribute("viewBox", "0 0 24 24"); s.setAttribute("aria-hidden", "true");
    for (const d of PATHS[k] || []) { const p = document.createElementNS(NS, "path"); p.setAttribute("d", d); p.setAttribute("fill", "none"); p.setAttribute("stroke", "currentColor");
      p.setAttribute("stroke-width", "1.8"); p.setAttribute("stroke-linecap", "round"); p.setAttribute("stroke-linejoin", "round"); s.append(p); } return s; };
  const NAMES = {calendar: "Calendar", vantage: "Vantage", recommended: "Settings", chips: "Chips", weather: "Weather"};
  const PER = {s: 2, m: 3, l: 5};

  function act(a) {
    if (!a) return;
    if (a.startsWith("settings:")) T.open("settings", a.slice(9));
    else if (a.startsWith("chat:")) { $("home-bot").click(); }
    else if (/^https:\/\//.test(a)) window.open(a, "_blank", "noopener");
  }
  const toChat = text => { $("home-bot").click(); if (text) setTimeout(() => T.send(text), 350); };
  function runChip(c) {
    $("home-bot").click();
    const p = String(c.prompt || c.name);
    setTimeout(() => { if (/\s$/.test(p)) { const ta = $("c-text"); ta.value = p; ta.focus(); } else T.send(`${p} (Use my "${c.name}" chip.)`, {show: `${c.icon || ""} ${c.name}`.trim()}); }, 350);
  }
  function sec(title, sub) { const h = el("div", "hf-sec"); h.append(el("h3", null, title)); if (sub) h.append(el("span", null, sub)); return h; }
  function tile(it, kind, onX) {
    const a = el(it.url ? "a" : "div", "hf-tile");
    if (it.url) { a.href = it.url; a.target = "_blank"; a.rel = "noopener noreferrer"; }
    const img = el("div", "img" + (it.image ? "" : " none"));
    if (it.image) img.style.backgroundImage = `url("${it.image.replace(/"/g, "%22")}")`; else img.append(icon(PATHS[kind] ? kind : "found"));
    const tx = el("div", "tx"), sm = el("small", null, (it.source || host(it.url) || kind) + (kind && kind !== "news" ? " · " + kind : ""));
    if (it.match) sm.append(el("span", "tag", "· for you"));
    tx.append(sm, el("b", null, it.title)); if (it.price) tx.append(el("span", "price", it.price));
    a.append(img, tx);
    if (onX) { const x = el("button", "x", "×"); x.type = "button"; x.setAttribute("aria-label", "Remove from Home"); x.addEventListener("click", e => { e.preventDefault(); e.stopPropagation(); onX(); }); a.append(x); }
    return a;
  }

  // ---- one extra as a card (the same in every layout); null when it has nothing to show
  function card(k, d, big) {
    const btn = (cls, on) => { const b = el("button", "hx" + (cls ? " " + cls : "")); b.type = "button"; if (on) b.addEventListener("click", on); return b; };
    const t = d.today || {events: [], reminders: []}, rec = d.recommended || {items: [], done: 0, total: 0};
    if (k === "calendar") {
      const b = btn("", () => T.open("calendar"));
      b.append(el("small", null, t.events.length ? `Today · ${t.events.length} event${t.events.length > 1 ? "s" : ""}` : "Calendar"));
      if (t.events.length) for (const e of t.events.slice(0, big ? 4 : 2)) { const r = el("div", "ev"); r.append(el("em", null, e.when), document.createTextNode(e.title)); b.append(r); }
      else b.append(el("span", null, "Nothing on today. Tap to see your week."));
      return b;
    }
    if (k === "vantage") { const b = btn("soon"); b.disabled = true; b.append(el("small", null, "Vantage"), el("b", null, "The world near you"), el("span", null, "Not ready yet")); return b; }
    if (k === "recommended") {
      if (!rec.items.length) return null;
      const b = btn("", () => act(rec.items[0].action));
      b.append(el("small", null, `Finish setting up · ${rec.done} of ${rec.total}`), el("b", null, rec.items[0].title), el("span", null, rec.items[0].sub));
      if (big && rec.items[1]) b.append(el("span", null, "Next: " + rec.items.slice(1, 3).map(i => i.title).join(", ")));
      const pg = el("div", "prog"), i = el("i"); i.style.width = `${rec.total ? rec.done / rec.total * 100 : 0}%`; pg.append(i); b.append(pg);
      return b;
    }
    if (k === "today") {
      // reminders, plus today's events only when the calendar card isn't showing them already; soonest first
      const withEvents = !(d.order || []).includes("calendar");
      const list = t.reminders.map(r => [r.t || 0, r.when, r.text]).concat(withEvents ? t.events.map(e => [e.t || 0, e.when, e.title]) : [])
        .sort((a, b) => a[0] - b[0]);
      if (!list.length) return null;
      const b = btn("", () => toChat());
      b.append(el("small", null, withEvents ? "Today" : "Reminders today"));
      const items = list.map(x => [x[1], x[2]]).slice(0, big ? 4 : 2);
      for (const [w, x] of items) { const r = el("div", "ev"); r.append(el("em", null, w), document.createTextNode(x)); b.append(r); }
      return b;
    }
    if (k === "approvals") {
      const a = (d.stack || []).find(c => c.kind === "approve"); if (!a) return null;
      const b = btn("warn", () => act(a.action)); b.append(el("small", null, a.eyebrow), el("b", null, a.title)); if (a.sub) b.append(el("span", null, a.sub)); return b;
    }
    if (k === "chips") {
      const on = (d.chips || []).filter(c => c.on).slice(0, 6); if (!on.length) return null;
      const b = el("div", "hx"); b.append(el("small", null, "Your chips"));
      const row = el("div", "pills");
      for (const c of on) { const p = el("button", "hp", `${c.icon || "✨"} ${c.name}`); p.type = "button"; p.addEventListener("click", () => runChip(c)); row.append(p); }
      b.append(row); return b;
    }
    if (k === "found") {
      const f = (d.found || [])[0]; if (!f) return null;
      const b = btn("", () => act(f.url || "chat:")); b.append(el("small", null, "Found for you"), el("b", null, f.title));
      if (f.price) { const p = el("span", null, f.price); p.style.color = "var(--accent)"; b.append(p); } return b;
    }
    if (k === "stories") {
      const n = (d.news || [])[0]; if (!n) return null;
      const b = btn("", () => act(n.url)); b.append(el("small", null, "Top story" + (n.match ? " · for you" : "")), el("b", null, n.title), el("span", null, n.source || "")); return b;
    }
    if (k === "weather") {
      const w = d.weather; if (!w) return null;
      const b = btn("", () => toChat("What's the weather today?"));
      b.append(el("small", null, "Weather"), el("b", null, `${w.temp}° · ${w.condition}`), el("span", null, `High ${w.hi}°, low ${w.lo}°`)); return b;
    }
    return null;
  }
  // ---- one extra as a small round button (dock, satellites)
  function button(k, d) {
    const b = el("button", "hb" + (k === "vantage" ? " soon" : "")); b.type = "button";
    const c = el("span", "c"); c.append(icon(k)); b.append(c, document.createTextNode(NAMES[k] || k));
    const rec = d.recommended || {items: []};
    if (k === "recommended" && rec.items.length) b.append(el("span", "bd", String(rec.items.length)));
    if (k === "vantage") { b.disabled = true; b.setAttribute("aria-label", "Vantage, coming soon"); }
    b.addEventListener("click", () => {
      if (k === "calendar") T.open("calendar");
      else if (k === "recommended") act((rec.items[0] || {}).action || "settings:root");
      else if (k === "chips") T.open("settings", "chips");
      else if (k === "weather") toChat("What's the weather today?");
    });
    return b;
  }
  const BUTTONS = ["calendar", "vantage", "recommended", "chips", "weather"];

  // ---- the layouts (classic is the feed; the rest come from the Home Lab)
  function classic(d) {
    const kids = [];
    if ((d.stack || []).length) {
      const st = el("div", "hf-stack"); st.setAttribute("aria-label", "What matters now");
      for (const c of d.stack) {
        const b = el("button", "hf-card " + (c.tone || "")); b.type = "button";
        b.append(el("small", null, c.eyebrow), el("b", null, c.title)); if (c.sub) b.append(el("span", null, c.sub));
        b.addEventListener("click", () => act(c.action)); st.append(b);
      }
      kids.push(st);
    }
    kids.push(sec("Found for you", (d.found || []).length ? "" : "Deals, stories and ideas Theta finds land here"));
    if ((d.found || []).length) {
      const r = el("div", "hf-row");
      for (const f of d.found) r.append(tile(f, f.kind, async () => { if (!T.state.demo) { try { await T.http("/api/home?id=" + encodeURIComponent(f.id), {method: "DELETE"}); } catch (e) {} } render(); }));
      kids.push(r);
    } else kids.push(el("p", "hf-empty", "Try a chip like Best price or News digest, and Theta saves what it finds here."));
    const on = (d.chips || []).filter(c => c.on).slice(0, 8);
    if (on.length) {
      kids.push(sec("Your chips"));
      const box = el("div", "hf-chips");
      for (const c of on) { const b = el("button", null, `${c.icon || "✨"} ${c.name}`); b.type = "button"; b.addEventListener("click", () => runChip(c)); box.append(b); }
      kids.push(box);
    }
    if ((d.news || []).length) {
      kids.push(sec("Top stories", d.news.some(n => n.match) ? "Your interests first" : ""));
      const r = el("div", "hf-row"); for (const n of d.news) r.append(tile(n, "news")); kids.push(r);
    }
    return kids;
  }
  const cards = (d, keys, n, big) => keys.map((k, i) => card(k, d, big && i === 0)).filter(Boolean).slice(0, n);
  const why = d => d.why ? [el("p", "hwhy", d.why)] : [];
  function dock(d, size) {
    const btns = d.order.filter(k => BUTTONS.includes(k) && k !== "weather").slice(0, 4), row = el("div", "hrow");
    btns.forEach(k => row.append(button(k, d)));
    const list = el("div", "hlist"); cards(d, d.order.filter(k => !btns.includes(k)), PER[size] - 1, size === "l").forEach(c => list.append(c));
    return [row, list, ...why(d)];
  }
  function bento(d, size) {
    const g = el("div", "hgrid");
    cards(d, d.order.filter(k => k !== "vantage"), PER[size] + 1, size === "l").forEach((c, i) => { if (i === 0 && size !== "s") c.classList.add("wide"); g.append(c); });
    if (d.order.includes("vantage")) g.append(card("vantage", d));  // always there, greyed, until it's ready
    return [g, ...why(d)];
  }
  function today(d, size) {
    const kids = [], t = d.today || {events: [], reminders: []};
    const items = t.events.map(e => [e.t || 0, e.when, e.title]).concat(t.reminders.map(r => [r.t || 0, r.when, r.text]))
      .sort((a, b) => a[0] - b[0]).map(x => [x[1], x[2]]);  // one line, soonest first
    if (items.length) { const row = el("div", "hf-row"); for (const [w, x] of items) { const p = el("button", "hp"); p.type = "button"; p.append(el("em", null, w), document.createTextNode(x)); p.addEventListener("click", () => T.open("calendar")); row.append(p); } kids.push(row); }
    const list = el("div", "hlist"); list.style.marginTop = "10px";
    cards(d, d.order.filter(k => !["calendar", "today", "vantage", "chips"].includes(k)), PER[size] - 1, false).forEach(c => list.append(c));
    kids.push(list);
    const pills = el("div", "hrow"); pills.style.flexWrap = "wrap"; pills.style.gap = "8px";
    for (const k of d.order.filter(k => ["calendar", "vantage", "chips", "weather"].includes(k)).slice(0, 4)) {
      const p = el("button", "hp", k === "vantage" ? "Vantage · soon" : NAMES[k]); p.type = "button";
      if (k === "vantage") { p.disabled = true; p.style.opacity = ".4"; } else p.addEventListener("click", () => button(k, d).click());
      pills.append(p);
    }
    kids.push(pills, ...why(d));
    return kids;
  }
  function satellites(d, size) {
    const sats = d.order.filter(k => BUTTONS.includes(k)).slice(0, 4);
    const next = d.order.filter(k => !BUTTONS.includes(k));
    const list = el("div", "hlist"); cards(d, next, size === "l" ? 2 : 1, false).forEach(c => list.append(c));
    requestAnimationFrame(() => place(sats, d));
    return [list, ...why(d)];
  }
  function place(sats, d) { // small buttons around the globe, left and right of it (never over its name)
    mid.querySelectorAll(".hsat").forEach(n => n.remove());
    const w = document.querySelector("#home .home-orb-wrap"); if (!w || !sats.length) return;
    const mr = mid.getBoundingClientRect(), r = w.getBoundingClientRect(), cx = r.left - mr.left + r.width / 2, cy = r.top - mr.top + mid.scrollTop + r.height / 2, R = r.width / 2 + 36;
    const ANG = [-160, -20, 160, 20].map(a => a * Math.PI / 180);
    sats.forEach((k, i) => { const b = button(k, d); b.classList.add("hsat"); b.style.left = `${cx + Math.cos(ANG[i]) * R - 28}px`; b.style.top = `${cy + Math.sin(ANG[i]) * R - 30}px`; mid.append(b); });
  }
  function sheet(d, size) { // only the globe on Home; the rest in a sheet that peeks above search, tap or swipe to open
    let sh = $("hf-sheet");
    if (!sh) { sh = el("div"); sh.id = "hf-sheet"; $("home").append(sh); }
    const t = d.today || {events: [], reminders: []}, line = el("div", "hf-row"); line.style.margin = "0";
    const pend = (d.stack || []).find(c => c.kind === "approve"), rec = d.recommended || {items: []};
    const add = (txt, em, warn) => { const p = el("span", "hp"); if (em) p.append(el("em", null, em)); p.append(document.createTextNode(txt)); if (warn) p.style.color = "#ffc04d"; line.append(p); };
    if (t.events[0]) add(t.events[0].title, t.events[0].when);
    if (pend) add(pend.title, null, true);
    if (rec.items.length) add(`${rec.done} of ${rec.total} set up`);
    if (d.weather) add(`${d.weather.temp}° ${d.weather.condition}`);
    const tap = el("button", "tap"); tap.type = "button"; tap.setAttribute("aria-label", "Show more"); tap.append(el("span", "hd"));
    const list = el("div", "hlist"); list.style.marginTop = "12px";
    cards(d, d.order, 9, size === "l").forEach(c => list.append(c));
    sh.replaceChildren(tap, line, list, ...why(d));
    const peek = {s: 64, m: 92, l: 150}[size];
    const set = open => { sh.classList.toggle("open", open); sh.style.maxHeight = open ? "62vh" : peek + "px"; };
    const bot = document.querySelector("#home .home-bottom"); if (bot) sh.style.bottom = `${bot.getBoundingClientRect().height - 26}px`;  // above search and any banner
    set(sh.classList.contains("open"));
    tap.onclick = () => set(!sh.classList.contains("open"));
    let y0 = null; sh.ontouchstart = e => { y0 = e.touches[0].clientY; }; sh.ontouchend = e => { if (y0 == null) return; const dy = e.changedTouches[0].clientY - y0; if (Math.abs(dy) > 30 && !(sh.scrollTop > 0 && dy > 0)) set(dy < 0); y0 = null; };
    return [];
  }
  const LAYOUTS = {dock, bento, sheet, satellites, today};

  let last = null;
  function local() { try { return JSON.parse(T.store("theta:home") || "null"); } catch (e) { return null; } }
  async function render() {
    let d;
    if (T.state.demo) d = demo();
    else { try { d = await T.api("/api/home"); } catch (e) { return; } }
    try { d.chips = T.state.demo ? demoChips() : (await T.api("/api/chips")).chips || []; } catch (e) { d.chips = []; }
    d.order = d.order || []; if (d.chips.some(c => c.on) && !d.order.includes("chips")) d.order.push("chips");
    const lay = local() || d.layout || {layout: "classic", size: "m", off: []};
    d.order = d.order.filter(k => !(lay.off || []).includes(k));
    last = d;
    const home = $("home"), name = LAYOUTS[lay.layout] ? lay.layout : "classic";
    home.className = home.className.replace(/\b(lay|hs)-\S+/g, "").trim();
    home.classList.add("has-feed", "lay-" + name, "hs-" + (lay.size || "m"));
    mid.querySelectorAll(".hsat").forEach(n => n.remove());
    if (name !== "sheet") $("hf-sheet")?.remove();
    const hello = el("div", "hf-hello"); hello.append(el("small", null, d.date), el("b", null, d.hello));
    const kids = name === "classic" ? [hello, ...classic(d)] : [...(name === "sheet" ? [] : [hello]), ...LAYOUTS[name](d, lay.size || "m")];
    feed.replaceChildren(...kids);
  }
  T.homeRender = render;
  function demoChips() { return [{name: "Morning brief", icon: "☀️", prompt: "Give me my morning brief.", on: true}, {name: "Best price", icon: "🏷️", prompt: "Find me the best price on ", on: true}]; }
  function demo() {
    return {hello: "Good evening, Sam", date: new Date().toLocaleDateString(undefined, {weekday: "long", month: "long", day: "numeric"}),
      stack: [{kind: "approve", eyebrow: "Waiting for your OK", title: "1 thing ready to go", sub: "Book a showroom visit, Fri 1 PM", action: "chat:"},
        {kind: "calendar", eyebrow: "Up next", title: "Dentist", sub: "3:30 PM · 12 Main St", action: "chat:", tone: "warn"}],
      found: [{id: "a", kind: "deal", title: "Arc floor lamp, lowest of 4 stores", price: "$89", source: "Lamp Shop"},
        {id: "b", kind: "news", title: "Jazz win in overtime behind 41 from Markkanen", source: "ESPN"}],
      news: [{title: "Storms expected across the Mountain West this weekend", source: "NPR", match: true}, {title: "Markets close higher on rate hopes", source: "BBC"}],
      today: (() => { const at = h => { const x = new Date(); x.setHours(h, h % 1 * 60, 0, 0); return x.getTime() / 1000; };
        return {events: [{title: "Dentist", when: "3:30 PM", t: at(15.5)}, {title: "Call with Sam", when: "5:00 PM", t: at(17)}],
          reminders: [{text: "Trash goes out", when: "8:00 PM", t: at(20)}, {text: "Take vitamins", when: "9:00 AM", t: at(9)}]}; })(),
      weather: {temp: 34, condition: "light snow", hi: 38, lo: 21, unit: "F"},
      recommended: {items: [{key: "backups", title: "Turn on Drive backups", sub: "A copy every 3 hours", action: "settings:connections"}, {key: "push", title: "Let Theta text you", sub: "Reminders on your phone", action: "settings:notifications"}], done: 5, total: 7},
      order: ["approvals", "calendar", "today", "weather", "found", "recommended", "stories", "vantage"],
      why: "First: something is waiting for your OK; you have 2 events today; light snow today.", layout: {layout: "classic", size: "m", off: []}};
  }
  new MutationObserver(() => { if (!$("home").hidden) render(); }).observe($("home"), {attributes: true, attributeFilter: ["hidden"]});
  setTimeout(() => { if (!$("home").hidden) render(); }, 800);

  // ---- Settings > General > Home: layout, size and which extras show
  const g = T.settings("Home", "general");
  const pane = el("div"); pane.style.padding = "6px 14px 12px"; g.append(pane);
  const LAYS = [["classic", "Classic"], ["dock", "Dock"], ["bento", "Bento"], ["sheet", "Sheet"], ["satellites", "Satellites"], ["today", "Today line"]];
  const XS = [["calendar", "Calendar"], ["vantage", "Vantage"], ["recommended", "Recommended settings"], ["today", "Today & reminders"], ["approvals", "Approvals"],
    ["chips", "Chips"], ["found", "Found for you"], ["stories", "Top stories"], ["weather", "Weather"]];
  async function save(patch) {
    const cur = Object.assign({layout: "classic", size: "m", off: []}, local() || (last && last.layout) || {}, patch);
    try { T.store("theta:home", JSON.stringify(cur)); } catch (e) {}
    if (!T.state.demo) { try { await T.post("/api/home/layout", cur); } catch (e) { T.toast("Couldn't save that on the server; it's kept on this phone."); } }
    paintSettings(); if (!$("home").hidden) render();
  }
  function seg(label, opts, val, on) {
    const wrap = el("div"); wrap.append(el("div", "lk-sec", label));
    const row = el("div", "onb-segs"); row.style.display = "flex"; row.style.flexWrap = "wrap"; row.style.gap = "6px";
    for (const [v, n] of opts) { const b = el("button", v === val ? "on" : null, n); b.type = "button"; b.setAttribute("aria-pressed", String(v === val)); b.addEventListener("click", () => on(v)); row.append(b); }
    wrap.append(row); return wrap;
  }
  function paintSettings() {
    const cur = Object.assign({layout: "classic", size: "m", off: []}, local() || (last && last.layout) || {});
    const xs = el("div"); xs.append(el("div", "lk-sec", "Extras on Home"));
    const row = el("div", "onb-segs"); row.style.display = "flex"; row.style.flexWrap = "wrap"; row.style.gap = "6px";
    for (const [k, n] of XS) { const on = !cur.off.includes(k), b = el("button", on ? "on" : null, n); b.type = "button"; b.setAttribute("aria-pressed", String(on));
      b.addEventListener("click", () => save({off: on ? cur.off.concat(k) : cur.off.filter(x => x !== k)})); row.append(b); }
    xs.append(row);
    pane.replaceChildren(seg("Layout", LAYS, cur.layout, v => save({layout: v})), seg("Size of the extras", [["s", "Compact"], ["m", "Regular"], ["l", "Large"]], cur.size, v => save({size: v})), xs,
      el("p", "fine", "Theta's globe stays the main button in every layout. The extras are ordered for you, from what's going on, and empty ones hide."));
  }
  paintSettings();
  // the server's choice wins once signed in (set on another device)
  setTimeout(async () => { if (T.state.demo || !T.state.authed) return; try { const l = await T.api("/api/home/layout"); T.store("theta:home", JSON.stringify(l)); paintSettings(); } catch (e) {} }, 1500);
})();
