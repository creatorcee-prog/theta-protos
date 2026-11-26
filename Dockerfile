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

COPY . .

# Railway sets PORT; the server reads it (default 8780). Data goes to the volume (RAILWAY_VOLUME_MOUNT_PATH).
EXPOSE 8780
CMD ["python", "-m", "server"]
