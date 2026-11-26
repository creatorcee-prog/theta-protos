/* calendar: the in-app calendar (server/gcal.py). A week strip and a day agenda, colored by source (Google, calendar
 * links, events kept in Theta), a "+" to add an event, calendar links (ICS) to add or remove, and a Settings section
 * for leave-by heads-ups and the Google account. Uses window.Theta from app.js; DOM nodes only, never innerHTML.
 */
(() => {
  "use strict";
  function boot() {
    const T = window.Theta, el = T.el, svg = T.svg, demo = () => !!T.state.demo;
    const pad = n => String(n).padStart(2, "0");
    const ymd = d => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
    const parseDay = s => { const [y, m, d] = s.slice(0, 10).split("-").map(Number); return new Date(y, m - 1, d); };
    const addDays = (d, n) => { const x = new Date(d); x.setDate(x.getDate() + n); return x; };
    const monday = d => addDays(new Date(d.getFullYear(), d.getMonth(), d.getDate()), -((d.getDay() + 6) % 7));
    const hm = d => d.toLocaleTimeString([], {hour: "numeric", minute: "2-digit"});

    // ---- styles (all under #calendar or .cal-)
    const css = el("style");
    css.textContent = `
#calendar .cal-nav { display: flex; align-items: center; gap: 8px; margin: 4px 0 10px; }
#calendar .cal-nav h3 { flex: 1; margin: 0; font-size: 17px; font-weight: 500; text-align: center; }
#calendar .cal-round { width: 40px; height: 40px; border-radius: 50%; background: #2a2a2a; display: grid; place-items: center; flex: none; }
#calendar .cal-round:active { background: #333; }
#calendar .cal-round svg { width: 20px; height: 20px; }
#calendar .cal-today { background: #2a2a2a; border-radius: 999px; padding: 8px 14px; font-size: 15px; }
#calendar .cal-strip { display: grid; grid-template-columns: repeat(7, 1fr); gap: 4px; touch-action: pan-y; user-select: none; }
#calendar .cal-day { display: flex; flex-direction: column; align-items: center; gap: 2px; padding: 8px 0 7px; border-radius: 16px; background: #1b1b1b; min-width: 0; }
#calendar .cal-day small { color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: .04em; }
#calendar .cal-day b { font-size: 18px; font-weight: 500; }
#calendar .cal-day.today b { color: var(--accent); }
#calendar .cal-day[aria-pressed="true"] { background: #f2f2f2; color: #111; }
#calendar .cal-day[aria-pressed="true"] small { color: #555; }
#calendar .cal-day[aria-pressed="true"].today b { color: #0b6f91; }
#calendar .cal-dots { display: flex; gap: 3px; height: 6px; }
#calendar .cal-dots i { width: 6px; height: 6px; border-radius: 50%; }
#calendar .cal-agenda { margin-top: 14px; touch-action: pan-y; min-height: 120px; }
#calendar .cal-agenda h4 { margin: 0 2px 8px; font-size: 15px; font-weight: 500; color: var(--muted); }
#calendar .cal-ev { display: flex; gap: 12px; padding: 12px 14px; border-radius: 16px; background: #1b1b1b; margin-bottom: 8px; align-items: stretch; }
#calendar .cal-bar { width: 4px; border-radius: 4px; flex: none; }
#calendar .cal-ev .cal-when { flex: none; width: 74px; font-size: 14px; color: var(--muted); line-height: 1.35; }
#calendar .cal-ev .cal-what { flex: 1; min-width: 0; }
#calendar .cal-ev .cal-what b { display: block; font-weight: 500; overflow-wrap: anywhere; }
#calendar .cal-ev .cal-what span { display: block; color: var(--muted); font-size: 14px; overflow-wrap: anywhere; }
#calendar .cal-x { color: var(--muted); width: 32px; height: 32px; display: grid; place-items: center; flex: none; border-radius: 50%; }
#calendar .cal-x svg { width: 18px; height: 18px; }
#calendar .cal-form { background: #1b1b1b; border-radius: 20px; padding: 14px; margin: 6px 0 14px; display: grid; gap: 10px; }
#calendar .cal-form .cal-row { display: flex; gap: 8px; flex-wrap: wrap; }
#calendar .cal-form input, #calendar .cal-form select { flex: 1 1 120px; min-width: 0; height: 44px; border-radius: 12px; border: 1px solid #333;
  background: #141414; padding: 0 12px; font-size: 16px; color: var(--text); color-scheme: dark; }
#calendar .cal-form .cal-btns { display: flex; gap: 8px; justify-content: flex-end; }
#calendar .cal-primary { background: #f2f2f2; color: #111; border-radius: 999px; padding: 9px 18px; font-size: 15px; }
#calendar .cal-sub { display: flex; align-items: center; gap: 10px; padding: 10px 2px; border-top: 1px solid #262626; }
#calendar .cal-sub:first-child { border-top: 0; }
#calendar .cal-sub i { width: 12px; height: 12px; border-radius: 50%; flex: none; }
#calendar .cal-sub .cal-what { flex: 1; min-width: 0; }
#calendar .cal-sub .cal-what b { display: block; font-weight: 500; }
#calendar .cal-sub .cal-what span { display: block; color: var(--muted); font-size: 13px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
#calendar .cal-note { color: var(--muted); font-size: 14px; margin: 6px 2px; }
`;
    document.head.append(css);

    // a calendar icon for the menu, added to the page's icon sprite
    const sprite = document.querySelector("symbol[id^='i-']");
    if (sprite && !document.getElementById("i-cal")) {
      const NS = "http://www.w3.org/2000/svg", sym = document.createElementNS(NS, "symbol");
      sym.id = "i-cal"; sym.setAttribute("viewBox", "0 0 24 24");
      const g = document.createElementNS(NS, "g");
      for (const [k, v] of [["fill", "none"], ["stroke", "currentColor"], ["stroke-width", "2"], ["stroke-linecap", "round"], ["stroke-linejoin", "round"]]) g.setAttribute(k, v);
      const r = document.createElementNS(NS, "rect");
      for (const [k, v] of [["x", "4"], ["y", "5.5"], ["width", "16"], ["height", "14.5"], ["rx", "2.5"]]) r.setAttribute(k, v);
      const p = document.createElementNS(NS, "path"); p.setAttribute("d", "M4 10h16M8.5 3.5v4M15.5 3.5v4");
      g.append(r, p); sym.append(g); sprite.parentNode.append(sym);
    }

    // ---- demo data
    const DEMO_SRC = {google: ["Google", "#4fd3ff"], team: ["Team (link)", "#ffb35c"], theta: ["Theta", "#b18cff"]};
    let demoEvents = null, demoSubs = [{id: "d1", name: "Team (link)", url: "https://calendar.example.com/team.ics", color: "#ffb35c"}];
    function demoList() {
      if (demoEvents) return demoEvents;
      const t0 = new Date(), mk = (dayOff, h, m, mins, title, src, loc) => {
        const d = addDays(new Date(t0.getFullYear(), t0.getMonth(), t0.getDate()), dayOff);
        if (h == null) return {id: "demo" + Math.random(), title, start: ymd(d), end: ymd(addDays(d, 1)), all_day: true, location: loc || "", source: DEMO_SRC[src][0], color: DEMO_SRC[src][1]};
        const s = new Date(d); s.setHours(h, m); const e = new Date(s.getTime() + mins * 60000);
        return {id: "demo" + Math.random(), title, start: s.toISOString(), end: e.toISOString(), all_day: false, location: loc || "", source: DEMO_SRC[src][0], color: DEMO_SRC[src][1]};
      };
      demoEvents = [];
      for (let i = -7; i < 21; i++) { const d = addDays(t0, i); if (d.getDay() > 0 && d.getDay() < 6) demoEvents.push(mk(i, 9, 30, 15, "Standup", "team")); }
      demoEvents.push(mk(0, 15, 0, 45, "Dentist", "google", "12 Main St"), mk(0, 19, 0, 90, "Dinner with Sam", "google", "Sushi Den"),
        mk(1, 12, 30, 60, "Lunch with Ana", "google", "Cafe Max"), mk(2, null, 0, 0, "Day off", "team"),
        mk(3, 17, 0, 60, "Gym", "theta"), mk(5, 10, 0, 120, "Team offsite", "team", "Union Station"), mk(-2, 18, 0, 60, "Book club", "google"));
      return demoEvents;
    }

    // ---- state
    let week = monday(new Date()), day = new Date(), events = [], info = {}, loadSeq = 0;
    const sh = T.sheet("calendar", "Calendar", () => { week = monday(day); render(); load(); loadSubs(); });
    sh.root.classList.add("cal-sheet");
    const body = sh.body;
    T.menu("Calendar", document.getElementById("i-cal") ? "i-cal" : "i-grid", "calendar");

    const nav = el("div", "cal-nav"), prev = el("button", "cal-round"), next = el("button", "cal-round"),
      label = el("h3"), todayBtn = el("button", "cal-today", "Today"), plus = el("button", "cal-round");
    prev.type = next.type = todayBtn.type = plus.type = "button";
    prev.append(svg("i-back")); next.append(svg("i-chev")); plus.append(svg("i-plus"));
    prev.setAttribute("aria-label", "Previous week"); next.setAttribute("aria-label", "Next week"); plus.setAttribute("aria-label", "Add an event");
    nav.append(prev, label, next, todayBtn, plus);
    const strip = el("div", "cal-strip"); strip.setAttribute("role", "group"); strip.setAttribute("aria-label", "Days of the week");
    const form = el("form", "cal-form"); form.hidden = true;
    const agenda = el("div", "cal-agenda"); agenda.setAttribute("aria-live", "polite");
    const note = el("p", "cal-note");
    const subsHead = el("h3", "sec", "Calendar links"), subsBox = el("div", "group"), subsNote = el("p", "fine",
      "Add a calendar's ICS or webcal link (school, sports, a shared calendar). Read-only; refreshed every 15 minutes.");
    body.append(nav, strip, form, agenda, note, subsHead, subsNote, subsBox);

    const shiftWeek = n => { week = addDays(week, 7 * n); day = addDays(day, 7 * n); render(); load(); };
    prev.addEventListener("click", () => shiftWeek(-1));
    next.addEventListener("click", () => shiftWeek(1));
    todayBtn.addEventListener("click", () => { day = new Date(); week = monday(day); render(); load(); });
    plus.addEventListener("click", () => { form.hidden = !form.hidden; if (!form.hidden) { fDate.value = ymd(day); fTitle.focus(); } });

    // swipe: the strip moves by a week, the agenda by a day
    function swipe(node, fn) {
      let x0 = null, y0 = 0;
      node.addEventListener("touchstart", e => { const t = e.touches[0]; x0 = t.clientX; y0 = t.clientY; }, {passive: true});
      node.addEventListener("touchend", e => {
        if (x0 == null) return; const t = e.changedTouches[0], dx = t.clientX - x0, dy = t.clientY - y0; x0 = null;
        if (Math.abs(dx) > 60 && Math.abs(dx) > 1.5 * Math.abs(dy)) fn(dx < 0 ? 1 : -1);
      }, {passive: true});
    }
    swipe(strip, shiftWeek);
    swipe(agenda, n => { day = addDays(day, n); const w = monday(day); if (w.getTime() !== week.getTime()) { week = w; load(); } render(); });

    // ---- which events fall on a day
    function onDay(e, d) {
      const key = ymd(d);
      if (e.all_day) { const s = e.start.slice(0, 10), en = (e.end || "").slice(0, 10) || s; return key >= s && (key < en || key === s); }
      const s = new Date(e.start), en = new Date(e.end || e.start), d0 = new Date(d.getFullYear(), d.getMonth(), d.getDate()), d1 = addDays(d0, 1);
      return (s < d1 && en > d0) || (s >= d0 && s < d1);
    }
    function render() {
      const today = ymd(new Date()), end = addDays(week, 6);
      label.textContent = week.getMonth() === end.getMonth()
        ? week.toLocaleDateString([], {month: "long", year: "numeric"})
        : `${week.toLocaleDateString([], {month: "short"})} – ${end.toLocaleDateString([], {month: "short", year: "numeric"})}`;
      sh.pill.textContent = demo() ? "Demo" : "";
      strip.replaceChildren();
      for (let i = 0; i < 7; i++) {
        const d = addDays(week, i), b = el("button", "cal-day" + (ymd(d) === today ? " today" : "")); b.type = "button";
        b.setAttribute("aria-pressed", String(ymd(d) === ymd(day)));
        b.setAttribute("aria-label", d.toLocaleDateString([], {weekday: "long", month: "long", day: "numeric"}));
        const dots = el("span", "cal-dots");
        for (const c of [...new Set(events.filter(e => onDay(e, d)).map(e => e.color))].slice(0, 3)) { const i2 = el("i"); i2.style.background = c; dots.append(i2); }
        b.append(el("small", null, d.toLocaleDateString([], {weekday: "short"}).slice(0, 3)), el("b", null, String(d.getDate())), dots);
        b.addEventListener("click", () => { day = d; render(); });
        strip.append(b);
      }
      agenda.replaceChildren(el("h4", null, ymd(day) === today ? "Today" : day.toLocaleDateString([], {weekday: "long", month: "long", day: "numeric"})));
      const list = events.filter(e => onDay(e, day)).sort((a, b) => (b.all_day - a.all_day) || (new Date(a.start) - new Date(b.start)));
      if (!list.length) agenda.append(el("p", "empty", info.loading ? "Loading…" : "Nothing on this day."));
      for (const e of list) agenda.append(row(e));
      const notes = [];
      if (info.google_note) notes.push(info.google_note);
      else if (info.google === false && !demo()) notes.push("Connect Google (Settings > Connections) to see your Google Calendar here too.");
      for (const p of info.problems || []) notes.push(p + ".");
      note.textContent = notes.join(" ");
    }
    function row(e) {
      const r = el("div", "cal-ev"), bar = el("span", "cal-bar"); bar.style.background = e.color || "#888";
      const when = el("div", "cal-when");
      if (e.all_day) when.textContent = "All day";
      else { const s = new Date(e.start), en = new Date(e.end || e.start); when.append(el("div", null, hm(s))); if (en > s) when.append(el("div", null, hm(en))); }
      const what = el("div", "cal-what"); what.append(el("b", null, e.title || "(no title)"));
      const sub = [e.location, e.source].filter(Boolean).join(" · "); if (sub) what.append(el("span", null, sub));
      r.append(bar, when, what);
      if (String(e.id || "").startsWith("t:")) { // kept in Theta, so it can be removed here
        const x = el("button", "cal-x"); x.type = "button"; x.setAttribute("aria-label", "Remove " + (e.title || "event")); x.append(svg("i-close"));
        x.addEventListener("click", async () => {
          try { await T.api("/api/calendar/events?id=" + encodeURIComponent(e.id), {method: "DELETE"}); load(); } catch (err) { T.toast("Couldn't remove that."); }
        });
        r.append(x);
      }
      return r;
    }
    async function load() {
      const seq = ++loadSeq, from = ymd(week), to = ymd(addDays(week, 6));
      if (demo()) { events = demoList(); info = {google: true}; render(); return; }
      info = Object.assign({}, info, {loading: true}); render();
      try {
        const j = await T.api(`/api/calendar?from=${from}&to=${to}`);
        if (seq !== loadSeq) return;
        events = Array.isArray(j.events) ? j.events : []; info = j;
      } catch (e) {
        if (seq !== loadSeq) return;
        info = {problems: ["Couldn't load the calendar just now"]};
      }
      render();
    }

    // ---- add an event
    const fTitle = el("input"), fDate = el("input"), fTime = el("input"), fDur = el("select"), fLoc = el("input");
    fTitle.placeholder = "Title"; fTitle.required = true; fTitle.maxLength = 200; fTitle.setAttribute("aria-label", "Title");
    fDate.type = "date"; fDate.required = true; fDate.setAttribute("aria-label", "Date");
    fTime.type = "time"; fTime.setAttribute("aria-label", "Time (empty for all day)");
    fLoc.placeholder = "Place (optional)"; fLoc.maxLength = 300; fLoc.setAttribute("aria-label", "Place");
    for (const [v, t] of [[15, "15 min"], [30, "30 min"], [45, "45 min"], [60, "1 hour"], [90, "1.5 hours"], [120, "2 hours"], [180, "3 hours"]]) {
      const o = el("option", null, t); o.value = v; if (v === 60) o.selected = true; fDur.append(o); }
    fDur.setAttribute("aria-label", "Duration");
    const r1 = el("div", "cal-row"), r2 = el("div", "cal-row"), btns = el("div", "cal-btns"),
      cancel = el("button", "btn-dark", "Cancel"), save = el("button", "cal-primary", "Add");
    cancel.type = "button"; save.type = "submit";
    r1.append(fDate, fTime); r2.append(fDur, fLoc); btns.append(cancel, save);
    form.append(fTitle, r1, r2, el("p", "fine", "Goes to your Google Calendar when Google is connected, else it's kept in Theta. Leave the time empty for all day."), btns);
    cancel.addEventListener("click", () => { form.hidden = true; });
    form.addEventListener("submit", async ev => {
      ev.preventDefault();
      const b = {title: fTitle.value.trim(), date: fDate.value, time: fTime.value, duration: Number(fDur.value), location: fLoc.value.trim()};
      if (!b.title || !b.date) return;
      if (demo()) {
        const d = parseDay(b.date), s = new Date(d);
        if (b.time) { const [h, m] = b.time.split(":").map(Number); s.setHours(h, m); }
        demoList().push({id: "t:demo" + Date.now(), title: b.title, start: b.time ? s.toISOString() : b.date, end: b.time ? new Date(s.getTime() + b.duration * 60000).toISOString() : ymd(addDays(d, 1)),
          all_day: !b.time, location: b.location, source: "Theta", color: "#b18cff"});
        T.toast("Added (demo: kept on this page).");
      } else {
        save.disabled = true;
        try { const r = await T.post("/api/calendar/events", b); T.toast(r.where === "google" ? "Added to your Google Calendar." : "Added. It's kept in Theta (Google isn't connected)."); }
        catch (e) { save.disabled = false; T.toast("Couldn't add that: " + (e.status === 400 ? "check the date and time." : "try again in a moment.")); return; }
        save.disabled = false;
      }
      form.hidden = true; fTitle.value = ""; fTime.value = ""; fLoc.value = "";
      day = parseDay(b.date); week = monday(day); render(); load();
    });

    // ---- calendar links
    let subs = [];
    async function loadSubs() {
      if (demo()) subs = demoSubs;
      else { try { subs = (await T.api("/api/calendar/subscriptions")).subscriptions || []; } catch (e) { subs = []; } }
      renderSubs();
    }
    const sName = el("input"), sUrl = el("input"), sAdd = el("button", "cal-primary", "Add link"), sForm = el("form", "cal-form");
    sName.placeholder = "Name, e.g. School"; sName.maxLength = 60; sName.setAttribute("aria-label", "Calendar name");
    sUrl.placeholder = "https://… or webcal://… (.ics)"; sUrl.type = "url"; sUrl.required = true; sUrl.setAttribute("aria-label", "Calendar link");
    sUrl.setAttribute("inputmode", "url"); sUrl.autocapitalize = "off"; sAdd.type = "submit";
    const sBtns = el("div", "cal-btns"); sBtns.append(sAdd);
    sForm.append(sName, sUrl, sBtns);
    sForm.addEventListener("submit", async ev => {
      ev.preventDefault();
      const url = sUrl.value.trim(), name = sName.value.trim();
      if (!url) return;
      if (demo()) { demoSubs.push({id: "d" + Date.now(), name: name || "Calendar", url, color: "#7be08a"}); T.toast("Added (demo)."); }
      else {
        try {
          const r = await T.http("/api/calendar/subscriptions", {method: "POST", headers: {"content-type": "application/json"}, body: JSON.stringify({url, name})});
          const j = await r.json().catch(() => ({}));
          if (!r.ok) { T.toast(j.error || "Couldn't add that link.", 4500); return; }
          T.toast("Calendar added.");
        } catch (e) { T.toast("Couldn't add that link right now."); return; }
      }
      sUrl.value = ""; sName.value = ""; loadSubs(); load();
    });
    function renderSubs() {
      subsBox.replaceChildren();
      for (const s of subs) {
        const r = el("div", "cal-sub"), dot = el("i"); dot.style.background = s.color || "#888";
        const w = el("div", "cal-what"); w.append(el("b", null, s.name || "Calendar"), el("span", null, s.url || ""));
        const x = el("button", "cal-x"); x.type = "button"; x.setAttribute("aria-label", "Remove " + (s.name || "calendar")); x.append(svg("i-close"));
        x.addEventListener("click", async () => {
          if (demo()) { demoSubs = demoSubs.filter(d => d.id !== s.id); subs = demoSubs; renderSubs(); return; }
          try { await T.api("/api/calendar/subscriptions?id=" + encodeURIComponent(s.id), {method: "DELETE"}); loadSubs(); load(); }
          catch (e) { T.toast("Couldn't remove that."); }
        });
        r.append(dot, w, x); subsBox.append(r);
      }
      if (!subs.length) subsBox.append(el("p", "cal-note", "No calendar links yet."));
      subsBox.append(sForm);
    }

    // ---- Settings: leave-by heads-ups and the Google account
    const g = T.settings("Calendar");
    const nRow = el("div", "row-set"), nTxt = el("div", "txt"), nSw = el("label", "switch"), nIn = el("input");
    nTxt.append(el("b", null, "Leave-by heads-ups"), el("span", null, "About 30 minutes before an event with a place, Theta texts you with directions."));
    nIn.type = "checkbox"; nIn.checked = true; nIn.setAttribute("aria-label", "Leave-by heads-ups"); nSw.append(nIn, el("i"));
    nRow.append(nTxt, nSw);
    const gRow = el("div", "row-set"), gTxt = el("div", "txt"), gInfo = el("span", null, "Gmail, Calendar and Drive."), gBtn = el("button", "btn-dark", "Connect");
    gBtn.type = "button"; gTxt.append(el("b", null, "Google account"), gInfo); gRow.append(gTxt, gBtn);
    g.append(nRow, gRow);
    let gConnected = false, gNote = "";
    async function loadSettings() {
      if (demo()) { gInfo.textContent = "Demo mode: nothing is connected."; return; }
      try { const s = await T.api("/api/calendar/settings"); nIn.checked = s.calendar_nudges !== false; } catch (e) {}
      try {
        const cons = await T.api("/api/connections"), gm = (Array.isArray(cons) ? cons : []).find(c => c.id === "gmail") || {};
        gConnected = !!gm.connected; gNote = gm.note || "";
        gInfo.textContent = gConnected ? `Connected${gm.account ? " as " + gm.account : ""}: Gmail, Calendar and Drive.` : (gNote || "Not connected. Connect to use Gmail, Calendar and Drive.");
        gBtn.textContent = gConnected ? "Disconnect" : (gNote && /7 days|signed/i.test(gNote) ? "Reconnect" : "Connect");
      } catch (e) {}
    }
    nIn.addEventListener("change", async () => {
      if (demo()) { T.toast(nIn.checked ? "Heads-ups on (demo)." : "Heads-ups off (demo)."); return; }
      try { await T.post("/api/calendar/settings", {calendar_nudges: nIn.checked}); } catch (e) { nIn.checked = !nIn.checked; T.toast("Couldn't save that."); }
    });
    gBtn.addEventListener("click", async () => {
      if (demo()) { T.toast("In demo mode nothing connects. On Theta this signs in with Google."); return; }
      if (!gConnected) { location.href = "/api/google/start"; return; }
      if (!confirm("Disconnect Google? Theta will stop reading your mail, calendar and files.")) return;
      try { await T.post("/api/google/disconnect"); T.toast("Google disconnected."); } catch (e) { T.toast("Couldn't disconnect right now."); }
      loadSettings();
    });
    const settingsEl = document.getElementById("settings");
    if (settingsEl) new MutationObserver(() => { if (!settingsEl.hidden) loadSettings(); }).observe(settingsEl, {attributes: true, attributeFilter: ["hidden"]});

    // ---- back from Google's sign-in
    const Q = new URLSearchParams(location.search);
    if (Q.has("connected") || Q.has("google_error")) {
      const err = Q.get("google_error"), msg = Q.get("connected") === "google" ? "Google is connected: Gmail, Calendar and Drive."
        : err === "not_configured" ? "Google isn't set up on the server yet (GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET)."
        : err === "access_denied" ? "Google wasn't connected: the sign-in was cancelled." : "Google didn't connect. Try Connect again.";
      const u = new URL(location.href); u.searchParams.delete("connected"); u.searchParams.delete("google_error");
      try { history.replaceState(history.state, "", u.pathname + u.search + u.hash); } catch (e) {}
      setTimeout(() => T.toast(msg, 4500), 2600);
    }
  }
  if (window.Theta) boot(); else window.addEventListener("theta:ready", boot, {once: true});
})();
