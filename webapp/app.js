"use strict";

const tg = window.Telegram && window.Telegram.WebApp;

const I18N = {
  en: {
    search: "Search channels…",
    loading: "Loading…",
    empty: "No channels yet. Ask the admin to /update.",
    not_approved: "Not approved yet — talk to the admin.",
    network_error: "Network error.",
    saved: "Saved.",
    cleared: "Filter cleared.",
    deliveryMode: "Delivery mode",
    filterPrompt: "Filter prompt",
    filterPlaceholder: "Plain-language rules for what you want to see…",
    save: "Save filter",
    clear: "Clear",
    back: "← Back",
    noDescription: "No description.",
    open: "🔗 Open in Telegram",
    tips: [
      "Tips for a good filter:",
      "• Plain language; bullets work well.",
      "• Split into want / don't want (\"Interesting:\" / \"Not interesting:\").",
      "• Be concrete — name topics, domains, or keywords.",
      "• Add exceptions when broad rules have them.",
      "• Any language works.",
    ].join("\n"),
    modes: { off: "⬜ Off", filtered: "🔀 Filtered", debug: "🐞 Debug", all: "✅ All" },
    badgeFilter: "filter set",
    badgeMode: { off: "off", filtered: "filtered", debug: "debug", all: "all" },
    usageTitle: "Usage",
    usageMine: "Your usage",
    usagePerUser: "Per user (delivered)",
    usageSystem: "System total (actual API spend)",
    usageEmbeddings: "Embeddings",
    usageNone: "(none yet)",
    usageInOut: (i, o) => `in ${i.toLocaleString()} · out ${o.toLocaleString()}`,
    usageTokens: (n) => `${n.toLocaleString()} tokens`,
    settingsTitle: "Settings",
    autoDeleteHeading: "Auto-delete",
    autoDeleteLabel: "Hours (1–720, blank to disable)",
    autoDeleteHint: "When enabled, every summary DM gets a 💾 Save button. If you don't tap Save, the message is deleted after this many hours.",
    autoDeleteSave: "Save",
    autoDeleteClear: "Disable",
    autoDeleteEnabled: (h) => `Auto-delete after ${h}h.`,
    autoDeleteDisabled: "Auto-delete disabled.",
    autoDeleteBad: "Enter 1–720 hours.",
    dedupDebugHeading: "Dedup debug",
    dedupDebugLabel: "Enable",
    dedupDebugHint: "When on, near-duplicate posts are still delivered as fresh DMs marked 🔁 DUPLICATE with a link to the original. Off: duplicates are silently chained as buttons under the first DM.",
    dedupDebugOn: "Dedup debug on.",
    dedupDebugOff: "Dedup debug off.",
    summaryPromptHeading: "📝 Summary system prompt",
    summaryPromptLabel: "System prompt",
    summaryPromptHint: "This prompt is sent to the model for every summary, for all users. Reset restores the hardcoded default.",
    summaryPromptSave: "Save",
    summaryPromptReset: "Reset",
    summaryPromptSaved: "System prompt saved.",
    summaryPromptResetDone: "System prompt reset to default.",
    providerRequest: "Request to be a provider",
    providerPending: "Provider request pending",
    providerDenied: "Provider request denied",
    providerApproved: "✅ Provider",
    providerRequestSent: "Request submitted.",
    providerBlacklistLabel: "⛔ Blacklist for my contribution",
    providerBlacklistHint: "When checked, this channel is hidden from bot users via your contribution. Other providers' contributions are unaffected.",
    providerBlacklistOn: "Channel blacklisted.",
    providerBlacklistOff: "Channel un-blacklisted.",
  },
  ru: {
    search: "Поиск каналов…",
    loading: "Загрузка…",
    empty: "Каналов пока нет. Попроси админа /update.",
    not_approved: "Доступ ещё не одобрен — напиши админу.",
    network_error: "Ошибка сети.",
    saved: "Сохранено.",
    cleared: "Фильтр удалён.",
    deliveryMode: "Режим доставки",
    filterPrompt: "Фильтр",
    filterPlaceholder: "Опиши обычным языком, что тебе интересно…",
    save: "Сохранить",
    clear: "Очистить",
    back: "← Назад",
    noDescription: "Описания нет.",
    open: "🔗 Открыть в Telegram",
    tips: [
      "Советы по фильтру:",
      "• Пиши обычным языком; списки удобны.",
      "• Раздели на интересное/неинтересное.",
      "• Будь конкретным — темы, ключевые слова.",
      "• Добавляй исключения, если у правил они есть.",
      "• Можно писать на любом языке.",
    ].join("\n"),
    modes: { off: "⬜ Выкл", filtered: "🔀 Фильтр", debug: "🐞 Отладка", all: "✅ Все" },
    badgeFilter: "фильтр",
    badgeMode: { off: "выкл", filtered: "фильтр", debug: "отладка", all: "все" },
    usageTitle: "Расход",
    usageMine: "Твой расход",
    usagePerUser: "По пользователям (доставлено)",
    usageSystem: "Системный итог (фактический расход API)",
    usageEmbeddings: "Эмбеддинги",
    usageNone: "(пока пусто)",
    usageInOut: (i, o) => `вход ${i.toLocaleString()} · выход ${o.toLocaleString()}`,
    usageTokens: (n) => `${n.toLocaleString()} токенов`,
    settingsTitle: "Настройки",
    autoDeleteHeading: "Авто-удаление",
    autoDeleteLabel: "Часы (1–720, пусто — выкл)",
    autoDeleteHint: "Когда включено, у каждой сводки появляется кнопка 💾 Сохранить. Если не нажать — сообщение удалится через указанное число часов.",
    autoDeleteSave: "Сохранить",
    autoDeleteClear: "Отключить",
    autoDeleteEnabled: (h) => `Авто-удаление через ${h} ч.`,
    autoDeleteDisabled: "Авто-удаление отключено.",
    autoDeleteBad: "Введи 1–720 часов.",
    dedupDebugHeading: "Отладка дедупликации",
    dedupDebugLabel: "Включить",
    dedupDebugHint: "Когда включено, похожие посты приходят отдельными сообщениями с пометкой 🔁 ДУБЛЬ и ссылкой на оригинал. Выключено: дубли молча добавляются кнопкой к первому сообщению.",
    dedupDebugOn: "Отладка дедупликации включена.",
    dedupDebugOff: "Отладка дедупликации выключена.",
    summaryPromptHeading: "📝 Системный промпт сводок",
    summaryPromptLabel: "Системный промпт",
    summaryPromptHint: "Этот промпт отправляется модели для каждой сводки и применяется ко всем пользователям. Сброс возвращает значение по умолчанию.",
    summaryPromptSave: "Сохранить",
    summaryPromptReset: "Сбросить",
    summaryPromptSaved: "Системный промпт сохранён.",
    summaryPromptResetDone: "Системный промпт сброшен к значению по умолчанию.",
    providerRequest: "Стать провайдером",
    providerPending: "Запрос на провайдера в обработке",
    providerDenied: "Запрос на провайдера отклонён",
    providerApproved: "✅ Провайдер",
    providerRequestSent: "Запрос отправлен.",
    providerBlacklistLabel: "⛔ Заблокировать для моего вклада",
    providerBlacklistHint: "Когда отмечено, этот канал скрыт от пользователей бота через ваш вклад. Вклады других провайдеров не затрагиваются.",
    providerBlacklistOn: "Канал заблокирован.",
    providerBlacklistOff: "Канал разблокирован.",
  },
};

