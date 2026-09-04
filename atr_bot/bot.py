"""aiogram handlers, access control and the hourly scheduler."""

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
from aiogram.types import BotCommand, BotCommandScopeChat, Message, TelegramObject

from .config import Settings
from .exchanges import ExchangeError, interval_ms
from .formatting import HELP, format_settings, format_symbol, format_top, parse_timeframe, tf_name
from .scanner import Scanner
from .storage import ROLE_ADMIN, ROLE_OWNER, ROLE_TRADER, ROLE_TITLES, Store, User

log = logging.getLogger(__name__)

router = Router()

# Commands that work without access.
PUBLIC_COMMANDS = {"start", "myid", "help"}

# /set aliases -> Settings attribute, type, (min, max)
_SET_PARAMS: dict[str, tuple[str, type, tuple[float, float]]] = {
    "period": ("atr_period", int, (2, 200)),
    "период": ("atr_period", int, (2, 200)),
    "lookback": ("lookbacks", int, (1, 500)),  # handled specially (per timeframe)
    "окно": ("lookbacks", int, (1, 500)),
    "top": ("top_n", int, (1, 50)),
    "топ": ("top_n", int, (1, 50)),
    "volume": ("min_quote_volume", float, (0, 1e12)),
    "оборот": ("min_quote_volume", float, (0, 1e12)),
    "atr": ("min_atr_pct", float, (0, 100)),
}


class Deps:
    """Runtime dependencies shared by handlers (injected via dispatcher workflow data)."""

    def __init__(self, settings: Settings, scanner: Scanner, store: Store):
        self.settings = settings
        self.scanner = scanner
        self.store = store


ADMIN_HELP = (
    "🛠 <b>Админка</b>\n"
    "/users — все пользователи и роли\n"
    "/requests — кто писал боту, но доступа не имеет\n"
    "/add_trader ID или @username — дать доступ трейдеру\n"
    "/del_trader ID или @username — забрать доступ\n"
    "/add_admin ID или @username — назначить админа (только владелец)\n"
    "/del_admin ID или @username — снять админа (только владелец)\n"
    "/settings и /set — параметры сканера\n\n"
    "<i>По @username можно добавить только того, кто уже писал боту (/start). "
    "Иначе — по ID, его пользователь узнает командой /myid.</i>"
)


def _user_of(message: Message):
    return message.from_user


def _command_name(message: Message) -> str | None:
    if not message.text or not message.text.startswith("/"):
        return None
    return message.text.split()[0][1:].split("@")[0].lower()


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
        message = event if isinstance(event, Message) else None
        if message is None or message.from_user is None:
            return await handler(event, data)
        user = message.from_user
        store = self.deps.store
        await store.touch(user.id, user.username, user.full_name)

        # Bootstrap: OWNER_ID from config, otherwise the first person to /start a fresh bot.
        if not store.has_owner():
            owner_id = self.deps.settings.owner_id or user.id
            if owner_id == user.id:
                await store.set_role(user.id, ROLE_OWNER)
                await _set_menu(message.bot, user.id, ADMIN_COMMANDS)
                log.info("owner bootstrapped: %s (%s)", user.id, user.username)
                await message.answer("👑 Вы назначены владельцем бота.")
        for admin_id in self.deps.settings.admin_ids:
            if store.role(admin_id) is None:
                await store.set_role(admin_id, ROLE_ADMIN, added_by=0)

        cmd = _command_name(message)
        if store.has_access(user.id) or cmd in PUBLIC_COMMANDS:
            return await handler(event, data)

        if cmd is not None or message.chat.type == "private":
            await message.answer(
                "⛔ У вас нет доступа к боту.\n"
                f"Ваш ID: <code>{user.id}</code> — отправьте его администратору."
            )
        return None


# ------------------------------------------------------------------ public

@router.message(CommandStart())
@router.message(Command("help"))
async def cmd_start(message: Message, deps: Deps) -> None:
    uid = _user_of(message).id
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
    uid = _user_of(message).id
    role = deps.store.role(uid)
    role_txt = ROLE_TITLES.get(role, "нет доступа") if role else "нет доступа"
    await message.answer(f"Ваш ID: <code>{uid}</code>\nРоль: <b>{role_txt}</b>")


# ------------------------------------------------------------------ traders

def _parse_top_args(args: str | None, settings: Settings) -> tuple[str, int] | None:
    """'/top 4h 20', '/top 20 4h', '/top d' -> (interval, n). None on bad input."""
    interval, n = settings.interval, settings.top_n
    for token in (args or "").split():
        tf = parse_timeframe(token)
        if tf is not None and tf in settings.intervals:
            interval = tf
        elif token.isdigit():
            n = max(1, min(50, int(token)))
        else:
            return None
    return interval, n


