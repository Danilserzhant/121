"""aiogram handlers, access control, menus, alerts and schedulers."""

from __future__ import annotations

import asyncio
import html
import logging
import re
import time
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware, Bot, Dispatcher, Router, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command, CommandObject, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    BotCommand, BotCommandScopeChat, BufferedInputFile, CallbackQuery, InputMediaPhoto, Message, ReplyKeyboardRemove,
    TelegramObject,
)

from . import keyboards as kb
from .charts import render_chart
from .config import Settings
from .exchanges import ExchangeError, interval_ms
from .formatting import (
    DIRECTION_TITLES, HELP, SORTS, VIEWS, format_breakouts, format_settings, format_symbol, format_top, format_watch_alert,
    format_watchlist, parse_amount, parse_corr_filter, parse_direction, parse_filter, parse_sort, parse_timeframe, set_tv_exchange,
    tf_name, welcome,
)
from .scanner import CORR_FILTERS, ScanResult, Scanner
from .storage import (
    ROLE_ADMIN, ROLE_OWNER, ROLE_TRADER, ROLE_TITLES, SUB_1D, SUB_1H, SUB_ALERTS, SUB_KINDS, SUB_TITLES, Store, User,
)

log = logging.getLogger(__name__)

router = Router()

PUBLIC_COMMANDS = {"start", "myid", "help"}
PUBLIC_CALLBACKS = ("req:ask",)
SYMBOL_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]{1,14}$")

# /set aliases -> Settings attribute, type, (min, max)
_SET_PARAMS: dict[str, tuple[str, type, tuple[float, float]]] = {
    "period": ("atr_period", int, (2, 200)),
    "период": ("atr_period", int, (2, 200)),
    "top": ("top_n", int, (1, 50)),
    "топ": ("top_n", int, (1, 50)),
    "volume": ("min_quote_volume", float, (0, 1e12)),
    "оборот": ("min_quote_volume", float, (0, 1e12)),
    "atr": ("min_atr_pct", float, (0, 100)),
    "выброс": ("alert_tr_ratio", float, (1, 20)),
    "breakout": ("alert_tr_ratio", float, (1, 20)),
    "watch": ("watch_tr_ratio", float, (1, 20)),
    "рост": ("watch_expansion_pct", float, (5, 1000)),
    "expansion": ("watch_expansion_pct", float, (5, 1000)),
}
_LOOKBACK_KEYS = ("окно", "lookback")


class Deps:
    """Runtime dependencies shared by handlers (injected via dispatcher workflow data)."""

    def __init__(self, settings: Settings, scanner: Scanner, store: Store):
        self.settings = settings
        self.scanner = scanner
        self.store = store
        # (user_id, symbol, kind) -> candle_time of the last alert, to avoid repeats
        self.alerted: dict[tuple[int, str, str], int] = {}
        # (unix ts, number of breakout coins) per hourly scan, for the daily digest
        self.breakout_log: list[tuple[float, int]] = []


class Ask(StatesGroup):
    symbol = State()      # waiting for a ticker to show the card
    watch = State()       # waiting for tickers to add to the watchlist


ADMIN_HELP = (
    "🛠 <b>Админка</b>\n"
    "👥 Пользователи — роли, кнопки «убрать / админ / трейдер»\n"
    "📨 Заявки — кто писал боту без доступа, одобрение кнопкой\n"
    "⚙️ Настройки — параметры сканера и алертов кнопками\n\n"
    "Текстом: /add_trader ID или @username, /del_trader, /add_admin, /del_admin, "
    "/set параметр значение, /users, /requests"
)


def _command_name(message: Message) -> str | None:
    if not message.text or not message.text.startswith("/"):
        return None
    return message.text.split()[0][1:].split("@")[0].lower()


async def _safe_edit(message: Message, text: str, reply_markup: Any = None) -> None:
    try:
        await message.edit_text(text, reply_markup=reply_markup)
    except TelegramBadRequest as exc:
        if "message is not modified" not in str(exc):
            raise


# ------------------------------------------------------------------ access

class AccessMiddleware(BaseMiddleware):
    """Remember every user, bootstrap the owner, and reject users without a role."""

    def __init__(self, deps: Deps):
        self.deps = deps

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not isinstance(event, (Message, CallbackQuery)) or event.from_user is None:
            return await handler(event, data)
        user = event.from_user
        store = self.deps.store
        await store.touch(user.id, user.username, user.full_name)
        message = event if isinstance(event, Message) else event.message

        # Bootstrap: OWNER_ID from config, otherwise the first person to write to a fresh bot.
        if not store.has_owner():
            owner_id = self.deps.settings.owner_id or user.id
            if owner_id == user.id:
                await store.set_role(user.id, ROLE_OWNER)
                await _set_menu(data["bot"], user.id, ADMIN_COMMANDS)
                log.info("owner bootstrapped: %s (%s)", user.id, user.username)
                if isinstance(message, Message):
                    await message.answer("👑 Вы назначены владельцем бота.", reply_markup=kb.main_menu(True))
        for admin_id in self.deps.settings.admin_ids:
            if store.role(admin_id) is None:
                await store.set_role(admin_id, ROLE_ADMIN, added_by=0)

        if store.has_access(user.id):
            return await handler(event, data)
        if isinstance(event, CallbackQuery):
            if event.data and event.data.startswith(PUBLIC_CALLBACKS):
                return await handler(event, data)
            await event.answer("⛔ Нет доступа", show_alert=True)
            return None
        cmd = _command_name(event)
        if cmd in PUBLIC_COMMANDS:
            return await handler(event, data)
        if cmd is not None or event.chat.type == "private":
            await event.answer(
                "⛔ У вас нет доступа к боту.\n"
                f"Ваш ID: <code>{user.id}</code> — отправьте его администратору или нажмите кнопку.",
                reply_markup=kb.request_access_keyboard(),
            )
        return None


# ------------------------------------------------------------------ start / help / menu

