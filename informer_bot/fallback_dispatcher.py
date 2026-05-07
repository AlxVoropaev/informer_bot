import logging
from collections.abc import Awaitable, Callable

from informer_bot.remote_processor import (
    RemoteProcessorClient,
    RemoteProcessorError,
    RemoteProcessorTimeout,
)
from informer_bot.summarizer import Embedding, RelevanceCheck, Summary

log = logging.getLogger(__name__)


class FallbackDispatcher:
    """Routes calls to the remote client when healthy, else to fallback fns."""

    def __init__(
        self,
        *,
        remote: RemoteProcessorClient,
        fallback_summarize: Callable[[str], Awaitable[Summary]] | None,
        fallback_is_relevant: (
            Callable[[str, str], Awaitable[RelevanceCheck]] | None
        ),
        fallback_embed: Callable[[str], Awaitable[Embedding]] | None,
    ) -> None:
        self._remote = remote
        self._fallback_summarize = fallback_summarize
        self._fallback_is_relevant = fallback_is_relevant
        self._fallback_embed = fallback_embed

    async def summarize(self, text: str) -> Summary:
        if self._remote.healthy:
            try:
                return await self._remote.summarize(text)
            except (RemoteProcessorTimeout, RemoteProcessorError) as exc:
                if self._fallback_summarize is None:
                    raise
                log.warning("fallback summarize: %s", exc)
                return await self._fallback_summarize(text)
        if self._fallback_summarize is None:
            raise RemoteProcessorError(
                "remote unhealthy and no summarize fallback configured"
            )
        return await self._fallback_summarize(text)

    async def is_relevant(self, text: str, filter_prompt: str) -> RelevanceCheck:
        if self._remote.healthy:
            try:
                return await self._remote.is_relevant(text, filter_prompt)
            except (RemoteProcessorTimeout, RemoteProcessorError) as exc:
                if self._fallback_is_relevant is None:
                    raise
                log.warning("fallback is_relevant: %s", exc)
                return await self._fallback_is_relevant(text, filter_prompt)
        if self._fallback_is_relevant is None:
            raise RemoteProcessorError(
                "remote unhealthy and no is_relevant fallback configured"
            )
        return await self._fallback_is_relevant(text, filter_prompt)

    async def embed(self, text: str) -> Embedding:
        if self._remote.healthy:
            try:
                return await self._remote.embed(text)
            except (RemoteProcessorTimeout, RemoteProcessorError) as exc:
                if self._fallback_embed is None:
                    raise
                log.warning("fallback embed: %s", exc)
                return await self._fallback_embed(text)
        if self._fallback_embed is None:
            raise RemoteProcessorError(
                "remote unhealthy and no embed fallback configured"
            )
        return await self._fallback_embed(text)
