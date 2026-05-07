from types import SimpleNamespace
from unittest.mock import AsyncMock

from processor_bot.handlers import handle_request
from shared.protocol import (
    EmbedReply,
    EmbedRequest,
    IsRelevantReply,
    IsRelevantRequest,
    PingReply,
    PingRequest,
    SummarizeReply,
    SummarizeRequest,
)


def _fake_chat(content: str, prompt_tokens: int = 5, completion_tokens: int = 2) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(
            prompt_tokens=prompt_tokens, completion_tokens=completion_tokens
        ),
    )


def _fake_embed(vector: list[float], total_tokens: int = 4) -> SimpleNamespace:
    return SimpleNamespace(
        data=[SimpleNamespace(embedding=vector, index=0)],
        usage=SimpleNamespace(total_tokens=total_tokens, prompt_tokens=total_tokens),
    )


async def test_ping_returns_ping_reply_with_same_id() -> None:
    client = AsyncMock()
    req = PingRequest.new()

    reply = await handle_request(
        req, client=client, chat_model="m", embedding_model="e",
    )

    assert isinstance(reply, PingReply)
    assert reply.id == req.id


async def test_summarize_returns_summarize_reply() -> None:
    client = AsyncMock()
    client.chat.completions.create = AsyncMock(
        return_value=_fake_chat("brief", prompt_tokens=10, completion_tokens=3)
    )
    req = SummarizeRequest.new("Some long post")

    reply = await handle_request(
        req, client=client, chat_model="qwen3.5:4b", embedding_model="e",
    )

    assert isinstance(reply, SummarizeReply)
    assert reply.id == req.id
    assert reply.text == "brief"
    assert reply.input_tokens == 10
    assert reply.output_tokens == 3


async def test_is_relevant_yes() -> None:
    client = AsyncMock()
    client.chat.completions.create = AsyncMock(return_value=_fake_chat("YES"))
    req = IsRelevantRequest.new("Post", "I want AI")

    reply = await handle_request(
        req, client=client, chat_model="qwen3.5:4b", embedding_model="e",
    )

    assert isinstance(reply, IsRelevantReply)
    assert reply.id == req.id
    assert reply.relevant is True


async def test_is_relevant_no() -> None:
    client = AsyncMock()
    client.chat.completions.create = AsyncMock(return_value=_fake_chat("NO"))
    req = IsRelevantRequest.new("Post", "filter")

    reply = await handle_request(
        req, client=client, chat_model="qwen3.5:4b", embedding_model="e",
    )

    assert isinstance(reply, IsRelevantReply)
    assert reply.relevant is False


async def test_embed_returns_embed_reply() -> None:
    client = AsyncMock()
    client.embeddings.create = AsyncMock(
        return_value=_fake_embed([0.1, 0.2, 0.3], total_tokens=7)
    )
    req = EmbedRequest.new("Brief.", dimensions=512)

    reply = await handle_request(
        req, client=client, chat_model="c", embedding_model="qwen3-embedding:4b",
    )

    assert isinstance(reply, EmbedReply)
    assert reply.id == req.id
    assert reply.vector == [0.1, 0.2, 0.3]
    assert reply.tokens == 7
    assert reply.model == "qwen3-embedding:4b"


async def test_embed_passes_model_and_dimensions() -> None:
    client = AsyncMock()
    client.embeddings.create = AsyncMock(return_value=_fake_embed([0.0]))
    req = EmbedRequest.new("text", dimensions=128)

    await handle_request(
        req, client=client, chat_model="c", embedding_model="emb-model",
    )

    kwargs = client.embeddings.create.await_args.kwargs
    assert kwargs["model"] == "emb-model"
    assert kwargs["dimensions"] == 128
    assert kwargs["input"] == "text"
