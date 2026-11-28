/* models: Settings > General > Models (server/modelcheck.py). Which model handles what, which keys the server has,
 * and "Check models": a one-word test to each model, with what answered and why the others didn't.
 * DOM nodes only, never innerHTML. Uses window.Theta (app.js). */
(() => {
  "use strict";
  const T = window.Theta;
  if (!T) return;
  const el = T.el;

  const style = document.createElement("style");
  style.textContent = `
.mc-keys { display: flex; flex-wrap: wrap; gap: 6px; padding: 12px 0; }
.mc-key { font-size: 13px; padding: 4px 10px; border-radius: 999px; background: #2a2a2a; color: var(--muted); }
.mc-key.on { background: rgba(76, 208, 125, .16); color: #4cd07d; }
.mc-tier { display: flex; justify-content: space-between; gap: 10px; padding: 10px 0; border-top: 1px solid #262626; font-size: 15px; }
.mc-tier b { font-weight: 500; }
.mc-tier small { display: block; color: var(--muted); font-size: 13px; }
.mc-tier .mc-m { text-align: right; color: #cfcfcf; font-size: 13.5px; overflow-wrap: anywhere; max-width: 55%; }
.mc-tier .mc-m.none { color: #ff8a80; }
.mc-res { display: flex; gap: 10px; align-items: flex-start; padding: 9px 0; border-top: 1px solid #262626; font-size: 14.5px; }
.mc-dot { width: 20px; flex: none; font-weight: 700; }
.mc-dot.ok { color: #4cd07d; } .mc-dot.bad { color: #ff8a80; }
.mc-res small { display: block; color: var(--muted); font-size: 13px; overflow-wrap: anywhere; }
`;
  document.head.append(style);

  const g = T.settings("Models", "general");
  g.classList.add("dev-only"); if (g.previousElementSibling) g.previousElementSibling.classList.add("dev-only");  // which model and key: developer details
  const fine = el("p", "fine set-fine", "Theta picks the model for each message. Check sends each one a one-word test, so you can see which keys work. Keys are read from DEEPSEEK_API_KEY, ANTHROPIC_API_KEY, GEMINI_API_KEY, GROQ_API_KEY and TAVILY_API_KEY on Railway (CLAUDE_API_KEY and GOOGLE_API_KEY work too). If a model name doesn't exist for your key, Check switches Theta to the closest one that works.");
  fine.classList.add("dev-only");
  let st = null, results = null, busy = false;
  const TIER = {quick: "Everyday", think: "Thinking", code: "Code", search: "Live facts", vision: "Photos", local: "Private"};

  function render() {
    g.replaceChildren();
    if (!st) { g.append(el("p", "fine", T.state.demo ? "Demo mode: this shows the real server's models." : "Loading…")); return; }
    const keys = el("div", "mc-keys");
    for (const p of st.providers) keys.append(el("span", "mc-key" + (p.key ? " on" : ""), (p.key ? "✓ " : "") + p.name));
    keys.append(el("span", "mc-key" + (st.search ? " on" : ""), (st.search ? "✓ " : "") + "Web search"));
    g.append(keys);
    for (const t of st.tiers) {
      const r = el("div", "mc-tier"), l = el("div");
      l.append(el("b", null, TIER[t.tier] || t.tier), el("small", null, t.what));
      const first = t.models[0];
      const m = el("div", "mc-m" + (first ? "" : " none"), first ? `${first.model}` + (t.models.length > 1 ? ` (+${t.models.length - 1} backup${t.models.length > 2 ? "s" : ""})` : "") : "none: add a key");
      r.append(l, m); g.append(r);
    }
    const row = el("div", "row-set"), tx = el("div", "txt");
    tx.append(el("b", null, "Check models"), el("span", null, busy ? "Testing each one…" : "About 10 seconds. Costs a fraction of a cent."));
    const b = el("button", "btn-dark", busy ? "Checking…" : "Check"); b.type = "button"; b.disabled = busy;
    b.addEventListener("click", run);
    row.append(tx, b); g.append(row);
    if (results) for (const r of results) {
      const d = el("div", "mc-res"), t = el("div");
      t.append(document.createTextNode(`${r.provider === "tavily" ? "Tavily" : r.model}`),
        el("small", null, r.ok ? (r.note ? r.note + " " : "") + `Answered in ${(r.ms / 1000).toFixed(1)}s · used for ${r.tiers.map(x => TIER[x] || x).join(", ")}` : r.error));
      d.append(el("span", "mc-dot " + (r.ok ? "ok" : "bad"), r.ok ? "✓" : "✕"), t); g.append(d);
    }
    if (!fine.isConnected) g.after(fine);
  }
  async function run() {
    if (T.state.demo) { T.toast("Demo mode: this checks the real server's models."); return; }
    busy = true; render();
    try { const r = await T.post("/api/models/check", {}); results = r.results || []; st = r.status || st; }
    catch (e) { T.toast((e && e.message) || "The check didn't run.", 4000); }
    busy = false; render();
  }
  async function load() {
    if (T.state.demo) { render(); return; }
    try { st = await T.api("/api/models/status"); } catch (e) {}
    render();
  }
  render();
  const sheet = document.getElementById("settings");
  if (sheet) new MutationObserver(() => { if (!sheet.hidden) load(); }).observe(sheet, {attributes: true, attributeFilter: ["hidden"]});
})();
