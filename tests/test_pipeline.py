from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from informer_bot.db import Database
from informer_bot.pipeline import handle_new_post, refresh_channels
from informer_bot.summarizer import Embedding, RelevanceCheck, Summary


def _summary(
    text: str = "Brief.",
    input_tokens: int = 100,
    output_tokens: int = 20,
    provider: str = "anthropic",
) -> Summary:
    return Summary(
        text=text,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        provider=provider,
    )


def _relevance(
    relevant: bool,
    input_tokens: int = 30,
    output_tokens: int = 1,
    provider: str = "anthropic",
) -> RelevanceCheck:
    return RelevanceCheck(
        relevant=relevant,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        provider=provider,
    )


def _expected_body(channel_title: str, summary: str, link: str) -> str:
    return f'<a href="{link}">{channel_title}</a>\n{summary}'


def _send_dm(message_id: int = 999) -> AsyncMock:
    return AsyncMock(return_value=message_id)


def _embed_fn(
    vector: list[float] | None = None,
    tokens: int = 5,
    provider: str = "openai",
) -> AsyncMock:
    return AsyncMock(return_value=Embedding(
        vector=vector or [0.0, 1.0], tokens=tokens, provider=provider,
    ))


def _edit_dm() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def db(tmp_path: Path) -> Database:
    return Database(tmp_path / "p.db")


# ---------- handle_new_post ----------

async def test_handle_new_post_skips_empty_text(db: Database) -> None:
    db.upsert_channel(channel_id=1, title="A")
    db.subscribe(user_id=10, channel_id=1)
    summarize = AsyncMock()
    is_rel = AsyncMock()
    send_dm = _send_dm()

    await handle_new_post(
        channel_id=1, message_id=100, text="   ",
        link="https://t.me/a/100", db=db, summarize_fn=summarize,
        is_relevant_fn=is_rel, send_dm=send_dm,
        embed_fn=_embed_fn(), edit_dm=_edit_dm(),
    )

    summarize.assert_not_called()
    is_rel.assert_not_called()
    send_dm.assert_not_called()


async def test_handle_new_post_summarises_and_dms_subscribers(db: Database) -> None:
    db.upsert_channel(channel_id=1, title="Channel A")
    db.subscribe(user_id=10, channel_id=1)
    db.subscribe(user_id=20, channel_id=1)
    summarize = AsyncMock(return_value=_summary("Brief."))
    is_rel = AsyncMock()
    send_dm = _send_dm()

    await handle_new_post(
        channel_id=1, message_id=100, text="Long post body",
        link="https://t.me/a/100", db=db, summarize_fn=summarize,
        is_relevant_fn=is_rel, send_dm=send_dm,
        embed_fn=_embed_fn(), edit_dm=_edit_dm(),
    )

    summarize.assert_awaited_once_with("Long post body")
    is_rel.assert_not_called()
    assert send_dm.await_count == 2
    expected = _expected_body("Channel A", "Brief.", "https://t.me/a/100")
    sent = {call.args[0]: call.args for call in send_dm.await_args_list}
    assert sent[10] == (10, expected, None)
    assert sent[20] == (20, expected, None)


async def test_handle_new_post_passes_photo_to_send_dm(db: Database) -> None:
    db.upsert_channel(channel_id=1, title="A")
    db.subscribe(user_id=10, channel_id=1)
    summarize = AsyncMock(return_value=_summary("Brief."))
    is_rel = AsyncMock()
    send_dm = _send_dm()

    await handle_new_post(
        channel_id=1, message_id=100, text="body",
        link="https://t.me/a/100", db=db, summarize_fn=summarize,
        is_relevant_fn=is_rel, send_dm=send_dm, photo=b"PNG",
        embed_fn=_embed_fn(), edit_dm=_edit_dm(),
    )

    send_dm.assert_awaited_once()
    assert send_dm.await_args.args[0] == 10
    assert send_dm.await_args.args[2] == b"PNG"


async def test_handle_new_post_html_escapes_title_and_summary(db: Database) -> None:
    db.upsert_channel(channel_id=1, title="A & <B>")
    db.subscribe(user_id=10, channel_id=1)
    summarize = AsyncMock(return_value=_summary("5 < 10 & true"))
    is_rel = AsyncMock()
    send_dm = _send_dm()

    await handle_new_post(
        channel_id=1, message_id=100, text="body",
        link="https://t.me/a/100", db=db, summarize_fn=summarize,
        is_relevant_fn=is_rel, send_dm=send_dm,
        embed_fn=_embed_fn(), edit_dm=_edit_dm(),
    )

    body = send_dm.await_args.args[1]
    assert "A &amp; &lt;B&gt;" in body
    assert "5 &lt; 10 &amp; true" in body


async def test_handle_new_post_records_per_user_and_system_usage(db: Database) -> None:
    db.upsert_channel(channel_id=1, title="A")
    db.subscribe(user_id=10, channel_id=1)
    db.subscribe(user_id=20, channel_id=1)
    summarize = AsyncMock(return_value=_summary("Brief.", input_tokens=100, output_tokens=20))
    is_rel = AsyncMock()
    send_dm = _send_dm()

    await handle_new_post(
        channel_id=1, message_id=100, text="Long post body",
        link="https://t.me/a/100", db=db, summarize_fn=summarize,
        is_relevant_fn=is_rel, send_dm=send_dm,
        embed_fn=_embed_fn(), edit_dm=_edit_dm(),
    )

    assert db.get_usage(user_id=10) == [("anthropic", 100, 20)]
    assert db.get_usage(user_id=20) == [("anthropic", 100, 20)]
    assert db.get_system_usage() == [("anthropic", 100, 20)]


async def test_handle_new_post_records_provider_from_summary(
    db: Database,
) -> None:
    db.upsert_channel(channel_id=1, title="A")
    db.subscribe(user_id=10, channel_id=1)
    summarize = AsyncMock(return_value=_summary(
        "Brief.", input_tokens=100, output_tokens=20, provider="remote",
    ))
    is_rel = AsyncMock()

    await handle_new_post(
        channel_id=1, message_id=100, text="body",
        link="https://t.me/a/100", db=db, summarize_fn=summarize,
        is_relevant_fn=is_rel, send_dm=_send_dm(),
        embed_fn=_embed_fn(provider="ollama", tokens=7), edit_dm=_edit_dm(),
    )

    assert db.get_usage(user_id=10) == [("remote", 100, 20)]
    assert db.get_system_usage() == [("remote", 100, 20)]
    assert db.get_embedding_usage() == [("ollama", 7)]


