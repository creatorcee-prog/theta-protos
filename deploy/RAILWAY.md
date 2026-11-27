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
3. The service deploys from `main`, which has everything.

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

Leave `VAPID_PUBLIC_KEY` and `VAPID_PRIVATE_KEY` out. They are a matched pair of encryption keys, not passwords:
on first start the server makes a valid pair and keeps it on the volume. Copying Theta's pair from Vercel doesn't
help, because Vercel won't show sensitive values, and the phone signs up again for a new address anyway.

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

## Web browsing: Theta's own browser (the Dockerfile)
Theta can open websites itself, read them and fill in forms, using a headless Chromium. The repo has a `Dockerfile`
for this, and Railway builds a Dockerfile at the repo's root automatically (the deploy log says "Using detected
Dockerfile"). It starts from the official Playwright image, so Chromium and everything it needs are already inside.
`railway.json` still supplies the start check (`/api/health`) and the restart policy.

- **Memory costs money.** Chromium uses a few hundred MB of RAM while a page is open (often 200 to 500 MB, more on
  heavy sites), and Railway bills RAM by the minute. Theta keeps one browser tab set per conversation and closes it
  after 5 idle minutes; when nothing is open, it closes Chromium completely, so the idle cost is the server alone
  (about 50 MB).
- **The image is big** (about 2 GB), so the first build takes a few minutes. Later builds reuse it.
- **To turn browsing off** without changing the build, add the variable `THETA_BROWSER=0`.
- **Safety:** Theta only opens public `http`/`https` sites, never addresses on private networks (including
  Railway's internal network). Anything that submits, buys, books, posts, signs up, deletes or sends waits for
  your Approve tap, with the exact fields shown (passwords and card numbers masked). The model never types a
  password: logins come from 1Password or Bitwarden (below), or you sign in yourself on Theta's screen.
- **Theta's screen:** while Theta browses, a small live picture floats above the chat; tap it (or ••• > Theta's
  screen) to watch full size and take over: tap, swipe, type. Sites stay signed in between chats (cookies kept in
  the volume, owner-only); Settings > Security > Theta's browser > Sign out forgets them all.
- **Browser first:** for anything done on a website, Theta does it there itself. Connected apps (Gmail, Calendar,
  Drive, texts, bank) still go through their APIs first: faster, surer, and Google often refuses sign-ins from
  automated browsers.