const state = {
  language: "en",
  channels: [],
  filteredView: [],
  searchQuery: "",
  selectedId: null,
  isOwner: false,
  autoDeleteHours: null,
  dedupDebug: false,
  summaryPrompt: null,
  summaryPromptDefault: null,
  isProvider: false,
  providerStatus: null,
  providerBlacklist: [],
  providerChannels: [],
};

function t() { return I18N[state.language] || I18N.en; }

function el(id) { return document.getElementById(id); }

function fmtUsd(n) { return `$${(n || 0).toFixed(4)}`; }

async function api(path, options = {}) {
  const initData = (tg && tg.initData) || "";
  const headers = { "Content-Type": "application/json", "X-Telegram-Init-Data": initData, ...(options.headers || {}) };
  const resp = await fetch(path, { ...options, headers });
  if (!resp.ok) {
    const body = await resp.json().catch(() => ({}));
    const err = new Error(body.error || `HTTP ${resp.status}`);
    err.status = resp.status;
    throw err;
  }
  return resp.json();
}

function showToast(message) {
  const node = el("toast");
  node.textContent = message;
  node.classList.add("visible");
  clearTimeout(showToast._timer);
  showToast._timer = setTimeout(() => node.classList.remove("visible"), 1800);
}

function applyLanguage() {
  const dict = t();
  el("search").placeholder = dict.search;
  el("filter-input").placeholder = dict.filterPlaceholder;
  el("filter-tips").textContent = dict.tips;
  el("filter-save").textContent = dict.save;
  el("filter-clear").textContent = dict.clear;
  el("details-back").textContent = dict.back;
  el("usage-back").textContent = dict.back;
  el("usage-title").textContent = dict.usageTitle;
  el("settings-back").textContent = dict.back;
  el("settings-title").textContent = dict.settingsTitle;
  el("autodel-heading").textContent = dict.autoDeleteHeading;
  el("autodel-label").textContent = dict.autoDeleteLabel;
  el("autodel-hint").textContent = dict.autoDeleteHint;
  el("autodel-save").textContent = dict.autoDeleteSave;
  el("autodel-clear").textContent = dict.autoDeleteClear;
  el("dedup-debug-heading").textContent = dict.dedupDebugHeading;
  el("dedup-debug-label").textContent = dict.dedupDebugLabel;
  el("dedup-debug-hint").textContent = dict.dedupDebugHint;
  el("summary-prompt-heading").textContent = dict.summaryPromptHeading;
  el("summary-prompt-label").textContent = dict.summaryPromptLabel;
  el("summary-prompt-hint").textContent = dict.summaryPromptHint;
  el("summary-prompt-save").textContent = dict.summaryPromptSave;
  el("summary-prompt-reset").textContent = dict.summaryPromptReset;
  el("provider-blacklist-label").textContent = dict.providerBlacklistLabel;
  el("provider-blacklist-hint").textContent = dict.providerBlacklistHint;
  document.querySelectorAll('input[name="mode"]').forEach((input) => {
    const labelSpan = input.nextElementSibling;
    labelSpan.textContent = dict.modes[input.value];
  });
  renderProviderBanner();
}


