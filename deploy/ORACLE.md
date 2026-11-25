# Theta on a free Oracle Cloud machine (from your phone)

This stands in for the Linux box until the box works again. The server is the same; later you copy
`/var/lib/theta-protos` to the box and nothing else changes. It takes about 30 minutes, mostly waiting.
Everything below works in a phone browser.

## What you get
- A small always-on Linux computer (Oracle's "Always Free" Ampere machine: 2 cores, 12 GB of memory, free with
  no time limit).
- Theta's server running on it, with phone notifications.
- A private AI model on the machine itself (Llama 3.1 8B), which Theta can use for private questions. It is slow,
  a few words a second, but nothing leaves the machine.
- Tailscale, so only your own devices can open it. There is no public address.

## One rule to know: Oracle reclaims idle free machines
Oracle treats a free machine as idle, and may take it back, when over 7 days its CPU, network **and** memory use
all stay under 20%. This is from [Oracle's Always Free page](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm).
An assistant waiting for messages is idle most of the time. The local model stays loaded in memory (about 5 of
the 12 GB), which keeps memory use above 20%. If you turn the local model off (`LOCAL_MODEL=""`), expect Oracle
to reclaim the machine sooner or later.

## 1. Sign up for Oracle Cloud
1. Go to oracle.com/cloud/free and sign up. It asks for a card to verify you; the Always Free tier doesn't charge it.
2. Pick a **home region** near you. Free machines can only be made in your home region, and you can't change it later.

## 2. Set up Tailscale
1. Install the Tailscale app on your iPhone and sign in. Use the same account for everything below.
2. In your phone browser, open login.tailscale.com/admin.
3. **DNS** page: turn on **MagicDNS** and **HTTPS Certificates**.
4. **Settings > Keys > Generate auth key**: not reusable, expires in 1 day. Copy it.

## 3. Fill in the setup script
1. Open `deploy/oracle-cloud-init.sh` in this repo (in the GitHub app, or github.com in a browser) and copy all of it into a notes app.
2. Fill in the lines at the top:
   - `TAILSCALE_AUTHKEY`: the key from step 2.
   - `PROTOS_KEY`: a long random password. Theta's app asks for it once.
   - `DEEPSEEK_API_KEY`: at least one model key. The others are optional.
   - `VAPID_SUBJECT`: `mailto:` plus an email address of yours.
   - `TZ_NAME`: your time zone.
   - `GITHUB_TOKEN`: only if this repo is private. On github.com go to Settings > Developer settings > Fine-grained
     tokens, then pick repository `theta-protos` with Contents: Read-only and a 7-day expiry.
   - `BRANCH`: leave as is until the work is merged into `main`.
3. Oracle keeps this script with the machine's settings, so anyone who can sign in to your Oracle account can read
   it. The Tailscale key expires on its own; give model keys a spending limit on their own sites.

## 4. Create the machine
In the Oracle console (cloud.oracle.com), go to **Compute > Instances > Create instance**:
1. **Image:** Change image > Ubuntu > **Canonical Ubuntu 24.04**.
2. **Shape:** Change shape > Ampere > **VM.Standard.A1.Flex**, with **2 OCPUs** and **12 GB** memory.
   It should say "Always Free-eligible".
3. **Networking:** keep the defaults.
4. **SSH keys:** "Generate a key pair for me" and save the private key (Files app). It's only needed if something
   goes wrong.
5. **Show advanced options > Management > Paste cloud-init script:** paste your filled-in script.
6. **Create.**

If it says **"Out of host capacity"**, free Ampere machines are temporarily full in your region. Try another
availability domain in the Placement section, or try again later. Oracle's page says the same.

## 5. Open Theta on your phone
1. Wait about 15 minutes. Downloading the local model takes most of that.
2. In the Tailscale app, a machine named **theta** appears.
3. With Tailscale on, open `https://theta.<your-tailnet>.ts.net` in Safari. The Tailscale app shows your tailnet name.
4. Sign in with your `PROTOS_KEY`.
5. Tap **Share > Add to Home Screen**. The dot-globe icon appears on your home screen.
6. Open Theta **from that icon**, go to Settings, and turn on notifications (needs iOS 16.4 or newer).

Pushes arrive even with Tailscale off; opening the app needs Tailscale on.

## If something doesn't work
- **No "theta" in Tailscale after 20 minutes:** the setup log is `/var/log/theta-setup.log` on the machine, and the
  last step it reached is in `/var/lib/theta-setup-step`. To read them from a phone: in the Oracle console, open
  **Cloud Shell** (the `>_` icon), upload your saved key, and run
  `ssh -i <key> ubuntu@<the instance's public IP> 'sudo cat /var/lib/theta-setup-step; sudo tail -50 /var/log/theta-setup.log'`.
  The usual causes are an expired Tailscale key, or the repo being private with no `GITHUB_TOKEN`.
- **The page doesn't open but the machine shows in Tailscale:** HTTPS certificates are off in the Tailscale admin
  (step 2.3). Turn them on, then reboot the instance from the Oracle console.
- **Change a key later:** edit `/etc/theta-protos.env` on the machine (`sudo nano /etc/theta-protos.env`),
  then run `sudo systemctl restart theta-protos`.
- **Update Theta:** `cd /opt/theta-protos && sudo git pull && sudo systemctl restart theta-protos`.

## Moving to the box later
On the box, follow `deploy/README.md`, then copy `/var/lib/theta-protos` from this machine to the same place on
the box. Chats, memory, reminders and the notification keys all move with it, so your phone keeps working.
