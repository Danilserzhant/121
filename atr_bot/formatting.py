"""Telegram (HTML) message formatting."""

from __future__ import annotations

import html
from datetime import datetime, timezone

from .indicators import AtrMetrics
from .scanner import ScanResult

TF_NAMES = {"1h": "1ч", "4h": "4ч", "1d": "1Д", "1w": "1Н"}
TF_UNIT = {"1h": "час", "4h": "4 часа", "1d": "день", "1w": "неделю"}
TF_PLURAL = {"1h": "ч", "4h": "×4ч", "1d": "дн", "1w": "нед"}

TF_ALIASES = {
    "1h": {"1h", "h", "1ч", "ч", "час", "hour", "60"},
    "4h": {"4h", "4", "4ч", "240"},
    "1d": {"1d", "d", "1д", "д", "день", "day", "дн", "daily"},
    "1w": {"1w", "w", "1н", "н", "неделя", "week", "нед", "weekly"},
}
DIRECTION_ALIASES = {
    "long": {"long", "лонг", "up", "вверх", "l", "л", "рост"},
    "short": {"short", "шорт", "down", "вниз", "s", "ш", "слив"},
    "all": {"all", "все", "всё", "any"},
}
DIRECTION_TITLES = {"long": "🟢 только рост", "short": "🔴 только падение", "all": ""}
VIEWS = ("list", "table")
SORTS = ("atr", "expansion", "corr", "corrhi")
SORT_TITLES = {
    "atr": "📊 Топ по ATR%",
    "expansion": "📈 Топ по росту ATR",
    "corr": "🧭 Сами по себе (низкая ρ с BTC)",
    "corrhi": "🔗 Вместе с BTC (высокая ρ)",
}
SORT_ALIASES = {
    "expansion": {"exp", "expansion", "рост", "расширение", "delta", "δ"},
    "corr": {"corr", "корр", "independent", "indep", "независимые", "сами", "ρ"},
    "corrhi": {"corr+", "corrhi", "corrhigh", "withbtc", "сbtc", "сбтк", "вместе", "ρ+"},
    "atr": {"atr", "атр"},
}


def parse_sort(token: str) -> str | None:
    t = token.strip().lower()
    for by, names in SORT_ALIASES.items():
        if t in names:
            return by
    return None
MEDALS = {1: "🥇", 2: "🥈", 3: "🥉"}
LINE = "━━━━━━━━━━━━━━━━━━"


import re as _re

_AMOUNT_RE = _re.compile(r"^(\d+(?:[.,]\d+)?)\s*([kmb]|к|м|млн|млрд|b|тыс)?$", _re.I)
_FILTER_KEYS = {
    "vol": {"vol", "v", "volume", "оборот", "об", "объём", "объем"},
    "cap": {"cap", "c", "mcap", "marketcap", "капа", "кап", "капитализация", "mc"},
}
_MULT = {"k": 1e3, "к": 1e3, "тыс": 1e3, "m": 1e6, "м": 1e6, "млн": 1e6, "b": 1e9, "млрд": 1e9}


def parse_amount(token: str) -> float | None:
    """'20m' -> 20_000_000, '1.5b' -> 1.5e9, '500k' -> 500_000, '5000000' -> 5e6."""
    m = _AMOUNT_RE.match(token.strip().lower())
    if not m:
        return None
    value = float(m.group(1).replace(",", "."))
    unit = (m.group(2) or "").lower()
    return value * _MULT.get(unit, 1.0)


def parse_filter(token: str) -> tuple[str, float] | tuple[str, None] | None:
    """'vol>20m' / 'cap1b' -> ('vol', 2e7); bare 'cap' -> ('cap', None) (value in next token)."""
    t = token.strip().lower().lstrip("≥>=")
    m = _re.match(r"^([a-zа-яё]+)\s*[>=:≥]*\s*(.*)$", t)
    if not m:
        return None
    key, rest = m.group(1), m.group(2)
    kind = next((k for k, names in _FILTER_KEYS.items() if key in names), None)
    if kind is None:
        return None
    if not rest:
        return kind, None
    value = parse_amount(rest)
    return (kind, value) if value is not None else None


def parse_direction(token: str) -> str | None:
    t = token.strip().lower()
    for d, names in DIRECTION_ALIASES.items():
        if t in names:
            return d
    return None


def parse_timeframe(token: str) -> str | None:
    t = token.strip().lower()
    for tf, names in TF_ALIASES.items():
        if t in names:
            return tf
    return None


