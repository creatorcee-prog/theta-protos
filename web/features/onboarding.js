/* onboarding: the first-run intro, texted in the chat itself (server/onboarding.py). Uses window.Theta (app.js).
 * - Once the app is signed in and ready: GET /api/onboarding. While it's needed, POST {start: true, tz} posts the
 *   current step's texts and the app's inbox check shows them.
 * - Question cards {type: "onboarding", step, question, options, hint, dismiss, answered} are drawn here, with
 *   lettered options like a quiz (A, B, C). An option answers through POST /api/onboarding {step, answer}, or
 *   sends a chat message ({chat}) so the model does real work, or does something first ({do: "push"}).
 * - {type: "onboarding_event"} is a quiet centered line in the thread ("Renamed to Pip").
 * - The name Theta goes by (the "bot_name" setting) is shown in the header, home and the composer.
 * - Settings > General gets "Name" and "Run the intro again".
 * DOM nodes only, never innerHTML. */
(() => {
  "use strict";
  const T = window.Theta;
  if (!T) return;
  const el = T.el;
  const $ = id => document.getElementById(id);
  const NS = "http://www.w3.org/2000/svg";
  const phoneTz = () => { try { return Intl.DateTimeFormat().resolvedOptions().timeZone || ""; } catch (e) { return ""; } };

  const style = document.createElement("style");
  style.textContent = `
.thread .card.onb { background: none; overflow: visible; width: min(100%, 340px); }
.onb-box { background: var(--card); border: 1px solid #2c2c2c; border-radius: 22px; padding: 16px 16px 8px; position: relative; }
.onb-q { font-weight: 600; font-size: 17px; line-height: 1.3; padding-right: 30px; margin-bottom: 6px; }
.onb-x { position: absolute; top: 10px; right: 10px; width: 32px; height: 32px; border-radius: 50%; display: grid; place-items: center; color: #9a9a9a; }
.onb-x svg { width: 18px; height: 18px; }
.onb-opt { display: flex; align-items: center; gap: 14px; width: 100%; padding: 10px 0; text-align: left; font-size: 17px; color: var(--text); }
.onb-opt .k { width: 28px; height: 28px; border-radius: 8px; border: 1px solid #3a3a3a; display: grid; place-items: center; font-size: 13px; color: #bbb; flex: none; }
.onb-opt:active .k { background: #333; }
.onb-box.used .onb-opt { color: var(--muted); pointer-events: none; }
.onb-box.used .onb-opt.picked { color: var(--text); }
.onb-box.used .onb-opt.picked .k { background: #fff; color: #111; border-color: #fff; }
.onb-box.used .onb-x { display: none; }
.onb-hint { color: var(--muted); font-size: 14.5px; margin: 10px 4px 0; }
.onb-box.nobox { background: none; border: 0; padding: 0; }
.thread .card.onb-ev { background: none; align-self: center; width: auto; max-width: 100%; margin: 6px 0; }
.onb-ev-in { display: flex; align-items: center; gap: 7px; color: var(--muted); font-size: 14px; }
.onb-ev-in svg { width: 15px; height: 15px; }
.cards-added { display: flex; align-items: center; gap: 6px; color: #4cd07d; font-size: 15px; font-weight: 500; }
.cards-added svg { width: 16px; height: 16px; }
`;
  document.head.append(style);

  const icon = (d, w) => {
    const v = document.createElementNS(NS, "svg");
    v.setAttribute("viewBox", "0 0 24 24"); v.setAttribute("aria-hidden", "true"); v.setAttribute("fill", "none");
    v.setAttribute("stroke", "currentColor"); v.setAttribute("stroke-width", String(w || 2)); v.setAttribute("stroke-linecap", "round"); v.setAttribute("stroke-linejoin", "round");
    for (const p of [].concat(d)) { const n = document.createElementNS(NS, "path"); n.setAttribute("d", p); v.append(n); }
    return v;
  };
  const I = {
    x: () => icon("M6 6l12 12M18 6L6 18"),
    pencil: () => icon(["M4 20h4L19 9l-4-4L4 16z", "M13.5 6.5l4 4"], 1.8),
    check: () => icon("M5 12.5l4.5 4.5L19 7.5", 2.4),
  };

  // ---------------------------------------------------------------- the name Theta goes by
  let botName = "Theta";
  function applyName(name) {
    if (!name || typeof name !== "string") return;
    botName = name;
    const hn = document.querySelector("#home-bot .home-name"); if (hn) hn.textContent = name;
    const cn = document.querySelector("#chat-name span"); if (cn) cn.textContent = name;
    const ta = $("c-text"); if (ta) { ta.placeholder = "Ask " + name; ta.setAttribute("aria-label", "Message " + name); }
    $("home-bot") && $("home-bot").setAttribute("aria-label", "Open chat with " + name);
    $("chat-name") && $("chat-name").setAttribute("aria-label", name);
    document.title = name;
    const inp = $("set-botname"); if (inp && document.activeElement !== inp) inp.value = name;
  }

  // ---------------------------------------------------------------- talking to the route
  const poll = () => window.dispatchEvent(new Event("protos:inbox"));
  async function call(body) {
    const r = await T.post("/api/onboarding", body);
    if (r && r.bot_name) applyName(r.bot_name);
    poll();
    return r;
  }
  const DO = {
    async push() { // flip the Settings switch, which runs the app's own subscribe flow (needs this tap)
      const sw = $("set-push");
      if (!sw) return "off";
      if (T.store("protos:push") === "1") return "on";
      sw.checked = true; sw.dispatchEvent(new Event("change"));
      for (let i = 0; i < 60; i++) { await new Promise(r => setTimeout(r, 250)); if (T.store("protos:push") === "1") return "on"; if (!sw.checked) return "off"; }
      return T.store("protos:push") === "1" ? "on" : "off";
    },
  };

  // ---------------------------------------------------------------- cards
  T.card("onboarding", (c, m) => {
    const outer = el("div", "onb"), box = el("div", "onb-box");
    const opts = Array.isArray(c.options) ? c.options : [];
    const key = "onb:" + (m && m.id) + ":" + c.step;
    const picked = c.answered || T.store(key);
    if (picked) box.classList.add("used");
    if (!c.question && !opts.length) box.classList.add("nobox");
    if (c.question) box.append(el("div", "onb-q", c.question));
    const answer = async (o, b) => {
      if (box.classList.contains("used") || T.state.streaming) return;
      box.classList.add("used"); b.classList.add("picked"); T.store(key, o.label);
      try {
        if (o.chat) { T.send(o.chat, {show: o.label}); return; }
        let ans = o.answer;
        if (o.do && DO[o.do]) ans = await DO[o.do]();
        await call({step: c.step, answer: ans});
      } catch (e) {
        box.classList.remove("used"); b.classList.remove("picked"); T.store(key, "");
        T.toast((e && e.message) || "That didn't go through. Try again.", 3600);
      }
    };
    opts.forEach((o, i) => {
      const b = el("button", "onb-opt" + (picked && (picked === o.label || picked === o.answer) ? " picked" : "")); b.type = "button";
      b.append(el("span", "k", String.fromCharCode(65 + i)), el("span", null, o.label));
      b.addEventListener("click", () => answer(o, b));
      box.append(b);
    });
    if (c.dismiss && (c.question || opts.length)) {
      const x = el("button", "onb-x"); x.type = "button"; x.setAttribute("aria-label", "Skip this question"); x.append(I.x());
      x.addEventListener("click", () => answer({label: "Skipped", answer: "skip"}, x));
      box.append(x);
    }
    outer.append(box);
    if (c.hint && !picked) {
      // only the newest question keeps its "answer in the chat" hint
      document.querySelectorAll("#thread .onb-hint").forEach(h => h.remove());
      outer.append(el("p", "onb-hint", c.hint));
    }
    return outer;
  });

  T.card("onboarding_event", c => {
    const n = el("div", "onb-ev"), inner = el("div", "onb-ev-in");
    inner.append(c.icon === "pencil" ? I.pencil() : I.check(), el("span", null, c.text || ""));
    n.append(inner);
    return n;
  });

  // a connect card that's done says Added (the intro marks its Gmail card once Google is connected)
  T.decorate((m, row) => {
    const cards = ((m.meta || {}).cards || []);
    cards.forEach((c, i) => {
      if (!c || c.type !== "connect" || !c.connected) return;
      const node = row.querySelectorAll(".card")[i];
      const btns = node && node.querySelector(".cards-btns");
      if (!btns) return;
      const ok = el("div", "cards-added"); ok.append(I.check(), el("span", null, "Added"));
      btns.replaceWith(ok);
    });
  });

  // ---------------------------------------------------------------- Settings > General
  const g = T.settings("Name and intro", "general");
  const nameRow = el("div", "row-set"), nameTxt = el("div", "txt");
  nameTxt.append(el("b", null, "Name"), el("span", null, "What your assistant goes by, in the chat and on calls."));
  const inp = el("input"); inp.id = "set-botname"; inp.maxLength = 24; inp.autocomplete = "off"; inp.value = botName;
  inp.setAttribute("aria-label", "Assistant's name");
  inp.style.cssText = "background:#2a2a2a;border:0;border-radius:12px;padding:8px 10px;font-size:15px;width:9.5em;color:var(--text)";
  inp.addEventListener("change", async () => {
    const v = inp.value.trim();
    if (!v || v === botName) { inp.value = botName; return; }
    try { await T.post("/api/settings", {bot_name: v}); applyName(v); T.toast("Renamed to " + v + "."); }
    catch (e) { inp.value = botName; T.toast("Names can use letters, spaces, dots and hyphens, up to 24.", 3600); }
  });
  nameRow.append(nameTxt, inp);
  const introRow = el("div", "row-set"), introTxt = el("div", "txt");
  introTxt.append(el("b", null, "Run the intro again"), el("span", null, "The hello, the questions and the first task, in the chat."));
  const again = el("button", "btn-dark", "Start"); again.type = "button";
  again.addEventListener("click", async () => {
    if (T.state.demo) { T.toast("Demo mode: the intro runs on the real server."); return; }
    try { await call({reset: true, tz: phoneTz()}); T.close(); setTimeout(() => { const b = $("home-bot"); if (b && !$("home").hidden) b.click(); }, 300); }
    catch (e) { T.toast("Couldn't start the intro. Try again.", 3200); }
  });
  introRow.append(introTxt, again);
  g.append(nameRow, introRow);

  // ---------------------------------------------------------------- start or resume, once signed in
  let begun = false;
  async function begin() {
    if (begun || T.state.demo || !T.state.authed || !T.state.ready) return;
    begun = true;
    try {
      const st = await T.api("/api/onboarding");
      if (st && st.bot_name) applyName(st.bot_name);
      if (st && st.needed) await call({start: true, tz: phoneTz()});
    } catch (e) { begun = false; }
  }
  const tick = setInterval(() => { begin(); if (begun) clearInterval(tick); }, 400);
  setTimeout(() => clearInterval(tick), 60000);
  // back from Google's sign-in, or reopened: the intro may move on
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible" && begun && !T.state.demo) T.api("/api/onboarding").then(st => { if (st && st.needed) call({start: true, tz: phoneTz()}); }).catch(() => {});
  });
})();
