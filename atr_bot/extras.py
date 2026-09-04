"""Overlap view, presets, quiet hours, daily digest and quiet-aware alert delivery."""

from __future__ import annotations

import asyncio
import html
import logging
import time
from datetime import datetime, timedelta, timezone

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command, CommandObject, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from . import keyboards as kb
from .bot import Deps, TopQuery, _parse_top_args, _safe_edit, _scan_and_record, _top_kb, _top_text, show_top
from .exchanges import ExchangeError
from .formatting import (
    _arrow, _sign, format_digest, format_overlap, format_presets, format_prefs, format_queued, parse_timeframe, tf_name,
)
from .indicators import AtrMetrics

log = logging.getLogger(__name__)
router = Router()

OVERLAP_INTERVALS = ["1h", "4h", "1d"]


class AskPreset(StatesGroup):
    name = State()


# ------------------------------------------------------------------ quiet-aware delivery

def local_now(prefs: dict) -> datetime:
    return datetime.now(tz=timezone.utc) + timedelta(hours=prefs["tz"])


def in_quiet(prefs: dict, now: datetime | None = None) -> bool:
    if not prefs["quiet_on"]:
        return False
    h = (now or local_now(prefs)).hour
    start, end = prefs["quiet_start"] % 24, prefs["quiet_end"] % 24
    if start == end:
        return False
    return start <= h < end if start < end else (h >= start or h < end)


async def send_alert(bot: Bot, deps: Deps, user_id: int, kind: str, text: str, markup=None) -> bool:
    """Send a personal alert now, or queue it for later when the user is in quiet hours."""
    prefs = deps.store.user_prefs(user_id)
    if in_quiet(prefs):
        await deps.store.enqueue(user_id, kind, text, time.time())
        return False
    try:
        await bot.send_message(user_id, text, reply_markup=markup)
    except (TelegramForbiddenError, TelegramBadRequest) as exc:
        log.warning("alert to %s failed: %s", user_id, exc)
    return True


# ------------------------------------------------------------------ overlap

async def compute_overlap(deps: Deps) -> list[tuple[str, dict[str, AtrMetrics]]]:
    n = deps.settings.overlap_top
    results = await asyncio.gather(*(_scan_and_record(deps, tf) for tf in OVERLAP_INTERVALS))
    per_symbol: dict[str, dict[str, AtrMetrics]] = {}
    for tf, res in zip(OVERLAP_INTERVALS, results):
        for m in res.top(n, "atr"):
            per_symbol.setdefault(m.symbol, {})[tf] = m
    hits = [(sym, d) for sym, d in per_symbol.items() if len(d) >= 2]
    hits.sort(key=lambda x: (-len(x[1]), -max(m.atr_pct for m in x[1].values())))
    return hits


async def show_overlap(message: Message, deps: Deps, edit: bool = False) -> None:
    status = message if edit else await message.answer("⏳ Сравниваю таймфреймы…")
    try:
        hits = await compute_overlap(deps)
    except ExchangeError as exc:
        await _safe_edit(status, f"😕 Биржа не ответила: <code>{html.escape(str(exc)[:200])}</code>")
        return
    text = format_overlap(hits[:20], OVERLAP_INTERVALS, deps.settings.overlap_top)
    await _safe_edit(status, text, kb.overlap_keyboard([sym for sym, _ in hits]))


@router.message(Command("overlap"))
@router.message(F.text == kb.BTN_OVERLAP)
async def cmd_overlap(message: Message, deps: Deps, state: FSMContext) -> None:
    await state.clear()
    await show_overlap(message, deps)


@router.callback_query(F.data == "ov:refresh")
async def cb_overlap(query: CallbackQuery, deps: Deps) -> None:
    await query.answer("Обновляю…")
    await show_overlap(query.message, deps, edit=True)


# ------------------------------------------------------------------ presets

async def show_presets(message: Message, deps: Deps, uid: int, edit: bool = False) -> None:
    presets = deps.store.user_presets(uid)
    text, markup = format_presets(presets), kb.presets_keyboard(presets)
    if edit:
        await _safe_edit(message, text, markup)
    else:
        await message.answer(text, reply_markup=markup)


@router.message(Command("presets"))
@router.message(F.text == kb.BTN_PRESETS)
async def cmd_presets(message: Message, deps: Deps, state: FSMContext) -> None:
    await state.clear()
    await show_presets(message, deps, message.from_user.id)


@router.message(Command("preset"))
async def cmd_preset(message: Message, command: CommandObject, deps: Deps) -> None:
    """/preset Имя [аргументы как у /top]."""
    parts = (command.args or "").split(None, 1)
    if not parts:
        await message.answer("Использование: <code>/preset Лонги 4ч 4h long cap 300m</code> — имя, затем настройки как у /top")
        return
    name, args = parts[0], (parts[1] if len(parts) > 1 else "")
    q = _parse_top_args(args, deps.settings, "atr")
    if q is None:
        await message.answer("Не понял настройки. Пример: <code>/preset Лонги4ч 4h long cap 300m</code>")
        return
    await _save_preset(message, deps, message.from_user.id, name, q)


