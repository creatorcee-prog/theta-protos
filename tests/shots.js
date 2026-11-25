// Screenshots and smoke checks for the phone app (web/), in demo mode, at iPhone 14 size.
//   node tests/shots.js                     # shots go to $SHOTS_DIR, default <tmp>/protos-shots
// Serves web/ with `python3 -m http.server`, opens /?demo=1, walks splash -> home -> chat (working, mid-stream, done,
// a proactive text) -> Connect apps -> Settings, then the login screen (a 401 from a mocked API) and a markdown
// safety check. Exits 1 on any console error, page error or failed check.
const {chromium, devices} = require("playwright");
const {spawn} = require("child_process");
const path = require("path");
const fs = require("fs");
const os = require("os");
const net = require("net");

const ROOT = path.resolve(__dirname, "..");
const OUT = process.env.SHOTS_DIR || path.join(os.tmpdir(), "protos-shots");
fs.mkdirSync(OUT, {recursive: true});

const freePort = () => new Promise(res => { const s = net.createServer(); s.listen(0, () => { const p = s.address().port; s.close(() => res(p)); }); });
const sleep = ms => new Promise(r => setTimeout(r, ms));
const problems = [];
const check = (ok, what) => { console.log((ok ? "ok   " : "FAIL ") + what); if (!ok) problems.push(what); };

async function waitUp(url) {
  for (let i = 0; i < 50; i++) { try { const r = await fetch(url); if (r.ok) return; } catch (e) {} await sleep(100); }
  throw new Error("server didn't start");
}

