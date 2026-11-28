/* dialogs: one behavior for every sheet, menu and overlay (Settings, feature sheets, Attach, GIFs, effects, the photo
   viewer, voice mode, the chat menu). Each used to handle opening and closing on its own, so Escape, focus and swipes
   worked in some and not others. Watching the `hidden` attribute, this gives all of them:
   - focus moves into the overlay when it opens and back to what opened it when it closes; Tab stays inside it
   - everything behind it is `inert` (not tappable, not read out by VoiceOver) while it's open
   - Escape closes the top one, through its own close button, so its own cleanup runs
   - bottom sheets with a grab handle close when dragged down; full-screen sheets close with a swipe from the left
     edge, like iOS's back gesture
   - the chat menu: arrow keys move between items, Home/End jump, Escape returns to the ... button
   DOM nodes only. */
(() => {
  "use strict";
  const T = window.Theta;
  if (!T) return;
  const app = document.getElementById("app") || document.body;
  const SEL = "#settings, .sheet, #fxpick, #viewer, #voice, #menu";
  const CLOSERS = ["[data-close]", ":scope > .sheet-head button[aria-label='Close']", "#gif-close", "#fx-close", "#viewer-close", "#voice-close"];
  const FOCUSABLE = "button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex='-1'])";
  const open = [];   // overlays now showing, newest last: {el, from}
  const visible = e => !e.hidden && e.getClientRects().length > 0;
  const focusables = e => [...e.querySelectorAll(FOCUSABLE)].filter(x => x.offsetParent !== null && !x.closest("[hidden]"));

  function setInert() {  // the chat menu isn't modal (a tap outside closes it), so it never makes anything inert
    const modal = [...open].reverse().find(o => o.el.id !== "menu");
    const top = modal ? modal.el : null;
    for (const c of app.children) {
      if (c.id === "scrim" || c.classList.contains("toast")) continue;
      c.inert = !!top && !(c === top || c.contains(top));
    }
  }
  function opened(e) {
    if (open.some(o => o.el === e)) return;
    open.push({el: e, from: document.activeElement});
    setInert();
    requestAnimationFrame(() => {
      if (e.hidden || e.contains(document.activeElement)) return;
      const first = e.id === "menu" ? e.querySelector("[role=menuitem]") : (e.querySelector("[autofocus]") || focusables(e)[0]);
      if (first) first.focus({preventScroll: true});
      else { if (!e.hasAttribute("tabindex")) e.tabIndex = -1; e.focus({preventScroll: true}); }
    });
  }
  function closed(e) {
    const i = open.findIndex(o => o.el === e);
    if (i < 0) return;
    const [{from}] = open.splice(i, 1);
    setInert();
    if (from && from.isConnected && !from.closest("[hidden]") && document.activeElement && (e.contains(document.activeElement) || document.activeElement === document.body)) {
      try { from.focus({preventScroll: true}); } catch (err) {}
    }
  }
  function close(e) {
    if (e.id === "menu") { e.hidden = true; return; }
    for (const s of CLOSERS) {
      let b = null; try { b = e.querySelector(s); } catch (err) {}
      if (b && visible(b)) { b.click(); return; }
    }
    const scrim = document.getElementById("scrim");
    if (scrim && !scrim.hidden) { scrim.click(); if (e.hidden) return; }
    e.hidden = true;
  }

  // watch every overlay, including ones features add later
  const watch = new MutationObserver(list => {
    for (const m of list) {
      if (m.type === "attributes" && m.target.matches && m.target.matches(SEL)) (m.target.hidden ? closed : opened)(m.target);
      for (const n of m.addedNodes || []) if (n.nodeType === 1 && n.matches(SEL)) { if (!n.hidden) opened(n); }
    }
    keepFocus();
  });
  // a page change inside a sheet (Settings > Back) can hide the focused button: focus would fall to nowhere, and
  // VoiceOver with it. Put it on the sheet's first control instead.
  function keepFocus() {
    const modal = [...open].reverse().find(o => o.el.id !== "menu");
    if (!modal) return;
    requestAnimationFrame(() => {
      const a = document.activeElement, e = modal.el;
      if (e.hidden || (a && a !== document.body && e.contains(a) && !a.closest("[hidden]") && a.offsetParent !== null)) return;
      const f = focusables(e)[0];
      if (f) f.focus({preventScroll: true});
    });
  }
  watch.observe(app, {attributes: true, attributeFilter: ["hidden"], subtree: true, childList: true});
  document.querySelectorAll(SEL).forEach(e => { if (!e.hidden) opened(e); });

  document.addEventListener("keydown", ev => {
    const top = open.length ? open[open.length - 1].el : null;
    if (!top) return;
    if (ev.key === "Escape" && !ev.defaultPrevented) {
      if (document.getElementById("msgbar") && !document.getElementById("msgbar").hidden) return;  // its own handler
      ev.preventDefault(); close(top); return;
    }
    if (ev.key === "Tab" && top.id !== "menu") {  // keep Tab inside the top overlay
      const f = focusables(top); if (!f.length) return;
      const i = f.indexOf(document.activeElement);
      if (ev.shiftKey && (i <= 0)) { ev.preventDefault(); f[f.length - 1].focus(); }
      else if (!ev.shiftKey && (i === f.length - 1 || i < 0)) { ev.preventDefault(); f[0].focus(); }
      return;
    }
    if (top.id === "menu" && ["ArrowDown", "ArrowUp", "Home", "End"].includes(ev.key)) {
      const items = [...top.querySelectorAll("[role=menuitem]")].filter(visible); if (!items.length) return;
      ev.preventDefault();
      const i = items.indexOf(document.activeElement);
      const j = ev.key === "Home" ? 0 : ev.key === "End" ? items.length - 1 : (i + (ev.key === "ArrowDown" ? 1 : -1) + items.length) % items.length;
      items[j].focus();
    }
  });

  // bottom sheets: drag the grab handle (or the top of the sheet) down to close
  function dragToClose(sheet) {
    if (sheet._drag) return; sheet._drag = true;
    let y0 = null, dy = 0;
    sheet.addEventListener("pointerdown", e => {
      const r = sheet.getBoundingClientRect();
      if (e.clientY - r.top > 56 && !e.target.closest(".grab")) return;  // only from the top strip, so lists still scroll
      y0 = e.clientY; dy = 0; sheet.style.transition = "none";
      try { sheet.setPointerCapture(e.pointerId); } catch (err) {}
    });
    sheet.addEventListener("pointermove", e => {
      if (y0 == null) return;
      dy = Math.max(0, e.clientY - y0); sheet.style.transform = `translateY(${dy}px)`;
    });
    const end = () => {
      if (y0 == null) return;
      y0 = null; sheet.style.transition = ""; sheet.style.transform = "";
      if (dy > 80) close(sheet);
    };
    sheet.addEventListener("pointerup", end); sheet.addEventListener("pointercancel", end);
  }
  document.querySelectorAll(".sheet.bottom").forEach(dragToClose);

  // full-screen sheets: a swipe in from the left edge goes back (the standalone app has no browser back gesture)
  let sx = null, sy = 0, st = 0;
  document.addEventListener("touchstart", e => {
    const t = e.touches[0];
    sx = t.clientX < 24 && open.some(o => o.el.classList.contains("full")) ? t.clientX : null; sy = t.clientY; st = performance.now();
  }, {passive: true});
  document.addEventListener("touchend", e => {
    if (sx == null) return;
    const t = e.changedTouches[0], dx = t.clientX - sx, dyy = Math.abs(t.clientY - sy);
    sx = null;
    if (dx > 80 && dyy < 60 && performance.now() - st < 700) {
      const top = [...open].reverse().find(o => o.el.classList.contains("full"));
      if (top) { const back = top.el.querySelector("#settings-back:not([hidden])"); if (back && visible(back)) back.click(); else close(top.el); }
    }
  }, {passive: true});
})();
