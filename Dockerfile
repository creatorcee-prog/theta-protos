# Theta on Railway with a real browser (server/browser.py drives headless Chromium through Playwright).
# Railway builds this root Dockerfile on its own; railway.json still supplies the healthcheck and restart policy.
#
# The official Playwright image: Ubuntu 24.04 (noble), Python 3.12 as `python`/`python3`, pip, and the browsers'
# system libraries. The pip package below MUST stay the same version as the image tag, or Playwright looks for
# a Chromium build that isn't there.
FROM mcr.microsoft.com/playwright/python:v1.63.0-noble

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

# dependencies first, so code changes don't reinstall them
COPY requirements.txt .
RUN python3 -m pip install -r requirements.txt playwright==1.63.0 \
 && python3 -m playwright install chromium \
 && rm -rf /ms-playwright/firefox-* /ms-playwright/webkit-* \
 && python3 -c "import playwright, sys; print('playwright ok on', sys.version)"

# The Bitwarden CLI (server/bitwarden.py signs Theta's browser in with Bitwarden logins): the official standalone
# build, pinned and checked against its SHA-256 (taken from the GitHub release download, 2026-11-27).
ARG BW_VERSION=2026.10.1
ARG BW_SHA256=eb09c3715291c21cf744819b873a255c1247b1b8b45bae138621a644ec7ad8f5
RUN python3 -c "import hashlib, io, os, urllib.request, zipfile; \
v, want = os.environ['BW_VERSION'], os.environ['BW_SHA256']; \
data = urllib.request.urlopen(f'https://github.com/bitwarden/clients/releases/download/cli-v{v}/bw-linux-{v}.zip', timeout=120).read(); \
got = hashlib.sha256(data).hexdigest(); \
assert got == want, 'bw zip checksum mismatch: ' + got; \
zipfile.ZipFile(io.BytesIO(data)).extract('bw', '/usr/local/bin'); \
os.chmod('/usr/local/bin/bw', 0o755); print('bw', v, 'installed')"

COPY . .

# Railway sets PORT; the server reads it (default 8780). Data goes to the volume (RAILWAY_VOLUME_MOUNT_PATH).
EXPOSE 8780
CMD ["python", "-m", "server"]
