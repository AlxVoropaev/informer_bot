from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from informer_bot.summarizer import (
    EMBED_DIMENSIONS,
    EMBED_MODEL,
    PRICE_PER_MTOK_INPUT,
    PRICE_PER_MTOK_OUTPUT,
    embed_summary,
    estimate_cost_usd,
    is_relevant,
    summarize,
)


def _fake_response(text: str, input_tokens: int = 12, output_tokens: int = 7) -> SimpleNamespace:
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
        usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens),
    )


@pytest.fixture
def fake_client() -> AsyncMock:
    client = AsyncMock()
    client.messages.create = AsyncMock(return_value=_fake_response("A short brief."))
    return client


async def test_summarize_returns_text_and_usage(fake_client: AsyncMock) -> None:
    fake_client.messages.create.return_value = _fake_response(
        "A short brief.", input_tokens=42, output_tokens=11
    )

    result = await summarize("Some long post text", client=fake_client)

    assert result.text == "A short brief."
    assert result.input_tokens == 42
    assert result.output_tokens == 11


async def test_summarize_calls_haiku_with_system_prompt_and_user_text(
    fake_client: AsyncMock,
) -> None:
    await summarize("Post body here", client=fake_client)

    fake_client.messages.create.assert_awaited_once()
    kwargs = fake_client.messages.create.await_args.kwargs
    assert kwargs["model"] == "claude-haiku-4-5"
    assert isinstance(kwargs["max_tokens"], int) and kwargs["max_tokens"] > 0
    assert "one or two sentences" in kwargs["system"].lower()
    assert "language of the post" in kwargs["system"].lower()
    assert kwargs["messages"] == [{"role": "user", "content": "Post body here"}]


async def test_summarize_strips_whitespace(fake_client: AsyncMock) -> None:
    fake_client.messages.create.return_value = _fake_response("  Brief with padding.\n\n")

    result = await summarize("anything", client=fake_client)

    assert result.text == "Brief with padding."


async def test_is_relevant_yes(fake_client: AsyncMock) -> None:
    fake_client.messages.create.return_value = _fake_response(
        "YES", input_tokens=30, output_tokens=1
    )

    result = await is_relevant("Post about AI", "I want AI news", client=fake_client)

    assert result.relevant is True
    assert result.input_tokens == 30
    assert result.output_tokens == 1


async def test_is_relevant_no(fake_client: AsyncMock) -> None:
    fake_client.messages.create.return_value = _fake_response("NO")

    result = await is_relevant("Crypto pump", "I want AI news", client=fake_client)

    assert result.relevant is False


async def test_is_relevant_tolerates_whitespace_and_case(fake_client: AsyncMock) -> None:
    fake_client.messages.create.return_value = _fake_response("  yes\n")

    result = await is_relevant("post", "filter", client=fake_client)

    assert result.relevant is True


async def test_is_relevant_passes_filter_and_post_to_user_message(
    fake_client: AsyncMock,
) -> None:
    fake_client.messages.create.return_value = _fake_response("YES")

    await is_relevant("POST_BODY", "FILTER_TEXT", client=fake_client)

    kwargs = fake_client.messages.create.await_args.kwargs
    assert kwargs["model"] == "claude-haiku-4-5"
    assert "classifier" in kwargs["system"].lower() or "relevan" in kwargs["system"].lower()
    user_content = kwargs["messages"][0]["content"]
    assert "FILTER_TEXT" in user_content
    assert "POST_BODY" in user_content


def _fake_embed_response(vector: list[float], total_tokens: int = 8) -> SimpleNamespace:
    return SimpleNamespace(
        data=[SimpleNamespace(embedding=vector, index=0)],
        usage=SimpleNamespace(total_tokens=total_tokens, prompt_tokens=total_tokens),
    )


