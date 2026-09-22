"""Opt in with RUN_DB_TESTS=1 and mount init.sql as TEST_SCHEMA_PATH in Docker.

Each test run owns a random PostgreSQL schema. Only that schema is truncated/dropped.
No paid providers are called. A missing DB/schema fixture fails an opted-in run.
"""

import concurrent.futures
import os
import threading
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

import psycopg
from fastapi.testclient import TestClient
from psycopg import sql
from psycopg_pool import ConnectionPool
from support import configured, real_config

from app.core import db
from app.core.config import get_settings
from app.core.errors import (
    DocumentConflict,
    IndexIdentityConflict,
    ProviderError,
    SchemaMismatch,
    ServiceError,
)
from app.core.index import check_schema
from app.main import app
from app.services.embeddings import _local_embed
from app.services.ingestion import process_document
from app.services.retrieval import retrieve


@unittest.skipUnless(
    os.environ.get("RUN_DB_TESTS") == "1",
    "Set RUN_DB_TESTS=1 for isolated PostgreSQL integration tests",
)
class IntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dsn = os.environ.get("TEST_DATABASE_URL") or get_settings().database_url
        cls.schema = "test_insighthub_" + uuid.uuid4().hex
        source = Path(
            os.environ.get(
                "TEST_SCHEMA_PATH",
                str(Path(__file__).resolve().parents[2] / "infra/db/init.sql"),
            )
        )
        cls.schema_sql = source.read_text()
        cls.old_pool = db._pool
        with psycopg.connect(cls.dsn, autocommit=True) as conn:
            # Extension must be installed by the DB bootstrap, never by the test run.
            if not conn.execute("SELECT 1 FROM pg_extension WHERE extname = 'vector'").fetchone():
                raise RuntimeError("Initialize pgvector using infra/db/init.sql before integration tests")
            conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(cls.schema)))
        cls.addClassCleanup(cls.cleanup_schema)
        with psycopg.connect(cls.dsn, options=f"-csearch_path={cls.schema},public") as conn:
            conn.execute(cls.schema_sql)
        db._pool = ConnectionPool(
            conninfo=cls.dsn,
            min_size=2,
            max_size=10,
            configure=db._configure,
            kwargs={"options": f"-csearch_path={cls.schema},public"},
            open=True,
        )
        db._pool.wait(timeout=15)

    @classmethod
    def cleanup_schema(cls):
        if db._pool is not cls.old_pool:
            db._pool.close()
        db._pool = cls.old_pool
        with psycopg.connect(cls.dsn, autocommit=True) as conn:
            conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(cls.schema)))

    def setUp(self):
        self.config = configured()
        self.config.__enter__()
        self.addCleanup(self.config.__exit__, None, None, None)
        with db.get_conn() as conn:
            conn.execute("TRUNCATE chunks, documents, embedding_index RESTART IDENTITY CASCADE")
        self.client = TestClient(app)

        # No live Redis/worker here. Stand in for the queue by running the same
        # process_document synchronously, matching the real worker's contract:
        # processing failures never propagate back to the enqueue caller (the
        # worker only records them in the document row), so this must swallow
        # ServiceError the same way, not let it surface as a 503 enqueue_failed.
        def fake_enqueue(document_id, filename, content):
            try:
                process_document(document_id, filename, content)
            except ServiceError:
                pass

        patcher = patch("app.routers.documents.enqueue_ingestion", side_effect=fake_enqueue)
        patcher.start()
        self.addCleanup(patcher.stop)

    def create_document(self, filename="test.txt"):
        with db.get_conn() as conn:
            return conn.execute(
                "INSERT INTO documents(filename) VALUES (%s) RETURNING id",
                (filename,),
            ).fetchone()[0]

    def state(self, document_id):
        with db.get_conn() as conn:
            return conn.execute(
                "SELECT status, chunk_count, content_sha256, error_code, "
                "(SELECT count(*) FROM chunks WHERE document_id = documents.id) "
                "FROM documents WHERE id = %s",
                (document_id,),
            ).fetchone()

    def test_fixture_upload_retrieve_chat_metrics_delete_end_to_end(self):
        self.assertEqual(self.client.get("/readyz").status_code, 200)
        self.assertEqual(self.client.post("/chat", json={"question": "RAG?"}).status_code, 404)
        response = self.client.post("/documents", files={"file": ("rag.txt", b"RAG uses retrieved documents.")})
        self.assertEqual(response.status_code, 202, response.text)
        document = response.json()
        self.assertEqual(document["mode"], "fixture")
        self.assertEqual(document["status"], "pending")
        self.assertEqual(document["chunk_count"], 0)
        # Worker stand-in (setUp) already ran process_document synchronously by
        # the time this response came back; the response itself is still
        # honestly "pending" (D-async contract), the DB is already ready.
        self.assertEqual(self.client.get("/documents").json()[0]["status"], "ready")
        self.assertEqual(self.client.get("/documents").json()[0]["chunk_count"], 1)
        chat = self.client.post("/chat", json={"question": "RAG uses retrieved documents."})
        self.assertEqual(chat.status_code, 200, chat.text)
        self.assertIn("FIXTURE", chat.json()["answer"])
        self.assertEqual(chat.json()["sources"], ["rag.txt"])
        self.assertAlmostEqual(chat.json()["contexts"][0]["similarity"], 1, places=3)
        self.assertEqual(chat.json()["usage"]["source"], "unavailable")
        metrics = self.client.get("/metrics")
        self.assertEqual(metrics.status_code, 200)
        self.assertIn('insighthub_documents_total{status="ready"} 1.0', metrics.text)
        self.assertEqual(self.client.delete(f"/documents/{document['id']}").status_code, 204)
        with db.get_conn() as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM chunks").fetchone()[0], 0)
        self.assertIn(
            'insighthub_documents_total{status="ready"} 0.0',
            self.client.get("/metrics").text,
        )

    def test_successful_retry_is_noop_and_conflicting_payload_is_409(self):
        document_id = self.create_document()
        first = process_document(document_id, "test.txt", b"hello world")
        with patch("app.services.ingestion.embed") as provider:
            self.assertEqual(process_document(document_id, "test.txt", b"hello world"), first)
            provider.assert_not_called()
        for filename, content in (
            ("test.txt", b"changed"),
            ("other.txt", b"hello world"),
        ):
            with self.assertRaises(DocumentConflict):
                process_document(document_id, filename, content)
        state = self.state(document_id)
        self.assertEqual((state[0], state[1], state[4]), ("ready", first, first))
        self.assertIsNotNone(state[2])

    def test_concurrent_successful_retries_call_provider_once(self):
        document_id = self.create_document()
        started, release = threading.Event(), threading.Event()

        def slow_embed(texts, input_type):
            started.set()
            self.assertTrue(release.wait(timeout=5))
            return _local_embed(texts, 1024)

        with patch("app.services.ingestion.embed", side_effect=slow_embed) as provider:
            with concurrent.futures.ThreadPoolExecutor(2) as executor:
                first = executor.submit(process_document, document_id, "test.txt", b"same")
                self.assertTrue(started.wait(timeout=3))
                second = executor.submit(process_document, document_id, "test.txt", b"same")
                release.set()
                self.assertEqual(first.result(timeout=5), second.result(timeout=5))
            self.assertEqual(provider.call_count, 1)
        self.assertEqual(self.state(document_id)[4], 1)

    def test_failed_attempt_and_concurrent_retry_end_ready(self):
        document_id = self.create_document()
        started, release = threading.Event(), threading.Event()
        calls = []

        def fail_once(texts, input_type):
            calls.append(True)
            if len(calls) == 1:
                started.set()
                release.wait(timeout=5)
                raise ProviderError()
            return _local_embed(texts, 1024)

        with patch("app.services.ingestion.embed", side_effect=fail_once):
            with concurrent.futures.ThreadPoolExecutor(2) as executor:
                first = executor.submit(process_document, document_id, "test.txt", b"same")
                self.assertTrue(started.wait(timeout=3))
                second = executor.submit(process_document, document_id, "test.txt", b"same")
                release.set()
                with self.assertRaises(ProviderError):
                    first.result(timeout=5)
                self.assertEqual(second.result(timeout=5), 1)
        self.assertEqual(self.state(document_id)[0], "ready")
        self.assertEqual(self.state(document_id)[4], 1)
        self.assertIsNone(self.state(document_id)[3])

    def test_failed_vectors_are_atomic_and_can_retry(self):
        document_id = self.create_document()
        for invalid in ([], [[float("nan")] * 1024], [[1.0] * 1023]):
            with (
                patch("app.services.ingestion.embed", return_value=invalid),
                self.assertRaises(ProviderError),
            ):
                process_document(document_id, "test.txt", b"content")
            state = self.state(document_id)
            self.assertEqual((state[0], state[1], state[4]), ("failed", 0, 0))
            self.assertEqual(state[3], "provider_error")
            with db.get_conn() as conn:
                self.assertEqual(
                    conn.execute("SELECT count(*) FROM embedding_index").fetchone()[0],
                    0,
                )
        self.assertEqual(process_document(document_id, "test.txt", b"content"), 1)

    def test_mid_insert_database_failure_rolls_back_all_chunks(self):
        document_id = self.create_document()
        with db.get_conn() as conn:
            conn.execute(
                "CREATE FUNCTION reject_second() RETURNS trigger LANGUAGE plpgsql AS $$ "
                "BEGIN IF NEW.chunk_index = 1 THEN RAISE EXCEPTION 'secret'; END IF; "
                "RETURN NEW; END $$"
            )
            conn.execute(
                "CREATE TRIGGER reject_second BEFORE INSERT ON chunks FOR EACH ROW EXECUTE FUNCTION reject_second()"
            )
        try:
            with configured(chunk_size=4, chunk_overlap=0):
                with self.assertRaises(Exception) as raised:
                    process_document(document_id, "test.txt", b"a b c d e f")
                self.assertNotIn("secret", str(raised.exception))
        finally:
            with db.get_conn() as conn:
                conn.execute("DROP TRIGGER reject_second ON chunks")
                conn.execute("DROP FUNCTION reject_second()")
        state = self.state(document_id)
        self.assertEqual((state[0], state[1], state[4]), ("failed", 0, 0))

    def test_empty_extracted_text_is_failed_and_422(self):
        # Whitespace-only content passes the API's own emptiness check (nonzero
        # bytes) — invalid-after-extraction is pipeline work, now async: the
        # upload itself is accepted (202) and the failure surfaces in the row.
        response = self.client.post("/documents", files={"file": ("empty.txt", b" \n ")})
        self.assertEqual(response.status_code, 202, response.text)
        document = self.client.get("/documents").json()[0]
        self.assertEqual(document["status"], "failed")
        self.assertEqual(document["chunk_count"], 0)
        self.assertEqual(document["error_code"], "invalid_document")

    def test_index_identity_change_rejects_query_upload_and_readiness(self):
        self.client.post("/documents", files={"file": ("test.txt", b"content")})
        with (
            configured(embedding_revision="2"),
            patch("app.services.retrieval.embed") as provider,
        ):
            with self.assertRaises(IndexIdentityConflict):
                retrieve("question")
            provider.assert_not_called()
            response = self.client.post("/documents", files={"file": ("new.txt", b"new content")})
            self.assertEqual(response.status_code, 409, response.text)
            self.assertEqual(self.client.get("/readyz").status_code, 503)
        with db.get_conn() as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM chunks").fetchone()[0], 1)

    def test_same_dimension_real_provider_cannot_query_fixture_index(self):
        self.client.post("/documents", files={"file": ("test.txt", b"content")})
        with real_config(), patch("app.services.retrieval.embed") as provider:
            with self.assertRaises(IndexIdentityConflict):
                retrieve("question")
        provider.assert_not_called()

    def test_dimension_mismatch_is_rejected_before_provider(self):
        with configured(embedding_dim=768), db.get_conn() as conn:
            with self.assertRaises(SchemaMismatch):
                check_schema(conn)

    def test_real_gateway_full_pipeline_with_mock_http(self):
        def embedding_response(*args, **kwargs):
            return {
                "data": [{"index": i, "embedding": [1.0] * 1024} for i in range(len(kwargs["payload"]["input"]))],
                "usage": {"prompt_tokens": 5},
            }

        with (
            real_config(),
            patch(
                "app.services.embeddings.post_json",
                side_effect=embedding_response,
            ),
            patch(
                "app.services.llm.post_json",
                return_value={
                    "choices": [{"message": {"content": "Supported answer [nguồn: real.txt]"}}],
                    "usage": {"prompt_tokens": 12, "completion_tokens": 8},
                },
            ),
        ):
            upload = self.client.post("/documents", files={"file": ("real.txt", b"content")})
            self.assertEqual(upload.status_code, 202, upload.text)
            chat = self.client.post("/chat", json={"question": "question"})
            self.assertEqual(chat.status_code, 200, chat.text)
            self.assertEqual(chat.json()["mode"], "real")
            self.assertEqual(chat.json()["usage"]["input_tokens"], 12)
            self.assertEqual(chat.json()["usage"]["source"], "provider")

    def test_provider_failure_is_502_and_metadata_truthful(self):
        # Provider failure happens during pipeline work, now async: the upload
        # itself is still accepted (202) — the failure surfaces in the row,
        # not in the HTTP response, matching the contract table in plan.md.
        with (
            real_config(),
            patch("app.services.embeddings.post_json", side_effect=ProviderError()),
        ):
            response = self.client.post("/documents", files={"file": ("real.txt", b"content")})
        self.assertEqual(response.status_code, 202, response.text)
        document = self.client.get("/documents").json()[0]
        self.assertEqual(
            (document["status"], document["chunk_count"], document["error_code"]),
            ("failed", 0, "provider_error"),
        )

    def test_enqueue_failure_marks_document_failed_and_returns_503(self):
        with patch(
            "app.routers.documents.enqueue_ingestion",
            side_effect=RuntimeError("redis down"),
        ):
            response = self.client.post("/documents", files={"file": ("x.txt", b"content")})
        self.assertEqual(response.status_code, 503, response.text)
        document = self.client.get("/documents").json()[0]
        self.assertEqual((document["status"], document["error_code"]), ("failed", "enqueue_failed"))

    def test_retry_happy_path_keeps_same_id_and_succeeds(self):
        document_id = self.create_document("retryable.txt")
        with patch("app.services.ingestion.embed", side_effect=ProviderError()):
            with self.assertRaises(ProviderError):
                process_document(document_id, "retryable.txt", b"original content")
        self.assertEqual(self.state(document_id)[0], "failed")

        response = self.client.post(
            f"/documents/{document_id}/retry",
            files={"file": ("retryable.txt", b"original content")},
        )
        self.assertEqual(response.status_code, 202, response.text)
        self.assertEqual(response.json()["id"], document_id)
        state = self.state(document_id)
        self.assertEqual((state[0], state[4]), ("ready", 1))

    def test_retry_missing_id_is_404(self):
        response = self.client.post("/documents/999999/retry", files={"file": ("x.txt", b"content")})
        self.assertEqual(response.status_code, 404, response.text)

    def test_retry_wrong_status_is_409(self):
        upload = self.client.post("/documents", files={"file": ("ready.txt", b"content")})
        document_id = upload.json()["id"]
        response = self.client.post(
            f"/documents/{document_id}/retry",
            files={"file": ("ready.txt", b"content")},
        )
        self.assertEqual(response.status_code, 409, response.text)

    def test_retry_filename_mismatch_is_409(self):
        document_id = self.create_document("a.txt")
        with patch("app.services.ingestion.embed", side_effect=ProviderError()):
            with self.assertRaises(ProviderError):
                process_document(document_id, "a.txt", b"content")
        response = self.client.post(
            f"/documents/{document_id}/retry",
            files={"file": ("different.txt", b"content")},
        )
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(self.state(document_id)[0], "failed")

    def test_retry_content_mismatch_is_409(self):
        document_id = self.create_document("a.txt")
        with patch("app.services.ingestion.embed", side_effect=ProviderError()):
            with self.assertRaises(ProviderError):
                process_document(document_id, "a.txt", b"content")
        response = self.client.post(
            f"/documents/{document_id}/retry",
            files={"file": ("a.txt", b"different content")},
        )
        self.assertEqual(response.status_code, 409, response.text)

    def test_retry_accepts_null_hash_when_never_processed(self):
        # Failed before the worker ever ran process_document (e.g. enqueue
        # error) — content_sha256/pipeline_id are still NULL; the NULL-safe
        # match (D7) must accept a retry for exactly this case.
        document_id = self.create_document("neverprocessed.txt")
        with db.get_conn() as conn:
            conn.execute(
                "UPDATE documents SET status='failed', error_code='enqueue_failed' WHERE id=%s",
                (document_id,),
            )
        self.assertIsNone(self.state(document_id)[2])  # content_sha256 still NULL
        response = self.client.post(
            f"/documents/{document_id}/retry",
            files={"file": ("neverprocessed.txt", b"anything")},
        )
        self.assertEqual(response.status_code, 202, response.text)

    def test_concurrent_retries_exactly_one_succeeds(self):
        document_id = self.create_document("concurrent.txt")
        with patch("app.services.ingestion.embed", side_effect=ProviderError()):
            with self.assertRaises(ProviderError):
                process_document(document_id, "concurrent.txt", b"content")

        def do_retry(_):
            return self.client.post(
                f"/documents/{document_id}/retry",
                files={"file": ("concurrent.txt", b"content")},
            )

        with concurrent.futures.ThreadPoolExecutor(2) as executor:
            results = list(executor.map(do_retry, range(2)))
        self.assertEqual(sorted(r.status_code for r in results), [202, 409])
