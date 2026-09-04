"""aiogram handlers, access control, inline keyboards, alerts and schedulers."""

from __future__ import annotations

import asyncio
import html
import logging
import time
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware, Bot, Dispatcher, Router, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import (
    BotCommand, BotCommandScopeChat, BufferedInputFile, CallbackQuery, InlineKeyboardButton,
    InlineKeyboardMarkup, InputMediaPhoto, Message, TelegramObject,
)

from .charts import render_chart
from .config import Settings
from .exchanges import ExchangeError, interval_ms
from .formatting import (
    DIRECTION_TITLES, HELP, format_breakouts, format_settings, format_symbol, format_top, format_watch_alert,
    format_watchlist, parse_direction, parse_timeframe, tf_name,
)
from .indicators import AtrMetrics
from .scanner import ScanResult, Scanner
from .storage import (
    ROLE_ADMIN, ROLE_OWNER, ROLE_TRADER, ROLE_TITLES, SUB_1D, SUB_1H, SUB_ALERTS, SUB_KINDS, SUB_TITLES, Store, User,
)

log = logging.getLogger(__name__)

router = Router()

# Commands that work without access.
PUBLIC_COMMANDS = {"start", "myid", "help"}

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


ADMIN_HELP = (
    "🛠 <b>Админка</b>\n"
    "/users — все пользователи и роли\n"
    "/requests — кто писал боту, но доступа не имеет\n"
    "/add_trader ID или @username — дать доступ трейдеру\n"
    "/del_trader ID или @username — забрать доступ\n"
    "/add_admin ID или @username — назначить админа (только владелец)\n"
    "/del_admin ID или @username — снять админа (только владелец)\n"
    "/settings и /set — параметры сканера и алертов\n\n"
    "<i>По @username можно добавить только того, кто уже писал боту (/start). "
    "Иначе — по ID, его пользователь узнает командой /myid.</i>"
)


def _command_name(message: Message) -> str | None:
    if not message.text or not message.text.startswith("/"):
        return None
    return message.text.split()[0][1:].split("@")[0].lower()


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
                    await message.answer("👑 Вы назначены владельцем бота.")
        for admin_id in self.deps.settings.admin_ids:
            if store.role(admin_id) is None:
                await store.set_role(admin_id, ROLE_ADMIN, added_by=0)

        if store.has_access(user.id):
            return await handler(event, data)
        if isinstance(event, CallbackQuery):
            await event.answer("⛔ Нет доступа", show_alert=True)
            return None
        cmd = _command_name(event)
        if cmd in PUBLIC_COMMANDS:
            return await handler(event, data)
        if cmd is not None or event.chat.type == "private":
            await event.answer(
                "⛔ У вас нет доступа к боту.\n"
                f"Ваш ID: <code>{user.id}</code> — отправьте его администратору."
            )
        return None


# ------------------------------------------------------------------ public

@router.message(CommandStart())
@router.message(Command("help"))
async def cmd_start(message: Message, deps: Deps) -> None:
    uid = message.from_user.id
    role = deps.store.role(uid)
    if role is None:
        await message.answer(
            "🤖 <b>ATR Bot</b>\n\nДоступ выдаёт администратор.\n"
            f"Ваш ID: <code>{uid}</code> — отправьте его администратору, чтобы получить доступ."
        )
        return
    text = HELP
    if deps.store.is_admin(uid):
        text += "\n\n" + ADMIN_HELP
    await message.answer(text)


@router.message(Command("myid"))
async def cmd_myid(message: Message, deps: Deps) -> None:
    uid = message.from_user.id
    role = deps.store.role(uid)
    await message.answer(f"Ваш ID: <code>{uid}</code>\nРоль: <b>{ROLE_TITLES.get(role, 'нет доступа') if role else 'нет доступа'}</b>")


# ------------------------------------------------------------------ top / exp

def _parse_top_args(args: str | None, settings: Settings) -> tuple[str, int, str] | None:
    """'/top 4h 20 long' in any order -> (interval, n, direction). None on bad input."""
    interval, n, direction = settings.interval, settings.top_n, "all"
    for token in (args or "").split():
        tf = parse_timeframe(token)
        d = parse_direction(token)
        if tf is not None and tf in settings.intervals:
            interval = tf
        elif d is not None:
            direction = d
        elif token.isdigit():
            n = max(1, min(50, int(token)))
        else:
            return None
    return interval, n, direction


