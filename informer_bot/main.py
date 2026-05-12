import asyncio
import contextlib
import functools
import logging
import signal
import time
from typing import Any
from urllib.parse import quote

from openai import AsyncOpenAI
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, MenuButtonWebApp, WebAppInfo
from telegram.ext import (
    AIORateLimiter,
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
)
from telethon import TelegramClient

from informer_bot.album import AlbumBuffer
from informer_bot.bot import (
    BotState,
    build_dm_keyboard,
    cmd_app,
    cmd_become_provider,
    cmd_help,
    cmd_revoke_provider,
    cmd_start,
    cmd_update,
    cmd_usage,
    notify_owner_provider_request,
    on_approve,
    on_become_provider_self,
    on_deny,
    on_provider_approve,
    on_provider_deny,
    on_save,
)
from informer_bot.client import (
    catch_up,
    fetch_subscribed_channels,
)
from informer_bot.config import Config, load_config
from informer_bot.db import Database
from informer_bot.fallback_dispatcher import FallbackDispatcher
from informer_bot.i18n import t
from informer_bot.pipeline import (
    AnnounceNewChannelFn,
    EditDmFn,
    EmbedFn,
    FetchChannelsForFn,
    IsRelevantFn,
    SendDmFn,
    SummarizeFn,
    handle_new_post,
)
from informer_bot.provider_clients import ProviderClient, start_all, stop_all
from informer_bot.remote_processor import RemoteProcessorClient
from informer_bot.summarizer import (
    EMBED_DIMENSIONS,
    EMBED_MODEL,
    Summary,
    embed_summary,
    is_relevant,
    is_relevant_ollama,
    summarize,
    summarize_ollama,
)
from informer_bot.webapp import start_server as start_webapp_server

log = logging.getLogger(__name__)


def setup_embedder(
    cfg: Config, db: Database, ollama_client: AsyncOpenAI | None = None,
) -> tuple[EmbedFn | None, str | None]:
    """Pick an embedding provider, return (embed_fn, embedding_id).

    embed_fn is None when dedup is disabled. embedding_id is a stable string
    used to detect provider/model switches across restarts.
    """
    embed_fn: EmbedFn | None = None
    embedding_id: str | None = None
    provider = cfg.embedding_provider
    if provider == "auto":
        provider = "openai" if cfg.openai_api_key else "none"

    if provider == "openai":
        if not cfg.openai_api_key:
            raise SystemExit("EMBEDDING_PROVIDER=openai but OPENAI_API_KEY is missing")
        openai_client = AsyncOpenAI(api_key=cfg.openai_api_key)
        embed_fn = functools.partial(
            embed_summary, client=openai_client, provider="openai",
        )
        embedding_id = f"openai:{EMBED_MODEL}:{EMBED_DIMENSIONS}"
        log.info("embedding provider: openai (%s, %d dims)", EMBED_MODEL, EMBED_DIMENSIONS)
    elif provider == "ollama":
        client = ollama_client or AsyncOpenAI(
            base_url=cfg.ollama_base_url, api_key="ollama",
        )
        embed_fn = functools.partial(
            embed_summary,
            client=client,
            provider="ollama",
            model=cfg.ollama_embedding_model,
            dimensions=None,
        )
        embedding_id = f"ollama:{cfg.ollama_embedding_model}"
        log.info(
            "embedding provider: ollama (%s @ %s)",
            cfg.ollama_embedding_model, cfg.ollama_base_url,
        )
    else:
        log.warning("embedding provider: none — deduplication disabled")

    if embed_fn is not None and embedding_id is not None:
        prev = db.get_meta("embedding_id")
        if prev is not None and prev != embedding_id:
            log.warning(
                "embedding model changed (%s -> %s); dropping dedup index",
                prev, embedding_id,
            )
            db.purge_dedup_all()
        db.set_meta("embedding_id", embedding_id)
        db.purge_dedup_older_than(
            cutoff=int(time.time()) - cfg.dedup_window_hours * 3600
        )

    return embed_fn, embedding_id


def _build_anthropic_chat_fns(cfg: Config) -> tuple[SummarizeFn, IsRelevantFn]:
    del cfg  # AsyncAnthropic picks up ANTHROPIC_API_KEY from env automatically.
    return summarize, is_relevant


def _build_ollama_chat_fns(
    cfg: Config, ollama_client: AsyncOpenAI
) -> tuple[SummarizeFn, IsRelevantFn]:
    summarize_fn = functools.partial(
        summarize_ollama, client=ollama_client, model=cfg.ollama_chat_model,
    )
    is_relevant_fn = functools.partial(
        is_relevant_ollama, client=ollama_client, model=cfg.ollama_chat_model,
    )
    return summarize_fn, is_relevant_fn


