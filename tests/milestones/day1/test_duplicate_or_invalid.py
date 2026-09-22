"""Invalid file type is rejected (400); retrying a document that isn't
'failed' is rejected as a conflict (409) — no duplicate/second attempt."""

from _common import unique_filename, upload_json, wait_for_status


def test_duplicate_or_invalid():
    status, doc = upload_json("not-allowed.exe", b"binary-ish content")
    print(f"\n[test_duplicate_or_invalid] wrong extension -> {status}: {doc}")
    assert status == 400, f"expected 400 for disallowed extension, got {status}: {doc}"

    filename = unique_filename()
    status, doc = upload_json(filename, b"Content that will become ready normally.")
    assert status == 202, f"expected 202, got {status}: {doc}"
    document_id = doc["id"]
    final = wait_for_status(document_id, {"ready", "failed"}, deadline_seconds=30)
    assert final["status"] == "ready", final

    status, retry_doc = upload_json(
        filename, b"Content that will become ready normally.", path=f"/documents/{document_id}/retry"
    )
    print(f"[test_duplicate_or_invalid] retry on non-failed doc -> {status}: {retry_doc}")
    assert status == 409, f"expected 409 retrying a non-failed document, got {status}: {retry_doc}"
