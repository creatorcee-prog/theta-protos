#!/bin/bash
# theta-protos on an Oracle Cloud "Always Free" Ampere machine (Ubuntu 24.04, arm64).
#
# Paste this whole file into Oracle's "Initialization script" box when you create the instance (Create compute
# instance > Show advanced options > Management > Paste cloud-init script). It runs once, as root, on first boot,
# and sets everything up: the Theta server, phone notifications, a private local model, and Tailscale so only
# your own devices can reach it. Steps for doing this from a phone: deploy/ORACLE.md.
#
# Fill in the lines between the two rulers below. Everything else can stay as it is.
# Note: Oracle keeps this script in the instance's settings, so anyone who can sign in to your Oracle account can
# read what you put here. Use a Tailscale key that expires, and keys with spending limits.
# ---------------------------------------------------------------------------------------------------------------
TAILSCALE_AUTHKEY=""     # Tailscale admin > Settings > Keys > Generate auth key (one-off, expires in 1 day)
PROTOS_KEY=""            # the password the app asks for: make it long and random (a password manager can make one)
DEEPSEEK_API_KEY=""      # at least one model key; DeepSeek is the cheapest that works well
ANTHROPIC_API_KEY=""     # optional
GEMINI_API_KEY=""        # optional
GROQ_API_KEY=""          # optional
TAVILY_API_KEY=""        # optional: live web search with sources
VAPID_SUBJECT="mailto:you@example.com"   # an email address of yours; Apple refuses pushes without a real-looking one
TZ_NAME="America/Denver"                 # your time zone (quiet hours and the 7 AM / 6 PM briefs use it)
VANTAGE_URL=""           # optional: https://<your Theta>/vantage, for Vantage alerts and briefs
VANTAGE_KEY=""           # optional: Theta's dashboard key, if VANTAGE_URL is set
GITHUB_TOKEN=""          # only if the theta-protos repo is private: a fine-grained token, this repo only, Contents: Read-only
BRANCH="claude/loving-brahmagupta-y86b04"   # change to "main" once the work is merged
LOCAL_MODEL="llama3.1:8b"   # private model on the machine; "" to skip (see ORACLE.md: it also keeps Oracle from
                            # treating the machine as idle and reclaiming it)
HOSTNAME_TS="theta"      # the name your phone will see: https://theta.<your-tailnet>.ts.net
# ---------------------------------------------------------------------------------------------------------------

set -uo pipefail
LOG=/var/log/theta-setup.log
exec > >(tee -a "$LOG") 2>&1
step() { echo "=== $(date -u +%H:%M:%S) $*"; echo "$*" > /var/lib/theta-setup-step; }
fail() { echo "!!! $*"; echo "FAILED: $*" > /var/lib/theta-setup-step; exit 1; }
REPO="github.com/creatorcee-prog/theta-protos"
export DEBIAN_FRONTEND=noninteractive

step "packages"
apt-get update -y && apt-get install -y git python3 python3-venv curl ca-certificates || fail "apt install"

step "the theta-protos user and code"
id theta-protos >/dev/null 2>&1 || useradd -r -s /usr/sbin/nologin theta-protos
if [ ! -d /opt/theta-protos/.git ]; then
  if [ -n "$GITHUB_TOKEN" ]; then URL="https://x-access-token:${GITHUB_TOKEN}@${REPO}"; else URL="https://${REPO}"; fi
  git clone --depth 1 --branch "$BRANCH" "$URL" /opt/theta-protos || fail "git clone (private repo? set GITHUB_TOKEN)"
  git -C /opt/theta-protos remote set-url origin "https://${REPO}"   # don't keep the token on disk
fi

step "python and phone notifications (pywebpush)"
python3 -m venv /opt/theta-protos/venv && /opt/theta-protos/venv/bin/pip install -q pywebpush || echo "pywebpush failed: chat works, push won't"

if [ -n "$LOCAL_MODEL" ]; then
  step "local model ($LOCAL_MODEL) with Ollama"
  curl -fsSL https://ollama.com/install.sh | sh || echo "ollama install failed: no local model"
  mkdir -p /etc/systemd/system/ollama.service.d
  # keep the model loaded all the time: instant private answers, and memory use stays above Oracle's idle line
  printf '[Service]\nEnvironment=OLLAMA_KEEP_ALIVE=-1\nEnvironment=OLLAMA_HOST=127.0.0.1:11434\n' > /etc/systemd/system/ollama.service.d/theta.conf
  systemctl daemon-reload && systemctl restart ollama
  sleep 5
  ollama pull "$LOCAL_MODEL" || echo "model pull failed"
  # load it once now; Theta's own calls keep it loaded after that
  curl -s http://127.0.0.1:11434/api/generate -d "{\"model\":\"$LOCAL_MODEL\",\"prompt\":\"hi\",\"keep_alive\":-1}" >/dev/null || true
  LOCAL_URL="http://127.0.0.1:11434/v1"
else
  LOCAL_URL=""
fi

step "settings file (/etc/theta-protos.env)"
cat > /etc/theta-protos.env <<ENV
PROTOS_KEY=${PROTOS_KEY}
DEEPSEEK_API_KEY=${DEEPSEEK_API_KEY}
ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
GEMINI_API_KEY=${GEMINI_API_KEY}
GROQ_API_KEY=${GROQ_API_KEY}
TAVILY_API_KEY=${TAVILY_API_KEY}
LOCAL_LLM_URL=${LOCAL_URL}
LOCAL_LLM_MODEL=${LOCAL_MODEL}
PROTOS_TZ=${TZ_NAME}
VAPID_SUBJECT=${VAPID_SUBJECT}
VANTAGE_URL=${VANTAGE_URL}
VANTAGE_KEY=${VANTAGE_KEY}
ENV
chown root:theta-protos /etc/theta-protos.env && chmod 640 /etc/theta-protos.env

step "the Theta service"
cp /opt/theta-protos/deploy/theta-protos.service /etc/systemd/system/
systemctl daemon-reload && systemctl enable --now theta-protos || fail "theta-protos service"
for i in $(seq 1 20); do curl -fs http://127.0.0.1:8780/api/health && break; sleep 2; done

step "Tailscale (private HTTPS for your phone)"
curl -fsSL https://tailscale.com/install.sh | sh || fail "tailscale install"
[ -n "$TAILSCALE_AUTHKEY" ] || fail "TAILSCALE_AUTHKEY is empty"
tailscale up --authkey="$TAILSCALE_AUTHKEY" --hostname="$HOSTNAME_TS" || fail "tailscale up (expired or used key?)"
tailscale serve --bg 8780 || echo "tailscale serve failed: turn on HTTPS certificates in the Tailscale admin (DNS page), then reboot the instance"

step "done"
echo "Theta is up. On your phone (Tailscale on): https://${HOSTNAME_TS}.<your-tailnet>.ts.net"
