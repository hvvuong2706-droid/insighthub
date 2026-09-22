"""SH1: retry is idempotent — same failing input, retried, stays consistent:
same document id, no duplicate row, no crash, truthful error_code every time.

Scenario chosen deliberately for a live black-box test with no DB access and
no provider mocking available: whitespace-only content is accepted by the
API's own byte-level check (nonzero bytes) but fails *after* extraction
inside the worker (InvalidDocument) — a real, reproducible 'failed' state
reachable over HTTP alone, in fixture mode, every time.
"""

from _common import get_json, unique_filename, upload_json, wait_for_status


def test_retry_idempotent():
    filename = unique_filename()
    whitespace_only = b"   \n\t  \n  "

    status, doc = upload_json(filename, whitespace_only)
    assert status == 202, f"expected 202, got {status}: {doc}"
    document_id = doc["id"]

    first = wait_for_status(document_id, {"ready", "failed"}, deadline_seconds=30)
    print(f"\n[test_retry_idempotent] first attempt: id={document_id} -> {first['status']}")
    assert first["status"] == "failed", f"expected whitespace-only content to fail: {first}"
    assert first["error_code"] == "invalid_document"
    assert first["chunk_count"] == 0

    # Retry with the exact same bytes — deterministically fails the same way.
    status, retry_doc = upload_json(filename, whitespace_only, path=f"/documents/{document_id}/retry")
    print(f"[test_retry_idempotent] retry #1: {status} id={retry_doc.get('id')}")
    assert status == 202, f"expected 202 on retry, got {status}: {retry_doc}"
    assert retry_doc["id"] == document_id, "retry must keep the same document id"

    second = wait_for_status(document_id, {"ready", "failed"}, deadline_seconds=30)
    print(f"[test_retry_idempotent] after retry #1: id={document_id} -> {second['status']}")
    assert second["status"] == "failed"
    assert second["error_code"] == "invalid_document"
    assert second["chunk_count"] == 0

    # Retry again — still consistent, still exactly one row for this id.
    status, retry_doc_2 = upload_json(filename, whitespace_only, path=f"/documents/{document_id}/retry")
    assert status == 202, f"expected 202 on retry #2, got {status}: {retry_doc_2}"
    wait_for_status(document_id, {"ready", "failed"}, deadline_seconds=30)

    _, docs = get_json("/documents")
    matches = [d for d in docs if d["id"] == document_id]
    print(f"[test_retry_idempotent] rows with id={document_id} after 2 retries: {len(matches)}")
    assert len(matches) == 1, "retry must never create a duplicate document row"
