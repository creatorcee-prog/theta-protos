/* Theta's avatar: a turning globe of dots (ported from theta-app's "Urchin Pour", head.py).
 * Real 3D: the dots sit on a Fibonacci sphere, are depth-sorted, and near dots are bigger and brighter while far
 * ones fade into fog. A white-hot core glows in the middle with a cyan/blue halo.
 * Status (the avatar's motion IS the status; there is no typing indicator):
 *   "idle"     a slow turn and a breath
 *   ack()      one pulse and a ring: "got it"
 *   "working"  (alias "thinking") the dots swirl in latitude bands
 *   "speaking" spikes pour out of the globe, following the level the app pulses as text streams in
 *   "waiting"  waiting on you: the dots gather in a little and take Theta's indigo accent
 *   done()     settle: a soft ring, then back to idle
 * Openings (for the splash): "converge" (dots start as stars and glide into the globe, nearest first) and
 * "signal" (rings of dots pulse out like a broadcast, then come home as the globe's latitudes).
 * Dot shapes (theta-app's "Voice and tools > Dots"): circle, triangle, square, diamond, pentagon, hexagon, star.
 * Styles (theta-app's avatar styles): urchin (the default), precision (fine and dense), lumen (an inner shell and a
 * bright rim), flow (always gently streaming), signal (rays that pulse out), rings (the classic rings).
 * Color: setColor("#a78bfa") tints the globe from the theme color. A mount can pass {style, shape, hue} to preview
 * one without changing the saved look.
 *
 *   const orb = ThetaOrb.mount(canvas, {dots: 520});
 *   orb.setState("thinking"); orb.pulse(0.6); orb.opening("converge", () => ...); orb.destroy();
 * One shared animation loop drives every orb; orbs that are hidden (display:none) or off-screen skip drawing.
 */
