/* Demo mode: a fake Theta backend in the page. It answers the same HTTP API as server/ (docs/SPEC.md) with real
 * Response objects, including a streamed text/event-stream for POST /api/chat, so the app runs the same code
 * path. Used with ?demo=1, or when the API can't be reached. Nothing leaves the page.
 */
(function () {
  "use strict";
  const now = () => Math.floor(Date.now() / 1000);
  let nextId = 100;
  const msgs = [];
  const add = (role, text, meta, t) => { const m = {id: nextId++, bot: "theta", role, text, t: t || now(), meta: meta || {}}; msgs.push(m); return m; };

  // a little history, so the chat isn't empty
  const H = now() - 3600 * 20;
  const seed = [
    ["user", "Morning. What's on today?"],
    ["assistant", "Morning. Light day:\n\n- **10:30** dentist (leave by 10:05, there's roadwork on Colfax)\n- **2:00** call with Sam about the hub\n- Trash goes out tonight\n\nThe dentist is the only thing with a hard edge.", {model: "deepseek-chat", tier: "quick"}],
    ["user", "Remind me what I spent on groceries this month"],
    ["assistant", "**$412** so far in November, about $60 under where you usually are by the 24th. Biggest single run was King Soopers on the 9th ($96).", {model: "deepseek-reasoner", tier: "think"}],
    ["assistant", "Sorted your newsletters", {task: {title: "Sorted 214 newsletters into Later", state: "done"}}],
    ["assistant", "Evening brief: nothing urgent. Your package from the camera shop lands tomorrow before noon, and it's going down to **14°F** tonight, so the hose bib might want a cover.", {proactive: true, source: "brief", level: 3}],
  ];
  seed.forEach((s, i) => add(s[0], s[1], s[2], H + i * 600));

  const settings = (() => { try { return JSON.parse(localStorage.getItem("protos:demo-settings")) || null; } catch (e) { return null; } })()
    || {proactive: true, quiet: [22, 7], tz: "America/Denver", loc: null};
  const saveSettings = () => { try { localStorage.setItem("protos:demo-settings", JSON.stringify(settings)); } catch (e) {} };
  const connections = [
    {id: "gmail", name: "Gmail", connected: true, what: "Search, read, draft and sort your email."},
    {id: "gcal", name: "Google Calendar", connected: true, what: "See your day, add and move events."},
    {id: "gdrive", name: "Google Drive", connected: false, what: "Find, read and create files."},
    {id: "vantage", name: "Vantage", connected: true, what: "Alerts near you and big world events."},
    {id: "obsidian", name: "Obsidian vault", connected: true, what: "Theta's notes and your memory file."},
    {id: "plex", name: "Plex", connected: false, what: "What you're watching and what's next."},
    {id: "homeassistant", name: "Home Assistant", connected: false, what: "Lights, locks and the thermostat."},
    {id: "github", name: "GitHub", connected: false, what: "Issues, pull requests and builds."},
    {id: "notion", name: "Notion", connected: false, what: "Pages, databases and to-dos."},
    {id: "spotify", name: "Spotify", connected: false, what: "Play, queue and find music."},
  ];

  // canned replies, picked with the same kind of rules the router uses
  function reply(text) {
    const t = text.toLowerCase();
    if (/\b(code|error|bug|stack|traceback|python|js|function)\b/.test(t))
      return {route: {model: "deepseek-coder", tier: "code", why: "looks like code"},
        text: "Looks like the loop runs one past the end. Change the bound to `i < items.length` and it stops throwing.\n\nIf it still fails, paste the **full** traceback and I'll go line by line."};
    if (/\b(news|today|price|weather|score|latest)\b/.test(t))
      return {route: {model: "deepseek-chat", tier: "search", why: "live facts"},
        text: "Here's the short version from this morning:\n\n1. **Weather:** 31°F now, sunny, high of 44.\n2. **Roads:** I-25 is clear; Colfax still has the lane closure.\n3. **Markets:** flat so far.\n\nSources: [National Weather Service](https://www.weather.gov) and CDOT."};
    if (/\b(plan|should i|compare|why|vs|decide|budget)\b/.test(t))
      return {route: {model: "deepseek-reasoner", tier: "think", why: "a decision with trade-offs"},
        text: "Short answer: **wait a week**.\n\nWhy:\n- The price usually drops on the 1st.\n- You've got $412 into groceries already, so the month is tighter than it looks.\n- Nothing you need it for happens before the 5th.\n\nWant me to remind you on the 1st?"};
    if (/\b(nudge|remind)\b/.test(t))
      return {route: {model: "deepseek-chat", tier: "quick", why: "a reminder"}, text: "Done. I'll text you at **1:30**."};
    if (/^(hi|hey|hello|yo|morning|evening)\b/.test(t))
      return {route: {model: "deepseek-chat", tier: "quick", why: "short chat"}, text: "Hey. Quiet day so far. What are we working on?"};
    return {route: {model: "deepseek-chat", tier: "quick", why: "short chat"},
      text: "Got it. I'll keep an eye on that and **text you** if anything changes. Anything else before I go quiet?"};
  }

  const json = (obj, status) => new Response(JSON.stringify(obj), {status: status || 200, headers: {"content-type": "application/json"}});
  const sleep = ms => new Promise(r => setTimeout(r, ms));

  function chatStream(body) {
    const enc = new TextEncoder(), user = add("user", String(body.text || ""), {client_id: body.client_id});
    const r = reply(user.text);
    let cancelled = false;
    const stream = new ReadableStream({
      async start(ctl) {
        const send = (ev, data) => { if (!cancelled) ctl.enqueue(enc.encode(`event: ${ev}\ndata: ${JSON.stringify(data)}\n\n`)); };
        send("user", user);
        await sleep(250);
        send("route", r.route);
        await sleep(r.route.tier === "think" ? 1400 : 700); // a beat of thinking
        const parts = r.text.match(/\S+\s*|\s+/g) || [];
        for (let i = 0; i < parts.length; i += 2) {
          if (cancelled) return;
          send("delta", {text: parts.slice(i, i + 2).join("")});
          await sleep(45 + Math.random() * 70);
        }
        const done = add("assistant", r.text, {model: r.route.model, tier: r.route.tier, why: r.route.why});
        send("done", done);
        if (!cancelled) ctl.close();
      },
      cancel() { cancelled = true; },
    });
    return new Response(stream, {status: 200, headers: {"content-type": "text/event-stream"}});
  }

  // one proactive text, about 8 s after the app opens
  setTimeout(() => {
    add("assistant", "Heads-up: snow starts around **4 pm** near you, 2–4 inches by morning. Your 2:00 with Sam is across town. Want me to nudge you at 1:30 so you leave early?",
      {proactive: true, source: "vantage", level: 3, actions: [{label: "Yes, nudge me at 1:30", value: "Yes, nudge me at 1:30 to leave for Sam"}, {label: "I'm working from home", value: "I'm not driving today, working from home"}]});
    window.dispatchEvent(new Event("protos:inbox")); // like a push arriving: the app checks its inbox now
  }, 8000);

  async function demoFetch(input, init) {
    init = init || {};
    const u = new URL(typeof input === "string" ? input : input.url, location.href), p = u.pathname, method = (init.method || "GET").toUpperCase();
    let body = {}; try { body = init.body ? JSON.parse(init.body) : {}; } catch (e) {}
    await sleep(60 + Math.random() * 80);
    if (p === "/api/health") return json({ok: true, version: "demo"});
    if (p === "/api/login") return json({ok: true});
    if (p === "/api/bots") return json([{id: "theta", name: "Theta", avatar: {kind: "globe"}}]);
    if (p === "/api/messages") {
      const before = Number(u.searchParams.get("before")) || Infinity, limit = Number(u.searchParams.get("limit")) || 50;
      const list = msgs.filter(m => m.id < before);
      return json({messages: list.slice(Math.max(0, list.length - limit))});
    }
    if (p === "/api/chat" && method === "POST") return chatStream(body);
    if (p === "/api/inbox") { const since = Number(u.searchParams.get("since")) || 0; return json({messages: msgs.filter(m => m.id > since)}); }
    if (p === "/api/push/key") return json({key: ""});
    if (p === "/api/push/subscribe" || p === "/api/push/test") return json({ok: true, demo: true});
    if (p === "/api/connections") return json(connections);
    if (p.startsWith("/api/connections/") && method === "POST") {
      const c = connections.find(x => x.id === p.split("/").pop()); if (c) c.connected = !c.connected; return json(c || {}, c ? 200 : 404);
    }
    if (p === "/api/settings") { if (method === "POST") { Object.assign(settings, body); saveSettings(); } return json(settings); }
    return json({error: "not found"}, 404);
  }

  window.ThetaDemo = {fetch: demoFetch};
})();
