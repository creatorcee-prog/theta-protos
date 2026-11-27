/* chips: Theta's skills (server/chips.py). Settings > Chips lists them (turn one off, open it to edit, Reset a
   built-in, delete yours, make a new one). In the chat, a row of chips sits above the box while it's empty: a tap
   runs that chip now. DOM nodes only, never innerHTML. Demo mode keeps edits on this page only. */
(() => {
  "use strict";
  const T = window.Theta;
  if (!T) return;
  const {el} = T;

  const css = document.createElement("style");
  css.textContent = `
.chp-row { display: flex; gap: 8px; overflow-x: auto; margin: -12px -14px 6px; padding: 12px 14px 4px; scrollbar-width: none;
  -webkit-overflow-scrolling: touch; background: linear-gradient(rgba(20, 20, 20, .6), var(--bg) 45%); }
.chp-row::-webkit-scrollbar { display: none; }
.chp-row[hidden] { display: none; }
.chp-pill { flex: none; display: inline-flex; align-items: center; gap: 6px; padding: 8px 13px; border-radius: 999px; background: #232325;
  border: 1px solid #333; color: var(--text); font-size: 14.5px; white-space: nowrap; }
.chp-pill:active { background: #2e2e31; }
.chp-item { border-top: 1px solid #2a2a2a; }
.chp-item:first-child { border-top: 0; }
.chp-head { display: flex; align-items: center; gap: 12px; padding: 12px 16px 12px 0; }
.chp-ic { width: 38px; height: 38px; border-radius: 12px; background: #262628; display: grid; place-items: center; font-size: 20px; flex: none; }
.chp-txt { flex: 1; min-width: 0; text-align: left; color: var(--text); }
.chp-txt b { display: block; font-size: 16.5px; font-weight: 500; }
.chp-txt span { display: block; color: var(--muted); font-size: 13.5px; line-height: 1.35; margin-top: 1px; }
.chp-txt .chp-tag { display: inline-block; margin-top: 0; font-size: 11.5px; color: var(--muted); border: 1px solid #3a3a3a; border-radius: 999px; padding: 1px 7px; margin-left: 6px; vertical-align: 2px; }
.chp-edit { display: flex; flex-direction: column; gap: 8px; padding: 0 16px 14px 0; }
.chp-edit label { color: var(--muted); font-size: 13px; margin-top: 4px; }
.chp-edit input, .chp-edit textarea { background: #262628; border: 0; border-radius: 12px; padding: 10px 12px; color: var(--text); font-size: 15.5px; font-family: inherit; }
.chp-edit textarea { min-height: 150px; line-height: 1.4; resize: vertical; }
.chp-edit .chp-two { display: flex; gap: 8px; }
.chp-edit .chp-two input:first-child { width: 64px; flex: none; text-align: center; }
.chp-edit .chp-two input:last-child { flex: 1; min-width: 0; }
.chp-btns { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 4px; }
.chp-new { margin-top: 14px; }
`;
  document.head.append(css);

  const DEMO = [
    {id: "morning-brief", name: "Morning brief", icon: "☀️", when: "They ask for a brief or a rundown of the day.", prompt: "Give me my morning brief.", steps: "1. Weather…\n2. Today's calendar…", builtin: true, on: true},
    {id: "inbox-sweep", name: "Inbox sweep", icon: "📥", when: "They want their inbox cleaned up.", prompt: "Sweep my inbox.", steps: "1. …", builtin: true, on: true},
    {id: "plan-my-day", name: "Plan my day", icon: "🗓️", when: "They ask to plan their day.", prompt: "Plan my day.", steps: "1. …", builtin: true, on: true},
    {id: "best-price", name: "Best price", icon: "🏷️", when: "They want the best deal on something.", prompt: "Find me the best price on ", steps: "1. …", builtin: true, on: true},
    {id: "money-check", name: "Money check", icon: "💸", when: "They ask about spending or subscriptions.", prompt: "How's my money looking this month?", steps: "1. …", builtin: true, on: true}];
  let chips = null, open = null;
  const demo = () => T.state.demo;

  async function load() {
    if (demo()) { chips = chips || DEMO.map(c => Object.assign({}, c)); return chips; }
    try { chips = (await T.api("/api/chips")).chips; } catch (e) {}
    return chips;
  }
  async function call(method, body, q) {
    if (demo()) return null;
    const r = await T.http("/api/chips" + (q || ""), {method, headers: {"content-type": "application/json"}, body: body ? JSON.stringify(body) : undefined});
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(j.error || "That didn't save.");
    chips = j.chips; return j;
  }

  // ---------------------------------------------------------------- the row above the chat box
  const wrap = document.querySelector(".composer-wrap"), composer = document.getElementById("composer"), text = document.getElementById("c-text");
  const row = el("div", "chp-row"); row.setAttribute("role", "toolbar"); row.setAttribute("aria-label", "Chips");
  if (wrap && composer) wrap.insertBefore(row, composer);
  function paintRow() {
    const on = (chips || []).filter(c => c.on);
    row.replaceChildren(...on.map(c => {
      const b = el("button", "chp-pill"); b.type = "button"; b.append(el("span", null, c.icon || "✨"), document.createTextNode(c.name));
      b.addEventListener("click", () => run(c)); return b;
    }));
    sync();
  }
  // shown while the box is empty and Theta isn't answering; a prompt that ends in a space ("…price on ") is
  // put in the box to finish instead of sent
  function sync() { row.hidden = !row.childElementCount || !!(text && text.value.trim()) || !!T.state.streaming; }
  function run(c) {
    const p = String(c.prompt || c.name);
    if (/\s$/.test(p) && text) { text.value = p; text.dispatchEvent(new Event("input", {bubbles: true})); text.focus(); sync(); return; }
    T.send(`${p} (Use my "${c.name}" chip.)`, {show: `${c.icon || ""} ${c.name}`.trim()});
  }
  if (text) text.addEventListener("input", sync);
  for (const ev of ["user", "done", "error"]) T.on(ev, () => setTimeout(sync, 50));

  // ---------------------------------------------------------------- Settings > Chips
  function editor(c, isNew) {
    const f = el("form", "chp-edit");
    const icon = el("input"), name = el("input"), when = el("input"), prompt = el("input"), steps = el("textarea");
    icon.value = c.icon || "✨"; icon.maxLength = 8; icon.setAttribute("aria-label", "Icon (an emoji)");
    name.value = c.name || ""; name.placeholder = "Name"; name.maxLength = 40; name.setAttribute("aria-label", "Name");
    when.value = c.when || ""; when.placeholder = "When to use it, e.g. I ask for a rundown of my day"; when.maxLength = 240;
    prompt.value = c.prompt || ""; prompt.placeholder = "What tapping it sends"; prompt.maxLength = 400;
    steps.value = c.steps || ""; steps.placeholder = "The steps Theta follows, one per line"; steps.maxLength = 3000;
    const two = el("div", "chp-two"); two.append(icon, name);
    const btns = el("div", "chp-btns"), sv = el("button", "btn-white", isNew ? "Add chip" : "Save"); sv.type = "submit";
    btns.append(sv);
    if (!isNew) {
      const del = el("button", "btn-dark", c.builtin ? (c.edited ? "Reset to Theta's version" : "") : "Delete"); del.type = "button";
      if (del.textContent) {
        del.addEventListener("click", async () => {
          if (!c.builtin && !confirm(`Delete the ${c.name} chip?`)) return;
          try { if (demo()) chips = chips.filter(x => x.id !== c.id || c.builtin); else await call("DELETE", null, "?id=" + encodeURIComponent(c.id)); open = null; paintPage(); paintRow(); T.toast(c.builtin ? "Reset." : "Deleted."); }
          catch (e) { T.toast(e.message, 3500); }
        });
        btns.append(del);
      }
    }
    f.append(el("label", null, "Icon and name"), two, el("label", null, "When Theta uses it"), when, el("label", null, "Tapping it sends"), prompt,
      el("label", null, "Steps"), steps, btns);
    f.addEventListener("submit", async e => {
      e.preventDefault();
      const body = {icon: icon.value.trim(), name: name.value.trim(), when: when.value.trim(), prompt: prompt.value, steps: steps.value.trim()};
      if (!isNew) body.id = c.id;
      try {
        if (demo()) { if (isNew) chips.push(Object.assign({id: "x" + Date.now(), on: true, builtin: false}, body)); else Object.assign(c, body, {edited: c.builtin}); }
        else await call("POST", {chip: body});
        open = null; paintPage(); paintRow(); T.toast(isNew ? "Chip added." : "Saved.");
      } catch (err) { T.toast(err.message, 3500); }
    });
    return f;
  }
  function paintPage() {
    const page = document.getElementById("tab-chips"); if (!page || !chips) return;
    const g = el("div", "group acc-form");
    for (const c of chips) {
      const item = el("div", "chp-item"), head = el("div", "chp-head"), ic = el("span", "chp-ic", c.icon || "✨");
      const tx = el("button", "chp-txt"); tx.type = "button"; tx.setAttribute("aria-expanded", String(open === c.id));
      const b = el("b", null, c.name); if (c.builtin) b.append(el("span", "chp-tag", c.edited ? "Edited" : "Built in"));
      tx.append(b, el("span", null, c.when || ""));
      tx.addEventListener("click", () => { open = open === c.id ? null : c.id; paintPage(); });
      const lab = el("label", "switch"), sw = el("input"); sw.type = "checkbox"; sw.setAttribute("switch", ""); sw.checked = c.on; sw.setAttribute("aria-label", c.name + " on");
      sw.addEventListener("change", async () => {
        try { if (demo()) c.on = sw.checked; else await call("POST", {id: c.id, on: sw.checked}); paintRow(); } catch (e) { sw.checked = !sw.checked; T.toast(e.message, 3000); }
      });
      lab.append(sw, el("i")); head.append(ic, tx, lab); item.append(head);
      if (open === c.id) item.append(editor(c, false));
      g.append(item);
    }
    const nb = el("button", "btn-dark chp-new", open === "new" ? "Cancel" : "New chip"); nb.type = "button";
    nb.addEventListener("click", () => { open = open === "new" ? null : "new"; paintPage(); });
    const kids = [el("p", "acc-note", "Chips are Theta's playbooks for things you ask often. Theta opens the right one by itself when a request fits, and the ones that are on sit above the chat box for a one-tap run. You can also say “make that a chip” after Theta does something."), g, nb];
    if (open === "new") { const ng = el("div", "group acc-form"); ng.style.marginTop = "10px"; ng.style.paddingTop = "12px"; ng.append(editor({icon: "✨"}, true)); kids.push(ng); }
    page.replaceChildren(...kids);
    T.emit("chips-painted", {page, reload: async () => { if (!demo()) chips = null; await load(); paintPage(); paintRow(); }});
  }

  T.on("settings-page", async d => {
    if (!d) return;
    if (d.page === "chips") { await load(); paintPage(); }
    if (d.page === "root") { await load(); const v = document.getElementById("nav-v-chips"); if (v && chips) v.textContent = `${chips.filter(c => c.on).length} on`; }
  });
  // the app may still be signing in (or finding out it's the demo) when this runs: try again a few times
  (async () => { for (const ms of [0, 1500, 4000, 9000]) { await new Promise(r => setTimeout(r, ms)); await load(); if (chips) { paintRow(); return; } } })();
})();
