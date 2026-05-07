from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from informer_bot.db import Database
from informer_bot.main import _wrap_embed_with_remote_model_check
from informer_bot.summarizer import EMBED_DIMENSIONS, Embedding


@pytest.fixture
def db(tmp_path: Path) -> Database:
    return Database(tmp_path / "p.db")


def _emb(provider: str, model: str) -> Embedding:
    return Embedding(vector=[0.1], tokens=1, provider=provider, model=model)


async def test_wrap_records_embedding_id_on_first_call(db: Database) -> None:
    inner = AsyncMock(return_value=_emb("remote", "qwen3-embedding:4b"))

    wrapped = _wrap_embed_with_remote_model_check(inner, db)
    await wrapped("text")

    assert (
        db.get_meta("embedding_id")
        == f"remote:qwen3-embedding:4b:{EMBED_DIMENSIONS}"
    )


def _post_embedding_count(db: Database) -> int:
    return db._conn.execute("SELECT COUNT(*) FROM post_embeddings").fetchone()[0]


async def test_wrap_purges_when_remote_model_changes(db: Database) -> None:
    db.set_meta("embedding_id", f"remote:old-model:{EMBED_DIMENSIONS}")
    db.store_post_embedding(
        channel_id=1, message_id=1, embedding=[0.0], summary="s", link="l",
    )
    inner = AsyncMock(return_value=_emb("remote", "new-model"))

    wrapped = _wrap_embed_with_remote_model_check(inner, db)
    await wrapped("text")

    assert (
        db.get_meta("embedding_id")
        == f"remote:new-model:{EMBED_DIMENSIONS}"
    )
    assert _post_embedding_count(db) == 0


async def test_wrap_keeps_index_when_model_unchanged(db: Database) -> None:
    inner = AsyncMock(return_value=_emb("remote", "same-model"))
    wrapped = _wrap_embed_with_remote_model_check(inner, db)
    await wrapped("text")
    db.store_post_embedding(
        channel_id=1, message_id=1, embedding=[0.0], summary="s", link="l",
    )

    await wrapped("text2")

    assert _post_embedding_count(db) == 1


async def test_wrap_purges_when_fallback_provider_replies(db: Database) -> None:
    db.set_meta("embedding_id", f"remote:remote-model:{EMBED_DIMENSIONS}")
    db.store_post_embedding(
        channel_id=1, message_id=1, embedding=[0.0], summary="s", link="l",
    )
    inner = AsyncMock(return_value=_emb("openai", "text-embedding-3-small"))

    wrapped = _wrap_embed_with_remote_model_check(inner, db)
    await wrapped("text")

    assert (
        db.get_meta("embedding_id")
        == f"openai:text-embedding-3-small:{EMBED_DIMENSIONS}"
    )
    assert _post_embedding_count(db) == 0