async def test_embed_summary_returns_vector_and_tokens() -> None:
    client = AsyncMock()
    client.embeddings.create = AsyncMock(
        return_value=_fake_embed_response([0.1, 0.2, 0.3], total_tokens=11)
    )

    result = await embed_summary("Brief summary.", client=client)

    assert result.vector == [0.1, 0.2, 0.3]
    assert result.tokens == 11


async def test_embed_summary_uses_configured_model_and_dims() -> None:
    client = AsyncMock()
    client.embeddings.create = AsyncMock(
        return_value=_fake_embed_response([0.0])
    )

    await embed_summary("Brief.", client=client)

    kwargs = client.embeddings.create.await_args.kwargs
    assert kwargs["model"] == EMBED_MODEL
    assert kwargs["dimensions"] == EMBED_DIMENSIONS
    assert kwargs["input"] == "Brief."


async def test_embed_summary_omits_dimensions_when_none() -> None:
    client = AsyncMock()
    client.embeddings.create = AsyncMock(
        return_value=_fake_embed_response([0.0])
    )

    await embed_summary("Brief.", client=client, dimensions=None)

    kwargs = client.embeddings.create.await_args.kwargs
    assert "dimensions" not in kwargs


def _fake_chat_response(
    content: str, prompt_tokens: int = 12, completion_tokens: int = 7
) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(
            prompt_tokens=prompt_tokens, completion_tokens=completion_tokens
        ),
    )


async def test_summarize_ollama_returns_text_and_usage() -> None:
    from informer_bot.summarizer import summarize_ollama

    client = AsyncMock()
    client.chat.completions.create = AsyncMock(
        return_value=_fake_chat_response("brief", prompt_tokens=12, completion_tokens=3)
    )

    result = await summarize_ollama("Some long post", client=client, model="qwen3.5:4b")

    assert result.text == "brief"
    assert result.input_tokens == 12
    assert result.output_tokens == 3


async def test_summarize_ollama_calls_with_temperature_zero_and_model() -> None:
    from informer_bot.summarizer import summarize_ollama

    client = AsyncMock()
    client.chat.completions.create = AsyncMock(
        return_value=_fake_chat_response("brief")
    )

    await summarize_ollama("Body", client=client, model="qwen3.5:4b")

    kwargs = client.chat.completions.create.await_args.kwargs
    assert kwargs["model"] == "qwen3.5:4b"
    assert kwargs["temperature"] == 0
    assert isinstance(kwargs["max_tokens"], int) and kwargs["max_tokens"] > 0
    assert kwargs["messages"][0]["role"] == "system"
    assert kwargs["messages"][1] == {"role": "user", "content": "Body"}


async def test_is_relevant_ollama_yes_and_no() -> None:
    from informer_bot.summarizer import is_relevant_ollama

    client = AsyncMock()
    client.chat.completions.create = AsyncMock(
        return_value=_fake_chat_response("YES")
    )
    yes = await is_relevant_ollama(
        "Post", "filter", client=client, model="qwen3.5:4b"
    )
    assert yes.relevant is True

    client.chat.completions.create = AsyncMock(
        return_value=_fake_chat_response("NO")
    )
    no = await is_relevant_ollama(
        "Post", "filter", client=client, model="qwen3.5:4b"
    )
    assert no.relevant is False


def test_estimate_cost_usd_matches_per_mtok_pricing() -> None:
    cost = estimate_cost_usd(input_tokens=1_000_000, output_tokens=0)
    assert cost == pytest.approx(PRICE_PER_MTOK_INPUT)

    cost = estimate_cost_usd(input_tokens=0, output_tokens=1_000_000)
    assert cost == pytest.approx(PRICE_PER_MTOK_OUTPUT)

    cost = estimate_cost_usd(input_tokens=500_000, output_tokens=200_000)
    assert cost == pytest.approx(
        0.5 * PRICE_PER_MTOK_INPUT + 0.2 * PRICE_PER_MTOK_OUTPUT
    )
