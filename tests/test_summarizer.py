from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from informer_bot.summarizer import summarize


def _fake_response(text: str) -> SimpleNamespace:
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)])


@pytest.fixture
def fake_client() -> AsyncMock:
    client = AsyncMock()
    client.messages.create = AsyncMock(return_value=_fake_response("A short brief."))
    return client


async def test_summarize_returns_text_from_response(fake_client: AsyncMock) -> None:
    result = await summarize("Some long post text", client=fake_client)

    assert result == "A short brief."


async def test_summarize_calls_haiku_with_system_prompt_and_user_text(
    fake_client: AsyncMock,
) -> None:
    await summarize("Post body here", client=fake_client)

    fake_client.messages.create.assert_awaited_once()
    kwargs = fake_client.messages.create.await_args.kwargs
    assert kwargs["model"] == "claude-haiku-4-5"
    assert isinstance(kwargs["max_tokens"], int) and kwargs["max_tokens"] > 0
    assert "1-2 sentence" in kwargs["system"].lower() or "1–2 sentence" in kwargs["system"].lower()
    assert "language of the post" in kwargs["system"].lower()
    assert kwargs["messages"] == [{"role": "user", "content": "Post body here"}]


async def test_summarize_strips_whitespace(fake_client: AsyncMock) -> None:
    fake_client.messages.create.return_value = _fake_response("  Brief with padding.\n\n")

    result = await summarize("anything", client=fake_client)

    assert result == "Brief with padding."
