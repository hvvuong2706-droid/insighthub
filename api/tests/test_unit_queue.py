"""enqueue_ingestion is the only seam the router touches; keep it patchable without live Redis."""

import unittest
from unittest.mock import AsyncMock, patch

from app.services.queue import enqueue_ingestion


class EnqueueTests(unittest.TestCase):
    def test_enqueues_run_ingestion_with_given_args(self):
        pool = AsyncMock()
        with patch("app.services.queue.create_pool", AsyncMock(return_value=pool)):
            enqueue_ingestion(7, "doc.txt", b"hello")
        pool.enqueue_job.assert_awaited_once_with("run_ingestion", 7, "doc.txt", b"hello")
        pool.aclose.assert_awaited_once()

    def test_pool_closed_even_if_enqueue_raises(self):
        pool = AsyncMock()
        pool.enqueue_job.side_effect = RuntimeError("boom")
        with patch("app.services.queue.create_pool", AsyncMock(return_value=pool)):
            with self.assertRaises(RuntimeError):
                enqueue_ingestion(7, "doc.txt", b"hello")
        pool.aclose.assert_awaited_once()

    def test_create_pool_failure_propagates(self):
        with patch("app.services.queue.create_pool", AsyncMock(side_effect=ConnectionError("no redis"))):
            with self.assertRaises(ConnectionError):
                enqueue_ingestion(7, "doc.txt", b"hello")


if __name__ == "__main__":
    unittest.main()