async def _send_top(message: Message, command: CommandObject, deps: Deps, by: str) -> None:
    parsed = _parse_top_args(command.args, deps.settings)
    if parsed is None:
        tfs = ", ".join(deps.settings.intervals)
        await message.answer(
            f"Использование: <code>/{command.command} [таймфрейм] [N]</code>\n"
            f"Например <code>/{command.command} 4h 20</code>. Таймфреймы: {tfs}"
        )
        return
    interval, n = parsed
    status = await message.answer(f"⏳ Сканирую рынок · {tf_name(interval)}…")
    try:
        result = await deps.scanner.scan(interval)
    except ExchangeError as exc:
        log.exception("scan failed")
        await status.edit_text(f"❌ Ошибка биржи: <code>{html.escape(str(exc))}</code>")
        return
    await status.edit_text(format_top(result, n, by))


@router.message(Command("top"))
async def cmd_top(message: Message, command: CommandObject, deps: Deps) -> None:
    await _send_top(message, command, deps, by="atr")


@router.message(Command("exp"))
async def cmd_exp(message: Message, command: CommandObject, deps: Deps) -> None:
    await _send_top(message, command, deps, by="expansion")


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
    await status.edit_text(format_symbol(name, per_tf, ranks))


@router.message(Command("sub"))
async def cmd_sub(message: Message, deps: Deps) -> None:
    added = await deps.store.subscribe(message.chat.id)
    if added:
        await message.answer("✅ Подписал. Буду присылать топ после закрытия каждой часовой свечи.")
    else:
        await message.answer("Уже подписан. Отключить — /unsub")


@router.message(Command("unsub"))
async def cmd_unsub(message: Message, deps: Deps) -> None:
    removed = await deps.store.unsubscribe(message.chat.id)
    await message.answer("🔕 Рассылка отключена." if removed else "Подписки и так не было.")


# ------------------------------------------------------------------ admin

async def _require_admin(message: Message, deps: Deps, owner_only: bool = False) -> bool:
    uid = _user_of(message).id
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
        f"🔔 Подписанных чатов: {len(s.chats)}",
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
    await message.answer(
        "<b>Писали боту без доступа</b>:\n" + "\n".join(lines)
        + "\n\nВыдать доступ: <code>/add_trader ID</code>"
    )


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
    actor = _user_of(message).id
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
    if len(parts) == 3 and parts[0].lower() in ("окно", "lookback"):
        tf = parse_timeframe(parts[1])
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
            "Параметры: " + ", ".join(sorted(set(_SET_PARAMS)))
        )
        return
    if parts[0].lower() in ("окно", "lookback"):
        parts = [parts[0], deps.settings.interval, parts[1]]
        return await cmd_set(message, CommandObject(prefix="/", command="set", args=" ".join(parts)), deps)
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


# ------------------------------------------------------------------ scheduler

async def hourly_scheduler(bot: Bot, deps: Deps) -> None:
    """After every candle close: scan and push the top list to all subscribed chats."""
    step = interval_ms(deps.settings.interval) / 1000
    while True:
        now = time.time()
        next_close = (now // step + 1) * step + deps.settings.close_delay
        log.info("next auto scan in %.0fs", next_close - now)
        await asyncio.sleep(next_close - now)
        chats = sorted(deps.store.chats)
        if not chats:
            continue
        try:
            result = await deps.scanner.scan(force=True)
        except ExchangeError:
            log.exception("scheduled scan failed")
            continue
        text = format_top(result, deps.settings.top_n)
        for chat_id in chats:
            try:
                await bot.send_message(chat_id, text)
            except TelegramForbiddenError:
                log.info("chat %s blocked the bot, unsubscribing", chat_id)
                await deps.store.unsubscribe(chat_id)
            except TelegramBadRequest as exc:
                log.warning("cannot send to %s: %s", chat_id, exc)
            await asyncio.sleep(0.05)


USER_COMMANDS = [
    BotCommand(command="top", description="Топ по ATR%: /top, /top 4h, /top 1d, /top 1w"),
    BotCommand(command="exp", description="Топ по росту ATR: /exp [тф] [N]"),
    BotCommand(command="atr", description="Монета на всех таймфреймах: /atr BTC"),
    BotCommand(command="sub", description="Авторассылка после закрытия часа"),
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
        dp.include_router(router)
        dp["deps"] = deps
        task = asyncio.create_task(hourly_scheduler(bot, deps))
        try:
            log.info("bot started on %s (%s), %d users", settings.exchange, settings.interval, len(store.users))
            await dp.start_polling(bot, allowed_updates=["message"])
        finally:
            task.cancel()
            await bot.session.close()
