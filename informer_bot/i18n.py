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
            "/update — refresh the channel list from your Telegram account"
        ),
        "refreshing": "Refreshing channel list...",
        "refresh_failed": "Refresh failed. Check logs.",
        "refresh_done": "Channel list refreshed.",
        "usage_admin_header": "Usage by user (delivered), per provider:",
        "usage_admin_none": "  (none yet)",
        "usage_admin_system_label": "System total (actual API spend), per provider:",
        "usage_admin_embedding_label": "Embeddings, per provider:",
        "usage_user_header": "Your usage, per provider:",
        "usage_user_none": "  (none yet)",
        "usage_user_total": "  Total: in={inp:,} out={out:,} ≈ ${cost:.4f}",
        "access_request": "Access request from {label}",
        "approve_button": "✅ Allow",
        "deny_button": "⛔ Deny",
        "user_allowed": "Allowed user {target}.",
        "user_denied_msg": "Denied user {target}.",
        "channel_gone": "Channel '{title}' is no longer available.",
        "channel_new": "📢 New channel available: {title}\nOpen the Mini App to subscribe.",
        "channel_new_open_button": "🪟 Open in Mini App",
        "debug_filtered_marker": "🐞 FILTERED",
        "debug_duplicate_marker": "🔁 DUPLICATE",
        "summary_truncated_marker": "⚠️ summary truncated",
        "summary_truncated_notice": "⚠️ Couldn't summarize this post — the model hit its output limit. Open the original above.",
        "original_label": "Original",
        "dedup_disabled_notice": "⚠️ Deduplication disabled: OPENAI_API_KEY is not set.",
        "startup_notice": "🟢 Bot started.",
        "shutdown_notice": "🔴 Bot shutting down.",
        "open_miniapp_button": "🪟 Open Mini App",
        "miniapp_intro": "Open the channel manager:",
        "miniapp_unconfigured": "Mini App is not configured (MINIAPP_URL is unset).",
        "miniapp_menu_label": "Channels",
        "save_button": "💾 Save",
        "saved_button": "✅ Saved",
        "channel_settings_link": "⚙",
        "provider_request_submitted": "Your request to become a provider has been submitted. The owner will review it.",
        "provider_owner_already": "You are already the primary provider.",
        "provider_already_pending": "Your provider request is already pending review.",
        "provider_already_approved": "You are already an approved provider.",
        "provider_request_denied": "Your previous provider request was denied. Contact the owner.",
        "provider_request_admin": "Provider request from {user_label}. Approve?",
        "provider_approve_button": "Approve",
        "provider_deny_button": "Deny",
        "become_provider_button": "🛰 Become a provider",
        "provider_self_approved_user": "You're now a provider. The owner will run the login CLI for your Telegram account before your channels are picked up.",
        "provider_self_approved_owner": "User {user_label} self-onboarded as a provider. Run the login CLI when ready.",
        "provider_approved_owner": "Provider approved: {user_label}. Run the login CLI for them next.",
        "provider_approved_user": "You're approved as a provider. The owner still needs to run the login CLI for your Telegram account before you can contribute.",
        "provider_denied_owner": "Provider request denied: {user_label}.",
        "provider_denied_user": "Your provider request was denied.",
        "revoke_invalid_id": "Usage: /revoke_provider <user_id>",
        "revoke_cannot_revoke_owner": "Cannot revoke the primary provider.",
        "revoke_not_a_provider": "User is not a provider.",
        "provider_revoked_owner": "Provider revoked: {user_label}. Their session file was removed.",
        "provider_revoked_user": "Your provider status has been revoked.",
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
            "/update — обновить список каналов из твоего Telegram-аккаунта"
        ),
        "refreshing": "Обновляю список каналов...",
        "refresh_failed": "Обновление не удалось. Смотри логи.",
        "refresh_done": "Список каналов обновлён.",
        "usage_admin_header": "Расход по пользователям (доставлено), по провайдерам:",
        "usage_admin_none": "  (пока пусто)",
        "usage_admin_system_label": "Системный итог (фактический расход API), по провайдерам:",
        "usage_admin_embedding_label": "Эмбеддинги, по провайдерам:",
        "usage_user_header": "Твой расход, по провайдерам:",
        "usage_user_none": "  (пока пусто)",
        "usage_user_total": "  Итого: in={inp:,} out={out:,} ≈ ${cost:.4f}",
        "access_request": "Запрос доступа от {label}",
        "approve_button": "✅ Разрешить",
        "deny_button": "⛔ Отклонить",
        "user_allowed": "Пользователь {target} разрешён.",
        "user_denied_msg": "Пользователь {target} отклонён.",
        "channel_gone": "Канал '{title}' больше недоступен.",
        "channel_new": "📢 Новый канал доступен: {title}\nОткрой Mini App, чтобы подписаться.",
        "channel_new_open_button": "🪟 Открыть в Mini App",
        "debug_filtered_marker": "🐞 ОТФИЛЬТРОВАНО",
        "debug_duplicate_marker": "🔁 ДУБЛЬ",
        "summary_truncated_marker": "⚠️ выжимка обрезана",
        "summary_truncated_notice": "⚠️ Не удалось сделать выжимку — модель упёрлась в лимит токенов. Открой оригинал по ссылке выше.",
        "original_label": "Оригинал",
        "dedup_disabled_notice": "⚠️ Дедупликация отключена: OPENAI_API_KEY не задан.",
        "startup_notice": "🟢 Бот запущен.",
        "shutdown_notice": "🔴 Бот выключается.",
        "open_miniapp_button": "🪟 Открыть Mini App",
        "miniapp_intro": "Открой менеджер каналов:",
        "miniapp_unconfigured": "Mini App не настроен (MINIAPP_URL не задан).",
        "miniapp_menu_label": "Каналы",
        "save_button": "💾 Сохранить",
        "saved_button": "✅ Сохранено",
        "channel_settings_link": "⚙",
        "provider_request_submitted": "Ваш запрос на статус провайдера отправлен. Владелец рассмотрит его.",
        "provider_owner_already": "Вы уже основной провайдер.",
        "provider_already_pending": "Ваш запрос уже находится на рассмотрении.",
        "provider_already_approved": "Вы уже подтверждённый провайдер.",
        "provider_request_denied": "Ваш предыдущий запрос был отклонён. Свяжитесь с владельцем.",
        "provider_request_admin": "Запрос на провайдера от {user_label}. Одобрить?",
        "provider_approve_button": "Одобрить",
        "provider_deny_button": "Отклонить",
        "become_provider_button": "🛰 Стать провайдером",
        "provider_self_approved_user": "Вы стали провайдером. Перед тем как ваши каналы начнут обрабатываться, владельцу нужно запустить CLI входа для вашего Telegram-аккаунта.",
        "provider_self_approved_owner": "Пользователь {user_label} самостоятельно стал провайдером. Запустите CLI входа, когда будете готовы.",
        "provider_approved_owner": "Провайдер одобрен: {user_label}. Теперь запустите CLI входа для их аккаунта.",
        "provider_approved_user": "Вы одобрены как провайдер. Владельцу ещё нужно запустить CLI входа для вашего Telegram-аккаунта, прежде чем вы сможете участвовать.",
        "provider_denied_owner": "Запрос отклонён: {user_label}.",
        "provider_denied_user": "Ваш запрос на провайдера отклонён.",
        "revoke_invalid_id": "Использование: /revoke_provider <user_id>",
        "revoke_cannot_revoke_owner": "Нельзя отозвать основного провайдера.",
        "revoke_not_a_provider": "Пользователь не является провайдером.",
        "provider_revoked_owner": "Провайдер отозван: {user_label}. Файл сессии удалён.",
        "provider_revoked_user": "Ваш статус провайдера отозван.",
    },
}


def t(lang: str, key: str, **fmt: object) -> str:
    table = _STRINGS.get(lang) or _STRINGS[DEFAULT_LANGUAGE]
    template = table.get(key) or _STRINGS[DEFAULT_LANGUAGE][key]
    return template.format(**fmt) if fmt else template
