/* home: the opening screen's sections under Theta's globe (server/home.py): a greeting, the smart stack (the few
   things that matter now, swipe through them), Found for you (deals, stories and ideas Theta saved while working),
   your chips, and top stories (your interests first). Refreshes each time Home shows. DOM nodes only. */
(() => {
  "use strict";
  const T = window.Theta;
  if (!T) return;
  const {el} = T;
  const $ = id => document.getElementById(id);

  const css = document.createElement("style");
  css.textContent = `
#home .home-mid { bottom: 0; overflow-y: auto; overflow-x: hidden; align-content: start; -webkit-overflow-scrolling: touch;
  padding-bottom: calc(var(--sab) + 150px); scrollbar-width: none; }
#home .home-mid::-webkit-scrollbar { display: none; }
#home.has-feed .home-bottom { padding-top: 30px; background: linear-gradient(to bottom, transparent, var(--bg) 30px); }
#home.has-feed .home-orb-wrap { width: 170px; height: 170px; margin: -22px 0 -26px; }
.hf { width: 100%; max-width: 560px; padding: 0 16px; box-sizing: border-box; display: grid; gap: 4px; margin-top: 10px; }
.hf-hello { text-align: left; padding: 2px 4px 6px; }
.hf-hello small { display: block; color: var(--muted); font-size: 13px; letter-spacing: .02em; text-transform: uppercase; }
.hf-hello b { font-size: 24px; font-weight: 600; }
.hf-sec { display: flex; justify-content: space-between; align-items: baseline; margin: 16px 4px 8px; }
.hf-sec h3 { margin: 0; font-size: 18px; font-weight: 600; }
.hf-sec span { color: var(--muted); font-size: 13px; }
.hf-stack { display: flex; overflow-x: auto; scroll-snap-type: x mandatory; gap: 10px; scrollbar-width: none; margin: 0 -16px; padding: 0 16px; }
.hf-stack::-webkit-scrollbar { display: none; }
.hf-card { flex: 0 0 86%; scroll-snap-align: center; text-align: left; background: #1b1b1d; border: 1px solid #2a2a2c; border-radius: 22px;
  padding: 14px 16px; color: var(--text); min-height: 86px; }
.hf-card.warn { border-color: #6b5520; } .hf-card.bad { border-color: #6b2525; background: #2a1515; }
.hf-card small { display: block; color: var(--accent); font-size: 12.5px; font-weight: 600; letter-spacing: .02em; text-transform: uppercase; }
.hf-card.bad small { color: #ff8a80; }
.hf-card b { display: block; font-size: 17px; font-weight: 600; margin: 4px 0 2px; line-height: 1.3; }
.hf-card span { color: var(--muted); font-size: 14px; }
.hf-row { display: flex; overflow-x: auto; gap: 10px; scrollbar-width: none; margin: 0 -16px; padding: 0 16px 2px; }
.hf-row::-webkit-scrollbar { display: none; }
.hf-tile { flex: 0 0 210px; text-align: left; background: #1b1b1d; border-radius: 18px; overflow: hidden; color: var(--text); text-decoration: none;
  display: flex; flex-direction: column; position: relative; }
.hf-tile .img { height: 112px; background: #26262a center/cover no-repeat; }
.hf-tile .img.none { display: grid; place-items: center; font-size: 34px; }
.hf-tile .tx { padding: 10px 12px 12px; }
.hf-tile small { display: block; color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: .02em; }
.hf-tile b { display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; font-size: 15px; font-weight: 500; line-height: 1.3; margin-top: 3px; }
.hf-tile .price { display: inline-block; margin-top: 6px; font-weight: 600; color: var(--accent); }
.hf-tile .x { position: absolute; top: 6px; right: 6px; width: 26px; height: 26px; border-radius: 50%; background: rgba(0,0,0,.55); color: #ddd; font-size: 15px; line-height: 26px; text-align: center; }
.hf-tile .tag { display: inline-block; margin-left: 6px; color: var(--accent); }
.hf-chips { display: flex; flex-wrap: wrap; gap: 8px; }
.hf-chips button { padding: 9px 14px; border-radius: 999px; background: #232325; border: 1px solid #333; color: var(--text); font-size: 14.5px; }
.hf-empty { color: var(--muted); font-size: 14px; padding: 4px; }
`;
  document.head.append(css);

  const mid = document.querySelector("#home .home-mid"); if (!mid) return;
  const feed = el("div", "hf"); feed.setAttribute("aria-label", "Home"); mid.append(feed);
  const ICON = {deal: "🏷️", news: "📰", watch: "🎬", place: "📍", idea: "💡", update: "✅"};
  const host = u => { try { return new URL(u).hostname.replace(/^www\./, ""); } catch (e) { return ""; } };

  function act(a) {
    if (!a) return;
    if (a.startsWith("settings:")) T.open("settings", a.slice(9));
    else if (a.startsWith("chat:")) { $("home-bot").click(); }
    else if (/^https:\/\//.test(a)) window.open(a, "_blank", "noopener");
  }
  function sec(title, sub) { const h = el("div", "hf-sec"); h.append(el("h3", null, title)); if (sub) h.append(el("span", null, sub)); return h; }
  function tile(it, kind, onX) {
    const a = el(it.url ? "a" : "div", "hf-tile");
    if (it.url) { a.href = it.url; a.target = "_blank"; a.rel = "noopener noreferrer"; }
    const img = el("div", "img" + (it.image ? "" : " none"));
    if (it.image) img.style.backgroundImage = `url("${it.image.replace(/"/g, "%22")}")`; else img.textContent = ICON[kind] || "✨";
    const tx = el("div", "tx"), sm = el("small", null, (it.source || host(it.url) || kind) + (kind && kind !== "news" ? " · " + kind : ""));
    if (it.match) sm.append(el("span", "tag", "· for you"));
    tx.append(sm, el("b", null, it.title)); if (it.price) tx.append(el("span", "price", it.price));
    a.append(img, tx);
    if (onX) { const x = el("button", "x", "×"); x.type = "button"; x.setAttribute("aria-label", "Remove from Home"); x.addEventListener("click", e => { e.preventDefault(); e.stopPropagation(); onX(); }); a.append(x); }
    return a;
  }
  async function render() {
    let d;
    if (T.state.demo) d = demo();
    else { try { d = await T.api("/api/home"); } catch (e) { return; } }
    const kids = [];
    const hello = el("div", "hf-hello"); hello.append(el("small", null, d.date), el("b", null, d.hello)); kids.push(hello);
    if ((d.stack || []).length) {
      const st = el("div", "hf-stack"); st.setAttribute("aria-label", "What matters now");
      for (const c of d.stack) {
        const b = el("button", "hf-card " + (c.tone || "")); b.type = "button";
        b.append(el("small", null, c.eyebrow), el("b", null, c.title)); if (c.sub) b.append(el("span", null, c.sub));
        b.addEventListener("click", () => act(c.action)); st.append(b);
      }
      kids.push(st);
    }
    kids.push(sec("Found for you", (d.found || []).length ? "" : "Deals, stories and ideas Theta finds land here"));
    if ((d.found || []).length) {
      const r = el("div", "hf-row");
      for (const f of d.found) r.append(tile(f, f.kind, async () => { if (!T.state.demo) { try { await T.http("/api/home?id=" + encodeURIComponent(f.id), {method: "DELETE"}); } catch (e) {} } render(); }));
      kids.push(r);
    } else kids.push(el("p", "hf-empty", "Try a chip like Best price or News digest, and Theta saves what it finds here."));
    try {
      const cj = T.state.demo ? {chips: [{name: "Morning brief", icon: "☀️", prompt: "Give me my morning brief.", on: true}, {name: "Best price", icon: "🏷️", prompt: "Find me the best price on ", on: true}]} : await T.api("/api/chips");
      const on = (cj.chips || []).filter(c => c.on).slice(0, 8);
      if (on.length) {
        kids.push(sec("Your chips"));
        const box = el("div", "hf-chips");
        for (const c of on) {
          const b = el("button", null, `${c.icon || "✨"} ${c.name}`); b.type = "button";
          b.addEventListener("click", () => {
            $("home-bot").click();
            const p = String(c.prompt || c.name);
            setTimeout(() => { if (/\s$/.test(p)) { const ta = $("c-text"); ta.value = p; ta.focus(); } else T.send(`${p} (Use my "${c.name}" chip.)`, {show: `${c.icon || ""} ${c.name}`.trim()}); }, 350);
          });
          box.append(b);
        }
        kids.push(box);
      }
    } catch (e) {}
    if ((d.news || []).length) {
      kids.push(sec("Top stories", d.news.some(n => n.match) ? "Your interests first" : ""));
      const r = el("div", "hf-row"); for (const n of d.news) r.append(tile(n, "news")); kids.push(r);
    }
    feed.replaceChildren(...kids);
    $("home").classList.add("has-feed");
  }
  function demo() {
    return {hello: "Good evening, Sam", date: new Date().toLocaleDateString(undefined, {weekday: "long", month: "long", day: "numeric"}),
      stack: [{eyebrow: "Waiting for your OK", title: "1 thing ready to go", sub: "Book a showroom visit, Fri 1 PM", action: "chat:"},
        {eyebrow: "Up next", title: "Dentist", sub: "3:30 PM · 12 Main St", action: "chat:", tone: "warn"}],
      found: [{id: "a", kind: "deal", title: "Arc floor lamp, lowest of 4 stores", price: "$89", source: "Lamp Shop"},
        {id: "b", kind: "news", title: "Jazz win in overtime behind 41 from Markkanen", source: "ESPN"}],
      news: [{title: "Storms expected across the Mountain West this weekend", source: "NPR", match: true}, {title: "Markets close higher on rate hopes", source: "BBC"}]};
  }
  new MutationObserver(() => { if (!$("home").hidden) render(); }).observe($("home"), {attributes: true, attributeFilter: ["hidden"]});
  setTimeout(() => { if (!$("home").hidden) render(); }, 800);
})();