async def test_handle_new_post_filter_uses_relevance_provider(
    db: Database,
) -> None:
    """Filter check tokens land under the provider on the RelevanceCheck —
    even when a separate fallback summarize provider would differ."""
    db.upsert_channel(channel_id=1, title="A")
    db.add_pending_user(user_id=10, username="alice")
    db.set_user_status(user_id=10, status="approved")
    db.subscribe(user_id=10, channel_id=1)
    db.set_channel_filter(user_id=10, channel_id=1, filter_prompt="AI")
    summarize = AsyncMock(return_value=_summary(
        "Brief.", input_tokens=100, output_tokens=20, provider="anthropic",
    ))
    is_rel = AsyncMock(return_value=_relevance(
        True, input_tokens=30, output_tokens=1, provider="remote",
    ))

    await handle_new_post(
        channel_id=1, message_id=100, text="AI news",
        link="https://t.me/a/100", db=db, summarize_fn=summarize,
        is_relevant_fn=is_rel, send_dm=_send_dm(),
        embed_fn=_embed_fn(), edit_dm=_edit_dm(),
    )

    assert sorted(db.get_usage(user_id=10)) == [
        ("anthropic", 100, 20),
        ("remote", 30, 1),
    ]
    assert sorted(db.get_system_usage()) == [
        ("anthropic", 100, 20),
        ("remote", 30, 1),
    ]


async def test_handle_new_post_is_idempotent_per_message(db: Database) -> None:
    db.upsert_channel(channel_id=1, title="A")
    db.subscribe(user_id=10, channel_id=1)
    summarize = AsyncMock(return_value=_summary("Brief."))
    is_rel = AsyncMock()
    send_dm = _send_dm()

    for _ in range(2):
        await handle_new_post(
            channel_id=1, message_id=100, text="body",
            link="https://t.me/a/100", db=db, summarize_fn=summarize,
            is_relevant_fn=is_rel, send_dm=send_dm,
            embed_fn=_embed_fn(), edit_dm=_edit_dm(),
        )

    summarize.assert_awaited_once()
    send_dm.assert_awaited_once()


async def test_handle_new_post_silent_when_channel_blacklisted(db: Database) -> None:
    db.upsert_channel(channel_id=1, title="A")
    db.subscribe(user_id=10, channel_id=1)
    db.set_blacklisted(channel_id=1, blacklisted=True)
    summarize = AsyncMock(return_value=_summary("Brief."))
    is_rel = AsyncMock()
    send_dm = _send_dm()

    await handle_new_post(
        channel_id=1, message_id=100, text="body",
        link="https://t.me/a/100", db=db, summarize_fn=summarize,
        is_relevant_fn=is_rel, send_dm=send_dm,
        embed_fn=_embed_fn(), edit_dm=_edit_dm(),
    )

    send_dm.assert_not_called()


# ---------- per-user filter ----------

async def test_handle_new_post_filters_out_user_when_irrelevant(db: Database) -> None:
    db.upsert_channel(channel_id=1, title="A")
    db.add_pending_user(user_id=10, username="alice")
    db.set_user_status(user_id=10, status="approved")
    db.subscribe(user_id=10, channel_id=1)
    db.set_channel_filter(user_id=10, channel_id=1, filter_prompt="only AI")
    summarize = AsyncMock(return_value=_summary("Brief."))
    is_rel = AsyncMock(return_value=_relevance(False))
    send_dm = _send_dm()

    await handle_new_post(
        channel_id=1, message_id=100, text="Crypto pump news",
        link="https://t.me/a/100", db=db, summarize_fn=summarize,
        is_relevant_fn=is_rel, send_dm=send_dm,
        embed_fn=_embed_fn(), edit_dm=_edit_dm(),
    )

    is_rel.assert_awaited_once_with("Crypto pump news", "only AI")
    summarize.assert_not_called()
    send_dm.assert_not_called()


async def test_handle_new_post_filters_in_user_when_relevant(db: Database) -> None:
    db.upsert_channel(channel_id=1, title="Channel A")
    db.add_pending_user(user_id=10, username="alice")
    db.set_user_status(user_id=10, status="approved")
    db.subscribe(user_id=10, channel_id=1)
    db.set_channel_filter(user_id=10, channel_id=1, filter_prompt="only AI")
    summarize = AsyncMock(return_value=_summary("Brief."))
    is_rel = AsyncMock(return_value=_relevance(True))
    send_dm = _send_dm()

    await handle_new_post(
        channel_id=1, message_id=100, text="New AI model released",
        link="https://t.me/a/100", db=db, summarize_fn=summarize,
        is_relevant_fn=is_rel, send_dm=send_dm,
        embed_fn=_embed_fn(), edit_dm=_edit_dm(),
    )

    summarize.assert_awaited_once()
    expected = _expected_body("Channel A", "Brief.", "https://t.me/a/100")
    send_dm.assert_awaited_once_with(10, expected, None)


async def test_handle_new_post_summarises_once_when_at_least_one_user_passes(
    db: Database,
) -> None:
    db.upsert_channel(channel_id=1, title="A")
    db.add_pending_user(user_id=10, username="alice")
    db.add_pending_user(user_id=20, username="bob")
    db.set_user_status(user_id=10, status="approved")
    db.set_user_status(user_id=20, status="approved")
    db.subscribe(user_id=10, channel_id=1)
    db.subscribe(user_id=20, channel_id=1)
    db.set_channel_filter(user_id=10, channel_id=1, filter_prompt="AI")
    db.set_channel_filter(user_id=20, channel_id=1, filter_prompt="crypto")
    summarize = AsyncMock(return_value=_summary("Brief.", input_tokens=100, output_tokens=20))

    async def fake_is_rel(text: str, filt: str) -> RelevanceCheck:
        return _relevance(filt == "AI")

    is_rel = AsyncMock(side_effect=fake_is_rel)
    send_dm = _send_dm()

    await handle_new_post(
        channel_id=1, message_id=100, text="An AI breakthrough",
        link="https://t.me/a/100", db=db, summarize_fn=summarize,
        is_relevant_fn=is_rel, send_dm=send_dm,
        embed_fn=_embed_fn(), edit_dm=_edit_dm(),
    )

    assert is_rel.await_count == 2
    summarize.assert_awaited_once()
    send_dm.assert_awaited_once()
    assert send_dm.await_args.args[0] == 10


async def test_handle_new_post_skips_summary_when_no_user_passes(db: Database) -> None:
    db.upsert_channel(channel_id=1, title="A")
    db.add_pending_user(user_id=10, username="alice")
    db.set_user_status(user_id=10, status="approved")
    db.subscribe(user_id=10, channel_id=1)
    db.set_channel_filter(user_id=10, channel_id=1, filter_prompt="AI")
    summarize = AsyncMock(return_value=_summary("Brief."))
    is_rel = AsyncMock(return_value=_relevance(False))
    send_dm = _send_dm()

    await handle_new_post(
        channel_id=1, message_id=100, text="Crypto pump",
        link="https://t.me/a/100", db=db, summarize_fn=summarize,
        is_relevant_fn=is_rel, send_dm=send_dm,
        embed_fn=_embed_fn(), edit_dm=_edit_dm(),
    )

    summarize.assert_not_called()
    send_dm.assert_not_called()