def _top_keyboard(settings: Settings, by: str, interval: str, n: int, direction: str) -> InlineKeyboardMarkup:
    def cb(by_=by, tf=interval, n_=n, d=direction) -> str:
        return f"top:{by_}:{tf}:{n_}:{d}"

    tf_row = [
        InlineKeyboardButton(text=("· " if tf == interval else "") + tf_name(tf), callback_data=cb(tf=tf))
        for tf in settings.intervals
    ]
    mode_row = [
        InlineKeyboardButton(text=("· " if by == "atr" else "") + "ATR%", callback_data=cb(by_="atr")),
        InlineKeyboardButton(text=("· " if by == "expansion" else "") + "ΔATR", callback_data=cb(by_="expansion")),
        InlineKeyboardButton(text=("· " if direction == "long" else "") + "🟢 Long", callback_data=cb(d="long")),
        InlineKeyboardButton(text=("· " if direction == "short" else "") + "🔴 Short", callback_data=cb(d="short")),
        InlineKeyboardButton(text=("· " if direction == "all" else "") + "Все", callback_data=cb(d="all")),
    ]
    action_row = [
        InlineKeyboardButton(text=f"{'· ' if n == 10 else ''}10", callback_data=cb(n_=10)),
        InlineKeyboardButton(text=f"{'· ' if n == 20 else ''}20", callback_data=cb(n_=20)),
        InlineKeyboardButton(text=f"{'· ' if n == 30 else ''}30", callback_data=cb(n_=30)),
        InlineKeyboardButton(text="🔄 Обновить", callback_data=cb() + ":r"),
    ]
    return InlineKeyboardMarkup(inline_keyboard=[tf_row, mode_row, action_row])


async def _scan_and_record(deps: Deps, interval: str, force: bool = False) -> ScanResult:
    result = await deps.scanner.scan(interval, force=force)
    if result.ranked:
        top_syms = [m.symbol for m in result.ranked[: deps.settings.history_top]]
        await deps.store.record_top(interval, result.candle_time, top_syms)
    return result


def _top_text(deps: Deps, result: ScanResult, n: int, by: str, direction: str) -> str:
    rows = result.top(n, by, direction)
    streaks = deps.store.streaks(result.interval, result.candle_time, [m.symbol for m in rows]) if rows else {}
    return format_top(result, n, by, direction, streaks)


async def _send_top(message: Message, command: CommandObject, deps: Deps, by: str) -> None:
    parsed = _parse_top_args(command.args, deps.settings)
    if parsed is None:
        tfs = ", ".join(deps.settings.intervals)
        await message.answer(
            f"Использование: <code>/{command.command} [таймфрейм] [N] [long|short]</code>\n"
            f"Например <code>/{command.command} 4h 20 long</code>. Таймфреймы: {tfs}"
        )
        return
    interval, n, direction = parsed
    status = await message.answer(f"⏳ Сканирую рынок · {tf_name(interval)}…")
    try:
        result = await _scan_and_record(deps, interval)
    except ExchangeError as exc:
        log.exception("scan failed")
        await status.edit_text(f"❌ Ошибка биржи: <code>{html.escape(str(exc))}</code>")
        return
    await status.edit_text(_top_text(deps, result, n, by, direction), reply_markup=_top_keyboard(deps.settings, by, interval, n, direction))


@router.message(Command("top"))
async def cmd_top(message: Message, command: CommandObject, deps: Deps) -> None:
    await _send_top(message, command, deps, by="atr")


@router.message(Command("exp"))
async def cmd_exp(message: Message, command: CommandObject, deps: Deps) -> None:
    await _send_top(message, command, deps, by="expansion")


