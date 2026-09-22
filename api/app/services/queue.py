"""Enqueue is a synchronous hop into Redis; caller decides what a failure means."""

import asyncio

from arq import create_pool
from arq.connections import RedisSettings

from app.core.config import get_settings


async def _enqueue(document_id: int, filename: str, content: bytes) -> None:
    settings = get_settings()
    pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    try:
        await pool.enqueue_job("run_ingestion", document_id, filename, content)
    finally:
        await pool.aclose()


def enqueue_ingestion(document_id: int, filename: str, content: bytes) -> None:
    asyncio.run(_enqueue(document_id, filename, content))