async def test_handle_new_post_charges_filter_tokens_to_user_and_system(db: Database) -> None:
    db.upsert_channel(channel_id=1, title="A")
    db.add_pending_user(user_id=10, username="alice")
    db.set_user_status(user_id=10, status="approved")
    db.subscribe(user_id=10, channel_id=1)
    db.set_channel_filter(user_id=10, channel_id=1, filter_prompt="AI")
    summarize = AsyncMock(return_value=_summary("Brief.", input_tokens=100, output_tokens=20))
    is_rel = AsyncMock(return_value=_relevance(True, input_tokens=30, output_tokens=1))
    send_dm = _send_dm()

    await handle_new_post(
        channel_id=1, message_id=100, text="AI news",
        link="https://t.me/a/100", db=db, summarize_fn=summarize,
        is_relevant_fn=is_rel, send_dm=send_dm,
        embed_fn=_embed_fn(), edit_dm=_edit_dm(),
    )

    assert db.get_usage(user_id=10) == [("anthropic", 130, 21)]
    assert db.get_system_usage() == [("anthropic", 130, 21)]


async def test_handle_new_post_mode_all_skips_filter_check(db: Database) -> None:
    db.upsert_channel(channel_id=1, title="Channel A")
    db.add_pending_user(user_id=10, username="alice")
    db.set_user_status(user_id=10, status="approved")
    db.subscribe(user_id=10, channel_id=1, mode="all")
    db.set_channel_filter(user_id=10, channel_id=1, filter_prompt="only AI")
    summarize = AsyncMock(return_value=_summary("Brief."))
    is_rel = AsyncMock()
    send_dm = _send_dm()

    await handle_new_post(
        channel_id=1, message_id=100, text="Crypto pump news",
        link="https://t.me/a/100", db=db, summarize_fn=summarize,
        is_relevant_fn=is_rel, send_dm=send_dm,
        embed_fn=_embed_fn(), edit_dm=_edit_dm(),
    )

    is_rel.assert_not_called()
    summarize.assert_awaited_once()
    expected = _expected_body("Channel A", "Brief.", "https://t.me/a/100")
    send_dm.assert_awaited_once_with(10, expected, None)


async def test_handle_new_post_mixes_modes_per_user(db: Database) -> None:
    db.upsert_channel(channel_id=1, title="Channel A")
    db.add_pending_user(user_id=10, username="alice")
    db.add_pending_user(user_id=20, username="bob")
    db.set_user_status(user_id=10, status="approved")
    db.set_user_status(user_id=20, status="approved")
    db.subscribe(user_id=10, channel_id=1, mode="all")
    db.subscribe(user_id=20, channel_id=1, mode="filtered")
    db.set_channel_filter(user_id=20, channel_id=1, filter_prompt="AI")
    summarize = AsyncMock(return_value=_summary("Brief."))
    is_rel = AsyncMock(return_value=_relevance(False))
    send_dm = _send_dm()

    await handle_new_post(
        channel_id=1, message_id=100, text="Crypto pump",
        link="https://t.me/a/100", db=db, summarize_fn=summarize,
        is_relevant_fn=is_rel, send_dm=send_dm,
        embed_fn=_embed_fn(), edit_dm=_edit_dm(),
    )

    is_rel.assert_awaited_once_with("Crypto pump", "AI")
    expected = _expected_body("Channel A", "Brief.", "https://t.me/a/100")
    send_dm.assert_awaited_once_with(10, expected, None)


async def test_handle_new_post_debug_mode_relevant_no_marker(db: Database) -> None:
    db.upsert_channel(channel_id=1, title="Channel A")
    db.add_pending_user(user_id=10, username="alice")
    db.set_user_status(user_id=10, status="approved")
    db.subscribe(user_id=10, channel_id=1, mode="debug")
    db.set_channel_filter(user_id=10, channel_id=1, filter_prompt="only AI")
    summarize = AsyncMock(return_value=_summary("Brief."))
    is_rel = AsyncMock(return_value=_relevance(True))
    send_dm = _send_dm()

    await handle_new_post(
        channel_id=1, message_id=100, text="AI news",
        link="https://t.me/a/100", db=db, summarize_fn=summarize,
        is_relevant_fn=is_rel, send_dm=send_dm,
        embed_fn=_embed_fn(), edit_dm=_edit_dm(),
    )

    is_rel.assert_awaited_once_with("AI news", "only AI")
    expected = _expected_body("Channel A", "Brief.", "https://t.me/a/100")
    send_dm.assert_awaited_once_with(10, expected, None)


async def test_handle_new_post_debug_mode_irrelevant_marks_filtered(db: Database) -> None:
    db.upsert_channel(channel_id=1, title="Channel A")
    db.add_pending_user(user_id=10, username="alice")
    db.set_user_status(user_id=10, status="approved")
    db.subscribe(user_id=10, channel_id=1, mode="debug")
    db.set_channel_filter(user_id=10, channel_id=1, filter_prompt="only AI")
    summarize = AsyncMock(return_value=_summary("Brief."))
    is_rel = AsyncMock(return_value=_relevance(False))
    send_dm = _send_dm()

    await handle_new_post(
        channel_id=1, message_id=100, text="Crypto pump",
        link="https://t.me/a/100", db=db, summarize_fn=summarize,
        is_relevant_fn=is_rel, send_dm=send_dm,
        embed_fn=_embed_fn(), edit_dm=_edit_dm(),
    )

    is_rel.assert_awaited_once_with("Crypto pump", "only AI")
    summarize.assert_awaited_once()
    send_dm.assert_awaited_once()
    body = send_dm.await_args.args[1]
    assert body.startswith("🐞 FILTERED\n")
    assert _expected_body("Channel A", "Brief.", "https://t.me/a/100") in body


async def test_handle_new_post_debug_mode_no_filter_no_marker(db: Database) -> None:
    db.upsert_channel(channel_id=1, title="Channel A")
    db.add_pending_user(user_id=10, username="alice")
    db.set_user_status(user_id=10, status="approved")
    db.subscribe(user_id=10, channel_id=1, mode="debug")
    summarize = AsyncMock(return_value=_summary("Brief."))
    is_rel = AsyncMock()
    send_dm = _send_dm()

    await handle_new_post(
        channel_id=1, message_id=100, text="anything",
        link="https://t.me/a/100", db=db, summarize_fn=summarize,
        is_relevant_fn=is_rel, send_dm=send_dm,
        embed_fn=_embed_fn(), edit_dm=_edit_dm(),
    )

    is_rel.assert_not_called()
    expected = _expected_body("Channel A", "Brief.", "https://t.me/a/100")
    send_dm.assert_awaited_once_with(10, expected, None)