@router.message(CommandStart())
@router.message(Command("help", "menu"))
@router.message(F.text == kb.BTN_HELP)
async def cmd_start(message: Message, deps: Deps, state: FSMContext) -> None:
    await state.clear()
    uid = message.from_user.id
    role = deps.store.role(uid)
    if role is None:
        await message.answer(
            "🤖 <b>ATR Bot</b>\n\nДоступ выдаёт администратор.\n"
            f"Ваш ID: <code>{uid}</code>. Нажмите кнопку — админы получат заявку.",
            reply_markup=kb.request_access_keyboard(),
        )
        return
    is_admin = deps.store.is_admin(uid)
    menu = kb.main_menu(is_admin) if message.chat.type == "private" else None
    if _command_name(message) in ("start", "menu"):
        await message.answer(welcome(message.from_user.first_name or "трейдер", is_admin), reply_markup=menu)
        return
    text = HELP + ("\n\n" + ADMIN_HELP if is_admin else "")
    await message.answer(text, reply_markup=menu)


@router.message(Command("myid"))
async def cmd_myid(message: Message, deps: Deps) -> None:
    uid = message.from_user.id
    role = deps.store.role(uid)
    await message.answer(f"Ваш ID: <code>{uid}</code>\nРоль: <b>{ROLE_TITLES.get(role, 'нет доступа') if role else 'нет доступа'}</b>")


@router.callback_query(F.data == "req:ask")
async def cb_request_access(query: CallbackQuery, deps: Deps) -> None:
    user = query.from_user
    if deps.store.has_access(user.id):
        await query.answer("У вас уже есть доступ", show_alert=True)
        return
    admins = [u for u in deps.store.users.values() if u.role in (ROLE_OWNER, ROLE_ADMIN)]
    who = f"<code>{user.id}</code>" + (f" · @{html.escape(user.username)}" if user.username else "") + f" · {html.escape(user.full_name)}"
    sent = 0
    for admin in admins:
        try:
            await query.bot.send_message(admin.id, f"📨 <b>Заявка на доступ</b>\n{who}", reply_markup=kb.approve_keyboard(user.id, admin.role == ROLE_OWNER))
            sent += 1
        except (TelegramForbiddenError, TelegramBadRequest):
            continue
    await query.answer("Заявка отправлена, ждите ответа" if sent else "Админы недоступны, передайте свой ID вручную", show_alert=True)


@router.callback_query(F.data == "noop")
async def cb_noop(query: CallbackQuery) -> None:
    await query.answer()


