# Theta (theta-protos): handoff

The state of the project as of 2026-11-26, at build `c3392ff` on `main` (app and server version 0.4.0). Read this
first, then `docs/SPEC.md` (the API), `docs/FEATURES.md` (how features plug in) and `docs/LATER.md` (saved for
later).

## What Theta is
- A personal assistant you text, like iMessage: a phone app (a home-screen web app) plus a Python server.
- It picks a model per message and answers in one voice (Theta's persona, `persona/SOUL.md`).
- It texts you first (Vantage alerts, briefs, reminders, routines) and does real work through tools, with an
  Approve tap for anything that sends, buys or deletes.
- **Repos:**
  - `creatorcee-prog/theta-protos`: this app.
  - `creatorcee-prog/theta-app`: the older Theta on Vercel, which hosts Vantage.
- **Branches:** work happens on `claude/loving-brahmagupta-y86b04`, and finished work is pushed to `main`.
  Railway deploys `main`.

## Where it runs
- **Railway:** https://theta-protos-production.up.railway.app
  - It builds from the `Dockerfile` (a Playwright image, so Theta's browser works). railway.json sets the
    build, the start command `python -m server`, the health check `/api/health` and restart-always.
  - **Data:** one SQLite file on the Railway volume mounted at `/data` (`RAILWAY_VOLUME_MOUNT_PATH`). To move to
    another host, copy `protos.db`.
  - **Variables set now:** `PROTOS_KEY`, `DEEPSEEK_API_KEY`, `VAPID_SUBJECT`, `PROTOS_TZ`.
  - **Check what's deployed:** `/api/health` shows `version` and `build`. The app shows both under "Theta" on
    the sign-in page and at the bottom of Settings.
- **The phone:** the user installed the app from Safari (Add to Home Screen). It updates itself on the next
  open; the service-worker cache is v10.
- **The Linux box** (the long-term home, `deploy/README.md`) is down: its motherboard is broken. Railway stands
  in until it's fixed.
- **Not used:** the free Oracle Cloud route (`deploy/ORACLE.md`, `deploy/oracle-cloud-init.sh`). The user
  gave up on it after setup problems.

## Done and live (on `main`)

### Core
- **Server:** `server/app.py`, Python standard library plus `pywebpush` and Playwright.
- **Model routing** (`router.py`): quick, think, code, search, vision and local tiers across DeepSeek,
  Anthropic, Gemini, Groq and a local model, with fallback, stickiness and a router classifier.
- **Persona** (`persona.py`):
  - one stable system prompt (cache-friendly), with volatile context put last
  - the style rules, including Wikipedia's "Signs of AI writing" list
  - the lessons learned from likes and dislikes
- **Clean-up pass** (`persona.clean` and `Cleaner`) strips the unmistakable AI-writing signs from every reply:
  - openers and sign-offs
  - em dashes (also while streaming)
  - curly quotes
  - "it's important to note"
  - "In conclusion"
  - "delve into"
  - chatbot link tags
- **Agent loop** (`agent.py`):
  - a step cap and per-tool time limits
  - approval cards for "send" tools; if the needed service isn't connected, the connect card comes with the draft
  - ack-then-result ("On it.")
- **Tools on every message except small talk** (`tools.relevant`): small talk stays on the instant
  streaming path.
- **Memory:** an editable memory block, summaries of old turns, and history search (`memory.py`).
- **Turn log** with tokens and cost; 26 golden conversations in `evals/` (`evals/run.py`).
- **The feature plug-in system** (`server/ext.py`, `window.Theta` in `web/app.js`, `web/features.js`).

### Features (`server/<name>.py`, plus `web/features/<name>.js` where there's a screen)
- **Push and proactive:** Vantage events and briefs as texts plus push, with quiet hours, a daily cap and Red
  waking you (`push.py`, `proactive.py`, `vantage.py`).
- **Routines:** plain-words schedules, plus triggers on emails and on Vantage Red (`routines.py`).
- **Saved workflows:** the "Save as a workflow" chip (`workflows.py`).
- **Research helpers:** read-only, running in parallel, with a daily cost cap (`subagents.py`).
- **Images:** Gemini (`media.py`); needs `GEMINI_API_KEY`.
- **Google:** Gmail, Calendar, Drive, Docs and Slides, with OAuth (`google.py`); in-app calendar and calendar
  links (`gcal.py`). Not connected yet.
- **Theta's own browser:** Playwright. Submits need approval and passwords are refused (`browser.py`).
- **Phone calls:** Twilio (`calls.py`). Not set up yet.
- **Face ID sign-in:** passkeys (`passkeys.py`).
- **Cards** (`cards.py`, `web/features/cards.js`):
  - **The kit:** 13 types, plus the `show_card` tool and a weather tool (Open-Meteo, no key needed).
  - **Code-made cards that appear every time they apply:**
    - a link card when a page is opened
    - event cards from the calendar
    - an email card when one is read
    - a weather card
    - a connect card whenever something isn't connected, even with no tool call
  - **Structure in a reply becomes a card:** a numbered list → steps, a short list → checklist, a markdown
    table → table.
  - **When a message's shape calls for a card and none was made,** one quick-model call fills it (`fits` /
    `cardify`). Live: 6 of 6 indirect messages got a card.
- **Message actions:**
  - token use under each reply
  - long-press bar with tapbacks, Copy, Copy with prompt, Like/Dislike (with reasons that become lessons),
    Sources, Edit and the Model line
  - inline source pills
  - editing your last message
- **Texting feel (0.4):**
  - grouping and tails, time separators, swipe left for times, Delivered/Read
  - human pacing
  - tapbacks (`reactions.py`)
  - screen effects and bubble effects
  - photo uploads to the vision tier (`uploads.py`)
  - GIFs (`gifs.py`; needs `GIPHY_API_KEY`)
  - haptics (`web/haptics.js`)
  - the keyboard docking onto iOS's keyboard bar
- **App shell:**
  - splash: full once a day, then about 1 s
  - version line, self-updating service worker
  - 401 lockout after 20 wrong keys in 10 minutes
  - the server refuses to start on Railway without `PROTOS_KEY`

### Tests
- **Python:** `for t in tests/test_*.py; do python3 $t; done` (27 files, all passing; lines starting `FAIL`
  are failures).
- **Web:** `node tests/shots.js` (headless iPhone checks and screenshots) and `python3 tests/test_web.py`.
- **Live checks:** `DEEPSEEK_API_KEY=sk-dummy` works in the Claude sandbox, because its proxy injects the key.

## In the middle of (paused, saved, not running)
- **Stage 5 B (activity line and live view)** and **stage 5 C onboarding** are saved in commit `75eb145`.
  Commit `01291a1` set them aside. The card kit from C has already been restored and is live.
  - **B:**
    - honest `activity` stream events ("Reading your inbox · 4s", "Waking 3 helpers")
    - `meta.timing` and "Took 6s · …" under replies
    - tapping that line opens a live view of Theta's browser that the user can control (`server/live.py`,
      `web/features/activity.js`, `web/features/live.js`, and changes to `app.py`, `agent.py` and `browser.py`)
    - it was stopped partway: check it against current `app.py`/`agent.py` before restoring
  - **C onboarding:** Theta texts you through setup in the chat: name, time zone, notifications, Face ID,
    location, Google, a first routine and a tour (`server/onboarding.py`, `web/features/onboarding.js`).
    `onboarding.js` may be incomplete.
  - **To resume:** `git checkout 75eb145 -- <those files>`, then add "live", "onboarding" (server) and
    "activity", "live", "onboarding" (web) back to `ext.FEATURES` and `web/features.js` (they're commented out
    there), then run the suite.
