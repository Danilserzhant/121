"""aiogram handlers + hourly scheduler."""

from __future__ import annotations

import asyncio
import logging
import time

from aiogram import Bot, Dispatcher, Router, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import BotCommand, Message

from .config import Settings
from .exchanges import ExchangeError, interval_ms
from .formatting import HELP, format_settings, format_symbol, format_top
from .scanner import Scanner
from .storage import SubscriberStore

log = logging.getLogger(__name__)

router = Router()

# /set aliases -> Settings attribute, type, (min, max)
_SET_PARAMS: dict[str, tuple[str, type, tuple[float, float]]] = {
    "period": ("atr_period", int, (2, 200)),
    "период": ("atr_period", int, (2, 200)),
    "lookback": ("lookback", int, (1, 500)),
    "окно": ("lookback", int, (1, 500)),
    "top": ("top_n", int, (1, 50)),
    "топ": ("top_n", int, (1, 50)),
    "volume": ("min_quote_volume", float, (0, 1e12)),
    "оборот": ("min_quote_volume", float, (0, 1e12)),
    "atr": ("min_atr_pct", float, (0, 100)),
}


class Deps:
    """Runtime dependencies shared by handlers (injected via dispatcher workflow data)."""

    def __init__(self, settings: Settings, scanner: Scanner, store: SubscriberStore):
        self.settings = settings
        self.scanner = scanner
        self.store = store


def _is_admin(settings: Settings, message: Message) -> bool:
    if not settings.admin_ids:
        return True
    uid = message.from_user.id if message.from_user else None
    return uid in settings.admin_ids or message.chat.id in settings.admin_ids


@router.message(CommandStart())
@router.message(Command("help"))
async def cmd_start(message: Message) -> None:
    await message.answer(HELP)


@router.message(Command("top"))
async def cmd_top(message: Message, command: CommandObject, deps: Deps) -> None:
    n = deps.settings.top_n
    if command.args:
        try:
            n = max(1, min(50, int(command.args.strip())))
        except ValueError:
            await message.answer("Использование: <code>/top 20</code>")
            return
    status = await message.answer("⏳ Сканирую рынок…")
    try:
        result = await deps.scanner.scan()
    except ExchangeError as exc:
        log.exception("scan failed")
        await status.edit_text(f"❌ Ошибка биржи: <code>{exc}</code>")
        return
    await status.edit_text(format_top(result, n))


@router.message(Command("atr"))
async def cmd_atr(message: Message, command: CommandObject, deps: Deps) -> None:
    if not command.args:
        await message.answer("Использование: <code>/atr BTC</code> или <code>/atr BTCUSDT</code>")
        return
    symbol = command.args.split()[0]
    try:
        m = await deps.scanner.symbol_metrics(symbol)
    except ExchangeError as exc:
        await message.answer(f"❌ Ошибка биржи: <code>{exc}</code>")
        return
    if m is None:
        await message.answer(f"Не нашёл монету <code>{symbol.upper()}</code> на {deps.settings.exchange} или мало истории.")
        return
    await message.answer(format_symbol(m, deps.scanner.last, deps.settings.interval))


@router.message(Command("sub"))
async def cmd_sub(message: Message, deps: Deps) -> None:
    added = await deps.store.add(message.chat.id)
    if added:
        await message.answer("✅ Подписал. Буду присылать топ после закрытия каждой часовой свечи.")
    else:
        await message.answer("Уже подписан. Отключить — /unsub")


@router.message(Command("unsub"))
async def cmd_unsub(message: Message, deps: Deps) -> None:
    removed = await deps.store.remove(message.chat.id)
    await message.answer("🔕 Рассылка отключена." if removed else "Подписки и так не было.")


@router.message(Command("settings"))
async def cmd_settings(message: Message, deps: Deps) -> None:
    await message.answer(format_settings(deps.settings))


@router.message(Command("set"))
async def cmd_set(message: Message, command: CommandObject, deps: Deps) -> None:
    if not _is_admin(deps.settings, message):
        await message.answer("⛔ Менять настройки могут только администраторы.")
        return
    parts = (command.args or "").split()
    if len(parts) != 2 or parts[0].lower() not in _SET_PARAMS:
        await message.answer(
            "Использование: <code>/set параметр значение</code>\n"
            "Параметры: " + ", ".join(sorted(set(_SET_PARAMS)))
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
    # Invalidate caches so the next /top reflects new parameters.
    deps.scanner._last = None
    deps.scanner._symbols_cache = None
    await message.answer(f"✅ <code>{attr}</code> = <code>{value:g}</code>\n\n" + format_settings(deps.settings))


@router.message(F.text)
async def fallback(message: Message) -> None:
    if message.chat.type == "private":
        await message.answer("Не понял команду. Справка — /help")


async def hourly_scheduler(bot: Bot, deps: Deps) -> None:
    """After every candle close: scan and push the top list to all subscribers."""
    step = interval_ms(deps.settings.interval) / 1000
    while True:
        now = time.time()
        next_close = (now // step + 1) * step + deps.settings.close_delay
        log.info("next auto scan in %.0fs", next_close - now)
        await asyncio.sleep(next_close - now)
        chats = deps.store.chats
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
                await deps.store.remove(chat_id)
            except TelegramBadRequest as exc:
                log.warning("cannot send to %s: %s", chat_id, exc)
            await asyncio.sleep(0.05)


async def run_bot(settings: Settings) -> None:
    if not settings.bot_token:
        raise SystemExit("BOT_TOKEN is not set (put it in .env or environment)")
    bot = Bot(settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    await bot.set_my_commands(
        [
            BotCommand(command="top", description="Топ монет по расширению ATR"),
            BotCommand(command="atr", description="ATR по монете: /atr BTC"),
            BotCommand(command="sub", description="Авторассылка после закрытия часа"),
            BotCommand(command="unsub", description="Отключить рассылку"),
            BotCommand(command="settings", description="Параметры сканера"),
            BotCommand(command="help", description="Справка"),
        ]
    )
    async with Scanner(settings) as scanner:
        deps = Deps(settings, scanner, SubscriberStore(settings.storage_path))
        dp = Dispatcher()
        dp.include_router(router)
        dp["deps"] = deps
        task = asyncio.create_task(hourly_scheduler(bot, deps))
        try:
            log.info("bot started on %s (%s)", settings.exchange, settings.interval)
            await dp.start_polling(bot, allowed_updates=["message"])
        finally:
            task.cancel()
            await bot.session.close()
