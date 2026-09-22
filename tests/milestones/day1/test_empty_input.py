"""Empty upload is rejected synchronously — unaffected by the async refactor."""

from _common import unique_filename, upload_json


def test_empty_input():
    status, doc = upload_json(unique_filename(), b"")
    print(f"\n[test_empty_input] empty upload -> {status}: {doc}")
    assert status == 422, f"expected 422 for empty content, got {status}: {doc}"
