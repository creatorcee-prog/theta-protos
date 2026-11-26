/* Haptics: a small tap of feedback at the moments that matter (send, a reply landing, a reaction, a toggle,
 * Approve, an error). app.js exposes it as Theta.haptic("light" | "success" | "warning").
 *   iPhone (iOS 18+ Safari and the Home Screen app): web pages get no vibration API, but toggling an
 *     <input type="checkbox" switch> plays the system's switch tick. So a hidden switch inside a label is
 *     clicked from code, inside the user's tap (outside a tap iOS stays silent, which is fine).
 *   Android: navigator.vibrate with a short pattern per kind.
 *   Anything else: nothing.
 * Rate-limited so a burst of events never turns into buzzing. */
(() => {
  "use strict";
  const ua = navigator.userAgent || "";
  const IOS = /iPhone|iPad|iPod/.test(ua) || (/Macintosh/.test(ua) && navigator.maxTouchPoints > 1);
  const VIBRATE = !IOS && typeof navigator.vibrate === "function";
  const PATTERN = {light: [9], success: [10, 70, 16], warning: [22, 90, 22, 90, 22]};
  const TICKS = {light: [0], success: [0, 90], warning: [0, 110, 220]};
  const GAP_MS = 140, PER_SEC = 4;
  let label = null, last = 0, recent = [];

  function iosSwitch() {
    if (label) return label;
    label = document.createElement("label");
    label.setAttribute("aria-hidden", "true");
    label.style.cssText = "position:fixed;left:-100px;top:0;width:1px;height:1px;overflow:hidden;opacity:0;pointer-events:none";
    const input = document.createElement("input");
    input.type = "checkbox"; input.setAttribute("switch", ""); input.tabIndex = -1;
    label.append(input);
    (document.body || document.documentElement).append(label);
    return label;
  }

  function haptic(kind, from) {
    kind = PATTERN[kind] ? kind : "light";
    if (!IOS && !VIBRATE) return false;
    // a real switch the user just flipped already ticked on its own
    if (IOS && from && from.matches && from.matches("input[switch]")) return false;
    const now = performance.now();
    recent = recent.filter(t => now - t < 1000);
    if (now - last < GAP_MS || recent.length >= PER_SEC) return false;
    last = now; recent.push(now);
    try {
      if (VIBRATE) return navigator.vibrate(PATTERN[kind]);
      const l = iosSwitch();
      for (const ms of TICKS[kind]) { if (ms) setTimeout(() => l.click(), ms); else l.click(); }
      return true;
    } catch (e) { return false; }
  }

  window.ThetaHaptics = {haptic, ios: IOS, vibrate: VIBRATE};
})();
