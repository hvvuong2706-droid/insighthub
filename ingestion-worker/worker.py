"""ARQ worker: dequeues jobs api/app/routers/documents.py enqueues, and runs the
SAME process_document pipeline the API used to run inline (D13 — no second
pipeline). Structured JSON log only (D11, constitution Article 3.5 allowlist);
never print filename/content/raw exceptions.
"""

import asyncio
import json
import logging
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from typing import Any

from app.core.config import get_settings
from app.core.db import get_conn, healthcheck
from app.core.errors import DocumentNotFound, ProviderError, SchemaMismatch, ServiceError
from app.services.ingestion import process_document
from arq import Retry
from arq.connections import RedisSettings
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

RETRYABLE = (ProviderError, SchemaMismatch)
BACKOFF_SECONDS = (1, 2, 4)  # D5: 3 retries max, exponential.
HEALTH_PORT = 8081


def _log(event: str, **fields: object) -> None:
    print(
        json.dumps(
            {
                "event": event,
                "timestamp": datetime.now(UTC).isoformat(),
                **fields,
            }
        ),
        flush=True,
    )


async def run_ingestion(ctx: dict[str, Any], document_id: int, filename: str, content: bytes) -> None:
    job_try = ctx["job_try"]
    job_id = ctx["job_id"]
    try:
        chunk_count = await asyncio.to_thread(process_document, document_id, filename, content)
    except DocumentNotFound:
        # Document was deleted while the job waited in queue — not a failure.
        _log("ingestion_skipped", document_id=document_id, job_id=job_id, attempt=job_try)
        return
    except ServiceError as exc:
        if isinstance(exc, RETRYABLE) and job_try <= len(BACKOFF_SECONDS):
            _log(
                "ingestion_retry",
                document_id=document_id,
                job_id=job_id,
                attempt=job_try,
                error_code=exc.code,
            )
            raise Retry(defer=BACKOFF_SECONDS[job_try - 1]) from None
        _log(
            "ingestion_failed",
            document_id=document_id,
            job_id=job_id,
            attempt=job_try,
            status="failed",
            error_code=exc.code,
        )
        return
    except Exception:
        # process_document only raises ServiceError subclasses; this is a defensive
        # fallback for something failing before it even started (e.g. no DB connection).
        _log(
            "ingestion_failed",
            document_id=document_id,
            job_id=job_id,
            attempt=job_try,
            status="failed",
            error_code="internal_error",
        )
        return
    _log(
        "ingestion_completed",
        document_id=document_id,
        job_id=job_id,
        status="ready",
        chunk_count=chunk_count,
    )


class _HealthHandler(BaseHTTPRequestHandler):
    def log_message(self, *args: object) -> None:  # silence default access log (D11 spirit)
        pass

    def do_GET(self) -> None:
        if self.path == "/healthz":
            self._respond(200, b'{"status":"ok"}', "application/json")
        elif self.path == "/readyz":
            ok = healthcheck()
            body = b'{"status":"ready"}' if ok else b'{"status":"not_ready"}'
            self._respond(200 if ok else 503, body, "application/json")
        elif self.path == "/metrics":
            self._respond(200, generate_latest(), CONTENT_TYPE_LATEST)
        else:
            self._respond(404, b"", "text/plain")

    def _respond(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.end_headers()
        self.wfile.write(body)


_health_server: ThreadingHTTPServer | None = None


def silence_arq_job_logger() -> None:
    """Must run after arq's own logging.config.dictConfig(...), not at import time.

    arq's CLI imports this module (to build WorkerSettings) *before* calling
    dictConfig(default_log_config(...)); dictConfig resets any not-explicitly-
    listed logger's level back to NOTSET, silently undoing a module-level
    setLevel() call here. Confirmed by running a job end-to-end, seeing
    filename/content leak into the log, then reproducing and fixing it in
    isolation (see ingestion-worker/tests/test_log_no_leak.py).
    """
    logging.getLogger("arq.worker").setLevel(logging.CRITICAL)


async def on_startup(ctx: dict[str, Any]) -> None:
    global _health_server
    silence_arq_job_logger()
    get_settings()  # fail fast on bad config before accepting jobs
    with get_conn() as conn:
        conn.execute("SELECT 1")  # fail fast if Postgres is unreachable too
    _health_server = ThreadingHTTPServer(("0.0.0.0", HEALTH_PORT), _HealthHandler)
    Thread(target=_health_server.serve_forever, daemon=True).start()
    _log("worker_started", port=HEALTH_PORT)


async def on_shutdown(ctx: dict[str, Any]) -> None:
    if _health_server is not None:
        _health_server.shutdown()
    _log("worker_stopped")


class WorkerSettings:
    functions = [run_ingestion]
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    max_tries = len(BACKOFF_SECONDS) + 2  # safety net above our own controlled retries
    health_check_interval = 30
    on_startup = on_startup
    on_shutdown = on_shutdown