async def _save_preset(message: Message, deps: Deps, uid: int, name: str, q: TopQuery) -> None:
    name = name.strip()[:24]
    preset = {"name": name, **q.to_dict(), "auto": False}
    if not await deps.store.preset_save(uid, preset):
        await message.answer("Больше 10 пресетов нельзя. Удалите лишний в 📁 Пресеты.")
        return
    await message.answer(f"💾 Сохранил пресет <b>{html.escape(name)}</b>.", reply_markup=kb.main_menu(deps.store.is_admin(uid)))
    await show_presets(message, deps, uid)


@router.callback_query(F.data.startswith("p:"))
async def cb_preset(query: CallbackQuery, deps: Deps, state: FSMContext) -> None:
    parts = query.data.split(":")
    action = parts[1]
    uid = query.from_user.id
    if action == "save":
        q = TopQuery.from_callback(deps.settings, parts[2:9])
        if q is None:
            await query.answer()
            return
        await state.set_state(AskPreset.name)
        await state.update_data(query=q.to_dict())
        await query.answer()
        await query.message.answer("Как назвать пресет? Например <code>Лонги 4ч</code>:", reply_markup=kb.cancel_menu())
        return
    if action == "list":
        await query.answer()
        await show_presets(query.message, deps, uid, edit=True)
        return
    idx = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else -1
    presets = deps.store.user_presets(uid)
    if not 0 <= idx < len(presets):
        await query.answer("Пресет не найден")
        await show_presets(query.message, deps, uid, edit=True)
        return
    p = presets[idx]
    if action == "run":
        await query.answer(f"▶ {p['name']}")
        await show_top(query.message, deps, TopQuery.from_dict(deps.settings, p))
    elif action == "auto":
        on = await deps.store.preset_toggle_auto(uid, idx)
        await query.answer(f"🔔 {p['name']}: после закрытия {tf_name(p['interval'])} свечи" if on else f"🔕 {p['name']}: авторассылка выкл")
        await show_presets(query.message, deps, uid, edit=True)
    elif action == "del":
        await deps.store.preset_delete(uid, idx)
        await query.answer(f"Удалил {p['name']}")
        await show_presets(query.message, deps, uid, edit=True)
    else:
        await query.answer()


@router.message(StateFilter(AskPreset.name), F.text, ~F.text.in_(kb.MENU_BUTTONS))
async def ask_preset_name(message: Message, deps: Deps, state: FSMContext) -> None:
    data = await state.get_data()
    await state.clear()
    q = TopQuery.from_dict(deps.settings, data.get("query", {}))
    await _save_preset(message, deps, message.from_user.id, message.text, q)


# ------------------------------------------------------------------ quiet hours / digest

async def show_prefs(message: Message, deps: Deps, uid: int, edit: bool = False) -> None:
    p = deps.store.user_prefs(uid)
    text, markup = format_prefs(p, len(deps.store.queue.get(uid, []))), kb.quiet_keyboard(p)
    if edit:
        await _safe_edit(message, text, markup)
    else:
        await message.answer(text, reply_markup=markup)


@router.message(Command("quiet"))
async def cmd_quiet(message: Message, command: CommandObject, deps: Deps) -> None:
    """/quiet — show; /quiet 23 8 — set hours; /quiet off."""
    parts = (command.args or "").split()
    uid = message.from_user.id
    if len(parts) == 2 and all(x.isdigit() for x in parts):
        await deps.store.set_pref(uid, quiet_on=True, quiet_start=int(parts[0]) % 24, quiet_end=int(parts[1]) % 24)
    elif parts and parts[0].lower() in ("off", "выкл"):
        await deps.store.set_pref(uid, quiet_on=False)
    await show_prefs(message, deps, uid)


@router.message(Command("tz"))
async def cmd_tz(message: Message, command: CommandObject, deps: Deps) -> None:
    arg = (command.args or "").strip().replace("utc", "").replace("UTC", "")
    try:
        tz = max(-12, min(14, int(arg)))
    except ValueError:
        await message.answer("Использование: <code>/tz +3</code>")
        return
    await deps.store.set_pref(message.from_user.id, tz=tz)
    await show_prefs(message, deps, message.from_user.id)


@router.message(Command("digest"))
async def cmd_digest(message: Message, command: CommandObject, deps: Deps) -> None:
    arg = (command.args or "").strip().lower()
    uid = message.from_user.id
    if arg.isdigit():
        await deps.store.set_pref(uid, digest_on=True, digest_hour=int(arg) % 24)
    elif arg in ("off", "выкл"):
        await deps.store.set_pref(uid, digest_on=False)
    elif arg in ("now", "сейчас"):
        await send_digest(message.bot, deps, uid)
        return
    await show_prefs(message, deps, uid)