(async () => {
  const port = await freePort();
  const srv = spawn("python3", ["-m", "http.server", String(port), "--bind", "127.0.0.1"], {cwd: path.join(ROOT, "web"), stdio: "ignore"});
  const base = `http://127.0.0.1:${port}`;
  let browser;
  try {
    await waitUp(base + "/");
    browser = await chromium.launch();
    const ctx = await browser.newContext({...devices["iPhone 14"], serviceWorkers: "allow"});
    const page = await ctx.newPage();
    const errors = [];
    page.on("console", m => { if (m.type() === "error") errors.push(m.text()); });
    page.on("pageerror", e => errors.push(String(e)));
    page.on("requestfailed", r => { if (!/\/api\//.test(r.url())) errors.push("request failed: " + r.url()); });
    const shot = async name => {
      const f = path.join(OUT, name + ".png"); await page.screenshot({path: f}); console.log("shot " + f);
      // nothing may stick out sideways (the filter chips scroll on purpose)
      const wide = await page.evaluate(() => [...document.querySelectorAll("#app *")].filter(e => {
        if (e.closest(".chips") || !e.getClientRects().length) return false;
        const r = e.getBoundingClientRect(); return r.width && (r.right > innerWidth + 1 || r.left < -1);
      }).map(e => e.tagName.toLowerCase() + (e.id ? "#" + e.id : "") + (e.className && e.className.baseVal === undefined ? "." + String(e.className).split(" ")[0] : "")).slice(0, 5));
      check(wide.length === 0, name + ": no horizontal overflow" + (wide.length ? ": " + wide.join(", ") : ""));
    };

    await page.goto(base + "/?demo=1");
    await sleep(1300);
    await shot("01-splash");
    await page.waitForSelector("#home:not([hidden])", {timeout: 8000});
    await page.waitForSelector("#splash", {state: "hidden", timeout: 3000});
    await sleep(500);
    await shot("02-home");
    check(await page.isVisible("#home-orb"), "home shows Theta's globe");

    // chat: history, then a message that gets a long, streamed reply
    await page.click("#home-bot");
    await page.waitForSelector("#chat:not([hidden])");
    await sleep(400);
    check((await page.$$("#thread .msg")).length >= 4, "history loaded");
    await page.fill("#c-text", "Should I buy the new camera now or wait? Compare it for me");
    await page.click("#c-send");
    await page.waitForSelector("#thread .pending-orb", {timeout: 2000});
    check(await page.$("#thread .typing") === null, "no three-dot typing indicator");
    check(await page.evaluate(() => [...document.querySelectorAll("#thread .msg.u")].some(e => e.textContent.startsWith("Should I buy"))), "user bubble shown at once");
    await sleep(500);
    await shot("03-chat-working");
    await page.waitForSelector("#thread .msg.a.streaming", {timeout: 6000});
    await sleep(500);
    await shot("04-chat-mid-stream");
    await page.waitForFunction(() => !window.ThetaApp.state.streaming, null, {timeout: 15000});
    await sleep(700);
    await shot("05-chat-done");
    const last = await page.evaluate(() => { const e = [...document.querySelectorAll("#thread .msg.a")].find(x => x.textContent.startsWith("Short answer"));
      return e ? {bold: !!e.querySelector("strong"), list: !!e.querySelector("ul li"), id: e.dataset.id} : {}; });
    check(last.bold && last.list, "reply renders bold and bullets");
    check(!!last.id, "reply reconciled with the stored message id");

    // a short reply lands whole (never streams)
    await page.fill("#c-text", "hey");
    await page.click("#c-send");
    const streamedShort = await page.waitForSelector("#thread .msg.a.streaming", {timeout: 1500}).then(() => true).catch(() => false);
    await page.waitForFunction(() => !window.ThetaApp.state.streaming, null, {timeout: 8000});
    check(!streamedShort, "a short reply appears whole");

    // the proactive text arrives about 8 s in, with choices
    await page.waitForSelector("#thread .actions .act", {timeout: 14000});
    await sleep(1400);
    await shot("06-chat-proactive");
    check((await page.$$("#thread .actions .act")).length >= 2, "proactive offer shows choice chips");

    // the route hint (long-press; right-click in a desktop browser)
    const hey = await page.evaluateHandle(() => { const m = [...document.querySelectorAll("#thread .msg.a[data-id]")].find(e => e.textContent.startsWith("Hey.")); m.scrollIntoView({block: "center"}); return m; });
    await sleep(300);
    await hey.asElement().click({button: "right"});
    await sleep(250);
    const hint = await page.$eval("#hint", e => (e.hidden ? "" : e.textContent));
    check(/Answered by|texted first/.test(hint), "long-press shows which model answered: " + hint.replace(/\s+/g, " ").slice(0, 60));
    await shot("07-chat-route-hint");
    await page.mouse.click(5, 400);

    // Connect apps
    await page.click("#chat-more");
    await page.click('#menu [data-act="connect"]');
    await page.waitForSelector("#connect .app-row", {timeout: 4000});
    await sleep(450);
    await shot("08-connect-apps");
    check(/\d+ connected/.test(await page.textContent("#connect-count")), "Connect apps shows the connected count");
    await page.click("#connect [data-close]");
    await page.waitForSelector("#connect", {state: "hidden"});

    // Settings, from the avatar button on home
    await page.click("#chat-back");
    await page.waitForSelector("#home:not([hidden])");
    await page.click("#home-me");
    await page.waitForSelector("#settings:not([hidden])");
    await sleep(500);
    await shot("09-settings");
    check((await page.textContent("#set-loc-note")).includes("10 km"), "location note says rounded to about 10 km");

    // markdown is built safely
    const safe = await page.evaluate(() => {
      const d = document.createElement("div");
      d.append(window.ThetaApp.md("<img src=x onerror=alert(1)> [a](javascript:alert(1)) [b](http://x.test) [c](https://ok.test) **bold** `code`\n1. one\n2. two"));
      return {img: !!d.querySelector("img"), links: [...d.querySelectorAll("a")].map(a => a.href), strong: !!d.querySelector("strong"), code: !!d.querySelector("code"), ol: d.querySelectorAll("ol li").length};
    });
    check(!safe.img && safe.links.length === 1 && safe.links[0] === "https://ok.test/" && safe.strong && safe.code && safe.ol === 2, "markdown: no raw HTML, https links only");

    check(errors.length === 0, "no console errors" + (errors.length ? ": " + errors.join(" | ") : ""));

    // the login screen: a real (mocked) API that answers 401
    const p2 = await ctx.newPage();
    const e2 = []; p2.on("pageerror", e => e2.push(String(e)));
    await p2.route("**/api/**", route => {
      const u = new URL(route.request().url());
      if (u.pathname === "/api/health") return route.fulfill({json: {ok: true, version: "0.test"}});
      if (u.pathname === "/api/login") return route.fulfill({status: 401, json: {error: "bad key"}});
      return route.fulfill({status: 401, json: {error: "sign in"}});
    });
    await p2.goto(base + "/");
    await p2.waitForSelector("#login:not([hidden])", {timeout: 8000});
    await sleep(500);
    await p2.fill("#login-key", "wrong");
    await p2.click("#login-form button");
    await p2.waitForFunction(() => document.getElementById("login-err").textContent.length > 0);
    const f = path.join(OUT, "10-login.png"); await p2.screenshot({path: f}); console.log("shot " + f);
    check(e2.length === 0, "login page has no errors" + (e2.length ? ": " + e2.join(" | ") : ""));
  } catch (e) {
    problems.push(String(e && e.stack || e));
    console.error(e);
  } finally {
    if (browser) await browser.close();
    srv.kill();
  }
  console.log(problems.length ? `\n${problems.length} problem(s)` : "\nall good");
  process.exit(problems.length ? 1 : 0);
})();
