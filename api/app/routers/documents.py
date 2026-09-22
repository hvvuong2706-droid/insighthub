"""Async upload contract: 202 once the job is queued, worker finishes the job."""

import hashlib

from fastapi import APIRouter, HTTPException, UploadFile

from app.core.config import get_settings
from app.core.db import get_conn
from app.core.errors import (
    DocumentConflict,
    DocumentNotFound,
    EnqueueFailed,
    InvalidDocument,
)
from app.core.index import check_schema, ensure_index_identity
from app.services.ingestion import compute_pipeline_id
from app.services.queue import enqueue_ingestion

router = APIRouter(prefix="/documents", tags=["documents"])
ALLOWED_EXT = (".txt", ".md", ".pdf")


def _read_validated_file(file: UploadFile) -> tuple[str, bytes]:
    filename = file.filename
    try:
        if not filename or not filename.lower().endswith(ALLOWED_EXT):
            raise HTTPException(400, "Chỉ chấp nhận: .txt, .md, .pdf")
        if len(filename) > 255 or "\x00" in filename:
            raise HTTPException(422, "Tên file không hợp lệ.")
        content = file.file.read(get_settings().max_upload_bytes + 1)
    finally:
        file.file.close()
    if len(content) > get_settings().max_upload_bytes:
        raise HTTPException(413, "File vượt quá giới hạn upload.")
    if not content:
        raise InvalidDocument()
    return filename, content


def _enqueue_or_fail_closed(document_id: int, filename: str, content: bytes) -> None:
    try:
        enqueue_ingestion(document_id, filename, content)
    except Exception:
        # D14: fail closed. Never overwrite a row a worker already finished —
        # if the job actually did reach the queue despite this error, the
        # worker will still process it and overwrite failed->ready normally.
        with get_conn() as conn:
            conn.execute(
                "UPDATE documents SET status = 'failed', error_code = %s WHERE id = %s AND status = 'pending'",
                (EnqueueFailed.code, document_id),
            )
        raise EnqueueFailed() from None


@router.post("", status_code=202)
def upload_document(file: UploadFile) -> dict[str, object]:
    filename, content = _read_validated_file(file)
    # D15: cheap read-only preflight so an identity conflict still surfaces as a
    # synchronous 409 here, same as today, instead of only inside the worker later.
    with get_conn() as conn:
        check_schema(conn)
        ensure_index_identity(conn, claim=False)
    with get_conn() as conn:
        document_id = conn.execute(
            "INSERT INTO documents (filename, status) VALUES (%s, 'pending') RETURNING id",
            (filename,),
        ).fetchone()[0]
    _enqueue_or_fail_closed(document_id, filename, content)
    settings = get_settings()
    return {
        "id": document_id,
        "filename": filename,
        "status": "pending",
        "chunk_count": 0,
        "mode": settings.rag_mode,
        "embedding_identity_id": None,
    }


@router.post("/{document_id}/retry", status_code=202)
def retry_document(document_id: int, file: UploadFile) -> dict[str, object]:
    # D7: the client must resend the exact original file — the row only ever
    # stores a hash, never the raw bytes.
    filename, content = _read_validated_file(file)
    digest = hashlib.sha256(content).hexdigest()
    pipeline_id = compute_pipeline_id()
    with get_conn() as conn:
        with conn.transaction():
            row = conn.execute(
                "SELECT filename, status, content_sha256, pipeline_id FROM documents WHERE id = %s FOR UPDATE",
                (document_id,),
            ).fetchone()
            if row is None:
                raise DocumentNotFound()
            # NULL-safe: content_sha256/pipeline_id are only ever set by
            # process_document, so a document that failed before the worker
            # ever ran them (e.g. an enqueue failure) still has them NULL.
            if (
                row[1] != "failed"
                or row[0] != filename
                or row[2] not in (None, digest)
                or row[3] not in (None, pipeline_id)
            ):
                raise DocumentConflict()
            conn.execute(
                "UPDATE documents SET status = 'pending', error_code = NULL WHERE id = %s",
                (document_id,),
            )
    _enqueue_or_fail_closed(document_id, filename, content)
    return {
        "id": document_id,
        "filename": filename,
        "status": "pending",
        "chunk_count": 0,
    }


@router.get("")
def list_documents() -> list[dict[str, object]]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, filename, status, chunk_count, created_at, "
            "embedding_identity_id, error_code FROM documents ORDER BY created_at DESC"
        ).fetchall()
    return [
        {
            "id": r[0],
            "filename": r[1],
            "status": r[2],
            "chunk_count": r[3],
            "created_at": r[4].isoformat(),
            "embedding_identity_id": r[5],
            "error_code": r[6],
        }
        for r in rows
    ]


@router.delete("/{document_id}", status_code=204)
def delete_document(document_id: int) -> None:
    with get_conn() as conn:
        result = conn.execute(
            "DELETE FROM documents WHERE id = %s RETURNING id",
            (document_id,),
        ).fetchone()
    if result is None:
        raise HTTPException(404, "Không tìm thấy tài liệu.")