@router.callback_query(F.data.startswith("q:"))
async def cb_quiet(query: CallbackQuery, deps: Deps) -> None:
    parts = query.data.split(":")
    action = parts[1]
    uid = query.from_user.id
    p = deps.store.user_prefs(uid)
    delta = int(parts[2]) if len(parts) > 2 and parts[2].lstrip("-").isdigit() else 0
    if action == "show":
        await query.answer()
        await show_prefs(query.message, deps, uid, edit=True)
        return
    if action == "back":
        from .bot import _subs_text
        await query.answer()
        await _safe_edit(query.message, _subs_text(deps.store, uid), kb.subs_keyboard(deps.store, uid, True))
        return
    if action == "now":
        await query.answer("Готовлю дайджест…")
        await send_digest(query.bot, deps, uid)
        return
    if action == "tz":
        await deps.store.set_pref(uid, tz=max(-12, min(14, p["tz"] + delta)))
    elif action == "quiet":
        await deps.store.set_pref(uid, quiet_on=not p["quiet_on"])
    elif action == "qs":
        await deps.store.set_pref(uid, quiet_start=(p["quiet_start"] + delta) % 24)
    elif action == "qe":
        await deps.store.set_pref(uid, quiet_end=(p["quiet_end"] + delta) % 24)
    elif action == "digest":
        await deps.store.set_pref(uid, digest_on=not p["digest_on"])
    elif action == "dh":
        await deps.store.set_pref(uid, digest_hour=(p["digest_hour"] + delta) % 24)
    await query.answer()
    await show_prefs(query.message, deps, uid, edit=True)


async def _flush_queue(bot: Bot, deps: Deps, uid: int) -> list[dict]:
    items = await deps.store.drain_queue(uid)
    for text in (format_queued(items) if items else []):
        try:
            await bot.send_message(uid, text)
        except (TelegramForbiddenError, TelegramBadRequest) as exc:
            log.warning("queue flush to %s failed: %s", uid, exc)
        await asyncio.sleep(0.1)
    return items


async def send_digest(bot: Bot, deps: Deps, uid: int) -> None:
    user = deps.store.users.get(uid)
    name = (user.name.split()[0] if user and user.name else "трейдер")
    q = TopQuery(deps.settings, "atr")
    q.n = 10
    try:
        result = await _scan_and_record(deps, "1h")
        top_text = _top_text(deps, result, q)
        watched = deps.store.watchlist(uid)
        metrics = await deps.scanner.metrics_for(watched, "1h") if watched else {}
    except ExchangeError as exc:
        top_text, metrics = f"😕 Биржа не ответила: <code>{html.escape(str(exc)[:200])}</code>", {}
    watch_lines = []
    for sym in sorted(watched if metrics else [], key=lambda s: -abs(metrics[s].move_pct) if metrics.get(s) else 0):
        m = metrics.get(sym)
        if m and abs(m.move_pct) >= 2:
            watch_lines.append(f"  {_arrow(m.move_pct)} <b>{sym.removesuffix('USDT')}</b> {_sign(m.move_pct)} · ATR {m.atr_pct:.1f}% · Δ {m.expansion_pct:+.0f}%")
    breakouts_total = sum(n for _, n in deps.breakout_log)
    queued = deps.store.queue.get(uid, [])
    text = format_digest(name, top_text, queued, breakouts_total, watch_lines)
    try:
        await bot.send_message(uid, text, reply_markup=_top_kb(deps, q))
    except (TelegramForbiddenError, TelegramBadRequest) as exc:
        log.warning("digest to %s failed: %s", uid, exc)
        return
    await _flush_queue(bot, deps, uid)
    await deps.store.set_pref(uid, last_digest=local_now(deps.store.user_prefs(uid)).strftime("%Y-%m-%d"))


async def prefs_scheduler(bot: Bot, deps: Deps) -> None:
    """Every minute: send due digests, flush queued alerts once quiet hours end."""
    while True:
        await asyncio.sleep(60 - time.time() % 60)
        try:
            for uid in list(deps.store.prefs):
                p = deps.store.user_prefs(uid)
                now = local_now(p)
                today = now.strftime("%Y-%m-%d")
                if p["digest_on"] and now.hour == p["digest_hour"] % 24 and p.get("last_digest") != today:
                    await send_digest(bot, deps, uid)
                elif deps.store.queue.get(uid) and not in_quiet(p, now):
                    await _flush_queue(bot, deps, uid)
        except Exception:  # noqa: BLE001 - keep the loop alive
            log.exception("prefs scheduler tick failed")
