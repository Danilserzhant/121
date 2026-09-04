"""Reply and inline keyboards."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

from .config import Settings
from .formatting import tf_name
from .storage import SUB_KINDS, SUB_TITLES, Store

# Reply keyboard labels (also matched as text by handlers).
BTN_TOP = "📊 Топ ATR"
BTN_EXP = "📈 Рост ATR"
BTN_WATCH = "👀 Мои монеты"
BTN_SYMBOL = "🔎 Монета"
BTN_SUBS = "🔔 Подписки"
BTN_HELP = "❓ Помощь"
BTN_SETTINGS = "⚙️ Настройки"
BTN_USERS = "👥 Пользователи"
BTN_REQUESTS = "📨 Заявки"
BTN_CANCEL = "✖ Отмена"

MENU_BUTTONS = {BTN_TOP, BTN_EXP, BTN_WATCH, BTN_SYMBOL, BTN_SUBS, BTN_HELP, BTN_SETTINGS, BTN_USERS, BTN_REQUESTS, BTN_CANCEL}


def main_menu(is_admin: bool) -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(text=BTN_TOP), KeyboardButton(text=BTN_EXP)],
        [KeyboardButton(text=BTN_WATCH), KeyboardButton(text=BTN_SYMBOL)],
        [KeyboardButton(text=BTN_SUBS), KeyboardButton(text=BTN_HELP)],
    ]
    if is_admin:
        rows.append([KeyboardButton(text=BTN_SETTINGS), KeyboardButton(text=BTN_USERS), KeyboardButton(text=BTN_REQUESTS)])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True, is_persistent=True, input_field_placeholder="Тикер или команда…")


def cancel_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=BTN_CANCEL)]], resize_keyboard=True)


def _mark(active: bool, text: str) -> str:
    return ("· " if active else "") + text


def top_keyboard(settings: Settings, by: str, interval: str, n: int, direction: str) -> InlineKeyboardMarkup:
    def cb(by_=by, tf=interval, n_=n, d=direction) -> str:
        return f"top:{by_}:{tf}:{n_}:{d}"

    tf_row = [InlineKeyboardButton(text=_mark(tf == interval, tf_name(tf)), callback_data=cb(tf=tf)) for tf in settings.intervals]
    mode_row = [
        InlineKeyboardButton(text=_mark(by == "atr", "ATR%"), callback_data=cb(by_="atr")),
        InlineKeyboardButton(text=_mark(by == "expansion", "ΔATR"), callback_data=cb(by_="expansion")),
        InlineKeyboardButton(text=_mark(direction == "long", "🟢 Long"), callback_data=cb(d="long")),
        InlineKeyboardButton(text=_mark(direction == "short", "🔴 Short"), callback_data=cb(d="short")),
        InlineKeyboardButton(text=_mark(direction == "all", "Все"), callback_data=cb(d="all")),
    ]
    action_row = [
        InlineKeyboardButton(text=_mark(n == 10, "10"), callback_data=cb(n_=10)),
        InlineKeyboardButton(text=_mark(n == 20, "20"), callback_data=cb(n_=20)),
        InlineKeyboardButton(text=_mark(n == 30, "30"), callback_data=cb(n_=30)),
        InlineKeyboardButton(text="🔄 Обновить", callback_data=cb() + ":r"),
    ]
    return InlineKeyboardMarkup(inline_keyboard=[tf_row, mode_row, action_row])


def chart_keyboard(settings: Settings, symbol: str, interval: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=_mark(tf == interval, tf_name(tf)), callback_data=f"chart:{symbol}:{tf}") for tf in settings.intervals],
        [InlineKeyboardButton(text="👀 Следить", callback_data=f"w:add:{symbol}"),
         InlineKeyboardButton(text="🔎 Карточка", callback_data=f"sym:{symbol}")],
    ])


def symbol_keyboard(settings: Settings, symbol: str, watched: bool) -> InlineKeyboardMarkup:
    watch_btn = (
        InlineKeyboardButton(text="✖ Не следить", callback_data=f"w:rm:{symbol}:sym")
        if watched else InlineKeyboardButton(text="👀 Следить", callback_data=f"w:add:{symbol}")
    )
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"📈 {tf_name(tf)}", callback_data=f"chart:{symbol}:{tf}") for tf in settings.intervals],
        [watch_btn, InlineKeyboardButton(text="🔄 Обновить", callback_data=f"sym:{symbol}")],
    ])


def watchlist_keyboard(symbols: list[str]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for sym in symbols:
        short = sym.removesuffix("USDT")
        rows.append([
            InlineKeyboardButton(text=f"🔎 {short}", callback_data=f"sym:{sym}"),
            InlineKeyboardButton(text="📈", callback_data=f"chart:{sym}:1h"),
            InlineKeyboardButton(text="✖", callback_data=f"w:rm:{sym}:list"),
        ])
    footer = [InlineKeyboardButton(text="➕ Добавить", callback_data="w:ask"), InlineKeyboardButton(text="🔄 Обновить", callback_data="w:refresh")]
    if symbols:
        footer.append(InlineKeyboardButton(text="🗑 Очистить", callback_data="w:clear"))
    rows.append(footer)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def subs_keyboard(store: Store, chat_id: int) -> InlineKeyboardMarkup:
    kinds = store.chat_subs(chat_id)
    rows = [
        [InlineKeyboardButton(text=("✅ " if k in kinds else "☐ ") + SUB_TITLES[k], callback_data=f"sub:toggle:{k}")]
        for k in SUB_KINDS
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


# Settings menu: attribute -> (label, choices)
SETTING_CHOICES: dict[str, tuple[str, list[float]]] = {
    "top_n": ("Топ", [10, 15, 20, 30]),
    "atr_period": ("ATR период", [7, 10, 14, 20]),
    "min_quote_volume": ("Мин. оборот", [1e6, 3e6, 5e6, 10e6, 50e6]),
    "alert_tr_ratio": ("Выброс ×ATR", [2, 2.5, 3, 4]),
    "watch_tr_ratio": ("Watch ×ATR", [1.5, 2, 2.5, 3]),
    "watch_expansion_pct": ("Watch ΔATR %", [30, 50, 100, 200]),
}


def _fmt_choice(attr: str, v: float) -> str:
    if attr == "min_quote_volume":
        return f"{v/1e6:g}M"
    return f"{v:g}"


def settings_keyboard(settings: Settings) -> InlineKeyboardMarkup:
    rows = []
    for attr, (label, choices) in SETTING_CHOICES.items():
        current = getattr(settings, attr)
        rows.append([InlineKeyboardButton(text=f"{label}:", callback_data="noop")] + [
            InlineKeyboardButton(text=_mark(abs(current - v) < 1e-9, _fmt_choice(attr, v)), callback_data=f"set:{attr}:{v:g}")
            for v in choices
        ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def users_keyboard(store: Store, actor_is_owner: bool) -> InlineKeyboardMarkup:
    from .storage import ROLE_ADMIN, ROLE_OWNER, ROLE_TRADER

    rows = []
    users = sorted(store.users.values(), key=lambda u: ({ROLE_OWNER: 0, ROLE_ADMIN: 1, ROLE_TRADER: 2}[u.role], u.added_at))
    for u in users[:40]:
        if u.role == ROLE_OWNER:
            continue
        name = ("@" + u.username) if u.username else (u.name or str(u.id))
        icon = "🛠" if u.role == ROLE_ADMIN else "📈"
        row = [InlineKeyboardButton(text=f"{icon} {name[:20]}", callback_data="noop")]
        if u.role == ROLE_TRADER:
            if actor_is_owner:
                row.append(InlineKeyboardButton(text="⬆ админ", callback_data=f"u:{u.id}:admin"))
            row.append(InlineKeyboardButton(text="✖ убрать", callback_data=f"u:{u.id}:remove"))
        elif actor_is_owner:
            row.append(InlineKeyboardButton(text="⬇ трейдер", callback_data=f"u:{u.id}:trader"))
            row.append(InlineKeyboardButton(text="✖ убрать", callback_data=f"u:{u.id}:remove"))
        rows.append(row)
    rows.append([InlineKeyboardButton(text="📨 Заявки", callback_data="menu:requests"), InlineKeyboardButton(text="🔄 Обновить", callback_data="menu:users")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def requests_keyboard(store: Store, actor_is_owner: bool) -> InlineKeyboardMarkup:
    rows = []
    for uid, info in store.pending()[:20]:
        name = ("@" + info["username"]) if info.get("username") else (info.get("name") or str(uid))
        row = [
            InlineKeyboardButton(text=name[:20], callback_data="noop"),
            InlineKeyboardButton(text="✅ трейдер", callback_data=f"u:{uid}:trader"),
        ]
        if actor_is_owner:
            row.append(InlineKeyboardButton(text="🛠 админ", callback_data=f"u:{uid}:admin"))
        row.append(InlineKeyboardButton(text="🚫", callback_data=f"u:{uid}:deny"))
        rows.append(row)
    rows.append([InlineKeyboardButton(text="🔄 Обновить", callback_data="menu:requests")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def request_access_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📨 Запросить доступ", callback_data="req:ask")]])


def approve_keyboard(uid: int, actor_is_owner: bool) -> InlineKeyboardMarkup:
    row = [InlineKeyboardButton(text="✅ Трейдер", callback_data=f"u:{uid}:trader")]
    if actor_is_owner:
        row.append(InlineKeyboardButton(text="🛠 Админ", callback_data=f"u:{uid}:admin"))
    row.append(InlineKeyboardButton(text="🚫 Отказать", callback_data=f"u:{uid}:deny"))
    return InlineKeyboardMarkup(inline_keyboard=[row])
