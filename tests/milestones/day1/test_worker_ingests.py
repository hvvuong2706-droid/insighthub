"""MH7: the ingestion-worker must pick the job up and reach 'ready' within 30s."""

import time

from _common import unique_filename, upload_json, wait_for_status


def test_worker_ingests():
    filename = unique_filename()
    status, doc = upload_json(filename, b"Ingestion worker milestone content for Day 1.")
    assert status == 202, f"expected 202, got {status}: {doc}"
    document_id = doc["id"]

    started = time.monotonic()
    final = wait_for_status(document_id, {"ready", "failed"}, deadline_seconds=30)
    elapsed = time.monotonic() - started

    print(f"\n[test_worker_ingests] id={document_id} -> {final['status']} after {elapsed:.2f}s")

    assert final["status"] == "ready", f"document ended {final['status']!r}, not ready: {final}"
    assert final["chunk_count"] > 0
    assert elapsed < 30.0
