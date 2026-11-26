/* approvals: the card for an action waiting for the user's tap, and Settings > Security > Approvals.
 * - Card {type: "approval", id, tool, preview, state, result}: shown as a compact list, one line per action (one or
 *   many) with a check and a cross dot; tap a line for the code-written preview. The full card below is the fallback
 *   renderer the list replaces. Tapping calls POST /api/approve; the card then says what happened (Done, Discarded,
 *   Didn't go through, Expired). state "auto" is a receipt: done without a tap because the user allows that action.
 * - Settings > Security > Approvals: for each action, ask first or just do it (server/approvals.py).
 * DOM nodes only, never innerHTML. Uses window.Theta (app.js). */
(() => {
  "use strict";
  const T = window.Theta;
  if (!T) return;
  const el = T.el;
  const NS = "http://www.w3.org/2000/svg";

  const style = document.createElement("style");
  style.textContent = `
.ap-in { padding: 14px 16px; display: flex; flex-direction: column; gap: 10px; font-size: 15px; line-height: 1.4; min-width: 0; }
.ap-kick { display: flex; align-items: center; gap: 7px; font-size: 12.5px; font-weight: 600; letter-spacing: .04em; text-transform: uppercase; color: var(--muted); }
.ap-kick svg { width: 15px; height: 15px; }
.ap-body { overflow-wrap: anywhere; }
.ap-body p { margin: 0 0 6px; }
.ap-body p:last-child { margin-bottom: 0; }
.ap-body blockquote { margin: 4px 0; padding-left: 10px; border-left: 2px solid #444; color: #ddd; }
.ap-btns { display: flex; gap: 8px; }
.ap-btns button { flex: 1; padding: 10px 0; border-radius: 999px; font-size: 15.5px; font-weight: 600; }
.ap-ok { background: #fff; color: #111; }
.ap-no { background: #333; color: var(--text); }
.ap-btns button[disabled] { opacity: .5; }
.ap-state { display: flex; align-items: center; gap: 7px; font-size: 14.5px; font-weight: 500; }
.ap-state svg { width: 16px; height: 16px; }
.ap-state.good { color: #4cd07d; } .ap-state.bad { color: #ff8a80; } .ap-state.meh { color: var(--muted); }
.ap-res { color: var(--muted); font-size: 13.5px; }
/* two or more in one message: a compact list, one line each, with dot buttons */
.apl { padding: 6px 0; min-width: 0; }
.apl-head { display: flex; align-items: center; justify-content: space-between; padding: 8px 16px 6px; font-size: 12.5px; font-weight: 600; letter-spacing: .04em; text-transform: uppercase; color: var(--muted); }
.apl-row { display: flex; align-items: center; gap: 10px; padding: 7px 10px 7px 16px; min-height: 44px; }
.apl-row + .apl-row { border-top: 1px solid #2c2c2c; }
.apl-txt { flex: 1; min-width: 0; text-align: left; color: var(--text); }
.apl-txt b { display: block; font-weight: 500; font-size: 15px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.apl-txt small { display: block; color: var(--muted); font-size: 12.5px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.apl-dot { width: 34px; height: 34px; border-radius: 50%; display: grid; place-items: center; flex: none; }
.apl-dot svg { width: 16px; height: 16px; }
.apl-dot.yes { background: #fff; color: #111; }
.apl-dot.no { background: #333; color: #ddd; }
.apl-dot[disabled] { opacity: .45; }
.apl-done { display: grid; place-items: center; width: 34px; height: 34px; flex: none; }
.apl-done svg { width: 17px; height: 17px; }
.apl-done.good { color: #4cd07d; } .apl-done.bad { color: #ff8a80; } .apl-done.meh { color: var(--muted); }
.apl-more { padding: 0 16px 10px; font-size: 14px; color: #ddd; overflow-wrap: anywhere; }
.apl-more p { margin: 0 0 4px; }
.apl-lit { white-space: pre-wrap; }
.apl-why { color: #ff8a80; padding-top: 0; font-size: 13px; }
.apl-all { font-size: 13px; font-weight: 600; color: var(--accent); letter-spacing: 0; text-transform: none; padding: 4px 0 4px 10px; }
.apl-all[disabled] { opacity: .45; }
`;
  document.head.append(style);

  const icon = d => { const v = document.createElementNS(NS, "svg"); v.setAttribute("viewBox", "0 0 24 24"); v.setAttribute("fill", "none"); v.setAttribute("stroke", "currentColor"); v.setAttribute("stroke-width", "2.2"); v.setAttribute("stroke-linecap", "round"); v.setAttribute("stroke-linejoin", "round"); v.setAttribute("aria-hidden", "true"); for (const p of [].concat(d)) { const n = document.createElementNS(NS, "path"); n.setAttribute("d", p); v.append(n); } return v; };
  const I = {check: () => icon("M5 12.5l4.5 4.5L19 7.5"), x: () => icon("M6 6l12 12M18 6L6 18"), clock: () => icon(["M12 8v4.5l3 2", "M12 3a9 9 0 100 18 9 9 0 000-18z"]), bolt: () => icon("M13 3L5 14h6l-1 7 8-11h-6z")};
  const LABEL = {send_email_draft: "Email", send_text: "Text", call_someone: "Phone call", calendar_invite: "Calendar invite",
    drive_share: "Share", browse_submit: "Website", gmail_trash: "Trash", gmail_unsubscribe: "Unsubscribe",
    calendar_delete: "Delete event", calendar_move: "Move event", drive_trash: "Drive trash"};
  const STATES = {done: ["good", "check", "Done"], auto: ["good", "bolt", "Done without asking"], denied: ["meh", "x", "Discarded"],
    failed: ["bad", "x", "Didn't go through"], expired: ["meh", "clock", "Expired: ask again if you still want it"]};

  function stateLine(state, result) {
    const [cls, ic, text] = STATES[state] || ["meh", "clock", state];
    const n = el("div", "ap-state " + cls); n.append(I[ic](), el("span", null, text));
    const out = [n];
    if (result && state === "failed") out.push(el("div", "ap-res", String(result)));
    return out;
  }

  T.card("approval", (c, m) => {
    const box = el("div", "ap-in");
    box.dataset.ap = "1";
    const kick = el("div", "ap-kick"); kick.append(el("span", null, LABEL[c.tool] || "Action"));
    const body = el("div", "ap-body"); body.append(T.md(c.preview || ""));
    box.append(kick, body);
    const key = "ap:" + c.id;
    const local = c.id != null ? T.store(key) : "";
    const state = c.state && c.state !== "pending" ? c.state : (local || "pending");
    if (state !== "pending") { box.append(...stateLine(state, c.result)); return box; }
    const btns = el("div", "ap-btns"), ok = el("button", "ap-ok", "Approve"), no = el("button", "ap-no", "Discard");
    ok.type = no.type = "button";
    ok.setAttribute("aria-label", "Approve: " + (LABEL[c.tool] || "action")); no.setAttribute("aria-label", "Discard: " + (LABEL[c.tool] || "action"));
    const decide = async decision => {
      if (T.state.demo) { T.toast("Demo mode: nothing was sent."); return; }
      ok.disabled = no.disabled = true;
      try {
        const r = await T.post("/api/approve", {id: c.id, decision});
        const st = (r && r.state) || (decision === "deny" ? "denied" : "done");
        T.store(key, st);
        btns.replaceWith(...stateLine(st, r && r.result));
      } catch (e) {
        // 409: already handled elsewhere (another device, a double tap); show what the server says
        ok.disabled = no.disabled = false;
        T.toast(human(e && e.message) || "That didn't go through. Try again.", 3600);
      }
      window.dispatchEvent(new Event("protos:inbox"));
    };
    ok.addEventListener("click", () => decide("approve"));
    no.addEventListener("click", () => decide("deny"));
    btns.append(ok, no); box.append(btns);
    return box;
  });

  // ---------------------------------------------------------------- every approval: a compact list (one line each)
  const plain = s => String(s || "").replace(/\*\*|__|`/g, "").replace(/^>\s?/, "").replace(/\s*<[^>]+@[^>]+>/g, "").trim();
  // a tool's error is written for the model ("Ask the user to..."): show the user the plain part
  function human(text) {
    const t = String(text || "").replace(/^Error:\s*/, "");
    if (/isn't connected|not connected|isn't set up|aren't set up/i.test(t)) {
      const what = (t.match(/^(Google|Gmail|Twilio|Texting|Phone calls|Google Drive)/i) || [])[1] || "That app";
      return `${what} isn't connected yet. Connect it in Settings > Apps, then try again.`;
    }
    const first = t.split(/(?<=[.!?])\s+/)[0] || "It didn't go through.";
    return first.replace(/\b(the user|they)\b/g, "you").slice(0, 160);
  }
  function summary(c) {
    const lines = String(c.preview || "").split("\n").map(plain).filter(Boolean);
    return [lines[0] || (LABEL[c.tool] || "Action"), lines[1] || ""];
  }
  function stateOf(c) { return c.state && c.state !== "pending" ? c.state : ((c.id != null && T.store("ap:" + c.id)) || "pending"); }

  function listCard(items) {
    const box = el("div", "apl"), head = el("div", "apl-head");
    const waiting = () => items.filter(c => stateOf(c) === "pending");
    // the header says what actually happened: "3 waiting for you", "All set", or "2 didn't go through"
    const headText = () => {
      const w = waiting().length, bad = items.filter(c => stateOf(c) === "failed").length;
      if (w) return w === 1 ? "Waiting for you" : `${w} waiting for you`;
      if (bad) return items.length === 1 ? "Didn't go through" : `${bad} didn't go through`;
      return items.length === 1 && stateOf(items[0]) === "denied" ? "Discarded" : "All set";
    };
    head.append(el("span", null, headText()));
    const all = el("button", "apl-all", "Approve all"); all.type = "button";
    if (waiting().length > 1) head.append(all);
    box.append(head);
    const rowsById = new Map();

    const doneMark = st => { const [cls, ic] = STATES[st] || ["meh", "clock"]; const n = el("span", "apl-done " + cls); n.append(I[ic]()); n.setAttribute("aria-label", (STATES[st] || [0, 0, st])[2]); return n; };
    async function decide(c, decision) {
      const r = rowsById.get(c.id);
      r.btns.forEach(b => { b.disabled = true; });
      try {
        const res = await T.post("/api/approve", {id: c.id, decision, quiet: true});
        const st = (res && res.state) || (decision === "deny" ? "denied" : "done");
        T.store("ap:" + c.id, st); c.state = st;
        r.slot.replaceChildren(doneMark(st));
        if (st === "failed") { r.why.textContent = human(res && res.result); r.why.hidden = false; }
      } catch (e) {
        r.btns.forEach(b => { b.disabled = false; });
        T.toast((e && e.message) || "That didn't go through. Try again.", 3600);
      }
      head.firstChild.textContent = headText();
      if (waiting().length < 2) all.remove();
      window.dispatchEvent(new Event("protos:inbox"));
    }

    for (const c of items) {
      const [title, sub] = summary(c), st = stateOf(c);
      const row = el("div", "apl-row"), txt = el("button", "apl-txt"); txt.type = "button";
      txt.append(el("b", null, title)); if (sub) txt.append(el("small", null, sub));
      txt.setAttribute("aria-expanded", "false");
      // details: what the title and detail line don't already say (an email's body, a trash list), quotes unwrapped
      // quoted lines are the literal words being sent (an email body, a text): plain text, never markdown
      const rest = String(c.preview || "").split("\n").filter(l => l.trim()).slice(2);
      const more = el("div", "apl-more"); more.hidden = true;
      for (const l of rest) more.append(/^>/.test(l) ? el("p", "apl-lit", l.replace(/^>\s?/, "")) : T.md(l));
      if (rest.length) txt.addEventListener("click", () => { more.hidden = !more.hidden; txt.setAttribute("aria-expanded", String(!more.hidden)); });
      else txt.removeAttribute("aria-expanded");
      const why = el("div", "apl-more apl-why"); why.hidden = true;
      const slot = el("span"); slot.style.display = "contents";
      const btns = [];
      if (st === "pending" && c.id != null) {
        const yes = el("button", "apl-dot yes"), no = el("button", "apl-dot no");
        yes.type = no.type = "button"; yes.append(I.check()); no.append(I.x());
        yes.setAttribute("aria-label", "Approve: " + title); no.setAttribute("aria-label", "Discard: " + title);
        yes.addEventListener("click", () => { if (T.state.demo) { T.toast("Demo mode: nothing was sent."); return; } decide(c, "approve"); });
        no.addEventListener("click", () => { if (T.state.demo) { T.toast("Demo mode: nothing was sent."); return; } decide(c, "deny"); });
        slot.append(yes, no); btns.push(yes, no);
      } else slot.append(doneMark(st));
      row.append(txt, slot);
      box.append(row, why, more);
      rowsById.set(c.id, {slot, btns, why});
    }
    all.addEventListener("click", async () => {
      if (T.state.demo) { T.toast("Demo mode: nothing was sent."); return; }
      all.disabled = true;
      for (const c of waiting()) await decide(c, "approve");
    });
    return box;
  }

  T.decorate((m, row) => {
    const items = ((m.meta || {}).cards || []).filter(c => c && c.type === "approval");
    if (!items.length) return;
    const nodes = [...row.querySelectorAll(".card")].filter(n => n.dataset.ap === "1");
    if (!nodes.length) return;
    const list = listCard(items); list.classList.add("card");
    nodes[0].before(list);
    nodes.forEach(n => n.remove());
  });

  // ---------------------------------------------------------------- Settings > Security > Approvals
  const g = T.settings("Approvals", "security");
  const fine = el("p", "fine set-fine", "Switched on, Theta does it and shows a card of exactly what it did. Emails, texts, calls, invites, sharing and websites still wait for you when a routine starts them or when that turn read an email, a web page or a file, so outside text can never make Theta act alone.");
  let rows = [];
  function render() {
    g.replaceChildren();
    for (const p of rows) {
      const r = el("div", "row-set"), t = el("div", "txt");
      t.append(el("b", null, p.label), el("span", null, p.what + (p.auto ? ". Does it without asking." : ". Asks you first.")));
      const sw = el("label", "switch"), inp = el("input"); inp.type = "checkbox"; inp.setAttribute("switch", ""); inp.checked = !!p.auto;
      inp.setAttribute("aria-label", p.label + ": do it without asking");
      inp.addEventListener("change", async () => {
        try { rows = await T.post("/api/approvals/policy", {tool: p.tool, auto: inp.checked}); render(); }
        catch (e) { inp.checked = !inp.checked; T.toast("Couldn't change that. Try again.", 3000); }
      });
      sw.append(inp, el("i")); r.append(t, sw); g.append(r);
    }
    if (!rows.length) g.append(el("p", "fine", "Loading…"));
    if (!fine.isConnected) g.after(fine);
  }
  async function load() {
    if (T.state.demo) { rows = []; render(); return; }
    try { rows = await T.api("/api/approvals/policy"); } catch (e) {}
    render();
  }
  render();
  const sheet = document.getElementById("settings");
  if (sheet) new MutationObserver(() => { if (!sheet.hidden) load(); }).observe(sheet, {attributes: true, attributeFilter: ["hidden"]});
})();
