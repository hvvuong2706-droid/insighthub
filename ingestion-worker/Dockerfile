# InsightHub ingestion-worker (Day 1). Imports api/app unmodified (D13) —
# build context is the repo root so this stage can COPY it in.
FROM python:3.12.14-slim@sha256:78387bc3881b8273120a12ebe6c1ab22b018ccc2c9adf565ae1ac9b536e184ea AS base
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app

FROM base AS deps
COPY ingestion-worker/requirements.txt .
RUN pip install --no-cache-dir --require-hashes -r requirements.txt

FROM base AS runtime
RUN groupadd --system --gid 1001 workeruser \
    && useradd --system --uid 1001 --gid workeruser workeruser
COPY --from=deps /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=deps /usr/local/bin /usr/local/bin
COPY --chown=workeruser:workeruser api/app ./app
COPY --chown=workeruser:workeruser ingestion-worker/worker.py .
COPY --chown=workeruser:workeruser ingestion-worker/tests ./tests
USER workeruser
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8081/readyz', timeout=2)" || exit 1
CMD ["arq", "worker.WorkerSettings"]
