# Stage 5: feels like iMessage, acts like a person, shows its work

The visual identity stays: the dot-globe, the dark theme and the cyan/indigo accents. The goal is for the app to
feel built by Apple, use texting conventions everyone already knows, and keep honest about what it's doing.

## Who owns what (nobody edits another builder's files)

| Builder | Owns | Builds |
|---|---|---|
| A: Texting | `web/app.js`, `web/style.css`, `web/index.html`, `web/demo.js`, `web/haptics.js` (new), `server/uploads.py` (new feature), `server/gifs.py` (new feature) | The iMessage look and feel, reactions and effects, photos, GIFs, haptics, human pacing on screen |
| B: Activity | `server/app.py`, `server/agent.py`, `server/browser.py`, `web/features/activity.js` (new), `web/features/live.js` (new) | Activity events, timing, the live view of Theta's browser with control |
| C: Cards | `server/cards.py` (new feature), `server/onboarding.py` (new feature), `server/tools.py` (only the not-connected errors), `web/features/cards.js` (new), `web/features/onboarding.js` (new) | The card kit, connect cards, onboarding |

New feature modules go in `ext.FEATURES` and `web/features.js`. Each builder may add one line to each of those
two lists; nothing else in them changes.

## Contracts between builders

- **Stream events.** In addition to user / route / ack / tool / delta / done / error, B adds:
  - `event: activity`, `data: {"id", "text", "state": "start"|"done", "kind", "t"}`. The text is human, e.g.
    "Reading your inbox", "Waking 3 helpers", "Opening example.com", "Drafting the email". kind is one of
    think | search | read | write | browse | helpers | call | image.
  - `done` keeps the Message as before. Its `meta.timing` is `{"total_ms", "first_ms"}` and its `meta.activity`
    is the list of activity texts.
  - Features listen with `Theta.on("activity", fn)`.
- **The status line.** A shows the latest activity as a small line under the pending globe while Theta works:
  "Reading your inbox · 4s". After the reply it becomes "Took 6s · read 3 emails" under the reply. That line is
  an element with class `activity-line` and `data-msg=<id>`. When it's tapped while Theta was using the browser,
  A calls `Theta.emit("activity-tap", {message, live: true})`. B's `live.js` listens with
  `Theta.on("activity-tap", ...)` and opens the live view.
  - A adds `emit(ev, data)` to window.Theta, calling the same `listeners` as stream events.
- **Cards.** `meta.cards = [{type, ...}]`. Server tools append to `ctx["cards"]`; app.py already copies those
  into the reply. In the app, C registers each type with `Theta.card(type, fn)` and returns an element. A styles
  the card frame only (`.card`); C styles the inside.
- **Reactions** (A).
  - `POST /api/messages/react` `{id, emoji, by: "user"}`, stored in `meta.reactions` `{user: "heart", theta: "haha"}`.
  - B's agent may react on Theta's behalf. A exposes `reactions.set(msg_id, "theta", kind)` in `server/uploads.py`
    (or `server/reactions.py` if cleaner) for that, and A owns that file.
- **Pacing** (A, in the app).
  - A short, chatty reply arrives as one or a few bubbles, split on paragraph breaks only when each part is
    short. The bubbles land with a natural typing delay: about 30–45 ms a character, capped at about 1.8 s per
    bubble.
  - Long, detailed answers stream as now.
  - Nothing is invented. The text is exactly what the model wrote.

## Honesty rules (everyone)

- **Pacing:** the delay is presentation only. It never pretends Theta is doing work it isn't.
- **Activity text:** says what is really happening.
- **Not connected or failing:** say so plainly and show the connect card. Never make up a result.
- **Live view:** shows the real browser.
