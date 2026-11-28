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
  background: linear-gradient(145deg, #1f6f8b, #1b3f6b); font-size: 1rem; }
.calls-card .calls-who { font-weight: 600; display: block; }
.calls-card .calls-sub { color: var(--muted); font-size: 0.8235rem; display: block; }
.calls-card .calls-out { font-size: 0.9412rem; line-height: 1.38; }
.calls-card details { font-size: 0.8824rem; }
.calls-card summary { color: var(--accent); cursor: pointer; list-style: none; padding: 2px 0; }
.calls-card summary::-webkit-details-marker { display: none; }
.calls-card .calls-line { margin: 6px 0 0; line-height: 1.35; }
.calls-card .calls-line b { color: var(--muted); font-weight: 500; margin-right: 6px; }
.calls-phone { background: #2a2a2a; border: 0; border-radius: 12px; padding: 8px 12px; font-size: 0.9412rem; color: var(--text);
  width: 100%; max-width: 230px; outline: none; }
.calls-phone:focus { box-shadow: 0 0 0 2px #3a3a3a; }
.calls-note { color: var(--muted); font-size: 0.8235rem; margin: 0; padding: 0 0 12px; line-height: 1.35; }
.calls-setup { background: #1d1d1d; border: 1px solid var(--line); border-radius: 14px; padding: 12px 14px; margin: 4px 0 12px; font-size: 0.8529rem; line-height: 1.4; }
.calls-setup h4 { margin: 0 0 6px; font-size: 0.8824rem; }
.calls-setup ol { margin: 6px 0 0; padding-left: 20px; }
.calls-setup li { margin: 0 0 8px; }
.calls-setup code { background: #2a2a2a; border-radius: 6px; padding: 1px 5px; font-size: 0.7647rem; word-break: break-all; }
.calls-setup .cs-copy { margin-left: 6px; font-size: 0.7353rem; color: var(--accent); background: none; border: 0; padding: 0; cursor: pointer; }
.calls-setup .cs-vars { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 6px; }
.calls-setup .cs-var { font-size: 0.7353rem; border-radius: 999px; padding: 2px 9px; background: #2a2a2a; color: var(--muted); }
.calls-setup .cs-var.ok { background: #16351f; color: #8fe0a5; }
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

  // the 10-minute wait between calls to the same number (on by default; off while testing)
  const gsw = el("label", "switch"), gap = el("input");
  gap.type = "checkbox"; gap.setAttribute("switch", ""); gap.setAttribute("aria-label", "Wait between calls to the same number");
  gsw.append(gap, el("i"));
  const gr = row("Wait 10 minutes between calls", "Theta won't call the same number twice within 10 minutes. Turn it off while you're testing calls.");
  gr.r.append(gsw);
  gap.addEventListener("change", () => save({gap_off: !gap.checked}));
  const rsw = el("label", "switch"), rec = el("input");
  rec.type = "checkbox"; rec.setAttribute("switch", ""); rec.setAttribute("aria-label", "Record calls");
  rsw.append(rec, el("i"));
  const recr = row("Record calls", "Calls to others start with “This call is recorded.” If they say they'd rather not, Theta stops and keeps none of it. Recordings stay 90 days, in Call history.");
  recr.r.append(rsw);
  // the voice people hear: a natural preset, or your own ElevenLabs voice (cloned or from their library)
  const vsel = el("select"); vsel.setAttribute("aria-label", "Call voice");
  const vr = row("Voice", "What people hear when Theta calls. Natural voices sound like a person, not a robot.");
  vr.r.append(vsel);
  // live (full-duplex) calls talk in one of Gemini's preset voices, the whole call through; Play makes a short sample
  // in that voice with the same model (server/livevoice.py)
  const lsel = el("select"); lsel.setAttribute("aria-label", "Live call voice");
  const lplay = el("button", "btn-dark", "Play"); lplay.type = "button"; lplay.setAttribute("aria-label", "Play a sample of this voice");
  const lr = row("Live call voice", "The voice on live calls, where people can talk over Theta and it stops to listen. Tap Play to hear it.");
  const lbox = el("div"); lbox.style.cssText = "display:flex;gap:8px;align-items:center"; lbox.append(lsel, lplay); lr.r.append(lbox);
  let lAudio = null;
  lplay.addEventListener("click", async () => {
    if (T.state.demo) { T.toast("Demo mode: samples play on the real server."); return; }
    if (lAudio && !lAudio.paused) { lAudio.pause(); lplay.textContent = "Play"; return; }
    lplay.disabled = true; lplay.textContent = "Loading…";
    try {
      const r = await T.http("/api/calls/voice_sample?voice=" + encodeURIComponent(lsel.value));
      if (!r.ok) { let m = ""; try { m = (await r.json()).error; } catch (e) {} throw new Error(m || "HTTP " + r.status); }
      lAudio = new Audio(URL.createObjectURL(await r.blob()));
      lAudio.addEventListener("ended", () => { lplay.textContent = "Play"; });
      await lAudio.play(); lplay.textContent = "Stop";
    } catch (e) { lplay.textContent = "Play"; T.toast("Couldn't play a sample: " + ((e && e.message) || "try again"), 3600); }
    finally { lplay.disabled = false; }
  });
  lsel.addEventListener("change", () => { if (lAudio) lAudio.pause(); lplay.textContent = "Play"; save({live_voice: lsel.value}).then(() => T.toast("Live call voice changed.", 2400)); });
  // the last few live calls, for the developer: where the audio went (dev-only, from server/livecall.py save_diag)
  const diagBox = el("div", "fine dev-only"); diagBox.style.cssText = "padding:0 16px 10px;white-space:pre-wrap;font-size: 0.7353rem";
  const elWrap = el("div", "calls-el"); elWrap.hidden = true;
  const elId = el("input", "calls-phone"); elId.placeholder = "Voice ID"; elId.autocomplete = "off"; elId.setAttribute("aria-label", "Voice ID");
  const elRef = el("input", "calls-phone"); elRef.placeholder = "Telnyx secret name"; elRef.autocomplete = "off"; elRef.setAttribute("aria-label", "Telnyx secret name");
  const elSave = el("button", "btn-dark", "Use this voice"); elSave.type = "button";
  // your own voice: ElevenLabs or Fish Audio, both through Telnyx
  const OWN = {
    elevenlabs: {label: "My own ElevenLabs voice…", note: "Use any ElevenLabs voice, including one cloned from your own. Copy its voice ID from ElevenLabs > Voices. In Telnyx, add your ElevenLabs API key under Integration Secrets and put that secret's name here. ElevenLabs needs a paid plan for this.", models: null},
    fishaudio: {label: "My own Fish Audio voice…", note: "Use any Fish Audio voice, including one cloned from your own. Copy the voice's ID from its page on fish.audio. If Telnyx asks for your Fish Audio API key, add it under Integration Secrets and put that secret's name here.", models: ["s2.1-pro", "s2-pro", "s1"]},
  };
  const elNote = el("p", "calls-note", "");
  const elModel = el("select"); elModel.setAttribute("aria-label", "Voice model"); elModel.hidden = true;
  elWrap.append(elNote, elId, elModel, elRef, elSave);
  const showOwn = kind => {
    const o = OWN[kind]; elWrap.hidden = !o; if (!o) return;
    elNote.textContent = o.note;
    elModel.replaceChildren(); elModel.hidden = !o.models;
    for (const m of o.models || []) { const op = el("option", null, m); op.value = m; elModel.append(op); }
  };
  // the Telnyx setup steps, right here (with this app's own addresses), until calling works
  const setupBox = el("div", "calls-setup"); setupBox.hidden = true;
  const link = (href, text) => { const a = el("a", null, text); a.href = href; a.target = "_blank"; a.rel = "noopener noreferrer"; return a; };
  const codeCopy = text => {
    const w = el("span"), c = el("code", null, text), b = el("button", "cs-copy", "Copy"); b.type = "button";
    b.addEventListener("click", async () => { try { await navigator.clipboard.writeText(text); T.toast("Copied."); } catch (e) { T.toast(text, 6000); } });
    w.append(c, b); return w;
  };
  function renderSetup(st) {
    const miss = (st && st.missing) || [], have = new Set((st && st.set) || []);
    setupBox.hidden = !!state.configured && !miss.length;
    if (setupBox.hidden) return;
    if (!T.state.dev) {  // server setup is for whoever runs Theta; everyone else gets one plain line
      setupBox.replaceChildren(el("p", "fine", "Phone calls aren't set up on this Theta yet. Whoever runs your Theta can turn them on."));
      return;
    }
    const base = location.origin;
    const li = (...parts) => { const n = el("li"); n.append(...parts); return n; };
    const b = t => el("b", null, t);
    const ol = el("ol");
    ol.append(
      li("Make an account at ", link("https://telnyx.com/sign-up", "telnyx.com"), " and add a payment method."),
      li(b("Numbers > Buy Numbers"), ": pick one with voice and SMS."),
      li(b("Voice > Programmable Voice > TeXML Applications > Add"), ". Voice URL (POST): ", codeCopy(base + "/api/calls/inbound"),
        ". Save, assign your number to it, and copy the application's ", b("ID"), "."),
      li(b("Messaging > Messaging Profiles > Add"), ". Webhook URL (API v2): ", codeCopy(base + "/api/texts/inbound"),
        ". Assign your number. For US texts, register under ", b("Messaging > 10DLC"), " (sole proprietor); carriers block unregistered texts."),
      li(b("Account > API Keys > Create"), " (copy it) and ", b("Account > Public Key"), " (copy it)."),
      li("On Railway > your service > ", b("Variables"), ", add these, then redeploy:"));
    const vars = el("div", "cs-vars");
    const vals = {TELNYX_API_KEY: "the API key", TELNYX_FROM: "your number, +1…", TELNYX_TEXML_APP_ID: "step 3's ID", TELNYX_PUBLIC_KEY: "the public key", PROTOS_PUBLIC_URL: base};
    for (const k of ["TELNYX_API_KEY", "TELNYX_FROM", "TELNYX_TEXML_APP_ID", "TELNYX_PUBLIC_KEY", "PROTOS_PUBLIC_URL"]) {
      const v = el("span", "cs-var" + (have.has(k) ? " ok" : ""), (have.has(k) ? "✓ " : "") + k); v.title = have.has(k) ? "Set" : "Not set: " + vals[k]; vars.append(v);
    }
    const last = ol.lastChild; last.append(vars, el("div", "calls-note", "Green ones are already set. PROTOS_PUBLIC_URL is " + base + "."));
    ol.append(li("Back here: enter your number and name, pick a voice, and tap ", b("Test call"), "."));
    setupBox.replaceChildren(el("h4", null, "Set up calls and texts (about 15 minutes)"), ol);
  }
  g.append(setupBox, pr.r, nr.r, rr.r, recr.r, gr.r, lr.r, diagBox, vr.r, elWrap, tr.r, note);

  let state = {};
  const status = () => {
    if (T.state.demo) { note.textContent = "Demo: sample values. On Theta these save to the server."; return; }
    renderSetup(state.setup);
    if (!state.configured) note.textContent = "Calling isn't set up yet: follow the steps above.";
    else if (!state.public_url) note.textContent = T.state.dev ? "Set PROTOS_PUBLIC_URL on the server so the phone service can reach Theta."
      : "Phone calls aren't fully set up on this Theta yet. Whoever runs your Theta can finish it.";
    else note.textContent = `Calls to others: ${state.today || 0} of ${state.cap ?? 5} today, ${(state.hours || [8, 21])[0]}:00–${(state.hours || [8, 21])[1]}:00 your time, each one only after you approve it.`;
  };
  const fill = () => {
    gap.checked = !state.gap_off;
    phone.value = state.phone || ""; name.value = state.name || ""; red.checked = !!state.call_on_red; rec.checked = state.record !== false;
    vsel.replaceChildren();
    for (const v of state.voices || []) { const o = el("option", null, v.label); o.value = v.id; vsel.append(o); }
    for (const [k, o] of Object.entries(OWN)) { const op = el("option", null, o.label); op.value = k; vsel.append(op); }
    lsel.replaceChildren();
    for (const v of state.live_voices || []) { const o = el("option", null, v.label); o.value = v.id; lsel.append(o); }
    lsel.value = state.live_voice || "Puck";
    lr.r.hidden = !(state.live_voices || []).length;
    const dg = state.live_diag || [];
    diagBox.textContent = dg.length ? "Last live calls:\n" + dg.map(d => `${new Date(d.t * 1000).toLocaleTimeString([], {hour: "numeric", minute: "2-digit"})} ${d.kind}, ${d.seconds}s: `
      + `heard ${d.frames_in} frames (${d.held} held before the opening), sent ${d.to_gemini} to Gemini, ${d.audio_out} audio back, `
      + `transcripts ${d.heard} in / ${d.said} out, byte order ${d.order}, ended: ${d.end}` + (d.error ? `\n   error: ${d.error}` : "")
      + (d.opening ? `\n   opening heard as: "${d.opening}"` : "")).join("\n") : "";
    // with live calls on, the other voice only speaks on a call that couldn't go live
    vr.s.textContent = state.live ? "Used only when a call can't go live (the turn-by-turn kind)."
      : "What people hear when Theta calls. Natural voices sound like a person, not a robot.";
    const cur = state.voice || {};
    vsel.value = OWN[cur.kind] ? cur.kind : (cur.id || ((state.voices || [])[0] || {}).id || "");
    showOwn(vsel.value);
    if (OWN[cur.kind]) { elId.value = cur.voice_id || ""; elRef.value = cur.key_ref || ""; if (cur.model && OWN[cur.kind].models) elModel.value = cur.model; }
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
      state = {phone: "+13035551234", name: "Sam", call_on_red: true, configured: true, public_url: true, cap: 5, today: 1, live: true,
        live_voice: "Puck", live_voices: ["Zephyr bright", "Puck upbeat", "Charon informative", "Kore firm", "Aoede breezy", "Sulafat warm"]
          .map(x => { const [n, d] = x.split(" "); return {id: n, label: `${n} (${d})`}; }),
        voices: [{id: "natural-f", label: "Natural, warm (female)"}, {id: "natural-m", label: "Natural, calm (male)"}], voice: {id: "natural-f"}};
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
    showOwn(vsel.value);
    if (!OWN[vsel.value]) save({voice: {id: vsel.value}}).then(() => T.toast("Voice changed. Tap Test call to hear it.", 3200));
  });
  elSave.addEventListener("click", async () => {
    const kind = vsel.value, o = OWN[kind];
    const voice = {kind, voice_id: elId.value.trim(), key_ref: elRef.value.trim()};
    if (o && o.models) voice.model = elModel.value;
    try { await T.post("/api/calls/settings", {voice}); T.toast(`Using your ${kind === "fishaudio" ? "Fish Audio" : "ElevenLabs"} voice. Tap Test call to hear it.`, 3600); }
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
.ch-ic { width: 38px; height: 38px; border-radius: 50%; background: #262626; display: grid; place-items: center; flex: none; font-size: 1rem; }
.ch-txt { flex: 1; min-width: 0; }
.ch-txt b { display: block; font-weight: 500; font-size: 0.9706rem; }
.ch-txt small { display: block; color: var(--muted); font-size: 0.7941rem; }
.ch-out { display: block; color: #cfcfcf; font-size: 0.8235rem; margin-top: 3px; }
.ch-tr { padding: 4px 0 12px 50px; display: flex; flex-direction: column; gap: 6px; }
.ch-say { max-width: 88%; padding: 7px 11px; border-radius: 16px; font-size: 0.8529rem; line-height: 1.35; white-space: pre-wrap; overflow-wrap: anywhere; }
.ch-say.theta { background: #2c2c2e; align-self: flex-start; }
.ch-say.them { background: #0a84ff; color: #fff; align-self: flex-end; }
.ch-who { font-size: 0.6765rem; color: var(--muted); margin: 0 4px -3px; }
.ch-who.r { align-self: flex-end; }
.calls-el { display: flex; flex-direction: column; gap: 8px; padding: 4px 0 12px; }
.calls-el select { background: #2a2a2a; border: 0; border-radius: 12px; padding: 10px 12px; font-size: 0.9412rem; color: var(--text); align-self: flex-start; }
.ch-audio { width: 100%; height: 40px; margin-bottom: 6px; }
.ch-rec { font-size: 0.7059rem; color: #ff8a80; margin-left: 6px; }
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
  window.addEventListener("theta:dev", () => { if (state && Object.keys(state).length) fill(); });
})();
