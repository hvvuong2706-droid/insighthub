"""Shared HTTP helpers for the Day 1 milestone tests — stdlib only, no mocks.

These tests hit a REAL running stack (INSIGHTHUB_API_URL). Not collected by
pytest itself (doesn't match test_*.py), only imported by sibling test files.
"""

import json
import os
import time
import urllib.error
import urllib.request
import uuid

API_URL = os.environ.get("INSIGHTHUB_API_URL", "http://localhost:8000").rstrip("/")


def request(method, path, body=None, headers=None, timeout=15):
    req = urllib.request.Request(API_URL + path, data=body, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, exc.read()
        finally:
            exc.close()


def get_json(path, timeout=15):
    status, raw = request("GET", path, timeout=timeout)
    return status, json.loads(raw)


def post_json(path, payload, timeout=15):
    status, raw = request(
        "POST",
        path,
        body=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        timeout=timeout,
    )
    return status, json.loads(raw)


def _multipart(field_name, filename, content, content_type="text/plain"):
    boundary = "InsightHubDay1" + uuid.uuid4().hex
    body = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="{field_name}"; filename="{filename}"\r\n'
        f"Content-Type: {content_type}\r\n\r\n"
    ).encode() + content + f"\r\n--{boundary}--\r\n".encode()
    return body, {"Content-Type": f"multipart/form-data; boundary={boundary}"}


def upload(filename, content, path="/documents", timeout=15):
    body, headers = _multipart("file", filename, content)
    return request("POST", path, body=body, headers=headers, timeout=timeout)


def upload_json(filename, content, path="/documents", timeout=15):
    status, raw = upload(filename, content, path=path, timeout=timeout)
    return status, json.loads(raw)


def unique_filename(suffix=".txt"):
    return f"day1-milestone-{uuid.uuid4().hex}{suffix}"


def wait_for_status(document_id, want_statuses, deadline_seconds=30, interval=1):
    """Poll GET /documents until the given id reaches one of want_statuses."""
    deadline = time.monotonic() + deadline_seconds
    last = None
    while time.monotonic() < deadline:
        status, docs = get_json("/documents")
        assert status == 200, f"GET /documents returned {status}"
        matches = [d for d in docs if str(d["id"]) == str(document_id)]
        if matches:
            last = matches[0]
            if last["status"] in want_statuses:
                return last
        time.sleep(interval)
    raise AssertionError(
        f"document {document_id} did not reach {want_statuses} within {deadline_seconds}s "
        f"(last seen: {last})"
    )
