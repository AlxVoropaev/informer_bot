from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from informer_bot.fallback_dispatcher import FallbackDispatcher
from informer_bot.remote_processor import (
    RemoteProcessorError,
    RemoteProcessorTimeout,
)
from informer_bot.summarizer import Embedding, RelevanceCheck, Summary


def _summary(text: str, provider: str = "remote") -> Summary:
    return Summary(text=text, input_tokens=1, output_tokens=1, provider=provider)


def _relevance(flag: bool, provider: str = "remote") -> RelevanceCheck:
    return RelevanceCheck(
        relevant=flag, input_tokens=1, output_tokens=1, provider=provider,
    )


def _embedding(provider: str = "remote") -> Embedding:
    return Embedding(vector=[0.1, 0.2], tokens=2, provider=provider, model="m")


def _remote(*, healthy: bool, **methods: AsyncMock) -> SimpleNamespace:
    return SimpleNamespace(
        healthy=healthy,
        summarize=methods.get("summarize", AsyncMock()),
        is_relevant=methods.get("is_relevant", AsyncMock()),
        embed=methods.get("embed", AsyncMock()),
    )


async def test_summarize_healthy_uses_remote() -> None:
    remote_summarize = AsyncMock(return_value=_summary("remote"))
    fb = AsyncMock(return_value=_summary("fb"))
    remote = _remote(healthy=True, summarize=remote_summarize)
    d = FallbackDispatcher(
        remote=remote,  # type: ignore[arg-type]
        fallback_summarize=fb,
        fallback_is_relevant=None,
        fallback_embed=None,
    )

    result = await d.summarize("text")

    assert result.text == "remote"
    remote_summarize.assert_awaited_once_with("text", system_prompt=None)
    fb.assert_not_awaited()


async def test_summarize_forwards_system_prompt_to_remote() -> None:
    remote_summarize = AsyncMock(return_value=_summary("remote"))
    fb = AsyncMock(return_value=_summary("fb"))
    remote = _remote(healthy=True, summarize=remote_summarize)
    d = FallbackDispatcher(
        remote=remote,  # type: ignore[arg-type]
        fallback_summarize=fb,
        fallback_is_relevant=None,
        fallback_embed=None,
    )

    await d.summarize("text", system_prompt="CUSTOM")

    remote_summarize.assert_awaited_once_with("text", system_prompt="CUSTOM")
    fb.assert_not_awaited()


async def test_summarize_forwards_system_prompt_to_fallback() -> None:
    remote_summarize = AsyncMock(side_effect=RemoteProcessorTimeout("timed out"))
    fb = AsyncMock(return_value=_summary("fb"))
    remote = _remote(healthy=True, summarize=remote_summarize)
    d = FallbackDispatcher(
        remote=remote,  # type: ignore[arg-type]
        fallback_summarize=fb,
        fallback_is_relevant=None,
        fallback_embed=None,
    )

    await d.summarize("text", system_prompt="CUSTOM")

    fb.assert_awaited_once_with("text", system_prompt="CUSTOM")


async def test_summarize_unhealthy_skips_remote() -> None:
    remote_summarize = AsyncMock(return_value=_summary("remote"))
    fb = AsyncMock(return_value=_summary("fb"))
    remote = _remote(healthy=False, summarize=remote_summarize)
    d = FallbackDispatcher(
        remote=remote,  # type: ignore[arg-type]
        fallback_summarize=fb,
        fallback_is_relevant=None,
        fallback_embed=None,
    )

    result = await d.summarize("text")

    assert result.text == "fb"
    remote_summarize.assert_not_awaited()
    fb.assert_awaited_once_with("text", system_prompt=None)


async def test_summarize_remote_timeout_falls_back() -> None:
    remote_summarize = AsyncMock(side_effect=RemoteProcessorTimeout("timed out"))
    fb = AsyncMock(return_value=_summary("fb"))
    remote = _remote(healthy=True, summarize=remote_summarize)
    d = FallbackDispatcher(
        remote=remote,  # type: ignore[arg-type]
        fallback_summarize=fb,
        fallback_is_relevant=None,
        fallback_embed=None,
    )

    result = await d.summarize("text")

    assert result.text == "fb"
    fb.assert_awaited_once_with("text", system_prompt=None)


async def test_summarize_remote_processor_error_falls_back() -> None:
    remote_summarize = AsyncMock(side_effect=RemoteProcessorError("model crashed"))
    fb = AsyncMock(return_value=_summary("fb"))
    remote = _remote(healthy=True, summarize=remote_summarize)
    d = FallbackDispatcher(
        remote=remote,  # type: ignore[arg-type]
        fallback_summarize=fb,
        fallback_is_relevant=None,
        fallback_embed=None,
    )

    result = await d.summarize("text")

    assert result.text == "fb"
    fb.assert_awaited_once_with("text", system_prompt=None)