function renderProviderBanner() {
  const banner = el("provider-banner");
  const dict = t();
  banner.replaceChildren();
  if (state.isOwner || state.isProvider) {
    if (state.isProvider) {
      const tag = document.createElement("span");
      tag.className = "provider-tag approved";
      tag.textContent = dict.providerApproved;
      banner.appendChild(tag);
      banner.hidden = false;
      return;
    }
  }
  if (state.providerStatus === "pending") {
    const tag = document.createElement("span");
    tag.className = "provider-tag pending";
    tag.textContent = dict.providerPending;
    banner.appendChild(tag);
    banner.hidden = false;
    return;
  }
  if (state.providerStatus === "denied") {
    const tag = document.createElement("span");
    tag.className = "provider-tag denied";
    tag.textContent = dict.providerDenied;
    banner.appendChild(tag);
    banner.hidden = false;
    return;
  }
  if (!state.isOwner && state.providerStatus === null) {
    const btn = document.createElement("button");
    btn.id = "provider-request-btn";
    btn.type = "button";
    btn.className = "provider-request";
    btn.textContent = dict.providerRequest;
    btn.addEventListener("click", requestProvider);
    banner.appendChild(btn);
    banner.hidden = false;
    return;
  }
  banner.hidden = true;
}


async function requestProvider() {
  const btn = el("provider-request-btn");
  if (btn) btn.disabled = true;
  try {
    const data = await api("/api/become_provider", {
      method: "POST",
      body: JSON.stringify({}),
    });
    if (data.ok) {
      state.providerStatus = "pending";
      state.isProvider = false;
      showToast(t().providerRequestSent);
      if (tg && tg.HapticFeedback) tg.HapticFeedback.notificationOccurred("success");
    } else if (data.reason === "already_pending") {
      state.providerStatus = "pending";
    } else if (data.reason === "already_approved") {
      state.providerStatus = "approved";
      state.isProvider = true;
    } else if (data.reason === "denied") {
      state.providerStatus = "denied";
    }
    renderProviderBanner();
  } catch (e) {
    if (btn) btn.disabled = false;
    showToast(e.message || t().network_error);
  }
}


