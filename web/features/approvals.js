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
/* emails, texts and calls, framed inside Theta's bubble so the words are always visible */
.cm { margin-top: 10px; border: 1px solid #3a3a3a; border-radius: 16px; background: #171717; padding: 11px 12px 12px; font-size: 15px; line-height: 1.4; text-align: left; }
.cm:first-child { margin-top: 0; }
.cm-head { display: flex; align-items: center; gap: 7px; font-size: 12.5px; font-weight: 600; letter-spacing: .04em; text-transform: uppercase; color: var(--muted); margin-bottom: 6px; }
.cm-head svg { width: 15px; height: 15px; }
.cm-pill { margin-left: auto; text-transform: none; letter-spacing: 0; font-weight: 600; font-size: 12.5px; padding: 2px 9px; border-radius: 999px; background: #2a2a2a; color: #ddd; }
.cm-pill.good { background: rgba(76, 208, 125, .16); color: #4cd07d; } .cm-pill.bad { background: rgba(255, 138, 128, .15); color: #ff8a80; }
.cm-pill.wait { background: #fff; color: #111; }
.cm-line { color: #cfcfcf; font-size: 14px; overflow-wrap: anywhere; }
.cm-line span { color: var(--muted); display: inline-block; min-width: 3.2em; }
.cm-subj { font-weight: 600; font-size: 15.5px; margin: 4px 0 6px; overflow-wrap: anywhere; }
.cm-body { white-space: pre-wrap; overflow-wrap: anywhere; color: #eee; border-top: 1px solid #2c2c2c; padding-top: 8px; }
.cm-body.clamp { display: -webkit-box; -webkit-line-clamp: 9; -webkit-box-orient: vertical; overflow: hidden; }
.cm-more { color: var(--accent); font-size: 14px; padding: 6px 0 0; }
.cm-sms { margin-top: 6px; padding: 8px 12px; border-radius: 18px; white-space: pre-wrap; overflow-wrap: anywhere; max-width: 92%; }
.cm-sms.out { background: #0a84ff; color: #fff; margin-left: auto; border-bottom-right-radius: 6px; }
.cm-sms.in { background: #2c2c2e; color: #fff; border-bottom-left-radius: 6px; }
.cm-acts { display: flex; justify-content: flex-end; gap: 10px; margin-top: 10px; }
.cm-why { color: #ff8a80; font-size: 13px; margin-top: 6px; }
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

  // ---------------------------------------------------------------- emails, texts and calls, framed in the bubble
  const ICON = {
    email: () => icon(["M3.5 6.5h17v11h-17z", "M4 7l8 6 8-6"]),
    text: () => icon("M4 5h16v11H9l-4 3.5V16H4z"),
    text_in: () => icon("M4 5h16v11H9l-4 3.5V16H4z"),
    call: () => icon("M6.6 3.5l3 3.2-1.8 2.4a12 12 0 006.1 6.1l2.4-1.8 3.2 3-1.6 2.6C11 20 4 13 4 5.1z"),
  };
  const fmtNum = n => (/^\+1\d{10}$/.test(String(n || "")) ? `+1 ${n.slice(2, 5)}-${n.slice(5, 8)}-${n.slice(8)}` : String(n || ""));
  const KIND = {email: "Email", text: "Text", text_in: "Text", call: "Call"};
  function pill(kind, st) {
    const map = {pending: ["wait", "Waiting for you"], auto: ["good", kind === "call" ? "Calling" : "Sent"],
      done: ["good", kind === "call" ? "Calling" : "Sent"], denied: ["", "Discarded"], failed: ["bad", "Didn't go through"],
      expired: ["", "Expired"], draft: ["", "Draft in Gmail"], in: ["", "Received"]};
    const [cls, text] = map[st] || ["", st];
    return el("span", "cm-pill " + cls, text);
  }
  function frame(c) {
    const cm = c.comm || {}, kind = cm.kind || "email", st = c.type === "in" ? "in" : (c.type === "comm" ? (c.state || "draft") : stateOf(c));
    const box = el("div", "cm cm-" + kind), head = el("div", "cm-head");
    head.append((ICON[kind] || ICON.email)(), el("span", null, KIND[kind] || "Message"));
    let p = pill(kind, st); head.append(p);
    box.append(head);
    const line = (label, value) => { const d = el("div", "cm-line"); d.append(el("span", null, label), document.createTextNode(value)); return d; };
    if (kind === "email") {
      box.append(line("To", cm.to || ""));
      if (cm.cc) box.append(line("Cc", cm.cc));
      if (cm.subject) box.append(el("div", "cm-subj", cm.subject));
      const body = el("div", "cm-body", cm.body || ""); box.append(body);
      if ((cm.body || "").split("\n").length > 9 || (cm.body || "").length > 520) {
        body.classList.add("clamp");
        const more = el("button", "cm-more", "Show all"); more.type = "button";
        more.addEventListener("click", () => { body.classList.toggle("clamp"); more.textContent = body.classList.contains("clamp") ? "Show all" : "Show less"; });
        box.append(more);
      }
    } else if (kind === "text" || kind === "text_in") {
      const who = (cm.number && cm.number === cm.to ? fmtNum(cm.to) : (cm.to || "")) + (cm.number && cm.number !== cm.to ? " · " + fmtNum(cm.number) : "");
      box.append(line(kind === "text_in" ? "From" : "To", who));
      box.append(el("div", "cm-sms " + (kind === "text_in" ? "in" : "out"), cm.body || ""));
    } else {
      box.append(line("To", (cm.to || "") + (cm.number && cm.number !== cm.to ? " · " + fmtNum(cm.number) : "")));
      if (cm.body) box.append(el("div", "cm-body", cm.body));
    }
    if (st === "failed" && c.result) box.append(el("div", "cm-why", human(c.result)));
    if (c.type === "approval" && st === "pending" && c.id != null) {
      const acts = el("div", "cm-acts"), yes = el("button", "apl-dot yes"), no = el("button", "apl-dot no");
      yes.type = no.type = "button"; yes.append(I.check()); no.append(I.x());
      yes.setAttribute("aria-label", "Send it"); no.setAttribute("aria-label", "Discard it");
      const go = async decision => {
        if (T.state.demo) { T.toast("Demo mode: nothing was sent."); return; }
        yes.disabled = no.disabled = true;
        try {
          const res = await T.post("/api/approve", {id: c.id, decision, quiet: true});
          const s2 = (res && res.state) || (decision === "deny" ? "denied" : "done");
          T.store("ap:" + c.id, s2); c.state = s2;
          const np = pill(kind, s2); p.replaceWith(np); p = np; acts.remove();
          if (s2 === "failed") box.append(el("div", "cm-why", human(res && res.result)));
        } catch (e) { yes.disabled = no.disabled = false; T.toast(human(e && e.message), 3600); }
        window.dispatchEvent(new Event("protos:inbox"));
      };
      yes.addEventListener("click", () => go("approve")); no.addEventListener("click", () => go("deny"));
      acts.append(yes, no); box.append(acts);
    }
    return box;
  }

  T.card("comm", () => { const n = el("div"); n.dataset.comm = "1"; return n; });

  T.decorate((m, row, bubble) => {
    const meta = m.meta || {}, cards = meta.cards || [];
    const comms = cards.filter(c => c && c.comm && (c.type === "approval" || c.type === "comm"));
    if (meta.comm) comms.unshift({type: "in", comm: meta.comm});
    const rest = cards.filter(c => c && c.type === "approval" && !c.comm);
    const nodes = [...row.querySelectorAll(".card")].filter(n => n.dataset.ap === "1" || n.dataset.comm === "1");
    if (!comms.length && !rest.length) return;
    if (rest.length) { const list = listCard(rest); list.classList.add("card"); (nodes[0] ? nodes[0].before(list) : row.append(list)); }
    nodes.forEach(n => n.remove());
    if (comms.length && bubble && bubble.classList.contains("msg")) {
      if (meta.comm) bubble.replaceChildren();  // an incoming text: the frame is the whole message
      for (const c of comms) bubble.append(frame(c));
    }
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
