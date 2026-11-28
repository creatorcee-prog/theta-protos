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
        if (e.closest(".chips, .chp-row, .hf-stack, .hf-row, .lk-row") || !e.getClientRects().length) return false;
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
    // the Home layouts (Settings > General > Home): each keeps the globe and shows the extras, Vantage greyed
    for (const lay of ["dock", "bento", "sheet", "satellites", "today"]) {
      await page.evaluate(l => { localStorage.setItem("theta:home", JSON.stringify({layout: l, size: "m", off: []})); return window.Theta.homeRender(); }, lay);
      await sleep(400);
      await shot("02-home-" + lay);
      const got = await page.evaluate(() => { const o = document.querySelector("#home .home-orb-wrap").getBoundingClientRect();
        const v = [...document.querySelectorAll("#home .hx.soon, #home .hb.soon, #home .hp[disabled]")];
        return {orb: o.width > 100 && o.top >= 0, vantage: v.length > 0 && v.every(e => e.disabled), cls: document.getElementById("home").className}; });
      check(got.orb && got.cls.includes("lay-" + lay), lay + ": Home keeps the globe as the main thing");
      if (lay !== "sheet") check(got.vantage, lay + ": Vantage shows, greyed out and not tappable");
    }
    await page.evaluate(() => { localStorage.removeItem("theta:home"); return window.Theta.homeRender(); });
    await sleep(300);

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
    { // a message someone sent, quoted by Theta ("> " lines), shows as a received-message card, sender inside it
      await page.waitForSelector("#thread .cm-quoted", {timeout: 12000}).catch(() => {});
      const q = await page.evaluate(() => { const f = document.querySelector("#thread .cm-quoted"); return f && {text: f.innerText, raw: document.querySelector("#thread").innerText.includes("> Hey")}; });
      check(q && /Received/i.test(q.text) && /From\s*Sam Rivera/i.test(q.text) && /Email/i.test(q.text) && !q.raw, "a quoted email shows as a Received card with who sent it, no raw > syntax");
      await page.evaluate(() => document.querySelector("#thread .cm-quoted").scrollIntoView({block: "center"})); await sleep(150);
      await shot("02c-quoted-email");
    }
    { // a multi-step job's phases: a check for each done, and one it never finished shows as not done
      await page.waitForSelector("#thread .pg .pg-step", {timeout: 5000}).catch(() => {});  // the history renders in pieces
      const pg = await page.evaluate(() => [...document.querySelectorAll("#thread .pg .pg-step")].map(r => r.className.split(" ")[1]));
      check(pg.join(",") === "done,done,skipped", "a reply keeps its progress card: " + pg.join(","));
      await page.evaluate(() => { document.querySelector("#thread .pg").scrollIntoView({block: "center"});
        // and the live card while working: in progress spins, to come shows a clock
        const live = Theta.progressCard([{text: "Research completed", state: "done"}, {text: "Comparing findings", state: "active"}, {text: "Verification pending", state: "pending"}]);
        // shown in the finished card's place, so the shot never looks like two cards for one turn
        const done = document.querySelector("#thread .pg"); live.id = "pg-live"; done.after(live); done.hidden = true; });
      await sleep(200); await shot("02d-progress");
      await page.evaluate(() => { document.getElementById("pg-live").remove(); document.querySelector("#thread .pg").hidden = false; });
    }
    { // long replies: headings by level, rules, tables, and code that scrolls inside the bubble instead of being cut off
      const r = await page.evaluate(() => { const box = document.createElement("div"); box.className = "msg a text";
        box.append(window.ThetaApp.md("# A\n\n### B\n\n---\n\n| Time | What |\n|---|---|\n| 9:00 AM | Breakfast |\n\n```\n" + "x".repeat(200) + "\n```"));
        document.getElementById("thread").append(box);
        const pre = box.querySelector("pre");
        const out = {h3: !!box.querySelector("h3"), h4: !!box.querySelector("h4"), hr: !!box.querySelector("hr"), th: box.querySelectorAll("th").length,
          pre: pre.scrollWidth > pre.clientWidth, fits: box.getBoundingClientRect().right <= innerWidth + 1};
        box.hidden = true; return out; });
      check(r.h3 && r.h4 && r.hr && r.th === 2 && r.pre && r.fits, "replies render headings, rules and tables, and long code scrolls inside the bubble: " + JSON.stringify(r));
    }
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
      if (pg === "usage") { // the workers' daily budget is set here, 5 cents to start
        const v = await page.$eval("#set-worker-budget", e => e.selectedOptions[0].textContent).catch(() => "");
        check(v === "5¢", "Settings > Usage has the workers' daily budget, at 5¢: " + v);
      }
      if (pg === "chips") { // Suggested: skills from other agents, adapted; nothing is added until you tap Add
        await page.waitForSelector("#tab-chips .chh-item", {timeout: 4000}).catch(() => {});
        check(await page.$("#tab-chips .chh-item .chh-tx") !== null, "chips: suggested chips adapted from other agents' skills show");
        await page.click("#tab-chips .chh-item .chh-tx"); await sleep(200);
        await page.evaluate(() => document.querySelector("#tab-chips .chh").scrollIntoView());
        await shot("09h2-chips-suggested");
        const before = await page.$$eval("#tab-chips .chp-item", n => n.length);
        await page.click("#tab-chips .chh-btns .btn-dark"); await sleep(300);
        check(!await page.$("#tab-chips .chh-item") && before >= 1, "chips: Add takes the suggestion off the list");
      }
      await page.click("#settings-back");
      await page.waitForSelector("#tab-root:not([hidden])");
    }
    await page.click('#tab-root [data-go="chips"]');
    await page.click("#tab-chips .chp-item .chp-txt");
    await page.waitForSelector("#tab-chips .chp-edit textarea");
    check((await page.inputValue("#tab-chips .chp-edit textarea")).length > 0, "a chip opens to its steps");
    await page.click("#settings-back");
    await page.click('#tab-root [data-go="general"]');
    { // Theta's look: live globes to swipe through for color, style, dots and opening (not menus of names)
      await page.waitForSelector("#tab-general .lk-row .lk-tile canvas", {timeout: 4000}).catch(() => {});
      const n = await page.$$eval("#tab-general .lk-row", rs => rs.map(r => r.querySelectorAll(".lk-tile canvas").length));
      check(n.join(",") === "6,11,7,2", "look: color, style (11, with the glass ones), dots and opening each show live previews: " + n.join(","));
      { // a glass style (Generation 8) draws light in its preview tile
        const lit = await page.evaluate(() => { const cv = [...document.querySelectorAll("#tab-general .lk-row")][1].querySelectorAll("canvas")[6];
          const d = cv.getContext("2d").getImageData(0, 0, cv.width, cv.height).data; let s = 0; for (let i = 3; i < d.length; i += 4) s += d[i]; return s / (d.length / 4); });
        check(lit > 8, "the Ribbons preview draws light (mean alpha " + Math.round(lit) + ")");
      }
      await page.click("#tab-general .lk-row:nth-of-type(2) .lk-tile:nth-child(3)");
      check(await page.evaluate(() => ThetaOrb.style === "lumen" && localStorage.getItem("theta:style") === "lumen"), "tapping a style applies it");
      await page.evaluate(() => document.querySelector("#tab-general .lk-row").scrollIntoView({block: "start"})); await sleep(700);
      await shot("09k-look");
      await page.click("#tab-general .lk-row:nth-of-type(2) .lk-tile:nth-child(1)");
    }
    check((await page.textContent("#set-loc-note")).includes("10 km"), "location note says rounded to about 10 km");
    check(await page.isChecked("#set-usage"), "Show token use is on by default");
    await page.waitForSelector("#set-lessons .lesson", {timeout: 3000}).catch(() => {});
    const les = await page.$$eval("#set-lessons .lesson b", e => e.map(x => x.textContent));
    check(les.some(t => /too long/.test(t)), "Settings lists what Theta learned: " + les.join(" | "));
    await page.click("#set-lessons details.sim summary").catch(() => {});
    { const t = await page.$eval("#set-lessons details.sim", d => d.innerText).catch(() => "");
      check(["Root cause", "Why this fix", "Predicted", "Observed", "Models", "Where"].every(k => t.includes(k)), "each lesson's details read: root cause, why, predicted, observed %, models %, where"); }
    await page.evaluate(() => document.getElementById("set-lessons").scrollIntoView({block: "center"}));
    await sleep(300);
    await shot("09c-settings-lessons");
    await page.click("#set-usage");
    check(await page.evaluate(() => document.documentElement.classList.contains("no-usage") && localStorage.getItem("protos:show-usage") === "0"), "turning token use off hides it (stored on the phone)");
    await page.click("#set-usage");
    // developer details off: what anyone who doesn't run Theta sees (no token lines, no lesson internals, no models)
    await page.click("#set-dev"); await sleep(300);
    check(await page.evaluate(() => !document.documentElement.classList.contains("dev")
      && getComputedStyle(document.querySelector("#set-usage").closest(".row-set")).display === "none"
      && [...document.querySelectorAll("details.sim")].every(d => getComputedStyle(d).display === "none")),
      "developer details off: token use and lesson internals are hidden");
    await shot("09l-settings-no-dev");
    await page.click("#set-dev"); await sleep(200);
    check(await page.evaluate(() => document.documentElement.classList.contains("dev")), "and back on for the account that runs Theta");
    await page.click("#set-lessons .lesson button");
    await sleep(400);
    check(!(await page.$$eval("#set-lessons .lesson b", e => e.map(x => x.textContent))).some(t => /too long/.test(t)), "a lesson can be removed");
    await page.click("#settings-back");
    { // every sheet: focus inside, background inert, Escape closes it and focus goes back to what opened it
      await sleep(150);
      const st = await page.evaluate(() => ({inside: document.getElementById("settings").contains(document.activeElement),
        active: (document.activeElement || {}).id || (document.activeElement || {}).tagName,
        inert: document.getElementById("home").inert || document.getElementById("chat").inert}));
      check(st.inside && st.inert, "an open sheet holds focus and the screen behind it is inert" + (st.inside && st.inert ? "" : ": " + JSON.stringify(st)));
    }
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

    // large text (the iPhone's text size at about 150%): everything scales with it, nothing runs off the side
    const p5 = await ctx.newPage();
    await p5.addInitScript(() => { document.addEventListener("DOMContentLoaded", () => { document.documentElement.style.fontSize = "26px"; }); });
    await p5.goto(base + "/?demo=1");
    await p5.waitForSelector("#home:not([hidden])", {timeout: 8000}); await sleep(900);
    const big = await p5.evaluate(() => ({title: parseFloat(getComputedStyle(document.querySelector(".hf-hello b") || document.body).fontSize),
      wide: [...document.querySelectorAll("#app *")].filter(e => !e.closest(".chips, .chp-row, .hf-stack, .hf-row, .lk-row") && e.getClientRects().length
        && e.getBoundingClientRect().right > innerWidth + 1).length}));
    check(big.title > 30 && big.wide === 0, "with large text the app scales up and nothing sticks out sideways: " + JSON.stringify(big));
    await p5.screenshot({path: path.join(OUT, "11-large-text.png")});
    await p5.click("#home-bot"); await sleep(700);
    await p5.screenshot({path: path.join(OUT, "11b-large-text-chat.png")});
    await p5.close();

    // a server that's down (a 503, then back): never the built-in demo's made-up data, and it reconnects by itself
    const p4 = await ctx.newPage();
    let up = false;
    await p4.route("**/api/**", route => {
      const u = new URL(route.request().url());
      if (!up) return route.fulfill({status: 503, json: {error: "restarting"}});
      if (u.pathname === "/api/health") return route.fulfill({json: {ok: true, version: "0.test"}});
      if (u.pathname.startsWith("/api/messages")) return route.fulfill({json: {messages: []}});
      return route.fulfill({json: {}});
    });
    await p4.goto(base + "/");
    await p4.waitForSelector("#home:not([hidden])", {timeout: 12000});
    await sleep(600);
    const down = await p4.evaluate(() => ({demo: window.ThetaApp.state.demo, body: document.body.innerText}));
    check(!down.demo && !/Sam|Dentist/.test(down.body), "a server that's down never shows the demo's made-up data");
    check(/Can't reach Theta/.test(down.body), "it says it can't reach Theta and keeps trying");
    up = true;
    await p4.waitForFunction(() => window.ThetaApp.state.ready, null, {timeout: 15000}).catch(() => {});
    check(await p4.evaluate(() => window.ThetaApp.state.ready && !window.ThetaApp.state.demo), "and picks up by itself once the server's back");
    await p4.close();

    // a mouse: the "..." beside a bubble opens the bar, Escape closes it and gives focus back
    const dctx = await browser.newContext({viewport: {width: 1100, height: 800}});
    const p3 = await dctx.newPage();
    const e3 = []; p3.on("pageerror", e => e3.push(String(e)));
    await p3.goto(base + "/?demo=1");
    await p3.waitForSelector("#home:not([hidden])", {timeout: 8000});
    { // a wide window shows Home and the chat side by side
      await sleep(600);
      const w = await p3.evaluate(() => { const h = document.getElementById("home").getBoundingClientRect(), c = document.getElementById("chat").getBoundingClientRect();
        return {both: !document.getElementById("chat").hidden, side: c.left >= h.right - 1 && c.width > 300}; });
      check(w.both && w.side, "a desktop window shows Home and the chat side by side" + (w.both && w.side ? "" : ": " + JSON.stringify(w)));
      { const f = path.join(OUT, "12-desktop-two-pane.png"); await p3.screenshot({path: f}); console.log("shot " + f); }
      // a row that scrolls sideways moves with the mouse wheel (it looked cut off: a wheel only went up and down)
      const box = await p3.evaluate(() => { for (const e of document.querySelectorAll("#home *")) { const ox = getComputedStyle(e).overflowX;
        if ((ox === "auto" || ox === "scroll") && e.scrollWidth > e.clientWidth + 20 && e.offsetParent) { e.scrollIntoView({block: "center"}); e.id = e.id || "shots-row";
          const r = e.getBoundingClientRect(); return {id: e.id, x: r.left + r.width / 2, y: r.top + r.height / 2}; } } return null; });
      if (box) {
        await p3.mouse.move(box.x, box.y); await p3.mouse.wheel(0, 240); await sleep(300);
        const left = await p3.evaluate(id => document.getElementById(id).scrollLeft, box.id);
        check(left > 0, "the mouse wheel scrolls a sideways row on desktop: " + left);
      } else check(false, "found a sideways row on Home to scroll");
    }
    { // the glass styles' opening (ignite) plays and hands over, with no errors
      const ms = await p3.evaluate(() => new Promise(res => {
        const c = document.createElement("canvas"); c.style.cssText = "position:fixed;left:0;top:0;width:200px;height:200px;z-index:99"; document.body.append(c);
        const o = ThetaOrb.mount(c, {style: "ribbons"}), t0 = performance.now();
        o.opening("converge", () => { const k = o.open; res(Math.round(performance.now() - t0)); o.destroy(); c.remove(); }, 1);
        setTimeout(() => res(-1), 5000);
      }));
      check(ms > 1200 && ms < 3000, "the glass globe's opening plays and finishes: " + ms + " ms");
    }
    { // the keyboard: Escape closes a sheet and focus returns to the button that opened it
      await p3.focus("#home-me"); await p3.keyboard.press("Enter"); await sleep(500);
      await p3.keyboard.press("Escape"); await sleep(500);
      const r = await p3.evaluate(() => ({hidden: document.getElementById("settings").hidden, back: document.activeElement && document.activeElement.id}));
      check(r.hidden && r.back === "home-me", "Escape closes a sheet and puts focus back on what opened it" + (r.hidden && r.back === "home-me" ? "" : ": " + JSON.stringify(r)));
    }
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
    { // a message sent while Theta answers waits above the box (the box stays free) and sends itself when the reply ends
      await p3.fill("#c-text", "What's the weather tomorrow?"); await p3.click("#c-send");
      await p3.waitForFunction(() => window.ThetaApp.state.streaming, null, {timeout: 6000}).catch(() => {});
      await p3.fill("#c-text", "And the day after?"); await p3.click("#c-send"); await sleep(200);
      const q = await p3.evaluate(() => ({items: document.querySelectorAll("#c-queued .q-item").length, box: document.getElementById("c-text").value,
        sent: [...document.querySelectorAll("#thread .msg.u")].some(e => e.textContent.includes("And the day after"))}));
      check(q.items === 1 && q.box === "" && !q.sent, "a message sent mid-reply waits above the box, which is free again: " + JSON.stringify(q));
      { const f = path.join(OUT, "13-queued.png"); await p3.screenshot({path: f}); console.log("shot " + f); }
      await p3.waitForFunction(() => [...document.querySelectorAll("#thread .msg.u")].some(e => e.textContent.includes("And the day after")), null, {timeout: 20000}).catch(() => {});
      const after = await p3.evaluate(() => ({items: document.querySelectorAll("#c-queued .q-item").length,
        sent: [...document.querySelectorAll("#thread .msg.u")].some(e => e.textContent.includes("And the day after"))}));
      check(after.sent && after.items === 0, "and it sends itself once the reply is done: " + JSON.stringify(after));
    }
    check(e3.length === 0, "desktop page has no errors" + (e3.length ? ": " + e3.join(" | ") : ""));
    await dctx.close();

    { // agents: make one from a ready-made start on Home, chat with it, and Theta's chat stays its own
      const actx = await browser.newContext({viewport: {width: 390, height: 844}, deviceScaleFactor: 2});
      const pa = await actx.newPage(); const ea = []; pa.on("pageerror", e => ea.push(String(e)));
      await pa.goto(base + "/?demo=1"); await pa.waitForSelector("#home:not([hidden]) .ag-row .ag-new", {timeout: 8000});
      await pa.click(".ag-row .ag-new"); await pa.waitForSelector("#agent-edit:not([hidden]) .ag-starts button", {timeout: 4000});
      await pa.click("#agent-edit .ag-starts button:first-child"); await sleep(200);
      check(await pa.inputValue("#agent-edit #ag-name") === "Job hunter", "a ready-made start fills in the agent's form");
      { const f = path.join(OUT, "14-agent-new.png"); await pa.screenshot({path: f}); console.log("shot " + f); }
      await pa.click("#agent-edit .ag-save");
      await pa.waitForSelector("#chat:not([hidden])", {timeout: 5000});
      await sleep(600);
      const head = await pa.evaluate(() => ({name: document.querySelector("#chat-name span").textContent, ph: document.getElementById("c-text").placeholder,
        msgs: document.querySelectorAll("#thread .msg").length}));
      check(head.name === "Job hunter" && head.ph === "Ask Job hunter", "the new agent's chat opens under its own name: " + JSON.stringify(head));
      await pa.fill("#c-text", "Any new roles near me?"); await pa.click("#c-send");
      await pa.waitForFunction(() => !window.ThetaApp.state.streaming && document.querySelectorAll("#thread .msg.a").length > 0, null, {timeout: 15000}).catch(() => {});
      await sleep(400);
      { const f = path.join(OUT, "15-agent-chat.png"); await pa.screenshot({path: f}); console.log("shot " + f); }
      await pa.click("#chat-back"); await pa.waitForSelector("#home:not([hidden])"); await sleep(400);
      await pa.waitForSelector(".wk .wk-row", {timeout: 6000}).catch(() => {});
      const wkr = await pa.evaluate(() => [...document.querySelectorAll(".wk .wk-row small")].map(e => e.textContent));
      check(wkr.length >= 1 && wkr.every(t => /^w\d+\.[a-z0-9-]+@home · /.test(t)), "Home lists the workers, each at its own address: " + JSON.stringify(wkr));
      await pa.evaluate(() => document.querySelector(".ag-row").scrollIntoView({block: "start"})); await sleep(300);
      { const f = path.join(OUT, "16-home-agents.png"); await pa.screenshot({path: f}); console.log("shot " + f); }
      await pa.click("#home-bot"); await pa.waitForSelector("#chat:not([hidden])"); await sleep(600);
      const back = await pa.evaluate(() => ({name: document.querySelector("#chat-name span").textContent,
        leaked: [...document.querySelectorAll("#thread .msg.u")].some(e => e.textContent.includes("Any new roles"))}));
      check(back.name !== "Job hunter" && !back.leaked, "Home's globe opens Theta's own chat, without the agent's messages: " + JSON.stringify(back));
      await pa.click("#chat-back"); await pa.waitForSelector("#home:not([hidden])");
      await pa.click(".ag-row .ag-chip:not(.ag-new)"); await sleep(700);
      const again = await pa.evaluate(() => [...document.querySelectorAll("#thread .msg.u")].some(e => e.textContent.includes("Any new roles")));
      check(again, "and the agent's chat still has its own messages");
      check(ea.length === 0, "agents: no page errors" + (ea.length ? ": " + ea.join(" | ") : ""));
      await actx.close();
    }
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
