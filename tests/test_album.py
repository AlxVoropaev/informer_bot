import asyncio
from unittest.mock import AsyncMock

import pytest

from informer_bot.album import AlbumBuffer

DELAY = 0.05


@pytest.fixture
def on_flush() -> AsyncMock:
    return AsyncMock()


async def test_non_grouped_message_flushes_immediately(on_flush: AsyncMock) -> None:
    buf = AlbumBuffer(on_flush=on_flush, delay=DELAY)

    await buf.add(
        channel_id=1, channel_username="ch", message_id=42,
        grouped_id=None, text="solo",
    )

    on_flush.assert_awaited_once_with(1, 42, "solo", "https://t.me/ch/42")


async def test_grouped_messages_coalesce_after_delay(on_flush: AsyncMock) -> None:
    buf = AlbumBuffer(on_flush=on_flush, delay=DELAY)

    await buf.add(channel_id=1, channel_username="ch", message_id=11,
                  grouped_id=999, text="caption")
    await buf.add(channel_id=1, channel_username="ch", message_id=12,
                  grouped_id=999, text="")
    await buf.add(channel_id=1, channel_username="ch", message_id=13,
                  grouped_id=999, text="")

    on_flush.assert_not_called()
    await asyncio.sleep(DELAY * 4)

    on_flush.assert_awaited_once_with(1, 11, "caption", "https://t.me/ch/11")


async def test_grouped_link_uses_lowest_message_id_regardless_of_arrival_order(
    on_flush: AsyncMock,
) -> None:
    buf = AlbumBuffer(on_flush=on_flush, delay=DELAY)

    await buf.add(channel_id=1, channel_username="ch", message_id=22,
                  grouped_id=7, text="late")
    await buf.add(channel_id=1, channel_username="ch", message_id=20,
                  grouped_id=7, text="early")

    await asyncio.sleep(DELAY * 4)

    on_flush.assert_awaited_once()
    args = on_flush.await_args.args
    assert args[0] == 1
    assert args[1] == 20
    assert args[3] == "https://t.me/ch/20"


async def test_multiple_captions_in_album_are_concatenated(on_flush: AsyncMock) -> None:
    buf = AlbumBuffer(on_flush=on_flush, delay=DELAY)

    await buf.add(channel_id=1, channel_username="ch", message_id=10,
                  grouped_id=5, text="first")
    await buf.add(channel_id=1, channel_username="ch", message_id=11,
                  grouped_id=5, text="second")

    await asyncio.sleep(DELAY * 4)

    on_flush.assert_awaited_once()
    text = on_flush.await_args.args[2]
    assert "first" in text and "second" in text
    assert text.index("first") < text.index("second")


async def test_two_independent_groups_flush_independently(on_flush: AsyncMock) -> None:
    buf = AlbumBuffer(on_flush=on_flush, delay=DELAY)

    await buf.add(channel_id=1, channel_username="a", message_id=1,
                  grouped_id=100, text="A")
    await buf.add(channel_id=2, channel_username="b", message_id=2,
                  grouped_id=200, text="B")

    await asyncio.sleep(DELAY * 4)

    assert on_flush.await_count == 2
    seen = {call.args[3] for call in on_flush.await_args_list}
    assert seen == {"https://t.me/a/1", "https://t.me/b/2"}
