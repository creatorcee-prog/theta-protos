/* calls: phone calls through Telnyx (server/calls.py, server/telco.py). A "Phone calls" section in Settings (your number, the name
   Theta gives when it calls someone for you, "Call me on Red alerts", a test call) and a compact card for call
   messages (meta.source == "call"): who, how long, the outcome, and the transcript behind a tap.
   Builds DOM nodes only. In demo mode nothing is sent: the section shows sample values and a sample card. */
(() => {
  "use strict";
  const T = window.Theta;
  if (!T) return;
  const {el} = T;

  const css = document.createElement("style");
  css.textContent = `
.calls-card { display: flex; flex-direction: column; gap: 6px; min-width: 220px; }
.calls-card .calls-top { display: flex; align-items: center; gap: 10px; }
.calls-card .calls-ic { flex: none; width: 34px; height: 34px; border-radius: 50%; display: grid; place-items: center;
  background: linear-gradient(145deg, #1f6f8b, #1b3f6b); font-size: 17px; }
.calls-card .calls-who { font-weight: 600; display: block; }
.calls-card .calls-sub { color: var(--muted); font-size: 14px; display: block; }
.calls-card .calls-out { font-size: 16px; line-height: 1.38; }
.calls-card details { font-size: 15px; }
.calls-card summary { color: var(--accent); cursor: pointer; list-style: none; padding: 2px 0; }
.calls-card summary::-webkit-details-marker { display: none; }
.calls-card .calls-line { margin: 6px 0 0; line-height: 1.35; }
.calls-card .calls-line b { color: var(--muted); font-weight: 500; margin-right: 6px; }
.calls-phone { background: #2a2a2a; border: 0; border-radius: 12px; padding: 8px 12px; font-size: 16px; color: var(--text);
  width: 100%; max-width: 230px; outline: none; }
.calls-phone:focus { box-shadow: 0 0 0 2px #3a3a3a; }
.calls-note { color: var(--muted); font-size: 14px; margin: 0; padding: 0 0 12px; line-height: 1.35; }
.calls-sample { padding: 8px 0 14px; }
.calls-sample .msg { max-width: 100%; }
`;
  document.head.append(css);

  const dur = s => { s = Math.max(0, Math.round(Number(s) || 0)); return Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0"); };

  // ---------------------------------------------------------------- the call card
  function card(meta) {
    const c = el("div", "calls-card");
    const top = el("div", "calls-top"), ic = el("div", "calls-ic", "☎"), who = el("div");
    ic.setAttribute("aria-hidden", "true");
    const other = meta.kind === "other";
    const name = other ? "Call to " + (meta.name || meta.to || "someone") : (meta.kind === "alert" ? "Alert call to you" : "Theta called you");
    const bits = [];
    if (meta.duration) bits.push(dur(meta.duration));
    if (other && meta.name && meta.to) bits.push(String(meta.to));
    who.append(el("span", "calls-who", name), el("span", "calls-sub", bits.join(" · ") || "Phone call"));
    top.append(ic, who);
    c.append(top);
    if (meta.outcome) c.append(el("div", "calls-out", String(meta.outcome)));
    const lines = Array.isArray(meta.transcript) ? meta.transcript : [];
    if (lines.length) {
      const d = el("details"), s = el("summary", null, `Transcript (${lines.length} line${lines.length === 1 ? "" : "s"})`);
      d.append(s);
      for (const t of lines) {
        const p = el("p", "calls-line");
        p.append(el("b", null, t.who === "theta" ? "Theta" : (other ? "Them" : "You")), document.createTextNode(String(t.text || "")));
        d.append(p);
      }
      c.append(d);
    }
    return c;
  }

  T.decorate((m, row, bubble) => {
    const meta = m && m.meta;
    if (!meta || meta.source !== "call" || !bubble || !bubble.classList.contains("msg")) return;
    bubble.replaceChildren(card(meta));
    bubble.classList.add("calls-msg");
  });

  // ---------------------------------------------------------------- Settings > Phone calls
  const g = T.settings("Phone calls");
  const note = el("p", "calls-note", "");

  const row = (title, sub) => {
    const r = el("div", "row-set"), t = el("div", "txt"), s = el("span", null, sub);
    t.append(el("b", null, title), s); r.append(t); return {r, s};
  };

  const phone = el("input", "calls-phone");
  phone.type = "tel"; phone.inputMode = "tel"; phone.autocomplete = "tel"; phone.placeholder = "+13035551234";
  phone.setAttribute("aria-label", "Your phone number");
  const pr = row("Your number", "In international form. Theta only ever calls you on this number.");
  pr.r.append(phone);

  const name = el("input", "calls-phone");
  name.type = "text"; name.autocomplete = "given-name"; name.placeholder = "Your first name"; name.maxLength = 40;
  name.setAttribute("aria-label", "Your name for calls");
  const nr = row("Your name", "Said at the start of calls to others: “Theta, an AI assistant calling on behalf of…”");
  nr.r.append(name);

  const sw = el("label", "switch"), red = el("input");
  red.type = "checkbox"; red.setAttribute("aria-label", "Call me on Red alerts");
  sw.append(red, el("i"));
  const rr = row("Call me on Red alerts", "If a Red alert near you goes out, Theta also phones you and reads it.");
  rr.r.append(sw);

  const test = el("button", "btn-dark", "Test call"); test.type = "button";
  const tr = row("Test call", "Theta calls your number and says a short line.");
  tr.r.append(test);

  const rsw = el("label", "switch"), rec = el("input");
  rec.type = "checkbox"; rec.setAttribute("switch", ""); rec.setAttribute("aria-label", "Record calls");
  rsw.append(rec, el("i"));
  const recr = row("Record calls", "Calls to others start with “This call is recorded.” If they say they'd rather not, Theta stops and keeps none of it. Recordings stay 90 days, in Call history.");
  recr.r.append(rsw);
  // the voice people hear: a natural preset, or your own ElevenLabs voice (cloned or from their library)
  const vsel = el("select"); vsel.setAttribute("aria-label", "Call voice");
  const vr = row("Voice", "What people hear when Theta calls. Natural voices sound like a person, not a robot.");
  vr.r.append(vsel);
  const elWrap = el("div", "calls-el"); elWrap.hidden = true;
  const elId = el("input", "calls-phone"); elId.placeholder = "ElevenLabs voice ID"; elId.autocomplete = "off"; elId.setAttribute("aria-label", "ElevenLabs voice ID");
  const elRef = el("input", "calls-phone"); elRef.placeholder = "Telnyx secret name for your key"; elRef.autocomplete = "off"; elRef.setAttribute("aria-label", "Telnyx secret name");
  const elSave = el("button", "btn-dark", "Use this voice"); elSave.type = "button";
  elWrap.append(el("p", "calls-note", "Use any ElevenLabs voice, including one cloned from your own. Copy its voice ID from ElevenLabs > Voices. In Telnyx, add your ElevenLabs API key under Integration Secrets and put that secret's name here. ElevenLabs needs a paid plan for this."), elId, elRef, elSave);
  g.append(pr.r, nr.r, rr.r, recr.r, vr.r, elWrap, tr.r, note);

  let state = {};
  const status = () => {
    if (T.state.demo) { note.textContent = "Demo: sample values. On Theta these save to the server."; return; }
    if (!state.configured) note.textContent = "Calling isn't set up on the server yet (Telnyx keys). See deploy/RAILWAY.md.";
    else if (!state.public_url) note.textContent = "Set PROTOS_PUBLIC_URL on the server so the phone service can reach Theta.";
    else note.textContent = `Calls to others: ${state.today || 0} of ${state.cap ?? 5} today, ${(state.hours || [8, 21])[0]}:00–${(state.hours || [8, 21])[1]}:00 your time, each one only after you approve it.`;
  };
  const fill = () => {
    phone.value = state.phone || ""; name.value = state.name || ""; red.checked = !!state.call_on_red; rec.checked = state.record !== false;
    vsel.replaceChildren();
    for (const v of state.voices || []) { const o = el("option", null, v.label); o.value = v.id; vsel.append(o); }
    const own = el("option", null, "My own ElevenLabs voice…"); own.value = "elevenlabs"; vsel.append(own);
    const cur = state.voice || {};
    vsel.value = cur.kind === "elevenlabs" ? "elevenlabs" : (cur.id || ((state.voices || [])[0] || {}).id || "");
    elWrap.hidden = vsel.value !== "elevenlabs";
    if (cur.kind === "elevenlabs") { elId.value = cur.voice_id || ""; elRef.value = cur.key_ref || ""; }
    status();
  };

  let sample = null;
  function demoSample() {
    if (sample) return;
    sample = el("div", "calls-sample");
    const b = el("div", "msg a");
    b.append(card({kind: "other", name: "Luigi's", to: "+13035550142", duration: 94,
      outcome: "Booked: a table for 2 at 7pm Friday under Sam. They'll hold it 15 minutes.",
      transcript: [
        {who: "theta", text: "Hi, this is Theta, an AI assistant calling on behalf of Sam. I'm calling to book a table for 2 at 7pm this Friday."},
        {who: "them", text: "Sure, let me check. Yes, 7 works. Name?"},
        {who: "theta", text: "Sam, please."},
        {who: "them", text: "Got it. We hold tables for 15 minutes."},
        {who: "theta", text: "Perfect, thank you. Goodbye."}]}));
    sample.append(el("p", "calls-note", "What a call looks like in the chat:"), b);
    g.append(sample);
  }

  async function load() {
    if (T.state.demo) {
      state = {phone: "+13035551234", name: "Sam", call_on_red: true, configured: true, public_url: true, cap: 5, today: 1};
      fill(); demoSample(); return;
    }
    try { state = await T.api("/api/calls/settings"); fill(); } catch (e) { note.textContent = "Couldn't load call settings."; }
  }
  async function save(patch) {
    if (T.state.demo) { Object.assign(state, patch); fill(); T.toast("Saved (demo)."); return; }
    try { state = await T.post("/api/calls/settings", patch); fill(); }
    catch (e) { T.toast(e && e.status === 400 ? "That number doesn't look right. Use the +1… form." : "Couldn't save that. Try again."); fill(); }
  }
  phone.addEventListener("change", () => save({phone: phone.value.trim()}));
  name.addEventListener("change", () => save({name: name.value.trim()}));
  red.addEventListener("change", () => save({call_on_red: red.checked}));
  rec.addEventListener("change", () => save({record: rec.checked}));
  vsel.addEventListener("change", () => {
    elWrap.hidden = vsel.value !== "elevenlabs";
    if (vsel.value !== "elevenlabs") save({voice: {id: vsel.value}}).then(() => T.toast("Voice changed. Tap Test call to hear it.", 3200));
  });
  elSave.addEventListener("click", async () => {
    try { await T.post("/api/calls/settings", {voice: {kind: "elevenlabs", voice_id: elId.value.trim(), key_ref: elRef.value.trim()}}); T.toast("Using your ElevenLabs voice. Tap Test call to hear it.", 3600); }
    catch (e) { T.toast((e && e.message) || "That voice didn't save.", 4000); }
  });
  test.addEventListener("click", async () => {
    if (T.state.demo) { T.toast("In demo mode a test is just this toast. On Theta your phone rings."); return; }
    test.disabled = true;
    try {
      const r = await T.post("/api/calls/test", {});
      T.toast(r && r.ok ? "Calling you now." : ((r && r.error) || "The test call didn't start."), 4200);
    } catch (e) { T.toast("The test call didn't start. Check the number and the server's phone keys.", 4200); }
    finally { test.disabled = false; }
  });

  // ---------------------------------------------------------------- Call history: every call, with its transcript
  const hstyle = document.createElement("style");
  hstyle.textContent = `
.ch-row { width: 100%; text-align: left; display: flex; gap: 12px; align-items: flex-start; padding: 12px 2px; border-top: 1px solid #262626; color: var(--text); }
.ch-row:first-child { border-top: 0; }
.ch-ic { width: 38px; height: 38px; border-radius: 50%; background: #262626; display: grid; place-items: center; flex: none; font-size: 17px; }
.ch-txt { flex: 1; min-width: 0; }
.ch-txt b { display: block; font-weight: 500; font-size: 16.5px; }
.ch-txt small { display: block; color: var(--muted); font-size: 13.5px; }
.ch-out { display: block; color: #cfcfcf; font-size: 14px; margin-top: 3px; }
.ch-tr { padding: 4px 0 12px 50px; display: flex; flex-direction: column; gap: 6px; }
.ch-say { max-width: 88%; padding: 7px 11px; border-radius: 16px; font-size: 14.5px; line-height: 1.35; white-space: pre-wrap; overflow-wrap: anywhere; }
.ch-say.theta { background: #2c2c2e; align-self: flex-start; }
.ch-say.them { background: #0a84ff; color: #fff; align-self: flex-end; }
.ch-who { font-size: 11.5px; color: var(--muted); margin: 0 4px -3px; }
.ch-who.r { align-self: flex-end; }
.calls-el { display: flex; flex-direction: column; gap: 8px; padding: 4px 0 12px; }
.ch-audio { width: 100%; height: 40px; margin-bottom: 6px; }
.ch-rec { font-size: 12px; color: #ff8a80; margin-left: 6px; }
`;
  document.head.append(hstyle);
  const fmtNum = n => (/^\+1\d{10}$/.test(String(n || "")) ? `+1 ${n.slice(2, 5)}-${n.slice(5, 8)}-${n.slice(8)}` : String(n || ""));
  const when = t => { const d = new Date(t * 1000); return d.toLocaleDateString([], {month: "short", day: "numeric"}) + ", " + d.toLocaleTimeString([], {hour: "numeric", minute: "2-digit"}); };
  const hist = T.sheet("callhist", "Call history", openHistory);
  async function openHistory() {
    hist.body.replaceChildren(el("p", "empty", "Loading…"));
    let calls = [];
    if (!T.state.demo) { try { calls = (await T.api("/api/calls/history")).calls || []; } catch (e) { /* offline */ } }
    hist.pill.textContent = calls.length ? calls.length + (calls.length === 1 ? " call" : " calls") : "";
    hist.body.replaceChildren();
    if (!calls.length) { hist.body.append(el("p", "empty", T.state.demo ? "Demo mode: calls show here on Theta." : "No calls yet. Every call Theta makes shows here with its transcript.")); return; }
    for (const c of calls) {
      const other = c.kind === "other";
      const row = el("button", "ch-row"); row.type = "button";
      const tx = el("div", "ch-txt");
      tx.append(el("b", null, other ? c.who : (c.kind === "alert" ? "Alert call to you" : "Theta called you")),
        el("small", null, [when(c.t), c.duration ? dur(c.duration) : (c.state === "done" ? "" : c.state), other ? fmtNum(c.to) : ""].filter(Boolean).join(" · ")));
      if (c.audio) tx.querySelector("b").append(el("span", "ch-rec", "● Recorded"));
      if (c.outcome || c.purpose) tx.append(el("span", "ch-out", c.outcome || c.purpose));
      row.append(el("span", "ch-ic", other ? "☎" : "↘"), tx);
      const tr = el("div", "ch-tr"); tr.hidden = true;
      if (c.audio) { const a = el("audio", "ch-audio"); a.controls = true; a.preload = "none"; a.src = c.audio; a.setAttribute("aria-label", "Recording of this call"); tr.append(a); }
      if (c.turns.length) {
        for (const t of c.turns) {
          const them = t.who !== "theta";
          tr.append(el("div", "ch-who" + (them ? " r" : ""), them ? (other ? "Them" : "You") : "Theta"), el("div", "ch-say " + (them ? "them" : "theta"), t.text || ""));
        }
      } else tr.append(el("p", "fine", "No words were exchanged on this call."));
      row.setAttribute("aria-expanded", "false");
      row.addEventListener("click", () => { tr.hidden = !tr.hidden; row.setAttribute("aria-expanded", String(!tr.hidden)); });
      hist.body.append(row, tr);
    }
  }
  T.menu("Call history", "i-bell", "callhist");
  const hr = row("Call history", "Every call Theta makes, with who, how long, how it went and the full transcript.");
  const hb = el("button", "btn-dark", "Open"); hb.type = "button"; hb.addEventListener("click", () => T.open("callhist"));
  hr.r.append(hb); g.append(hr.r);

  // load when Settings opens (and once now, if it's already open)
  const sheet = document.getElementById("settings");
  if (sheet) {
    new MutationObserver(() => { if (!sheet.hidden) load(); }).observe(sheet, {attributes: true, attributeFilter: ["hidden"]});
    if (!sheet.hidden) load();
  }
})();
