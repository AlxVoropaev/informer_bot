LANGUAGES = ("en", "ru")
DEFAULT_LANGUAGE = "en"
LANGUAGE_NAMES = {"en": "English", "ru": "Русский"}

_STRINGS: dict[str, dict[str, str]] = {
    "en": {
        "greeting": "Hi, I'm informer. Open the Mini App to pick channels — tap the burger menu or run /app. See /help for all commands.",
        "denied": "Not allowed.",
        "pending": "Your request has been sent to the administrator. Please wait.",
        "still_pending": "Still waiting for the administrator's approval.",
        "access_denied": "Sorry, you are not allowed to use this bot.",
        "approved_notice": "You are approved! Open the Mini App to pick channels — tap the burger menu or run /app. See /help for all commands.",
        "user_help": (
            "Open the Mini App (burger menu or /app) to pick channels, set per-channel filters, switch language, and view usage. "
            "All client apps support Mini Apps — please use it for everything below.\n\n"
            "Commands:\n"
            "/start — request access / get started\n"
            "/app — open the Mini App\n"
            "/usage — your token usage and estimated cost\n"
            "/help — show this message\n\n"
            "In the Mini App\n"
            "  • Tap a channel to pick its delivery mode: ⬜ Off → 🔀 Filtered → 🐞 Debug → ✅ All.\n"
            "  • Set a per-channel filter (plain language) to keep only matching posts. 🐞 Debug delivers everything but tags filtered posts so you can tune the prompt.\n"
            "  • Change interface language and view usage from the top bar.\n\n"
            "Need a channel added? Message @alxvoropaev."
        ),
        "owner_help_extra": (
            "\n\nAdmin:\n"
            "/blacklist — toggle channel blacklist\n"
            "/update — refresh the channel list from your Telegram account"
        ),
        "done_button": "Done",
        "channel_unavailable": "Channel unavailable.",
        "admin_pick_blacklist": "Admin: tap to toggle blacklist.",
        "blacklist_closed": "Blacklist closed.",
        "refreshing": "Refreshing channel list...",
        "refresh_failed": "Refresh failed. Check logs.",
        "refresh_done": "Channel list refreshed.",
        "usage_admin_header": "Usage by user (delivered):",
        "usage_admin_none": "(none yet)",
        "usage_admin_system_label": "System total (actual API spend)",
        "usage_admin_embedding_label": "Embeddings (OpenAI)",
        "usage_admin_embedding_line": "{label}: tokens={tokens:,} ≈ ${cost:.4f}",
        "usage_user_block": "Your usage:\nInput tokens: {inp:,}\nOutput tokens: {out:,}\nEstimated cost: ${cost:.4f}",
        "access_request": "Access request from {label}",
        "approve_button": "✅ Allow",
        "deny_button": "⛔ Deny",
        "user_allowed": "Allowed user {target}.",
        "user_denied_msg": "Denied user {target}.",
        "channel_blocked": "Admin blocked channel '{title}', you will not get updates anymore.",
        "channel_gone": "Channel '{title}' is no longer available.",
        "channel_new": "📢 New channel available: {title}\nOpen the Mini App to subscribe.",
        "channel_new_open_button": "🪟 Open in Mini App",
        "debug_filtered_marker": "🐞 FILTERED",
        "debug_duplicate_marker": "🔁 DUPLICATE",
        "dedup_disabled_notice": "⚠️ Deduplication disabled: OPENAI_API_KEY is not set.",
        "startup_notice": "🟢 Bot started.",
        "shutdown_notice": "🔴 Bot shutting down.",
        "open_miniapp_button": "🪟 Open Mini App",
        "miniapp_intro": "Open the channel manager:",
        "miniapp_unconfigured": "Mini App is not configured (MINIAPP_URL is unset).",
        "miniapp_menu_label": "Channels",
        "save_button": "💾 Save",
        "saved_button": "✅ Saved",
    },
    "ru": {
        "greeting": "Привет, я informer. Открой Mini App, чтобы выбрать каналы — через бургер-меню или команду /app. /help — все команды.",
        "denied": "Нет доступа.",
        "pending": "Запрос отправлен администратору. Пожалуйста, подождите.",
        "still_pending": "Всё ещё жду одобрения администратора.",
        "access_denied": "Извини, тебе нельзя пользоваться этим ботом.",
        "approved_notice": "Доступ одобрен! Открой Mini App, чтобы выбрать каналы — через бургер-меню или команду /app. /help — все команды.",
        "user_help": (
            "Открой Mini App (бургер-меню или /app), чтобы выбирать каналы, задавать фильтры, менять язык и смотреть расход. "
            "Mini App поддерживается во всех клиентах Telegram — используй его для всего ниже.\n\n"
            "Команды:\n"
            "/start — запросить доступ / начать\n"
            "/app — открыть Mini App\n"
            "/usage — расход токенов и примерная стоимость\n"
            "/help — показать это сообщение\n\n"
            "В Mini App\n"
            "  • Нажми на канал, чтобы выбрать режим доставки: ⬜ Выкл → 🔀 Фильтр → 🐞 Отладка → ✅ Все.\n"
            "  • Задай фильтр для канала (обычным языком) — придут только подходящие посты. 🐞 Отладка присылает все посты и помечает отфильтрованные, чтобы ты мог подкрутить промпт.\n"
            "  • Смени язык и посмотри расход в верхней панели.\n\n"
            "Нужен новый канал? Пиши @alxvoropaev."
        ),
        "owner_help_extra": (
            "\n\nАдмин:\n"
            "/blacklist — переключить чёрный список каналов\n"
            "/update — обновить список каналов из твоего Telegram-аккаунта"
        ),
        "done_button": "Готово",
        "channel_unavailable": "Канал недоступен.",
        "admin_pick_blacklist": "Админ: нажми, чтобы переключить блокировку.",
        "blacklist_closed": "Чёрный список закрыт.",
        "refreshing": "Обновляю список каналов...",
        "refresh_failed": "Обновление не удалось. Смотри логи.",
        "refresh_done": "Список каналов обновлён.",
        "usage_admin_header": "Расход по пользователям (доставлено):",
        "usage_admin_none": "(пока пусто)",
        "usage_admin_system_label": "Системный итог (фактический расход API)",
        "usage_admin_embedding_label": "Эмбеддинги (OpenAI)",
        "usage_admin_embedding_line": "{label}: токены={tokens:,} ≈ ${cost:.4f}",
        "usage_user_block": "Твой расход:\nВходные токены: {inp:,}\nВыходные токены: {out:,}\nПримерная стоимость: ${cost:.4f}",
        "access_request": "Запрос доступа от {label}",
        "approve_button": "✅ Разрешить",
        "deny_button": "⛔ Отклонить",
        "user_allowed": "Пользователь {target} разрешён.",
        "user_denied_msg": "Пользователь {target} отклонён.",
        "channel_blocked": "Админ заблокировал канал '{title}', ты больше не будешь получать обновления.",
        "channel_gone": "Канал '{title}' больше недоступен.",
        "channel_new": "📢 Новый канал доступен: {title}\nОткрой Mini App, чтобы подписаться.",
        "channel_new_open_button": "🪟 Открыть в Mini App",
        "debug_filtered_marker": "🐞 ОТФИЛЬТРОВАНО",
        "debug_duplicate_marker": "🔁 ДУБЛЬ",
        "dedup_disabled_notice": "⚠️ Дедупликация отключена: OPENAI_API_KEY не задан.",
        "startup_notice": "🟢 Бот запущен.",
        "shutdown_notice": "🔴 Бот выключается.",
        "open_miniapp_button": "🪟 Открыть Mini App",
        "miniapp_intro": "Открой менеджер каналов:",
        "miniapp_unconfigured": "Mini App не настроен (MINIAPP_URL не задан).",
        "miniapp_menu_label": "Каналы",
        "save_button": "💾 Сохранить",
        "saved_button": "✅ Сохранено",
    },
}


def t(lang: str, key: str, **fmt: object) -> str:
    table = _STRINGS.get(lang) or _STRINGS[DEFAULT_LANGUAGE]
    template = table.get(key) or _STRINGS[DEFAULT_LANGUAGE][key]
    return template.format(**fmt) if fmt else template
