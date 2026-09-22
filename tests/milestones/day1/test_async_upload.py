"""MH6: POST /documents must return 202 in under 1s — not block on processing."""

import time

from _common import unique_filename, upload_json


def test_async_upload():
    filename = unique_filename()
    started = time.monotonic()
    status, doc = upload_json(filename, b"InsightHub Day 1 milestone content.")
    elapsed = time.monotonic() - started

    print(f"\n[test_async_upload] POST /documents -> {status} in {elapsed:.3f}s, id={doc.get('id')}")

    assert status == 202, f"expected 202, got {status}: {doc}"
    assert elapsed < 1.0, f"upload took {elapsed:.3f}s, must be <1s (MH6)"
    assert doc["filename"] == filename
    assert doc["status"] in {"pending", "queued", "processing", "ready"}
    assert doc["chunk_count"] in (0, None) or doc["status"] == "ready"
