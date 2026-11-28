// contact sheets: for each avatar, idle/listening/thinking/speaking (3 frames each, 0.3 s apart), moods, moments, small size
const {chromium} = require("playwright"); const fs = require("fs");
const CODES = (process.argv[2] || "7.2,8.1,8.2,8.4,8.5,8.6").split(",");
const OUT = process.argv[3] || __dirname + "/sheets";
(async () => {
  fs.mkdirSync(OUT, {recursive: true});
  const b = await chromium.launch(); const p = await b.newPage({viewport: {width: 1300, height: 1000}});
  const errs = []; p.on("pageerror", e => errs.push(e.message));
  // draw only the avatars on the sheets: with all ~20 drawing, the page ran at about 7 fps, so the clock (which caps a
  // frame at 0.05 s) ran at a third of real time: frames "0.3 s apart" showed 0.1 s of motion, and moods were caught
  // mid-fade (concerned still magenta)
  await p.goto("file://" + __dirname + "/avatar-lab.html?only=" + CODES.join(",")); await p.waitForTimeout(1200);
  const fps = await p.evaluate(() => new Promise(r => { let n = 0; const t0 = performance.now(); const f = () => { n++; if (performance.now() - t0 < 1000) requestAnimationFrame(f); else r(n); }; requestAnimationFrame(f); }));
  console.log("frames per second while recording:", fps, fps < 20 ? "(low: motion and fades will look slower than real)" : "");
  const grab = () => p.evaluate(codes => Object.fromEntries(codes.map(code => { const card = [...document.querySelectorAll(".spec")].find(s => s.querySelector(".code").textContent === code);
    return [code, {big: card.querySelector("canvas").toDataURL("image/png"), small: card.querySelector("canvas.small").toDataURL("image/png")}]; })), CODES);
  const tiles = Object.fromEntries(CODES.map(c => [c, []]));
  const shoot = async label => { const g = await grab(); for (const c of CODES) tiles[c].push([label, g[c].big]); return g; };
  const click = sel => p.click(sel);
  for (const state of ["idle", "listening", "thinking", "speaking"]) {
    await click(`[data-state="${state}"]`); await p.waitForTimeout(1600);
    for (let i = 0; i < 3; i++) { await shoot(`${state} ${i + 1}`); await p.waitForTimeout(300); }
  }
  await click('[data-state="idle"]');
  for (const mood of ["concerned", "sleepy", "happy"]) { await click(`[data-mood="${mood}"]`); await p.waitForTimeout(2200); await shoot("mood: " + mood); }
  await click('[data-mood="calm"]'); await p.waitForTimeout(1500);
  for (const [sit, ms] of [["success", 900], ["alert", 1200], ["working", 2200]]) { await click(`[data-sit="${sit}"]`); await p.waitForTimeout(ms); await shoot("moment: " + sit); }
  await click('[data-sit="none"]'); await click('[data-state="speaking"]'); await p.waitForTimeout(1500);
  const sm = await grab();
  for (const code of CODES) {
    const data = await p.evaluate(async ([code, list, small]) => {
      const T = 220, cols = 6, rows = Math.ceil(list.length / cols) + 1, cv = document.createElement("canvas"); cv.width = cols * T; cv.height = rows * (T + 22) + 30;
      const g = cv.getContext("2d"); g.fillStyle = "#111"; g.fillRect(0, 0, cv.width, cv.height); g.fillStyle = "#fff"; g.font = "bold 18px sans-serif"; g.fillText("Avatar " + code, 10, 22);
      const load = src => new Promise(r => { const i = new Image(); i.onload = () => r(i); i.src = src; });
      for (let k = 0; k < list.length; k++) { const [label, src] = list[k], x = (k % cols) * T, y = 30 + Math.floor(k / cols) * (T + 22);
        g.drawImage(await load(src), x + 2, y, T - 4, T - 4); g.fillStyle = "#ccc"; g.font = "13px sans-serif"; g.fillText(label, x + 6, y + T + 14); }
      const y = 30 + Math.ceil(list.length / cols) * (T + 22), im = await load(small);
      g.drawImage(im, 10, y + 40, 72, 72); g.drawImage(im, 100, y + 20, 112, 112); g.fillStyle = "#ccc"; g.fillText("chat size (speaking): 72 px and 112 px", 230, y + 80);
      return cv.toDataURL("image/png");
    }, [code, tiles[code], sm[code].small]);
    fs.writeFileSync(`${OUT}/sheet-${code}.png`, Buffer.from(data.split(",")[1], "base64"));
  }
  console.log("errors:", errs.slice(0, 5)); await b.close();
})();
