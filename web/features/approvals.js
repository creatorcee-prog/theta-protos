/* approvals: the card for an action waiting for the user's tap, and Settings > Security > Approvals.
 * - Card {type: "approval", id, tool, preview, state, result}: what it'll do (the code-written preview), with its
 *   own Approve and Discard. Tapping calls POST /api/approve; the card then says what happened (Done, Discarded,
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
        T.toast((e && e.message) || "That didn't go through. Try again.", 3600);
      }
      window.dispatchEvent(new Event("protos:inbox"));
    };
    ok.addEventListener("click", () => decide("approve"));
    no.addEventListener("click", () => decide("deny"));
    btns.append(ok, no); box.append(btns);
    return box;
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