- **Stage 5 A leftovers:** the app.js side of the activity line exists and waits for B's events. Pacing,
  effects and tapbacks need a real-phone check.

## Not verified yet
- **Not tried on the user's phone:** the 0.4 texting look, tapbacks, effects, haptics and the keyboard docking
  (the earlier keyboard fix was confirmed working).
- **Weather card live:** the weather service rate-limits the Claude sandbox, so it's tested with simulated
  data only.
- **Needs accounts the user hasn't set up:** Google sign-in, Twilio calls, Gemini images and GIPHY GIFs. All
  are tested against simulated services only.

## Yet to do (the user's asks, in order of what's next)
1. **Accounts** (steps in `deploy/RAILWAY.md`; they go on Railway's Variables tab):
   - Google: `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `PROTOS_PUBLIC_URL`
   - `GEMINI_API_KEY`
   - `TAVILY_API_KEY` (web search)
   - `GIPHY_API_KEY`
   - Twilio: `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM`

   Then re-run the live walkthrough with screenshots.
2. **Resume the paused work:** B (activity line and the live view of Theta's screen) and C (onboarding).
3. **From `docs/LATER.md`:**
   - **Slack connector**
   - **Password vault:** Bitwarden or 1Password through placeholders the model never sees.
   - **Tighter browser address checks:** DNS rebinding, WebSockets, the first hop of a redirect.
   - **12-hour time** in the leave-by text.
   - **A native iPhone app** (Capacitor): removes iOS's keyboard bar and gives full haptics. Needs an Apple
     developer account.
   - **Move to the Linux box** once it's fixed.
4. **Small known issues:**
   - The "Save as a workflow" chip names the workflow from the raw message.
   - The research helpers and the search tier can't check the live web until Tavily is set.

## Related: the old Theta (theta-app on Vercel)
- **Its Upstash Redis hit the free plan's monthly command limit** and refuses requests until the reset
  (around Dec 1) or an upgrade.
- **Fixes merged there** (PRs #154 and #155) batch Vantage's storage and show the database's reason on a
  readable error page.
- **Vantage lives there.** After the reset, set `VANTAGE_URL` and `VANTAGE_KEY` on Railway to get Vantage texts
  and briefs.
- **Change its `DASHBOARD_KEY`:** the current one appeared in Vercel's request logs.

## Working agreements with the user
- **Usage:** they have low usage limits. Keep at most 3 builder agents at once, and prefer doing the work
  directly when limits are tight.
- **Before pushing:** run the full suite and the app's screenshot checks.
- **Screenshots:** send them for anything visual.
- **Reporting:** say plainly what was and wasn't verified.
- **Commits:** end with the attribution lines in the session's instructions. Never put model names in commits.
