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

COPY backend/requirements.txt backend/requirements-dev.txt backend/requirements-browser.txt ./
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
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/playwright-browsers
RUN pip install --no-cache-dir --requirement requirements-browser.txt \
    && mkdir -p /opt/playwright-browsers \
    && PLAYWRIGHT_BROWSERS_PATH=/opt/playwright-browsers python -m playwright install --with-deps chromium \
    && chmod -R a+rX /opt/playwright-browsers
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