async def test_handle_new_post_debug_marker_uses_user_language(db: Database) -> None:
    db.upsert_channel(channel_id=1, title="Channel A")
    db.add_pending_user(user_id=10, username="alice")
    db.set_user_status(user_id=10, status="approved")
    db.set_language(user_id=10, language="ru")
    db.subscribe(user_id=10, channel_id=1, mode="debug")
    db.set_channel_filter(user_id=10, channel_id=1, filter_prompt="only AI")
    summarize = AsyncMock(return_value=_summary("Brief."))
    is_rel = AsyncMock(return_value=_relevance(False))
    send_dm = _send_dm()

    await handle_new_post(
        channel_id=1, message_id=100, text="Crypto pump",
        link="https://t.me/a/100", db=db, summarize_fn=summarize,
        is_relevant_fn=is_rel, send_dm=send_dm,
        embed_fn=_embed_fn(), edit_dm=_edit_dm(),
    )

    body = send_dm.await_args.args[1]
    assert body.startswith("🐞 ОТФИЛЬТРОВАНО\n")


async def test_handle_new_post_debug_charges_filter_tokens_when_excluded(
    db: Database,
) -> None:
    db.upsert_channel(channel_id=1, title="A")
    db.add_pending_user(user_id=10, username="alice")
    db.set_user_status(user_id=10, status="approved")
    db.subscribe(user_id=10, channel_id=1, mode="debug")
    db.set_channel_filter(user_id=10, channel_id=1, filter_prompt="AI")
    summarize = AsyncMock(return_value=_summary("Brief.", input_tokens=100, output_tokens=20))
    is_rel = AsyncMock(return_value=_relevance(False, input_tokens=30, output_tokens=1))
    send_dm = _send_dm()

    await handle_new_post(
        channel_id=1, message_id=100, text="Crypto",
        link="https://t.me/a/100", db=db, summarize_fn=summarize,
        is_relevant_fn=is_rel, send_dm=send_dm,
        embed_fn=_embed_fn(), edit_dm=_edit_dm(),
    )

    assert db.get_usage(user_id=10) == [("anthropic", 130, 21)]
    assert db.get_system_usage() == [("anthropic", 130, 21)]


async def test_handle_new_post_debug_mixed_with_filtered_recipient(db: Database) -> None:
    db.upsert_channel(channel_id=1, title="Channel A")
    db.add_pending_user(user_id=10, username="alice")
    db.add_pending_user(user_id=20, username="bob")
    db.set_user_status(user_id=10, status="approved")
    db.set_user_status(user_id=20, status="approved")
    db.subscribe(user_id=10, channel_id=1, mode="filtered")
    db.subscribe(user_id=20, channel_id=1, mode="debug")
    db.set_channel_filter(user_id=10, channel_id=1, filter_prompt="AI")
    db.set_channel_filter(user_id=20, channel_id=1, filter_prompt="AI")
    summarize = AsyncMock(return_value=_summary("Brief."))
    is_rel = AsyncMock(return_value=_relevance(False))
    send_dm = _send_dm()

    await handle_new_post(
        channel_id=1, message_id=100, text="Crypto",
        link="https://t.me/a/100", db=db, summarize_fn=summarize,
        is_relevant_fn=is_rel, send_dm=send_dm,
        embed_fn=_embed_fn(), edit_dm=_edit_dm(),
    )

    summarize.assert_awaited_once()
    send_dm.assert_awaited_once()
    sent_user_id, body, _ = send_dm.await_args.args
    assert sent_user_id == 20
    assert body.startswith("🐞 FILTERED\n")


async def test_handle_new_post_filter_tokens_recorded_even_when_user_excluded(
    db: Database,
) -> None:
    db.upsert_channel(channel_id=1, title="A")
    db.add_pending_user(user_id=10, username="alice")
    db.set_user_status(user_id=10, status="approved")
    db.subscribe(user_id=10, channel_id=1)
    db.set_channel_filter(user_id=10, channel_id=1, filter_prompt="AI")
    summarize = AsyncMock()
    is_rel = AsyncMock(return_value=_relevance(False, input_tokens=30, output_tokens=1))
    send_dm = _send_dm()

    await handle_new_post(
        channel_id=1, message_id=100, text="Crypto pump",
        link="https://t.me/a/100", db=db, summarize_fn=summarize,
        is_relevant_fn=is_rel, send_dm=send_dm,
        embed_fn=_embed_fn(), edit_dm=_edit_dm(),
    )

    assert db.get_usage(user_id=10) == [("anthropic", 30, 1)]
    assert db.get_system_usage() == [("anthropic", 30, 1)]
    summarize.assert_not_called()


# ---------- refresh_channels ----------

async def test_refresh_upserts_new_channels(db: Database) -> None:
    fetch = AsyncMock(return_value=[
        (1, "Alpha", "alpha", "About Alpha"),
        (2, "Beta", "beta", None),
    ])
    send_dm = _send_dm()

    await refresh_channels(fetch_fn=fetch, db=db, send_dm=send_dm)

    rows = {c.id: c for c in db.list_channels(include_blacklisted=True)}
    assert rows[1].title == "Alpha"
    assert rows[1].username == "alpha"
    assert rows[1].about == "About Alpha"
    assert rows[2].title == "Beta"
    assert rows[2].username == "beta"
    assert rows[2].about is None
    send_dm.assert_not_called()


async def test_refresh_notifies_subscribers_when_channel_disappears(db: Database) -> None:
    db.upsert_channel(channel_id=1, title="Alpha")
    db.upsert_channel(channel_id=2, title="Gone")
    db.subscribe(user_id=10, channel_id=2)
    db.subscribe(user_id=20, channel_id=2)

    fetch = AsyncMock(return_value=[(1, "Alpha", "alpha", None)])
    send_dm = _send_dm()

    await refresh_channels(fetch_fn=fetch, db=db, send_dm=send_dm)

    assert send_dm.await_count == 2
    for call in send_dm.await_args_list:
        user_id, text = call.args
        assert user_id in {10, 20}
        assert "Gone" in text and "no longer available" in text.lower()
    assert {c.id for c in db.list_channels(include_blacklisted=True)} == {1}


