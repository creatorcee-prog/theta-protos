/* desktop: rows that scroll sideways (Home's stories and finds, the chips, the look pickers, photo strips) hide their
   scrollbars, so with a mouse they looked cut off: a wheel only scrolls up and down, and a mouse can't swipe. With a
   mouse (a fine pointer that hovers), this:
   - turns the wheel's up/down into sideways scrolling over a row that scrolls sideways
   - lets the row be dragged sideways; a drag doesn't also tap whatever it started on
   Touch screens keep their own swipe. DOM only. */
(() => {
  "use strict";
  const mouse = matchMedia("(hover: hover) and (pointer: fine)");

  // the nearest element under the pointer that scrolls sideways and has more to show
  function sideways(t) {
    for (let e = t instanceof Element ? t : null; e && e !== document.body; e = e.parentElement) {
      if (e.scrollWidth <= e.clientWidth + 2) continue;
      const ox = getComputedStyle(e).overflowX;
      if (ox === "auto" || ox === "scroll") return e;
    }
    return null;
  }

  document.addEventListener("wheel", ev => {
    if (!mouse.matches || ev.ctrlKey || Math.abs(ev.deltaX) >= Math.abs(ev.deltaY)) return;  // a trackpad's own sideways swipe works already
    const row = sideways(ev.target); if (!row) return;
    const max = row.scrollWidth - row.clientWidth, d = ev.deltaMode === 1 ? ev.deltaY * 16 : ev.deltaY;
    if ((d < 0 && row.scrollLeft <= 0) || (d > 0 && row.scrollLeft >= max - 1)) return;  // at its end: let the page scroll
    ev.preventDefault();
    row.scrollLeft += d;
  }, {passive: false});

  let drag = null;
  document.addEventListener("pointerdown", ev => {
    if (!mouse.matches || ev.pointerType !== "mouse" || ev.button !== 0) return;
    if (ev.target.closest("input, textarea, select, [contenteditable], canvas")) return;
    const row = sideways(ev.target); if (!row) return;
    drag = {row, x: ev.clientX, left: row.scrollLeft, moved: false, id: ev.pointerId};
  }, true);
  document.addEventListener("pointermove", ev => {
    if (!drag || ev.pointerId !== drag.id) return;
    const dx = ev.clientX - drag.x;
    if (!drag.moved && Math.abs(dx) < 6) return;
    if (!drag.moved) { drag.moved = true; drag.snap = drag.row.style.scrollSnapType; drag.row.style.scrollSnapType = "none"; drag.row.classList.add("dragging"); }
    drag.row.scrollLeft = drag.left - dx;
  }, true);
  const end = ev => {
    if (!drag || (ev && ev.pointerId !== drag.id)) return;
    const d = drag; drag = null;
    if (!d.moved) return;
    d.row.style.scrollSnapType = d.snap || ""; d.row.classList.remove("dragging");
    // the click that follows a drag isn't a tap on the tile under the mouse
    const eat = e => { e.stopPropagation(); e.preventDefault(); };
    addEventListener("click", eat, {capture: true, once: true});
    setTimeout(() => removeEventListener("click", eat, {capture: true}), 0);
  };
  document.addEventListener("pointerup", end, true);
  document.addEventListener("pointercancel", end, true);

  const css = document.createElement("style");
  css.textContent = `.dragging { cursor: grabbing; user-select: none; } .dragging * { pointer-events: none; }`;
  document.head.append(css);
})();