async function toggleProviderBlacklist(channelId, blacklisted) {
  try {
    const data = await api("/api/blacklist", {
      method: "POST",
      body: JSON.stringify({ channel_id: channelId, blacklisted }),
    });
    state.providerBlacklist = data.blacklist || [];
    const dict = t();
    showToast(blacklisted ? dict.providerBlacklistOn : dict.providerBlacklistOff);
    if (tg && tg.HapticFeedback) tg.HapticFeedback.impactOccurred("light");
    renderList();
  } catch (e) {
    el("provider-blacklist-input").checked = (state.providerBlacklist || []).includes(channelId);
    showToast(e.message || t().network_error);
  }
}

function rebuildLangSelect() {
  const sel = el("lang");
  sel.innerHTML = "";
  for (const code of ["en", "ru"]) {
    const opt = document.createElement("option");
    opt.value = code;
    opt.textContent = code === "en" ? "English" : "Русский";
    if (code === state.language) opt.selected = true;
    sel.appendChild(opt);
  }
}

function renderList() {
  const dict = t();
  const container = el("list");
  container.removeAttribute("aria-busy");
  const q = state.searchQuery.trim().toLowerCase();
  const items = state.channels.filter((c) => !q || c.title.toLowerCase().includes(q));
  state.filteredView = items;

  if (items.length === 0) {
    container.innerHTML = `<div class="empty">${q ? "—" : dict.empty}</div>`;
    return;
  }

  const blSet = new Set(state.providerBlacklist || []);
  const frag = document.createDocumentFragment();
  for (const c of items) {
    const row = document.createElement("div");
    row.className = "row";
    row.dataset.id = String(c.id);

    const icon = document.createElement("div");
    icon.className = "mode-icon";
    icon.textContent = ({ off: "⬜", filtered: "🔀", debug: "🐞", all: "✅" })[c.mode] || "⬜";

    const titleBlock = document.createElement("div");
    titleBlock.className = "title-block";
    const title = document.createElement("div");
    title.className = "title";
    title.textContent = (state.isProvider && blSet.has(c.id) ? "⛔ " : "") + c.title;
    titleBlock.appendChild(title);

    const meta = document.createElement("div");
    meta.className = "meta";
    const modeBadge = document.createElement("span");
    modeBadge.className = "badge";
    modeBadge.textContent = dict.badgeMode[c.mode] || c.mode;
    meta.appendChild(modeBadge);
    if (c.filter_prompt) {
      const f = document.createElement("span");
      f.className = "badge has-filter";
      f.textContent = dict.badgeFilter;
      meta.appendChild(f);
    }
    if (c.username) {
      const u = document.createElement("span");
      u.textContent = "@" + c.username;
      meta.appendChild(u);
    }
    titleBlock.appendChild(meta);

    const chev = document.createElement("div");
    chev.className = "chevron";
    chev.textContent = "›";

    row.appendChild(icon);
    row.appendChild(titleBlock);
    row.appendChild(chev);
    row.addEventListener("click", () => openDetails(c.id));
    frag.appendChild(row);
  }
  container.replaceChildren(frag);
}

function openDetails(channelId) {
  const c = state.channels.find((x) => x.id === channelId);
  if (!c) return;
  state.selectedId = channelId;
  const dict = t();

  el("details-title").textContent = c.title;
  const link = el("details-link");
  if (c.username) {
    link.textContent = dict.open;
    link.href = `https://t.me/${c.username}`;
    link.hidden = false;
  } else {
    link.hidden = true;
  }
  el("details-about").textContent = c.about || "";

  document.querySelectorAll('input[name="mode"]').forEach((input) => {
    input.checked = input.value === c.mode;
  });
  el("filter-input").value = c.filter_prompt || "";

  const blSection = el("provider-blacklist-section");
  const providerChannels = new Set(state.providerChannels || []);
  if (state.isProvider && providerChannels.has(c.id)) {
    blSection.hidden = false;
    el("provider-blacklist-input").checked =
      (state.providerBlacklist || []).includes(c.id);
  } else {
    blSection.hidden = true;
  }

  el("list").classList.add("hidden");
  el("details").classList.remove("hidden");
  el("details").setAttribute("aria-hidden", "false");
  el("search").parentElement.style.display = "none";
  window.scrollTo(0, 0);

  if (tg && tg.BackButton) {
    tg.BackButton.show();
    tg.BackButton.onClick(closeDetails);
  }
}

