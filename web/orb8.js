/* Theta's Generation 8 avatars (from the Avatar Lab, docs/avatar-lab): light inside a dark glass sphere, in five
 * styles: ribbons, horizon, plasma, liquid, nebula. web/orb.js hands a frame to ThetaOrb8.draw when one of these
 * styles is chosen; the orb's own eased states drive them (idle, thinking, speaking, and "waiting on you" as
 * listening) and its color is the theme color. The drawing code is the lab's, unchanged apart from a transparent
 * background and a square fitted into any canvas. Generated from the lab page; edit the lab, then copy it here.
 */
(function () {
  "use strict";
  const TAU = Math.PI * 2;
  const cur = {hue: 195, sat: 95, light: 62, speed: 1, jitter: 0, bounce: 0}, st = {energy: 1};
  const moodW = {calm: 1, focused: 0, happy: 0, concerned: 0, sleepy: 0, proud: 0};
  let W = {idle: 1, listening: 0, thinking: 0, speaking: 0};
  const SIT = {success: 0, alert: 0, working: 0}; let sitT = 0;
  let OX = 0, OY = 0;
  const spec = (a, t, lv) => lv * (0.55 * Math.abs(Math.sin(a * 5 + t * 9)) + 0.45 * Math.abs(Math.sin(a * 11 - t * 5)));
  const tint = (l, a, satK = 0.5) => `hsla(${cur.hue},${Math.round(cur.sat * satK)}%,${Math.min(98, l)}%,${a})`;
  function lightAt(g, x, y, r, a, k = 0.09) { // a real light: hot white core, steep 1/(1+(d/k)^2) falloff, a faint tail to nothing
    const gr = g.createRadialGradient(x, y, 0, x, y, r);
    for (const d of [0, .03, .07, .12, .2, .3, .45, .65, .85, 1]) { const f = (1 / (1 + (d / k) ** 2)) * (1 - d) ** 2;
      gr.addColorStop(d, f > 0.5 ? `hsla(${cur.hue},${Math.round(cur.sat * (1 - f) )}%,${Math.round(70 + 28 * f)}%,${a * f})` : tint(66, a * f, 1)); }
    g.fillStyle = gr; g.beginPath(); g.arc(x, y, r, 0, TAU); g.fill();
  }
  const hsla = (h, s, l, a) => `hsla(${(h % 360 + 360) % 360},${Math.max(0, Math.min(100, s))}%,${Math.max(0, Math.min(98, l))}%,${Math.max(0, Math.min(1, a))})`;
  // ---- Generation 8: Glass, rebuilt on Generation 7's engine. Light living inside a dark glass sphere (after the
  // voice-assistant orbs the user sent), in real 3D: the same drifting camera, depth sorting and fog, every moving
  // part on a spring, the state weights (W) blending one state's shape into the next, the mood color plus companions
  // around the wheel, moods that bend the shape, and the moments (Got it, Heads-up, Working) on top.
  // the companions spread around the wheel when calm and close in on the mood color in any other mood, so a mood
  // colors the whole light, not just the rim
  const pal8 = (k, spread = 1) => cur.hue + [0, 135, -45, 95][((k % 4) + 4) % 4] * spread * (1 - 0.8 * (1 - moodW.calm));
  function spring(o, key, target, k = 0.08, d = 0.8) {
    if (o[key] === undefined) { o[key] = target; o[key + "_v"] = 0; }
    o[key + "_v"] = (o[key + "_v"] + (target - o[key]) * k) * d; o[key] += o[key + "_v"]; return o[key];
  }
  function cam8(t, sp) {
    const yaw = t * 0.16 * sp * (1 + 1.4 * W.thinking), pitch = 0.32 + 0.05 * Math.sin(t * 0.3) - 0.12 * W.listening;
    return {yaw, cy: Math.cos(yaw), sy: Math.sin(yaw), cp: Math.cos(pitch), spn: Math.sin(pitch)};
  }
  const view = (m, x, y, z) => { const x1 = x * m.cy - z * m.sy, z1 = x * m.sy + z * m.cy; return [x1, y * m.cp - z1 * m.spn, y * m.spn + z1 * m.cp]; };
  const scr = (c, R, x, y, z, D = 3.6) => { const k = D / (D + z); return [c + x * R * k, c + y * R * k, z, k]; };
  function eul(v, a, b, cc) { // rotate about x by a, y by b, z by cc
    let [x, y, z] = v; let t1 = y * Math.cos(a) - z * Math.sin(a); z = y * Math.sin(a) + z * Math.cos(a); y = t1;
    t1 = x * Math.cos(b) + z * Math.sin(b); z = -x * Math.sin(b) + z * Math.cos(b); x = t1;
    t1 = x * Math.cos(cc) - y * Math.sin(cc); y = x * Math.sin(cc) + y * Math.cos(cc); x = t1; return [x, y, z];
  }
  const add3 = (a, b, s = 1) => [a[0] + b[0] * s, a[1] + b[1] * s, a[2] + b[2] * s];
  const dot3 = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
  const cross3 = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
  const norm3 = a => { const l = Math.hypot(a[0], a[1], a[2]) || 1; return [a[0] / l, a[1] / l, a[2] / l]; };
  // the moments, on any point: success sends a green wave out from the middle, alert flickers the silhouette amber
  const hueTo = (h, target, w) => { // the short way round the wheel, unless that way crosses green (then the other way)
    let d = (((target - h) % 360) + 540) % 360 - 180;
    const mid = ((h + d / 2) % 360 + 360) % 360; if (target < 90 && mid > 85 && mid < 175) d = d > 0 ? d - 360 : d + 360;
    return h + d * w; };
  function ring8(g, c, rr, hue, a, R) { // a continuous ring of light (soft, layered strokes; never dots)
    for (const [lw, k] of [[0.34, 0.12], [0.22, 0.18], [0.12, 0.24], [0.06, 0.28]]) { g.lineWidth = R * lw; g.strokeStyle = hsla(hue, 85, 66, a * k); g.beginPath(); g.arc(c, c, rr, 0, TAU); g.stroke(); } }
  function moment8(hue, x, y, z) {
    let tone = 0;
    if (SIT.success > 0.01) { const w = Math.max(0, Math.sin(Math.hypot(x, y) * 5 - sitT * 5)) ** 3 * SIT.success; hue = hueTo(hue, 145, w); tone = Math.max(tone, w); }
    if (SIT.alert > 0.01) { const e = Math.max(0.35, 1 - Math.abs(z) * 2.2) * (0.55 + 0.45 * Math.sin(sitT * 9 + x * 7)) * SIT.alert; hue = hueTo(hue, 36, e); tone = Math.max(tone, e); }
    return [hue, tone];
  }
  function shell8(g, S, t, lv, o = {}) {
    const c = S / 2, R = S * 0.29 * (1 + 0.025 * Math.sin(t * 1.3) + 0.04 * lv * W.speaking) * (1 - 0.04 * moodW.focused);
    g.setTransform(1, 0, 0, 1, OX, OY);
    g.translate(0, -S * cur.bounce * 0.01 * Math.abs(Math.sin(t * 3)) + S * 0.02 * moodW.sleepy);
    let gr = g.createRadialGradient(c, c, R * 0.9, c, c, R * 1.8);
    gr.addColorStop(0, hsla(cur.hue, 70, 45, 0.13 + 0.16 * lv + 0.06 * W.thinking)); gr.addColorStop(1, hsla(cur.hue, 70, 30, 0));
    g.fillStyle = gr; g.beginPath(); g.arc(c, c, R * 1.8, 0, TAU); g.fill();
    if (!o.bare) {
      gr = g.createRadialGradient(c - R * 0.18, c - R * 0.22, R * 0.05, c, c, R);
      gr.addColorStop(0, hsla(cur.hue, 22, 13, 0.92)); gr.addColorStop(0.75, hsla(cur.hue, 30, 6, 0.96)); gr.addColorStop(1, hsla(cur.hue, 35, 3, 1));
      g.fillStyle = gr; g.beginPath(); g.arc(c, c, R, 0, TAU); g.fill();
      g.globalCompositeOperation = "lighter"; // Fresnel: glass brightens toward its edge
      gr = g.createRadialGradient(c, c, R * 0.68, c, c, R);
      gr.addColorStop(0, hsla(cur.hue, 60, 60, 0)); gr.addColorStop(1, hsla(cur.hue, 60, 62, 0.13 + 0.08 * lv));
      g.fillStyle = gr; g.beginPath(); g.arc(c, c, R, 0, TAU); g.fill(); g.globalCompositeOperation = "source-over";
    }
    return {c, R};
  }
  function rim8(g, c, R, t, lv, cam) { // chromatic edge, key-light highlight, and the moments on the rim
    g.globalCompositeOperation = "lighter";
    const n = 120;
    for (const [dx, dh, a0] of [[-0.012, 38, 0.55], [0, 0, 0.8], [0.012, -38, 0.55]]) {
      g.lineWidth = Math.max(1, R * 0.011);
      for (let i = 0; i < n; i++) {
        const a = i / n * TAU, k = Math.pow(0.5 + 0.5 * Math.cos(2 * (a - 2.25 - 0.25 * Math.sin(cam.yaw))), 2.2);
        let hue = cur.hue + dh + 30 * Math.sin(a + t * 0.2), al = (0.06 + 0.5 * k) * a0 * (0.85 + 0.35 * lv);
        if (SIT.alert > 0.01) { hue = hueTo(hue, 36, SIT.alert); al += 0.25 * SIT.alert * (0.6 + 0.4 * Math.sin(t * 9)); }
        if (SIT.success > 0.01) { const sweep = Math.max(0, Math.cos(a + Math.PI / 2 - sitT * 3)) ** 6 * SIT.success; hue = hueTo(hue, 145, sweep); al += 0.6 * sweep; }
        g.strokeStyle = hsla(hue, 85, 72, al); g.beginPath(); g.arc(c + dx * R, c, R * 0.994, a, a + TAU / n * 1.1); g.stroke();
      }
    }
    if (SIT.alert > 0.01) { const pulse = 0.65 + 0.35 * Math.sin(t * 7);
      for (let i = 0; i < 72; i++) { const a = i / 72 * TAU, top = (0.5 + 0.5 * Math.cos(a + Math.PI / 2)) ** 2;
        for (const [lw, k] of [[0.09, 0.22], [0.035, 0.6]]) { g.lineWidth = R * lw * (0.4 + 0.6 * top); g.strokeStyle = hsla(36, 95, 62, k * top * pulse * SIT.alert);
          g.beginPath(); g.arc(c, c, R * 0.99, a, a + TAU / 72 * 1.1); g.stroke(); } } }
    if (SIT.working > 0.01) { const f = (sitT * 0.25) % 1; g.lineWidth = Math.max(1.5, R * 0.028); g.lineCap = "round"; // progress drawn on the glass rim itself
      g.strokeStyle = hsla(280, 85, 72, 0.9 * SIT.working); g.beginPath(); g.arc(c, c, R * 0.994, -Math.PI / 2, -Math.PI / 2 + f * TAU); g.stroke();
      const a = -Math.PI / 2 + f * TAU, gr2 = g.createRadialGradient(c + Math.cos(a) * R, c + Math.sin(a) * R, 0, c + Math.cos(a) * R, c + Math.sin(a) * R, R * 0.12);
      gr2.addColorStop(0, hsla(280, 90, 80, 0.8 * SIT.working)); gr2.addColorStop(1, hsla(280, 90, 70, 0)); g.fillStyle = gr2; g.beginPath(); g.arc(c + Math.cos(a) * R, c + Math.sin(a) * R, R * 0.12, 0, TAU); g.fill(); }
    const hx = c - R * 0.36 + Math.sin(cam.yaw) * R * 0.07, hy = c - R * 0.5;
    g.save(); g.translate(hx, hy); g.rotate(-0.55); g.scale(1, 0.42);
    const gr = g.createRadialGradient(0, 0, 0, 0, 0, R * 0.34); gr.addColorStop(0, "rgba(255,255,255,0.2)"); gr.addColorStop(1, "rgba(255,255,255,0)");
    g.fillStyle = gr; g.beginPath(); g.arc(0, 0, R * 0.34, 0, TAU); g.fill(); g.restore();
    g.strokeStyle = "rgba(255,255,255,0.06)"; g.lineWidth = Math.max(1, R * 0.015); g.beginPath(); g.arc(c, c, R * 0.9, 0.25, 1.2); g.stroke();
    g.globalCompositeOperation = "source-over";
  }
  const inside8 = (g, c, R, fn) => { g.save(); g.beginPath(); g.arc(c, c, R * 0.985, 0, TAU); g.clip(); g.globalCompositeOperation = "lighter"; fn(); g.restore(); };
  const dtOf = (me, t) => { const dt = Math.min(0.05, Math.max(0, t - (me.lt ?? t))); me.lt = t; return dt; };

  const sprites8 = {};
  function sprite8(hue) {
    const key = Math.round(((hue % 360) + 360) % 360 / 6) * 6; if (sprites8[key]) return sprites8[key];
    const cv = document.createElement("canvas"); cv.width = cv.height = 64; const x = cv.getContext("2d"), gr = x.createRadialGradient(32, 32, 0, 32, 32, 32);
    gr.addColorStop(0, hsla(key, 90, 70, 1)); gr.addColorStop(0.35, hsla(key, 90, 58, 0.45)); gr.addColorStop(1, hsla(key, 90, 50, 0));
    x.fillStyle = gr; x.fillRect(0, 0, 64, 64); return (sprites8[key] = cv);
  }
  // a bright core: a wide soft bloom and a small white heart (at chat size the light still reads)
  function core8(g, c, R, t, lv, k = 1) {
    lightAt(g, c, c, R * (0.95 + 0.3 * lv + 0.12 * W.thinking * Math.abs(Math.sin(t * 3))) * k, 0.72, 0.12);
    const gr = g.createRadialGradient(c, c, 0, c, c, R * 0.2 * k);
    gr.addColorStop(0, `rgba(255,255,255,${0.45 + 0.15 * lv})`); gr.addColorStop(0.4, hsla(cur.hue, 70, 80, 0.3)); gr.addColorStop(1, hsla(cur.hue, 60, 70, 0));
    g.fillStyle = gr; g.beginPath(); g.arc(c, c, R * 0.2 * k, 0, TAU); g.fill();
  }
  // light, not shapes: a soft haze inside the glass, and a bloom over everything (the frame shrunk and laid back on
  // top, which blurs every edge into glow and works in every browser, iPhone Safari included)
  function haze8(g, c, R, lv, k = 1) {
    const gr = g.createRadialGradient(c, c, 0, c, c, R);
    gr.addColorStop(0, hsla(cur.hue, 80, 60, (0.16 + 0.1 * lv) * k)); gr.addColorStop(0.7, hsla(pal8(1, 0.4), 80, 50, 0.08 * k)); gr.addColorStop(1, hsla(cur.hue, 80, 45, 0.02 * k));
    g.fillStyle = gr; g.beginPath(); g.arc(c, c, R, 0, TAU); g.fill();
  }
  let bloomCv = null;
  function bloom8(g, S, a = 0.55) { a *= 0.75;
    if (!bloomCv) { bloomCv = document.createElement("canvas"); bloomCv.width = bloomCv.height = 60; }
    const b = bloomCv.getContext("2d"), cw = g.canvas.width, ch = g.canvas.height; b.globalCompositeOperation = "copy"; b.drawImage(g.canvas, 0, 0, 60, 60);
    g.save(); g.setTransform(1, 0, 0, 1, 0, 0); g.globalCompositeOperation = "lighter"; g.globalAlpha *= a; g.imageSmoothingQuality = "high";
    g.drawImage(bloomCv, 0, 0, cw, ch); g.restore();
  }
  const glow8 = (g, x, y, r, hue, a) => { if (a <= 0.003 || r <= 0.3) return; g.globalAlpha = Math.min(1, a); g.drawImage(sprite8(hue), x - r, y - r, 2 * r, 2 * r); g.globalAlpha = 1; };
  const bold8 = S => S < 200 ? 1.5 : 1; // at chat size, light gets wider so it still reads
  const rotZ = (v, a) => [v[0] * Math.cos(a) - v[1] * Math.sin(a), v[0] * Math.sin(a) + v[1] * Math.cos(a), v[2]];

  // 8.1 Ribbons: silk ribbons of light, each brightest along its spine and fading to nothing at its edges
  function g8ribbons(g, S, t, lv, me) {
    const sp = cur.speed * st.energy, dt = dtOf(me, t), {c, R} = shell8(g, S, t, lv), cam = cam8(t, sp);
    if (!me.rb) me.rb = [0, 1, 2, 3, 4].map(k => ({k, ph: k * 1.3, ax: k * 1.1, ay: k * 1.9, az: k * 0.6}));
    me.rz = (me.rz || 0) + dt * sp * (0.18 + 2.8 * W.thinking);
    const fan = spring(me, "fan", W.listening, 0.06), Q = [], SP = [];
    for (const rb of me.rb) {
      const width = spring(rb, "w", bold8(S) * (0.3 + 0.05 * Math.sin(t * 1.1 + rb.ph) + 0.26 * lv * W.speaking * (0.6 + 0.4 * Math.sin(t * 9 + rb.k)) + 0.06 * W.listening * (0.6 + lv)) * (1 - 0.35 * W.thinking));
      const bulge = spring(rb, "b", 0.26 + 0.1 * Math.sin(t * 0.7 + rb.ph) + 0.4 * lv * W.speaking);
      const reach = spring(rb, "reach", 1 - 0.3 * W.thinking + (0.14 * lv + 0.12 * Math.sin(t * 7 + rb.k)) * W.speaking, 0.08);
      const twist = spring(rb, "tw", 0.9 + 2.2 * W.thinking, 0.05), spin = (0.3 + 0.9 * W.thinking) * sp * (rb.k % 2 ? 1 : -1);
      rb.ax += dt * spin * 0.6; rb.ay += dt * spin * (0.8 + 0.12 * rb.k); rb.az += dt * spin * 0.3;
      const E = [[1, 0, 0], [0, 1, 0], [0, 0, 1]].map(v => eul(v, rb.ax, rb.ay, rb.az));
      const N = 50, M = [], Wv = [];
      const fix = v => { v = rotZ(view(cam, ...v), me.rz + rb.k * 0.3 * fan); v[1] *= 1 - fan * (0.58 - 0.1 * Math.sin(t * 4)); v[0] *= 1 + 0.08 * fan; return v; };
      for (let i = 0; i <= N; i++) {
        const u = i / N, th = (u - 0.5) * 3.0;
        let p = add3(add3([0, 0, 0], E[0], 0.8 * Math.cos(th) - 0.12), E[1], 0.78 * Math.sin(th));
        p = add3(p, E[2], bulge * Math.sin(Math.PI * u) + 0.12 * lv * W.speaking * Math.sin(u * 11 - t * 11 + rb.ph));
        p = p.map(x => x * reach); p[1] += 0.08 * moodW.sleepy * Math.sin(Math.PI * u);
        const len = Math.hypot(...p); if (len > 0.9) p = p.map(x => x * 0.9 / len);
        const rad = norm3(add3(p, E[2], -dot3(p, E[2]))), tw = twist * (u - 0.5) * Math.PI + t * 0.5 + rb.ph;
        const w = add3(E[2].map(x => x * Math.cos(tw)), rad, Math.sin(tw)), h = width * Math.pow(Math.sin(Math.PI * u), 1.1) * (1 + 0.06 * moodW.concerned * Math.sin(t * 9 + u * 6));
        const m = fix(p), e = fix(add3(p, w, h)); M.push(m); Wv.push([e[0] - m[0], e[1] - m[1], e[2] - m[2]]);
      }
      for (let i = 0; i < N; i++) {
        const nrm = norm3(cross3([M[i + 1][0] - M[i][0], M[i + 1][1] - M[i][1], M[i + 1][2] - M[i][2]], Wv[i]));
        const u = i / N, f = Math.abs(nrm[2]), [hue, tone] = moment8(pal8(rb.k % 3) + 30 * (u - 0.5) - 30 * W.thinking, M[i][0], M[i][1], M[i][2]);
        for (const [k, a] of [[1, 0.07], [0.8, 0.09], [0.6, 0.12], [0.4, 0.14], [0.2, 0.17]]) Q.push([M[i][2] - k * 0.001, i, M, Wv, k, a, f, Math.sin(Math.PI * u), hue, tone]);
        if (i % 2 === 0) SP.push([M[i], hue, Math.hypot(Wv[i][0], Wv[i][1]) * Math.sin(Math.PI * u)]);
      }
    }
    Q.sort((a, b) => b[0] - a[0]);
    inside8(g, c, R, () => {
      haze8(g, c, R, lv, 1 + 0.25 * W.thinking); core8(g, c, R, t, lv, 0.95);
      if (W.thinking > 0.02) for (let j = 0; j < 3; j++) for (let i = 0; i < 22; i++) { // soft trails orbiting at mid-radius (overlapping glow: no edge)
        const a = t * 2.2 + j * TAU / 3 + i * 0.06; glow8(g, c + Math.cos(a) * R * 0.6, c + Math.sin(a) * R * 0.6, R * 0.13 * bold8(S), pal8(j) - 30, 0.05 * W.thinking * (1 - i / 22)); }
      for (const [z, i, M, Wv, k, a, f, taper, hue, tone] of Q) {
        const fog = Math.max(0.4, Math.min(1, 0.78 - z * 0.55)), al = a * (0.2 + 0.95 * f) * taper * fog * (0.9 + 0.35 * lv) * (1 + 0.3 * W.listening) * (1 - 0.3 * W.thinking);
        g.fillStyle = hsla(hue, 94 - 20 * f ** 8, 50 + 14 * f + 8 * tone, Math.min(1, al));
        const P = [add3(M[i], Wv[i], k), add3(M[i + 1], Wv[i + 1], k), add3(M[i + 1], Wv[i + 1], -k), add3(M[i], Wv[i], -k)];
        g.beginPath(); P.forEach((p, j) => { const [x, y] = scr(c, R, ...p); j ? g.lineTo(x, y) : g.moveTo(x, y); }); g.closePath(); g.fill();
      }
      for (const [m, hue, h] of SP) { const [x, y, , k] = scr(c, R, ...m); glow8(g, x, y, R * (0.06 + 0.5 * h) * k, hue, 0.1 * (0.8 + 0.4 * lv)); }
    });
    bloom8(g, S, 0.6);
    rim8(g, c, R, t, lv, cam);
  }

  // 8.2 Horizon: a band of light across the whole glass in a soft vertical bloom, with its reflection below
  function band8(g, R, ratio, lv, t, alpha, hueA, hueB, white = 1, taper = 0.7) {
    const top = [], bot = [];
    for (let i = 0; i <= 90; i++) {
      const u = -0.97 + i / 90 * 1.94, env = Math.pow(Math.max(0, 1 - u * u), taper);
      const th = R * ratio * env * (1 + 1.2 * lv * W.speaking * (0.5 * Math.abs(Math.sin(u * 7 + t * 10)) + 0.5 * Math.abs(Math.sin(u * 13 - t * 6))));
      const y = R * 0.2 * lv * W.speaking * Math.sin(u * 9 + t * 11) * env + R * (0.3 * moodW.sleepy - 0.3 * moodW.happy) * u * u
        + R * 0.025 * moodW.concerned * Math.sin(u * 40 + t * 30) * env; // sleepy droops, happy smiles, concerned trembles
      top.push([u * R, y - th]); bot.push([u * R, y + th]);
    }
    const gr = g.createLinearGradient(-R, 0, R, 0), mid = white >= 1 ? `rgba(255,255,255,${alpha})` : hsla((hueA + hueB) / 2, 60, 86, alpha);
    gr.addColorStop(0, hsla(hueB, 90, 60, 0)); gr.addColorStop(0.22, hsla(hueB, 90, 64, alpha)); gr.addColorStop(0.5, mid);
    gr.addColorStop(0.78, hsla(hueA, 90, 64, alpha)); gr.addColorStop(1, hsla(hueA, 90, 60, 0));
    g.fillStyle = gr; g.beginPath(); top.forEach(([x, y], i) => i ? g.lineTo(x, y) : g.moveTo(x, y)); for (let i = bot.length - 1; i >= 0; i--) g.lineTo(...bot[i]); g.closePath(); g.fill();
  }
  function g8horizon(g, S, t, lv, me) {
    const sp = cur.speed * st.energy, dt = dtOf(me, t), {c, R} = shell8(g, S, t, lv), cam = cam8(t, sp);
    me.spin = (me.spin || 0) + dt * sp * 2.4 * W.thinking;
    if (W.thinking < 0.5) { const home = Math.round(me.spin / Math.PI) * Math.PI; me.spin += (home - me.spin) * Math.min(1, dt * 2.5); } // settle level again
    const ratio = bold8(S) * spring(me, "ratio", (0.075 + 0.02 * Math.sin(t * 1.2) + 0.2 * W.listening * (0.8 + 0.6 * lv) + 0.02 * moodW.happy * Math.abs(Math.sin(t * 4))) * (1 - 0.35 * moodW.concerned), 0.07);
    const ang = 0.07 * Math.sin(t * 0.45) + me.spin + 0.06 * moodW.sleepy + spring(me, "upright", Math.PI / 2 * W.speaking, 0.06); // it stands up to speak
    const mh = h => { let [hh] = moment8(h, 0, 0, 0.3); if (SIT.success > 0.01) hh = hueTo(hh, 145, SIT.success * 0.85); return hh; };
    const hA = mh(pal8(0)), hB = mh(pal8(1));
    inside8(g, c, R, () => {
      haze8(g, c, R, lv, 0.8);
      g.save(); g.translate(c, c);
      let lowG = g.createRadialGradient(0, R * 0.4, 0, 0, R * 0.4, R * 0.75); // the band's light filling the lower glass
      lowG.addColorStop(0, hsla(hA, 80, 55, 0.2 + 0.1 * lv)); lowG.addColorStop(1, hsla(hB, 80, 45, 0)); g.fillStyle = lowG; g.beginPath(); g.arc(0, R * 0.4, R * 0.75, 0, TAU); g.fill();
      lowG = g.createRadialGradient(0, R * 0.62, 0, 0, R * 0.62, R * 0.5); lowG.addColorStop(0, hsla(hB, 80, 60, 0.18)); lowG.addColorStop(1, hsla(hB, 80, 50, 0)); // a soft pool of reflected light
      g.fillStyle = lowG; g.beginPath(); g.arc(0, R * 0.62, R * 0.5, 0, TAU); g.fill();
      g.rotate(ang);
      g.save(); g.scale(1, 0.42 + 0.3 * W.listening); // the vertical bloom around the band
      let gr = g.createRadialGradient(0, 0, 0, 0, 0, R);
      gr.addColorStop(0, hsla(hA, 80, 64, (0.5 + 0.25 * lv - 0.22 * W.listening + 0.25 * moodW.happy) * (1 - 0.3 * moodW.sleepy))); gr.addColorStop(0.55, hsla(hB, 80, 55, 0.16 + 0.1 * moodW.happy)); gr.addColorStop(1, hsla(hB, 80, 50, 0));
      g.fillStyle = gr; g.beginPath(); g.arc(0, 0, R, 0, TAU); g.fill(); g.restore();
      for (const k of [1, 2]) if (W.thinking > 0.02) { g.save(); g.rotate(k * Math.PI / 3); band8(g, R, ratio * 0.6, lv, t, 0.5 * W.thinking, mh(pal8(k)), mh(pal8(k + 1)), 1, 2.2); g.restore(); } // spokes taper to nothing
      const dim = 1 - 0.35 * moodW.sleepy;
      band8(g, R, ratio, lv, t, (0.85 - 0.45 * W.listening) * dim, hA, hB, 1 - W.listening, 0.7 + 1.5 * W.thinking);
      band8(g, R, ratio * 0.38, lv, t, (0.85 - 0.7 * W.listening) * dim, hA + 15, hB - 15, 1 - W.listening, 0.7 + 1.5 * W.thinking);
      for (const e of [-1, 1]) { gr = g.createRadialGradient(e * R * 0.96, 0, 0, e * R * 0.96, 0, R * 0.22);
        gr.addColorStop(0, hsla(e > 0 ? hA : hB, 90, 74, 0.6)); gr.addColorStop(1, hsla(hA, 90, 60, 0)); g.fillStyle = gr; g.beginPath(); g.arc(e * R * 0.96, 0, R * 0.22, 0, TAU); g.fill(); }
      g.restore();
    });
    bloom8(g, S, 0.55);
    rim8(g, c, R, t, lv, cam);
  }

  // 8.3 Aurora: curtains of light rising from below the middle, one main color and one accent; speech becomes an
  // equalizer centered on the core
  function g8aurora(g, S, t, lv, me) {
    const sp = cur.speed * st.energy, dt = dtOf(me, t), {c, R} = shell8(g, S, t, lv), cam = cam8(t, sp);
    me.ph = (me.ph || 0) + dt * sp * (0.8 + 3.2 * W.thinking);
    const lift = spring(me, "lift", 0.22 * W.listening * (0.6 + lv)), P = [];
    for (let k = 0; k < 3; k++) {
      const z0 = -0.36 + k * 0.36;
      for (let i = 0; i <= 44; i++) {
        const x = -0.86 + i / 44 * 1.72, edge = 1 - Math.min(1, (x * x + z0 * z0) / 0.8) ** 2; if (edge <= 0) continue;
        const y0 = 0.34 + 0.1 * Math.sin(x * 2.2 + me.ph + k * 1.7);
        let h = (0.5 + 0.12 * Math.sin(x * 5 - me.ph * 1.3 + k) * (1 - 0.8 * moodW.sleepy)) * (1 - 0.6 * moodW.sleepy) + 0.8 * W.speaking * spec(x * 3 + k, t, lv) * (1 - 0.6 * Math.abs(x)) + lift * (1 - Math.abs(x));
        h += 0.06 * moodW.concerned * Math.abs(Math.sin(x * 17 + t * 12));
        P.push([view(cam, x, y0, z0), h, edge, k]);
      }
    }
    P.sort((a, b) => b[0][2] - a[0][2]);
    inside8(g, c, R, () => {
      haze8(g, c, R, lv, 0.9); core8(g, c, R, t, lv, 0.55);
      for (const [v, h, edge, k] of P) {
        const [sx, sy, z, kk] = scr(c, R, ...v), fog = Math.max(0.4, Math.min(1, 0.8 - z * 0.6)), hh = R * h * kk;
        let [hue, tone] = moment8((k === 2 ? pal8(1, 0.5) : pal8(0, 0.3) + 12 * k) + 40 * W.thinking * Math.sin(t * 1.4 + k), v[0], v[1], z);
        const w = R * 0.08 * kk * (1 + 1.6 * moodW.sleepy), a = Math.min(1, 0.26 * edge * fog * (0.9 + 0.4 * lv) * (1 + 0.4 * W.listening) + 0.1 * tone);
        g.globalAlpha = a; g.drawImage(sprite8(hue), sx - w, sy - hh * 1.05, 2 * w, hh * 1.4);
        g.globalAlpha = a * 0.55; g.drawImage(sprite8(hue + 35), sx - w * 0.7, sy - hh * 1.5, 1.4 * w, hh * 1.1);
        if (W.speaking > 0.05) { g.globalAlpha = Math.min(1, a * 1.4 * W.speaking); g.drawImage(sprite8(hue - 10), sx - w * 0.3, sy - hh * 0.95, 0.6 * w, hh * 1.1); } // a crisp luminous core in each ray
      }
      g.globalAlpha = 1;
    });
    bloom8(g, S, 0.6);
    rim8(g, c, R, t, lv, cam);
  }

  // 8.4 Liquid: a drop of liquid light built only from glow (no edge you can trace); lobes swell with speech, drops
  // circle each other to think, a halo breathes out to the rim to listen
  function drop8(g, x, y, rb, t, lv, hue, seed, a) { // glow only: a soft body, a swirl of two colors inside, a small warm heart
    glow8(g, x, y, rb * 1.8, hue, 0.3 * a);
    for (let i = 0; i < 12; i++) {
      const th = i / 12 * TAU + t * 0.5 + seed, wob = 1 + 0.12 * Math.sin(3 * th + t * 1.4 + seed) + 0.65 * W.speaking * spec(th * 1.5 + seed, t, lv) + 0.08 * moodW.concerned * Math.sin(11 * th + t * 14);
      const sw = 0.25 + 0.3 * (0.5 + 0.5 * Math.sin(th * 2 - t * 1.3)); // a two-armed swirl of color inside the drop
      glow8(g, x + Math.cos(th) * rb * sw * wob, y + Math.sin(th) * rb * sw * wob, rb * 0.6, i % 2 ? hue : pal8(1, 0.5) + (hue - cur.hue), 0.22 * a);
    }
    const gr = g.createRadialGradient(x, y, 0, x, y, rb * 0.4);
    gr.addColorStop(0, hsla(hue, 50, 88, 0.4 * a)); gr.addColorStop(1, hsla(hue, 80, 70, 0)); g.fillStyle = gr; g.beginPath(); g.arc(x, y, rb * 0.4, 0, TAU); g.fill();
  }
  function g8liquid(g, S, t, lv, me) {
    const sp = cur.speed * st.energy, dt = dtOf(me, t), {c, R} = shell8(g, S, t, lv), cam = cam8(t, sp);
    me.orb = (me.orb || 0) + dt * sp * (0.4 + 3.0 * W.thinking);
    const d = spring(me, "d", 0.1 + 0.3 * W.thinking - 0.06 * W.listening), size = spring(me, "sz", (0.62 - 0.18 * W.thinking - 0.24 * W.listening + 0.04 * moodW.happy * Math.abs(Math.sin(t * 4))) * (1 + 0.14 * lv * W.speaking));
    inside8(g, c, R, () => {
      haze8(g, c, R, lv);
      if (W.listening > 0.01) { const beat = 0.5 + 0.5 * Math.sin(t * 5.5); ring8(g, c, R * (0.55 + 0.25 * beat + 0.12 * lv), pal8(0), 0.5 * W.listening * (0.6 + 0.6 * beat), R); }
      if (W.speaking > 0.02) for (let i = 0; i < 5; i++) { const a = i / 5 * TAU + t * 0.6, r = R * (0.45 + 0.4 * lv * spec(a * 2, t, lv) / Math.max(0.1, lv)); // lobes reaching out with the voice
        glow8(g, c + Math.cos(a) * r * 0.85, c + Math.sin(a) * r * 0.85, R * (0.32 + 0.15 * lv), pal8(i % 2), 0.26 * W.speaking * (0.5 + lv)); }
      const B = [0, 1, 2].map(k => { const a = me.orb + k * TAU / 3, p = view(cam, Math.cos(a) * d, 0.12 * Math.sin(a * 2 + t) * d, Math.sin(a) * d); return [p, k]; });
      B.sort((a, b) => b[0][2] - a[0][2]);
      for (const [p, k] of B) { const [x, y, z, kk] = scr(c, R, ...p), [hue, tone] = moment8(pal8(k), p[0], p[1], z);
        drop8(g, x, y + R * 0.05 * moodW.sleepy, R * size * kk * (k ? 0.8 : 1), t, lv, hue, k * 2.1, Math.min(1, (0.75 + 0.3 * lv + 0.2 * tone) * Math.max(0.6, 0.9 - z * 0.5)) * (k ? Math.max(W.thinking, 0.25) : 1)); }
    });
    bloom8(g, S, 0.6);
    rim8(g, c, R, t, lv, cam);
  }

  // 8.5 Plasma: soft ribbons of energy with a thin hot spine, two or three colors, far strands dim
  function g8plasma(g, S, t, lv, me) {
    const sp = cur.speed * st.energy, dt = dtOf(me, t), {c, R} = shell8(g, S, t, lv), cam = cam8(t, sp);
    if (!me.lp) me.lp = Array.from({length: 4}, (_, k) => ({k, a: k * 1.2, b: k * 2.1, cc: k * 0.6, ph: k * 1.4}));
    const pts = [], spines = []; me.tr = (me.tr || 0) + dt * sp * 3.2 * W.thinking;
    for (const L of me.lp) {
      const spin = (0.4 + 1.9 * W.thinking) * sp * (L.k % 2 ? 1 : -1);
      L.a += dt * spin * 0.6; L.b += dt * spin; L.cc += dt * spin * 0.3;
      const face = spring(L, "face", W.listening, 0.05), shrink = spring(L, "sh", 1 - 0.3 * W.listening * (0.8 + 0.2 * Math.sin(t * 6 + L.k))), amp = spring(L, "amp", 0.2 * lv * W.speaking), surge = spring(L, "surge", 1 + 0.28 * lv * W.speaking);
      const nrm = view(cam, ...eul([0, 0, 1], L.a * (1 - face), L.b * (1 - face), L.cc)), side = 0.25 + 0.75 * Math.abs(nrm[2]); // loops seen edge-on fade
      const hue = pal8(L.k % 2, 0.45), loop = [];
      for (let i = 0; i < 72; i++) {
        const th = i / 72 * TAU, r = shrink * surge * (0.6 + 0.1 * Math.sin(3 * th + t * 0.9 + L.ph) + 0.07 * Math.sin(5 * th - t * 1.2) + amp * Math.sin(4 * th + t * 9 + L.k) + 0.04 * moodW.concerned * Math.sin(17 * th + t * 12));
        let p = eul([Math.cos(th) * r, Math.sin(th) * r, 0], L.a * (1 - face), L.b * (1 - face), L.cc); p[1] += 0.06 * moodW.sleepy;
        if (W.thinking > 0.01) { const tr = me.tr || 0, x0 = p[0] * Math.cos(tr) - p[2] * Math.sin(tr), z0 = p[0] * Math.sin(tr) + p[2] * Math.cos(tr); // a flat disc, turning fast
          p = [p[0] + (x0 - p[0]) * W.thinking, p[1] * (1 - 0.82 * W.thinking), p[2] + (z0 - p[2]) * W.thinking]; }
        const v = view(cam, ...p); pts.push([v, hue, side]); loop.push(v);
      }
      spines.push([loop, hue, side]);
    }
    pts.sort((a, b) => b[0][2] - a[0][2]);
    inside8(g, c, R, () => {
      haze8(g, c, R, lv); core8(g, c, R, t, lv, 0.75);
      for (const [v, h0, side] of pts) {
        const [x, y, z, k] = scr(c, R, ...v), fog = Math.max(0.25, Math.min(1, 0.78 - z * 0.7)), [hue, tone] = moment8(h0, v[0], v[1], z);
        glow8(g, x, y, R * 0.17 * k * bold8(S), hue, (0.1 + 0.05 * tone) * fog * side * (0.85 + 0.5 * lv));
      }
      g.lineJoin = g.lineCap = "round"; // a thin hot spine along each loop, continuous (no beads)
      for (const [loop, hue, side] of spines) { g.strokeStyle = hsla(hue, 55, 85, 0.2 * side * (0.8 + 0.4 * lv) * (1 - 0.6 * W.speaking)); g.lineWidth = Math.max(1, R * 0.007);
        g.beginPath(); loop.forEach((v, i) => { const [x, y] = scr(c, R, ...v); i ? g.lineTo(x, y) : g.moveTo(x, y); }); g.closePath(); g.stroke(); }
    });
    bloom8(g, S, 0.6);
    rim8(g, c, R, t, lv, cam);
  }

  // 8.6 Nebula: a smooth glowing cloud in close colors; it gathers into a bright pulsing core to listen, pushes
  // bright lobes out toward the rim to speak, and winds into soft turning arms to think
  function g8nebula(g, S, t, lv, me) {
    const sp = cur.speed * st.energy, dt = dtOf(me, t), {c, R} = shell8(g, S, t, lv), cam = cam8(t, sp);
    if (!me.pc) me.pc = Array.from({length: 130}, (_, i) => { const u = Math.random() * 2 - 1, a = Math.random() * TAU, r = Math.cbrt(Math.random()) * 0.74, s = Math.sqrt(1 - u * u);
      return {p: [Math.cos(a) * s * r, u * r, Math.sin(a) * s * r], i, cl: i % 3, sz: 0.24 + Math.random() * 0.18, ph: Math.random() * TAU, w: null}; });
    me.spin = (me.spin || 0) + dt * sp * (0.3 + 2.2 * W.thinking);
    const flow = (0.45 + 0.5 * W.thinking) * sp, P = [], lobeA = t * 0.4;
    for (const q of me.pc) {
      let [x, y, z] = q.p; const a = dt * flow * (1.2 - Math.hypot(x, z));
      [x, z] = [x * Math.cos(a) - z * Math.sin(a), x * Math.sin(a) + z * Math.cos(a)]; y += dt * 0.1 * Math.sin(t * 0.6 + q.ph);
      const r0 = Math.hypot(x, y, z); if (r0 > 0.76) { x *= 0.76 / r0; y *= 0.76 / r0; z *= 0.76 / r0; } q.p = [x, y, z];
      const s = q.i / 130, arm = q.i % 2, sa = s * 6.5 + arm * Math.PI + me.spin, sr = 0.08 + 0.66 * s;
      let tgt = [x + (Math.cos(sa) * sr - x) * W.thinking, y * (1 - 0.55 * W.thinking), z + (Math.sin(sa) * sr - z) * W.thinking];
      const gather = 1 - 0.6 * W.listening * (0.85 + 0.15 * Math.sin(t * 5.5));
      const ang = Math.atan2(tgt[1], tgt[0]), lobe = Math.max(0, Math.cos(2 * (ang - lobeA))) ** 4, push = 1 + 2.2 * lv * W.speaking * lobe * (0.55 + 0.45 * Math.sin(t * 9 + q.ph));
      tgt = tgt.map(v => v * gather * push);
      if (!q.w) q.w = tgt.slice(); for (let j = 0; j < 3; j++) q.w[j] += (tgt[j] - q.w[j]) * 0.12;
      P.push([view(cam, q.w[0], q.w[1] + 0.06 * moodW.sleepy, q.w[2]), q, Math.hypot(...q.w)]);
    }
    P.sort((a, b) => b[0][2] - a[0][2]);
    inside8(g, c, R, () => {
      haze8(g, c, R, lv); core8(g, c, R, t, lv, 0.9 + 0.25 * W.listening);
      if (W.listening > 0.01) ring8(g, c, R * (0.62 + 0.12 * Math.sin(t * 5.5) + 0.12 * lv), pal8(0), 0.45 * W.listening, R); // a breathing halo
      for (const [v, q, r] of P) {
        const [x, y, z, k] = scr(c, R, ...v), fog = Math.max(0.4, Math.min(1, 0.8 - z * 0.6));
        let [hue, tone] = moment8(cur.hue + [0, 30, -26][q.cl] * (1 - 0.8 * (1 - moodW.calm)) + (q.i % 2 ? 45 : -20) * W.thinking, v[0], v[1], z); // the two arms take two colors
        const s = R * q.sz * k * (1 + 0.25 * lv * W.speaking) * (1 + 0.2 * moodW.concerned * Math.abs(Math.sin(t * 11 + q.ph)));
        glow8(g, x, y, s, hue, (0.16 + 0.08 * lv + 0.12 * tone) * fog * Math.pow(Math.max(0, 1 - r / 0.95), 1.2) * (1 - 0.2 * W.listening - 0.45 * W.thinking) * 1.35);
      }
    });
    bloom8(g, S, 0.55);
    rim8(g, c, R, t, lv, cam);
  }

  const DRAW = {ribbons: g8ribbons, horizon: g8horizon, plasma: g8plasma, liquid: g8liquid, nebula: g8nebula};
  window.ThetaOrb8 = {
    styles: Object.keys(DRAW),
    // one frame for one orb: its states come from orb.sw (eased), its color from its look
    draw(orb, g, style, t, lv) {
      const fn = DRAW[style]; if (!fn) return false;
      const L = orb._L(), sw = orb.sw || {};
      cur.hue = L.hue; cur.sat = L.sat; cur.light = L.light;
      const busy = Math.min(1, (sw.thinking || 0) + (sw.speaking || 0) + (sw.waiting || 0));
      W = {idle: 1 - busy, listening: sw.waiting || 0, thinking: sw.thinking || 0, speaking: sw.speaking || 0};
      const S = Math.min(orb.W, orb.H); OX = (orb.W - S) / 2; OY = (orb.H - S) / 2;
      orb._g8 = orb._g8 || {}; const me = orb._g8[style] || (orb._g8[style] = {});
      g.clearRect(0, 0, orb.W, orb.H);
      fn(g, S, t, Math.max(lv, 0.35 * (sw.speaking || 0) * (0.6 + 0.4 * Math.abs(Math.sin(t * 9)))), me);
      g.setTransform(1, 0, 0, 1, 0, 0); g.globalCompositeOperation = "source-over";
      return true;
    },
  };
})();