@router.message(F.text == kb.BTN_CANCEL)
async def btn_cancel(message: Message, deps: Deps, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Отменено.", reply_markup=kb.main_menu(deps.store.is_admin(message.from_user.id)))


# ------------------------------------------------------------------ top / exp

class TopQuery:
    """Everything that defines one top view."""

    FIELDS = ("by", "interval", "n", "direction", "view", "min_volume", "min_cap", "corr")

    def __init__(self, settings: Settings, by: str = "atr"):
        self.by = by
        self.interval = settings.interval
        self.n = settings.top_n
        self.direction = "all"
        self.view = "list"
        self.min_volume = 0.0
        self.min_cap = 0.0
        self.corr = "any"

    def to_dict(self) -> dict:
        return {f: getattr(self, f) for f in self.FIELDS}

    @classmethod
    def from_dict(cls, settings: Settings, d: dict) -> "TopQuery":
        q = cls(settings, d.get("by", "atr"))
        for f in cls.FIELDS:
            if f in d:
                setattr(q, f, d[f])
        return q

    @classmethod
    def from_callback(cls, settings: Settings, parts: list[str]) -> "TopQuery | None":
        """parts = [by, interval, n, direction, view, vol_millions, cap_millions, corr]."""
        if len(parts) < 8:
            return None
        by, interval, n_s, direction, view, vol_s, cap_s, corr = parts[:8]
        if (interval not in settings.intervals or by not in SORTS or direction not in DIRECTION_TITLES
                or view not in VIEWS or not vol_s.isdigit() or not cap_s.isdigit() or corr not in CORR_FILTERS):
            return None
        q = cls(settings, by)
        q.interval, q.direction, q.view, q.corr = interval, direction, view, corr
        q.n = max(1, min(50, int(n_s))) if n_s.isdigit() else settings.top_n
        q.min_volume, q.min_cap = int(vol_s) * 1e6, int(cap_s) * 1e6
        return q


def _parse_top_args(args: str | None, settings: Settings, by: str) -> TopQuery | None:
    """'/top 4h 20 long vol 20m cap>1b' in any order. None on bad input."""
    q = TopQuery(settings, by)
    tokens = (args or "").split()
    i = 0
    while i < len(tokens):
        token = tokens[i]
        tf = parse_timeframe(token)
        d = parse_direction(token)
        srt = parse_sort(token)
        cf = parse_corr_filter(token)
        f = parse_filter(token)
        if tf is not None and tf in settings.intervals:
            q.interval = tf
        elif d is not None:
            q.direction = d
        elif cf is not None:
            q.corr = cf
        elif srt is not None:
            q.by = srt
        elif f is not None:
            kind, value = f
            if value is None:  # value in the next token
                value = parse_amount(tokens[i + 1]) if i + 1 < len(tokens) else None
                if value is None:
                    return None
                i += 1
            if kind == "vol":
                q.min_volume = value
            else:
                q.min_cap = value
        elif token.isdigit():
            q.n = max(1, min(50, int(token)))
        elif token.lower() in ("table", "таблица"):
            q.view = "table"
        else:
            return None
        i += 1
    return q


async def _scan_and_record(deps: Deps, interval: str, force: bool = False) -> ScanResult:
    result = await deps.scanner.scan(interval, force=force)
    if result.ranked:
        top_syms = [m.symbol for m in result.ranked[: deps.settings.history_top]]
        await deps.store.record_top(interval, result.candle_time, top_syms)
    return result


def _top_text(deps: Deps, result: ScanResult, q: TopQuery) -> str:
    rows = result.top(q.n, q.by, q.direction, q.min_volume, q.min_cap, q.corr)
    streaks = deps.store.streaks(result.interval, result.candle_time, [m.symbol for m in rows]) if rows else {}
    return format_top(result, q.n, q.by, q.direction, streaks, q.view, q.min_volume, q.min_cap, q.corr)


def _top_kb(deps: Deps, q: TopQuery):
    return kb.top_keyboard(deps.settings, q.by, q.interval, q.n, q.direction, q.view, q.min_volume, q.min_cap, q.corr)


async def show_top(message: Message, deps: Deps, q: TopQuery, edit: bool = False, force: bool = False) -> None:
    status = message if edit else await message.answer(f"⏳ Сканирую рынок · {tf_name(q.interval)}…")
    try:
        result = await _scan_and_record(deps, q.interval, force=force)
    except ExchangeError as exc:
        log.exception("scan failed")
        await _safe_edit(status, f"😕 Биржа не ответила: <code>{html.escape(str(exc)[:200])}</code>\nПопробуйте ещё раз через минуту.")
        return
    await _safe_edit(status, _top_text(deps, result, q), _top_kb(deps, q))


async def _send_top(message: Message, command: CommandObject, deps: Deps, by: str) -> None:
    q = _parse_top_args(command.args, deps.settings, by)
    if q is None:
        tfs = ", ".join(deps.settings.intervals)
        await message.answer(
            f"Использование: <code>/{command.command} [таймфрейм] [N] [long|short] [vol 20m] [cap 1b] [сами|вместе]</code>\n"
            f"Например <code>/{command.command} 4h 20 long cap 300m сами</code>. Таймфреймы: {tfs}"
        )
        return
    await show_top(message, deps, q)


@router.message(Command("top"))
async def cmd_top(message: Message, command: CommandObject, deps: Deps) -> None:
    await _send_top(message, command, deps, by="atr")


@router.message(Command("exp"))
async def cmd_exp(message: Message, command: CommandObject, deps: Deps) -> None:
    await _send_top(message, command, deps, by="expansion")


@router.message(Command("corr"))
async def cmd_corr(message: Message, command: CommandObject, deps: Deps) -> None:
    await _send_top(message, command, deps, by="corr")


@router.message(F.text == kb.BTN_TOP)
async def btn_top(message: Message, deps: Deps, state: FSMContext) -> None:
    await state.clear()
    await show_top(message, deps, TopQuery(deps.settings, "atr"))


@router.message(F.text == kb.BTN_EXP)
async def btn_exp(message: Message, deps: Deps, state: FSMContext) -> None:
    await state.clear()
    await show_top(message, deps, TopQuery(deps.settings, "expansion"))


@router.callback_query(F.data.startswith("top:"))
async def cb_top(query: CallbackQuery, deps: Deps) -> None:
    parts = query.data.split(":")
    q = TopQuery.from_callback(deps.settings, parts[1:9])
    if q is None:
        await query.answer()
        return
    refresh = len(parts) > 9 and parts[9] == "r"
    await query.answer("Обновляю…" if refresh else None)
    await show_top(query.message, deps, q, edit=True, force=refresh)


# ------------------------------------------------------------------ symbol card / chart

async def show_symbol(message: Message, deps: Deps, uid: int, symbol: str, edit: bool = False) -> None:
    status = message if edit else await message.answer("⏳ Считаю…")
    try:
        per_tf = await deps.scanner.symbol_metrics(symbol)
    except ExchangeError as exc:
        await _safe_edit(status, f"😕 Биржа не ответила: <code>{html.escape(str(exc)[:200])}</code>")
        return
    if per_tf is None:
        await _safe_edit(status, f"Не нашёл монету <code>{html.escape(symbol.upper())}</code> на {deps.settings.exchange}.")
        return
    name = deps.scanner.normalize_symbol(symbol)
    ranks: dict[str, tuple[int, int]] = {}
    for tf in per_tf:
        last = deps.scanner.last(tf)
        rank = last.rank_of(name) if last else None
        if last and rank:
            ranks[tf] = (rank, len(last.ranked))
    watched = name in deps.store.watchlist(uid)
    await _safe_edit(status, format_symbol(name, per_tf, ranks, watched), kb.symbol_keyboard(deps.settings, name, watched))


@router.message(Command("atr"))
async def cmd_atr(message: Message, command: CommandObject, deps: Deps) -> None:
    if not command.args:
        await message.answer("Использование: <code>/atr BTC</code> или <code>/atr BTCUSDT</code>")
        return
    await show_symbol(message, deps, message.from_user.id, command.args.split()[0])


@router.message(F.text == kb.BTN_SYMBOL)
async def btn_symbol(message: Message, state: FSMContext) -> None:
    await state.set_state(Ask.symbol)
    await message.answer("Введите тикер, например <code>SOL</code> или <code>BTCUSDT</code>:", reply_markup=kb.cancel_menu())


@router.message(StateFilter(Ask.symbol), F.text, ~F.text.in_(kb.MENU_BUTTONS))
async def ask_symbol_input(message: Message, deps: Deps, state: FSMContext) -> None:
    await state.clear()
    token = message.text.strip().split()[0]
    if not SYMBOL_RE.match(token):
        await message.answer("Это не похоже на тикер.", reply_markup=kb.main_menu(deps.store.is_admin(message.from_user.id)))
        return
    await message.answer("Ок", reply_markup=kb.main_menu(deps.store.is_admin(message.from_user.id)))
    await show_symbol(message, deps, message.from_user.id, token)


@router.callback_query(F.data.startswith("sym:"))
async def cb_symbol(query: CallbackQuery, deps: Deps) -> None:
    symbol = query.data.split(":", 1)[1]
    await query.answer()
    if query.message.photo:  # came from a chart: send a new card instead of editing the photo
        await show_symbol(query.message, deps, query.from_user.id, symbol)
    else:
        await show_symbol(query.message, deps, query.from_user.id, symbol, edit=True)


async def _chart_png(deps: Deps, symbol: str, interval: str) -> tuple[str, bytes] | None:
    candles = await deps.scanner.candles(symbol, interval, deps.settings.chart_candles)
    if candles is None:
        return None
    name = deps.scanner.normalize_symbol(symbol)
    png = await asyncio.get_running_loop().run_in_executor(None, render_chart, name, interval, candles, deps.settings.atr_period)
    return name, png


@router.message(Command("chart"))
async def cmd_chart(message: Message, command: CommandObject, deps: Deps) -> None:
    parts = (command.args or "").split()
    if not parts:
        await message.answer("Использование: <code>/chart SOL</code> или <code>/chart SOL 4h</code>")
        return
    symbol, interval = parts[0], deps.settings.interval
    if len(parts) > 1:
        tf = parse_timeframe(parts[1])
        if tf is None or tf not in deps.settings.intervals:
            await message.answer(f"Таймфреймы: {', '.join(deps.settings.intervals)}")
            return
        interval = tf
    status = await message.answer("⏳ Рисую…")
    try:
        res = await _chart_png(deps, symbol, interval)
    except ExchangeError as exc:
        await status.edit_text(f"😕 Биржа не ответила: <code>{html.escape(str(exc)[:200])}</code>")
        return
    if res is None:
        await status.edit_text(f"Не нашёл монету <code>{html.escape(symbol.upper())}</code>.")
        return
    name, png = res
    await status.delete()
    await message.answer_photo(
        BufferedInputFile(png, filename=f"{name}_{interval}.png"),
        caption=f"{name} · {tf_name(interval)} · ATR({deps.settings.atr_period})",
        reply_markup=kb.chart_keyboard(deps.settings, name, interval),
    )


@router.callback_query(F.data.startswith("chart:"))
async def cb_chart(query: CallbackQuery, deps: Deps) -> None:
    _, symbol, interval = query.data.split(":")
    if interval not in deps.settings.intervals:
        await query.answer()
        return
    await query.answer("Рисую…")
    try:
        res = await _chart_png(deps, symbol, interval)
    except ExchangeError as exc:
        await query.message.answer(f"😕 Биржа не ответила: <code>{html.escape(str(exc)[:200])}</code>")
        return
    if res is None:
        return
    name, png = res
    caption = f"{name} · {tf_name(interval)} · ATR({deps.settings.atr_period})"
    markup = kb.chart_keyboard(deps.settings, name, interval)
    file = BufferedInputFile(png, filename=f"{name}_{interval}.png")
    if query.message.photo:
        await query.message.edit_media(InputMediaPhoto(media=file, caption=caption), reply_markup=markup)
    else:
        await query.message.answer_photo(file, caption=caption, reply_markup=markup)


# ------------------------------------------------------------------ watchlist

async def show_watchlist(message: Message, deps: Deps, uid: int, edit: bool = False) -> None:
    symbols = deps.store.watchlist(uid)
    if not symbols:
        text, markup = format_watchlist([], {}, deps.settings.interval), kb.watchlist_keyboard([])
        if edit:
            await _safe_edit(message, text, markup)
        else:
            await message.answer(text, reply_markup=markup)
        return
    status = message if edit else await message.answer("⏳ Считаю…")
    try:
        metrics = await deps.scanner.metrics_for(symbols, deps.settings.interval)
    except ExchangeError as exc:
        await _safe_edit(status, f"😕 Биржа не ответила: <code>{html.escape(str(exc)[:200])}</code>")
        return
    await _safe_edit(status, format_watchlist(symbols, metrics, deps.settings.interval), kb.watchlist_keyboard(symbols))


async def _watch_add_many(bot: Bot, deps: Deps, uid: int, tokens: list[str]) -> str:
    added, unknown = [], []
    known = {i.symbol for i in await deps.scanner.exchange.list_symbols()}
    for p in tokens[:20]:
        sym = deps.scanner.normalize_symbol(p)
        if sym not in known:
            unknown.append(sym)
        elif await deps.store.watch_add(uid, sym):
            added.append(sym)
    text = ""
    if added:
        text += "✅ Добавил: " + ", ".join(added) + "\n"
    if unknown:
        text += "❓ Не нашёл на бирже: " + ", ".join(unknown) + "\n"
    if not added and not unknown:
        text = "Уже в списке.\n"
    return text + f"В списке {len(deps.store.watchlist(uid))} монет."


@router.message(Command("watch"))
async def cmd_watch(message: Message, command: CommandObject, deps: Deps) -> None:
    parts = (command.args or "").replace(",", " ").split()
    if not parts:
        await show_watchlist(message, deps, message.from_user.id)
        return
    try:
        text = await _watch_add_many(message.bot, deps, message.from_user.id, parts)
    except ExchangeError as exc:
        await message.answer(f"😕 Биржа не ответила: <code>{html.escape(str(exc)[:200])}</code>")
        return
    await message.answer(text)


@router.message(Command("unwatch"))
async def cmd_unwatch(message: Message, command: CommandObject, deps: Deps) -> None:
    parts = (command.args or "").replace(",", " ").split()
    uid = message.from_user.id
    if not parts:
        await message.answer("Использование: <code>/unwatch SOL</code> или <code>/unwatch all</code>")
        return
    if parts[0].lower() in ("all", "все", "всё"):
        removed = await deps.store.watch_remove(uid)
    else:
        removed = []
        for p in parts:
            removed += await deps.store.watch_remove(uid, deps.scanner.normalize_symbol(p))
    await message.answer("🗑 Убрал: " + ", ".join(removed) if removed else "Таких монет в списке нет.")


@router.message(Command("watchlist"))
@router.message(F.text == kb.BTN_WATCH)
async def cmd_watchlist(message: Message, deps: Deps, state: FSMContext) -> None:
    await state.clear()
    await show_watchlist(message, deps, message.from_user.id)


@router.callback_query(F.data.startswith("w:"))
async def cb_watch(query: CallbackQuery, deps: Deps, state: FSMContext) -> None:
    parts = query.data.split(":")
    action = parts[1]
    uid = query.from_user.id
    if action == "ask":
        await state.set_state(Ask.watch)
        await query.answer()
        await query.message.answer("Введите тикеры через пробел, например <code>SOL ETH DOGE</code>:", reply_markup=kb.cancel_menu())
        return
    if action == "refresh":
        await query.answer("Обновляю…")
        await show_watchlist(query.message, deps, uid, edit=True)
        return
    if action == "clear":
        await deps.store.watch_remove(uid)
        await query.answer("Список очищен")
        await show_watchlist(query.message, deps, uid, edit=True)
        return
    if action == "add" and len(parts) >= 3:
        sym = parts[2]
        added = await deps.store.watch_add(uid, sym)
        await query.answer(f"👀 Слежу за {sym}" if added else f"{sym} уже в списке")
        if not query.message.photo:
            await show_symbol(query.message, deps, uid, sym, edit=True)
        return
    if action == "rm" and len(parts) >= 3:
        sym = parts[2]
        origin = parts[3] if len(parts) > 3 else "list"
        removed = await deps.store.watch_remove(uid, sym)
        await query.answer(f"✖ Больше не слежу за {sym}" if removed else "Не было в списке")
        if origin == "sym":
            await show_symbol(query.message, deps, uid, sym, edit=True)
        else:
            await show_watchlist(query.message, deps, uid, edit=True)
        return
    await query.answer()


@router.message(StateFilter(Ask.watch), F.text, ~F.text.in_(kb.MENU_BUTTONS))
async def ask_watch_input(message: Message, deps: Deps, state: FSMContext) -> None:
    await state.clear()
    tokens = [t for t in message.text.replace(",", " ").split() if SYMBOL_RE.match(t)]
    menu = kb.main_menu(deps.store.is_admin(message.from_user.id))
    if not tokens:
        await message.answer("Не увидел тикеров.", reply_markup=menu)
        return
    try:
        text = await _watch_add_many(message.bot, deps, message.from_user.id, tokens)
    except ExchangeError as exc:
        await message.answer(f"😕 Биржа не ответила: <code>{html.escape(str(exc)[:200])}</code>", reply_markup=menu)
        return
    await message.answer(text, reply_markup=menu)
    await show_watchlist(message, deps, message.from_user.id)


# ------------------------------------------------------------------ subscriptions

def _parse_sub_kind(args: str | None) -> str | None:
    token = (args or "").strip().lower()
    if not token:
        return SUB_1H
    if token in ("alerts", "alert", "алерты", "алерт", "выброс"):
        return SUB_ALERTS
    tf = parse_timeframe(token)
    if tf == "1d":
        return SUB_1D
    if tf == "1h":
        return SUB_1H
    return None


def _subs_text(store: Store, chat_id: int) -> str:
    kinds = store.chat_subs(chat_id)
    body = "Подписок нет." if not kinds else "Подписки: " + ", ".join(SUB_TITLES[k] for k in SUB_KINDS if k in kinds)
    return (
        "🔔 <b>Рассылки в этот чат</b>\n" + body + "\n\n"
        "<i>Часовой топ — после закрытия каждой часовой свечи · Дневной — после 00:00 UTC · "
        "Алерты — монеты, у которых свеча вышла за старый ATR. Нажмите, чтобы включить или выключить.</i>"
    )


@router.message(Command("sub"))
async def cmd_sub(message: Message, command: CommandObject, deps: Deps) -> None:
    kind = _parse_sub_kind(command.args)
    if kind is None:
        await message.answer("Использование: <code>/sub</code> (часовой топ), <code>/sub 1d</code>, <code>/sub alerts</code>")
        return
    added = await deps.store.subscribe(message.chat.id, kind)
    prefix = "✅ Подписал: " if added else "Уже подписаны: "
    await message.answer(prefix + SUB_TITLES[kind] + ".\n\n" + _subs_text(deps.store, message.chat.id), reply_markup=kb.subs_keyboard(deps.store, message.chat.id, message.chat.type == "private"))


@router.message(Command("unsub"))
async def cmd_unsub(message: Message, command: CommandObject, deps: Deps) -> None:
    token = (command.args or "").strip()
    kind = _parse_sub_kind(token) if token else None
    if token and kind is None:
        await message.answer("Использование: <code>/unsub</code> (все), <code>/unsub 1h</code>, <code>/unsub 1d</code>, <code>/unsub alerts</code>")
        return
    removed = await deps.store.unsubscribe(message.chat.id, kind)
    prefix = ("🔕 Отключил: " + ", ".join(SUB_TITLES[k] for k in SUB_KINDS if k in removed) + ".\n\n") if removed else "Такой подписки не было.\n\n"
    await message.answer(prefix + _subs_text(deps.store, message.chat.id), reply_markup=kb.subs_keyboard(deps.store, message.chat.id, message.chat.type == "private"))


@router.message(Command("subs"))
@router.message(F.text == kb.BTN_SUBS)
async def cmd_subs(message: Message, deps: Deps, state: FSMContext) -> None:
    await state.clear()
    await message.answer(_subs_text(deps.store, message.chat.id), reply_markup=kb.subs_keyboard(deps.store, message.chat.id, message.chat.type == "private"))


@router.callback_query(F.data.startswith("sub:toggle:"))
async def cb_sub_toggle(query: CallbackQuery, deps: Deps) -> None:
    kind = query.data.split(":")[2]
    if kind not in SUB_KINDS:
        await query.answer()
        return
    chat_id = query.message.chat.id
    if kind in deps.store.chat_subs(chat_id):
        await deps.store.unsubscribe(chat_id, kind)
        await query.answer(f"🔕 {SUB_TITLES[kind]}: выкл")
    else:
        await deps.store.subscribe(chat_id, kind)
        await query.answer(f"✅ {SUB_TITLES[kind]}: вкл")
    await _safe_edit(query.message, _subs_text(deps.store, chat_id), kb.subs_keyboard(deps.store, chat_id, query.message.chat.type == "private"))


# ------------------------------------------------------------------ admin

async def _require_admin(message: Message, deps: Deps, owner_only: bool = False) -> bool:
    uid = message.from_user.id
    if owner_only and not deps.store.is_owner(uid):
        await message.answer("⛔ Это может делать только владелец бота.")
        return False
    if not deps.store.is_admin(uid):
        await message.answer("⛔ Команда доступна только администраторам.")
        return False
    return True


def _fmt_users(title: str, users: list[User]) -> str:
    if not users:
        return f"<b>{title}</b>: —"
    return f"<b>{title}</b> ({len(users)}):\n" + "\n".join(f"  • {u.label()}" for u in users)


def _users_text(store: Store) -> str:
    return "\n\n".join([
        _fmt_users("👑 Владелец", store.by_role(ROLE_OWNER)),
        _fmt_users("🛠 Админы", store.by_role(ROLE_ADMIN)),
        _fmt_users("📈 Трейдеры", store.by_role(ROLE_TRADER)),
        "🔔 Подписки: " + ", ".join(f"{SUB_TITLES[k]} — {len(store.subscribed(k))}" for k in SUB_KINDS),
        f"👀 Монет в вотчлистах: {len(store.all_watched())}",
    ])


def _requests_text(store: Store) -> str:
    pending = store.pending()[:30]
    if not pending:
        return "📨 Заявок нет: все, кто писал боту, уже имеют роль."
    lines = []
    for uid, info in pending:
        who = f"<code>{uid}</code>"
        if info.get("username"):
            who += f" · @{html.escape(info['username'])}"
        if info.get("name"):
            who += f" · {html.escape(info['name'])}"
        lines.append(f"  • {who}")
    return "📨 <b>Писали боту без доступа</b>:\n" + "\n".join(lines) + "\n\nОдобрить — кнопкой ниже или <code>/add_trader ID</code>"


@router.message(Command("admin"))
async def cmd_admin(message: Message, deps: Deps) -> None:
    if await _require_admin(message, deps):
        await message.answer(ADMIN_HELP)


@router.message(Command("users"))
@router.message(F.text == kb.BTN_USERS)
async def cmd_users(message: Message, deps: Deps, state: FSMContext) -> None:
    await state.clear()
    if not await _require_admin(message, deps):
        return
    await message.answer(_users_text(deps.store), reply_markup=kb.users_keyboard(deps.store, deps.store.is_owner(message.from_user.id)))


@router.message(Command("requests"))
@router.message(F.text == kb.BTN_REQUESTS)
async def cmd_requests(message: Message, deps: Deps, state: FSMContext) -> None:
    await state.clear()
    if not await _require_admin(message, deps):
        return
    await message.answer(_requests_text(deps.store), reply_markup=kb.requests_keyboard(deps.store, deps.store.is_owner(message.from_user.id)))


@router.callback_query(F.data.in_({"menu:users", "menu:requests"}))
async def cb_admin_menu(query: CallbackQuery, deps: Deps) -> None:
    if not deps.store.is_admin(query.from_user.id):
        await query.answer("⛔ Только для админов", show_alert=True)
        return
    await query.answer()
    is_owner = deps.store.is_owner(query.from_user.id)
    if query.data == "menu:users":
        await _safe_edit(query.message, _users_text(deps.store), kb.users_keyboard(deps.store, is_owner))
    else:
        await _safe_edit(query.message, _requests_text(deps.store), kb.requests_keyboard(deps.store, is_owner))


async def _set_menu(bot: Bot, user_id: int, commands: list[BotCommand]) -> None:
    try:
        await bot.set_my_commands(commands, scope=BotCommandScopeChat(chat_id=user_id))
    except TelegramBadRequest:
        pass  # private chat with the user does not exist yet


async def _notify(bot: Bot, user_id: int, text: str, reply_markup: Any = None) -> None:
    try:
        await bot.send_message(user_id, text, reply_markup=reply_markup)
    except (TelegramForbiddenError, TelegramBadRequest):
        pass  # user never started the bot or blocked it


async def apply_role(bot: Bot, deps: Deps, actor: int, target: int, action: str) -> str:
    """Shared by text commands and buttons. action: trader | admin | remove | deny. Returns a status line."""
    store = deps.store
    current = store.role(target)
    if current == ROLE_OWNER:
        return "Роль владельца изменить нельзя."
    is_owner = store.is_owner(actor)
    if action == "deny":
        return "Заявка отклонена (пользователь остаётся без доступа)."
    if action == "remove":
        if current is None:
            return "У этого пользователя и так нет доступа."
        if current == ROLE_ADMIN and not is_owner:
            return "⛔ Снять админа может только владелец."
        removed = await store.remove_user(target)
        await _set_menu(bot, target, USER_COMMANDS)
        await _notify(bot, target, "⛔ Ваш доступ к боту отозван.", ReplyKeyboardRemove())
        return f"🗑 Доступ отозван: {removed.label()}"
    role = ROLE_ADMIN if action == "admin" else ROLE_TRADER
    if role == ROLE_ADMIN and not is_owner:
        return "⛔ Назначать админов может только владелец."
    if current == ROLE_ADMIN and role == ROLE_TRADER and not is_owner:
        return "⛔ Понизить админа может только владелец."
    if current == role:
        return f"Пользователь уже {ROLE_TITLES[role]}."
    user = await store.set_role(target, role, added_by=actor)
    await _set_menu(bot, target, ADMIN_COMMANDS if role == ROLE_ADMIN else USER_COMMANDS)
    await _notify(
        bot, target,
        f"✅ Вам выдан доступ к боту, роль: <b>{ROLE_TITLES[role]}</b>. Справка — /help",
        kb.main_menu(role == ROLE_ADMIN),
    )
    return f"✅ {user.label()} — теперь <b>{ROLE_TITLES[role]}</b>."


@router.callback_query(F.data.startswith("u:"))
async def cb_user_action(query: CallbackQuery, deps: Deps) -> None:
    if not deps.store.is_admin(query.from_user.id):
        await query.answer("⛔ Только для админов", show_alert=True)
        return
    _, uid_s, action = query.data.split(":")
    if not uid_s.lstrip("-").isdigit() or action not in ("trader", "admin", "remove", "deny"):
        await query.answer()
        return
    result = await apply_role(query.bot, deps, query.from_user.id, int(uid_s), action)
    await query.answer(re.sub(r"<[^>]+>", "", result)[:180])
    is_owner = deps.store.is_owner(query.from_user.id)
    text = query.message.text or ""
    if text.startswith("📨 Заявка на доступ"):
        await _safe_edit(query.message, query.message.html_text + "\n\n" + result)
    elif text.startswith("📨"):
        await _safe_edit(query.message, _requests_text(deps.store), kb.requests_keyboard(deps.store, is_owner))
    else:
        await _safe_edit(query.message, _users_text(deps.store), kb.users_keyboard(deps.store, is_owner))


async def _change_role(message: Message, command: CommandObject, deps: Deps, action: str, owner_only: bool) -> None:
    if not await _require_admin(message, deps, owner_only=owner_only):
        return
    ref = (command.args or "").strip().split()
    if len(ref) != 1:
        await message.answer(f"Использование: <code>/{command.command} 123456789</code> или <code>/{command.command} @username</code>")
        return
    target = deps.store.resolve(ref[0])
    if target is None:
        await message.answer(
            f"Не знаю пользователя <code>{html.escape(ref[0])}</code>. "
            "Он должен сначала написать боту /start, либо укажите числовой ID (команда /myid)."
        )
        return
    await message.answer(await apply_role(message.bot, deps, message.from_user.id, target, action))


@router.message(Command("add_trader"))
async def cmd_add_trader(message: Message, command: CommandObject, deps: Deps) -> None:
    await _change_role(message, command, deps, "trader", owner_only=False)


@router.message(Command("del_trader"))
async def cmd_del_trader(message: Message, command: CommandObject, deps: Deps) -> None:
    await _change_role(message, command, deps, "remove", owner_only=False)


@router.message(Command("add_admin"))
async def cmd_add_admin(message: Message, command: CommandObject, deps: Deps) -> None:
    await _change_role(message, command, deps, "admin", owner_only=True)


@router.message(Command("del_admin"))
async def cmd_del_admin(message: Message, command: CommandObject, deps: Deps) -> None:
    await _change_role(message, command, deps, "remove", owner_only=True)


@router.message(Command("settings"))
@router.message(F.text == kb.BTN_SETTINGS)
async def cmd_settings(message: Message, deps: Deps, state: FSMContext) -> None:
    await state.clear()
    is_admin = deps.store.is_admin(message.from_user.id)
    await message.answer(format_settings(deps.settings), reply_markup=kb.settings_keyboard(deps.settings) if is_admin else None)


@router.callback_query(F.data.startswith("set:"))
async def cb_set(query: CallbackQuery, deps: Deps) -> None:
    if not deps.store.is_admin(query.from_user.id):
        await query.answer("⛔ Только для админов", show_alert=True)
        return
    _, attr, value_s = query.data.split(":")
    if attr not in kb.SETTING_CHOICES:
        await query.answer()
        return
    value = float(value_s)
    if attr in ("top_n", "atr_period"):
        value = int(value)
    setattr(deps.settings, attr, value)
    deps.scanner.invalidate()
    await query.answer(f"{kb.SETTING_CHOICES[attr][0]} = {value:g}")
    await _safe_edit(query.message, format_settings(deps.settings), kb.settings_keyboard(deps.settings))


@router.message(Command("set"))
async def cmd_set(message: Message, command: CommandObject, deps: Deps) -> None:
    if not await _require_admin(message, deps):
        return
    parts = (command.args or "").split()
    if parts and parts[0].lower() in _LOOKBACK_KEYS:
        if len(parts) == 2:
            parts = [parts[0], deps.settings.interval, parts[1]]
        tf = parse_timeframe(parts[1]) if len(parts) == 3 else None
        if tf is None or tf not in deps.settings.intervals or not parts[2].isdigit() or not 1 <= int(parts[2]) <= 500:
            await message.answer("Использование: <code>/set окно 4h 6</code> (окно 1…500 свечей)")
            return
        deps.settings.lookbacks[tf] = int(parts[2])
        deps.scanner.invalidate()
        await message.answer(f"✅ Окно сравнения для {tf_name(tf)} = {parts[2]} свечей\n\n" + format_settings(deps.settings), reply_markup=kb.settings_keyboard(deps.settings))
        return
    if len(parts) != 2 or parts[0].lower() not in _SET_PARAMS:
        await message.answer("Использование: <code>/set параметр значение</code>\nПараметры: " + ", ".join(sorted(set(_SET_PARAMS) | set(_LOOKBACK_KEYS))))
        return
    attr, typ, (lo, hi) = _SET_PARAMS[parts[0].lower()]
    try:
        value = typ(parts[1].replace(",", "."))
    except ValueError:
        await message.answer("Значение должно быть числом.")
        return
    if not lo <= value <= hi:
        await message.answer(f"Допустимый диапазон: {lo:g}…{hi:g}")
        return
    setattr(deps.settings, attr, value)
    deps.scanner.invalidate()
    await message.answer(f"✅ <code>{attr}</code> = <code>{value:g}</code>\n\n" + format_settings(deps.settings), reply_markup=kb.settings_keyboard(deps.settings))


# ------------------------------------------------------------------ plain text: ticker or unknown

@router.message(F.text)
async def fallback(message: Message, deps: Deps) -> None:
    text = message.text.strip()
    if message.chat.type == "private" and SYMBOL_RE.match(text):
        await show_symbol(message, deps, message.from_user.id, text)
        return
    if message.chat.type == "private":
        await message.answer("Не понял. Напишите тикер (например <code>SOL</code>) или выберите раздел в меню.", reply_markup=kb.main_menu(deps.store.is_admin(message.from_user.id)))


# ------------------------------------------------------------------ alerts & schedulers

async def _broadcast(bot: Bot, deps: Deps, chats: list[int], text: str, **kwargs: Any) -> None:
    for chat_id in chats:
        try:
            await bot.send_message(chat_id, text, **kwargs)
        except TelegramForbiddenError:
            log.info("chat %s blocked the bot, unsubscribing", chat_id)
            await deps.store.unsubscribe(chat_id)
        except TelegramBadRequest as exc:
            log.warning("cannot send to %s: %s", chat_id, exc)
        await asyncio.sleep(0.05)


async def _breakout_alerts(bot: Bot, deps: Deps, result: ScanResult) -> None:
    from .extras import send_alert

    s = deps.settings
    hits = [m for m in result.ranked if m.last_tr_ratio >= s.alert_tr_ratio and m.last_tr_pct >= s.alert_min_tr_pct]
    now = time.time()
    deps.breakout_log = [(t, n) for t, n in deps.breakout_log if now - t < 86_400] + [(now, len(hits))]
    chats = deps.store.subscribed(SUB_ALERTS)
    if not hits or not chats:
        return
    hits.sort(key=lambda m: m.last_tr_ratio, reverse=True)
    text = format_breakouts(hits[:15], result.interval, s.alert_tr_ratio)
    markup = kb.symbols_keyboard([m.symbol for m in hits[:6]])
    groups = [c for c in chats if c < 0]
    if groups:
        await _broadcast(bot, deps, groups, text, reply_markup=markup)
    for uid in (c for c in chats if c > 0):
        await send_alert(bot, deps, uid, "breakout", text, markup)


async def _watch_alerts(bot: Bot, deps: Deps, interval: str) -> None:
    s = deps.settings
    watched = sorted(deps.store.all_watched())
    if not watched:
        return
    metrics = await deps.scanner.metrics_for(watched, interval)
    step = interval_ms(interval)
    for uid, symbols in list(deps.store.watch.items()):
        for sym in symbols:
            m = metrics.get(sym)
            if m is None:
                continue
            reasons = []
            key_tr, key_exp = (uid, sym, "tr"), (uid, sym, "exp")
            if m.last_tr_ratio >= s.watch_tr_ratio and deps.alerted.get(key_tr) != m.candle_time:
                reasons.append(f"свеча {m.last_tr_pct:.1f}% — это {m.last_tr_ratio:.1f}× ATR (порог {s.watch_tr_ratio:g}×)")
                deps.alerted[key_tr] = m.candle_time
            if m.expansion_pct >= s.watch_expansion_pct and m.candle_time - deps.alerted.get(key_exp, 0) >= 6 * step:
                reasons.append(f"ATR вырос на {m.expansion_pct:+.0f}% за {s.lookback_for(interval)} свечей (порог {s.watch_expansion_pct:g}%)")
                deps.alerted[key_exp] = m.candle_time
            if reasons:
                from .extras import send_alert

                await send_alert(bot, deps, uid, "watch", format_watch_alert(m, interval, reasons), kb.symbol_keyboard(s, sym, True))
                await asyncio.sleep(0.05)


async def _after_close(bot: Bot, deps: Deps, interval: str, sub_kind: str) -> None:
    """Everything that happens once a candle of `interval` closes."""
    try:
        result = await _scan_and_record(deps, interval, force=True)
    except ExchangeError:
        log.exception("scheduled %s scan failed", interval)
        return
    chats = deps.store.subscribed(sub_kind)
    if chats:
        q = TopQuery(deps.settings, "atr")
        q.interval = interval
        await _broadcast(bot, deps, chats, _top_text(deps, result, q), reply_markup=_top_kb(deps, q))
    if interval == "1h":
        try:
            deps.scanner.record_oi(result.candle_time, await deps.scanner.derivatives(force=True))
            await deps.store.save()
        except Exception:  # noqa: BLE001
            log.exception("OI snapshot failed")
        await _breakout_alerts(bot, deps, result)
    try:
        await _watch_alerts(bot, deps, interval)
    except ExchangeError:
        log.exception("watch alerts on %s failed", interval)
    from .extras import send_alert

    for uid, p in deps.store.auto_presets(interval):
        q = TopQuery.from_dict(deps.settings, p)
        text = f"📁 <b>{html.escape(p['name'])}</b>\n" + _top_text(deps, result, q)
        await send_alert(bot, deps, uid, "preset", text, _top_kb(deps, q))


async def candle_scheduler(bot: Bot, deps: Deps, interval: str, sub_kind: str) -> None:
    step = interval_ms(interval) / 1000
    while True:
        now = time.time()
        next_close = (now // step + 1) * step + deps.settings.close_delay
        log.info("next %s close job in %.0fs", interval, next_close - now)
        await asyncio.sleep(next_close - now)
        try:
            await _after_close(bot, deps, interval, sub_kind)
        except Exception:  # noqa: BLE001 - keep the loop alive
            log.exception("%s close job crashed", interval)


USER_COMMANDS = [
    BotCommand(command="menu", description="Меню"),
    BotCommand(command="top", description="Топ по ATR%: /top, /top 4h, /top 1d long"),
    BotCommand(command="exp", description="Топ по росту ATR: /exp [тф] [N]"),
    BotCommand(command="corr", description="Кто ходит сам по себе: корреляция с BTC"),
    BotCommand(command="atr", description="Монета на всех таймфреймах: /atr BTC"),
    BotCommand(command="chart", description="График свечей и ATR: /chart BTC 4h"),
    BotCommand(command="watch", description="Следить за монетой: /watch SOL"),
    BotCommand(command="watchlist", description="Мои монеты"),
    BotCommand(command="unwatch", description="Перестать следить: /unwatch SOL"),
    BotCommand(command="overlap", description="Совпадения таймфреймов"),
    BotCommand(command="presets", description="Мои пресеты"),
    BotCommand(command="subs", description="Рассылки в этот чат"),
    BotCommand(command="quiet", description="Тихие часы, пояс, дайджест"),
    BotCommand(command="myid", description="Мой Telegram ID и роль"),
    BotCommand(command="help", description="Справка"),
]
ADMIN_COMMANDS = USER_COMMANDS + [
    BotCommand(command="users", description="Пользователи и роли"),
    BotCommand(command="requests", description="Заявки на доступ"),
    BotCommand(command="settings", description="Параметры сканера"),
]


async def run_bot(settings: Settings) -> None:
    if not settings.bot_token:
        raise SystemExit("BOT_TOKEN is not set (put it in .env or environment)")
    set_tv_exchange(settings.exchange, settings.tv_symbol)
    bot = Bot(settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML, link_preview_is_disabled=True))
    await bot.set_my_commands(USER_COMMANDS)
    store = Store(settings.storage_path)
    if settings.owner_id and store.role(settings.owner_id) is None:
        await store.set_role(settings.owner_id, ROLE_OWNER)
    for uid in store.users:
        if store.is_admin(uid):
            await _set_menu(bot, uid, ADMIN_COMMANDS)
    async with Scanner(settings) as scanner:
        from .extras import prefs_scheduler, router as extras_router

        scanner.oi_history = store.oi_history  # shared list: the store persists it
        deps = Deps(settings, scanner, store)
        dp = Dispatcher()
        dp.message.outer_middleware(AccessMiddleware(deps))
        dp.callback_query.outer_middleware(AccessMiddleware(deps))
        dp.include_router(extras_router)  # before the main router: its catch-all text handler must come last
        dp.include_router(router)
        dp["deps"] = deps
        tasks = [
            asyncio.create_task(candle_scheduler(bot, deps, "1h", SUB_1H)),
            asyncio.create_task(candle_scheduler(bot, deps, "1d", SUB_1D)),
            asyncio.create_task(prefs_scheduler(bot, deps)),
        ]
        try:
            log.info("bot started on %s, %d users", settings.exchange, len(store.users))
            await dp.start_polling(bot, allowed_updates=["message", "callback_query"])
        finally:
            for t in tasks:
                t.cancel()
            await bot.session.close()