function closeDetails() {
  state.selectedId = null;
  el("details").classList.add("hidden");
  el("details").setAttribute("aria-hidden", "true");
  el("list").classList.remove("hidden");
  el("search").parentElement.style.display = "";
  if (tg && tg.BackButton) {
    tg.BackButton.offClick(closeDetails);
    tg.BackButton.hide();
  }
}

function renderUsage(data) {
  const dict = t();
  const body = el("usage-body");
  body.replaceChildren();

  const mine = document.createElement("div");
  mine.className = "usage-section";
  mine.innerHTML = `<h3>${dict.usageMine}</h3>`;
  const mineRow = document.createElement("div");
  mineRow.className = "usage-row";
  const u = data.user;
  mineRow.innerHTML = `<span>${dict.usageInOut(u.input_tokens, u.output_tokens)}</span><span class="num">${fmtUsd(u.cost_usd)}</span>`;
  mine.appendChild(mineRow);
  body.appendChild(mine);

  if (data.is_owner) {
    const perUser = document.createElement("div");
    perUser.className = "usage-section";
    perUser.innerHTML = `<h3>${dict.usagePerUser}</h3>`;
    if (!data.per_user || data.per_user.length === 0) {
      const empty = document.createElement("div");
      empty.className = "usage-row";
      empty.textContent = dict.usageNone;
      perUser.appendChild(empty);
    } else {
      for (const r of data.per_user) {
        const row = document.createElement("div");
        row.className = "usage-row";
        row.innerHTML = `<span>${r.label} — ${dict.usageInOut(r.input_tokens, r.output_tokens)}</span><span class="num">${fmtUsd(r.cost_usd)}</span>`;
        perUser.appendChild(row);
      }
    }
    body.appendChild(perUser);

    const sys = document.createElement("div");
    sys.className = "usage-section";
    sys.innerHTML = `<h3>${dict.usageSystem}</h3>`;
    const sysRow = document.createElement("div");
    sysRow.className = "usage-row";
    const s = data.system;
    sysRow.innerHTML = `<span>${dict.usageInOut(s.input_tokens, s.output_tokens)}</span><span class="num">${fmtUsd(s.cost_usd)}</span>`;
    sys.appendChild(sysRow);
    body.appendChild(sys);

    const emb = document.createElement("div");
    emb.className = "usage-section";
    emb.innerHTML = `<h3>${dict.usageEmbeddings}</h3>`;
    const embRow = document.createElement("div");
    embRow.className = "usage-row";
    const e = data.embeddings;
    embRow.innerHTML = `<span>${dict.usageTokens(e.tokens)}</span><span class="num">${fmtUsd(e.cost_usd)}</span>`;
    emb.appendChild(embRow);
    body.appendChild(emb);
  }
}

async function openUsage() {
  el("usage").classList.remove("hidden");
  el("usage").setAttribute("aria-hidden", "false");
  el("list").classList.add("hidden");
  el("search").parentElement.style.display = "none";
  window.scrollTo(0, 0);
  el("usage-body").innerHTML = `<div class="empty">${t().loading}</div>`;
  if (tg && tg.BackButton) {
    tg.BackButton.show();
    tg.BackButton.onClick(closeUsage);
  }
  try {
    const data = await api("/api/usage");
    renderUsage(data);
  } catch (e) {
    el("usage-body").innerHTML = `<div class="empty">${e.message || t().network_error}</div>`;
  }
}

function closeUsage() {
  el("usage").classList.add("hidden");
  el("usage").setAttribute("aria-hidden", "true");
  el("list").classList.remove("hidden");
  el("search").parentElement.style.display = "";
  if (tg && tg.BackButton) {
    tg.BackButton.offClick(closeUsage);
    tg.BackButton.hide();
  }
}

