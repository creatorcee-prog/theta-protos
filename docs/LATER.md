# Saved for later

## Check once the phone is on the latest build
- Settings in Theta, at the bottom, shows `Theta v0.1.0 (<commit>)`. The commit should match the newest one on `main`.
- With that build, test the keyboard: tap the chat box and the home Search box. Nothing should slide up or leave
  a blank gap. If it still does, send a screenshot with the keyboard open, plus that Settings line.

## Accounts to set up (steps in deploy/RAILWAY.md)
- **Google** (Gmail, Calendar, Drive, Docs, Slides):
  1. Make a Google Cloud project and enable the 5 APIs.
  2. Set the consent screen to Testing, with yourself as a test user.
  3. Create a Web client with redirect `https://<app>/api/google/callback`.
  4. On Railway, set `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` and `PROTOS_PUBLIC_URL`.
- **Images:** `GEMINI_API_KEY` on Railway.
- **Phone calls:** a Twilio account and number, then `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN` and `TWILIO_FROM`
  on Railway. Trial accounts can only call verified numbers.
- **Web search:** `TAVILY_API_KEY`, for live facts with sources and research helpers that check the web.
- Then re-run the live walkthrough of every feature against the real services.

## Later features
- Slack connector.
- Tighten the browser's address checks: DNS rebinding, WebSockets, and the first hop of a redirect.
- Show the leave-by time in 12-hour format.
- Theta's own Linux box: move from Railway by copying `protos.db` (deploy/README.md).
