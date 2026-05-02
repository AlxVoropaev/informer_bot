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
            "/list — pick channels to follow (tap to cycle: ⬜ off → 🔀 filtered → ✅ all)\n"
            "/filter — set a personal content filter (used in 🔀 mode); /filter alone shows it, /filter clear removes it\n"
            "/language — switch interface language\n"
            "/usage — your token usage and estimated cost\n"
            "/help — show this message"
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
        "filter_help": (
            "Send /filter <text> to set what you want to read. "
            "Send /filter clear to remove your filter (deliver everything). "
            "Send /filter alone to see your current filter."
        ),
        "filter_current": "Your filter:\n{filter}\n\n{help}",
        "filter_none": "No filter set — you receive everything.\n\n{help}",
        "filter_cleared": "Filter cleared. You will receive everything.",
        "filter_saved": "Filter saved:\n{filter}",
        "usage_admin_header": "Usage by user (delivered):",
        "usage_admin_none": "(none yet)",
        "usage_admin_system_label": "System total (actual API spend)",
        "usage_user_block": "Your usage:\nInput tokens: {inp:,}\nOutput tokens: {out:,}\nEstimated cost: ${cost:.4f}",
        "access_request": "Access request from {label}",
        "approve_button": "✅ Allow",
        "deny_button": "⛔ Deny",
        "user_allowed": "Allowed user {target}.",
        "user_denied_msg": "Denied user {target}.",
        "channel_blocked": "Admin blocked channel '{title}', you will not get updates anymore.",
        "channel_gone": "Channel '{title}' is no longer available.",
        "language_prompt": "Current language: {current}\nChoose:",
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
            "/list — выбрать каналы (нажми, чтобы переключить: ⬜ выкл → 🔀 фильтр → ✅ все)\n"
            "/filter — личный фильтр контента (для режима 🔀); /filter без аргументов покажет его, /filter clear удалит\n"
            "/language — сменить язык интерфейса\n"
            "/usage — расход токенов и примерная стоимость\n"
            "/help — показать это сообщение"
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
        "filter_help": (
            "Отправь /filter <текст>, чтобы задать, что ты хочешь читать. "
            "Отправь /filter clear, чтобы убрать фильтр (получать всё). "
            "Отправь /filter без аргументов, чтобы увидеть текущий фильтр."
        ),
        "filter_current": "Твой фильтр:\n{filter}\n\n{help}",
        "filter_none": "Фильтр не задан — получаешь всё.\n\n{help}",
        "filter_cleared": "Фильтр очищен. Будешь получать всё.",
        "filter_saved": "Фильтр сохранён:\n{filter}",
        "usage_admin_header": "Расход по пользователям (доставлено):",
        "usage_admin_none": "(пока пусто)",
        "usage_admin_system_label": "Системный итог (фактический расход API)",
        "usage_user_block": "Твой расход:\nВходные токены: {inp:,}\nВыходные токены: {out:,}\nПримерная стоимость: ${cost:.4f}",
        "access_request": "Запрос доступа от {label}",
        "approve_button": "✅ Разрешить",
        "deny_button": "⛔ Отклонить",
        "user_allowed": "Пользователь {target} разрешён.",
        "user_denied_msg": "Пользователь {target} отклонён.",
        "channel_blocked": "Админ заблокировал канал '{title}', ты больше не будешь получать обновления.",
        "channel_gone": "Канал '{title}' больше недоступен.",
        "language_prompt": "Текущий язык: {current}\nВыбери:",
    },
}


def t(lang: str, key: str, **fmt: object) -> str:
    table = _STRINGS.get(lang) or _STRINGS[DEFAULT_LANGUAGE]
    template = table.get(key) or _STRINGS[DEFAULT_LANGUAGE][key]
    return template.format(**fmt) if fmt else template