async def test_refresh_announces_new_channels_to_approved_users(db: Database) -> None:
    db.upsert_channel(channel_id=1, title="Existing")
    db.add_pending_user(user_id=10, username="alice")
    db.set_user_status(user_id=10, status="approved")
    db.add_pending_user(user_id=20, username="bob")
    db.set_user_status(user_id=20, status="approved")
    db.add_pending_user(user_id=30, username="eve")  # pending, must be skipped

    fetch = AsyncMock(return_value=[
        (1, "Existing", "existing", None),
        (2, "Fresh", "fresh", None),
        (3, "Brand", "brand", None),
    ])
    send_dm = _send_dm()
    announce = AsyncMock()

    await refresh_channels(
        fetch_fn=fetch, db=db, send_dm=send_dm,
        announce_new_channel=announce,
    )

    assert announce.await_count == 4  # 2 new channels x 2 approved users
    announced = {(c.args[0], c.args[1], c.args[2]) for c in announce.await_args_list}
    assert announced == {
        (10, 2, "Fresh"), (20, 2, "Fresh"),
        (10, 3, "Brand"), (20, 3, "Brand"),
    }


async def test_refresh_skips_announce_on_first_run_empty_db(db: Database) -> None:
    db.add_pending_user(user_id=10, username="alice")
    db.set_user_status(user_id=10, status="approved")

    fetch = AsyncMock(return_value=[
        (1, "Alpha", "alpha", None),
        (2, "Beta", "beta", None),
    ])
    announce = AsyncMock()

    await refresh_channels(
        fetch_fn=fetch, db=db, send_dm=_send_dm(),
        announce_new_channel=announce,
    )

    announce.assert_not_called()
    assert {c.id for c in db.list_channels()} == {1, 2}


async def test_refresh_announce_optional(db: Database) -> None:
    db.upsert_channel(channel_id=1, title="Existing")
    db.add_pending_user(user_id=10, username="alice")
    db.set_user_status(user_id=10, status="approved")

    fetch = AsyncMock(return_value=[
        (1, "Existing", "existing", None),
        (2, "Fresh", "fresh", None),
    ])

    # Must not raise when announce_new_channel is omitted.
    await refresh_channels(fetch_fn=fetch, db=db, send_dm=_send_dm())

    assert {c.id for c in db.list_channels()} == {1, 2}


async def test_refresh_silent_for_disappeared_blacklisted_channels(db: Database) -> None:
    db.upsert_channel(channel_id=1, title="Alpha")
    db.upsert_channel(channel_id=2, title="WasBanned")
    db.subscribe(user_id=10, channel_id=2)
    db.set_blacklisted(channel_id=2, blacklisted=True)

    fetch = AsyncMock(return_value=[(1, "Alpha", "alpha", None)])
    send_dm = _send_dm()

    await refresh_channels(fetch_fn=fetch, db=db, send_dm=send_dm)

    send_dm.assert_not_called()
    assert {c.id for c in db.list_channels(include_blacklisted=True)} == {1}


# ---------- dedup ----------

async def test_handle_new_post_records_delivered_and_embedding_on_first_send(
    db: Database,
) -> None:
    db.upsert_channel(channel_id=1, title="Channel A")
    db.subscribe(user_id=10, channel_id=1, mode="all")
    summarize = AsyncMock(return_value=_summary("Brief."))
    is_rel = AsyncMock()
    send_dm = _send_dm(message_id=4242)
    embed_fn = _embed_fn(vector=[1.0, 0.0], tokens=8)
    edit_dm = _edit_dm()

    await handle_new_post(
        channel_id=1, message_id=100, text="hello",
        link="https://t.me/a/100", db=db, summarize_fn=summarize,
        is_relevant_fn=is_rel, send_dm=send_dm,
        embed_fn=embed_fn, edit_dm=edit_dm, now=1000,
    )

    edit_dm.assert_not_called()
    embed_fn.assert_awaited_once_with("Brief.")
    rows = db.list_dedup_candidates(user_id=10, since=0)
    assert len(rows) == 1
    cid, mid, bmid, is_p, dup_links, vec, link = rows[0]
    assert (cid, mid, bmid, is_p, dup_links, link) == (
        1, 100, 4242, False, [], "https://t.me/a/100",
    )
    assert vec == pytest.approx([1.0, 0.0], rel=1e-5)
    assert db.get_embedding_usage() == [("openai", 8)]


async def test_handle_new_post_dedup_edits_existing_on_duplicate(db: Database) -> None:
    db.upsert_channel(channel_id=1, title="Channel A")
    db.upsert_channel(channel_id=2, title="Channel B")
    db.subscribe(user_id=10, channel_id=1, mode="all")
    db.subscribe(user_id=10, channel_id=2, mode="all")
    db.store_post_embedding(
        channel_id=1, message_id=100, embedding=[1.0, 0.0],
        summary="prev", link="https://t.me/a/100", now=900,
    )
    prev_body = _expected_body("Channel A", "prev", "https://t.me/a/100")
    db.record_delivered(
        user_id=10, channel_id=1, message_id=100, bot_message_id=555,
        is_photo=False, body=prev_body, now=900,
    )
    summarize = AsyncMock(return_value=_summary("Brief."))
    is_rel = AsyncMock()
    send_dm = _send_dm()
    embed_fn = _embed_fn(vector=[1.0, 0.0])
    edit_dm = _edit_dm()

    await handle_new_post(
        channel_id=2, message_id=200, text="dup",
        link="https://t.me/b/200", db=db, summarize_fn=summarize,
        is_relevant_fn=is_rel, send_dm=send_dm,
        embed_fn=embed_fn, edit_dm=edit_dm, now=1000,
    )

    send_dm.assert_not_called()
    edit_dm.assert_awaited_once()
    args = edit_dm.await_args.args
    assert args[0] == 10
    assert args[1] == 555
    assert args[2] == [("Channel B", "https://t.me/b/200")]
    assert db.get_delivered_dup_links(
        user_id=10, channel_id=1, message_id=100
    ) == [("Channel B", "https://t.me/b/200")]
    # original prev_body was not consumed by the test, just here for context
    assert prev_body


async def test_handle_new_post_no_dedup_below_threshold(db: Database) -> None:
    db.upsert_channel(channel_id=1, title="A")
    db.upsert_channel(channel_id=2, title="B")
    db.subscribe(user_id=10, channel_id=1, mode="all")
    db.subscribe(user_id=10, channel_id=2, mode="all")
    db.store_post_embedding(
        channel_id=1, message_id=100, embedding=[1.0, 0.0],
        summary="prev", link="https://t.me/a/100", now=900,
    )
    db.record_delivered(
        user_id=10, channel_id=1, message_id=100, bot_message_id=555,
        is_photo=False, body="prev", now=900,
    )
    summarize = AsyncMock(return_value=_summary("Brief."))
    is_rel = AsyncMock()
    send_dm = _send_dm(message_id=777)
    embed_fn = _embed_fn(vector=[0.0, 1.0])
    edit_dm = _edit_dm()

    await handle_new_post(
        channel_id=2, message_id=200, text="diff",
        link="https://t.me/b/200", db=db, summarize_fn=summarize,
        is_relevant_fn=is_rel, send_dm=send_dm,
        embed_fn=embed_fn, edit_dm=edit_dm, now=1000,
    )

    edit_dm.assert_not_called()
    send_dm.assert_awaited_once()


