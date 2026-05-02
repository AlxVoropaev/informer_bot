import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

OnFlush = Callable[[int, int, str, str], Awaitable[None]]


@dataclass(frozen=True)
class _Item:
    channel_id: int
    channel_username: str
    message_id: int
    text: str


class AlbumBuffer:
    """Coalesce Telegram album events. Non-grouped messages flush immediately;
    grouped messages are buffered and flushed after `delay` seconds of quiet."""

    def __init__(self, on_flush: OnFlush, delay: float = 1.5) -> None:
        self._on_flush = on_flush
        self._delay = delay
        self._groups: dict[int, list[_Item]] = {}
        self._tasks: dict[int, asyncio.Task] = {}

    async def add(
        self,
        *,
        channel_id: int,
        channel_username: str,
        message_id: int,
        grouped_id: int | None,
        text: str,
    ) -> None:
        if grouped_id is None:
            link = f"https://t.me/{channel_username}/{message_id}"
            await self._on_flush(channel_id, message_id, text, link)
            return

        self._groups.setdefault(grouped_id, []).append(
            _Item(channel_id, channel_username, message_id, text)
        )
        if (existing := self._tasks.get(grouped_id)) is not None:
            existing.cancel()
        self._tasks[grouped_id] = asyncio.create_task(self._flush_after(grouped_id))

    async def _flush_after(self, grouped_id: int) -> None:
        try:
            await asyncio.sleep(self._delay)
        except asyncio.CancelledError:
            return
        items = sorted(self._groups.pop(grouped_id, []), key=lambda i: i.message_id)
        self._tasks.pop(grouped_id, None)
        if not items:
            return
        first = items[0]
        text = "\n\n".join(i.text for i in items if i.text.strip()).strip()
        link = f"https://t.me/{first.channel_username}/{first.message_id}"
        await self._on_flush(first.channel_id, first.message_id, text, link)
