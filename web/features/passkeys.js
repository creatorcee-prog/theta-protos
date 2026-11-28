/* passkeys: Face ID sign-in (server/passkeys.py). Uses window.Theta (app.js) and the DOM.
 * 1. The login screen gets "Sign in with Face ID" above the key field, shown only when this browser can use
 *    passkeys and the server has at least one. It signs in with navigator.credentials.get and reloads.
 * 2. Settings > Sign-in lists the passkeys (name, last used, Remove) and adds one for this device.
 * Your face never leaves the phone; Theta only checks a signature. DOM nodes only, never innerHTML.
 * In demo mode nothing is sent: Settings shows sample rows with a note. */
(() => {
  "use strict";
  const T = window.Theta;
  if (!T) return;
  const el = T.el;
  const $ = id => document.getElementById(id);
  const can = !!window.PublicKeyCredential && !!(navigator.credentials && navigator.credentials.get);

  const style = document.createElement("style");
  style.textContent = `
.passkeys-face { width: 100%; height: 52px; display: flex; align-items: center; justify-content: center; gap: 10px; margin: 0 0 14px; }
.passkeys-face svg { width: 22px; height: 22px; }
.passkeys-or { color: var(--muted); font-size: 0.8235rem; margin: 0 0 12px; display: flex; align-items: center; gap: 10px; }
.passkeys-or::before, .passkeys-or::after { content: ""; flex: 1; border-top: 1px solid #2a2a2a; }
.passkeys-name { background: #2a2a2a; border: 0; border-radius: 12px; padding: 8px 12px; font-size: 0.9412rem; color: var(--text);
  width: 100%; max-width: 180px; min-width: 0; outline: none; }
.passkeys-name:focus { box-shadow: 0 0 0 2px #3a3a3a; }
.passkeys-add { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; width: 100%; }
.passkeys-add .btn-white { font-size: 0.8824rem; padding: 9px 16px; }
.passkeys-note { color: var(--muted); font-size: 0.8235rem; margin: 0; padding: 0 0 12px; line-height: 1.35; }
.passkeys-note.err { color: var(--danger); }
`;
  document.head.append(style);

  // ---- base64url <-> bytes
  const b64 = s => Uint8Array.from(atob(String(s).replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - String(s).length % 4) % 4)), c => c.charCodeAt(0));
  const u = buf => btoa(String.fromCharCode(...new Uint8Array(buf))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");

  const why = e => {
    if (e && e.name === "NotAllowedError") return "Face ID was cancelled or timed out, or this device has no Theta passkey for " +
      location.hostname + " (a passkey only works on the address it was added on).";
    if (e && e.name === "InvalidStateError") return "This device is already added.";
    if (e && e.name === "SecurityError") return "This address can't use passkeys (" + location.hostname + ").";
    return (e && e.message) || String(e);
  };
  const postRaw = async (path, body) => {
    const r = await T.http(path, {method: "POST", headers: {"content-type": "application/json"}, body: JSON.stringify(body || {})});
    let j = {}; try { j = await r.json(); } catch (e) {}
    return {status: r.status, ok: r.ok && j.ok !== false, j};
  };

  // Safari only shows Face ID when the request starts right from a tap, so the challenge is fetched ahead of time
  // (and again before it expires). Each challenge works once.
  function prefetch(path) {
    let o = null, at = 0, busy = null;
    const load = () => busy || (busy = (async () => {
      try { const r = await postRaw(path, {}); if (r.ok && r.j.challenge) { o = r.j; at = Date.now(); } else o = null; }
      catch (e) { o = null; }
      finally { busy = null; }
    })());
    return {
      load,
      async take() {
        if (!o || Date.now() - at > 240000) await load();
        const x = o; o = null; load();
        if (!x) throw new Error("Couldn't reach Theta. Check your connection.");
        return x;
      },
    };
  }

  // ---------------------------------------------------------------- login screen
  const login = $("login"), form = $("login-form");
  if (login && form && can) {
    const face = el("button", "btn-white passkeys-face"); face.type = "button"; face.hidden = true;
    face.append(T.svg("i-person"), document.createTextNode("Sign in with Face ID"));
    const or = el("p", "passkeys-or", "or use your key"); or.hidden = true;
    form.parentNode.insertBefore(face, form);
    form.parentNode.insertBefore(or, form);
    const keyBtn = form.querySelector('button[type="submit"]');
    const err = msg => { const e = $("login-err"); if (e) e.textContent = msg; };
    const opts = prefetch("/api/passkeys/login/options");
    let checking = false;

    const show = on => {
      face.hidden = or.hidden = !on;
      if (keyBtn) { keyBtn.classList.toggle("btn-white", !on); keyBtn.classList.toggle("btn-dark", on); }
    };
    async function check() {
      if (T.state.demo || checking) return;
      checking = true;
      try {
        const r = await T.http("/api/passkeys/login/options", {cache: "no-store"});
        const j = r.ok ? await r.json() : {};
        show(!!j.available);
        if (j.available) opts.load();
      } catch (e) { show(false); }
      finally { checking = false; }
    }
    new MutationObserver(() => { if (!login.hidden) check(); }).observe(login, {attributes: true, attributeFilter: ["hidden"]});
    if (!login.hidden) check();
    document.addEventListener("visibilitychange", () => { if (!document.hidden && !login.hidden && !face.hidden) opts.load(); });

    face.addEventListener("click", async () => {
      err(""); face.disabled = true;
      try {
        const o = await opts.take();
        const cred = await navigator.credentials.get({publicKey: {
          challenge: b64(o.challenge), rpId: o.rpId, userVerification: "required", timeout: o.timeout || 60000}});
        const r = cred.response;
        const res = await postRaw("/api/passkeys/login", {id: cred.id, clientDataJSON: u(r.clientDataJSON),
          authenticatorData: u(r.authenticatorData), signature: u(r.signature)});
        if (res.status === 429) throw new Error("Too many tries. Wait a few minutes, then try again.");
        if (!res.ok) throw new Error(res.j.error || `Theta answered ${res.status}. Try again.`);
        location.reload();
      } catch (e) { err("Couldn't sign in: " + why(e)); }
      finally { face.disabled = false; }
    });
  }

  // ---------------------------------------------------------------- Settings > Sign-in
  const g = T.settings("Sign-in");
  const list = el("div", "passkeys-list");
  const note = el("p", "passkeys-note", "");
  const addRow = el("div", "row-set"), addTxt = el("div", "txt");
  addTxt.append(el("b", null, "Face ID"), el("span", null,
    "Add this device and Theta opens with Face ID (or Touch ID, or your passcode) instead of the key. Your face never " +
    "leaves your phone; Theta only checks a signature. Passkeys sync through iCloud Keychain to your other Apple devices."));
  const add = el("div", "passkeys-add");
  const name = el("input", "passkeys-name"); name.type = "text"; name.value = "iPhone"; name.maxLength = 60;
  name.placeholder = "Name, like iPhone"; name.setAttribute("aria-label", "Device name");
  const addBtn = el("button", "btn-white", "Add Face ID on this device"); addBtn.type = "button";
  add.append(name, addBtn);
  addRow.append(addTxt, add);
  g.append(list, addRow, note);
  if (!window.PublicKeyCredential) { addBtn.disabled = true; }

  const when = t => {
    if (!t) return "";
    const d = new Date(t * 1000);
    return d.toLocaleDateString(undefined, {month: "short", day: "numeric"}) + " " +
      d.toLocaleTimeString(undefined, {hour: "numeric", minute: "2-digit"});
  };
  const say = (text, bad) => { note.textContent = text; note.classList.toggle("err", !!bad); };
  let items = [];
  let regOpts = null;

  function render() {
    list.replaceChildren();
    if (!items.length) {
      const r = el("div", "row-set"), t = el("div", "txt");
      t.append(el("b", null, "No devices yet"), el("span", null, "Add one below to sign in with Face ID."));
      r.append(t); list.append(r); return;
    }
    for (const k of items) {
      const r = el("div", "row-set"), t = el("div", "txt");
      const added = k.created ? "Added " + new Date(k.created * 1000).toLocaleDateString(undefined, {month: "short", day: "numeric"}) : "";
      t.append(el("b", null, k.name || "Device"),
        el("span", null, [added, k.last_used ? "last used " + when(k.last_used) : "never used"].filter(Boolean).join(", ")));
      const rm = el("button", "btn-dark quiet", "Remove"); rm.type = "button";
      rm.setAttribute("aria-label", "Remove " + (k.name || "device"));
      rm.addEventListener("click", async () => {
        if (T.state.demo) { items = items.filter(x => x !== k); render(); T.toast("Removed (demo)."); return; }
        rm.disabled = true;
        try {
          const res = await T.http("/api/passkeys?id=" + encodeURIComponent(k.id), {method: "DELETE"});
          if (!res.ok) throw new Error(String(res.status));
          items = items.filter(x => x !== k); render(); T.toast("Removed " + (k.name || "the device") + ".");
        } catch (e) { rm.disabled = false; T.toast("Couldn't remove it. Try again."); }
      });
      r.append(t, rm); list.append(r);
    }
  }

  async function load() {
    if (T.state.demo) {
      const now = Date.now() / 1000;
      if (!items.length) items = [{id: "demo1", name: "iPhone", created: now - 86400 * 12, last_used: now - 3600 * 2},
                                  {id: "demo2", name: "iPad", created: now - 86400 * 40, last_used: null}];
      render(); say("Demo: sample devices. On Theta these are your real passkeys."); return;
    }
    try {
      const j = await T.api("/api/passkeys");
      items = j.passkeys || []; render();
      if (!window.PublicKeyCredential) say("This browser can't make passkeys.");
      else say("");
      if (window.PublicKeyCredential && !regOpts) { regOpts = prefetch("/api/passkeys/register/options"); }
      if (regOpts) regOpts.load();
    } catch (e) { say("Couldn't load your sign-in devices."); }
  }

  addBtn.addEventListener("click", async () => {
    const label = name.value.trim() || "iPhone";
    if (T.state.demo) {
      items.push({id: "demo" + Date.now(), name: label, created: Date.now() / 1000, last_used: null});
      render(); T.toast("Added (demo). On Theta your phone asks for Face ID."); return;
    }
    if (!window.PublicKeyCredential) { say("This browser can't make passkeys.", true); return; }
    if (!regOpts) regOpts = prefetch("/api/passkeys/register/options");
    addBtn.disabled = true; say("Follow your device's prompt...");
    try {
      const o = await regOpts.take();
      const cred = await navigator.credentials.create({publicKey: {
        challenge: b64(o.challenge), rp: {name: o.rpName || "Theta", id: o.rpId},
        user: {id: b64(o.userId), name: "theta-owner", displayName: "Theta"},
        pubKeyCredParams: [{type: "public-key", alg: -7}], timeout: o.timeout || 60000, attestation: "none",
        authenticatorSelection: {authenticatorAttachment: "platform", residentKey: "required", requireResidentKey: true, userVerification: "required"},
        excludeCredentials: (o.exclude || []).map(id => ({type: "public-key", id: b64(id)}))}});
      const res = await postRaw("/api/passkeys/register", {name: label,
        clientDataJSON: u(cred.response.clientDataJSON), attestationObject: u(cred.response.attestationObject)});
      if (!res.ok) throw new Error(res.j.error || `Theta answered ${res.status}.`);
      say("Added. You can sign in with Face ID on this device now.");
      await load();
    } catch (e) { say("Couldn't add it: " + why(e), true); }
    finally { addBtn.disabled = false; }
  });

  // load when Settings opens (and once now, if it's already open)
  const sheet = $("settings");
  if (sheet) {
    new MutationObserver(() => { if (!sheet.hidden) load(); }).observe(sheet, {attributes: true, attributeFilter: ["hidden"]});
    if (!sheet.hidden) load();
  }
})();