async def test_handle_new_post_dedup_per_user(db: Database) -> None:
    db.upsert_channel(channel_id=1, title="A")
    db.upsert_channel(channel_id=2, title="B")
    db.subscribe(user_id=10, channel_id=2, mode="all")
    db.subscribe(user_id=20, channel_id=2, mode="all")
    db.store_post_embedding(
        channel_id=1, message_id=100, embedding=[1.0, 0.0],
        summary="prev", link="L1", now=900,
    )
    db.record_delivered(
        user_id=10, channel_id=1, message_id=100, bot_message_id=555,
        is_photo=False, body="prev_body", now=900,
    )
    summarize = AsyncMock(return_value=_summary("Brief."))
    is_rel = AsyncMock()
    send_dm = _send_dm(message_id=777)
    embed_fn = _embed_fn(vector=[1.0, 0.0])
    edit_dm = _edit_dm()

    await handle_new_post(
        channel_id=2, message_id=200, text="dup",
        link="https://t.me/b/200", db=db, summarize_fn=summarize,
        is_relevant_fn=is_rel, send_dm=send_dm,
        embed_fn=embed_fn, edit_dm=edit_dm, now=1000,
    )

    edit_dm.assert_awaited_once()
    edited_user = edit_dm.await_args.args[0]
    assert edited_user == 10
    send_dm.assert_awaited_once()
    sent_user = send_dm.await_args.args[0]
    assert sent_user == 20


async def test_handle_new_post_dedup_debug_marks_duplicate_with_marker(
    db: Database,
) -> None:
    db.upsert_channel(channel_id=1, title="Channel A")
    db.upsert_channel(channel_id=2, title="Channel B")
    db.subscribe(user_id=10, channel_id=2, mode="all")
    db.set_dedup_debug(user_id=10, enabled=True)
    db.store_post_embedding(
        channel_id=1, message_id=100, embedding=[1.0, 0.0],
        summary="prev", link="https://t.me/a/100", now=900,
    )
    db.record_delivered(
        user_id=10, channel_id=1, message_id=100, bot_message_id=555,
        is_photo=False, body="prev_body", now=900,
    )
    summarize = AsyncMock(return_value=_summary("Brief."))
    is_rel = AsyncMock()
    send_dm = _send_dm(message_id=777)
    embed_fn = _embed_fn(vector=[1.0, 0.0])
    edit_dm = _edit_dm()

    await handle_new_post(
        channel_id=2, message_id=200, text="dup",
        link="https://t.me/b/200", db=db, summarize_fn=summarize,
        is_relevant_fn=is_rel, send_dm=send_dm,
        embed_fn=embed_fn, edit_dm=edit_dm, now=1000,
    )

    edit_dm.assert_not_called()
    send_dm.assert_awaited_once()
    body = send_dm.await_args.args[1]
    assert body.startswith("🔁 DUPLICATE\n")
    assert (
        '↳ Original: <a href="https://t.me/a/100">Channel A</a>'
    ) in body
    rows = {r[1]: r for r in db.list_dedup_candidates(user_id=10, since=0)}
    assert 200 in rows


async def test_handle_new_post_dedup_debug_marker_and_original_link_localized(
    db: Database,
) -> None:
    db.upsert_channel(channel_id=1, title="Канал А")
    db.upsert_channel(channel_id=2, title="B")
    db.add_pending_user(user_id=10, username="alice")
    db.set_user_status(user_id=10, status="approved")
    db.set_language(user_id=10, language="ru")
    db.subscribe(user_id=10, channel_id=2, mode="all")
    db.set_dedup_debug(user_id=10, enabled=True)
    db.store_post_embedding(
        channel_id=1, message_id=100, embedding=[1.0, 0.0],
        summary="prev", link="https://t.me/a/100", now=900,
    )
    db.record_delivered(
        user_id=10, channel_id=1, message_id=100, bot_message_id=555,
        is_photo=False, body="prev", now=900,
    )
    summarize = AsyncMock(return_value=_summary("Brief."))
    is_rel = AsyncMock()
    send_dm = _send_dm()
    embed_fn = _embed_fn(vector=[1.0, 0.0])
    edit_dm = _edit_dm()

    await handle_new_post(
        channel_id=2, message_id=200, text="dup",
        link="https://t.me/b/200", db=db, summarize_fn=summarize,
        is_relevant_fn=is_rel, send_dm=send_dm,
        embed_fn=embed_fn, edit_dm=edit_dm, now=1000,
    )

    body = send_dm.await_args.args[1]
    assert body.startswith("🔁 ДУБЛЬ\n")
    assert '↳ Оригинал: <a href="https://t.me/a/100">Канал А</a>' in body


async def test_handle_new_post_filter_debug_without_dedup_debug_chains(
    db: Database,
) -> None:
    """`mode='debug'` alone (filter-debug) keeps the silent edit-chain path
    on duplicates — only the user-level dedup_debug toggle promotes them
    to a fresh DM."""
    db.upsert_channel(channel_id=1, title="A")
    db.upsert_channel(channel_id=2, title="B")
    db.subscribe(user_id=10, channel_id=2, mode="debug")
    db.store_post_embedding(
        channel_id=1, message_id=100, embedding=[1.0, 0.0],
        summary="prev", link="L1", now=900,
    )
    db.record_delivered(
        user_id=10, channel_id=1, message_id=100, bot_message_id=555,
        is_photo=False, body="prev", now=900,
    )
    summarize = AsyncMock(return_value=_summary("Brief."))
    is_rel = AsyncMock()
    send_dm = _send_dm()
    embed_fn = _embed_fn(vector=[1.0, 0.0])
    edit_dm = _edit_dm()

    await handle_new_post(
        channel_id=2, message_id=200, text="dup",
        link="https://t.me/b/200", db=db, summarize_fn=summarize,
        is_relevant_fn=is_rel, send_dm=send_dm,
        embed_fn=embed_fn, edit_dm=edit_dm, now=1000,
    )

    send_dm.assert_not_called()
    edit_dm.assert_awaited_once()


