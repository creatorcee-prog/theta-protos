/* onboarding: the first-run intro, texted in the chat itself (server/onboarding.py). Uses window.Theta (app.js).
 * - On open, once signed in: GET /api/onboarding; while it's needed, POST {start: true} posts the current step's
 *   texts and the app's inbox check shows them (one step at a time, resuming where they left off).
 * - Each step's card {type: "onboarding", step, buttons, ...} is drawn here. Its buttons answer through
 *   POST /api/onboarding {step, answer} (never through chat, so nothing reaches the model) and some do the
 *   work first, with the app's own features: push subscribe, Settings > Sign-in, rounded location, time zone.
 * - Settings > Intro > "Run the intro again" starts over.
 * - Demo: /?demo=1&onboarding=1 runs the same steps against a stand-in for the route, in the page.
 * DOM nodes only, never innerHTML. */
(() => {
  "use strict";
  const T = window.Theta;
  if (!T) return;
  const el = T.el;
  const Q = new URLSearchParams(location.search);
  const $ = id => document.getElementById(id);
  const NS = "http://www.w3.org/2000/svg";
  const phoneTz = () => { try { return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC"; } catch (e) { return "UTC"; } };
  const city = tz => String(tz).split("/").pop().replace(/_/g, " ");

  const style = document.createElement("style");
  style.textContent = `
.onb-in { padding: 14px 16px 15px; display: flex; flex-direction: column; gap: 12px; font-size: 15px; line-height: 1.35; min-width: 0; }
.onb-chips { display: flex; flex-wrap: wrap; gap: 8px; }
.onb-chip { padding: 9px 15px; border-radius: 999px; background: #1b1b1b; border: 1px solid #3a3a3a; font-size: 15px; color: #e8e8e8; }
.onb-chip.primary { background: #fff; color: #111; border-color: #fff; font-weight: 600; }
.onb-chip:active { transform: scale(.97); }
.onb-chip[disabled] { opacity: .5; }
.onb-col { display: flex; flex-direction: column; gap: 8px; }
.onb-col .onb-chip { text-align: left; border-radius: 16px; padding: 12px 15px; }
.onb-done { display: flex; align-items: center; gap: 8px; color: var(--muted); font-size: 14px; }
.onb-done svg { width: 16px; height: 16px; color: var(--accent); }
.onb-field { display: flex; flex-direction: column; gap: 5px; }
.onb-field span { font-size: 12px; font-weight: 600; letter-spacing: .05em; text-transform: uppercase; color: var(--muted); }
.onb-field input, .onb-in select { background: #2c2c2c; border: 0; border-radius: 12px; padding: 11px 13px; font-size: 16px; color: var(--text); outline: none; width: 100%; min-width: 0; }
.onb-field input:focus, .onb-in select:focus { box-shadow: 0 0 0 2px rgba(79, 211, 255, .55); }
.onb-head { display: flex; align-items: center; gap: 12px; }
.onb-tile { width: 44px; height: 44px; border-radius: 12px; flex: none; display: grid; place-items: center; color: #fff; background: linear-gradient(140deg, var(--accent), var(--accent-2)); }
.onb-tile svg { width: 24px; height: 24px; }
.onb-head b { display: block; font-size: 16px; }
.onb-head small { display: block; color: var(--muted); font-size: 14px; }
.onb-tz { display: flex; align-items: center; gap: 12px; padding: 12px 14px; border-radius: 16px; background: #2a2a2a; }
.onb-tz b { font-size: 17px; display: block; }
.onb-tz small { color: var(--muted); font-size: 13px; }
.onb-clock { margin-left: auto; font-size: 22px; font-weight: 300; font-variant-numeric: tabular-nums; }
.onb-tips { display: flex; flex-direction: column; gap: 14px; }
.onb-tip { display: flex; gap: 12px; align-items: flex-start; }
.onb-tip .onb-tile { width: 36px; height: 36px; border-radius: 10px; }
.onb-tip .onb-tile svg { width: 20px; height: 20px; }
.onb-tip b { display: block; font-size: 15.5px; }
.onb-tip span { color: var(--muted); font-size: 14px; }
.onb-err { color: var(--danger); font-size: 13.5px; }
.onb-pulse { animation: onbPulse 1.6s ease-in-out 2; }
@keyframes onbPulse { 50% { box-shadow: 0 0 0 3px rgba(79, 211, 255, .45); } }
@media (prefers-reduced-motion: reduce) { .onb-pulse { animation: none; } }
`;
  document.head.append(style);

  const icon = (paths, extra) => {
    const v = document.createElementNS(NS, "svg");
    v.setAttribute("viewBox", "0 0 24 24"); v.setAttribute("aria-hidden", "true"); v.setAttribute("fill", "none");
    v.setAttribute("stroke", "currentColor"); v.setAttribute("stroke-width", "2"); v.setAttribute("stroke-linecap", "round"); v.setAttribute("stroke-linejoin", "round");
    for (const d of paths) { const p = document.createElementNS(NS, "path"); p.setAttribute("d", d); v.append(p); }
    for (const [tag, a] of extra || []) { const n = document.createElementNS(NS, tag); for (const k in a) n.setAttribute(k, a[k]); v.append(n); }
    return v;
  };
  const ICONS = {
    bell: () => icon(["M6 16V11a6 6 0 0112 0v5l1.5 2h-15z", "M10 20.5a2.2 2.2 0 004 0"]),
    face: () => icon(["M4 8V6a2 2 0 012-2h2M16 4h2a2 2 0 012 2v2M20 16v2a2 2 0 01-2 2h-2M8 20H6a2 2 0 01-2-2v-2", "M9 9.5v1M15 9.5v1M12 9.5v3.5h-1", "M9 15.5c1.7 1.3 4.3 1.3 6 0"]),
    pin: () => icon(["M12 21s-6.5-6.1-6.5-11a6.5 6.5 0 0113 0c0 4.9-6.5 11-6.5 11z"], [["circle", {cx: 12, cy: 10, r: 2.3}]]),
    hold: () => icon(["M9 11V5.5a1.5 1.5 0 013 0V11M12 10V8.5a1.5 1.5 0 013 0V11M15 10.5a1.5 1.5 0 013 0V15a6 6 0 01-6 6h-.5a6 6 0 01-4.6-2.2L4.5 16a1.6 1.6 0 012.4-2.1L9 15.5"]),
    react: () => icon(["M12 20s-7-4.4-7-10a4 4 0 017-2.6A4 4 0 0119 10c0 5.6-7 10-7 10z"]),
    clock: () => icon(["M12 8v4.5l3 2"], [["circle", {cx: 12, cy: 12, r: 8}]]),
    check: () => icon(["M5 12.5l4.5 4.5L19 7.5"]),
  };

  // ---------------------------------------------------------------- talking to the route
  const poll = () => window.dispatchEvent(new Event("protos:inbox")); // the app fetches new messages now
  async function call(body) {
    const r = await T.post("/api/onboarding", body);
    poll();
    return r;
  }
  function openChat() {
    if (typeof T.openChat === "function") { T.openChat(); return; }
    const chat = $("chat"), bot = $("home-bot");
    if (chat && chat.hidden && bot && !$("home").hidden) bot.click();
  }

  // the work some buttons do before answering, with the app's own features
  const DO = {
    async push() {
      if (T.push && typeof T.push.enable === "function") return (await T.push.enable()) ? "on" : "off";
      // until app.js exposes Theta.push.enable(): flip the Settings switch, which runs the same subscribe flow
      const sw = $("set-push");
      if (!sw) { T.toast("Turn on notifications in Settings."); return "off"; }
      if (T.store("protos:push") === "1") return "on";
      sw.checked = true; sw.dispatchEvent(new Event("change"));
      for (let i = 0; i < 60; i++) { await new Promise(r => setTimeout(r, 250)); if (T.store("protos:push") === "1") return "on"; if (!sw.checked) return "off"; }
      return T.store("protos:push") === "1" ? "on" : "off";
    },
    async faceid() {
      if (typeof T.openSettings === "function") T.openSettings("Sign-in");
      else {
        T.open("settings");
        setTimeout(() => {
          const h = [...document.querySelectorAll("#settings h3.sec")].find(x => /sign-in/i.test(x.textContent));
          if (h) { h.scrollIntoView({behavior: "smooth", block: "start"}); const g = h.nextElementSibling; if (g) { g.classList.add("onb-pulse"); setTimeout(() => g.classList.remove("onb-pulse"), 3400); } }
        }, 450);
      }
      return "opened";
    },
    location() {
      return new Promise((res, rej) => {
        if (!navigator.geolocation) { rej(new Error("This browser can't share location.")); return; }
        navigator.geolocation.getCurrentPosition(p => {
          const r1 = v => Math.round(v * 10) / 10; // about 11 km: Theta never gets the exact spot
          res({lat: r1(p.coords.latitude), lon: r1(p.coords.longitude)});
        }, () => rej(new Error("Location is off for this site. You can skip this one.")), {enableHighAccuracy: false, timeout: 15000, maximumAge: 600000});
      });
    },
  };

  // ---------------------------------------------------------------- the card
  function answeredLine(text) {
    const d = el("div", "onb-done"); d.append(ICONS.check(), el("span", null, text)); return d;
  }
  function render(c, m) {
    const box = el("div", "onb-in"); box.dataset.step = c.step;
    const err = el("div", "onb-err"); err.hidden = true;
    const fields = {};
    if (c.kind === "notify" || c.kind === "faceid" || c.kind === "location") {
      const head = el("div", "onb-head"), tile = el("div", "onb-tile"), t = el("div");
      tile.append((ICONS[c.icon] || ICONS.bell)());
      const [title, sub] = {notify: ["Notifications", "Only for things that matter"], faceid: ["Face ID", "Settings > Sign-in"],
        location: ["Rough location", "Rounded to about 10 km"]}[c.kind];
      t.append(el("b", null, title), el("small", null, sub));
      head.append(tile, t); box.append(head);
    }
    if (c.kind === "name") {
      for (const f of c.fields || []) {
        const lab = el("label", "onb-field"), inp = el("input"); inp.type = "text"; inp.placeholder = f.placeholder || ""; inp.maxLength = 60;
        inp.autocomplete = f.key === "name" ? "name" : "nickname"; inp.enterKeyHint = "done";
        lab.append(el("span", null, f.label), inp); box.append(lab); fields[f.key] = inp;
      }
    }
    let tzSel = null, tz = phoneTz();
    if (c.kind === "tz") {
      const row = el("div", "onb-tz"), t = el("div"), clock = el("div", "onb-clock");
      const tick = () => { try { clock.textContent = new Date().toLocaleTimeString([], {hour: "numeric", minute: "2-digit", timeZone: tz}); } catch (e) { clock.textContent = ""; } };
      const name = el("b", null, city(tz) + " time"), zone = el("small", null, tz + " · from your phone");
      t.append(name, zone); row.append(t, clock); box.append(row); tick();
      tzSel = el("select"); tzSel.hidden = true; tzSel.setAttribute("aria-label", "Time zone");
      let zones = []; try { zones = Intl.supportedValuesOf("timeZone"); } catch (e) { zones = ["America/Los_Angeles", "America/Denver", "America/Chicago", "America/New_York", "Europe/London", "Europe/Berlin", "Asia/Tokyo", "Australia/Sydney", "UTC"]; }
      if (!zones.includes(tz)) zones.unshift(tz);
      for (const z of zones) { const o = el("option", null, z.replace(/_/g, " ")); o.value = z; if (z === tz) o.selected = true; tzSel.append(o); }
      tzSel.addEventListener("change", () => { tz = tzSel.value; name.textContent = city(tz) + " time"; zone.textContent = tz; tick(); });
      box.append(tzSel);
    }
    if (c.kind === "tour") {
      const tips = el("div", "onb-tips");
      for (const tp of c.tips || []) { const r = el("div", "onb-tip"), tile = el("div", "onb-tile"), t = el("div"); tile.append((ICONS[tp.icon] || ICONS.check)()); t.append(el("b", null, tp.title), el("span", null, tp.text)); r.append(tile, t); tips.append(r); }
      box.append(tips);
    }
    if (c.answered) { box.append(answeredLine(c.answered)); for (const i of Object.values(fields)) i.disabled = true; if (tzSel) tzSel.disabled = true; return box; }
    const chips = el("div", c.kind === "chips" ? "onb-col" : "onb-chips");
    const all = [];
    const lock = on => { for (const b of all) b.disabled = on; for (const i of Object.values(fields)) i.disabled = on; if (tzSel) tzSel.disabled = on; };
    for (const b of c.buttons || []) {
      const x = el("button", "onb-chip" + (b.primary ? " primary" : ""), b.label); x.type = "button"; all.push(x);
      x.addEventListener("click", async () => {
        if (x.disabled) return;
        err.hidden = true;
        let answer = b.answer;
        if (b.do === "tz-pick") { tzSel.hidden = false; tzSel.focus(); x.hidden = true; const ok = all.find(y => y !== x && y.classList.contains("primary")); if (ok) ok.textContent = "Use this one"; return; }
        lock(true);
        try {
          if (b.answer === "skip_all") { await call({skip_all: true}); box.replaceChildren(answeredLine("Skipped the intro.")); return; }
          if (c.kind === "name" && b.answer === "save") {
            answer = {name: fields.name ? fields.name.value.trim() : "", call: fields.call ? fields.call.value.trim() : ""};
            if (!answer.name && !answer.call) throw new Error("Type your name, or tap Skip.");
          }
          if (b.do === "tz") answer = {tz};
          if (b.do === "push") answer = await DO.push();
          if (b.do === "faceid") answer = await DO.faceid();
          if (b.do === "location") answer = await DO.location();
          await call({step: c.step, answer});
          box.replaceChildren(...[...box.children].filter(n => n !== chips && n !== err), answeredLine(answer === "skip" ? "Skipped" : b.do === "push" && answer !== "on" ? "Not turned on" : b.label));
        } catch (e) {
          lock(false);
          err.textContent = e && e.status === 400 ? "That didn't work. Check it and try again, or tap Skip." : (e && e.message) || String(e);
          err.hidden = false;
        }
      });
      chips.append(x);
    }
    for (const i of Object.values(fields)) i.addEventListener("keydown", e => { if (e.key === "Enter") { e.preventDefault(); const save = all.find(b => b.classList.contains("primary")); if (save) save.click(); } });
    box.append(chips, err);
    void m;
    return box;
  }
  T.card("onboarding", render);

  // ---------------------------------------------------------------- start, resume, run again
  let started = false;
  async function maybeStart(force) {
    if (started && !force) return;
    started = true;
    try {
      const st = await T.api("/api/onboarding");
      if (!st || !st.needed) return;
      const r = await call({start: true, tz: phoneTz()});
      if ((r.messages || []).length || st.index === 0) setTimeout(openChat, 600);
    } catch (e) { started = false; }
  }
  function waitReady() {
    const S = T.state;
    if (!(S.ready && S.authed)) { setTimeout(waitReady, 400); return; } // after the splash, and after sign-in
    if (S.demo) { if (Q.get("onboarding") !== "1") return; demo(); }   // the plain demo has no intro
    maybeStart();
  }
  setTimeout(waitReady, 300);

  const g = T.settings("Intro");
  const row = el("div", "row-set"), txt = el("div", "txt"), again = el("button", "btn-dark", "Start");
  txt.append(el("b", null, "Run the intro again"), el("span", null, "Theta walks you through setup in the chat, one step at a time."));
  again.type = "button";
  again.addEventListener("click", async () => {
    again.disabled = true;
    try { if (T.state.demo) demo(); await call({reset: true, tz: phoneTz()}); T.close(); setTimeout(openChat, 350); }
    catch (e) { T.toast("Couldn't start the intro. Try again in a moment."); }
    finally { again.disabled = false; }
  });
  row.append(txt, again); g.append(row);

  // ---------------------------------------------------------------- demo: a stand-in for /api/onboarding
  // The same steps and words as server/onboarding.py, kept in the page. Messages go to the demo backend.
  let demoOn = false;
  function demo() {
    if (demoOn || !T.state.demo) return;
    demoOn = true;
    const C = T.cards;
    if (!C) return;
    C.patchDemo();
    const STEPS = ["hello", "name", "tz", "notify", "faceid", "location", "google", "routine", "tour", "done"];
    const st = {i: 0, posted: {}, cards: {}, name: "", done: false};
    const card = (step, buttons, extra) => Object.assign({type: "onboarding", step, buttons}, extra || {});
    const B = (label, answer, primary, d) => Object.assign({label, answer}, primary ? {primary: true} : {}, d ? {do: d} : {});
    const SK = B("Skip", "skip");
    const ROUT = {morning: ["Morning brief at 7:00", "The morning brief, please.", "Morning brief, every day at 7am"],
      evening: ["Evening wrap-up at 21:00", "The evening wrap-up, please.", "Evening wrap-up, every day at 9pm"],
      weekly: ["Weekly review on Sundays", "The weekly review, please.", "Weekly review, Sundays at 6pm"]};
    const script = step => ({
      hello: [["Hi, I'm Theta. I keep track of your day, look things up, draft emails for your OK, set reminders, and text you first when something matters.", []],
        ["Let's get you set up. It takes about a minute, one thing at a time, and you can skip anything.", [card("hello", [B("Let's go", "go", true), B("Skip the intro", "skip_all")])]]],
      name: [["First, what's your name, and what should I call you?", [card("name", [B("Save", "save", true), SK], {kind: "name", fields: [{key: "name", label: "Your name", placeholder: "Sam Rivera"}, {key: "call", label: "Call me", placeholder: "Sam (optional)"}]})]]],
      tz: [[(st.name ? `Nice to meet you, ${st.name}. ` : "") + "Which time zone are you in? Reminders and briefs follow it.", [card("tz", [B("That's right", "confirm", true, "tz"), B("Pick another", "pick", false, "tz-pick"), SK], {kind: "tz"})]]],
      notify: [["Want a notification when I text you first? I only do it for things that matter: reminders, alerts near you and your briefs. Quiet hours are on from 22:00 to 7:00.", [card("notify", [B("Turn on notifications", "on", true, "push"), B("Not now", "skip")], {kind: "notify", icon: "bell"})]]],
      faceid: [["You can sign in with Face ID instead of typing your key. Your face never leaves the phone; I only check a signature.", [card("faceid", [B("Set up Face ID", "opened", true, "faceid"), B("Later", "skip")], {kind: "faceid", icon: "face"})]]],
      location: [["For alerts near you (quakes, storms, official warnings from Vantage), I can use your rough location, rounded to about 10 km. This one's optional.", [card("location", [B("Share rough location", "share", true, "location"), B("No thanks", "skip")], {kind: "location", icon: "pin"})]]],
      google: [["Connect Google and I can check your calendar, find emails and files, and draft replies for your OK. Nothing is ever sent without your tap.",
        [{type: "connect", service: "google", name: "Google", letter: "G", title: "Connect Google", why: "Gmail, Calendar and Drive need your Google sign-in. One sign-in covers all three.", action: "/api/google/start"}, card("google", [B("Continue", "continue"), B("Skip for now", "skip")])]]],
      routine: [["Pick a first routine. I'll set it up now; you can change or delete it any time.", [card("routine", Object.entries(ROUT).map(([k, v]) => B(v[0], k)).concat([B("None for now", "skip")]), {kind: "chips"})]]],
      tour: [["Three small things before you go:", [card("tour", [B("Got it", "ok", true)], {kind: "tour", tips: [
        {icon: "hold", title: "Long-press a message", text: "Copy it, like or dislike it, edit what you said, or see which model answered."},
        {icon: "react", title: "React like a text", text: "Double-tap or long-press a reply to send a heart or a haha. I react too, sometimes."},
        {icon: "clock", title: "“Took 6s · read 3 emails”", text: "The line under a reply says what I actually did. Tap it to see the steps."}]})]]],
      done: [[`You're set${st.name ? ", " + st.name : ""}. Ask me anything, or just say hi. You can run this intro again from Settings.`, []]],
    })[step];
    const post = (step, first) => {
      const out = [];
      script(step).forEach(([text, cards], i) => {
        const meta = {source: "onboarding", onboarding: step}; if (first && !i) meta.proactive = true; if (cards.length) meta.cards = cards;
        const m = C.demoAdd("assistant", text, meta); out.push(m); if (cards.length) st.cards[step] = m;
      });
      st.posted[step] = true; return out;
    };
    const mark = (step, label) => { const m = st.cards[step]; if (m) m.meta.cards = m.meta.cards.map(c => c.type === "onboarding" ? Object.assign({}, c, {answered: label}) : c); };
    const pub = () => ({needed: !st.done, done: st.done, step: st.done ? "done" : STEPS[st.i], index: st.done ? 9 : st.i, steps: STEPS});
    const json = o => new Response(JSON.stringify(o), {status: 200, headers: {"content-type": "application/json"}});
    const D = window.ThetaDemo, orig = D.fetch;
    D.fetch = async (input, init) => {
      const u = new URL(typeof input === "string" ? input : input.url, location.href);
      if (u.pathname !== "/api/onboarding") return orig(input, init);
      await new Promise(r => setTimeout(r, 120));
      if (!init || !init.method || init.method === "GET") return json(pub());
      const b = JSON.parse(init.body || "{}"), out = [];
      if (b.reset) { st.i = 0; st.posted = {}; st.cards = {}; st.done = false; }
      if (b.reset || b.start) { if (!st.done && !st.posted[STEPS[st.i]]) out.push(...post(STEPS[st.i], !Object.keys(st.posted).length || b.reset)); return json(Object.assign(pub(), {messages: out})); }
      if (b.skip_all) { mark(STEPS[st.i], "Skip the intro."); out.push(C.demoAdd("user", "Skip the intro.", {source: "onboarding"}), C.demoAdd("assistant", "No problem. Ask me anything, or just say hi. You can run the intro any time from Settings.", {source: "onboarding"})); st.done = true; return json(Object.assign(pub(), {messages: out})); }
      const step = STEPS[st.i], a = b.answer;
      if (b.step !== step || st.done) return json(Object.assign(pub(), {messages: []}));
      let echo = "Skip.", ack = "";
      if (a !== "skip") {
        if (step === "hello") echo = "Let's go.";
        if (step === "name") { st.name = a.call || a.name; echo = `I'm ${a.name || a.call}.` + (a.call && a.name && a.call !== a.name ? ` Call me ${a.call}.` : ""); }
        if (step === "tz") { echo = `${city(a.tz)} time (${a.tz}).`; ack = `Got it, times are in ${city(a.tz)} time now.`; }
        if (step === "notify") { echo = a === "on" ? "Turn them on." : "Not now."; ack = a === "on" ? "Notifications are on. I'll keep them for things that matter." : "No notifications for now; you can turn them on in Settings."; }
        if (step === "faceid") echo = "Let me set up Face ID.";
        if (step === "location") { echo = "Share my rough location."; ack = "Saved, rounded to about 10 km. I'll only use it for alerts near you."; }
        if (step === "google") { echo = "I'll do it later."; ack = "No problem. Connect apps in the ... menu has it."; }
        if (step === "routine") { echo = ROUT[a][1]; ack = `Done: ${ROUT[a][2]}. It's in Routines.`; }
        if (step === "tour") echo = "Got it.";
      }
      mark(step, echo);
      out.push(C.demoAdd("user", echo, {source: "onboarding", onboarding: step}));
      if (ack) out.push(C.demoAdd("assistant", ack, {source: "onboarding", onboarding: step, ack: true}));
      st.i++; out.push(...post(STEPS[st.i]));
      if (STEPS[st.i] === "done") st.done = true;
      return json(Object.assign(pub(), {messages: out}));
    };
  }
})();
