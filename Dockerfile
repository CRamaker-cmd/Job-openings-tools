# Job Hunter - runs the same on a Raspberry Pi (arm64), a PC or a server (amd64).
#   docker compose up -d                       # with browser scraping (bigger image, ~600 MB)
#   docker compose build --build-arg WITH_BROWSER=0   # slim image, no Google/Meta/Apple/Microsoft scraping
FROM python:3.12-slim-bookworm

ARG WITH_BROWSER=1
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1 TZ=Europe/Amsterdam

# Debian's own chromium exists for both arm64 and amd64, so no Playwright browser download is needed.
# (The slim variant installs nothing from apt.)
RUN if [ "$WITH_BROWSER" = "1" ]; then \
      apt-get update && apt-get install -y --no-install-recommends chromium fonts-liberation tzdata \
      && rm -rf /var/lib/apt/lists/*; \
    fi

WORKDIR /app
COPY requirements.txt requirements-browser.txt ./
RUN pip install -r requirements.txt \
    && if [ "$WITH_BROWSER" = "1" ]; then pip install -r requirements-browser.txt; fi

COPY jobhunter ./jobhunter
COPY config.example.yaml ./

# Run as an unprivileged user; /app/data is the only place that is written to (the volume).
RUN useradd --create-home --uid 1000 app && mkdir -p /app/data && chown -R app:app /app/data
USER app
ENV JOBHUNTER_CHROMIUM=/usr/bin/chromium
VOLUME /app/data
EXPOSE 8787

HEALTHCHECK --interval=60s --timeout=10s --start-period=30s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8787/status', timeout=8).status==200 else 1)"

CMD ["python", "-m", "jobhunter", "serve"]