def tf_name(interval: str) -> str:
    return TF_NAMES.get(interval, interval)


# ------------------------------------------------------------------ small helpers

def fmt_price(p: float) -> str:
    if p >= 1000:
        return f"{p:,.1f}"
    if p >= 1:
        return f"{p:.4f}".rstrip("0").rstrip(".")
    return f"{p:.6g}"


def fmt_big(v: float) -> str:
    """5_400_000 -> '5.4M', 1_130_000_000 -> '1.13B'."""
    if v >= 1e12:
        return f"{v/1e12:.2f}".rstrip("0").rstrip(".") + "T"
    if v >= 1e9:
        return f"{v/1e9:.2f}".rstrip("0").rstrip(".") + "B"
    if v >= 1e6:
        return f"{v/1e6:.1f}".rstrip("0").rstrip(".") + "M"
    if v >= 1e3:
        return f"{v/1e3:.0f}K"
    return f"{v:.0f}"


def _sign(v: float, digits: int = 1) -> str:
    return f"{v:+.{digits}f}%"


def _arrow(move: float) -> str:
    return "🟢" if move > 0 else "🔴" if move < 0 else "⚪️"


def _utc(ts_ms: int, interval: str = "1h") -> str:
    dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
    return dt.strftime("%d.%m") if interval in ("1d", "1w") else dt.strftime("%d.%m %H:%M")


def _window(interval: str, lookback: int) -> str:
    return f"{lookback}{TF_PLURAL.get(interval, ' свеч')}"


def short_symbol(symbol: str, width: int = 10) -> str:
    sym = symbol.removesuffix("USDT") if symbol.endswith("USDT") else symbol
    return sym[:width]


def _vol(v: float) -> str:
    return f"×{v:.1f}" if v < 10 else f"×{v:.0f}"


def _streak(st: int) -> str:
    if st == 1:
        return "🆕"
    if st >= 2:
        return f"🔥{st}"
    return ""


def _now_utc() -> str:
    return datetime.now(tz=timezone.utc).strftime("%H:%M")


# ------------------------------------------------------------------ top

def _rho(m: AtrMetrics) -> str:
    return f"{m.btc_corr:+.2f}" if m.btc_corr is not None else "—"


def _deriv_line(m: AtrMetrics) -> str:
    """'фандинг +0.010% · ОИ 152M (+8% 24ч)' or '' for spot."""
    parts = []
    if m.funding is not None:
        f = m.funding * 100
        flag = " 🔻" if f <= -0.03 else (" 🔺" if f >= 0.05 else "")
        parts.append(f"фандинг {f:+.3f}%{flag}")
    if m.oi_usd:
        oi = f"ОИ {fmt_big(m.oi_usd)}"
        if m.oi_change_24h is not None:
            oi += f" ({m.oi_change_24h:+.0f}% 24ч)"
        elif m.oi_change_1h is not None:
            oi += f" ({m.oi_change_1h:+.1f}% 1ч)"
        parts.append(oi)
    return " · ".join(parts)


def _top_header(result: ScanResult, by: str, direction: str, min_volume: float = 0.0, min_cap: float = 0.0) -> str:
    tf = result.interval
    title = SORT_TITLES.get(by, SORT_TITLES["atr"])
    dir_txt = f"  {DIRECTION_TITLES[direction]}" if direction != "all" else ""
    filters = []
    if min_volume > 0:
        filters.append(f"оборот ≥ {fmt_big(min_volume)}")
    if min_cap > 0:
        filters.append(f"капа ≥ {fmt_big(min_cap)}")
    filt = ("\n<i>🔍 " + " · ".join(filters) + "</i>") if filters else ""
    return (
        f"<b>{title} · {tf_name(tf)}</b>{dir_txt}\n"
        f"<i>{html.escape(result.exchange)} · свеча {_utc(result.candle_time, tf)} UTC · "
        f"{len(result.ranked)} монет · окно {_window(tf, result.lookback)}</i>{filt}\n"
    )


def _top_footer(result: ScanResult) -> str:
    tf = result.interval
    return (
        f"\n<i>ATR — средний ход за {TF_UNIT.get(tf, 'свечу')} · св — последняя свеча · "
        f"Δ — рост ATR за {_window(tf, result.lookback)} · × — объём свечи к среднему · ρ — корреляция с BTC по свечам · "
        f"об. — оборот 24ч · ОИ — открытый интерес и его изменение · 🔺🔻 — экстремальный фандинг · 🔥 — свечей подряд в топ-20 · "
        f"обновлено {_now_utc()} UTC</i>"
    )