## Phone calls and texts (Telnyx)
Calls, texts and call recordings go through Telnyx. (Twilio still works if its variables are set and Telnyx's
aren't, but Telnyx is the one to use.) About 15 minutes in a browser, once.

1. **Make a Telnyx account** at telnyx.com and add a payment method.
2. **Buy a number** with voice and SMS: **Numbers > Buy Numbers**.
3. **Calls:** **Voice > Programmable Voice > TeXML Applications > Add**. Any name. Voice URL:
   `https://<your app>.up.railway.app/api/calls/inbound`, method POST (that only answers people who call the number;
   Theta tells Telnyx where each call it makes should go). Save, then assign your number to this application.
   Copy the application's **ID**.
4. **Texts:** **Messaging > Messaging Profiles > Add**. Webhook URL:
   `https://<your app>.up.railway.app/api/texts/inbound`, webhook API version **2**. Assign your number to it.
   For US texting, register it for **A2P 10DLC** under **Messaging > 10DLC** (a sole proprietor brand is the one for
   a personal project); carriers block unregistered app texts.
5. **Keys:** **Account > API Keys > Create** (copy it), and **Account > Public Key** (copy it; Theta uses it to
   check that requests really come from Telnyx).
6. On Railway, add:
   ```
   TELNYX_API_KEY=KEY...
   TELNYX_FROM=+1...                   (the number you bought)
   TELNYX_TEXML_APP_ID=...             (step 3)
   TELNYX_PUBLIC_KEY=...               (step 5)
   PROTOS_PUBLIC_URL=https://<something>.up.railway.app
   ```
   Optional: `TELNYX_MESSAGING_PROFILE_ID`, `THETA_USER_PHONE=+1...`, `THETA_USER_NAME=Sam` (or set both in the app).
7. **In the app:** Settings > Apps > Phone calls. Enter your number and name, pick a **Voice**, and tap
   **Test call**.

**The voice:** the presets are natural voices (Amazon Polly neural, through Telnyx). For a voice of your own, use
ElevenLabs (a paid plan): in Telnyx, **Integration Secrets > Add**, paste your ElevenLabs API key and give the secret
a name; then in Theta pick **My own ElevenLabs voice**, paste the voice ID from ElevenLabs > Voices, and the secret's
name.
Or use **Fish Audio**: pick **My own Fish Audio voice**, paste the voice's ID from its page on fish.audio, and choose
a model (`s2.1-pro`, `s2-pro` or `s1`). If Telnyx asks for your Fish Audio key, add it under Integration Secrets the
same way and enter the secret's name.

**Recording:** on by default (Settings > Apps > Phone calls > Record calls). Calls to others open with "This call is
recorded."; if they object, Theta stops and keeps none of it. Audio is kept 90 days.

**Limits Theta keeps on its own:** never emergency or premium numbers; calls to others only from 8:00 to 21:00 your
time, at most 5 a day (the `calls_daily_cap` setting); never the same number twice within 10 minutes; each call to
someone else hangs up after 10 turns or 5 minutes; at most 20 texts a day.

**If calls don't work:** "Telnyx refused it" says why. If the phone rings but goes silent, check
`PROTOS_PUBLIC_URL` is exactly the app's address and the TeXML application's ID is right.

## Bank accounts (SimpleFIN, read-only)
Theta can read balances and transactions (never move money) through SimpleFIN Bridge, a small paid service for
personal apps.
1. Sign up at bridge.simplefin.org and link your banks and cards there.
2. Make a **setup token** (Bridge > Apps > New connection) and copy it.
3. In Theta: Settings > Apps > Bank accounts, paste it, tap **Connect**. Done; nothing to set on Railway.
SimpleFIN updates about once a day, so balances can be up to a day old. To cut access, tap Disconnect, and revoke
the connection at bridge.simplefin.org.

## 1Password (Theta's browser signs in for you)
Theta never sees the passwords: it fills them into the site itself, and only on the site the login belongs to.
1. In 1Password, make a vault named **Theta** and put in only the logins you want Theta to use (each with the
   site's address saved on it).
2. developer.1password.com > **Service accounts** > create one with read access to the Theta vault. Copy its token.
3. On Railway, add `OP_SERVICE_ACCOUNT_TOKEN=ops_...` and deploy.
Then ask Theta to do something behind a login ("check my water bill"); it opens the site and signs in.

## Bitwarden (the same, from your Bitwarden vault)
Theta uses the official Bitwarden CLI (the Dockerfile installs it), so it needs to log in and unlock like you do.
1. Safest: a **separate Bitwarden account** holding only the logins Theta should use (share them to it from your
   own vault). Or use a folder in your own account (step 3), knowing the master password opens everything.
2. Bitwarden web vault > **Settings > Security > Keys > View API key**: copy `client_id` and `client_secret`.
3. On Railway, add and deploy:
   ```
   BW_CLIENTID=user.xxxx
   BW_CLIENTSECRET=...
   BW_PASSWORD=...            (that account's master password, used only to unlock)
   BW_FOLDER=Theta            (optional: only logins in this folder)
   BW_SERVER=https://vault.bitwarden.eu   (only for the EU cloud or a self-hosted server)
   ```
Each login needs the site's address saved on it. One-time codes: if the login has an authenticator key saved,
Theta fills the current code itself.

## Google: Gmail, Calendar, Drive, Docs and Slides
One Google sign-in covers all of them. It takes about 15 minutes in a browser, once.
1. Open console.cloud.google.com and create a project (any name, e.g. "Theta").
2. **APIs & Services → Library**: enable **Gmail API**, **Google Calendar API**, **Google Drive API**,
   **Google Docs API**, **Google Slides API** and **People API** (Google Contacts).
3. **Google Auth Platform** (the OAuth consent screen):
   - **Branding:** app name "Theta", with your email as both the support and the developer contact.
   - **Audience:** user type **External**, publishing status **Testing**. Under **Test users**, add your own
     Google address.
   - **Data access:** add the Gmail (modify, send), Calendar (events, readonly), Drive (full `drive`, plus file and
     readonly), Docs, Slides, Contacts (`contacts.readonly`) and Gmail filters (`gmail.settings.basic`) scopes, plus
     openid and email.
4. **Clients → Create client → Web application.** Under authorized redirect URIs add exactly
   `https://<your app>.up.railway.app/api/google/callback` (https, no slash at the end). Copy the client ID and
   the secret.
5. On Railway, add these variables:
   ```
   GOOGLE_CLIENT_ID=<...>.apps.googleusercontent.com
   GOOGLE_CLIENT_SECRET=<...>
   PROTOS_PUBLIC_URL=https://<your app>.up.railway.app
   ```
6. In Theta, open **Settings → Connections**, tap **Connect** on Gmail, Calendar or Drive, sign in, and allow every box.
   Google warns that the app isn't verified. It's your own app, so choose Continue.

In Testing mode, Google ends the sign-in every 7 days
([Google's docs](https://developers.google.com/identity/protocols/oauth2#expiration)). Theta then says it was
signed out and shows Connect again; one tap fixes it. Publishing the app avoids this, but Google then requires
its verification process for Gmail access.

## Images
Images use your Gemini key (`GEMINI_API_KEY`). The model defaults to `gemini-2.5-flash-image`. If Google
renames it, set `GEMINI_IMAGE_MODEL`. Theta makes at most 10 images a day; change that in Settings.
