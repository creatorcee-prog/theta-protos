/* routines: the "Routines & workflows" sheet (server/routines.py, server/workflows.py). Uses window.Theta (app.js).
 * Lists routines (when in plain words, next run, on/off, Run now, delete) and saved workflows (goal, uses, delete),
 * with a "+ New routine" form that posts to /api/routines and shows the parse hint when the words don't parse.
 * DOM nodes only, never innerHTML. In demo mode it shows sample data and changes nothing on a server. */
(() => {
  "use strict";
  const T = window.Theta;
  if (!T) return;
  const {el} = T;

  const css = `
#routines .rt-sec { font-size: 1.1176rem; font-weight: 500; margin: 20px 2px 8px; display: flex; align-items: center; justify-content: space-between; gap: 8px; }
#routines .rt-group { background: #1b1b1b; border-radius: 20px; padding: 2px 16px; }
#routines .rt-row { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 12px; padding: 14px 0; border-top: 1px solid #262626; }
#routines .rt-row:first-child { border-top: 0; }
#routines .rt-txt { flex: 1 1 180px; min-width: 0; }
#routines .rt-txt b { display: block; font-weight: 500; font-size: 1rem; overflow-wrap: anywhere; }
#routines .rt-txt span { display: block; color: var(--muted); font-size: 0.8235rem; line-height: 1.35; margin-top: 2px; overflow-wrap: anywhere; }
#routines .rt-txt .rt-status { color: #e7b35a; }
#routines .rt-btns { display: flex; gap: 8px; margin-left: auto; align-items: center; }
#routines .rt-btn { background: #333; color: var(--text); border-radius: 999px; padding: 7px 14px; font-size: 0.8235rem; white-space: nowrap; }
#routines .rt-btn:active { background: #3c3c3c; }
#routines .rt-btn.del { background: transparent; color: var(--danger); padding: 7px 8px; }
#routines .rt-btn[disabled] { opacity: .5; }
#routines .rt-empty { color: var(--muted); font-size: 0.8824rem; padding: 16px 0; }
#routines .rt-note { color: var(--muted); font-size: 0.8235rem; margin: 10px 2px; line-height: 1.4; }
#routines .rt-form { display: grid; gap: 10px; padding: 14px 0; }
#routines .rt-form label { display: grid; gap: 6px; font-size: 0.8235rem; color: var(--muted); }
#routines .rt-form input, #routines .rt-form textarea { background: #2a2a2a; color: var(--text); border: 0; border-radius: 12px; padding: 10px 12px; font: inherit; font-size: 0.9412rem; width: 100%; box-sizing: border-box; }
#routines .rt-form textarea { min-height: 70px; resize: vertical; }
#routines .rt-err { color: var(--danger); font-size: 0.8235rem; line-height: 1.4; min-height: 0; }
#routines .rt-err:empty { display: none; }
#routines .rt-add { background: #fff; color: #111; border-radius: 999px; padding: 8px 14px; font-size: 0.8824rem; font-weight: 600; }
`;
  const style = document.createElement("style"); style.textContent = css; document.head.append(style);

  const now = () => Date.now() / 1000;
  const DEMO = {
    routines: [
      {id: 1, name: "Morning brief", prompt: "Brief me on today: calendar, weather, anything urgent in email.", when_words: "weekdays at 7:30am", enabled: true, next_run: (() => { const d = new Date(); d.setDate(d.getDate() + 1); d.setHours(7, 30, 0, 0); return d.getTime() / 1000; })(), last_run: now() - 3600 * 10, status: "ok", runs: 12},
      {id: 2, name: "Fun fact", prompt: "Tell me one fun fact.", when_words: "every 2 hours", enabled: false, next_run: now() + 5400, last_run: null, status: "", runs: 0},
      {id: 3, name: "Landlord mail", prompt: "Summarize it and tell me if I need to do anything.", when_words: "when an email from acme-properties.com arrives", enabled: true, next_run: null, last_run: null, status: "waiting for Gmail", runs: 0, trigger: {kind: "email_from"}},
    ],
    workflows: [
      {id: 1, name: "Weekend weather check", goal: "Weather for Saturday and Sunday where I'll be, plus what to pack.", uses: 3, steps: [{tool: "web_search"}, {tool: "plan_update"}]},
    ],
  };
  let data = {routines: [], workflows: [], runs_today: 0, cap: 20};
  let showForm = false;

  function whenNext(t) {
    if (!t) return "";
    const d = new Date(t * 1000), today = new Date();
    const tm = d.toLocaleTimeString([], {hour: "numeric", minute: "2-digit"});
    const days = Math.round((new Date(d.toDateString()) - new Date(today.toDateString())) / 86400000);
    if (days === 0) return "today " + tm;
    if (days === 1) return "tomorrow " + tm;
    return d.toLocaleDateString([], {weekday: "short", day: "numeric", month: "short"}) + " " + tm;
  }

  async function send(method, path, body) {
    const r = await T.http(path, {method, headers: {"content-type": "application/json"}, body: JSON.stringify(body || {})});
    let j = {}; try { j = await r.json(); } catch (e) {}
    if (r.status === 401) throw Object.assign(new Error("Sign in again."), {status: 401});
    if (!r.ok) throw Object.assign(new Error(j.error || `Theta answered ${r.status}.`), {status: r.status, body: j});
    return j;
  }

  async function load() {
    if (T.state.demo) { data = Object.assign({runs_today: 3, cap: 20}, JSON.parse(JSON.stringify(DEMO))); return; }
    const [r, w] = await Promise.all([T.api("/api/routines"), T.api("/api/workflows").catch(() => ({workflows: []}))]);
    data = {routines: r.routines || [], runs_today: r.runs_today || 0, cap: r.cap || 20, workflows: w.workflows || []};
  }

  function sw(on, onChange, label) {
    const s = el("label", "switch"), i = el("input"); i.type = "checkbox"; i.checked = !!on; i.setAttribute("aria-label", label);
    i.addEventListener("change", () => onChange(i.checked, i)); s.append(i, el("i")); return s;
  }
  function btn(text, cls, fn) { const b = el("button", "rt-btn" + (cls ? " " + cls : ""), text); b.type = "button"; b.addEventListener("click", fn); return b; }

  function routineRow(r) {
    const row = el("div", "rt-row"), txt = el("div", "rt-txt");
    txt.append(el("b", null, r.name));
    const bits = [r.when_words || r.when || ""];
    if (r.enabled && r.next_run) bits.push("next " + whenNext(r.next_run));
    if (!r.enabled) bits.push("off");
    txt.append(el("span", null, bits.filter(Boolean).join(" · ")));
    txt.append(el("span", null, r.prompt));
    if (r.status && r.status !== "ok") txt.append(el("span", "rt-status", r.status));
    const btns = el("div", "rt-btns");
    const run = btn("Run now", "", async () => {
      if (T.state.demo) { T.toast("In demo mode nothing runs. On Theta the result arrives as a message."); return; }
      run.disabled = true;
      try { await send("POST", "/api/routines", {action: "run", id: r.id}); T.toast("Running. The result arrives as a message."); }
      catch (e) { T.toast(e.message); }
      finally { setTimeout(() => { run.disabled = false; }, 4000); }
    });
    const del = btn("Delete", "del", async () => {
      if (!confirm(`Delete the routine "${r.name}"?`)) return;
      if (T.state.demo) { DEMO.routines = DEMO.routines.filter(x => x.id !== r.id); await refresh(); return; }
      try { await send("DELETE", "/api/routines", {id: r.id}); await refresh(); } catch (e) { T.toast(e.message); }
    });
    btns.append(run, del, sw(r.enabled, async (on, input) => {
      if (T.state.demo) { const d = DEMO.routines.find(x => x.id === r.id); if (d) d.enabled = on; await refresh(); return; }
      try { await send("PATCH", "/api/routines", {id: r.id, enabled: on}); await refresh(); }
      catch (e) { input.checked = !on; T.toast(e.message); }
    }, `Turn ${r.name} ${r.enabled ? "off" : "on"}`));
    row.append(txt, btns);
    return row;
  }

  function workflowRow(w) {
    const row = el("div", "rt-row"), txt = el("div", "rt-txt");
    txt.append(el("b", null, w.name), el("span", null, w.goal || ""));
    const steps = (w.steps || []).map(s => s.tool).join(" → ");
    txt.append(el("span", null, `${steps}${steps ? " · " : ""}used ${w.uses || 0}×`));
    const btns = el("div", "rt-btns");
    btns.append(btn("Delete", "del", async () => {
      if (!confirm(`Delete the workflow "${w.name}"?`)) return;
      if (T.state.demo) { DEMO.workflows = DEMO.workflows.filter(x => x.id !== w.id); await refresh(); return; }
      try { await send("DELETE", "/api/workflows", {id: w.id}); await refresh(); } catch (e) { T.toast(e.message); }
    }));
    row.append(txt, btns);
    return row;
  }

  function form() {
    const f = el("form", "rt-form");
    const field = (label, tag, name, ph) => {
      const l = el("label", null, label), i = el(tag); i.name = name; i.placeholder = ph; i.required = name !== "name"; l.append(i); f.append(l); return i;
    };
    const name = field("Name", "input", "name", "Morning brief");
    const prompt = field("What to do", "textarea", "prompt", "Tell me today's weather and my first meeting");
    const when = field("When, in plain words", "input", "when", "weekdays at 7:30, every 2 hours, when I get an email from sam@example.com");
    const err = el("div", "rt-err"); err.setAttribute("role", "alert");
    const go = el("button", "rt-add", "Save routine"); go.type = "submit";
    f.append(err, go);
    f.addEventListener("submit", async e => {
      e.preventDefault(); err.textContent = "";
      const body = {name: name.value.trim(), prompt: prompt.value.trim(), when: when.value.trim()};
      if (!body.prompt || !body.when) { err.textContent = "Say what to do and when."; return; }
      if (T.state.demo) {
        DEMO.routines.push({id: Date.now(), name: body.name || body.prompt.slice(0, 40), prompt: body.prompt, when_words: body.when, enabled: true, next_run: null, status: "demo: not parsed here", runs: 0});
        showForm = false; await refresh(); return;
      }
      go.disabled = true;
      try { await send("POST", "/api/routines", body); showForm = false; T.toast("Routine saved."); await refresh(); }
      catch (ex) { err.textContent = ex.message; if (ex.body && ex.body.field === "when") when.focus(); }
      finally { go.disabled = false; }
    });
    setTimeout(() => prompt.focus(), 50);
    return f;
  }

  let sheet = null;
  function render() {
    const {body, pill} = sheet;
    pill.textContent = data.routines.length ? `${data.runs_today}/${data.cap} today` : "";
    const head = el("div", "rt-sec"); head.append(el("span", null, "Routines"));
    const add = el("button", "rt-btn", showForm ? "Cancel" : "+ New routine"); add.type = "button";
    add.addEventListener("click", () => { showForm = !showForm; render(); });
    head.append(add);
    const g = el("div", "rt-group");
    if (showForm) g.append(form());
    if (!data.routines.length && !showForm) g.append(el("div", "rt-empty", "No routines yet. Make one here, or tell Theta something like “every morning at 8, brief me”."));
    for (const r of data.routines) g.append(routineRow(r));
    const wh = el("div", "rt-sec"); wh.append(el("span", null, "Saved workflows"));
    const wg = el("div", "rt-group");
    if (!data.workflows.length) wg.append(el("div", "rt-empty", "None yet. After Theta does something in a few steps, tap “Save as a workflow”."));
    for (const w of data.workflows) wg.append(workflowRow(w));
    const note = el("p", "rt-note", T.state.demo ? "Demo mode: sample routines; nothing here reaches a server."
      : "Routines run as Theta and post their result as a message. Anything that would send or reach someone still waits for your OK.");
    body.replaceChildren(head, g, wh, wg, note);
  }
  async function refresh() {
    try { await load(); } catch (e) { if (e && e.status !== 401) T.toast("Couldn't load routines."); }
    render();
  }

  sheet = T.sheet("routines", "Routines & workflows", () => { showForm = false; render(); refresh(); });
  T.menu("Routines", "i-bell", "routines");
})();