def _build_openai_embed_fn(cfg: Config) -> EmbedFn:
    if not cfg.openai_api_key:
        raise SystemExit("OPENAI_API_KEY missing for embedding fallback")
    openai_client = AsyncOpenAI(api_key=cfg.openai_api_key)
    return functools.partial(embed_summary, client=openai_client, provider="openai")


def _build_ollama_embed_fn(cfg: Config, ollama_client: AsyncOpenAI) -> EmbedFn:
    return functools.partial(
        embed_summary,
        client=ollama_client,
        provider="ollama",
        model=cfg.ollama_embedding_model,
        dimensions=None,
    )


def _wrap_summarize_with_custom_prompt(
    summarize_fn: SummarizeFn, db: Database
) -> SummarizeFn:
    async def wrapped(text: str, *, system_prompt: str | None = None) -> Summary:
        custom = db.get_meta("summary_prompt")
        return await summarize_fn(text, system_prompt=custom or None)
    return wrapped


def _wrap_embed_with_remote_model_check(embed_fn: EmbedFn, db: Database) -> EmbedFn:
    # Remote replies carry the embedding model the processor used. Reset the
    # dedup index when that model (or the active provider, on fallback) changes
    # — vectors aren't comparable across embedding spaces.
    async def wrapped(text: str):
        emb = await embed_fn(text)
        new_id = f"{emb.provider}:{emb.model}:{EMBED_DIMENSIONS}"
        prev = db.get_meta("embedding_id")
        if prev != new_id:
            if prev is not None:
                log.warning(
                    "embedding model changed (%s -> %s); dropping dedup index",
                    prev, new_id,
                )
                db.purge_dedup_all()
            db.set_meta("embedding_id", new_id)
        return emb
    return wrapped


def _make_send_dm(app: Application) -> SendDmFn:
    async def send_dm(
        user_id: int,
        text: str,
        photo: bytes | None = None,
        save_button: str | None = None,
    ) -> int | None:
        keyboard = build_dm_keyboard([], save_button)
        try:
            if photo is not None:
                msg = await app.bot.send_photo(
                    chat_id=user_id, photo=photo, caption=text,
                    parse_mode="HTML", reply_markup=keyboard,
                )
                log.info(
                    "outgoing: DM (photo) user=%s msg=%s cap_chars=%d",
                    user_id, msg.message_id, len(text),
                )
            else:
                msg = await app.bot.send_message(
                    chat_id=user_id, text=text, parse_mode="HTML",
                    reply_markup=keyboard,
                )
                log.info(
                    "outgoing: DM user=%s msg=%s chars=%d",
                    user_id, msg.message_id, len(text),
                )
            return msg.message_id
        except Exception:
            log.exception("send_dm to %s failed", user_id)
            return None

    return send_dm


def _make_edit_dm(app: Application) -> EditDmFn:
    async def edit_dm(
        user_id: int,
        bot_message_id: int,
        dup_links: list[tuple[str, str]],
        save_button: str | None = None,
    ) -> None:
        keyboard = build_dm_keyboard(dup_links, save_button)
        try:
            await app.bot.edit_message_reply_markup(
                chat_id=user_id, message_id=bot_message_id, reply_markup=keyboard,
            )
            log.info(
                "outgoing: DM buttons updated user=%s msg=%s links=%d save=%s",
                user_id, bot_message_id, len(dup_links), save_button is not None,
            )
        except Exception:
            log.exception(
                "edit_dm failed for user=%s msg=%s", user_id, bot_message_id
            )

    return edit_dm


async def _notify_owner_health(
    app: Application, owner_id: int, healthy: bool
) -> None:
    text = (
        "✅ Processor recovered, back on local models."
        if healthy
        else "⚠️ Processor unreachable, fail-safe enabled (Claude/OpenAI)."
    )
    try:
        await app.bot.send_message(chat_id=owner_id, text=text)
    except Exception:
        log.exception("notify_owner_health failed (healthy=%s)", healthy)