async def test_handle_new_post_dedup_outside_window_treated_as_new(db: Database) -> None:
    db.upsert_channel(channel_id=1, title="A")
    db.upsert_channel(channel_id=2, title="B")
    db.subscribe(user_id=10, channel_id=2, mode="all")
    db.store_post_embedding(
        channel_id=1, message_id=100, embedding=[1.0, 0.0],
        summary="old", link="L1", now=100,
    )
    db.record_delivered(
        user_id=10, channel_id=1, message_id=100, bot_message_id=1,
        is_photo=False, body="old", now=100,
    )
    summarize = AsyncMock(return_value=_summary("Brief."))
    is_rel = AsyncMock()
    send_dm = _send_dm()
    embed_fn = _embed_fn(vector=[1.0, 0.0])
    edit_dm = _edit_dm()

    await handle_new_post(
        channel_id=2, message_id=200, text="dup",
        link="https://t.me/b/200", db=db, summarize_fn=summarize,
        is_relevant_fn=is_rel, send_dm=send_dm,
        embed_fn=embed_fn, edit_dm=edit_dm,
        dedup_window_seconds=60, now=10_000,
    )

    edit_dm.assert_not_called()
    send_dm.assert_awaited_once()


async def test_handle_new_post_embeds_only_once_for_multiple_recipients(
    db: Database,
) -> None:
    db.upsert_channel(channel_id=1, title="A")
    db.subscribe(user_id=10, channel_id=1, mode="all")
    db.subscribe(user_id=20, channel_id=1, mode="all")
    summarize = AsyncMock(return_value=_summary("Brief."))
    is_rel = AsyncMock()
    send_dm = _send_dm()
    embed_fn = _embed_fn(vector=[0.0, 1.0])
    edit_dm = _edit_dm()

    await handle_new_post(
        channel_id=1, message_id=100, text="hello",
        link="https://t.me/a/100", db=db, summarize_fn=summarize,
        is_relevant_fn=is_rel, send_dm=send_dm,
        embed_fn=embed_fn, edit_dm=edit_dm, now=1000,
    )

    embed_fn.assert_awaited_once()
    assert send_dm.await_count == 2


async def test_handle_new_post_dedup_edit_targets_existing_message(db: Database) -> None:
    db.upsert_channel(channel_id=1, title="A")
    db.upsert_channel(channel_id=2, title="Channel B")
    db.subscribe(user_id=10, channel_id=2, mode="all")
    db.store_post_embedding(
        channel_id=1, message_id=100, embedding=[1.0, 0.0],
        summary="prev", link="L1", now=900,
    )
    db.record_delivered(
        user_id=10, channel_id=1, message_id=100, bot_message_id=555,
        is_photo=True, body="prev", now=900,
    )
    summarize = AsyncMock(return_value=_summary("Brief."))
    is_rel = AsyncMock()
    send_dm = _send_dm()
    embed_fn = _embed_fn(vector=[1.0, 0.0])
    edit_dm = _edit_dm()

    await handle_new_post(
        channel_id=2, message_id=200, text="dup",
        link="https://t.me/b/200", db=db, summarize_fn=summarize,
        is_relevant_fn=is_rel, send_dm=send_dm,
        embed_fn=embed_fn, edit_dm=edit_dm, now=1000,
    )

    assert edit_dm.await_args.args[1] == 555
    assert edit_dm.await_args.args[2] == [("Channel B", "https://t.me/b/200")]


async def test_handle_new_post_dedup_accumulates_links_for_chained_dups(
    db: Database,
) -> None:
    db.upsert_channel(channel_id=1, title="A")
    db.upsert_channel(channel_id=2, title="B")
    db.upsert_channel(channel_id=3, title="C")
    db.subscribe(user_id=10, channel_id=2, mode="all")
    db.subscribe(user_id=10, channel_id=3, mode="all")
    db.store_post_embedding(
        channel_id=1, message_id=100, embedding=[1.0, 0.0],
        summary="prev", link="L1", now=900,
    )
    db.record_delivered(
        user_id=10, channel_id=1, message_id=100, bot_message_id=555,
        is_photo=False, body="orig", now=900,
    )
    summarize = AsyncMock(return_value=_summary("Brief."))
    is_rel = AsyncMock()
    embed_fn = _embed_fn(vector=[1.0, 0.0])
    edit_dm_2 = _edit_dm()
    edit_dm_3 = _edit_dm()

    await handle_new_post(
        channel_id=2, message_id=200, text="dup1",
        link="L2", db=db, summarize_fn=summarize,
        is_relevant_fn=is_rel, send_dm=_send_dm(),
        embed_fn=embed_fn, edit_dm=edit_dm_2, now=1000,
    )
    await handle_new_post(
        channel_id=3, message_id=300, text="dup2",
        link="L3", db=db, summarize_fn=summarize,
        is_relevant_fn=is_rel, send_dm=_send_dm(),
        embed_fn=embed_fn, edit_dm=edit_dm_3, now=1100,
    )

    assert edit_dm_2.await_args.args[2] == [("B", "L2")]
    assert edit_dm_3.await_args.args[2] == [("B", "L2"), ("C", "L3")]
    assert db.get_delivered_dup_links(
        user_id=10, channel_id=1, message_id=100
    ) == [("B", "L2"), ("C", "L3")]


async def test_handle_new_post_dedup_charges_embedding_tokens_to_system(
    db: Database,
) -> None:
    db.upsert_channel(channel_id=1, title="A")
    db.subscribe(user_id=10, channel_id=1, mode="all")
    summarize = AsyncMock(return_value=_summary("Brief."))
    is_rel = AsyncMock()
    embed_fn = _embed_fn(vector=[1.0, 0.0], tokens=42)

    await handle_new_post(
        channel_id=1, message_id=100, text="hello",
        link="L", db=db, summarize_fn=summarize,
        is_relevant_fn=is_rel, send_dm=_send_dm(),
        embed_fn=embed_fn, edit_dm=_edit_dm(), now=1000,
    )

    assert db.get_embedding_usage() == [("openai", 42)]


async def test_handle_new_post_skips_dedup_when_embed_fn_is_none(db: Database) -> None:
    db.upsert_channel(channel_id=1, title="Channel A")
    db.subscribe(user_id=10, channel_id=1, mode="all")
    summarize = AsyncMock(return_value=_summary("Brief."))
    is_rel = AsyncMock()
    send_dm = _send_dm(message_id=4242)

    await handle_new_post(
        channel_id=1, message_id=100, text="hello",
        link="https://t.me/a/100", db=db, summarize_fn=summarize,
        is_relevant_fn=is_rel, send_dm=send_dm,
        embed_fn=None, edit_dm=None, now=1000,
    )

    send_dm.assert_awaited_once()
    assert db.get_embedding_usage() == []
    assert db.list_dedup_candidates(user_id=10, since=0) == []


