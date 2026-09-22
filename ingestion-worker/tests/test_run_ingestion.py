"""run_ingestion's retry/logging decisions, without a live DB/Redis."""

import asyncio
import io
import json
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from app.core.errors import (
    DocumentConflict,
    DocumentNotFound,
    InvalidDocument,
    ProviderError,
    SchemaMismatch,
)
from arq import Retry

import worker


def _run(document_id=1, filename="f.txt", content=b"x", job_try=1, job_id="job:1"):
    ctx = {"job_try": job_try, "job_id": job_id}
    buf = io.StringIO()
    with redirect_stdout(buf):
        result = asyncio.run(worker.run_ingestion(ctx, document_id, filename, content))
    lines = [json.loads(line) for line in buf.getvalue().splitlines() if line.strip()]
    return result, lines


class RunIngestionTests(unittest.TestCase):
    def test_success_logs_completed_with_chunk_count(self):
        with patch("worker.process_document", return_value=3):
            _, lines = _run()
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]["event"], "ingestion_completed")
        self.assertEqual(lines[0]["status"], "ready")
        self.assertEqual(lines[0]["chunk_count"], 3)

    def test_provider_error_retries_with_backoff_1_2_4(self):
        for job_try, expected_defer in ((1, 1), (2, 2), (3, 4)):
            with patch("worker.process_document", side_effect=ProviderError()):
                with self.assertRaises(Retry) as caught:
                    asyncio.run(worker.run_ingestion({"job_try": job_try, "job_id": "job:1"}, 1, "f.txt", b"x"))
                self.assertEqual(caught.exception.defer_score, expected_defer * 1000)

    def test_provider_error_stops_retrying_after_3_attempts(self):
        with patch("worker.process_document", side_effect=ProviderError()):
            result, lines = _run(job_try=4)
        self.assertIsNone(result)
        self.assertEqual(lines[0]["event"], "ingestion_failed")
        self.assertEqual(lines[0]["status"], "failed")
        self.assertEqual(lines[0]["error_code"], "provider_error")

    def test_schema_mismatch_is_retryable_too(self):
        with patch("worker.process_document", side_effect=SchemaMismatch()):
            with self.assertRaises(Retry):
                asyncio.run(worker.run_ingestion({"job_try": 1, "job_id": "job:1"}, 1, "f.txt", b"x"))

    def test_permanent_errors_never_retry(self):
        for exc in (InvalidDocument(), DocumentConflict()):
            with patch("worker.process_document", side_effect=exc):
                _, lines = _run(job_try=1)
            self.assertEqual(lines[0]["event"], "ingestion_failed")
            self.assertEqual(lines[0]["error_code"], exc.code)

    def test_document_not_found_is_skipped_not_failed(self):
        with patch("worker.process_document", side_effect=DocumentNotFound()):
            _, lines = _run()
        self.assertEqual(lines[0]["event"], "ingestion_skipped")
        self.assertNotIn("error_code", lines[0])

    def test_log_lines_never_contain_raw_content_or_filename(self):
        marker_filename = "SECRET_FILENAME_MARKER.txt"
        with patch("worker.process_document", return_value=1):
            _, lines = _run(filename=marker_filename, content=b"SECRET_CONTENT_MARKER")
        raw = json.dumps(lines)
        self.assertNotIn(marker_filename, raw)
        self.assertNotIn("SECRET_CONTENT_MARKER", raw)


if __name__ == "__main__":
    unittest.main()
