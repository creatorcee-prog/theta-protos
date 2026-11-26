# Theta on Railway (from your phone, about 10 minutes)

This stands in for the Linux box. The server runs exactly as it would on the box: replies stream, Theta texts you
first, and everything is kept in one database file on a Railway volume. Later you copy that file to the box.

**Cost:** the free trial is $5 of credit for 30 days. After that the Hobby plan is $5 a month and stays on all the time.
Railway's free plan puts services to sleep after a few minutes, and a sleeping Theta can't text you, so it doesn't
work for this. [Railway pricing](https://railway.com/pricing)

**Keys:** Railway stores the keys you give it, and it had a security incident recently. Make keys just for Theta,
give each one a spending limit on its own site, and revoke any key you stop using.

## 1. Create the service
1. Go to railway.com and sign in with GitHub.
2. Start a **New Project**, choose **Deploy from GitHub repo**, and pick **theta-protos**. If it isn't listed,
   tap the option to configure the GitHub app and give Railway access to that repo.
3. In the new service's **Settings > Source**, set the branch to `claude/loving-brahmagupta-y86b04`, or `main`
   once the work is merged.

Railway reads `railway.json` in the repo: it starts `python -m server`, checks `/api/health`, and restarts the
server if it ever stops.

## 2. Add a volume (where Theta's memory lives)
Add a **Volume** to the service and mount it at `/data`. Without a volume, every redeploy would wipe your chats,
reminders and memory. The server finds the volume on its own.

## 3. Add your keys
Open the service's **Variables** tab, switch to the raw editor, and paste:

```
PROTOS_KEY=<a long random password; the app asks for it once>
DEEPSEEK_API_KEY=<your key>
VAPID_SUBJECT=mailto:<an email address of yours>
PROTOS_TZ=America/Denver
```

Optional, add any you have:

```
ANTHROPIC_API_KEY=
GEMINI_API_KEY=
GROQ_API_KEY=
TAVILY_API_KEY=
VANTAGE_URL=https://<your Theta>/vantage
VANTAGE_KEY=<Theta's dashboard key>
```

To keep the notification keys Theta already uses, copy `VAPID_PUBLIC_KEY` and `VAPID_PRIVATE_KEY` from your
Vercel project. If you leave them out, a new pair is made once and kept on the volume.

The server **won't start** on Railway without `PROTOS_KEY`, because its address is public. After 20 wrong
passwords in 10 minutes, it refuses every sign-in for 10 minutes.

## 4. Get its address
Go to **Settings > Networking** and generate a domain. You get `https://<something>.up.railway.app`.
Wait for the deploy to show as active. The **Deployments** tab has its log, which lists the models it found.

## 5. Put it on your phone
1. Open the address in Safari and sign in with your `PROTOS_KEY`.
2. Tap **Share > Add to Home Screen** to get the dot-globe icon.
3. Open Theta **from that icon**, go to Settings, and turn on notifications (needs iOS 16.4 or newer).

## If something doesn't work
- **The deploy fails:** open the deploy's log. "PROTOS_KEY is not set" means step 3 is missing it. Otherwise,
  send me a screenshot of the last lines.
- **It says "Too many wrong keys":** wait 10 minutes, then sign in with the exact `PROTOS_KEY`.
- **Notifications don't arrive:** check that `VAPID_SUBJECT` is a real-looking email address, and that you opened
  Theta from the home-screen icon, not from Safari.

## Moving to the box later
Download `protos.db` from the volume, put it in `/var/lib/theta-protos/` on the box, and follow `deploy/README.md`.