def format_top(
    result: ScanResult,
    n: int,
    by: str = "atr",
    direction: str = "all",
    streaks: dict[str, int] | None = None,
    view: str = "list",
    min_volume: float = 0.0,
    min_cap: float = 0.0,
) -> str:
    rows = result.top(n, by, direction, min_volume, min_cap)
    head = _top_header(result, by, direction, min_volume, min_cap)
    if not rows:
        return head + "\nНичего не нашлось под этот фильтр."
    streaks = streaks or {}
    if view == "table":
        return head + _top_table(rows, by, streaks) + _top_footer(result)
    lines = []
    for i, m in enumerate(rows, start=1):
        num = MEDALS.get(i, f"{i}.")
        atr = f"ATR <b>{m.atr_pct:.1f}%</b>" if by == "atr" else f"ATR {m.atr_pct:.1f}%"
        exp = f"Δ <b>{m.expansion_pct:+.0f}%</b>" if by == "expansion" else f"Δ {m.expansion_pct:+.0f}%"
        rho = f"ρ <b>{_rho(m)}</b>" if by in ("corr", "corrhi") else f"ρ {_rho(m)}"
        st = _streak(streaks.get(m.symbol, 0))
        lines.append(
            f"{num} <b>{short_symbol(m.symbol)}</b>  {_arrow(m.move_pct)} {_sign(m.move_pct)}"
            + (f"  {st}" if st else "")
            + f"\n      {atr} · св {m.last_tr_pct:.1f}% · {exp} · {_vol(m.vol_ratio)} · {rho}"
            + f"\n      об. {fmt_big(m.quote_volume)}" + (f" · капа {fmt_big(m.market_cap)}" if m.market_cap else "")
            + (f"\n      {_deriv_line(m)}" if _deriv_line(m) else "")
        )
    return head + "\n".join(lines) + _top_footer(result)


def _top_table(rows: list[AtrMetrics], by: str, streaks: dict[str, int]) -> str:
    show_streak = any(v > 0 for v in streaks.values())
    header = f"{'#':>2} {'Монета':<8} {'ATR%':>5} {'Δ%':>5} {'Св%':>5} {'Ход%':>6} {'×об':>4} {'ρBTC':>5} {'Капа':>5}" + ("  Т" if show_streak else "")
    lines = [header]
    for i, m in enumerate(rows, start=1):
        line = (
            f"{i:>2} {short_symbol(m.symbol, 8):<8} {m.atr_pct:>5.1f} {m.expansion_pct:>+5.0f} "
            f"{m.last_tr_pct:>5.1f} {m.move_pct:>+6.1f} {m.vol_ratio:>4.1f} {_rho(m):>5} {(fmt_big(m.market_cap) if m.market_cap else '—'):>5}"
        )
        if show_streak:
            st = streaks.get(m.symbol, 0)
            line += f" {'н' if st == 1 else (str(st) if st > 1 else '·'):>2}"
        lines.append(line)
    return "<pre>" + html.escape("\n".join(lines)) + "</pre>"


# ------------------------------------------------------------------ symbol card

def format_symbol(symbol: str, per_tf: dict[str, AtrMetrics | None], ranks: dict[str, tuple[int, int]], watched: bool = False) -> str:
    first = next((m for m in per_tf.values() if m is not None), None)
    if first is None:
        return f"По <b>{html.escape(symbol)}</b> слишком мало истории."
    head = (
        f"🔎 <b>{html.escape(symbol)}</b>{'  👀' if watched else ''}\n"
        f"Цена <code>{fmt_price(first.close)}</code> · оборот 24ч <b>{fmt_big(first.quote_volume)}</b>"
        + (f" · капа <b>{fmt_big(first.market_cap)}</b>" if first.market_cap else "")
        + (f"\n{_deriv_line(first)}" if _deriv_line(first) else "") + f"\n{LINE}\n"
    )
    lines = []
    for tf, m in per_tf.items():
        if m is None:
            lines.append(f"<b>{tf_name(tf)}</b>  мало истории")
            continue
        rank = ranks.get(tf)
        rank_txt = f" · #{rank[0]} из {rank[1]}" if rank else ""
        lines.append(
            f"<b>{tf_name(tf):<2}</b>  ATR <b>{m.atr_pct:.2f}%</b> · Δ {m.expansion_pct:+.0f}%\n"
            f"      св {m.last_tr_pct:.1f}% ({m.last_tr_ratio:.1f}×) · {_arrow(m.move_pct)} {_sign(m.move_pct)} · {_vol(m.vol_ratio)} · ρ {_rho(m)}{rank_txt}"
        )
    return (
        head + "\n".join(lines) + f"\n{LINE}\n"
        "<i>ATR — средний ход за свечу · Δ — рост ATR к окну · св — последняя свеча и сколько это старых ATR · "
        "× — объём к среднему · ρ — корреляция с BTC · # — место в топе по ATR%</i>"
    )


