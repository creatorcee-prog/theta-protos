/* contacts: Settings > General > Contacts (server/contacts.py). The people Theta can text, call or email by name.
 * Lists them, adds or updates one (name, phone, email, who they are), and removes one. Uses window.Theta (app.js).
 * DOM nodes only, never innerHTML. */
(() => {
  "use strict";
  const T = window.Theta;
  if (!T) return;
  const el = T.el;

  const style = document.createElement("style");
  style.textContent = `
.ct-add { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; padding: 14px 0; border-top: 1px solid #262626; }
.ct-add:first-child { border-top: 0; }
.ct-add input { background: #2a2a2a; border: 0; border-radius: 12px; padding: 10px 12px; font-size: 16px; color: var(--text); min-width: 0; }
.ct-add input::placeholder { color: #808080; }
.ct-add .btn-dark { grid-column: 1 / -1; justify-self: start; }
.ct-row .txt span { overflow-wrap: anywhere; }
`;
  document.head.append(style);

  const g = T.settings("Contacts", "general");
  const fine = el("p", "fine set-fine", "Theta can text, call or email these people by name, and always shows you the message first.");

  let list = [], autoOn = true;
  const autoRow = el("div", "row-set"), autoTxt = el("div", "txt");
  autoTxt.append(el("b", null, "Send texts without asking"),
    el("span", null, "To saved contacts only, after a second model checks each one is safe, says only what you asked, and fits how you two text. Anything it isn't sure about waits for your tap."));
  const autoSw = el("label", "switch"), autoIn = el("input"); autoIn.type = "checkbox"; autoIn.setAttribute("switch", ""); autoIn.setAttribute("aria-label", "Send texts without asking");
  autoSw.append(autoIn, el("i")); autoRow.append(autoTxt, autoSw);
  autoIn.addEventListener("change", async () => {
    const want = autoIn.checked;
    try { await T.post("/api/settings", {texts_auto: want}); autoOn = want; T.toast(want ? "Reviewed texts go without asking." : "Every text waits for your tap."); }
    catch (e) { autoIn.checked = autoOn; T.toast("Couldn't change that. Try again.", 3000); }
  });
  const field = (ph, type, label) => { const i = el("input"); i.placeholder = ph; i.type = type || "text"; i.autocomplete = "off"; i.setAttribute("aria-label", label || ph); return i; };
  const fName = field("Name"), fRel = field("Who (mom, boss)", "text", "Who they are"), fPhone = field("Phone", "tel"), fEmail = field("Email", "email");
  const save = el("button", "btn-dark", "Add contact"); save.type = "button";

  function render() {
    g.replaceChildren();
    autoIn.checked = autoOn; g.append(autoRow);
    for (const c of list) {
      const row = el("div", "row-set ct-row"), txt = el("div", "txt");
      const bits = [c.note, c.phone, c.email].filter(Boolean).join(" · ");
      txt.append(el("b", null, c.name), el("span", null, bits));
      const rm = el("button", "btn-dark", "Remove"); rm.type = "button"; rm.setAttribute("aria-label", "Remove " + c.name);
      rm.addEventListener("click", async () => {
        try { await T.http("/api/contacts?id=" + encodeURIComponent(c.id), {method: "DELETE"}); list = list.filter(x => x.id !== c.id); render(); }
        catch (e) { T.toast("Couldn't remove that. Try again.", 3000); }
      });
      row.append(txt, rm);
      g.append(row);
    }
    const add = el("div", "ct-add");
    add.append(fName, fRel, fPhone, fEmail, save);
    g.append(add);
    if (!fine.isConnected) g.after(fine);
  }

  save.addEventListener("click", async () => {
    if (T.state.demo) { T.toast("Demo mode: contacts are saved on the real server."); return; }
    const body = {name: fName.value.trim(), note: fRel.value.trim(), phone: fPhone.value.trim(), email: fEmail.value.trim()};
    if (!body.name) { fName.focus(); T.toast("Add a name first."); return; }
    try {
      const c = await T.post("/api/contacts", body);
      list = list.filter(x => x.id !== c.id).concat([c]);
      for (const f of [fName, fRel, fPhone, fEmail]) f.value = "";
      render(); T.toast(`Saved ${c.name}.`);
    } catch (e) { T.toast((e && e.message) || "That didn't save.", 4000); }
  });

  async function load() {
    if (T.state.demo) { render(); return; }
    try { const r = await T.api("/api/contacts"); list = Array.isArray(r) ? r : []; } catch (e) { /* signed out or offline */ }
    try { const st = await T.api("/api/settings"); autoOn = !st || st.texts_auto !== false; } catch (e) {}
    render();
  }
  render();
  // load each time Settings opens
  const sheet = document.getElementById("settings");
  if (sheet) new MutationObserver(() => { if (!sheet.hidden) load(); }).observe(sheet, {attributes: true, attributeFilter: ["hidden"]});
})();
