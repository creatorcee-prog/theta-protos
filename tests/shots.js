// Screenshots and smoke checks for the phone app (web/), in demo mode, at iPhone 14 size.
//   node tests/shots.js                     # shots go to $SHOTS_DIR, default <tmp>/protos-shots
// Serves web/ with `python3 -m http.server`, opens /?demo=1, walks splash -> home -> chat (working, mid-stream, done,
// a proactive text) -> message actions (the action bar, copy, dislike reasons, source pills, editing) -> Connect apps
// -> Settings, then the login screen (a 401 from a mocked API), a markdown safety check and the "..." button on a
// desktop-sized page. Exits 1 on any console error, page error or failed check.
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
    await ctx.grantPermissions(["clipboard-read", "clipboard-write"], {origin: base});
    const page = await ctx.newPage();
    const errors = [];
    page.on("console", m => { if (m.type() === "error") errors.push(m.text()); });
    page.on("pageerror", e => errors.push(String(e)));
    page.on("requestfailed", r => { if (!/\/api\//.test(r.url())) errors.push("request failed: " + r.url()); });
    const shot = async name => {
      const f = path.join(OUT, name + ".png"); await page.screenshot({path: f}); console.log("shot " + f);
      // nothing may stick out sideways (the filter chips scroll on purpose)
      const wide = await page.evaluate(() => [...document.querySelectorAll("#app *")].filter(e => {
        if (e.closest(".chips, .chp-row, .hf-stack, .hf-row") || !e.getClientRects().length) return false;
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
    { // the message box is one row: [+] [text] [mic] [send] (a 0.4 change once wrapped them onto separate lines)
      const r = await page.evaluate(() => ["c-plus", "c-text", "c-mic", "c-send"].map(id => document.getElementById(id).getBoundingClientRect()).map(b => ({bottom: b.bottom, left: b.left})));
      const sameRow = r.every(b => Math.abs(b.bottom - r[3].bottom) < 14), ordered = r[0].left < r[1].left && r[1].left < r[2].left && r[2].left < r[3].left;
      check(sameRow && ordered, "message box: +, text, mic and send sit on one row");
    }
    await page.waitForSelector(".chp-row .chp-pill", {timeout: 12000}).catch(() => {});
    check((await page.$$(".chp-row .chp-pill")).length >= 5 && await page.isVisible(".chp-row"), "the chips row shows above the empty chat box");
    await shot("02b-chat-chips");
    const usage0 = (await page.$$("#thread .usage .u-txt")).length;
    check(usage0 >= 2, "history replies show their token use");
    await page.fill("#c-text", "Should I buy the new camera now or wait? Compare it for me");
    check(await page.isHidden(".chp-row"), "the chips row hides while you type");
    await page.click("#c-send");
    await page.waitForSelector("#thread .pending-orb", {timeout: 2000});
    check(await page.$("#thread .typing") === null, "no three-dot typing indicator");
    check(await page.evaluate(() => [...document.querySelectorAll("#thread .msg.u")].some(e => e.textContent.startsWith("Should I buy"))), "user bubble shown at once");
    await sleep(500);
    await shot("03-chat-working");
    await page.waitForSelector("#thread .msg.a.streaming", {timeout: 6000});
    const usageMid = await page.evaluate(() => { const s = document.querySelector("#thread .msg.a.streaming"); return s ? {streaming: true, line: !!(s.nextElementSibling && s.nextElementSibling.matches(".usage")) || !!s.querySelector(".usage")} : {streaming: false}; });
    check(usageMid.streaming && !usageMid.line, "no token line while the reply streams");
    await sleep(500);
    await shot("04-chat-mid-stream");
    await page.waitForFunction(() => !window.ThetaApp.state.streaming, null, {timeout: 15000});
    await sleep(700);
    await shot("05-chat-done");
    const last = await page.evaluate(() => { const e = [...document.querySelectorAll("#thread .msg.a")].find(x => x.textContent.startsWith("Short answer"));
      return e ? {bold: !!e.querySelector("strong"), list: !!e.querySelector("ul li"), id: e.dataset.id} : {}; });
    check(last.bold && last.list, "reply renders bold and bullets");
    check(!!last.id, "reply reconciled with the stored message id");
    const useLine = await page.evaluate(id => { const r = document.querySelector(`[data-key="m${id}"] .usage .u-txt`); return r ? r.textContent : ""; }, last.id);
    check(/^[\d,]+ in · [\d,]+ out · \$0\.\d{4}$/.test(useLine), "token line under the finished reply: " + useLine);
    await page.evaluate(id => document.querySelector(`[data-key="m${id}"] .usage`).scrollIntoView({block: "center"}), last.id);
    await sleep(200);
    await shot("05b-token-line");

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

    // the action bar (long-press; right-click in a desktop browser): Copy, Copy with prompt, Like, Dislike + the Model line
    const openBarOn = async pred => {
      const h = await page.evaluateHandle(pred);
      await h.asElement().evaluate(e => e.scrollIntoView({block: "center"})); await sleep(250); // above the composer, as a person would
      const bb = await h.asElement().boundingBox();
      await h.asElement().click({button: "right", position: {x: 8, y: bb.height / 2}}); await sleep(250); // the padding, not a link
      return page.$eval("#msgbar", e => (e.hidden ? null : {text: e.textContent, labels: [...e.querySelectorAll(".mb-acts button")].map(b => b.getAttribute("aria-label"))}));
    };
    const heyReply = () => { const m = [...document.querySelectorAll("#thread .msg.a[data-id]")].find(e => e.textContent.startsWith("Hey.")); m.scrollIntoView({block: "center"}); return m; };
    let barNow = await openBarOn(heyReply);
    check(!!barNow && ["Copy", "Copy with prompt", "Like", "Dislike"].every(l => barNow.labels.includes(l)), "action bar on a reply: " + (barNow ? barNow.labels.join(", ") : "not shown"));
    check(!!barNow && /Model: deepseek-chat/.test(barNow.text), "the bar's Model line says which model answered: " + (barNow ? barNow.text.replace(/\s+/g, " ").slice(-70) : ""));
    await shot("07-chat-action-bar");
    await page.click('#msgbar [aria-label="Copy with prompt"]');
    await page.waitForFunction(() => !document.getElementById("toast").hidden && document.getElementById("toast").textContent === "Copied", null, {timeout: 2000});
    const clip = await page.evaluate(() => navigator.clipboard.readText());
    check(clip === "You: hey\n\nTheta: Hey. Quiet day so far. What are we working on?", "Copy with prompt puts You/Theta on the clipboard: " + JSON.stringify(clip).slice(0, 80));
    check(await page.$eval("#msgbar", e => e.hidden), "the bar closes after Copy");
    barNow = await openBarOn(heyReply);
    await page.keyboard.press("Escape");
    check(await page.$eval("#msgbar", e => e.hidden), "Escape closes the action bar");

    // dislike: one tap records it, then "What was off?" chips
    await openBarOn(heyReply);
    await page.click('#msgbar [aria-label="Dislike"]');
    await page.waitForSelector("#msgbar .mb-chip");
    const chips = await page.$$eval("#msgbar .mb-chip", e => e.map(x => x.textContent));
    check(chips.join("|") === "Too long|Wrong|Not what I asked|Tone", "dislike asks what was off: " + chips.join(", "));
    await shot("08-dislike-reasons");
    await page.click("#msgbar .mb-chip >> text=Too long");
    await sleep(500);
    check(await page.evaluate(() => [...document.querySelectorAll("#thread .msg.a")].find(e => e.textContent.startsWith("Hey.")).closest(".item").querySelector(".voted.down") !== null), "the reply shows it was disliked");

    // sources: [n] citations become domain pills, plus a Sources row
    await page.fill("#c-text", "What's the latest news today?");
    await page.click("#c-send");
    await page.waitForFunction(() => !window.ThetaApp.state.streaming, null, {timeout: 15000});
    await sleep(600);
    const cites = await page.evaluate(() => {
      const it = [...document.querySelectorAll("#thread .item")].pop(), a = [...it.querySelectorAll(".msg a.cite")];
      return {inline: a.map(x => x.textContent), ok: a.every(x => x.href.startsWith("https://") && x.target === "_blank" && /noopener/.test(x.rel)),
        row: [...it.querySelectorAll(".srcs a.cite")].map(x => x.textContent), raw: /\[\d\]/.test(it.querySelector(".msg").textContent)};
    });
    check(cites.inline.join(",") === "weather.gov,cotrip.org,reuters.com" && cites.ok && !cites.raw, "citations render as https pills by the claim: " + cites.inline.join(", "));
    check(cites.row.length === 3, "a Sources row under the reply");
    await shot("09-source-pills");
    barNow = await openBarOn(() => { const m = [...document.querySelectorAll("#thread .msg.a[data-id]")].pop(); m.scrollIntoView({block: "center"}); return m; });
    check(!!barNow && barNow.labels.some(l => /^Sources/.test(l)), "the bar offers Sources when there are some");
    await page.click('#msgbar [aria-label^="Sources"]');
    await sleep(200);
    check((await page.$$("#msgbar .mb-src")).length === 3, "Sources lists every source");
    await shot("09b-sources-in-bar");
    await page.keyboard.press("Escape");

    // edit your last message: only the latest one offers Edit
    barNow = await openBarOn(() => { const m = [...document.querySelectorAll("#thread .msg.u[data-id]")][0]; m.scrollIntoView({block: "center"}); return m; });
    check(!!barNow && !barNow.labels.includes("Edit message"), "an older message has no Edit");
    await page.keyboard.press("Escape");
    barNow = await openBarOn(() => { const m = [...document.querySelectorAll("#thread .msg.u[data-id]")].pop(); m.scrollIntoView({block: "center"}); return m; });
    check(!!barNow && barNow.labels.includes("Edit message"), "your latest message offers Edit: " + JSON.stringify(barNow) + JSON.stringify(await page.evaluate(() => [...window.ThetaApp.state.msgs.values()].filter(m => m.role === "user").map(m => [m.id, m.text]))));
    await page.click('#msgbar [aria-label="Edit message"]');
    await sleep(300);
    check(await page.inputValue("#c-text") === "What's the latest news today?" && await page.isVisible("#edit-chip"), "Edit fills the composer and shows the Editing chip");
    await shot("10-editing");
    await page.fill("#c-text", "hey again");
    const before = await page.$$eval("#thread .msg", e => e.length);
    await page.click("#c-send");
    await page.waitForFunction(() => !window.ThetaApp.state.streaming, null, {timeout: 15000});
    await sleep(600);
    const after = await page.evaluate(() => {
      const us = [...document.querySelectorAll("#thread .msg.u")], last = us.pop();
      return {n: document.querySelectorAll("#thread .msg").length, text: last.textContent, edited: !!last.closest(".item").querySelector(".edited"),
        cites: document.querySelectorAll("#thread .msg a.cite").length, reply: [...document.querySelectorAll("#thread .msg.a")].pop().textContent, chip: document.getElementById("edit-chip").hidden};
    });
    check(after.text === "hey again" && after.edited && after.chip, "the edited message keeps its place, marked Edited");
    check(after.cites === 0 && after.reply.startsWith("Hey.") && after.n === before, "the old reply is replaced by a new one: " + after.reply.slice(0, 40));
    await shot("10b-edited");

    // Connections: a tab in Settings, opened from the "..." menu
    await page.click("#chat-more");
    await page.click('#menu [data-act="connect"]');
    await page.waitForSelector("#tab-connections:not([hidden]) .app-row", {timeout: 4000});
    await sleep(450);
    await shot("08-connections");
    check(/\d+ connected/.test(await page.textContent("#connect-count")), "Connections shows the connected count");
    check(await page.textContent("#settings-title") === "Apps" && await page.isVisible("#settings-back"), "the Apps page opens, with a back button");
    const conn = await page.evaluate(() => ({
      logos: document.querySelectorAll("#connect-list .app-ic.logo svg path").length,
      soon: [...document.querySelectorAll("#connect-list .app-row.soon button")].map(b => b.textContent),
      secs: [...document.querySelectorAll("#connect-list .sec")].map(h => h.textContent),
      wide: document.documentElement.scrollWidth > innerWidth}));
    check(conn.logos >= 5, "apps show brand logos: " + conn.logos);
    check(conn.soon.length > 0 && conn.soon.every(t => t === "Soon"), "apps not built yet say Soon");
    check(conn.secs.includes("Coming soon"), "a Coming soon section: " + conn.secs.join(" | "));
    check(!conn.wide, "no sideways scroll on the Connections tab");
    await page.evaluate(() => document.querySelector("#connect-list .app-row.soon").scrollIntoView({block: "center"}));
    await sleep(200);
    await shot("08b-connections-soon");
    await page.click("#settings-back");
    await page.waitForSelector("#tab-root:not([hidden])");
    check(await page.isHidden("#tab-connections") && await page.textContent("#settings-title") === "Settings", "back goes to the Settings list");
    await page.click('#tab-root [data-go="security"]');
    check(!(await page.isHidden("#tab-security")) && await page.isHidden("#tab-root"), "a row opens its page");
    await shot("08c-settings-security");
    await page.click("#settings [data-close]");
    await page.waitForSelector("#settings", {state: "hidden"});

    // Settings, from the avatar button on home
    await page.click("#chat-back");
    await page.waitForSelector("#home:not([hidden])");
    await page.click("#home-me");
    await page.waitForSelector("#settings:not([hidden])");
    await sleep(500);
    await shot("09-settings");
    check(!(await page.isHidden("#tab-root")) && (await page.textContent("#set-me-name")).length > 0, "Settings opens on the list, with the profile card");
    const rows = await page.$$eval("#tab-root .nav-row span", e => e.map(x => x.textContent));
    check(["Personalization", "Memory", "Chips", "Profile", "Usage", "Data and storage", "Apps", "General", "Log out"].every(r => rows.includes(r)), "the list has every page: " + rows.join(", "));
    for (const [pg, sel, name] of [["profile", "#acc-name", "09e-profile"], ["personalize", "#tab-personalize select", "09f-personalization"],
      ["memory", "#tab-memory .mem-line", "09g-memory"], ["chips", "#tab-chips .chp-item", "09h-chips"], ["usage", "#tab-usage .use-card", "09i-usage"],
      ["data", "#tab-data .dat-state", "09j-data"]]) {
      await page.click(`#tab-root [data-go="${pg}"]`);
      await page.waitForSelector(sel, {timeout: 4000});
      await sleep(300);
      await shot(name);
      await page.click("#settings-back");
      await page.waitForSelector("#tab-root:not([hidden])");
    }
    await page.click('#tab-root [data-go="chips"]');
    await page.click("#tab-chips .chp-item .chp-txt");
    await page.waitForSelector("#tab-chips .chp-edit textarea");
    check((await page.inputValue("#tab-chips .chp-edit textarea")).length > 0, "a chip opens to its steps");
    await page.click("#settings-back");
    await page.click('#tab-root [data-go="general"]');
    check((await page.textContent("#set-loc-note")).includes("10 km"), "location note says rounded to about 10 km");
    check(await page.isChecked("#set-usage"), "Show token use is on by default");
    await page.waitForSelector("#set-lessons .lesson", {timeout: 3000}).catch(() => {});
    const les = await page.$$eval("#set-lessons .lesson b", e => e.map(x => x.textContent));
    check(les.some(t => /too long/.test(t)), "Settings lists what Theta learned: " + les.join(" | "));
    await page.evaluate(() => document.getElementById("set-lessons").scrollIntoView({block: "center"}));
    await sleep(300);
    await shot("09c-settings-lessons");
    await page.click("#set-usage");
    check(await page.evaluate(() => document.documentElement.classList.contains("no-usage") && localStorage.getItem("protos:show-usage") === "0"), "turning token use off hides it (stored on the phone)");
    await page.click("#set-usage");
    await page.click("#set-lessons .lesson button");
    await sleep(400);
    check(!(await page.$$eval("#set-lessons .lesson b", e => e.map(x => x.textContent))).some(t => /too long/.test(t)), "a lesson can be removed");
    await page.click("#settings-back");
    await page.click('#tab-root [data-go="notifications"]');
    await sleep(200);
    await shot("09d-settings-alerts");
    check(await page.isVisible("#set-push") || await page.isVisible("#set-proactive"), "the Alerts tab has the notification settings");

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

    // a mouse: the "..." beside a bubble opens the bar, Escape closes it and gives focus back
    const dctx = await browser.newContext({viewport: {width: 1100, height: 800}});
    const p3 = await dctx.newPage();
    const e3 = []; p3.on("pageerror", e => e3.push(String(e)));
    await p3.goto(base + "/?demo=1");
    await p3.waitForSelector("#home:not([hidden])", {timeout: 8000});
    await p3.click("#home-bot");
    await p3.waitForSelector("#thread .msg.a[data-id]");
    await sleep(500);
    const reply1 = (await p3.$$("#thread .msg.a[data-id]"))[0];
    await reply1.hover();
    const more = await reply1.$(".more-btn");
    check(!!more && await more.isVisible(), "a mouse gets a ... button beside the bubble");
    await more.click();
    await sleep(200);
    check(await p3.evaluate(() => !document.getElementById("msgbar").hidden && document.activeElement.closest("#msgbar") !== null), "... opens the bar with focus in it");
    await p3.keyboard.press("Escape");
    check(await p3.evaluate(() => document.getElementById("msgbar").hidden && document.activeElement.classList.contains("more-btn")), "Escape closes it and returns focus");
    check(e3.length === 0, "desktop page has no errors" + (e3.length ? ": " + e3.join(" | ") : ""));
    await dctx.close();
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