function openSettings() {
  el("autodel-input").value = state.autoDeleteHours == null ? "" : String(state.autoDeleteHours);
  el("dedup-debug-input").checked = !!state.dedupDebug;
  const promptSection = el("summary-prompt-section");
  if (state.isOwner) {
    promptSection.hidden = false;
    const promptInput = el("summary-prompt-input");
    if (state.summaryPrompt == null) {
      promptInput.value = "";
      promptInput.placeholder = state.summaryPromptDefault || "";
    } else {
      promptInput.value = state.summaryPrompt;
      promptInput.placeholder = "";
    }
  } else {
    promptSection.hidden = true;
  }
  el("settings").classList.remove("hidden");
  el("settings").setAttribute("aria-hidden", "false");
  el("list").classList.add("hidden");
  el("search").parentElement.style.display = "none";
  window.scrollTo(0, 0);
  if (tg && tg.BackButton) {
    tg.BackButton.show();
    tg.BackButton.onClick(closeSettings);
  }
}

function closeSettings() {
  el("settings").classList.add("hidden");
  el("settings").setAttribute("aria-hidden", "true");
  el("list").classList.remove("hidden");
  el("search").parentElement.style.display = "";
  if (tg && tg.BackButton) {
    tg.BackButton.offClick(closeSettings);
    tg.BackButton.hide();
  }
}

async function saveDedupDebug(enabled) {
  try {
    const data = await api("/api/dedup_debug", {
      method: "POST",
      body: JSON.stringify({ enabled }),
    });
    state.dedupDebug = !!data.dedup_debug;
    const dict = t();
    showToast(state.dedupDebug ? dict.dedupDebugOn : dict.dedupDebugOff);
    if (tg && tg.HapticFeedback) tg.HapticFeedback.impactOccurred("light");
  } catch (e) {
    el("dedup-debug-input").checked = !!state.dedupDebug;
    showToast(e.message || t().network_error);
  }
}

async function saveAutoDelete(hours) {
  try {
    const data = await api("/api/auto_delete", {
      method: "POST",
      body: JSON.stringify({ hours }),
    });
    state.autoDeleteHours = data.auto_delete_hours;
    const dict = t();
    showToast(
      data.auto_delete_hours == null
        ? dict.autoDeleteDisabled
        : dict.autoDeleteEnabled(data.auto_delete_hours),
    );
    if (tg && tg.HapticFeedback) tg.HapticFeedback.notificationOccurred("success");
  } catch (e) {
    showToast(e.message === "bad_hours" ? t().autoDeleteBad : (e.message || t().network_error));
  }
}

async function saveSummaryPrompt(prompt, resetDone) {
  try {
    const data = await api("/api/summary_prompt", {
      method: "POST",
      body: JSON.stringify({ prompt }),
    });
    state.summaryPrompt = data.summary_prompt == null ? null : String(data.summary_prompt);
    state.summaryPromptDefault = data.summary_prompt_default == null ? null : String(data.summary_prompt_default);
    const promptInput = el("summary-prompt-input");
    if (state.summaryPrompt == null) {
      promptInput.value = "";
      promptInput.placeholder = state.summaryPromptDefault || "";
    } else {
      promptInput.value = state.summaryPrompt;
      promptInput.placeholder = "";
    }
    const dict = t();
    showToast(resetDone ? dict.summaryPromptResetDone : dict.summaryPromptSaved);
    if (tg && tg.HapticFeedback) tg.HapticFeedback.impactOccurred("light");
  } catch (e) {
    showToast(e.message || t().network_error);
  }
}

async function changeMode(channelId, mode) {
  try {
    const data = await api("/api/subscription", {
      method: "POST",
      body: JSON.stringify({ channel_id: channelId, mode }),
    });
    state.channels = data.channels;
    renderList();
    showToast(t().saved);
    if (tg && tg.HapticFeedback) tg.HapticFeedback.impactOccurred("light");
  } catch (e) {
    showToast(e.message || t().network_error);
  }
}

async function saveFilter(channelId, prompt) {
  try {
    const data = await api("/api/filter", {
      method: "POST",
      body: JSON.stringify({ channel_id: channelId, filter_prompt: prompt }),
    });
    state.channels = data.channels;
    renderList();
    const fresh = state.channels.find((x) => x.id === channelId);
    if (fresh && state.selectedId === channelId) {
      document.querySelectorAll('input[name="mode"]').forEach((input) => {
        input.checked = input.value === fresh.mode;
      });
      el("filter-input").value = fresh.filter_prompt || "";
    }
    showToast(prompt ? t().saved : t().cleared);
    if (tg && tg.HapticFeedback) tg.HapticFeedback.notificationOccurred("success");
  } catch (e) {
    showToast(e.message || t().network_error);
  }
}

