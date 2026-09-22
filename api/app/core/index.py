"""Prevent comparisons across embedding spaces, including equal-dimensional models."""

from psycopg import Error
from psycopg.types.json import Jsonb

from app.core.config import get_settings
from app.core.errors import IndexIdentityConflict, SchemaMismatch


def check_schema(conn) -> None:
    try:
        row = conn.execute(
            "SELECT atttypmod FROM pg_attribute WHERE attrelid = to_regclass('chunks') "
            "AND attname = 'embedding' AND NOT attisdropped"
        ).fetchone()
        if row is None or row[0] != get_settings().embedding_dim:
            raise SchemaMismatch()
        conn.execute(
            "SELECT content_sha256, pipeline_id, embedding_identity_id, error_code "
            "FROM documents LIMIT 0"
        )
        conn.execute(
            "SELECT identity_id, identity, dimension FROM embedding_index LIMIT 0"
        )
    except Error:
        raise SchemaMismatch() from None


def ensure_index_identity(conn, *, claim: bool):
    settings = get_settings()
    if claim:
        conn.execute(
            "INSERT INTO embedding_index (singleton, identity_id, identity, dimension) "
            "VALUES (TRUE, %s, %s, %s) ON CONFLICT (singleton) DO NOTHING",
            (
                settings.embedding_identity_id,
                Jsonb(settings.embedding_identity),
                settings.embedding_dim,
            ),
        )
    row = conn.execute(
        "SELECT identity_id, identity, dimension FROM embedding_index "
        "WHERE singleton = TRUE FOR SHARE"
    ).fetchone()
    if row is not None and (
        row[0] != settings.embedding_identity_id
        or row[1] != settings.embedding_identity
        or row[2] != settings.embedding_dim
    ):
        raise IndexIdentityConflict()
    if row is None and conn.execute("SELECT 1 FROM chunks LIMIT 1").fetchone():
        raise IndexIdentityConflict()
    return row is not None