async def test_handle_new_post_no_embed_fn_does_not_dedup_against_history(
    db: Database,
) -> None:
    db.upsert_channel(channel_id=1, title="A")
    db.upsert_channel(channel_id=2, title="B")
    db.subscribe(user_id=10, channel_id=2, mode="all")
    db.store_post_embedding(
        channel_id=1, message_id=100, embedding=[1.0, 0.0],
        summary="prev", link="L1", now=900,
    )
    db.record_delivered(
        user_id=10, channel_id=1, message_id=100, bot_message_id=555,
        is_photo=False, body="prev", now=900,
    )
    summarize = AsyncMock(return_value=_summary("Brief."))
    is_rel = AsyncMock()
    send_dm = _send_dm(message_id=777)

    await handle_new_post(
        channel_id=2, message_id=200, text="dup",
        link="https://t.me/b/200", db=db, summarize_fn=summarize,
        is_relevant_fn=is_rel, send_dm=send_dm,
        embed_fn=None, edit_dm=None, now=1000,
    )

    send_dm.assert_awaited_once()
    assert db.get_delivered_dup_links(
        user_id=10, channel_id=1, message_id=100
    ) == []


# ---------- auto-delete ----------

async def test_handle_new_post_no_save_button_when_auto_delete_off(
    db: Database,
) -> None:
    db.upsert_channel(channel_id=1, title="A")
    db.subscribe(user_id=10, channel_id=1, mode="all")
    summarize = AsyncMock(return_value=_summary("Brief."))
    is_rel = AsyncMock()
    send_dm = _send_dm()

    await handle_new_post(
        channel_id=1, message_id=100, text="body",
        link="L", db=db, summarize_fn=summarize,
        is_relevant_fn=is_rel, send_dm=send_dm,
        embed_fn=_embed_fn(), edit_dm=_edit_dm(), now=1000,
    )

    assert "save_button" not in send_dm.await_args.kwargs
    state = db.get_delivered_save_state(user_id=10, channel_id=1, message_id=100)
    assert state == (False, None)


async def test_handle_new_post_attaches_save_button_and_delete_at(
    db: Database,
) -> None:
    db.upsert_channel(channel_id=1, title="A")
    db.subscribe(user_id=10, channel_id=1, mode="all")
    db.set_user_auto_delete_hours(10, 6)
    summarize = AsyncMock(return_value=_summary("Brief."))
    is_rel = AsyncMock()
    send_dm = _send_dm()

    await handle_new_post(
        channel_id=1, message_id=100, text="body",
        link="L", db=db, summarize_fn=summarize,
        is_relevant_fn=is_rel, send_dm=send_dm,
        embed_fn=_embed_fn(), edit_dm=_edit_dm(), now=1000,
    )

    label = send_dm.await_args.kwargs["save_button"]
    assert label  # localized non-empty string
    state = db.get_delivered_save_state(user_id=10, channel_id=1, message_id=100)
    assert state == (False, 1000 + 6 * 3600)


async def test_handle_new_post_records_delivered_when_dedup_disabled(
    db: Database,
) -> None:
    db.upsert_channel(channel_id=1, title="A")
    db.subscribe(user_id=10, channel_id=1, mode="all")
    db.set_user_auto_delete_hours(10, 6)
    summarize = AsyncMock(return_value=_summary("Brief."))
    is_rel = AsyncMock()
    send_dm = _send_dm()

    await handle_new_post(
        channel_id=1, message_id=100, text="body",
        link="L", db=db, summarize_fn=summarize,
        is_relevant_fn=is_rel, send_dm=send_dm,
        embed_fn=None, edit_dm=None, now=1000,
    )

    state = db.get_delivered_save_state(user_id=10, channel_id=1, message_id=100)
    assert state == (False, 1000 + 6 * 3600)


async def test_handle_new_post_dup_chain_extends_delete_at(
    db: Database,
) -> None:
    db.upsert_channel(channel_id=1, title="A")
    db.upsert_channel(channel_id=2, title="B")
    db.subscribe(user_id=10, channel_id=2, mode="all")
    db.set_user_auto_delete_hours(10, 6)
    db.store_post_embedding(
        channel_id=1, message_id=100, embedding=[1.0, 0.0],
        summary="prev", link="L1", now=900,
    )
    db.record_delivered(
        user_id=10, channel_id=1, message_id=100, bot_message_id=555,
        is_photo=False, body="prev_body", now=900, delete_at=900 + 6 * 3600,
    )
    summarize = AsyncMock(return_value=_summary("Brief."))
    is_rel = AsyncMock()
    send_dm = _send_dm()
    embed_fn = _embed_fn(vector=[1.0, 0.0])
    edit_dm = _edit_dm()

    await handle_new_post(
        channel_id=2, message_id=200, text="dup",
        link="L2", db=db, summarize_fn=summarize,
        is_relevant_fn=is_rel, send_dm=send_dm,
        embed_fn=embed_fn, edit_dm=edit_dm, now=2000,
    )

    edit_dm.assert_awaited_once()
    assert edit_dm.await_args.kwargs.get("save_button")
    state = db.get_delivered_save_state(
        user_id=10, channel_id=1, message_id=100,
    )
    assert state == (False, 2000 + 6 * 3600)


async def test_handle_new_post_dup_chain_skips_extension_when_saved(
    db: Database,
) -> None:
    db.upsert_channel(channel_id=1, title="A")
    db.upsert_channel(channel_id=2, title="B")
    db.subscribe(user_id=10, channel_id=2, mode="all")
    db.set_user_auto_delete_hours(10, 6)
    db.store_post_embedding(
        channel_id=1, message_id=100, embedding=[1.0, 0.0],
        summary="prev", link="L1", now=900,
    )
    db.record_delivered(
        user_id=10, channel_id=1, message_id=100, bot_message_id=555,
        is_photo=False, body="prev_body", now=900, delete_at=900 + 6 * 3600,
    )
    db.set_delivered_saved(
        user_id=10, channel_id=1, message_id=100, saved=True, delete_at=None,
    )
    summarize = AsyncMock(return_value=_summary("Brief."))
    is_rel = AsyncMock()
    send_dm = _send_dm()
    embed_fn = _embed_fn(vector=[1.0, 0.0])
    edit_dm = _edit_dm()

    await handle_new_post(
        channel_id=2, message_id=200, text="dup",
        link="L2", db=db, summarize_fn=summarize,
        is_relevant_fn=is_rel, send_dm=send_dm,
        embed_fn=embed_fn, edit_dm=edit_dm, now=2000,
    )

    edit_dm.assert_awaited_once()
    # saved button label, not save
    assert edit_dm.await_args.kwargs.get("save_button")
    state = db.get_delivered_save_state(
        user_id=10, channel_id=1, message_id=100,
    )
    assert state == (True, None)
