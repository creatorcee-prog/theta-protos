/* progress: the live card of a multi-step job's phases (server/progress.py): a green check for each finished
   phase, a turning ring for the one in progress, a clock for the ones to come. It shows while Theta works and stays
   on the reply, where a phase Theta never finished shows as not done. DOM nodes only. */
(() => {
  "use strict";
  const T = window.Theta;
  if (!T) return;
  const {el} = T;
  const css = document.createElement("style");
  css.textContent = `
.pg { background: #1f1f21; border: 1px solid #2c2c2e; border-radius: 20px; padding: 6px 14px; margin: 6px 0 8px; max-width: 340px; text-align: left; }
.msg .pg { margin: 2px 0 10px; }
.pg-step { display: flex; align-items: center; gap: 12px; padding: 9px 0; font-size: 0.9118rem; line-height: 1.3; color: var(--text); }
.pg-step + .pg-step { border-top: 1px solid #2a2a2c; }
.pg-ic { width: 22px; height: 22px; flex: none; display: grid; place-items: center; }
.pg-step.done .pg-ic { border-radius: 50%; background: #30d158; }
.pg-step.done .pg-ic svg { width: 13px; height: 13px; color: #0b2614; }
.pg-step.active .pg-ic { border-radius: 50%; border: 2.5px solid #2c3e55; border-top-color: #8ab4ff; animation: pgSpin .9s linear infinite; box-sizing: border-box; }
.pg-step.pending, .pg-step.skipped { color: #a8a8ad; }
.pg-step.pending .pg-ic svg, .pg-step.skipped .pg-ic svg { width: 20px; height: 20px; color: #a8a8ad; }
.pg-step.skipped .pg-txt { text-decoration: line-through; text-decoration-color: #555; }
@keyframes pgSpin { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) { .pg-step.active .pg-ic { animation-duration: 2.4s; } }
`;
  document.head.append(css);
  const NS = "http://www.w3.org/2000/svg";
  function icon(paths, fill) {
    const s = document.createElementNS(NS, "svg"); s.setAttribute("viewBox", "0 0 24 24"); s.setAttribute("aria-hidden", "true");
    for (const d of paths) { const p = document.createElementNS(NS, "path"); p.setAttribute("d", d); p.setAttribute("fill", fill ? "currentColor" : "none");
      p.setAttribute("stroke", "currentColor"); p.setAttribute("stroke-width", fill ? "0" : "2.4"); p.setAttribute("stroke-linecap", "round"); p.setAttribute("stroke-linejoin", "round"); s.append(p); }
    return s;
  }
  const ICON = {
    done: () => icon(["M5 12.5l4.2 4.2L19 7"]),
    pending: () => icon(["M12 3a9 9 0 110 18 9 9 0 010-18z", "M12 7.5V12l3 2"]),
    skipped: () => icon(["M12 3a9 9 0 110 18 9 9 0 010-18z", "M8 12h8"]),
  };
  const WORD = {done: "done", active: "in progress", pending: "to come", skipped: "not done"};
  function card(steps) {
    const box = el("div", "pg"); box.setAttribute("role", "list"); box.setAttribute("aria-label", "Progress");
    for (const s of steps || []) {
      const row = el("div", "pg-step " + s.state); row.setAttribute("role", "listitem"); row.setAttribute("aria-label", `${s.text}: ${WORD[s.state] || s.state}`);
      const ic = el("span", "pg-ic"); if (ICON[s.state]) ic.append(ICON[s.state]());
      row.append(ic, el("span", "pg-txt", s.text)); box.append(row);
    }
    return box;
  }
  T.progressCard = card;

  // live: while Theta works, above the status line
  T.on("progress", (d, ctx) => {
    const host = ctx && ctx.pending; if (!host || !d || !Array.isArray(d.steps)) return;
    const old = host.querySelector(".pg"), next = card(d.steps);
    if (old) old.replaceWith(next); else host.prepend(next);
    if (ctx.follow) ctx.follow();
  });
  // kept: at the top of the reply
  T.decorate((m, row, bubble) => {
    const steps = (m.meta || {}).progress;
    if (!Array.isArray(steps) || !steps.length || !bubble || bubble.querySelector(".pg")) return;
    bubble.prepend(card(steps));
  });
})();