async function changeLanguage(code) {
  try {
    await api("/api/language", { method: "POST", body: JSON.stringify({ language: code }) });
    state.language = code;
    applyLanguage();
    renderList();
  } catch (e) {
    showToast(e.message || t().network_error);
  }
}

function deepLinkChannelId() {
  const sp = (tg && tg.initDataUnsafe && tg.initDataUnsafe.start_param) || "";
  const m = String(sp).match(/^channel_(-?\d+)$/);
  if (m) return Number(m[1]);
  const q = new URLSearchParams(window.location.search);
  const c = q.get("channel");
  return c ? Number(c) : null;
}

async function init() {
  if (tg) {
    tg.ready();
    tg.expand();
    if (tg.setHeaderColor) {
      try { tg.setHeaderColor("secondary_bg_color"); } catch (_) {}
    }
  }

  rebuildLangSelect();
  applyLanguage();

  try {
    const data = await api("/api/state");
    state.language = data.language || "en";
    state.channels = data.channels || [];
    state.isOwner = !!data.is_owner;
    state.autoDeleteHours = data.auto_delete_hours == null ? null : Number(data.auto_delete_hours);
    state.dedupDebug = !!data.dedup_debug;
    state.summaryPrompt = data.summary_prompt == null ? null : String(data.summary_prompt);
    state.summaryPromptDefault = data.summary_prompt_default == null ? null : String(data.summary_prompt_default);
    state.isProvider = !!data.is_provider;
    state.providerStatus = data.provider_status == null ? null : String(data.provider_status);
    state.providerBlacklist = Array.isArray(data.provider_blacklist) ? data.provider_blacklist : [];
    state.providerChannels = Array.isArray(data.provider_channels) ? data.provider_channels : [];
    rebuildLangSelect();
    applyLanguage();
    renderList();
    const targetId = deepLinkChannelId();
    if (targetId != null && state.channels.some((c) => c.id === targetId)) {
      openDetails(targetId);
    }
  } catch (e) {
    el("list").innerHTML = `<div class="empty">${
      e.status === 403 ? t().not_approved : (e.message || t().network_error)
    }</div>`;
  }

  el("search").addEventListener("input", (ev) => {
    state.searchQuery = ev.target.value;
    renderList();
  });
  el("lang").addEventListener("change", (ev) => changeLanguage(ev.target.value));
  el("details-back").addEventListener("click", closeDetails);
  el("usage-btn").addEventListener("click", openUsage);
  el("usage-back").addEventListener("click", closeUsage);
  el("settings-btn").addEventListener("click", openSettings);
  el("settings-back").addEventListener("click", closeSettings);
  el("autodel-save").addEventListener("click", () => {
    const raw = el("autodel-input").value.trim();
    if (raw === "") return saveAutoDelete(null);
    const n = parseInt(raw, 10);
    if (Number.isNaN(n) || n < 1 || n > 720) return showToast(t().autoDeleteBad);
    saveAutoDelete(n);
  });
  el("autodel-clear").addEventListener("click", () => {
    el("autodel-input").value = "";
    saveAutoDelete(null);
  });
  el("dedup-debug-input").addEventListener("change", (ev) => {
    saveDedupDebug(!!ev.target.checked);
  });
  el("summary-prompt-save").addEventListener("click", () => {
    const value = el("summary-prompt-input").value.trim();
    saveSummaryPrompt(value || null, false);
  });
  el("summary-prompt-reset").addEventListener("click", () => {
    el("summary-prompt-input").value = "";
    saveSummaryPrompt(null, true);
  });

  document.querySelectorAll('input[name="mode"]').forEach((input) => {
    input.addEventListener("change", () => {
      if (state.selectedId == null) return;
      changeMode(state.selectedId, input.value);
    });
  });

  el("filter-save").addEventListener("click", () => {
    if (state.selectedId == null) return;
    const value = el("filter-input").value.trim();
    saveFilter(state.selectedId, value || null);
  });
  el("filter-clear").addEventListener("click", () => {
    if (state.selectedId == null) return;
    el("filter-input").value = "";
    saveFilter(state.selectedId, null);
  });

  el("provider-blacklist-input").addEventListener("change", (ev) => {
    if (state.selectedId == null) return;
    toggleProviderBlacklist(state.selectedId, !!ev.target.checked);
  });
}

init();
