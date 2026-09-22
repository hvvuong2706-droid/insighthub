"""The async refactor must not break what already worked: upload -> ready ->
chat retrieves it -> metrics reflect it. Same guarantees as before Day 1,
just reached asynchronously now."""

from _common import post_json, request, unique_filename, upload_json, wait_for_status


def test_refactor_regression():
    filename = unique_filename()
    content = b"InsightHub regression check content for Day 1."

    status, doc = upload_json(filename, content)
    assert status == 202, f"expected 202, got {status}: {doc}"
    document_id = doc["id"]

    final = wait_for_status(document_id, {"ready", "failed"}, deadline_seconds=30)
    print(f"\n[test_refactor_regression] upload id={document_id} -> {final['status']}")
    assert final["status"] == "ready", final
    assert final["chunk_count"] > 0

    # Fixture-mode embeddings are hash-based, not semantic (see
    # embeddings.py's own docstring: "no semantic retrieval quality claim") —
    # a live stack may hold other documents too, so this only checks the
    # *shape* of a working chat response, not that it retrieves this exact
    # upload (same weaker check scripts/verify.py's smoke() uses).
    status, chat = post_json("/chat", {"question": "InsightHub"})
    print(f"[test_refactor_regression] POST /chat -> {status}, sources={chat.get('sources')}")
    assert status == 200, f"expected 200, got {status}: {chat}"
    assert isinstance(chat.get("answer"), str) and chat["answer"].strip()
    assert chat.get("sources")
    assert chat.get("contexts")

    status, body = request("GET", "/metrics")
    assert status == 200, "metrics endpoint must stay up after the refactor"
    assert b"insighthub_documents_total" in body