@router.callback_query(F.data.startswith("top:"))
async def cb_top(query: CallbackQuery, deps: Deps) -> None:
    parts = query.data.split(":")
    if len(parts) < 5:
        await query.answer()
        return
    _, by, interval, n_s, direction = parts[:5]
    refresh = len(parts) > 5 and parts[5] == "r"
    if interval not in deps.settings.intervals or by not in ("atr", "expansion") or direction not in DIRECTION_TITLES:
        await query.answer()
        return
    n = max(1, min(50, int(n_s))) if n_s.isdigit() else deps.settings.top_n
    await query.answer("Обновляю…" if refresh else None)
    try:
        result = await _scan_and_record(deps, interval, force=refresh)
    except ExchangeError as exc:
        await query.message.answer(f"❌ Ошибка биржи: <code>{html.escape(str(exc))}</code>")
        return
    try:
        await query.message.edit_text(
            _top_text(deps, result, n, by, direction),
            reply_markup=_top_keyboard(deps.settings, by, interval, n, direction),
        )
    except TelegramBadRequest as exc:
        if "message is not modified" not in str(exc):
            raise
        await query.answer("Без изменений")


# ------------------------------------------------------------------ symbol / chart

@router.message(Command("atr"))
async def cmd_atr(message: Message, command: CommandObject, deps: Deps) -> None:
    if not command.args:
        await message.answer("Использование: <code>/atr BTC</code> или <code>/atr BTCUSDT</code>")
        return
    symbol = command.args.split()[0]
    status = await message.answer("⏳ Считаю…")
    try:
        per_tf = await deps.scanner.symbol_metrics(symbol)
    except ExchangeError as exc:
        await status.edit_text(f"❌ Ошибка биржи: <code>{html.escape(str(exc))}</code>")
        return
    if per_tf is None:
        await status.edit_text(f"Не нашёл монету <code>{html.escape(symbol.upper())}</code> на {deps.settings.exchange}.")
        return
    name = deps.scanner.normalize_symbol(symbol)
    ranks: dict[str, tuple[int, int]] = {}
    for tf in per_tf:
        last = deps.scanner.last(tf)
        rank = last.rank_of(name) if last else None
        if last and rank:
            ranks[tf] = (rank, len(last.ranked))
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=f"📈 {tf_name(tf)}", callback_data=f"chart:{name}:{tf}") for tf in deps.settings.intervals
    ]])
    await status.edit_text(format_symbol(name, per_tf, ranks), reply_markup=kb)


def _chart_keyboard(settings: Settings, symbol: str, interval: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=("· " if tf == interval else "") + tf_name(tf), callback_data=f"chart:{symbol}:{tf}")
        for tf in settings.intervals
    ]])