# ------------------------------------------------------------------ alerts / watchlist

def format_breakouts(rows: list[AtrMetrics], interval: str, ratio: float) -> str:
    candle = _utc(rows[0].candle_time, interval)
    head = f"🚨 <b>Свеча-выброс · {tf_name(interval)}</b>\n<i>свеча {candle} UTC · порог {ratio:g}× ATR</i>\n{LINE}\n"
    lines = []
    for m in sorted(rows, key=lambda m: m.last_tr_ratio, reverse=True):
        lines.append(
            f"{_arrow(m.move_pct)} <b>{short_symbol(m.symbol, 12)}</b>  св <b>{m.last_tr_pct:.1f}%</b> = {m.last_tr_ratio:.1f}× ATR"
            f"\n      ATR {m.atr_pct:.2f}% · {_vol(m.vol_ratio)} · ход {_sign(m.move_pct)}"
        )
    return head + "\n".join(lines)


def format_watch_alert(m: AtrMetrics, interval: str, reasons: list[str]) -> str:
    return (
        f"👀 {_arrow(m.move_pct)} <b>{html.escape(m.symbol)}</b> · {tf_name(interval)} · свеча {_utc(m.candle_time, interval)} UTC\n"
        + "\n".join(f"• {r}" for r in reasons)
        + f"\n{LINE}\nATR {m.atr_pct:.2f}% · св {m.last_tr_pct:.1f}% ({m.last_tr_ratio:.1f}×) · {_vol(m.vol_ratio)} · "
        f"ход {_sign(m.move_pct)} · цена <code>{fmt_price(m.close)}</code>"
    )


def format_watchlist(symbols: list[str], metrics: dict[str, AtrMetrics | None], interval: str) -> str:
    if not symbols:
        return (
            "👀 <b>Мои монеты</b>\n\nСписок пуст. Нажмите «➕ Добавить» или напишите <code>/watch SOL ETH</code>.\n"
            "По монетам из списка приходят личные алерты, когда свеча выходит за ATR или ATR резко растёт."
        )
    lines = []
    for sym in symbols:
        m = metrics.get(sym)
        if m is None:
            lines.append(f"<b>{short_symbol(sym)}</b>  нет данных")
            continue
        lines.append(
            f"{_arrow(m.move_pct)} <b>{short_symbol(sym)}</b>  {_sign(m.move_pct)} · <code>{fmt_price(m.close)}</code>"
            f"\n      ATR <b>{m.atr_pct:.1f}%</b> · св {m.last_tr_pct:.1f}% ({m.last_tr_ratio:.1f}×) · Δ {m.expansion_pct:+.0f}% · {_vol(m.vol_ratio)}"
        )
    return (
        f"👀 <b>Мои монеты · {tf_name(interval)}</b>\n<i>{len(symbols)} монет · обновлено {_now_utc()} UTC</i>\n{LINE}\n"
        + "\n".join(lines)
    )


# ------------------------------------------------------------------ settings / help

def format_settings(s) -> str:  # noqa: ANN001 - Settings, avoid circular import in typing
    lookbacks = " · ".join(f"{tf_name(tf)} {s.lookback_for(tf)}" for tf in s.intervals)
    return (
        "⚙️ <b>Настройки</b>\n"
        f"{LINE}\n"
        f"Биржа: <b>{html.escape(s.exchange)}</b> · {s.quote_asset}\n"
        f"ATR период: <b>{s.atr_period}</b> · окно Δ: {lookbacks}\n"
        f"Топ: <b>{s.top_n}</b> монет · мин. оборот <b>{fmt_big(s.min_quote_volume)}</b> · мин. ATR <b>{s.min_atr_pct:g}%</b>\n"
        f"Свеча-выброс: ≥ <b>{s.alert_tr_ratio:g}×</b> ATR и ≥ {s.alert_min_tr_pct:g}% свеча\n"
        f"Мои монеты: ≥ <b>{s.watch_tr_ratio:g}×</b> ATR или Δ ≥ <b>{s.watch_expansion_pct:g}%</b>\n"
        f"{LINE}\n"
        "<i>Кнопками ниже или текстом: /set период 14, /set окно 4h 6, /set топ 20, "
        "/set оборот 10000000, /set atr 1.5, /set выброс 2.5, /set watch 2, /set рост 50</i>"
    )


