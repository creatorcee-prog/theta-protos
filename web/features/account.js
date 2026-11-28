/* account: the Settings pages about you (server/account.py).
   Root: the profile card, the storage warning, and the small values beside rows.
   Profile: photo, full name, nickname, email, phone, occupation, home, time zone, more about you, instructions.
   Personalization: style, warmth, enthusiasm, emoji. Memory: on/off, what Theta remembers (remove a line, add one).
   Usage: replies, tokens and cost (today, 7 and 30 days, 14 days of bars, by model).
   Data and storage: whether Theta's data survives deploys, backups (download, restore, Google Drive).
   Every field saves as you leave it. DOM nodes only, never innerHTML. Demo mode shows samples and saves nothing. */
(() => {
  "use strict";
  const T = window.Theta;
  if (!T) return;
  const {el} = T;
  const $ = id => document.getElementById(id);

  const css = document.createElement("style");
  css.textContent = `
.acc-photo { display: flex; flex-direction: column; align-items: center; gap: 10px; padding: 14px 0 6px; }
.acc-photo .set-avatar { width: 104px; height: 104px; font-size: 2.5882rem; }
.acc-pill { border: 1px solid #444; border-radius: var(--r-pill); padding: 7px 16px; font-size: var(--fs-m); color: var(--text); background: none; }
.acc-form { padding: 0 0 0 16px !important; }
.acc-f { display: flex; align-items: center; gap: 12px; min-height: 54px; padding-right: 16px; border-top: 1px solid var(--fill); }
.acc-f:first-child { border-top: 0; }
.acc-f label { width: 108px; flex: none; color: var(--muted); font-size: var(--fs-callout); }
.acc-f input, .acc-f select { flex: 1; min-width: 0; background: none; border: 0; color: var(--text); font-size: var(--fs-body); padding: 14px 0; outline: none; }
.acc-f select { appearance: none; -webkit-appearance: none; text-align: right; }
.acc-note { color: var(--muted); font-size: var(--fs-s); margin: 8px 4px 0; line-height: 1.4; }
.acc-area { width: 100%; min-height: 110px; background: var(--sunk); border: 0; border-radius: var(--r-l); padding: 14px 16px; color: var(--text);
  font-size: var(--fs-callout); line-height: 1.4; resize: vertical; outline: none; box-sizing: border-box; }
.acc-sel { display: flex; align-items: center; gap: 12px; min-height: 54px; padding-right: 16px; border-top: 1px solid var(--fill); }
.acc-sel:first-child { border-top: 0; }
.acc-sel span { flex: 1; font-size: var(--fs-body); }
.acc-sel select { background: none; border: 0; color: var(--muted); font-size: var(--fs-callout); text-align: right; }
.mem-line { display: flex; gap: 10px; align-items: flex-start; padding: 12px 0; border-top: 1px solid var(--fill); font-size: var(--fs-m); line-height: 1.4; padding-right: 12px; }
.mem-line:first-child { border-top: 0; }
.mem-line span { flex: 1; min-width: 0; overflow-wrap: anywhere; }
.mem-line button { color: var(--muted); font-size: var(--fs-lg); line-height: 1; padding: 0 4px; }
.mem-add { display: flex; gap: 8px; margin-top: 10px; }
.mem-add input { flex: 1; min-width: 0; background: var(--sunk); border: 0; border-radius: var(--r-m); padding: 11px 14px; color: var(--text); font-size: var(--fs-callout); }
.use-cards { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; }
.use-card { background: var(--sunk); border-radius: var(--r-l); padding: 12px; }
.use-card small { display: block; color: var(--muted); font-size: var(--fs-xs); }
.use-card b { display: block; font-size: var(--fs-lg); font-weight: 600; margin: 3px 0 1px; font-variant-numeric: tabular-nums; }
.use-card span { color: var(--muted); font-size: var(--fs-xs); font-variant-numeric: tabular-nums; }
.use-bars { display: flex; align-items: flex-end; gap: 4px; height: 90px; padding: 10px 2px 0; }
.use-bars i { flex: 1; background: var(--accent); border-radius: 4px 4px 0 0; min-height: 2px; opacity: .85; }
.use-days { display: flex; justify-content: space-between; color: var(--muted); font-size: var(--fs-2xs); padding: 4px 2px 0; }
.use-model { display: flex; justify-content: space-between; gap: 10px; padding: 11px 16px 11px 0; border-top: 1px solid var(--fill); font-size: var(--fs-m); }
.use-model:first-child { border-top: 0; }
.use-model span { color: var(--muted); white-space: nowrap; font-variant-numeric: tabular-nums; }
.dat-state { border-radius: var(--r-l); padding: 14px 16px; font-size: var(--fs-m); line-height: 1.45; }
.dat-state.ok { background: #13281a; border: 1px solid #22502f; color: #c9f1d4; }
.dat-state.bad { background: #3a1616; border: 1px solid #6b2525; color: #ffd7d2; }
.dat-state b { display: block; color: #fff; font-size: var(--fs-callout); margin-bottom: 2px; }
.dat-facts { color: var(--muted); font-size: var(--fs-sm); margin: 10px 4px 0; line-height: 1.5; }
.dat-bk { display: flex; justify-content: space-between; align-items: center; gap: 10px; padding: 10px 16px 10px 0; border-top: 1px solid var(--fill); font-size: var(--fs-m); }
.dat-bk:first-child { border-top: 0; }
#tab-data a.btn-dark { text-decoration: none; }
`;
  document.head.append(css);

  const DEMO = {profile: {name: "Sam Lee", nickname: "Sam", photo: "", email: "sam@example.com", phone: "+13035550142", occupation: "Designer",
      home: "Denver, CO", tz: "America/Denver", about: "Prefer short answers.", instructions: "Tell me when I'm wrong."},
    personalize: {style: "default", warmth: "more", enthusiasm: "less", emoji: "default", memory: true},
    storage: {persistent: true, why: "Saved on your Railway volume, so it survives deploys.", messages: 214, starts: 9,
      first_start: Date.now() / 1000 - 86400 * 21, oldest_message: Date.now() / 1000 - 86400 * 21, last_backup: {t: Date.now() / 1000 - 3600 * 5, where: "drive"}, drive_backup: true, drive_backup_on: true}};
  let acc = null;
  const demo = () => T.state.demo;
  const when = t => t ? new Date(t * 1000).toLocaleDateString(undefined, {month: "short", day: "numeric", year: "numeric"}) : "never";
  const ago = t => { if (!t) return "never"; const s = Date.now() / 1000 - t; return s < 3600 ? Math.max(1, Math.round(s / 60)) + " min ago" : s < 86400 ? Math.round(s / 3600) + " h ago" : when(t); };

  async function load() {
    if (demo()) { acc = acc || JSON.parse(JSON.stringify(DEMO)); return acc; }
    try { acc = await T.api("/api/account"); } catch (e) {}
    return acc;
  }
  async function save(part, patch) {
    if (demo()) { Object.assign(acc[part], patch); paintRoot(); T.toast("Saved (demo)."); return true; }
    try { acc = await T.post("/api/account", {[part]: patch}); paintRoot(); return true; }
    catch (e) { T.toast((e && e.message) || "Couldn't save that.", 4000); return false; }
  }
  function avatar(node, p) {
    node.textContent = p.photo ? "" : ((p.nickname || p.name || "?").trim()[0] || "?").toUpperCase();
    node.style.backgroundImage = p.photo ? `url("${p.photo}")` : "";
  }

  // ---------------------------------------------------------------- the root list
  function paintRoot() {
    if (!acc) return;
    const p = acc.profile, st = acc.storage;
    avatar($("set-avatar"), p);
    $("set-me-name").textContent = p.name || p.nickname || "Add your name";
    $("set-me-sub").textContent = p.email || p.occupation || "Name, photo, how Theta talks to you";
    $("nav-v-memory").textContent = acc.personalize.memory ? "On" : "Off";
    const w = $("set-storage-warn");
    w.hidden = !!st.persistent;
    if (!st.persistent) {
      const b = el("button", "btn-white", "How to fix"); b.type = "button";
      b.addEventListener("click", () => T.open("settings", "data"));
      w.replaceChildren(el("b", null, "Theta forgets everything on each deploy"), document.createTextNode(st.why), el("br"), b);
    }
    $("nav-v-data").textContent = st.persistent ? "" : "Not saved";
  }

  // ---------------------------------------------------------------- Profile
  const FIELDS = [["name", "Full name", "text", "name"], ["nickname", "Nickname", "text", "nickname"], ["email", "Email", "email", "email"],
    ["phone", "Phone", "tel", "tel"], ["occupation", "Occupation", "text", "organization-title"], ["home", "Home", "text", "address-level2"]];
  function zones() { try { return Intl.supportedValuesOf("timeZone"); } catch (e) { return ["America/Denver", "America/Los_Angeles", "America/Chicago", "America/New_York", "UTC"]; } }
  function profilePage() {
    const page = $("tab-profile"), p = acc.profile;
    const top = el("div", "acc-photo"), av = el("span", "set-avatar"); avatar(av, p);
    const pick = el("input"); pick.type = "file"; pick.accept = "image/*"; pick.hidden = true;
    const edit = el("button", "acc-pill", p.photo ? "Edit photo" : "Add photo"); edit.type = "button";
    edit.addEventListener("click", () => pick.click());
    pick.addEventListener("change", async () => {
      const f = pick.files && pick.files[0]; pick.value = ""; if (!f) return;
      if (demo()) { T.toast("Demo mode: photos save on the real server."); return; }
      try {
        const bmp = await createImageBitmap(f), side = Math.min(bmp.width, bmp.height), c = document.createElement("canvas");
        c.width = c.height = 384;
        c.getContext("2d").drawImage(bmp, (bmp.width - side) / 2, (bmp.height - side) / 2, side, side, 0, 0, 384, 384);
        const blob = await new Promise(r => c.toBlob(r, "image/jpeg", 0.85));
        const r = await T.http("/api/uploads", {method: "POST", headers: {"content-type": "image/jpeg"}, body: blob});
        const j = await r.json(); if (!r.ok) throw new Error(j.error || "upload failed");
        if (await save("profile", {photo: j.url})) { avatar(av, acc.profile); edit.textContent = "Edit photo"; T.toast("Photo saved."); }
      } catch (e) { T.toast("That photo didn't work. Try a JPEG or PNG.", 4000); }
    });
    top.append(av, edit, pick);
    const g = el("div", "group acc-form");
    for (const [k, label, type, ac] of FIELDS) {
      const row = el("div", "acc-f"), lab = el("label", null, label), inp = el("input");
      inp.id = "acc-" + k; lab.htmlFor = inp.id; inp.type = type; inp.value = p[k] || ""; inp.autocomplete = ac;
      inp.addEventListener("change", async () => { if (await save("profile", {[k]: inp.value})) { inp.value = acc.profile[k] || ""; T.toast("Saved."); } });
      row.append(lab, inp); g.append(row);
    }
    const tzRow = el("div", "acc-f"), tzl = el("label", null, "Time zone"), tz = el("select"); tz.id = "acc-tz"; tzl.htmlFor = "acc-tz";
    const here = Intl.DateTimeFormat().resolvedOptions().timeZone;
    for (const z of zones()) { const o = el("option", null, z.replace(/_/g, " ")); o.value = z; tz.append(o); }
    tz.value = p.tz || here || "America/Denver";
    tz.addEventListener("change", async () => { if (await save("profile", {tz: tz.value})) T.toast("Saved."); });
    tzRow.append(tzl, tz); g.append(tzRow);
    const note = el("p", "acc-note", "Theta calls you by your nickname. Your phone is where Theta calls or texts you; home is used for weather and travel times.");
    const area = (k, title, hint, ph) => {
      const h = el("h3", "sec", title), a = el("textarea", "acc-area"); a.value = p[k] || ""; a.placeholder = ph; a.maxLength = 1500;
      a.setAttribute("aria-label", title);
      a.addEventListener("change", async () => { if (await save("profile", {[k]: a.value})) T.toast("Saved."); });
      return [h, a, el("p", "acc-note", hint)];
    };
    const quiz = el("div", "group"); quiz.style.marginTop = "18px";
    { const r = el("div", "row-set"), t = el("div", "txt"), b = el("button", "btn-dark", "Take it"); b.type = "button";
      t.append(el("b", null, "Get-to-know-you quiz"), el("span", null, "A few minutes of questions in the chat; Theta fills this page in and suggests chips. Skip any."));
      b.addEventListener("click", () => (T.startQuiz ? T.startQuiz() : T.toast("The quiz isn't loaded yet. Try again.")));
      r.append(t, b); quiz.append(r); }
    page.replaceChildren(top, g, note,
      ...area("about", "More about you", "Anything Theta should keep in mind: what you do, who's who, what you care about.", "e.g., I'm a student, I live with my sister Ana, I'm training for a half marathon"),
      ...area("instructions", "Instructions", "These apply to every conversation, within Theta's rules (sending and spending still ask).", "e.g., Disagree with me when I'm wrong. Keep answers short."), quiz);
  }

  // ---------------------------------------------------------------- Personalization
  function personalizePage() {
    const page = $("tab-personalize"), s = acc.personalize;
    const g = el("div", "group acc-form");
    const sel = (k, label, opts) => {
      const row = el("div", "acc-sel"), sp = el("span", null, label), x = el("select"); x.setAttribute("aria-label", label);
      for (const [v, t] of opts) { const o = el("option", null, t); o.value = v; x.append(o); }
      x.value = s[k];
      x.addEventListener("change", async () => { if (await save("personalize", {[k]: x.value})) T.toast("Saved. Theta's next reply uses it."); });
      row.append(sp, x); g.append(row);
    };
    const LV = [["less", "Less"], ["default", "Default"], ["more", "More"]];
    sel("style", "Base style and tone", [["default", "Default"], ["concise", "Concise"], ["detailed", "Detailed"], ["casual", "Casual"], ["professional", "Professional"]]);
    sel("warmth", "Warmth", LV); sel("enthusiasm", "Enthusiasm", LV); sel("emoji", "Emoji", LV);
    const more = el("button", "acc-pill", "Profile and instructions"); more.type = "button"; more.style.marginTop = "14px";
    more.addEventListener("click", () => T.open("settings", "profile"));
    page.replaceChildren(el("p", "acc-note", "How Theta talks to you. It still sounds like Theta; these tune it."), g, more);
  }

  // ---------------------------------------------------------------- Memory
  async function memoryPage() {
    const page = $("tab-memory"), s = acc.personalize;
    const sw = el("div", "group"), row = el("div", "row-set"), tx = el("div", "txt");
    tx.append(el("b", null, "Use memory"), el("span", null, "Theta remembers facts about you across chats and uses them. Off: it stops reading and saving them (nothing is deleted)."));
    const lab = el("label", "switch"), inp = el("input"); inp.type = "checkbox"; inp.setAttribute("switch", ""); inp.checked = s.memory; inp.setAttribute("aria-label", "Use memory");
    inp.addEventListener("change", async () => { if (!(await save("personalize", {memory: inp.checked}))) inp.checked = !inp.checked; else T.toast(inp.checked ? "Memory is on." : "Memory is off."); });
    lab.append(inp, el("i")); row.append(tx, lab); sw.append(row);
    const list = el("div", "group"), add = el("form", "mem-add"), ai = el("input"), ab = el("button", "btn-dark", "Add");
    ai.placeholder = "Add something Theta should remember"; ai.setAttribute("aria-label", "Add a memory"); ab.type = "submit"; add.append(ai, ab);
    page.replaceChildren(sw, el("h3", "sec", "What Theta remembers"), list, add, el("p", "acc-note", "Theta adds to this as you talk. Remove anything that's wrong or that you'd rather it forgot."));
    let block = "";
    const paint = () => {
      const lines = block.split("\n").map(l => l.replace(/^[-*•]\s*/, "").trim()).filter(Boolean);
      list.replaceChildren(...(lines.length ? lines.map(l => {
        const r = el("div", "mem-line"), x = el("button", null, "×"); x.type = "button"; x.setAttribute("aria-label", "Forget: " + l);
        x.addEventListener("click", async () => {
          if (demo()) { block = block.split("\n").filter(b => !b.includes(l)).join("\n"); paint(); return; }
          try { const j = await T.post("/api/memory", {op: "remove", old: l}); block = j.block || ""; paint(); T.toast("Forgotten."); } catch (e) { T.toast("Couldn't remove that.", 3000); }
        });
        r.append(el("span", null, l), x); return r;
      }) : [el("p", "acc-note", "Nothing yet. Tell Theta about yourself, or add a line below.")]));
    };
    add.addEventListener("submit", async e => {
      e.preventDefault(); const t = ai.value.trim(); if (!t) return;
      if (demo()) { block += "\n- " + t; ai.value = ""; paint(); return; }
      try { const j = await T.post("/api/memory", {op: "add", text: t}); block = j.block || ""; ai.value = ""; paint(); } catch (err) { T.toast((err && err.message) || "Couldn't add that.", 3500); }
    });
    if (demo()) block = "- Calls me Sam\n- Training for a half marathon in April\n- Sister Ana lives in Boulder";
    else { try { block = (await T.api("/api/memory")).block || ""; } catch (e) {} }
    paint();
  }

  // ---------------------------------------------------------------- Usage
  const money = v => "$" + (v < 0.01 && v > 0 ? v.toFixed(4) : v.toFixed(2));
  const num = n => n >= 1e6 ? (n / 1e6).toFixed(1) + "M" : n >= 1e3 ? Math.round(n / 1e3) + "k" : String(n);
  async function usagePage() {
    const page = $("tab-usage");
    page.replaceChildren(el("p", "acc-note", "Loading…"));
    let u;
    if (demo()) u = {today: {replies: 12, tokens_in: 81000, tokens_out: 3200, cost_usd: 0.04}, week: {replies: 96, tokens_in: 610000, tokens_out: 24000, cost_usd: 0.31},
      month: {replies: 380, tokens_in: 2400000, tokens_out: 90000, cost_usd: 1.22}, models: [{provider: "deepseek", model: "deepseek-chat", replies: 350, tokens: 2300000, cost_usd: 0.9}],
      days: Array.from({length: 14}, (_, i) => ({day: "", replies: 5 + (i * 7) % 17, cost_usd: 0.02 + (i % 5) * 0.03}))};
    else { try { u = await T.api("/api/account/usage"); } catch (e) { page.replaceChildren(el("p", "acc-note", "Couldn't load usage.")); return; } }
    const cards = el("div", "use-cards");
    for (const [k, t] of [["today", "Today"], ["week", "7 days"], ["month", "30 days"]]) {
      const c = el("div", "use-card"), x = u[k];
      c.append(el("small", null, t), el("b", null, money(x.cost_usd)), el("span", null, `${x.replies} replies · ${num(x.tokens_in + x.tokens_out)} tokens`));
      cards.append(c);
    }
    const max = Math.max(0.0001, ...u.days.map(d => d.cost_usd));
    const bars = el("div", "use-bars"); bars.setAttribute("aria-label", "Cost per day, last 14 days");
    for (const d of u.days) { const i = el("i"); i.style.height = Math.round(d.cost_usd / max * 100) + "%"; i.title = `${d.day}: ${money(d.cost_usd)}, ${d.replies} replies`; bars.append(i); }
    const lbl = el("div", "use-days"); lbl.append(el("span", null, "14 days ago"), el("span", null, "Today"));
    const ms = el("div", "group acc-form");
    for (const m of u.models) { const r = el("div", "use-model"); r.append(document.createTextNode(m.model), el("span", null, `${m.replies} · ${money(m.cost_usd)}`)); ms.append(r); }
    if (!u.models.length) ms.append(el("p", "acc-note", "No replies yet."));
    page.replaceChildren(cards, el("h3", "sec", "Cost per day"), bars, lbl, el("h3", "sec", "By model (30 days)"), ms,
      el("p", "acc-note", "Costs are estimates from each provider's published prices; your provider's bill is the real number."));
  }

  // ---------------------------------------------------------------- Data and storage
  async function dataPage() {
    const page = $("tab-data"), st = acc.storage;
    const state = el("div", "dat-state " + (st.persistent ? "ok" : "bad"));
    state.append(el("b", null, st.persistent ? "Theta's data is safe across deploys" : "Theta forgets everything on each deploy"), document.createTextNode(st.why));
    const facts = el("p", "dat-facts",
      `Memory goes back to ${when(st.oldest_message || st.first_start)} · ${st.messages} messages · the server has started ${st.starts} time${st.starts === 1 ? "" : "s"}` +
      (st.last_start ? `, last ${ago(st.last_start)}` : "") + ".");
    const bk = el("div", "group acc-form");
    const row = (title, sub, node) => { const r = el("div", "row-set"), t = el("div", "txt"); t.append(el("b", null, title), el("span", null, sub)); r.append(t, node); bk.append(r); };
    const dl = el("a", "btn-dark", "Download"); dl.href = "/api/account/backup"; dl.setAttribute("download", "");
    if (demo()) dl.addEventListener("click", e => { e.preventDefault(); T.toast("Demo mode: backups download on the real server."); });
    row("Download a backup", "Everything Theta knows, as one file. Sign-ins to Google and your bank are left out.", dl);
    const file = el("input"); file.type = "file"; file.accept = ".db,application/x-sqlite3,application/octet-stream"; file.hidden = true;
    const rb = el("button", "btn-dark", "Restore"); rb.type = "button"; rb.addEventListener("click", () => file.click());
    file.addEventListener("change", async () => {
      const f = file.files && file.files[0]; file.value = ""; if (!f) return;
      if (demo()) { T.toast("Demo mode: restoring works on the real server."); return; }
      if (!confirm(`Replace Theta's data with ${f.name}? What's there now is kept as a copy on the server first.`)) return;
      try { const r = await T.http("/api/account/restore", {method: "POST", headers: {"content-type": "application/octet-stream"}, body: f});
        const j = await r.json(); if (!r.ok) throw new Error(j.error || "restore failed");
        T.toast(`Restored: ${j.messages} messages. Reloading…`, 4000); setTimeout(() => location.reload(), 1500);
      } catch (e) { T.toast((e && e.message) || "That file didn't restore.", 5000); }
    });
    row("Restore from a file", "Put a downloaded backup back. Apps you're connected to now stay connected.", rb);
    bk.append(file);
    const dg = el("div", "group acc-form");
    const lb = st.last_backup;
    page.replaceChildren(state, facts, el("h3", "sec", "Backups"), bk, el("h3", "sec", "Google Drive"), dg,
      el("p", "acc-note", lb ? `Last backup: ${ago(lb.t)} (${lb.where === "drive" ? "Google Drive" : "downloaded"})${lb.error ? ". The last Drive try failed: " + lb.error : ""}.` : "No backup yet."));
    if (!st.drive_backup) {
      const c = el("button", "btn-dark", "Connect"); c.type = "button"; c.addEventListener("click", () => T.open("settings", "connections"));
      const r = el("div", "row-set"), t = el("div", "txt"); t.append(el("b", null, "Backups to Drive"), el("span", null, "Connect Google with full Drive access and Theta saves a dated backup to a “Theta backups” folder every 3 hours. After a reset, connecting Google brings everything back by itself.")); r.append(t, c); dg.append(r);
      return;
    }
    const r = el("div", "row-set"), t = el("div", "txt"), lab = el("label", "switch"), sw = el("input");
    sw.type = "checkbox"; sw.setAttribute("switch", ""); sw.checked = st.drive_backup_on; sw.setAttribute("aria-label", "Backups to Drive");
    sw.addEventListener("change", async () => { if (demo()) return; try { acc = await T.post("/api/account", {drive_backup: sw.checked}); T.toast(sw.checked ? "Drive backups are on." : "Drive backups are off."); } catch (e) { sw.checked = !sw.checked; } });
    t.append(el("b", null, "Backups to Drive"), el("span", null, "Every 3 hours, in your Drive's “Theta backups” folder: the newest 16, plus one a day for 2 weeks. After a reset, Theta loads the newest one by itself.")); lab.append(sw, el("i")); r.append(t, lab); dg.append(r);
    const now = el("button", "btn-dark", "Back up now"); now.type = "button";
    const list = el("div");
    const paintList = bs => list.replaceChildren(...bs.slice(0, 7).map(b => {
      const x = el("div", "dat-bk"), go = el("button", "btn-dark", "Restore"); go.type = "button";
      go.addEventListener("click", async () => {
        if (demo()) { T.toast("Demo mode."); return; }
        if (!confirm(`Restore ${b.name}? What's there now is kept as a copy on the server first.`)) return;
        try { const j = await T.post("/api/account/restore?drive=" + encodeURIComponent(b.id), {}); T.toast(`Restored: ${j.messages} messages. Reloading…`, 4000); setTimeout(() => location.reload(), 1500); }
        catch (e) { T.toast((e && e.message) || "That backup didn't restore.", 5000); }
      });
      x.append(document.createTextNode(b.name.replace(/^Theta backup /, "").replace(/\.db$/, "")), go); return x;
    }));
    now.addEventListener("click", async () => {
      if (demo()) { T.toast("Demo mode."); return; }
      now.disabled = true; now.textContent = "Backing up…";
      try { const j = await T.post("/api/account/drive-backups", {}); paintList(j.backups || []); T.toast("Backed up to Drive."); }
      catch (e) { T.toast((e && e.message) || "Drive didn't take it.", 4000); }
      now.disabled = false; now.textContent = "Back up now";
    });
    dg.append(list); page.append(now);
    if (demo()) paintList([{id: "x", name: "Theta backup 2026-11-27 03.00.db"}, {id: "y", name: "Theta backup 2026-11-26 03.00.db"}]);
    else { try { paintList((await T.api("/api/account/drive-backups")).backups || []); } catch (e) {} }
  }

  const PAGES = {profile: profilePage, personalize: personalizePage, memory: memoryPage, usage: usagePage, data: dataPage};
  T.on("settings-page", async d => {
    if (!d) return;
    await load();
    if (!acc) return;
    if (d.page === "root") paintRoot();
    else if (PAGES[d.page]) PAGES[d.page]();
  });
  const sheet = document.getElementById("settings");
  if (sheet) new MutationObserver(async () => { if (!sheet.hidden) { await load(); paintRoot(); } }).observe(sheet, {attributes: true, attributeFilter: ["hidden"]});
})();