async def sweep_due_deletions(app: Application, db: Database) -> None:
    """Background task: every 60s, delete DM messages whose timer has expired."""
    while True:
        try:
            now = int(time.time())
            due = db.list_due_deletions(now=now)
            for user_id, channel_id, message_id, bot_msg_id, _is_photo in due:
                try:
                    await app.bot.delete_message(
                        chat_id=user_id, message_id=bot_msg_id,
                    )
                    log.info(
                        "auto-delete: removed user=%s msg=%s", user_id, bot_msg_id,
                    )
                except Exception as exc:
                    log.warning(
                        "auto-delete: telegram delete failed user=%s msg=%s: %s",
                        user_id, bot_msg_id, exc,
                    )
                    continue
                db.delete_delivered_row(
                    user_id=user_id, channel_id=channel_id, message_id=message_id,
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("auto-delete sweeper iteration failed")
        await asyncio.sleep(60)


def _make_announce_new_channel(
    app: Application, db: Database, miniapp_url: str | None
) -> AnnounceNewChannelFn:
    async def announce_new_channel(
        user_id: int, channel_id: int, channel_title: str
    ) -> None:
        lang = db.get_language(user_id)
        keyboard = None
        if miniapp_url:
            sep = "&" if "?" in miniapp_url else "?"
            url = f"{miniapp_url}{sep}channel={quote(str(channel_id))}"
            keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(
                text=t(lang, "channel_new_open_button"),
                web_app=WebAppInfo(url=url),
            )]])
        try:
            await app.bot.send_message(
                chat_id=user_id,
                text=t(lang, "channel_new", title=channel_title),
                reply_markup=keyboard,
            )
            log.info(
                "outgoing: new-channel announce user=%s channel=%s",
                user_id, channel_id,
            )
        except Exception:
            log.exception(
                "announce_new_channel to user=%s channel=%s failed",
                user_id, channel_id,
            )

    return announce_new_channel


