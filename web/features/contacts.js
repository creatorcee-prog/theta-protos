/* contacts: Settings > General > Contacts (server/contacts.py). The people Theta can text, call or email by name.
 * - "Send texts without asking" (reviewed texts to saved contacts)
 * - Google Contacts: synced by the server on its own; shows the count, "Sync now", or "Allow" when the Google
 *   sign-in predates contacts access
 * - Import a .vcf file (how an iPhone or iCloud shares contacts), and "Pick from this phone" where the browser has
 *   the Contact Picker (Android Chrome; not iPhone Safari)
 * - Search everyone, remove the ones you added, add one by hand
 * DOM nodes only, never innerHTML. Uses window.Theta (app.js). */
(() => {
  "use strict";
  const T = window.Theta;
  if (!T) return;
  const el = T.el;

  const style = document.createElement("style");
  style.textContent = `
.ct-add { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; padding: 14px 0; border-top: 1px solid #262626; }
.ct-add input, .ct-q { background: #2a2a2a; border: 0; border-radius: 12px; padding: 10px 12px; font-size: 16px; color: var(--text); min-width: 0; }
.ct-add input::placeholder, .ct-q::placeholder { color: #808080; }
.ct-add .btn-dark { grid-column: 1 / -1; justify-self: start; }
.ct-row .txt span { overflow-wrap: anywhere; }
.ct-tag { font-size: 12px; color: var(--muted); border: 1px solid #3a3a3a; border-radius: 999px; padding: 2px 8px; }
.ct-qrow { padding: 12px 0 4px; border-top: 1px solid #262626; }
.ct-q { width: 100%; }
.ct-btns { display: flex; gap: 8px; flex-wrap: wrap; }
.ct-file { display: none; }
`;
  document.head.append(style);

  const g = T.settings("Contacts", "general");
  const fine = el("p", "fine set-fine", "Theta can text, call or email these people by name. Texts it isn't sure about wait for your tap.");
  let own = [], gstat = {connected: false, count: 0}, autoOn = true, matches = null;
  const ago = t => { if (!t) return "not yet"; const m = Math.round((Date.now() / 1000 - t) / 60); return m < 2 ? "just now" : m < 90 ? m + " min ago" : Math.round(m / 60) + " h ago"; };
  const btn = (label, fn) => { const b = el("button", "btn-dark", label); b.type = "button"; b.addEventListener("click", fn); return b; };
  const row = (title, sub, right) => { const r = el("div", "row-set"), t = el("div", "txt"); t.append(el("b", null, title), el("span", null, sub)); r.append(t); if (right) r.append(right); return r; };

  // the switch
  const autoSw = el("label", "switch"), autoIn = el("input"); autoIn.type = "checkbox"; autoIn.setAttribute("switch", ""); autoIn.setAttribute("aria-label", "Send texts without asking");
  autoSw.append(autoIn, el("i"));
  autoIn.addEventListener("change", async () => {
    const want = autoIn.checked;
    try { await T.post("/api/settings", {texts_auto: want}); autoOn = want; T.toast(want ? "Reviewed texts go without asking." : "Every text waits for your tap."); }
    catch (e) { autoIn.checked = autoOn; T.toast("Couldn't change that. Try again.", 3000); }
  });

  // import a .vcf
  const file = el("input", "ct-file"); file.type = "file"; file.accept = ".vcf,text/vcard,text/x-vcard";
  file.addEventListener("change", async () => {
    const f = file.files && file.files[0]; file.value = "";
    if (!f) return;
    try {
      const r = await T.post("/api/contacts/import", {vcf: await f.text()});
      T.toast(`Added ${r.added}, updated ${r.updated}` + (r.skipped ? `, skipped ${r.skipped} with no number or email.` : "."), 4200);
      load();
    } catch (e) { T.toast((e && e.message) || "That file didn't import.", 4000); }
  });
  const pickable = "contacts" in navigator && "ContactsManager" in window;
  async function pick() {
    try {
      const got = await navigator.contacts.select(["name", "tel", "email"], {multiple: true});
      let n = 0;
      for (const c of got || []) {
        const name = (c.name || [])[0], phone = (c.tel || [])[0], email = (c.email || [])[0];
        if (!name || !(phone || email)) continue;
        try { await T.post("/api/contacts", {name, phone, email}); n++; } catch (e) {}
      }
      T.toast(n ? `Added ${n}.` : "Nothing added: they need a name and a number or email.", 3200); load();
    } catch (e) { /* closed the picker */ }
  }

  // search, add
  const q = el("input", "ct-q"); q.type = "search"; q.placeholder = "Search your contacts"; q.setAttribute("aria-label", "Search contacts");
  let qt = 0;
  q.addEventListener("input", () => { clearTimeout(qt); qt = setTimeout(search, 200); });
  async function search() {
    const v = q.value.trim();
    if (!v) { matches = null; render(); return; }
    try { const r = await T.api("/api/contacts?q=" + encodeURIComponent(v)); matches = r.matches || []; } catch (e) { matches = []; }
    render(); q.focus();
  }
  const field = (ph, type, label) => { const i = el("input"); i.placeholder = ph; i.type = type || "text"; i.autocomplete = "off"; i.setAttribute("aria-label", label || ph); return i; };
  const fName = field("Name"), fRel = field("Who (mom, boss)", "text", "Who they are"), fPhone = field("Phone", "tel"), fEmail = field("Email", "email");
  const save = btn("Add contact", async () => {
    if (T.state.demo) { T.toast("Demo mode: contacts are saved on the real server."); return; }
    const body = {name: fName.value.trim(), note: fRel.value.trim(), phone: fPhone.value.trim(), email: fEmail.value.trim()};
    if (!body.name) { fName.focus(); T.toast("Add a name first."); return; }
    try { const c = await T.post("/api/contacts", body); for (const f of [fName, fRel, fPhone, fEmail]) f.value = ""; T.toast(`Saved ${c.name}.`); load(); }
    catch (e) { T.toast((e && e.message) || "That didn't save.", 4000); }
  });

  function personRow(c) {
    const r = el("div", "row-set ct-row"), t = el("div", "txt");
    t.append(el("b", null, c.name), el("span", null, [c.note, c.phone, c.email].filter(Boolean).join(" · ")));
    r.append(t);
    if (c.source === "google") r.append(el("span", "ct-tag", "Google"));
    else r.append(btn("Remove", async () => {
      try { await T.http("/api/contacts?id=" + encodeURIComponent(c.id), {method: "DELETE"}); T.toast(`Removed ${c.name}.`); load(); }
      catch (e) { T.toast("Couldn't remove that. Try again.", 3000); }
    }));
    return r;
  }

  function render() {
    const keep = document.activeElement === q;
    g.replaceChildren();
    autoIn.checked = autoOn;
    g.append(row("Send texts without asking", "To saved contacts, after a second model checks each text is safe, says only what you asked, and fits how you two text.", autoSw));
    // Google Contacts
    const gsub = gstat.connected ? `${gstat.count} synced, ${ago(gstat.synced)}. Updates on its own twice a day.` + (gstat.error ? ` Last try failed: ${gstat.error}` : "")
      : "Allow it once and everyone in your Google Contacts is known by name.";
    g.append(row("Google Contacts", gsub, gstat.connected
      ? btn("Sync now", async e => { e.target.disabled = true; try { gstat = await T.post("/api/contacts/sync", {}); T.toast(`${gstat.count} contacts synced.`); } catch (err) { T.toast((err && err.message) || "Sync failed.", 3600); } render(); })
      : btn("Allow", () => { if (T.state.demo) { T.toast("Demo mode: this opens Google's sign-in."); return; } location.href = "/api/google/start"; })));
    // import
    const b = el("div", "ct-btns");
    b.append(btn("Import a file", () => file.click()));
    if (pickable) b.append(btn("Pick from this phone", pick));
    g.append(row("From your iPhone", "In the Contacts app, share a contact (or export a list) as a .vcf, or export everyone from iCloud.com. Then pick the file here.", b), file);
    // search and the people
    const qr = el("div", "ct-qrow"); qr.append(q); g.append(qr);
    const list = matches || own;
    if (matches && !matches.length) g.append(el("p", "fine", "Nobody matches that."));
    for (const c of list.slice(0, 40)) g.append(personRow(c));
    if (!matches && own.length > 40) g.append(el("p", "fine", `${own.length - 40} more: search to find them.`));
    const add = el("div", "ct-add"); add.append(fName, fRel, fPhone, fEmail, save); g.append(add);
    if (!fine.isConnected) g.after(fine);
    if (keep) q.focus();
  }

  async function load() {
    if (T.state.demo) { render(); return; }
    try { const r = await T.api("/api/contacts"); own = (r && r.contacts) || []; gstat = (r && r.google) || gstat; } catch (e) { /* signed out or offline */ }
    try { const st = await T.api("/api/settings"); autoOn = !!st && st.texts_auto === true; } catch (e) {}
    render();
  }
  render();
  const sheet = document.getElementById("settings");
  if (sheet) new MutationObserver(() => { if (!sheet.hidden) load(); }).observe(sheet, {attributes: true, attributeFilter: ["hidden"]});
})();
