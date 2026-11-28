/* agents: the assistants beside Theta (server/agents.py). On Home, a row under Theta's globe: one button per agent
   (its color, its name, a count of replies waiting) and "New agent". A sheet makes or edits one: a name, a color,
   what it's for, instructions in the user's own words, and which apps it may use, with a few ready-made starts.
   In an agent's chat, the ... menu has "Edit this agent". Uses window.Theta (app.js). DOM only. */
(() => {
  "use strict";
  const T = window.Theta;
  if (!T || !T.agents) return;
  const {el, svg, toast} = T, $ = id => document.getElementById(id);

  // ready-made starts: tap one to fill the form, then change anything
  const STARTS = [
    {name: "Job hunter", color: "#4cd07d", about: "Finds jobs that fit me and keeps my applications moving",
     instructions: "Look for roles that match my experience and what I've said I want. Keep a short list of open applications and what's next on each. Draft cover letters in my voice for me to check. Never apply or email anyone without asking me.",
     apps: ["email", "calendar", "drive", "browser"]},
    {name: "Coach", color: "#ffb35c", about: "Keeps me on track with training, sleep and food",
     instructions: "Be encouraging but direct. Check in on workouts and sleep, suggest the next session, and keep it realistic for my week. No medical advice: send me to a doctor for anything that sounds like an injury.",
     apps: ["calendar"]},
    {name: "Money", color: "#ffd54a", about: "Watches my spending and subscriptions",
     instructions: "Watch for unusual charges, upcoming bills and subscriptions I may have forgotten. Give me plain numbers from my accounts, never guesses. Don't move money.",
     apps: ["money", "email"]},
    {name: "Trip planner", color: "#a78bfa", about: "Plans trips: flights, places to stay, what to do",
     instructions: "Plan around my budget and dates. Compare a few real options with prices and links. Put the plan in my calendar when I say yes.",
     apps: ["calendar", "browser", "email"]},
    {name: "Study buddy", color: "#ff7ab6", about: "Helps me learn: explains, quizzes, plans study time",
     instructions: "Explain simply first, then go deeper if I ask. Quiz me with short questions. Plan study sessions in my calendar.",
     apps: ["calendar", "drive"]},
  ];
  let APPS = [{key: "email", label: "Email"}, {key: "calendar", label: "Calendar"}, {key: "drive", label: "Drive and docs"},
              {key: "texts", label: "Texts and contacts"}, {key: "calls", label: "Phone calls"}, {key: "browser", label: "Browser"},
              {key: "money", label: "Bank"}, {key: "routines", label: "Routines"}, {key: "images", label: "Images"}];
  let COLORS = ["#4fd3ff", "#a78bfa", "#ff7ab6", "#ffb35c", "#4cd07d", "#ff6a5c", "#5b7cff", "#ffd54a"];

  const css = document.createElement("style");
  css.textContent = `
/* a sideways-scrolling box in Home's grid may shrink to nothing (it did: 6 px), so it holds its chips' height */
.ag-row { min-height: 54px; flex: none; display: flex; gap: 8px; overflow-x: auto; scrollbar-width: none; padding: 4px 16px 2px; margin-top: 6px; justify-content: safe center; max-width: 100%; }
.ag-row::-webkit-scrollbar { display: none; }
.ag-chip { flex: none; display: inline-flex; align-items: center; gap: 8px; min-height: 44px; padding: 6px 14px 6px 8px; border-radius: var(--r-pill);
  background: var(--fill); border: 1px solid var(--fill-2); font-size: var(--fs-sm); position: relative; }
.ag-chip.on { border-color: color-mix(in srgb, var(--ag) 70%, transparent); }
.ag-dot { width: 26px; height: 26px; border-radius: 50%; flex: none;
  background: radial-gradient(circle at 38% 34%, #fff 0 8%, color-mix(in srgb, var(--ag) 85%, #fff) 22%, var(--ag) 48%, color-mix(in srgb, var(--ag) 30%, #000) 100%);
  box-shadow: 0 0 12px color-mix(in srgb, var(--ag) 55%, transparent); }
.ag-new .ag-dot { background: var(--fill-2); box-shadow: none; display: grid; place-items: center; color: var(--text-2); }
.ag-new .ag-dot svg { width: 14px; height: 14px; }
.ag-badge { position: absolute; top: -3px; right: -3px; min-width: 18px; height: 18px; padding: 0 5px; border-radius: var(--r-pill);
  background: var(--danger); color: #fff; font-size: var(--fs-2xs); font-weight: 700; display: grid; place-items: center; }
.ag-form { display: flex; flex-direction: column; gap: 14px; padding-bottom: 8px; }
.ag-starts { display: flex; gap: 8px; overflow-x: auto; scrollbar-width: none; margin: 0 -2px; padding: 2px; }
.ag-starts button { flex: none; min-height: 40px; padding: 0 14px; border-radius: var(--r-pill); background: var(--fill); border: 1px solid var(--fill-2); font-size: var(--fs-sm); }
.ag-f label, .ag-f .ag-l { display: block; font-size: var(--fs-xs); color: var(--muted); margin: 0 2px 6px; text-transform: uppercase; letter-spacing: .04em; }
.ag-f input, .ag-f textarea { width: 100%; background: var(--fill); border: 1px solid var(--fill-2); border-radius: var(--r-m); padding: 12px 14px; font-size: var(--fs-body); color: var(--text); }
.ag-f textarea { min-height: 120px; resize: vertical; line-height: 1.4; }
.ag-colors { display: flex; gap: 10px; flex-wrap: wrap; }
.ag-colors button { width: 44px; height: 44px; border-radius: 50%; display: grid; place-items: center; }
.ag-colors button span { width: 30px; height: 30px; border-radius: 50%; background: var(--ag); }
.ag-colors button[aria-checked="true"] { box-shadow: inset 0 0 0 2px var(--ag); }
.ag-apps { display: flex; flex-wrap: wrap; gap: 8px; }
.ag-apps button { min-height: 40px; padding: 0 14px; border-radius: var(--r-pill); background: var(--fill); border: 1px solid var(--fill-2); font-size: var(--fs-sm); color: var(--text-2); }
.ag-apps button[aria-pressed="true"] { background: color-mix(in srgb, var(--accent) 22%, var(--fill)); border-color: var(--accent); color: var(--text); }
.ag-note { font-size: var(--fs-xs); color: var(--muted); margin: 6px 2px 0; }
.ag-actions { display: flex; gap: 10px; }
.ag-actions .ag-save { flex: 1; min-height: 50px; border-radius: var(--r-pill); background: var(--text); color: var(--bg); font-weight: 600; }
.ag-actions .ag-del { min-height: 50px; padding: 0 18px; border-radius: var(--r-pill); background: var(--fill); color: var(--bad-text); }
html[data-agent]:not([data-agent="theta"]) #chat-name { border-color: color-mix(in srgb, var(--agc, var(--accent)) 50%, transparent); }
`;
  document.head.append(css);

  // ---- Home: the agents row under Theta's globe
  const hero = $("home-bot");
  const row = el("div", "ag-row"); row.setAttribute("role", "list"); row.setAttribute("aria-label", "Your agents");
  if (hero) hero.after(row);
  function renderRow() {
    row.replaceChildren();
    const list = T.agents.list().filter(a => a.id !== "theta"), cur = T.agents.current();
    for (const a of list) {
      const b = el("button", "ag-chip" + (a.id === cur ? " on" : "")); b.type = "button"; b.setAttribute("role", "listitem");
      b.style.setProperty("--ag", a.color || "var(--accent)");
      const n = (T.state.unreadBy || {})[a.id] || 0;
      b.append(el("span", "ag-dot"), el("span", null, a.name));
      if (n) b.append(el("span", "ag-badge", String(Math.min(n, 99))));
      b.setAttribute("aria-label", `Open chat with ${a.name}` + (a.about ? `, ${a.about}` : "") + (n ? `, ${n} new` : ""));
      b.addEventListener("click", () => T.agents.open(a.id));
      b.addEventListener("contextmenu", e => { e.preventDefault(); editor(a); });  // right-click or long-press: edit
      row.append(b);
    }
    const nb = el("button", "ag-chip ag-new"); nb.type = "button"; nb.setAttribute("role", "listitem");
    const d = el("span", "ag-dot"); d.append(svg("i-plus")); nb.append(d, el("span", null, list.length ? "New" : "New agent"));
    nb.setAttribute("aria-label", "Make a new agent");
    nb.addEventListener("click", () => editor(null));
    row.append(nb);
  }
  T.on("agents", data => {
    renderRow();
    const a = T.agents.list().find(x => x.id === T.agents.current());
    document.documentElement.style.setProperty("--agc", a && a.color ? a.color : "var(--accent)");
    const item = document.querySelector('#menu [data-act="agent-edit"]'); if (item) item.hidden = !a || a.id === "theta";
    if (data && data.unread) { const who = T.agents.list().find(x => x.id === data.unread); if (who) toast(`${who.name} replied.`, 2400); }
  });
  document.getElementById("menu").addEventListener("click", e => {
    const b = e.target.closest('[data-act="agent-edit"]'); if (!b) return;
    const a = T.agents.list().find(x => x.id === T.agents.current()); if (a && a.id !== "theta") setTimeout(() => editor(a), 50);
  });

  // ---- the sheet: make or edit an agent
  let editing = null;
  const sheet = T.sheet("agent-edit", "New agent", () => render());
  async function editor(a) {
    editing = a; T.open("agent-edit");
    try { const j = await T.api("/api/bots?full=1"); if (j && j.apps) { APPS = j.apps; COLORS = j.colors || COLORS; } } catch (e) {}
    render();
  }
  function render() {
    const a = editing, body = sheet.body;
    sheet.root.querySelector(".sheet-head h2").textContent = a ? a.name : "New agent";
    const f = {name: a ? a.name : "", color: a ? a.color : COLORS[(T.agents.list().length - 1) % COLORS.length],
               about: a ? a.about || "" : "", instructions: a ? a.instructions || "" : "", apps: a ? a.apps : ["email", "calendar", "browser"]};
    const form = el("form", "ag-form");
    if (!a) {
      const st = el("div", "ag-starts"); st.setAttribute("aria-label", "Ready-made starts");
      for (const s of STARTS) { const b = el("button", null, s.name); b.type = "button"; b.addEventListener("click", () => { Object.assign(f, JSON.parse(JSON.stringify(s))); fill(); }); st.append(b); }
      form.append(el("p", "ag-note", "Start from one of these, or from scratch. You can change everything later."), st);
    }
    const field = (label, node) => { const w = el("div", "ag-f"), l = el("label", null, label); node.id = node.id || "ag-" + label.toLowerCase().replace(/\W+/g, "-"); l.htmlFor = node.id; w.append(l, node); return w; };
    const name = el("input"); name.maxLength = 24; name.autocomplete = "off"; name.required = true; name.placeholder = "e.g. Job hunter";
    const about = el("input"); about.maxLength = 140; about.placeholder = "What it's for, in a line";
    const instr = el("textarea"); instr.maxLength = 2000; instr.placeholder = "How it should work, in your words. What it should always do, and never do.";
    const colors = el("div", "ag-colors"); colors.setAttribute("role", "radiogroup"); colors.setAttribute("aria-label", "Color");
    const apps = el("div", "ag-apps"), allB = el("button", null, "Every app"); allB.type = "button";
    const appWrap = el("div", "ag-f"); appWrap.append(el("span", "ag-l", "Apps it may use"), apps,
      el("p", "ag-note", "Search, memory and reminders always work. Anything that sends, buys or deletes still asks you first."));
    function fill() {
      name.value = f.name; about.value = f.about; instr.value = f.instructions;
      colors.replaceChildren();
      for (const c of COLORS) {
        const b = el("button"); b.type = "button"; b.setAttribute("role", "radio"); b.setAttribute("aria-checked", String(c === f.color)); b.setAttribute("aria-label", "Color " + c);
        b.style.setProperty("--ag", c); b.append(el("span")); b.addEventListener("click", () => { f.color = c; fill(); }); colors.append(b);
      }
      apps.replaceChildren(allB); allB.setAttribute("aria-pressed", String(f.apps == null));
      for (const ap of APPS) {
        const on = f.apps == null || f.apps.includes(ap.key), b = el("button", null, ap.label); b.type = "button";
        b.setAttribute("aria-pressed", String(on));
        b.addEventListener("click", () => {
          const set = new Set(f.apps == null ? APPS.map(x => x.key) : f.apps);
          set.has(ap.key) ? set.delete(ap.key) : set.add(ap.key);
          f.apps = set.size === APPS.length ? null : [...set]; fill();
        });
        apps.append(b);
      }
    }
    allB.addEventListener("click", () => { f.apps = f.apps == null ? [] : null; fill(); });
    name.addEventListener("input", () => { f.name = name.value; }); about.addEventListener("input", () => { f.about = about.value; });
    instr.addEventListener("input", () => { f.instructions = instr.value; });
    form.append(field("Name", name), field("What it's for", about), field("Instructions", instr));
    const cw = el("div", "ag-f"); cw.append(el("span", "ag-l", "Color"), colors); form.append(cw, appWrap);
    const acts = el("div", "ag-actions"), save = el("button", "ag-save", a ? "Save" : "Make agent"); save.type = "submit";
    acts.append(save);
    if (a) {
      const del = el("button", "ag-del", "Remove"); del.type = "button"; let armed = false;
      del.addEventListener("click", async () => {
        if (!armed) { armed = true; del.textContent = "Tap again to remove"; setTimeout(() => { armed = false; del.textContent = "Remove"; }, 3000); return; }
        try {
          await T.api("/api/bots/" + encodeURIComponent(a.id), {method: "DELETE"});
          if (T.agents.current() === a.id) await T.agents.switch("theta");
          await T.agents.reload(); T.close(); toast(a.name + " removed. Its chat is kept, just hidden.");
        } catch (e) { toast("Couldn't remove it. Try again."); }
      });
      acts.append(del);
    }
    form.append(acts);
    form.addEventListener("submit", async e => {
      e.preventDefault();
      const payload = {name: f.name.trim(), color: f.color, about: f.about.trim(), instructions: f.instructions.trim(), apps: f.apps};
      if (!payload.name) { name.focus(); return; }
      save.disabled = true;
      try {
        const out = await T.post(a ? "/api/bots/" + encodeURIComponent(a.id) : "/api/bots", payload);
        await T.agents.reload(); T.agents.apply(); T.close();
        if (!a && out && out.id) { toast(`${out.name} is ready. Say hi.`); setTimeout(() => T.agents.open(out.id), 250); }
        else toast("Saved.");
      } catch (err) { toast(err && err.message && !/^(HTTP|timeout)/.test(err.message) ? err.message : "Couldn't save that.", 3200); }
      finally { save.disabled = false; }
    });
    fill();
    body.replaceChildren(form);
  }
})();
