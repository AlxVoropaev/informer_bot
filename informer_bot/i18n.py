LANGUAGES = ("en", "ru")
DEFAULT_LANGUAGE = "en"
LANGUAGE_NAMES = {"en": "English", "ru": "Русский"}

_STRINGS: dict[str, dict[str, str]] = {
    "en": {
        "greeting": "Hi, I'm informer. Use /list to pick channels to follow. See /help for all commands.",
        "denied": "Not allowed.",
        "pending": "Your request has been sent to the administrator. Please wait.",
        "still_pending": "Still waiting for the administrator's approval.",
        "access_denied": "Sorry, you are not allowed to use this bot.",
        "approved_notice": "You are approved! Hi, I'm informer. Use /list to pick channels to follow. See /help for all commands.",
        "user_help": (
            "Commands:\n"
            "/start — request access / get started\n"
            "/list — pick channels to follow. Tap a channel title to cycle delivery mode: "
            "⬜ off → 🔀 filtered → 🐞 debug → ✅ all.\n"
            "/language — switch interface language\n"
            "/usage — your token usage and estimated cost\n"
            "/help — show this message\n\n"
            "Per-channel filters\n"
            "Each channel can have its own filter prompt (plain-language rules for what you want to see).\n"
            "  • ✏️ on a /list row — set or edit the filter (the bot asks for your prompt as the next message).\n"
            "  • 🗑 — delete the filter (kept hidden until you've set one).\n"
            "  • 🔀 filtered — only posts matching the filter are delivered. No filter set = same as ✅ all.\n"
            "  • 🐞 debug — every post is delivered, but ones the filter would have rejected are prefixed with 🐞 FILTERED so you can tune the prompt.\n"
            "Setting a filter from ⬜ off auto-switches the channel to 🔀 filtered.\n\n"
            "Need a channel added to the list? Message @alxvoropaev and I'll add it."
        ),
        "owner_help_extra": (
            "\n\nAdmin:\n"
            "/blacklist — toggle channel blacklist\n"
            "/update — refresh the channel list from your Telegram account"
        ),
        "pick_channels": "Pick channels:",
        "done_button": "Done",
        "selection_saved": "Channel selection saved.",
        "channel_unavailable": "Channel unavailable.",
        "admin_pick_blacklist": "Admin: tap to toggle blacklist.",
        "blacklist_closed": "Blacklist closed.",
        "refreshing": "Refreshing channel list...",
        "refresh_failed": "Refresh failed. Check logs.",
        "refresh_done": "Channel list refreshed.",
        "filter_tips": (
            "Tips for a good filter:\n"
            "• Write in plain language; bullets work well.\n"
            "• Split into what you want and what you don't (e.g. \"Interesting:\" / \"Not interesting:\").\n"
            "• Be concrete — name topics, domains, or keywords instead of vague labels.\n"
            "• Add exceptions when a broad rule has them (\"deaths/arrests, except in IT\").\n"
            "• Any language works; the filter doesn't have to match the post language."
        ),
        "filter_ask": "Send your filter prompt for '{title}' as your next message.\n\n{tips}",
        "filter_ask_with_current": (
            "Current filter for '{title}' (copy to edit):"
        ),
        "filter_saved_for": "Filter saved for '{title}':\n{filter}",
        "filter_deleted_for": "Filter for '{title}' deleted.",
        "filter_no_pending": "No pending filter request. Tap ✏️ next to a channel in /list first.",
        "filter_no_prompt_to_delete": "No filter set for this channel.",
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
        "channel_new": "📢 New channel available: {title}",
        "subscribe_filtered_button": "🔀 Filtered",
        "subscribe_debug_button": "🐞 Debug",
        "subscribe_all_button": "✅ All",
        "subscribed_toast": "Subscribed to '{title}' ({mode}).",
        "language_prompt": "Current language: {current}\nChoose:",
        "debug_filtered_marker": "🐞 FILTERED",
        "debug_duplicate_marker": "🔁 DUPLICATE",
        "dedup_disabled_notice": "⚠️ Deduplication disabled: OPENAI_API_KEY is not set.",
        "startup_notice": "🟢 Bot started.",
        "shutdown_notice": "🔴 Bot shutting down.",
        "channel_details_no_description": "<i>No description.</i>",
        "channel_details_open_button": "🔗 Open in Telegram",
        "channel_details_back_button": "⬅ Back to list",
        "channel_details_toggle_off": "⬜ Off — tap to subscribe",
        "channel_details_toggle_filtered": "🔀 Filtered — tap to cycle",
        "channel_details_toggle_debug": "🐞 Debug — tap to cycle",
        "channel_details_toggle_all": "✅ All — tap to cycle",
        "channel_details_edit_filter_button": "✏️ Edit filter",
        "channel_details_delete_filter_button": "🗑 Delete filter",
    },
    "ru": {
        "greeting": "Привет, я informer. Используй /list, чтобы выбрать каналы. /help — все команды.",
        "denied": "Нет доступа.",
        "pending": "Запрос отправлен администратору. Пожалуйста, подождите.",
        "still_pending": "Всё ещё жду одобрения администратора.",
        "access_denied": "Извини, тебе нельзя пользоваться этим ботом.",
        "approved_notice": "Доступ одобрен! Привет, я informer. Используй /list, чтобы выбрать каналы. /help — все команды.",
        "user_help": (
            "Команды:\n"
            "/start — запросить доступ / начать\n"
            "/list — выбрать каналы. Нажми на название канала, чтобы переключить режим доставки: "
            "⬜ выкл → 🔀 фильтр → 🐞 отладка → ✅ все.\n"
            "/language — сменить язык интерфейса\n"
            "/usage — расход токенов и примерная стоимость\n"
            "/help — показать это сообщение\n\n"
            "Фильтры для каналов\n"
            "У каждого канала может быть свой фильтр — обычным языком опиши, что тебе интересно.\n"
            "  • ✏️ в строке /list — задать или изменить фильтр (бот попросит прислать промпт следующим сообщением).\n"
            "  • 🗑 — удалить фильтр (показывается, только если он установлен).\n"
            "  • 🔀 фильтр — приходят только посты, прошедшие фильтр. Если фильтр не задан — то же, что ✅ все.\n"
            "  • 🐞 отладка — приходят все посты, но отфильтрованные помечаются префиксом 🐞 FILTERED — удобно, чтобы подкрутить промпт.\n"
            "Если задать фильтр в режиме ⬜ выкл, канал автоматически переключится в 🔀 фильтр.\n\n"
            "Если вам нужно добавить какой-то канал в список доступных — пишите @alxvoropaev, добавлю."
        ),
        "owner_help_extra": (
            "\n\nАдмин:\n"
            "/blacklist — переключить чёрный список каналов\n"
            "/update — обновить список каналов из твоего Telegram-аккаунта"
        ),
        "pick_channels": "Выбери каналы:",
        "done_button": "Готово",
        "selection_saved": "Выбор каналов сохранён.",
        "channel_unavailable": "Канал недоступен.",
        "admin_pick_blacklist": "Админ: нажми, чтобы переключить блокировку.",
        "blacklist_closed": "Чёрный список закрыт.",
        "refreshing": "Обновляю список каналов...",
        "refresh_failed": "Обновление не удалось. Смотри логи.",
        "refresh_done": "Список каналов обновлён.",
        "filter_tips": (
            "Советы по составлению фильтра:\n"
            "• Пиши обычным языком; списки работают хорошо.\n"
            "• Раздели на интересное и неинтересное (\"Интересно:\" / \"Не интересно:\").\n"
            "• Будь конкретным — называй темы, области, ключевые слова, а не общие ярлыки.\n"
            "• Добавляй исключения, если у широкого правила они есть (\"смерти/аресты, кроме IT\").\n"
            "• Можно писать на любом языке; язык фильтра не обязан совпадать с языком поста."
        ),
        "filter_ask": "Отправь следующим сообщением фильтр для '{title}'.\n\n{tips}",
        "filter_ask_with_current": (
            "Текущий фильтр для '{title}' (скопируй, чтобы изменить):"
        ),
        "filter_saved_for": "Фильтр для '{title}' сохранён:\n{filter}",
        "filter_deleted_for": "Фильтр для '{title}' удалён.",
        "filter_no_pending": "Нет ожидающего запроса фильтра. Сначала нажми ✏️ у канала в /list.",
        "filter_no_prompt_to_delete": "Для этого канала фильтр не задан.",
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
        "channel_new": "📢 Новый канал доступен: {title}",
        "subscribe_filtered_button": "🔀 Фильтр",
        "subscribe_debug_button": "🐞 Отладка",
        "subscribe_all_button": "✅ Все",
        "subscribed_toast": "Подписан на '{title}' ({mode}).",
        "language_prompt": "Текущий язык: {current}\nВыбери:",
        "debug_filtered_marker": "🐞 ОТФИЛЬТРОВАНО",
        "debug_duplicate_marker": "🔁 ДУБЛЬ",
        "dedup_disabled_notice": "⚠️ Дедупликация отключена: OPENAI_API_KEY не задан.",
        "startup_notice": "🟢 Бот запущен.",
        "shutdown_notice": "🔴 Бот выключается.",
        "channel_details_no_description": "<i>Описание отсутствует.</i>",
        "channel_details_open_button": "🔗 Открыть в Telegram",
        "channel_details_back_button": "⬅ К списку",
        "channel_details_toggle_off": "⬜ Выкл — нажми, чтобы подписаться",
        "channel_details_toggle_filtered": "🔀 Фильтр — нажми, чтобы переключить",
        "channel_details_toggle_debug": "🐞 Отладка — нажми, чтобы переключить",
        "channel_details_toggle_all": "✅ Все — нажми, чтобы переключить",
        "channel_details_edit_filter_button": "✏️ Редактировать фильтр",
        "channel_details_delete_filter_button": "🗑 Удалить фильтр",
    },
}


def t(lang: str, key: str, **fmt: object) -> str:
    table = _STRINGS.get(lang) or _STRINGS[DEFAULT_LANGUAGE]
    template = table.get(key) or _STRINGS[DEFAULT_LANGUAGE][key]
    return template.format(**fmt) if fmt else template
