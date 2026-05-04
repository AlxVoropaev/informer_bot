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
    assert "single-sentence" in kwargs["system"].lower()
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


async def test_local_embedder_wraps_fastembed_with_zero_tokens(monkeypatch) -> None:
    import sys

    from informer_bot import summarizer

    class FakeVector:
        def __init__(self, values: list[float]) -> None:
            self._values = values

        def tolist(self) -> list[float]:
            return list(self._values)

    class FakeTextEmbedding:
        def __init__(self, model_name: str, threads: int | None = None) -> None:
            self.model_name = model_name
            self.threads = threads

        def embed(self, texts):
            for _ in texts:
                yield FakeVector([0.5, -0.5, 0.25])

        @staticmethod
        def list_supported_models():
            return [{"model": "fake/model"}]

        @staticmethod
        def add_custom_model(**kwargs) -> None:
            pass

    monkeypatch.setitem(sys.modules, "fastembed", SimpleNamespace(TextEmbedding=FakeTextEmbedding))

    embedder = summarizer.LocalEmbedder(model_name="fake/model")
    result = await embedder.embed("Brief summary.")

    assert result.tokens == 0
    assert result.vector == [0.5, -0.5, 0.25]
    assert embedder.model_name == "fake/model"


def test_estimate_cost_usd_matches_per_mtok_pricing() -> None:
    cost = estimate_cost_usd(input_tokens=1_000_000, output_tokens=0)
    assert cost == pytest.approx(PRICE_PER_MTOK_INPUT)

    cost = estimate_cost_usd(input_tokens=0, output_tokens=1_000_000)
    assert cost == pytest.approx(PRICE_PER_MTOK_OUTPUT)

    cost = estimate_cost_usd(input_tokens=500_000, output_tokens=200_000)
    assert cost == pytest.approx(
        0.5 * PRICE_PER_MTOK_INPUT + 0.2 * PRICE_PER_MTOK_OUTPUT
    )
