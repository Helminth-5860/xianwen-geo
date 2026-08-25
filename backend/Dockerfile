FROM python:3.12.12-slim-bookworm AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HOME=/home/app

WORKDIR /app

RUN addgroup --system app \
    && adduser --system --ingroup app --home /home/app app \
    && mkdir -p /home/app \
    && chown app:app /home/app

COPY backend/requirements.txt backend/requirements-dev.txt ./
RUN pip install --no-cache-dir --requirement requirements.txt

FROM base AS test
RUN pip install --no-cache-dir --requirement requirements-dev.txt
COPY --chown=app:app backend/ .
COPY --chown=app:app config/plan-limit-keys.json /config/plan-limit-keys.json
RUN sed -i 's/\r$//' /app/entrypoint.sh && chmod +x /app/entrypoint.sh
USER app
ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["python", "-m", "pytest"]

FROM base AS browser
ARG DEBIAN_MIRROR=http://deb.debian.org/debian
ARG DEBIAN_SECURITY_MIRROR=http://deb.debian.org/debian-security
ARG BROWSER_PIP_INDEX_URL=https://pypi.org/simple
COPY backend/requirements-browser.txt ./
RUN sed -i \
        -e "s|http://deb.debian.org/debian-security|${DEBIAN_SECURITY_MIRROR}|g" \
        -e "s|http://deb.debian.org/debian|${DEBIAN_MIRROR}|g" \
        /etc/apt/sources.list.d/debian.sources \
    && apt-get update \
    && apt-get install -y --no-install-recommends chromium fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir --index-url "$BROWSER_PIP_INDEX_URL" --requirement requirements-browser.txt \
    && PLAYWRIGHT_EXPECTED_CHROMIUM="$(python -c 'from playwright.sync_api import sync_playwright; p=sync_playwright().start(); print(p.chromium.executable_path); p.stop()')" \
    && mkdir -p "$(dirname "$PLAYWRIGHT_EXPECTED_CHROMIUM")" \
    && ln -sf /usr/bin/chromium "$PLAYWRIGHT_EXPECTED_CHROMIUM" \
    && chromium --version \
    && test -x "$PLAYWRIGHT_EXPECTED_CHROMIUM"
COPY --chown=app:app backend/ .
COPY --chown=app:app config/plan-limit-keys.json /config/plan-limit-keys.json
RUN sed -i 's/\r$//' /app/entrypoint.sh && chmod +x /app/entrypoint.sh
USER app
ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["celery", "-A", "config", "worker", "--loglevel=INFO", "--queues=browser_audit", "--concurrency=1", "--prefetch-multiplier=1"]

FROM base AS production
COPY --chown=app:app backend/ .
COPY --chown=app:app config/plan-limit-keys.json /config/plan-limit-keys.json
RUN sed -i 's/\r$//' /app/entrypoint.sh && chmod +x /app/entrypoint.sh
USER app
EXPOSE 8000
ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["gunicorn", "config.wsgi:application", "--bind=0.0.0.0:8000", "--workers=2", "--error-logfile=-"]