async def _chart_png(deps: Deps, symbol: str, interval: str) -> tuple[str, bytes] | None:
    candles = await deps.scanner.candles(symbol, interval, deps.settings.chart_candles)
    if candles is None:
        return None
    name = deps.scanner.normalize_symbol(symbol)
    png = await asyncio.get_running_loop().run_in_executor(
        None, render_chart, name, interval, candles, deps.settings.atr_period
    )
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
        await status.edit_text(f"❌ Ошибка биржи: <code>{html.escape(str(exc))}</code>")
        return
    if res is None:
        await status.edit_text(f"Не нашёл монету <code>{html.escape(symbol.upper())}</code>.")
        return
    name, png = res
    await status.delete()
    await message.answer_photo(
        BufferedInputFile(png, filename=f"{name}_{interval}.png"),
        caption=f"{name} · {tf_name(interval)} · ATR({deps.settings.atr_period})",
        reply_markup=_chart_keyboard(deps.settings, name, interval),
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
        await query.message.answer(f"❌ Ошибка биржи: <code>{html.escape(str(exc))}</code>")
        return
    if res is None:
        return
    name, png = res
    media = InputMediaPhoto(
        media=BufferedInputFile(png, filename=f"{name}_{interval}.png"),
        caption=f"{name} · {tf_name(interval)} · ATR({deps.settings.atr_period})",
    )
    kb = _chart_keyboard(deps.settings, name, interval)
    if query.message.photo:
        await query.message.edit_media(media, reply_markup=kb)
    else:
        await query.message.answer_photo(media.media, caption=media.caption, reply_markup=kb)


# ------------------------------------------------------------------ watchlist

@router.message(Command("watch"))
async def cmd_watch(message: Message, command: CommandObject, deps: Deps) -> None:
    parts = (command.args or "").replace(",", " ").split()
    if not parts:
        await cmd_watchlist(message, deps)
        return
    uid = message.from_user.id
    added, unknown = [], []
    try:
        known = {i.symbol for i in await deps.scanner.exchange.list_symbols()}
    except ExchangeError as exc:
        await message.answer(f"❌ Ошибка биржи: <code>{html.escape(str(exc))}</code>")
        return
    for p in parts[:20]:
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
    text += f"В списке {len(deps.store.watchlist(uid))} монет. Показать: /watchlist"
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
async def cmd_watchlist(message: Message, deps: Deps) -> None:
    uid = message.from_user.id
    symbols = deps.store.watchlist(uid)
    if not symbols:
        await message.answer(format_watchlist([], {}, deps.settings.interval))
        return
    status = await message.answer("⏳ Считаю…")
    try:
        metrics = await deps.scanner.metrics_for(symbols, deps.settings.interval)
    except ExchangeError as exc:
        await status.edit_text(f"❌ Ошибка биржи: <code>{html.escape(str(exc))}</code>")
        return
    await status.edit_text(format_watchlist(symbols, metrics, deps.settings.interval))


# ------------------------------------------------------------------ subscriptions

def _parse_sub_kind(args: str | None) -> str | None:
    """None = default hourly; 'alerts'/'1d'/'1h' otherwise; '?' on garbage."""
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
    if not kinds:
        return "Подписок нет."
    return "Подписки: " + ", ".join(SUB_TITLES[k] for k in SUB_KINDS if k in kinds)


@router.message(Command("sub"))
async def cmd_sub(message: Message, command: CommandObject, deps: Deps) -> None:
    kind = _parse_sub_kind(command.args)
    if kind is None:
        await message.answer("Использование: <code>/sub</code> (часовой топ), <code>/sub 1d</code>, <code>/sub alerts</code>")
        return
    added = await deps.store.subscribe(message.chat.id, kind)
    prefix = "✅ Подписал: " if added else "Уже подписаны: "
    await message.answer(prefix + SUB_TITLES[kind] + ".\n" + _subs_text(deps.store, message.chat.id))


@router.message(Command("unsub"))
async def cmd_unsub(message: Message, command: CommandObject, deps: Deps) -> None:
    token = (command.args or "").strip()
    kind = _parse_sub_kind(token) if token else None
    if token and kind is None:
        await message.answer("Использование: <code>/unsub</code> (все), <code>/unsub 1h</code>, <code>/unsub 1d</code>, <code>/unsub alerts</code>")
        return
    removed = await deps.store.unsubscribe(message.chat.id, kind)
    if removed:
        await message.answer("🔕 Отключил: " + ", ".join(SUB_TITLES[k] for k in SUB_KINDS if k in removed) + ".\n" + _subs_text(deps.store, message.chat.id))
    else:
        await message.answer("Такой подписки не было.\n" + _subs_text(deps.store, message.chat.id))


@router.message(Command("subs"))
async def cmd_subs(message: Message, deps: Deps) -> None:
    await message.answer(_subs_text(deps.store, message.chat.id))


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


@router.message(Command("admin"))
async def cmd_admin(message: Message, deps: Deps) -> None:
    if await _require_admin(message, deps):
        await message.answer(ADMIN_HELP)


@router.message(Command("users"))
async def cmd_users(message: Message, deps: Deps) -> None:
    if not await _require_admin(message, deps):
        return
    s = deps.store
    text = "\n\n".join([
        _fmt_users("👑 Владелец", s.by_role(ROLE_OWNER)),
        _fmt_users("🛠 Админы", s.by_role(ROLE_ADMIN)),
        _fmt_users("📈 Трейдеры", s.by_role(ROLE_TRADER)),
        "🔔 Подписки: " + ", ".join(f"{SUB_TITLES[k]} — {len(s.subscribed(k))}" for k in SUB_KINDS),
        f"👀 Монет в вотчлистах: {len(s.all_watched())}",
    ])
    await message.answer(text)


@router.message(Command("requests"))
async def cmd_requests(message: Message, deps: Deps) -> None:
    if not await _require_admin(message, deps):
        return
    pending = deps.store.pending()[:30]
    if not pending:
        await message.answer("Заявок нет: все, кто писал боту, уже имеют роль.")
        return
    lines = []
    for uid, info in pending:
        who = f"<code>{uid}</code>"
        if info.get("username"):
            who += f" · @{html.escape(info['username'])}"
        if info.get("name"):
            who += f" · {html.escape(info['name'])}"
        lines.append(f"  • {who}")
    await message.answer("<b>Писали боту без доступа</b>:\n" + "\n".join(lines) + "\n\nВыдать доступ: <code>/add_trader ID</code>")


async def _set_menu(bot: Bot, user_id: int, commands: list[BotCommand]) -> None:
    try:
        await bot.set_my_commands(commands, scope=BotCommandScopeChat(chat_id=user_id))
    except TelegramBadRequest:
        pass  # private chat with the user does not exist yet


async def _notify(bot: Bot, user_id: int, text: str) -> None:
    try:
        await bot.send_message(user_id, text)
    except (TelegramForbiddenError, TelegramBadRequest):
        pass  # user never started the bot or blocked it


async def _change_role(message: Message, command: CommandObject, deps: Deps, role: str | None, owner_only: bool) -> None:
    """role=None removes the user."""
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
    actor = message.from_user.id
    current = deps.store.role(target)
    if current == ROLE_OWNER:
        await message.answer("Роль владельца изменить нельзя.")
        return
    if role is None:
        if current is None:
            await message.answer("У этого пользователя и так нет доступа.")
            return
        if current == ROLE_ADMIN and not deps.store.is_owner(actor):
            await message.answer("⛔ Снять админа может только владелец.")
            return
        removed = await deps.store.remove_user(target)
        await message.answer(f"🗑 Доступ отозван: {removed.label()}")
        await _notify(message.bot, target, "⛔ Ваш доступ к боту отозван.")
        return
    if current == ROLE_ADMIN and role == ROLE_TRADER and not deps.store.is_owner(actor):
        await message.answer("⛔ Понизить админа может только владелец.")
        return
    if current == role:
        await message.answer(f"Пользователь уже {ROLE_TITLES[role]}.")
        return
    user = await deps.store.set_role(target, role, added_by=actor)
    await _set_menu(message.bot, target, ADMIN_COMMANDS if role == ROLE_ADMIN else USER_COMMANDS)
    await message.answer(f"✅ {user.label()} — теперь <b>{ROLE_TITLES[role]}</b>.")
    await _notify(message.bot, target, f"✅ Вам выдан доступ к боту, роль: <b>{ROLE_TITLES[role]}</b>. Справка — /help")


@router.message(Command("add_trader"))
async def cmd_add_trader(message: Message, command: CommandObject, deps: Deps) -> None:
    await _change_role(message, command, deps, ROLE_TRADER, owner_only=False)


@router.message(Command("del_trader"))
async def cmd_del_trader(message: Message, command: CommandObject, deps: Deps) -> None:
    await _change_role(message, command, deps, None, owner_only=False)


@router.message(Command("add_admin"))
async def cmd_add_admin(message: Message, command: CommandObject, deps: Deps) -> None:
    await _change_role(message, command, deps, ROLE_ADMIN, owner_only=True)


@router.message(Command("del_admin"))
async def cmd_del_admin(message: Message, command: CommandObject, deps: Deps) -> None:
    await _change_role(message, command, deps, None, owner_only=True)


@router.message(Command("settings"))
async def cmd_settings(message: Message, deps: Deps) -> None:
    await message.answer(format_settings(deps.settings))


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
        await message.answer(f"✅ Окно сравнения для {tf_name(tf)} = {parts[2]} свечей\n\n" + format_settings(deps.settings))
        return
    if len(parts) != 2 or parts[0].lower() not in _SET_PARAMS:
        await message.answer(
            "Использование: <code>/set параметр значение</code>\n"
            "Параметры: " + ", ".join(sorted(set(_SET_PARAMS) | set(_LOOKBACK_KEYS)))
        )
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
    await message.answer(f"✅ <code>{attr}</code> = <code>{value:g}</code>\n\n" + format_settings(deps.settings))


@router.message(F.text)
async def fallback(message: Message) -> None:
    if message.chat.type == "private":
        await message.answer("Не понял команду. Справка — /help")


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
    chats = deps.store.subscribed(SUB_ALERTS)
    if not chats:
        return
    s = deps.settings
    hits = [
        m for m in result.ranked
        if m.last_tr_ratio >= s.alert_tr_ratio and m.last_tr_pct >= s.alert_min_tr_pct
    ]
    if not hits:
        return
    hits.sort(key=lambda m: m.last_tr_ratio, reverse=True)
    await _broadcast(bot, deps, chats, format_breakouts(hits[:15], result.interval, s.alert_tr_ratio))


async def _watch_alerts(bot: Bot, deps: Deps, interval: str) -> None:
    s = deps.settings
    watched = sorted(deps.store.all_watched())
    if not watched:
        return
    metrics = await deps.scanner.metrics_for(watched, interval)
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
            step = interval_ms(interval)
            last_exp = deps.alerted.get(key_exp, 0)
            if m.expansion_pct >= s.watch_expansion_pct and m.candle_time - last_exp >= 6 * step:
                reasons.append(f"ATR вырос на {m.expansion_pct:+.0f}% за {s.lookback_for(interval)} свечей (порог {s.watch_expansion_pct:g}%)")
                deps.alerted[key_exp] = m.candle_time
            if reasons:
                try:
                    await bot.send_message(uid, format_watch_alert(m, interval, reasons))
                except (TelegramForbiddenError, TelegramBadRequest) as exc:
                    log.warning("watch alert to %s failed: %s", uid, exc)
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
        text = _top_text(deps, result, deps.settings.top_n, "atr", "all")
        await _broadcast(bot, deps, chats, text, reply_markup=_top_keyboard(deps.settings, "atr", interval, deps.settings.top_n, "all"))
    if interval == "1h":
        await _breakout_alerts(bot, deps, result)
    try:
        await _watch_alerts(bot, deps, interval)
    except ExchangeError:
        log.exception("watch alerts on %s failed", interval)


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
    BotCommand(command="top", description="Топ по ATR%: /top, /top 4h, /top 1d long"),
    BotCommand(command="exp", description="Топ по росту ATR: /exp [тф] [N]"),
    BotCommand(command="atr", description="Монета на всех таймфреймах: /atr BTC"),
    BotCommand(command="chart", description="График свечей и ATR: /chart BTC 4h"),
    BotCommand(command="watch", description="Следить за монетой: /watch SOL"),
    BotCommand(command="watchlist", description="Мои монеты"),
    BotCommand(command="unwatch", description="Перестать следить: /unwatch SOL"),
    BotCommand(command="sub", description="Рассылка: /sub, /sub 1d, /sub alerts"),
    BotCommand(command="unsub", description="Отключить рассылку"),
    BotCommand(command="myid", description="Мой Telegram ID и роль"),
    BotCommand(command="help", description="Справка"),
]
ADMIN_COMMANDS = USER_COMMANDS + [
    BotCommand(command="admin", description="Админка"),
    BotCommand(command="users", description="Пользователи и роли"),
    BotCommand(command="requests", description="Кто просит доступ"),
    BotCommand(command="add_trader", description="Дать доступ трейдеру"),
    BotCommand(command="del_trader", description="Забрать доступ"),
    BotCommand(command="settings", description="Параметры сканера"),
]


