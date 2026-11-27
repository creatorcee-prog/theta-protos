/* chiphub: Settings > Chips > Suggested (server/chiphub.py). Skills made for other AI agents, rewritten by Theta into
   chips that use its own tools. Each shows its full steps and where it came from; nothing is added until you tap
   Add. "Look for more" scans again; Sources lists the skill collections Theta reads. DOM nodes only. */
(() => {
  "use strict";
  const T = window.Theta;
  if (!T) return;
  const {el} = T;

  const css = document.createElement("style");
  css.textContent = `
.chh h4 { margin: 22px 4px 8px; font-size: 13px; font-weight: 600; color: var(--muted); text-transform: uppercase; letter-spacing: .03em; }
.chh-item { border-top: 1px solid #2a2a2a; padding: 12px 16px 12px 0; }
.chh-item:first-child { border-top: 0; }
.chh-head { display: flex; gap: 12px; align-items: center; }
.chh-ic { width: 38px; height: 38px; border-radius: 12px; background: #262628; display: grid; place-items: center; font-size: 20px; flex: none; }
.chh-tx { flex: 1; min-width: 0; text-align: left; color: var(--text); }
.chh-tx b { display: block; font-size: 16.5px; font-weight: 500; }
.chh-tx span { display: block; color: var(--muted); font-size: 13.5px; line-height: 1.35; }
.chh-steps { white-space: pre-wrap; color: #cfcfcf; font-size: 14px; line-height: 1.45; margin: 10px 0 4px 50px; }
.chh-from { margin: 4px 0 0 50px; font-size: 12.5px; color: var(--muted); }
.chh-from a { color: var(--muted); }
.chh-btns { display: flex; gap: 8px; margin: 10px 0 0 50px; flex-wrap: wrap; }
.chh-src { width: 100%; box-sizing: border-box; background: #262628; border: 0; border-radius: 12px; padding: 10px 12px; color: var(--text); font: inherit; font-size: 15px; min-height: 70px; }
`;
  document.head.append(css);

  const DEMO = {items: [{id: "d1", from: "doc-coauthoring", source: "anthropics/skills", url: "https://github.com/anthropics/skills",
    chip: {icon: "📝", name: "Doc co-authoring", when: "They want to write a proposal, report or other document together.", prompt: "Help me write a document",
      steps: "1. Ask what it's for, who reads it and the length.\n2. Draft an outline and check it with them.\n3. Write it section by section.\n4. Save it with docs_create."}}],
    sources: ["anthropics/skills"], last_scan: null, skipped: 15};
  let data = null, open = null, editing = false, reload = null;

  async function load() {
    if (T.state.demo) { data = data || JSON.parse(JSON.stringify(DEMO)); return; }
    try { data = await T.api("/api/chips/suggested"); } catch (e) { data = null; }
  }
  async function act(body) {
    if (T.state.demo) { if (body.id) data.items = data.items.filter(i => i.id !== body.id); return; }
    const r = await T.http("/api/chips/suggested", {method: "POST", headers: {"content-type": "application/json"}, body: JSON.stringify(body)});
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(j.error || "That didn't work.");
    data = j;
  }
  function paint(page) {
    page.querySelector(".chh")?.remove();
    if (!data) return;
    const box = el("div", "chh");
    box.append(el("h4", null, "Suggested"));
    const g = el("div", "group acc-form");
    if (!data.items.length) g.append(el("p", "acc-note", data.scanning ? "Looking now…" : data.last_scan ? "Nothing new that fits right now." : "Theta hasn't looked yet."));
    for (const it of data.items) {
      const c = it.chip, item = el("div", "chh-item"), head = el("div", "chh-head");
      const tx = el("button", "chh-tx"); tx.type = "button"; tx.setAttribute("aria-expanded", String(open === it.id));
      tx.append(el("b", null, c.name), el("span", null, c.when));
      tx.addEventListener("click", () => { open = open === it.id ? null : it.id; paint(page); });
      head.append(el("span", "chh-ic", c.icon || "✨"), tx); item.append(head);
      if (open === it.id) {
        const from = el("p", "chh-from", "Adapted from "), a = el("a", null, `${it.from} (${it.source})`);
        a.href = it.url; a.target = "_blank"; a.rel = "noopener noreferrer"; from.append(a);
        const btns = el("div", "chh-btns"), add = el("button", "btn-dark", "Add"), no = el("button", "btn-dark", "Not for me");
        add.type = no.type = "button";
        add.addEventListener("click", async () => { try { await act({action: "add", id: it.id}); open = null; T.toast("Added to your chips."); if (reload) await reload(); else paint(page); } catch (e) { T.toast(e.message, 3500); } });
        no.addEventListener("click", async () => { try { await act({action: "dismiss", id: it.id}); open = null; paint(page); } catch (e) { T.toast(e.message, 3500); } });
        btns.append(add, no);
        item.append(el("div", "chh-steps", c.steps), from, btns);
      }
      g.append(item);
    }
    box.append(g);
    const note = el("p", "acc-note", "Skills written for other AI agents, rewritten by Theta to use its own tools. Read the steps before you add one: they came from someone else."
      + (data.skipped ? ` ${data.skipped} didn't fit a personal assistant (they need code or developer tools) and are hidden.` : ""));
    const more = el("button", "btn-dark", data.scanning ? "Looking…" : "Look for more"); more.type = "button"; more.disabled = !!data.scanning;
    more.addEventListener("click", async () => {
      try { await act({action: "scan"}); T.toast("Looking. New ones show here in a minute."); paint(page);
        for (const ms of [8000, 20000, 40000]) { await new Promise(r => setTimeout(r, ms)); await load(); paint(page); if (data && !data.scanning) break; } }
      catch (e) { T.toast(e.message, 3500); }
    });
    const srcBtn = el("button", "btn-dark", editing ? "Done" : "Sources"); srcBtn.type = "button";
    const btns = el("div", "chp-btns"); btns.style.marginTop = "10px"; btns.append(more, srcBtn);
    box.append(note, btns);
    if (editing) {
      const ta = el("textarea", "chh-src"); ta.value = data.sources.join("\n"); ta.setAttribute("aria-label", "Skill collections, one GitHub repo per line (owner/name)");
      box.append(el("p", "acc-note", "Skill collections Theta reads: GitHub repos with a Claude plugin marketplace, one per line (owner/name)."), ta);
      srcBtn.addEventListener("click", async () => {
        try { if (!T.state.demo) await act({action: "sources", sources: ta.value.split(/\s+/).filter(Boolean)}); editing = false; paint(page); T.toast("Saved."); } catch (e) { T.toast(e.message, 3500); }
      });
    } else srcBtn.addEventListener("click", () => { editing = true; paint(page); });
    page.append(box);
  }
  T.on("chips-painted", async d => { reload = d.reload; if (!data) await load(); paint(d.page); });
})();