def welcome(name: str, is_admin: bool) -> str:
    text = (
        f"👋 Привет, <b>{html.escape(name)}</b>!\n\n"
        "Я ищу самые волатильные монеты по ATR в % от цены на 1ч, 4ч, дневных и недельных свечах.\n\n"
        "📊 <b>Топ ATR</b> — кто ходит сильнее всех\n"
        "📈 <b>Рост ATR</b> — у кого волатильность просыпается\n"
        "🧭 <b>ρ BTC</b> — кто ходит сам по себе, а кто вслед за биткоином\n"
        "👀 <b>Мои монеты</b> — свой список с личными алертами\n"
        "🔎 <b>Монета</b> — карточка и график. Или просто напишите тикер: <code>SOL</code>\n"
        "🎯 <b>Совпадения</b> — кто в топе сразу на нескольких таймфреймах\n"
        "📁 <b>Пресеты</b> — сохранённые наборы фильтров, можно на авторассылку\n"
        "🔔 <b>Подписки</b> — часовой и дневной топ, алерты, тихие часы, дайджест\n"
    )
    if is_admin:
        text += "⚙️ <b>Настройки</b>, 👥 <b>Пользователи</b>, 📨 <b>Заявки</b> — админка\n"
    return text + "\nПолный список команд — /help"


HELP = (
    "🤖 <b>ATR Bot — команды</b>\n"
    f"{LINE}\n"
    "/top — топ по ATR% на часовых свечах\n"
    "/top 4h, /top 1d, /top 1w — другие таймфреймы\n"
    "/top 1d 30 long — количество и направление\n"
    "/top vol 20m cap 300m — оборот 24ч и капитализация не меньше\n"
    "/exp [тф] [N] — топ по росту ATR\n"
    "/corr [тф] — монеты, которые ходят сами по себе (низкая корреляция с BTC)\n"
    "/top corr+ — наоборот, самые связанные с BTC\n"
    "/atr SOL — карточка монеты на всех таймфреймах\n"
    "/chart SOL 4h — график свечей и ATR\n"
    "/watch SOL ETH · /unwatch SOL · /watchlist — мои монеты\n"
    "/overlap — совпадения таймфреймов\n"
    "/presets — мои пресеты · /preset имя — сохранить текущие настройки топа\n"
    "/subs — рассылки в этот чат (или /sub, /sub 1d, /sub alerts, /unsub)\n"
    "/quiet — тихие часы, часовой пояс, дайджест (/tz +3, /quiet 23 8, /digest 8)\n"
    "/myid — мой ID и роль · /menu — клавиатура\n"
    f"{LINE}\n"
    "<i>ATR% — средний диапазон свечи в % цены (Wilder 14). "
    "ρ — корреляция Пирсона свечных доходностей монеты и BTC на том же таймфрейме за окно сканирования. "
    "Δ — насколько ATR вырос к значению N свечей назад. "
    "Свеча-выброс — последняя свеча больше N старых ATR.</i>"
)


# ------------------------------------------------------------------ overlap / presets / quiet / digest

def format_overlap(hits: list[tuple[str, dict[str, AtrMetrics]]], intervals: list[str], top_n: int) -> str:
    """hits: [(symbol, {interval: metrics})] sorted best first."""
    head = (
        f"🎯 <b>Совпадения таймфреймов</b>\n"
        f"<i>монеты в топ-{top_n} по ATR% сразу на нескольких из {', '.join(tf_name(t) for t in intervals)}</i>\n{LINE}\n"
    )
    if not hits:
        return head + "Сейчас пересечений нет."
    lines = []
    for sym, per_tf in hits:
        tfs = " ".join(f"<b>{tf_name(tf)}</b>" for tf in intervals if tf in per_tf)
        first = per_tf[next(tf for tf in intervals if tf in per_tf)]
        details = " · ".join(f"{tf_name(tf)} {m.atr_pct:.1f}%" for tf, m in per_tf.items())
        lines.append(f"{_arrow(first.move_pct)} <b>{short_symbol(sym)}</b>  {tfs}\n      ATR: {details} · ρ {_rho(first)}")
    return head + "\n".join(lines) + "\n\n<i>Чем больше таймфреймов совпало, тем выше монета. Обычно это самый рабочий список.</i>"