async def run_bot(settings: Settings) -> None:
    if not settings.bot_token:
        raise SystemExit("BOT_TOKEN is not set (put it in .env or environment)")
    bot = Bot(settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    await bot.set_my_commands(USER_COMMANDS)
    store = Store(settings.storage_path)
    if settings.owner_id and store.role(settings.owner_id) is None:
        await store.set_role(settings.owner_id, ROLE_OWNER)
    for uid in store.users:
        if store.is_admin(uid):
            await _set_menu(bot, uid, ADMIN_COMMANDS)
    async with Scanner(settings) as scanner:
        deps = Deps(settings, scanner, store)
        dp = Dispatcher()
        dp.message.outer_middleware(AccessMiddleware(deps))
        dp.callback_query.outer_middleware(AccessMiddleware(deps))
        dp.include_router(router)
        dp["deps"] = deps
        tasks = [
            asyncio.create_task(candle_scheduler(bot, deps, "1h", SUB_1H)),
            asyncio.create_task(candle_scheduler(bot, deps, "1d", SUB_1D)),
        ]
        try:
            log.info("bot started on %s, %d users", settings.exchange, len(store.users))
            await dp.start_polling(bot, allowed_updates=["message", "callback_query"])
        finally:
            for t in tasks:
                t.cancel()
            await bot.session.close()