(function () {
  "use strict";
  const TAU = Math.PI * 2;
  const store = (k, v) => { try { if (v === undefined) return localStorage.getItem(k); localStorage.setItem(k, v); } catch (e) { return null; } };
  const reduceQ = window.matchMedia ? matchMedia("(prefers-reduced-motion: reduce)") : {matches: false};

  // ---- the look: Theta's house colors (the "theta" dots theme: cyan core, blue/indigo edges), or the theme color's
  const LOOK = {hue: 195, sat: 95, light: 62, edgeHue: 222, waitHue: 262};
  try { const c = localStorage.getItem("theta:accent"); if (c) Object.assign(LOOK, lookFor(c)); } catch (e) { /* no storage */ }

  // ---- dot shapes
  const SHAPES = ["circle", "triangle", "square", "diamond", "pentagon", "hexagon", "star"];
  const SIDES = {triangle: 3, square: 4, diamond: 4, pentagon: 5, hexagon: 6};
  let shape = store("theta:dot") || "circle";
  if (SHAPES.indexOf(shape) < 0) shape = "circle";
  // ---- styles: how the globe is built and moves
  const STYLES = {urchin: {}, precision: {n: 2, dotK: 0.62, glow: 0.7}, lumen: {inner: true, rim: true, glow: 1.2},
                  flow: {flow: true, inner: true}, signal: {rays: true, rim: true}, rings: {rings: true},
                  // Generation 8 (light in glass): drawn by web/orb8.js
                  ribbons: {g8: true}, horizon: {g8: true}, plasma: {g8: true}, liquid: {g8: true}, nebula: {g8: true}};
  let style = store("theta:style") || "urchin";
  if (!STYLES[style]) style = "urchin";
  // ---- color: the theme color's hue, kept for the next open
  function hexHue(hex) {
    const m = /^#?([0-9a-f]{6})$/i.exec(String(hex || "")); if (!m) return null;
    const n = parseInt(m[1], 16), r = (n >> 16) / 255, g = ((n >> 8) & 255) / 255, b = (n & 255) / 255;
    const mx = Math.max(r, g, b), mn = Math.min(r, g, b), d = mx - mn;
    if (d < 0.08) return {hue: 210, sat: 8};  // white / grey: a silver globe
    const h = mx === r ? ((g - b) / d) % 6 : mx === g ? (b - r) / d + 2 : (r - g) / d + 4;
    return {hue: (h * 60 + 360) % 360, sat: 95};
  }
  function lookFor(c) { const h = hexHue(c) || {hue: 195, sat: 95};
    return {hue: h.hue, sat: h.sat, light: 62, edgeHue: h.hue + 27, waitHue: h.hue + 67}; }
  function dotPath(g, x, y, r, rot, sh) { g.beginPath(); addDot(g, x, y, r, rot, sh); }
  // one dot added to the current path (many dots of one color are filled together: see draw)
  function addDot(g, x, y, r, rot, sh) {
    sh = sh || shape;
    if (sh === "circle" || r < 0.9) { g.moveTo(x + r, y); g.arc(x, y, r, 0, TAU); return; }
    if (sh === "star") {
      const R = r * 1.5, ri = R * 0.45;
      for (let i = 0; i < 10; i++) { const a = (rot || 0) + i * Math.PI / 5 - Math.PI / 2, rr = i % 2 ? ri : R;
        if (i) g.lineTo(x + Math.cos(a) * rr, y + Math.sin(a) * rr); else g.moveTo(x + Math.cos(a) * rr, y + Math.sin(a) * rr); }
      g.closePath(); return;
    }
    const n = SIDES[sh] || 4, R = r * (n === 3 ? 1.45 : n === 4 ? 1.25 : 1.12);
    const off = (sh === "diamond" ? 0 : sh === "square" ? Math.PI / 4 : -Math.PI / 2) + (rot || 0);
    for (let i = 0; i < n; i++) { const a = off + i * TAU / n;
      if (i) g.lineTo(x + Math.cos(a) * R, y + Math.sin(a) * R); else g.moveTo(x + Math.cos(a) * R, y + Math.sin(a) * R); }
    g.closePath();
  }

  const col = (h, s, l, a) => `hsla(${((h % 360) + 360) % 360},${Math.max(0, Math.min(100, s))}%,${Math.max(0, Math.min(97, l))}%,${Math.max(0, Math.min(1, a))})`;
  const inOut = k => { k = Math.max(0, Math.min(1, k)); return k < 0.5 ? 4 * k * k * k : 1 - Math.pow(-2 * k + 2, 3) / 2; };
  const easeOut = k => 1 - Math.pow(1 - Math.max(0, Math.min(1, k)), 3);

  function sphere(n) {
    const out = [];
    for (let i = 0; i < n; i++) {
      const y = 1 - (i / (n - 1)) * 2, r = Math.sqrt(Math.max(0, 1 - y * y)), th = i * 2.39996;
      out.push({bx: Math.cos(th) * r, by: y, bz: Math.sin(th) * r, lat: Math.asin(y), lon: th % TAU,
                s: Math.random(), w: null, v: [0, 0, 0], sx: 0, sy: 0, d: Math.random(), p: Math.random() * TAU});
    }
    return out;
  }

  const orbs = new Set();
  let raf = 0;
  function loop(ms) {
    raf = 0;
    for (const o of orbs) o._frame(ms);
    if (orbs.size) raf = requestAnimationFrame(loop);
  }
  const kick = () => { if (!raf && orbs.size) raf = requestAnimationFrame(loop); };

  class Orb {
    constructor(canvas, opt) {
      this.cv = canvas; this.g = canvas.getContext("2d"); this.opt = Object.assign({dots: 520, scale: 1, dotK: 1, glow: 1, maxDpr: 2, radiusPx: 0}, opt || {});
      this.dotsFor = null; this._dots();
      this.state = "idle"; this.level = 0; this.target = 0; this.burst = 0; this.sw = {thinking: 0, speaking: 0, waiting: 0}; this.rings = []; this.punch = 0;
      this.clock = Math.random() * 20; this.last = 0; this.open = null; this.fade = 1; this.W = 0; this.H = 0; this.dpr = 1;
      this.pts = []; this.visible = true;
      if (window.IntersectionObserver) { this.io = new IntersectionObserver(es => { this.visible = es[es.length - 1].isIntersecting; }); this.io.observe(canvas); }
      orbs.add(this); kick();
    }
    _st() { return STYLES[this.opt.style] || STYLES[style] || {}; }
    _L() { return this.opt.color ? (this._lk || (this._lk = lookFor(this.opt.color))) : LOOK; }
    _dots() { const n = Math.round(this.opt.dots * (this._st().n || 1)); if (this.dotsFor !== n) { this.dots = sphere(n); this.dotsFor = n; } }
    setState(s) { if (s === "working") s = "thinking"; if (s !== this.state) { this.state = s; this._restDrawn = false; if (s === "speaking") this.burst = 0.5; kick(); } }
    pulse(amount) { this.burst = Math.min(1, this.burst + (amount == null ? 0.35 : amount)); }
    ring(hue) { this.rings.push({t0: this.clock, hue: hue == null ? this._L().hue : hue}); kick(); }
    ack() { this.punch = 1; this.ring(); }
    done() { this.ring(this._L().hue); this.setState("idle"); }
    destroy() { orbs.delete(this); if (this.io) this.io.disconnect(); }
    _size() {
      const r = this.cv.getBoundingClientRect(), dpr = Math.min(this.opt.maxDpr, window.devicePixelRatio || 1);
      const W = Math.max(1, Math.round(r.width * dpr)), H = Math.max(1, Math.round(r.height * dpr));
      if (W !== this.W || H !== this.H) { this.cv.width = W; this.cv.height = H; this.W = W; this.H = H; this.dpr = dpr; if (this.open) this._seed(); }
    }
    // ---- openings
    opening(kind, done, speed) {
      kind = kind === "signal" ? "signal" : "converge";
      if (this._st().g8) { this.fade = 0; this.open = {kind: "fade", t0: performance.now(), done, speed: speed > 0 ? speed : 1}; kick(); return; } // glass styles fade in
      speed = speed > 0 ? speed : 1;
      if (reduceQ.matches) { this.fade = 0; this.open = {kind: "fade", t0: performance.now(), done, speed}; kick(); return; }
      this.open = {kind, t0: performance.now(), done, sky: [], speed};
      this._size(); this._seed();
      for (const q of this.dots) { q.w = null; q.v = [0, 0, 0]; }
      kick();
    }
    _seed() {
      const o = this.open; if (!o || o.kind === "fade") return;
      const W = this.W, H = this.H;
      for (const q of this.dots) { q.sx = Math.random() * W; q.sy = Math.random() * H; }
      o.sky = o.kind === "converge" ? Array.from({length: Math.round(Math.min(320, W * H / (2600 * this.dpr * this.dpr)))},
        () => ({x: Math.random() * W, y: Math.random() * H, d: Math.random(), p: Math.random() * TAU, s: 0.4 + Math.random() * 1.2})) : [];
    }
    // where a dot sits on the globe this frame (unit sphere, before the camera turns)
    _shape(q, t, lv) {
      const lon = Math.atan2(q.bz, q.bx), lat = Math.asin(Math.max(-1, Math.min(1, q.by)));
      let r = (1 + 0.04 * Math.sin(t * 1.4 + q.by * 4)) * (1 + 0.14 * this.punch * Math.sin(Math.PI * Math.min(1, this.punch)))
        * (1 - this.sw.waiting * (0.1 + 0.03 * Math.sin(t * 1.8 + q.s * 6)));
      const spk = this.sw.speaking;
      if (spk > 0.01) {
        const spec = lv * (0.55 * Math.abs(Math.sin((lon * 1.5 + lat) * 5 + t * 9)) + 0.45 * Math.abs(Math.sin((lon * 1.5 + lat) * 11 - t * 5)));
        // soft-capped: at full level with the start-of-speech burst the spikes reached about 2.1x the radius and, with
        // the spring's overshoot, flew past the halo to the canvas edge. tanh keeps small motion as it was and stops
        // the peaks near 1.5x
        const sp = spk * q.s * 1.1 * spec * (0.6 + 0.4 * Math.sin(lat * 4 + t * 5));
        r += 0.5 * Math.tanh(sp / 0.5);
      }
      const st = this._st();
      if (st.rays && q.s > 0.72) r += 0.32 * Math.pow(Math.max(0, Math.sin(t * 1.6 - q.s * 9 + lat * 2)), 6);  // rays pulse out
      if (st.inner && q.s < 0.28) r *= 0.58;  // an inner shell
      let x = q.bx, y = q.by, z = q.bz;
      const th = Math.max(this.sw.thinking, st.flow ? 0.45 : 0);
      if (this.swirl) { // swirl in latitude bands: the poles turn faster than the equator. Each dot is always ON the sphere,
        // turned by the swirl built up so far, which stays when thinking ends. (Blending between its swirled and home
        // positions cut straight through the globe and pinched it into a vertical streak whenever thinking handed over
        // to speaking.)
        const a = lon + this.swirl * (1.5 + Math.abs(lat)) + th * Math.sin(lat * 6 + t * 2) * 0.25, cl = Math.cos(lat);
        x = Math.cos(a) * cl; z = Math.sin(a) * cl; r *= 1 - 0.06 * th * Math.abs(Math.sin(t * 3));
      }
      return [x * r, y * r, z * r];
    }
    _frame(ms) {
      const cv = this.cv;
      if (!cv.isConnected) { this.destroy(); return; }
      if (cv.offsetParent === null && getComputedStyle(cv).position !== "fixed") return; // hidden
      if (!this.visible || document.hidden) return;
      if (cv.closest("[inert]")) return;  // under an open sheet (dialogs.js makes what's behind inert): nobody sees it
      // at rest (no state, ring, opening or pulse in progress) the globe only drifts: 30 frames a second is plenty, and
      // with Reduce Motion it holds still (one frame, then nothing until something happens). Measured before: 21-26%
      // of the main thread at rest, every frame redrawn at 60 fps
      const sig = [this.opt.style, this.opt.shape, this.opt.color, style, shape, LOOK.hue, this.cv.clientWidth].join();  // a look change redraws
      const busy = sig !== this._sig || this.state !== "idle" || this.rings.length || this.open || this.burst > 0.01 || this.punch > 0 || this.level > 0.02
        || this.sw.thinking > 0.02 || this.sw.speaking > 0.02 || this.sw.waiting > 0.02;
      const still = reduceQ.matches;
      if (!busy) {
        if (still && this._restDrawn && this.W) return;
        if (ms - (this._drawnAt || 0) < 1000 / 30 - 2) return;
      }
      this._restDrawn = !busy; this._drawnAt = ms; this._sig = sig;
      this._size();
      const dt = Math.min(0.05, (ms - (this.last || ms)) / 1000); this.last = ms;
      this.clock += dt * (still ? 0.35 : 1);
      const t = this.clock;
      // states ease in and out
      for (const k in this.sw) this.sw[k] += ((this.state === k ? 1 : 0) - this.sw[k]) * Math.min(1, dt * 4);
      this.swirl = (this.swirl || 0) + dt * (still ? 0.35 : 1) * 1.2 * Math.max(this.sw.thinking, this._st().flow ? 0.45 : 0);
      let target = 0;
      if (this.state === "speaking") target = 0.18 + 0.25 * Math.max(0, Math.sin(t * 13) * Math.sin(t * 5.3 + 1.2)) + 0.75 * this.burst;
      else if (this.state === "thinking") target = 0.1;
      this.burst *= Math.pow(0.04, dt); // decays within about a second
      this.punch = Math.max(0, this.punch - dt * 2.2);
      this.level += (Math.min(1, target) - this.level) * Math.min(1, dt * 10);
      this._dots();
      this.draw(t, still ? this.level * 0.4 : this.level);
    }
    draw(t, lv) {
      const g = this.g, W = this.W, H = this.H, o = this.opt, cx = W / 2, cy = H / 2, S = Math.min(W, H), LOOK = this._L(), st = this._st();
      const glow = o.glow * (st.glow || 1), dotK = o.dotK * (st.dotK || 1), shp = o.shape || shape;
      const R = o.radiusPx ? o.radiusPx * this.dpr : S * 0.24 * o.scale, D = 3.2;
      g.setTransform(1, 0, 0, 1, 0, 0); g.clearRect(0, 0, W, H);
      let op = this.open, ot = 0, out = 1, end = 0;
      if (op) {
        ot = (performance.now() - op.t0) / 1000 * (op.speed || 1);
        end = op.kind === "signal" ? 2.9 : op.kind === "converge" ? 2.7 : 0.5;
        if (op.kind === "fade") this.fade = Math.min(1, ot / 0.5);
        out = Math.max(0, Math.min(1, (ot - end) / 0.4)); // how far the globe has taken over
        if (ot > end + 0.45) { const d = op.done; this.open = null; op = null; this.fade = 1; if (d) setTimeout(d, 0); }
      }
      const fadeA = this.fade;
      if (st.g8 && window.ThetaOrb8) { // a Generation 8 style: light in glass (web/orb8.js)
        g.save(); g.globalAlpha = fadeA; ThetaOrb8.draw(this, g, o.style && STYLES[o.style] ? o.style : style, t, lv); g.restore(); return;
      }
      // halo: cyan in the middle, blue at the edge; brighter while it talks
      if (glow) {
        const hr = Math.min(R * (2.3 + 0.5 * lv), S / 2), gr = g.createRadialGradient(cx, cy, R * 0.1, cx, cy, hr), k = Math.min(1.4, glow) * fadeA * (op ? out * 0.8 + 0.2 : 1);
        gr.addColorStop(0, col(LOOK.hue, 100, 60, (0.30 + 0.25 * lv) * k));
        gr.addColorStop(0.35, col(LOOK.edgeHue - 10, 95, 52, (0.14 + 0.1 * lv) * k));
        gr.addColorStop(0.7, col(LOOK.edgeHue, 90, 45, 0.05 * k));
        gr.addColorStop(1, col(LOOK.edgeHue, 90, 40, 0));
        g.fillStyle = gr; g.beginPath(); g.arc(cx, cy, hr, 0, TAU); g.fill();
      }
      const yaw = t * 0.18 * (1 + 1.2 * this.sw.thinking), pitch = 0.3 + 0.06 * Math.sin(t * 0.37);
      const cyw = Math.cos(yaw), syw = Math.sin(yaw), cp = Math.cos(pitch), sp = Math.sin(pitch);
      const k = 0.07, damp = 0.8, pts = this.pts; pts.length = 0;
      const diag = Math.hypot(W, H), dotR = R * 0.0325 * dotK;
      if (st.rings && !op) { this._rings(cx, cy, R, t, lv, fadeA, LOOK); this._core(cx, cy, R, lv, fadeA); return; }
      for (const q of this.dots) {
        const tg = this._shape(q, t, lv);
        if (!q.w) q.w = tg.slice();
        for (let j = 0; j < 3; j++) { q.v[j] = (q.v[j] + (tg[j] - q.w[j]) * k) * damp; q.w[j] += q.v[j]; }
        const [x, y, z] = q.w;
        const x1 = x * cyw - z * syw, z1 = x * syw + z * cyw, y2 = y * cp - z1 * sp, z2 = y * sp + z1 * cp, pr = D / (D + z2);
        let px = cx + x1 * R * pr, py = cy + y2 * R * pr, home = 1, vis = 1;
        if (op && op.kind !== "fade") { // the opening: from the stars (or a broadcast) into the globe
          if (op.kind === "converge") {
            const dist = Math.hypot(q.sx - cx, q.sy - cy) / diag, kk = inOut((ot - 0.35 - dist * 1.4) / 1.3), bend = Math.sin(Math.PI * kk) * dist * 0.18;
            home = kk;
            px = q.sx + (px - q.sx) * kk - (q.sy - cy) * bend; py = q.sy + (py - q.sy) * kk + (q.sx - cx) * bend;
            vis = 0.45 + 0.55 * (0.5 + 0.5 * Math.sin(ot * 1.4 + q.p));
          } else {
            const n = Math.floor(((Math.sin(q.lat) + 1) / 2) * 8.99), e = easeOut((ot - n * 0.09) / 0.9), rr = e * S * (0.16 + 0.042 * n), a = q.lon + ot * 0.3;
            const kk = inOut((ot - 1.35 - Math.abs(n - 4) * 0.06) / 1.3), sx = cx + Math.cos(a) * rr, sy = cy + Math.sin(a) * rr;
            home = kk; px = sx + (px - sx) * kk; py = sy + (py - sy) * kk; vis = e > 0 ? Math.min(1, e * 3) * (1 - 0.6 * e) : 0;
          }
        }
        pts.push([px, py, z2, pr, q.s, Math.hypot(q.v[0], q.v[1], q.v[2]), home, vis, q.d]);
      }
      pts.sort((a, b) => b[2] - a[2]);
      g.globalCompositeOperation = "lighter";
      if (op && op.kind === "signal") for (let n = 0; n < 3; n++) {
        const u = Math.max(0, Math.min(1, (ot - n * 0.32) / 1.1)); if (!u || u >= 1) continue;
        g.globalAlpha = 0.28 * (1 - u); g.strokeStyle = col(LOOK.hue, 95, 62, 1); g.lineWidth = this.dpr;
        g.beginPath(); g.arc(cx, cy, u * S * 0.55, 0, TAU); g.stroke(); g.globalAlpha = 1;
      }
      if (op && op.sky) for (const st of op.sky) {
        g.fillStyle = col(205, 60, 92, (0.12 + 0.55 * st.d) * (0.45 + 0.55 * (0.5 + 0.5 * Math.sin(ot * st.s + st.p))) * (1 - out));
        dotPath(g, st.x, st.y, (0.4 + 1.2 * st.d * st.d) * this.dpr, st.p); g.fill();
      }
      let coreDone = false;
      const coreK = op ? out : 1;
      // at rest and while talking (no opening), dots of nearly the same color are filled together, one fill per color,
      // back half, then the core, then the front half. With additive light the order within a half doesn't change
      // the picture; it was 520 separate color strings and fills a frame (most of the globe's CPU, measured)
      const batch = op ? null : [new Map(), new Map()];
      for (const [px, py, z, pr, s, v, home, vis, d] of pts) {
        if (!batch && !coreDone && z < 0) { this._core(cx, cy, R, lv, coreK * fadeA); coreDone = true; }
        const fog = Math.max(0.12, Math.min(1, 0.62 - z * 0.55));
        const hue = LOOK.hue + s * 18 - 9 + Math.max(0, z) * (LOOK.edgeHue - LOOK.hue) + 25 * this.sw.thinking * Math.sin(s * 9 + t * 2)
          + (LOOK.waitHue - LOOK.hue) * this.sw.waiting * (0.6 + 0.4 * s);
        const light = LOOK.light + (pr - 0.8) * 50 + Math.min(1, v * 40) * 12;
        let a = (0.1 + 0.55 * (0.4 + 0.6 * s)) * fog * fadeA * 1.25;
        if (st.rim) a *= 1 + 1.1 * Math.max(0, 1 - Math.abs(z) * 2.2);  // a bright rim at the edge
        let r = dotR * pr * pr * (0.8 + 0.4 * s);
        if (op && op.kind !== "fade") {
          const conv = op.kind === "converge";
          a = (1 - home) * vis * (0.35 + 0.65 * d) + home * a; r = (1 - home) * (conv ? (0.5 + 1.1 * d * d) * this.dpr : 1.1 * this.dpr) + home * r;
          g.fillStyle = home < 0.5 && conv ? col(205, 60, 92, a) : col(hue, LOOK.sat, light, a);
        } else if (batch) {
          const key = `${Math.round(hue / 3) * 3}|${Math.round(light / 3) * 3}|${Math.round(a * 30)}`, m = batch[z < 0 ? 1 : 0];
          let list = m.get(key); if (!list) m.set(key, list = []);
          list.push(px, py, Math.max(0.5, r), s * TAU);
          continue;
        } else g.fillStyle = col(hue, LOOK.sat, light, a);
        dotPath(g, px, py, Math.max(0.5, r), s * TAU, shp); g.fill();
      }
      if (batch) {
        for (let half = 0; half < 2; half++) {
          if (half === 1) { this._core(cx, cy, R, lv, coreK * fadeA); coreDone = true; }
          for (const [key, list] of batch[half]) {
            const [h, l, a30] = key.split("|");
            g.fillStyle = col(+h, LOOK.sat, +l, a30 / 30); g.beginPath();
            for (let i = 0; i < list.length; i += 4) addDot(g, list[i], list[i + 1], list[i + 2], list[i + 3], shp);
            g.fill();
          }
        }
      }
      if (!coreDone) this._core(cx, cy, R, lv, coreK * fadeA);
      for (let i = this.rings.length - 1; i >= 0; i--) { // ack / done: a ring opens and fades
        const rg = this.rings[i], u = (t - rg.t0) / 0.9; if (u >= 1 || u < 0) { this.rings.splice(i, 1); continue; }
        g.strokeStyle = col(rg.hue, 95, 70, 0.55 * (1 - u)); g.lineWidth = Math.max(1, R * 0.05 * (1 - u));
        g.beginPath(); g.arc(cx, cy, R * (1.05 + 0.6 * easeOut(u)), 0, TAU); g.stroke();
      }
      g.globalCompositeOperation = "source-over";
    }
    _rings(cx, cy, R, t, lv, a, LK) {  // "Classic rings": tilted rings turning around the core
      const g = this.g;
      g.globalCompositeOperation = "lighter"; g.lineWidth = Math.max(1, R * 0.035);
      for (let i = 0; i < 5; i++) {
        const tilt = 0.35 + i * 0.55 + t * (0.25 + i * 0.07), rr = R * (0.62 + i * 0.12) * (1 + 0.08 * lv * Math.sin(t * 9 + i));
        g.strokeStyle = col(LK.hue + i * 7, LK.sat, LK.light + 8 - i * 4, (0.75 - i * 0.1) * a);
        g.beginPath(); g.ellipse(cx, cy, rr, rr * Math.abs(Math.cos(tilt)) * 0.9 + rr * 0.08, i * 0.6 + t * 0.15, 0, TAU); g.stroke();
      }
      g.globalCompositeOperation = "source-over";
    }
    _core(cx, cy, R, lv, a) {
      if (a <= 0.01) return;
      const g = this.g, cr = R * (0.16 + 0.2 * lv), gr = g.createRadialGradient(cx, cy, 0, cx, cy, cr * 3.2);
      const LOOK = this._L(), H = LOOK.hue, L = LOOK.light;
      [[0, `rgba(255,255,255,${a})`], [0.05, col(H, 95, L + 34, a)], [0.11, col(H, 95, L + 18, 0.85 * a)], [0.2, col(H, 95, L + 6, 0.5 * a)],
       [0.32, col(H, 95, L, 0.26 * a)], [0.48, col(H, 95, L, 0.12 * a)], [0.68, col(H, 95, L, 0.045 * a)], [1, col(H, 95, L, 0)]]
        .forEach(([o, c]) => gr.addColorStop(o, c));
      const op = g.globalCompositeOperation; g.globalCompositeOperation = "lighter";
      g.fillStyle = gr; g.beginPath(); g.arc(cx, cy, cr * 3.2, 0, TAU); g.fill(); g.globalCompositeOperation = op;
    }
  }

  window.ThetaOrb = {
    mount: (canvas, opt) => new Orb(canvas, opt),
    shapes: SHAPES.slice(),
    get shape() { return shape; },
    setShape(s) { if (SHAPES.indexOf(s) >= 0) { shape = s; store("theta:dot", s); } },
    styles: Object.keys(STYLES),
    get style() { return style; },
    setStyle(s) { if (STYLES[s]) { style = s; store("theta:style", s); } },
    setColor(c) { const l = lookFor(c); Object.assign(LOOK, l); for (const o of orbs) o._lk = null; },
    dotPath,
    look: LOOK,
  };
})();
