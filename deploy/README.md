# theta-protos on a Linux box

One service, `theta-protos.service` (system user `theta-protos`): `python3 -m server`, the app, the API and the
5-minute proactive tick (Theta texting first), with its SQLite database in `/var/lib/theta-protos`. The phone
reaches it over Tailscale (recommended) or a Cloudflare Tunnel; nothing listens on the open internet.

| file | what it is |
|---|---|
| `theta-protos.service` | the systemd unit: dedicated user, `PROTOS_DATA=/var/lib/theta-protos`, `Restart=always`, keys from `/etc/theta-protos.env` |
| `theta-protos.env.example` | every variable any module reads, with what it does |

## Install
```sh
sudo useradd -r -s /usr/sbin/nologin theta-protos
sudo git clone <this repo> /opt/theta-protos            # or copy the folder there
sudo python3 -m venv /opt/theta-protos/venv            # for phone notifications (pywebpush); optional
sudo /opt/theta-protos/venv/bin/pip install pywebpush
sudo cp /opt/theta-protos/deploy/theta-protos.env.example /etc/theta-protos.env
sudo chown root:theta-protos /etc/theta-protos.env && sudo chmod 640 /etc/theta-protos.env
sudoedit /etc/theta-protos.env                          # PROTOS_KEY, a model key, VAPID_SUBJECT, Vantage
sudo cp /opt/theta-protos/deploy/theta-protos.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now theta-protos
curl -s http://127.0.0.1:8780/api/health                # {"ok": true, ...}
journalctl -u theta-protos -f                           # its log
```
Needs Python 3.11+. Everything is standard library except push: without `pywebpush` the app still works, and
Settings says notifications need it. The unit puts `/opt/theta-protos/venv/bin` first on `PATH` when it exists,
so `python3 -m server` uses the venv. Update with `git pull` and `sudo systemctl restart theta-protos`.

Pick a long random `PROTOS_KEY` (`python3 -c "import secrets; print(secrets.token_urlsafe(32))"`): it is the
only lock on the API. VAPID keys can stay empty (a pair is made once and kept in the database); copy theta-app's
pair instead if you want the same keys as Theta.

Vantage: set `VANTAGE_URL=https://<theta>/vantage` and `VANTAGE_KEY=<Theta's dashboard key>`, or, on the same
box as a theta-app checkout, `VANTAGE_DIR=/opt/theta-app/vantage` (run in-process, files in
`/var/lib/theta-protos/vantage`). With neither there are no Vantage texts and no briefs.

## How the phone reaches it
The app is a PWA: installing it to the home screen and getting notifications need **HTTPS** (iPhone: iOS 16.4+,
opened from the Home Screen icon). The service listens on `127.0.0.1:8780` only; one of these puts HTTPS in front.

### Tailscale (recommended: private)
Only your own devices can reach it, there is no public URL, and Tailscale gives it a real certificate.
```sh
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
sudo tailscale serve --bg 8780          # https://<box>.<tailnet>.ts.net -> 127.0.0.1:8780
tailscale serve status
```
Turn on MagicDNS and HTTPS certificates in the Tailscale admin console (DNS page) if `serve` asks. On the phone:
install Tailscale, sign in to the same tailnet, open `https://<box>.<tailnet>.ts.net`, sign in with `PROTOS_KEY`,
then Share, Add to Home Screen. Open it from the icon and turn notifications on. Push still arrives when the
Tailscale app is off: Apple and Google deliver it; only opening the app needs the tailnet.

### Cloudflare Tunnel (when the phone can't run Tailscale)
A public HTTPS URL with no open ports on the box. Anyone can reach the sign-in page, so `PROTOS_KEY` must be
set; Cloudflare Access (Zero Trust, an email one-time PIN in front of the hostname) is a good second lock.
```sh
# install cloudflared from Cloudflare's package repo, then:
cloudflared tunnel login
cloudflared tunnel create theta-protos
cloudflared tunnel route dns theta-protos theta.example.com
cat <<'YAML' | sudo tee /etc/cloudflared/config.yml
tunnel: theta-protos
credentials-file: /etc/cloudflared/<tunnel-id>.json
ingress:
  - hostname: theta.example.com
    service: http://127.0.0.1:8780
  - service: http_status:404
YAML
sudo cloudflared service install && sudo systemctl enable --now cloudflared
```
Server-Sent Events (the streamed replies) pass through both; keep any Cloudflare buffering or caching off for `/api/`.

## Why these pieces
- **systemd** keeps it alive (`Restart=always`) and walls it in: it can write its own state (`/var/lib/theta-protos`),
  nothing else (`ProtectSystem=strict`, `ProtectHome`), the same shape as Theta OS's `os/linux/theta.service`.
- **SQLite, local**: no metered per-command store (Theta went down when its hosted Redis ran out of free commands).
- **127.0.0.1 + a tunnel**: no port forwarding, no certificate to renew by hand.
