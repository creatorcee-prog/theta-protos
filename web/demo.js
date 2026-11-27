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
    ["assistant", "Morning. Light day:\n\n- **10:30** dentist (leave by 10:05, there's roadwork on Colfax)\n- **2:00** call with Sam about the hub\n- Trash goes out tonight\n\nThe dentist is the only thing with a hard edge.", {model: "deepseek-chat", tier: "quick", usage: {in: 2841, out: 64, cached: 2304, cost_usd: 0.0003, model: "deepseek-chat"}}],
    ["user", "Remind me what I spent on groceries this month"],
    ["assistant", "**$412** so far in November, about $60 under where you usually are by the 24th. Biggest single run was King Soopers on the 9th ($96).", {model: "deepseek-reasoner", tier: "think", usage: {in: 3120, out: 418, cached: 2816, cost_usd: 0.0011, model: "deepseek-reasoner"}}],
    ["user", "What did Sam say about Saturday?"],
    ["assistant", "Sam's in for Saturday and bringing the ladder:\n\n> Hey! Are we still on for the hub install this Saturday? I can bring the ladder and the extra cable.\n\nFrom: Sam Rivera · sam@example.com\n\nWant me to tell him 10 works?", {model: "deepseek-chat", tier: "quick", tools: ["gmail_search", "gmail_read"]}],
    ["user", "Find me the cheapest arc floor lamp and when it'd get here"],
    ["assistant", "**$89 at Lamp Shop**, the lowest of 4 stores, free returns. Delivery quotes are still loading on two of them, so I'll check those again tonight.", {model: "deepseek-chat", tier: "quick", tools: ["progress_update", "web_search"], progress: [{text: "Research completed", state: "done"}, {text: "Comparing findings", state: "done"}, {text: "Verify delivery dates", state: "skipped"}]}],
    ["assistant", "Sorted your newsletters", {task: {title: "Sorted 214 newsletters into Later", state: "done"}}],
    ["assistant", "Evening brief: nothing urgent. Your package from the camera shop lands tomorrow before noon, and it's going down to **14°F** tonight, so the hose bib might want a cover.", {proactive: true, source: "brief", level: 3}],
  ];
  seed.forEach((s, i) => add(s[0], s[1], s[2], H + i * 600));

  const settings = (() => { try { return JSON.parse(localStorage.getItem("protos:demo-settings")) || null; } catch (e) { return null; } })()
    || {proactive: true, quiet: [22, 7], tz: "America/Denver", loc: null};
  const saveSettings = () => { try { localStorage.setItem("protos:demo-settings", JSON.stringify(settings)); } catch (e) {} };
  const connections = [
    {id: "gmail", name: "Gmail", cat: "Google", connected: true, what: "Search, read, draft and send mail"},
    {id: "calendar", name: "Google Calendar", cat: "Google", connected: true, what: "See and add events, invites with your OK"},
    {id: "drive", name: "Google Drive", cat: "Google", connected: false, what: "Find and read files, make Docs and Slides"},
    {id: "vantage", name: "Vantage", cat: "Theta", connected: true, what: "Events near you and in the world"},
    {id: "search", name: "Web search", cat: "Web", connected: true, what: "Live facts, news and prices, with sources"},
    {id: "phone", name: "Phone calls", cat: "Messaging", connected: false, what: "Theta calls you, and calls others for you with your OK"},
    {id: "slack", name: "Slack", cat: "Messaging", connected: false, soon: true, what: "Read channels, catch you up and draft replies"},
    {id: "notion", name: "Notion", cat: "Productivity", connected: false, soon: true, what: "Search, read and add to your pages"},
    {id: "obsidian", name: "Obsidian", cat: "Productivity", connected: false, soon: true, what: "Read and add to your vault"},
    {id: "homeassistant", name: "Home Assistant", cat: "Home", connected: false, soon: true, what: "Lights, locks and the thermostat"},
    {id: "spotify", name: "Spotify", cat: "Media", connected: false, soon: true, what: "Play, queue and find music"},
    {id: "github", name: "GitHub", cat: "Developer", connected: false, soon: true, what: "Issues, pull requests and builds"},
  ];


  // canned replies, picked with the same kind of rules the router uses
  function reply(text) {
    const t = text.toLowerCase();
    if (/\b(code|error|bug|stack|traceback|python|js|function)\b/.test(t))
      return {route: {model: "deepseek-coder", tier: "code", why: "looks like code"},
        text: "Looks like the loop runs one past the end. Change the bound to `i < items.length` and it stops throwing.\n\nIf it still fails, paste the **full** traceback and I'll go line by line."};
    if (/\b(news|today|price|weather|score|latest)\b/.test(t))
      return {route: {model: "deepseek-chat", tier: "search", why: "live facts"},
        text: "Here's the short version from this morning:\n\n1. **Weather:** 31°F now, sunny, high of 44 [1].\n2. **Roads:** I-25 is clear; Colfax still has the lane closure [2].\n3. **Markets:** flat so far [3].",
        sources: [{title: "Denver forecast - National Weather Service", url: "https://www.weather.gov/bou/"},
          {title: "COtrip traveler information", url: "https://www.cotrip.org/"},
          {title: "Stocks open flat ahead of data", url: "https://www.reuters.com/markets/"}]};
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

  // made-up but plausible token use, like the server's meta.usage
  function usage(r) {
    const prior = msgs.reduce((n, m) => n + m.text.length, 0), tin = 2600 + Math.round(prior / 4) + (r.sources ? 900 : 0);
    const out = Math.max(12, Math.round(r.text.length / 3.6)), cached = Math.round(tin * 0.82 / 64) * 64;
    const reasoner = r.route.model === "deepseek-reasoner", pin = reasoner ? 0.55 : 0.27, pc = 0.07, pout = reasoner ? 2.19 : 1.1;
    const cost = ((tin - cached) * pin + cached * pc + out * pout) / 1e6;
    return {in: tin, out, cached, cost_usd: Math.round(cost * 1e6) / 1e6, model: r.route.model};
  }
  function chatStream(body, edit) {
    const enc = new TextEncoder();
    let user, deleted = [];
    if (edit) { // like POST /api/messages/edit: rewrite the latest user message, drop the replies after it
      user = edit; user.text = String(body.text || ""); user.meta = Object.assign({}, user.meta, {edited: now()});
      for (let i = msgs.length - 1; i >= 0; i--) {
        const m = msgs[i]; if (m.id <= user.id) break;
        if (m.role === "assistant" && (!m.meta.proactive || m.meta.reply_to === user.id)) { deleted.push(m.id); msgs.splice(i, 1); }
      }
    } else user = add("user", String(body.text || ""), {client_id: body.client_id});
    const r = reply(user.text);
    let cancelled = false;
    const stream = new ReadableStream({
      async start(ctl) {
        const send = (ev, data) => { if (!cancelled) ctl.enqueue(enc.encode(`event: ${ev}\ndata: ${JSON.stringify(data)}\n\n`)); };
        if (edit) send("deleted", {ids: deleted, user_id: user.id});
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
        const meta = {model: r.route.model, tier: r.route.tier, why: r.route.why, reply_to: user.id, usage: usage(r)};
        if (r.sources) meta.sources = r.sources;
        if (edit) meta.edited = true;
        const done = add("assistant", r.text, meta);
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
    if (p === "/api/messages/edit" && method === "POST") {
      const lastUser = [...msgs].reverse().find(m => m.role === "user");
      if (!lastUser || lastUser.id !== Number(body.id)) return json({error: "only your latest message can be edited"}, 409);
      return chatStream(body, lastUser);
    }
    if (p === "/api/feedback" && method === "POST") {
      const m = msgs.find(x => x.id === Number(body.message_id) && x.role === "assistant");
      if (!m) return json({error: "no such reply"}, 404);
      const v = Number(body.vote);
      if (v) feedback.set(m.id, {id: m.id, vote: v, reason: v < 0 ? String(body.reason || "") : "", tier: m.meta.tier, reply: m.text, t: Date.now(), dismissed: false});
      else feedback.delete(m.id);
      if (v) m.meta.vote = v; else delete m.meta.vote;
      return json({ok: true, message_id: m.id, vote: v, lessons: lessons()});
    }
    if (p === "/api/feedback/summary") {
      if (method === "DELETE") {
        const l = lessons().find(x => x.id === u.searchParams.get("id"));
        if (!l) return json({error: "no such lesson"}, 404);
        for (const id of l.rows) { const f = feedback.get(id); if (f) f.dismissed = true; }
      }
      const all = [...feedback.values()];
      return json({lessons: lessons(), likes: all.filter(f => f.vote > 0).length, dislikes: all.filter(f => f.vote < 0).length});
    }
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

  // feedback -> lessons, the same rules as server/persona.py lessons() (simplified)
  const feedback = new Map();
  const REASONS = [["too long", "too-long", "Disliked: too long \u2192 keep replies shorter"], ["wrong", "wrong", "Disliked: wrong \u2192 check facts, and say plainly when unsure"],
    ["not what i asked", "off-target", "Disliked: not what I asked \u2192 answer the exact question first"], ["tone", "tone", "Disliked: the tone \u2192 plainer and more direct, match their tone"]];
  function lessons() {
    const found = new Map(), likes = new Map();
    const put = (id, text, f) => { const l = found.get(id) || {id, text, t: 0, n: 0, rows: []}; l.n++; l.rows.push(f.id); l.t = Math.max(l.t, f.t); found.set(id, l); };
    for (const f of feedback.values()) {
      if (f.dismissed) continue;
      if (f.vote < 0 && f.reason) {
        const low = f.reason.toLowerCase(), hit = REASONS.find(r => low === r[0] || low.startsWith(r[0] + ":"));
        if (hit) put("d:" + hit[1], hit[2], f); else put("d:x:" + low.slice(0, 60), `Disliked: "${f.reason.slice(0, 80)}" \u2192 avoid that`, f);
      } else if (f.vote > 0) { const k = (f.tier || "quick") + ":" + (f.reply.length <= 320 ? "short" : "detailed"); likes.set(k, (likes.get(k) || []).concat([f])); }
    }
    for (const [k, fs] of likes) if (fs.length >= 3) for (const f of fs) put("l:" + k, `Liked: ${k.split(":")[0]} replies ${k.endsWith("short") ? "that are short" : "that go into detail"} \u2192 keep doing that`, f);
    // demo only: an example of the self-improvement log on each lesson (made-up numbers, as all demo data is)
    const sim = l => ({root_cause: l.id.startsWith("d:") ? "You disliked: " + l.text.split(":")[1].split("\u2192")[0].trim() : "You liked a style of reply",
      rationale: `You disliked ${l.n} ${l.n === 1 ? "reply" : "replies"} for this. The fix: ${l.text.split("\u2192").pop().trim()}.`,
      predicted: {says: "at most half as many replies with this problem", base_pct: 30, target_pct: 15},
      observed: {pct: 12.5, rated: 8, base_pct: 30, verdict: "helping"},
      models: {"deepseek-chat": 75, "deepseek-reasoner": 25}, domains: {"research & web": {n: 5, pct: 20}, "conversation": {n: 3, pct: 0}}});
    return [...found.values()].sort((a, b) => b.t - a.t).slice(0, 6).map(l => Object.assign(l, {sim: sim(l)}));
  }

  window.ThetaDemo = {fetch: demoFetch};
})();
