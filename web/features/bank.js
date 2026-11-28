/* bank: Settings > Apps > Bank accounts (server/bank.py). Connect with a SimpleFIN setup token (read-only), see the
 * balances Theta sees, or disconnect. DOM nodes only, never innerHTML. Uses window.Theta (app.js). */
(() => {
  "use strict";
  const T = window.Theta;
  if (!T) return;
  const el = T.el;

  const style = document.createElement("style");
  style.textContent = `
.bk-in { display: flex; flex-direction: column; gap: 8px; padding: 12px 0; }
.bk-in input { background: var(--fill); border: 0; border-radius: var(--r-m); padding: 10px 12px; font-size: var(--fs-m); color: var(--text); min-width: 0; }
.bk-in .btn-dark { align-self: flex-start; }
.bk-acct { display: flex; justify-content: space-between; gap: 10px; padding: 10px 0; border-top: 1px solid var(--raised); font-size: var(--fs-m); }
.bk-acct small { display: block; color: var(--muted); font-size: var(--fs-s); }
.bk-acct b { font-weight: 600; white-space: nowrap; }
.bk-err { color: var(--bad-text); font-size: var(--fs-s); padding: 6px 0; }
`;
  document.head.append(style);

  const g = T.settings("Bank accounts", "connections");
  let st = null, busy = false;
  const money = (v, c) => (v < 0 ? "-" : "") + (c && c !== "USD" ? "" : "$") + Math.abs(v).toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2}) + (c && c !== "USD" ? " " + c : "");

  function render() {
    g.replaceChildren();
    if (!st) { g.append(el("p", "fine", T.state.demo ? "Demo mode: banks connect on the real server." : "Loading…")); return; }
    if (!st.connected) {
      const box = el("div", "bk-in");
      const a = el("a", null, "bridge.simplefin.org"); a.href = "https://bridge.simplefin.org/simplefin/create"; a.target = "_blank"; a.rel = "noopener noreferrer";
      const p = el("p", "fine"); p.append("Read-only: Theta can see balances and transactions, never move money. Link your banks at ", a, ", make a setup token there, and paste it here.");
      const inp = el("input"); inp.placeholder = "SimpleFIN setup token"; inp.autocomplete = "off"; inp.setAttribute("aria-label", "SimpleFIN setup token");
      const b = el("button", "btn-dark", busy ? "Connecting…" : "Connect"); b.type = "button"; b.disabled = busy;
      b.addEventListener("click", async () => {
        if (T.state.demo) { T.toast("Demo mode: banks connect on the real server."); return; }
        if (!inp.value.trim()) { inp.focus(); return; }
        busy = true; render();
        try { st = await T.post("/api/bank", {setup_token: inp.value.trim()}); T.toast("Bank connected."); }
        catch (e) { T.toast((e && e.message) || "That token didn't work.", 5000); }
        busy = false; render();
      });
      box.append(p, inp, b); g.append(box);
      return;
    }
    for (const x of st.accounts || []) {
      const r = el("div", "bk-acct"), l = el("div");
      l.append(document.createTextNode(x.name || "Account"), el("small", null, x.org || ""));
      r.append(l, el("b", null, money(x.balance, x.currency)));
      g.append(r);
    }
    if (!(st.accounts || []).length) g.append(el("p", "fine", "Connected. No accounts came back yet; SimpleFIN updates about once a day."));
    for (const e of st.errors || []) g.append(el("p", "bk-err", e));
    const row = el("div", "row-set"), tx = el("div", "txt");
    tx.append(el("b", null, "Disconnect"), el("span", null, "Theta forgets the access. To cut it off at the source too, revoke it at bridge.simplefin.org."));
    const d = el("button", "btn-dark", "Disconnect"); d.type = "button";
    d.addEventListener("click", async () => { try { st = await T.http("/api/bank", {method: "DELETE"}).then(r => r.json()); T.toast("Bank disconnected."); render(); } catch (e) { T.toast("Couldn't disconnect. Try again.", 3000); } });
    row.append(tx, d); g.append(row);
  }
  async function load() {
    if (T.state.demo) { render(); return; }
    try { st = await T.api("/api/bank"); } catch (e) {}
    render();
  }
  render();
  const sheet = document.getElementById("settings");
  if (sheet) new MutationObserver(() => { if (!sheet.hidden) load(); }).observe(sheet, {attributes: true, attributeFilter: ["hidden"]});
})();