def preset_title(p: dict) -> str:
    bits = [tf_name(p.get("interval", "1h")), SORT_TITLES.get(p.get("by", "atr"), "").split(" ", 1)[-1][:12]]
    if p.get("direction", "all") != "all":
        bits.append(DIRECTION_TITLES[p["direction"]].split(" ", 1)[0])
    if p.get("min_volume"):
        bits.append(f"об≥{fmt_big(p['min_volume'])}")
    if p.get("min_cap"):
        bits.append(f"капа≥{fmt_big(p['min_cap'])}")
    return " · ".join(b for b in bits if b)


def format_presets(presets: list[dict]) -> str:
    head = "📁 <b>Мои пресеты</b>\n"
    if not presets:
        return head + (
            "\nПока пусто. Настройте топ кнопками (таймфрейм, фильтры, сортировка) и нажмите под ним «💾 Сохранить».\n"
            "Пресет вызывается одной кнопкой, а с 🔔 приходит автоматически после закрытия свечи его таймфрейма."
        )
    lines = [f"{'🔔' if p.get('auto') else '▫️'} <b>{html.escape(p['name'])}</b> — <i>{preset_title(p)}</i>" for p in presets]
    return head + f"<i>{len(presets)} из 10</i>\n{LINE}\n" + "\n".join(lines) + "\n\n<i>▶ запустить · 🔔 авторассылка после закрытия свечи · ✖ удалить</i>"


def _hh(h: int) -> str:
    return f"{h % 24:02d}:00"


def format_prefs(p: dict, queued: int = 0) -> str:
    tz = p["tz"]
    quiet = f"{_hh(p['quiet_start'])}–{_hh(p['quiet_end'])}" if p["quiet_on"] else "выкл"
    digest = _hh(p["digest_hour"]) if p["digest_on"] else "выкл"
    text = (
        "🌙 <b>Тихие часы и дайджест</b>\n"
        f"{LINE}\n"
        f"Часовой пояс: <b>UTC{tz:+d}</b>\n"
        f"Тихие часы: <b>{quiet}</b>\n"
        f"Утренний дайджест: <b>{digest}</b>\n"
        f"{LINE}\n"
        "<i>В тихие часы личные алерты не приходят, а копятся и присылаются одним сообщением, когда тихие часы закончатся. "
        "Дайджест — раз в день: самые волатильные монеты за сутки, сколько было выбросов, что двигалось из ваших монет.</i>"
    )
    if queued:
        text += f"\n\n📥 В очереди сейчас: <b>{queued}</b>"
    return text


def format_digest(name: str, top_text: str, queued: list[dict], breakouts_total: int, watch_lines: list[str]) -> str:
    head = f"☀️ <b>Доброе утро, {html.escape(name)}!</b>\n<i>дайджест за последние сутки</i>\n{LINE}\n"
    parts = []
    if breakouts_total:
        parts.append(f"🚨 Свечей-выбросов за сутки: <b>{breakouts_total}</b>")
    if watch_lines:
        parts.append("👀 <b>Ваши монеты двигались:</b>\n" + "\n".join(watch_lines[:10]))
    if queued:
        parts.append(f"📥 Пока вы отдыхали, пришло <b>{len(queued)}</b> алертов, они ниже.")
    return head + ("\n\n".join(parts) + f"\n{LINE}\n" if parts else "") + top_text


def format_queued(items: list[dict]) -> list[str]:
    """Deferred alerts as a few messages (Telegram limit is 4096 chars)."""
    msgs, buf = [], f"📥 <b>Пока вы отдыхали</b> · {len(items)} алертов\n{LINE}\n"
    for it in items:
        t = datetime.fromtimestamp(it["ts"], tz=timezone.utc).strftime("%H:%M")
        chunk = f"\n<b>{t} UTC</b>\n{it['text']}\n"
        if len(buf) + len(chunk) > 3800:
            msgs.append(buf)
            buf = ""
        buf += chunk
    msgs.append(buf)
    return msgs
