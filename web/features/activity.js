/* activity: helpers for what Theta did on a turn (server: the `activity` stream events and a reply's meta.timing /
   meta.activity). app.js shows the status line; this only adds
     Theta.activitySummary(meta)     -> "Took 6s · read 3 emails · opened 1 site" (or "" with no timing)
     Theta.activityUsedBrowser(meta) -> true when the turn used Theta's browser (meta.live), so a tap can open the live view
     Theta.activityLog               -> the last 50 activity events this session saw, newest last: {id, text, state, kind, t, at}
   Plain functions, no DOM. */
(() => {
  "use strict";
  const T = window.Theta;
  if (!T) return;
  const log = [];
  T.on("activity", d => {
    if (!d || typeof d.text !== "string") return;
    log.push(Object.assign({}, d, {at: Date.now()}));
    if (log.length > 50) log.splice(0, log.length - 50);
  });

  const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;
  function took(ms) {
    const s = Math.max(1, Math.round((Number(ms) || 0) / 1000));
    return s < 60 ? `Took ${s}s` : `Took ${Math.floor(s / 60)}m ${s % 60}s`;
  }

  // what the texts say happened, in the order people care about; at most 3 parts after "Took Ns"
  function summary(meta) {
    meta = meta || {};
    const texts = Array.isArray(meta.activity) ? meta.activity.filter(t => typeof t === "string") : [];
    const timing = meta.timing || {};
    const parts = [];
    const count = re => texts.filter(t => re.test(t)).length;
    const emails = count(/^Reading an email/), inbox = count(/^Reading your inbox/);
    const sites = new Set(texts.filter(t => /^Opening /.test(t)).map(t => t.slice(8))).size;
    const searches = count(/^Searching the web/);
    const helpers = texts.reduce((n, t) => { const m = /^Waking (\d+) helpers/.exec(t); return n + (m ? +m[1] : /^Waking a helper/.test(t) ? 1 : 0); }, 0);
    if (emails) parts.push("read " + plural(emails, "email", "emails")); else if (inbox) parts.push("checked your inbox");
    if (sites) parts.push("opened " + plural(sites, "site", "sites"));
    if (helpers) parts.push(plural(helpers, "helper", "helpers"));
    if (searches) parts.push(searches === 1 ? "searched the web" : `searched the web ${searches} times`);
    if (count(/^Checking your calendar/)) parts.push("checked your calendar");
    if (count(/^Making the image/)) parts.push("made an image");
    if (count(/^Drafting the (email|reply)/)) parts.push("drafted an email");
    if (count(/^Setting the reminder/)) parts.push("set a reminder");
    if (count(/^Saving that to memory/)) parts.push("saved to memory");
    if (timing.total_ms == null) return parts.slice(0, 3).join(" · ");
    return [took(timing.total_ms)].concat(parts.slice(0, 3)).join(" · ");
  }

  T.activitySummary = summary;
  T.activityUsedBrowser = meta => !!(meta && (meta.live || (Array.isArray(meta.activity) && meta.activity.some(t => /^(Opening |Clicking |Typing into |Scrolling the page|Going back a page)/.test(t)))));
  T.activityLog = log;
})();