async def test_summarize_no_fallback_propagates_remote_error() -> None:
    remote_summarize = AsyncMock(side_effect=RemoteProcessorTimeout("timed out"))
    remote = _remote(healthy=True, summarize=remote_summarize)
    d = FallbackDispatcher(
        remote=remote,  # type: ignore[arg-type]
        fallback_summarize=None,
        fallback_is_relevant=None,
        fallback_embed=None,
    )

    with pytest.raises(RemoteProcessorTimeout):
        await d.summarize("text")


async def test_summarize_no_fallback_when_unhealthy_raises() -> None:
    remote = _remote(healthy=False)
    d = FallbackDispatcher(
        remote=remote,  # type: ignore[arg-type]
        fallback_summarize=None,
        fallback_is_relevant=None,
        fallback_embed=None,
    )

    with pytest.raises(RemoteProcessorError):
        await d.summarize("text")


async def test_is_relevant_healthy_uses_remote() -> None:
    remote_rel = AsyncMock(return_value=_relevance(True))
    fb = AsyncMock(return_value=_relevance(False))
    remote = _remote(healthy=True, is_relevant=remote_rel)
    d = FallbackDispatcher(
        remote=remote,  # type: ignore[arg-type]
        fallback_summarize=None,
        fallback_is_relevant=fb,
        fallback_embed=None,
    )

    result = await d.is_relevant("post", "interest")

    assert result.relevant is True
    remote_rel.assert_awaited_once_with("post", "interest")
    fb.assert_not_awaited()


async def test_is_relevant_unhealthy_uses_fallback() -> None:
    remote_rel = AsyncMock(return_value=_relevance(True))
    fb = AsyncMock(return_value=_relevance(False))
    remote = _remote(healthy=False, is_relevant=remote_rel)
    d = FallbackDispatcher(
        remote=remote,  # type: ignore[arg-type]
        fallback_summarize=None,
        fallback_is_relevant=fb,
        fallback_embed=None,
    )

    result = await d.is_relevant("post", "interest")

    assert result.relevant is False
    remote_rel.assert_not_awaited()
    fb.assert_awaited_once_with("post", "interest")


async def test_is_relevant_remote_error_falls_back() -> None:
    remote_rel = AsyncMock(side_effect=RemoteProcessorError("oops"))
    fb = AsyncMock(return_value=_relevance(False))
    remote = _remote(healthy=True, is_relevant=remote_rel)
    d = FallbackDispatcher(
        remote=remote,  # type: ignore[arg-type]
        fallback_summarize=None,
        fallback_is_relevant=fb,
        fallback_embed=None,
    )

    result = await d.is_relevant("post", "interest")

    assert result.relevant is False
    fb.assert_awaited_once_with("post", "interest")


async def test_embed_healthy_uses_remote() -> None:
    remote_embed = AsyncMock(return_value=_embedding())
    fb = AsyncMock(return_value=Embedding(vector=[9.9], tokens=99, provider="openai", model="text-embedding-3-small"))
    remote = _remote(healthy=True, embed=remote_embed)
    d = FallbackDispatcher(
        remote=remote,  # type: ignore[arg-type]
        fallback_summarize=None,
        fallback_is_relevant=None,
        fallback_embed=fb,
    )

    result = await d.embed("text")

    assert result.vector == [0.1, 0.2]
    fb.assert_not_awaited()


async def test_embed_unhealthy_uses_fallback() -> None:
    remote_embed = AsyncMock(return_value=_embedding())
    fb = AsyncMock(return_value=Embedding(vector=[9.9], tokens=99, provider="openai", model="text-embedding-3-small"))
    remote = _remote(healthy=False, embed=remote_embed)
    d = FallbackDispatcher(
        remote=remote,  # type: ignore[arg-type]
        fallback_summarize=None,
        fallback_is_relevant=None,
        fallback_embed=fb,
    )

    result = await d.embed("text")

    assert result.vector == [9.9]
    remote_embed.assert_not_awaited()
    fb.assert_awaited_once_with("text")


async def test_embed_remote_timeout_falls_back() -> None:
    remote_embed = AsyncMock(side_effect=RemoteProcessorTimeout("timed out"))
    fb = AsyncMock(return_value=Embedding(vector=[9.9], tokens=99, provider="openai", model="text-embedding-3-small"))
    remote = _remote(healthy=True, embed=remote_embed)
    d = FallbackDispatcher(
        remote=remote,  # type: ignore[arg-type]
        fallback_summarize=None,
        fallback_is_relevant=None,
        fallback_embed=fb,
    )

    result = await d.embed("text")

    assert result.vector == [9.9]