async def main() -> None:
    cfg = load_config()
    logging.getLogger().setLevel(cfg.log_level)
    log.info("starting informer_bot (log_level=%s, db=%s)", cfg.log_level, cfg.db_path)
    db = Database(cfg.db_path)
    db.set_user_status(user_id=cfg.owner_id, status="approved")

    miniapp_url = cfg.miniapp_url

    app = ApplicationBuilder().token(cfg.telegram_bot_token).rate_limiter(AIORateLimiter()).build()
    for handler in (
        CommandHandler("start", cmd_start),
        CommandHandler("help", cmd_help),
        CommandHandler("app", cmd_app),
        CommandHandler("usage", cmd_usage),
        CommandHandler("update", cmd_update),
        CallbackQueryHandler(on_approve, pattern=r"^approve:"),
        CallbackQueryHandler(on_deny, pattern=r"^deny:"),
        CallbackQueryHandler(on_save, pattern=r"^save$"),
        CommandHandler("become_provider", cmd_become_provider),
        CommandHandler("revoke_provider", cmd_revoke_provider),
        CallbackQueryHandler(on_provider_approve, pattern=r"^provider_approve:"),
        CallbackQueryHandler(on_provider_deny, pattern=r"^provider_deny:"),
        CallbackQueryHandler(on_become_provider_self, pattern=r"^provider_self$"),
    ):
        app.add_handler(handler)

    remote: RemoteProcessorClient | None = None
    if cfg.chat_provider == "remote" or cfg.embedding_provider == "remote":
        assert cfg.bus_group_id is not None
        assert cfg.processor_bot_user_id is not None
        remote = RemoteProcessorClient(
            application=app,
            bus_group_id=cfg.bus_group_id,
            processor_bot_user_id=cfg.processor_bot_user_id,
            timeout_seconds=cfg.processor_timeout_seconds,
        )
        remote.start()
        log.info(
            "remote processor: bus=%s peer=%s timeout=%.1fs",
            cfg.bus_group_id, cfg.processor_bot_user_id, cfg.processor_timeout_seconds,
        )

    ollama_client: AsyncOpenAI | None = None
    summarize_fn: SummarizeFn
    is_relevant_fn: IsRelevantFn
    if cfg.chat_provider == "ollama":
        ollama_client = AsyncOpenAI(base_url=cfg.ollama_base_url, api_key="ollama")
        summarize_fn, is_relevant_fn = _build_ollama_chat_fns(cfg, ollama_client)
        log.info(
            "chat provider: ollama (%s @ %s)",
            cfg.ollama_chat_model, cfg.ollama_base_url,
        )
    elif cfg.chat_provider == "remote":
        assert remote is not None
        if cfg.chat_provider_fallback == "ollama":
            if ollama_client is None:
                ollama_client = AsyncOpenAI(
                    base_url=cfg.ollama_base_url, api_key="ollama",
                )
            fb_sum, fb_rel = _build_ollama_chat_fns(cfg, ollama_client)
        else:
            fb_sum, fb_rel = _build_anthropic_chat_fns(cfg)
        log.info(
            "chat provider: remote (fallback=%s)", cfg.chat_provider_fallback,
        )
    else:
        summarize_fn, is_relevant_fn = _build_anthropic_chat_fns(cfg)

    embed_fn: EmbedFn | None
    fb_embed: EmbedFn | None = None
    if cfg.embedding_provider == "remote":
        assert remote is not None
        if cfg.embedding_provider_fallback == "openai":
            fb_embed = _build_openai_embed_fn(cfg)
        elif cfg.embedding_provider_fallback == "ollama":
            if ollama_client is None:
                ollama_client = AsyncOpenAI(
                    base_url=cfg.ollama_base_url, api_key="ollama",
                )
            fb_embed = _build_ollama_embed_fn(cfg, ollama_client)
        embed_fn = remote.embed
        db.purge_dedup_older_than(
            cutoff=int(time.time()) - cfg.dedup_window_hours * 3600
        )
        log.info(
            "embedding provider: remote (fallback=%s)",
            cfg.embedding_provider_fallback,
        )
    else:
        embed_fn, embedding_id = setup_embedder(cfg, db, ollama_client=ollama_client)

    if remote is not None:
        dispatcher = FallbackDispatcher(
            remote=remote,
            fallback_summarize=fb_sum if cfg.chat_provider == "remote" else None,
            fallback_is_relevant=fb_rel if cfg.chat_provider == "remote" else None,
            fallback_embed=fb_embed if cfg.embedding_provider == "remote" else None,
        )
        if cfg.chat_provider == "remote":
            summarize_fn = dispatcher.summarize
            is_relevant_fn = dispatcher.is_relevant
        if cfg.embedding_provider == "remote":
            embed_fn = _wrap_embed_with_remote_model_check(dispatcher.embed, db)
    summarize_fn = _wrap_summarize_with_custom_prompt(summarize_fn, db)
    send_dm = _make_send_dm(app)
    edit_dm: EditDmFn | None = _make_edit_dm(app) if embed_fn is not None else None
    announce_new_channel = _make_announce_new_channel(app, db, miniapp_url)

    async def on_post(
        channel_id: int, message_id: int, text: str, link: str, photo: bytes | None,
    ) -> None:
        await handle_new_post(
            channel_id=channel_id, message_id=message_id, text=text, link=link,
            db=db, summarize_fn=summarize_fn, is_relevant_fn=is_relevant_fn,
            send_dm=send_dm,
            embed_fn=embed_fn, edit_dm=edit_dm,
            dedup_threshold=cfg.dedup_threshold,
            dedup_window_seconds=cfg.dedup_window_hours * 3600,
            miniapp_tg_deeplink=cfg.miniapp_tg_deeplink,
            photo=photo,
        )

    buffer = AlbumBuffer(on_flush=on_post, delay=1.5)

    inflight: set[tuple[int, int]] = set()
    provider_clients: list[ProviderClient] = await start_all(
        db=db,
        api_id=cfg.telegram_api_id,
        api_hash=cfg.telegram_api_hash,
        buffer=buffer,
        inflight=inflight,
    )
    if not provider_clients:
        log.warning(
            "no usable Telethon sessions found — running in degraded mode "
            "(Mini App + PTB only, no Telethon updates); log in via the "
            "Mini App or run `uv run python login.py`",
        )
    else:
        log.info("started %d telethon provider client(s)", len(provider_clients))

    def _client_for(provider_id: int) -> TelegramClient:
        for pc in provider_clients:
            if pc.user_id == provider_id:
                return pc.tg
        raise KeyError(f"no live client for provider={provider_id}")

    async def fetch_for(
        provider_id: int,
    ) -> list[tuple[int, str, str, str | None]]:
        return await fetch_subscribed_channels(_client_for(provider_id))

    fetch_channels_for: FetchChannelsForFn = fetch_for
    app.bot_data["state"] = BotState(
        db=db,
        owner_id=cfg.owner_id,
        miniapp_url=miniapp_url,
        fetch_channels_for=fetch_channels_for,
        provider_user_ids=[pc.user_id for pc in provider_clients],
        send_dm=send_dm,
        announce_new_channel=announce_new_channel,
    )

    await app.initialize()
    await app.start()
    assert app.updater is not None
    await app.updater.start_polling()

    webapp_runner = None
    if miniapp_url:
        async def _notify_owner_provider_request(requester_id: int) -> None:
            await notify_owner_provider_request(
                app.bot, db, requester_id=requester_id, owner_id=cfg.owner_id,
            )

        async def _stop_provider_client(user_id: int) -> bool:
            for pc in list(provider_clients):
                if pc.user_id == user_id:
                    try:
                        await pc.tg.disconnect()
                    except Exception:
                        log.exception(
                            "provider_logout: disconnect user=%s failed", user_id,
                        )
                    provider_clients.remove(pc)
                    return True
            return False

        webapp_runner = await start_webapp_server(
            db=db, bot_token=cfg.telegram_bot_token, owner_id=cfg.owner_id,
            api_id=cfg.telegram_api_id, api_hash=cfg.telegram_api_hash,
            host=cfg.webapp_host, port=cfg.webapp_port,
            notify_owner_provider_request=_notify_owner_provider_request,
            send_dm=send_dm,
            stop_provider_client=_stop_provider_client,
        )
        try:
            await app.bot.set_chat_menu_button(menu_button=MenuButtonWebApp(
                text=t(db.get_language(cfg.owner_id), "miniapp_menu_label"),
                web_app=WebAppInfo(url=miniapp_url),
            ))
            log.info("set chat menu button -> %s", miniapp_url)
        except Exception:
            log.exception("failed to set chat menu button")
    else:
        log.warning(
            "MINIAPP_URL is not set: Mini App is disabled and the webapp on "
            "port %d will not start. The container will be reported as "
            "'unhealthy' (the compose healthcheck probes that port), but the "
            "bot itself works fine. To enable the Mini App, set MINIAPP_URL "
            "in data/.env (see docs/internals/miniapp.md).",
            cfg.webapp_port,
        )

    for pc in provider_clients:
        await catch_up(
            pc.tg, db, buffer,
            max_age_seconds=cfg.catch_up_window_hours * 3600,
        )

    for user_id in db.list_user_ids():
        try:
            chat = await app.bot.get_chat(chat_id=user_id)
        except Exception:
            log.debug("name refresh failed for user=%s", user_id)
            continue
        db.update_user_name(
            user_id=user_id, username=chat.username, first_name=chat.first_name
        )
        # Throttle to ~20 RPS — well under Telegram's flood-wait threshold.
        await asyncio.sleep(0.05)

    if embed_fn is None:
        await send_dm(
            cfg.owner_id,
            t(db.get_language(cfg.owner_id), "dedup_disabled_notice"),
        )

    await send_dm(cfg.owner_id, t(db.get_language(cfg.owner_id), "startup_notice"))

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, stop_event.set)

    log.info("informer_bot is running. Ctrl+C to stop.")
    disconnect_tasks = [
        asyncio.create_task(pc.tg.run_until_disconnected())
        for pc in provider_clients
    ]
    stop_task = asyncio.create_task(stop_event.wait())
    sweeper_task = asyncio.create_task(sweep_due_deletions(app, db))
    background_tasks: list[asyncio.Task[Any]] = [
        *disconnect_tasks, stop_task, sweeper_task,
    ]
    if remote is not None:
        remote.set_state_change_callback(
            lambda healthy: _notify_owner_health(app, cfg.owner_id, healthy)
        )
        health_task = asyncio.create_task(
            remote.run_health_check_loop(
                cfg.health_check_interval_seconds, stop_event,
            )
        )
        background_tasks.append(health_task)
    try:
        await asyncio.wait(
            {*disconnect_tasks, stop_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
    finally:
        await graceful_shutdown(
            app=app, provider_clients=provider_clients, db=db, cfg=cfg,
            send_dm=send_dm,
            tasks=tuple(background_tasks),
            webapp_runner=webapp_runner,
        )


async def graceful_shutdown(
    *,
    app: Application,
    provider_clients: list[ProviderClient],
    db: Database,
    cfg: Config,
    send_dm: SendDmFn,
    tasks: tuple[asyncio.Task, ...],
    webapp_runner,
) -> None:
    log.info("shutting down")
    with contextlib.suppress(Exception):
        await send_dm(
            cfg.owner_id, t(db.get_language(cfg.owner_id), "shutdown_notice")
        )
    for task in tasks:
        task.cancel()
    for task in tasks:
        with contextlib.suppress(asyncio.CancelledError):
            await task
    assert app.updater is not None
    await app.updater.stop()
    await app.stop()
    await app.shutdown()
    if webapp_runner is not None:
        await webapp_runner.cleanup()
    await stop_all(provider_clients)
    log.info("shutdown complete")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    asyncio.run(main())
