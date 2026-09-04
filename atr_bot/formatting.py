"""Telegram (HTML) message formatting."""

from __future__ import annotations

import html
from datetime import datetime, timezone

from .indicators import AtrMetrics
from .scanner import ScanResult

TF_NAMES = {"1h": "1ч", "4h": "4ч", "1d": "1Д", "1w": "1Н"}
TF_UNIT = {"1h": "час", "4h": "4 часа", "1d": "день", "1w": "неделю"}
TF_PLURAL = {"1h": "ч", "4h": "×4ч", "1d": "дн", "1w": "нед"}

# Anything a user may type to name a timeframe.
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
DIRECTION_TITLES = {"long": "только рост", "short": "только падение", "all": ""}


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


def _fmt_price(p: float) -> str:
    if p >= 1000:
        return f"{p:,.1f}"
    if p >= 1:
        return f"{p:.4f}"
    return f"{p:.6g}"


def _sign(v: float, digits: int = 1) -> str:
    return f"{v:+.{digits}f}%"


def _utc(ts_ms: int, interval: str = "1h") -> str:
    dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
    return dt.strftime("%d.%m") if interval in ("1d", "1w") else dt.strftime("%d.%m %H:%M")


def _window(interval: str, lookback: int) -> str:
    return f"{lookback}{TF_PLURAL.get(interval, ' свеч')}"


def _short(symbol: str, width: int = 8) -> str:
    sym = symbol.removesuffix("USDT") if symbol.endswith("USDT") else symbol
    return sym[:width]


def _vol(v: float) -> str:
    return f"x{v:.1f}" if v < 10 else f"x{v:.0f}"


def format_top(
    result: ScanResult,
    n: int,
    by: str = "atr",
    direction: str = "all",
    streaks: dict[str, int] | None = None,
) -> str:
    rows = result.top(n, by, direction)
    tf = result.interval
    if not rows:
        return f"Нет монет под фильтр ({tf_name(tf)}{', ' + DIRECTION_TITLES[direction] if direction != 'all' else ''})."
    candle = _utc(rows[0].candle_time, tf)
    title = "📈 <b>Топ по росту ATR" if by == "expansion" else "📊 <b>Топ по ATR в % цены"
    title += f" · {tf_name(tf)}"
    if direction != "all":
        title += f" · {DIRECTION_TITLES[direction]}"
    title += "</b>"
    head = (
        f"{title}\n"
        f"Биржа: {html.escape(result.exchange)} · свеча {candle} UTC\n"
        f"ATR({result.atr_period}), окно {_window(tf, result.lookback)} · {len(result.ranked)} монет\n"
    )
    show_streak = streaks is not None and any(v > 0 for v in streaks.values())
    header = f"{'#':>2} {'Монета':<8} {'ATR%':>5} {'ΔATR':>5} {'Свеча':>5} {'Ход':>6} {'Объём':>5}"
    if show_streak:
        header += f" {'Топ':>3}"
    lines = [header]
    for i, m in enumerate(rows, start=1):
        line = (
            f"{i:>2} {_short(m.symbol):<8} {m.atr_pct:>4.1f}% {m.expansion_pct:>+4.0f}% "
            f"{m.last_tr_pct:>4.1f}% {m.move_pct:>+5.1f}% {_vol(m.vol_ratio):>5}"
        )
        if show_streak:
            st = streaks.get(m.symbol, 0)
            line += f" {'new' if st == 1 else (str(st) if st > 1 else '·'):>3}"
        lines.append(line)
    table = "<pre>" + html.escape("\n".join(lines)) + "</pre>"
    legend = (
        f"\n<i>ATR% — средний ход за {TF_UNIT.get(tf, 'свечу')} в % цены · ΔATR — рост ATR за "
        f"{_window(tf, result.lookback)} · Свеча — диапазон последней свечи · "
        f"Ход — движение за {_window(tf, result.lookback)} · Объём — последняя свеча к среднему"
    )
    if show_streak:
        legend += " · Топ — сколько свечей подряд в топ-20, new — только зашла"
    legend += "</i>"
    return head + table + legend


def format_symbol(symbol: str, per_tf: dict[str, AtrMetrics | None], ranks: dict[str, tuple[int, int]]) -> str:
    """One coin across all timeframes. ranks: {interval: (rank, total)}."""
    first = next((m for m in per_tf.values() if m is not None), None)
    if first is None:
        return f"По <code>{html.escape(symbol)}</code> слишком мало истории."
    lines = [f"{'ТФ':<3} {'ATR%':>6} {'ΔATR':>6} {'Свеча':>6} {'Ход':>7} {'Объём':>5} {'Место':>6}"]
    for tf, m in per_tf.items():
        if m is None:
            lines.append(f"{tf_name(tf):<3} {'—':>6}  мало истории")
            continue
        rank = ranks.get(tf)
        rank_txt = f"#{rank[0]}/{rank[1]}" if rank else "—"
        lines.append(
            f"{tf_name(tf):<3} {m.atr_pct:>5.2f}% {m.expansion_pct:>+5.0f}% {m.last_tr_pct:>5.1f}% {m.move_pct:>+6.1f}% {_vol(m.vol_ratio):>5} {rank_txt:>6}"
        )
    return (
        f"🔎 <b>{html.escape(symbol)}</b> · цена <code>{_fmt_price(first.close)}</code> · "
        f"оборот 24ч {first.quote_volume/1e6:.1f}M\n"
        "<pre>" + html.escape("\n".join(lines)) + "</pre>\n"
        "<i>ATR% — средний ход за свечу в % цены · ΔATR — рост ATR к окну сравнения · "
        "Ход — движение за окно · Объём — последняя свеча к среднему · Место — в рейтинге по ATR% (если сканировали)</i>"
    )


def format_settings(s) -> str:  # noqa: ANN001 - Settings, avoid circular import in typing
    lookbacks = ", ".join(f"{tf_name(tf)}: {s.lookback_for(tf)}" for tf in s.intervals)
    return (
        "⚙️ <b>Настройки сканера</b>\n"
        f"Биржа: <code>{html.escape(s.exchange)}</code> · котировка {s.quote_asset}\n"
        f"Таймфрейм по умолчанию: <code>{s.interval}</code> (доступны {', '.join(s.intervals)})\n"
        f"ATR период: <code>{s.atr_period}</code>\n"
        f"Окно сравнения (свечей): {lookbacks}\n"
        f"Топ по умолчанию: <code>{s.top_n}</code>\n"
        f"Мин. оборот 24ч: <code>{s.min_quote_volume:,.0f}</code> {s.quote_asset}\n"
        f"Мин. ATR%: <code>{s.min_atr_pct}</code>\n"
        f"Кэш результата: <code>{s.cache_ttl}</code> с\n\n"
        f"Алерт свеча-выброс: ≥ <code>{s.alert_tr_ratio:g}</code>× ATR и ≥ <code>{s.alert_min_tr_pct:g}</code>% свеча\n"
        f"Алерт по своим монетам: ≥ <code>{s.watch_tr_ratio:g}</code>× ATR или ΔATR ≥ <code>{s.watch_expansion_pct:g}</code>%\n\n"
        "Изменить: <code>/set период 14</code>, <code>/set окно 4h 6</code>, "
        "<code>/set топ 20</code>, <code>/set оборот 10000000</code>, <code>/set atr 1.5</code>, "
        "<code>/set выброс 2.5</code>, <code>/set watch 2</code>, <code>/set рост 50</code>"
    )


HELP = (
    "🤖 <b>ATR Bot</b>\n"
    "Считаю ATR для всех монет биржи и показываю самые волатильные — "
    "ATR в % цены, то есть чистое движение за свечу.\n\n"
    "<b>Команды</b>\n"
    "/top — топ по ATR% на часовых свечах\n"
    "/top 4h, /top 1d, /top 1w — то же на 4ч, дневных, недельных\n"
    "/top 1d 30 — можно указать и количество монет\n"
    "/exp [тф] [N] — топ по росту ATR (волатильность расширяется)\n"
    "/top 1d long, /top short — только растущие или только падающие\n"
    "/atr SOL — монета на всех таймфреймах сразу\n"
    "/chart SOL [тф] — график свечей и ATR картинкой\n"
    "/watch SOL, /unwatch SOL, /watchlist — мои монеты; по ним приходят алерты\n"
    "/sub — часовой топ после закрытия каждой свечи\n"
    "/sub 1d — дневной топ после закрытия дня\n"
    "/sub alerts — алерты «свеча-выброс» по всему рынку\n"
    "/unsub [1h|1d|alerts] — отключить рассылку (без аргумента — все)\n"
    "/myid — мой Telegram ID и роль\n"
    "/help — эта справка"
)


def format_breakouts(rows: list[AtrMetrics], interval: str, ratio: float) -> str:
    candle = _utc(rows[0].candle_time, interval)
    lines = [f"🚨 <b>Свеча-выброс · {tf_name(interval)}</b> · свеча {candle} UTC · ≥{ratio:g}× ATR\n"]
    for m in sorted(rows, key=lambda m: m.last_tr_ratio, reverse=True):
        arrow = "🟢" if m.move_pct > 0 else "🔴"
        lines.append(
            f"{arrow} <b>{_short(m.symbol, 12)}</b> свеча {m.last_tr_pct:.1f}% = {m.last_tr_ratio:.1f}× ATR · "
            f"объём {_vol(m.vol_ratio)} · ATR {m.atr_pct:.2f}% · ход {_sign(m.move_pct)}"
        )
    return "\n".join(lines)


def format_watch_alert(m: AtrMetrics, interval: str, reasons: list[str]) -> str:
    arrow = "🟢" if m.move_pct > 0 else "🔴"
    return (
        f"👀 {arrow} <b>{html.escape(m.symbol)}</b> · {tf_name(interval)} · свеча {_utc(m.candle_time, interval)} UTC\n"
        + "\n".join(f"• {r}" for r in reasons)
        + f"\nATR {m.atr_pct:.2f}% · свеча {m.last_tr_pct:.1f}% ({m.last_tr_ratio:.1f}× ATR) · "
        f"объём {_vol(m.vol_ratio)} · ход {_sign(m.move_pct)} · цена <code>{_fmt_price(m.close)}</code>"
    )


def format_watchlist(symbols: list[str], metrics: dict[str, AtrMetrics | None], interval: str) -> str:
    if not symbols:
        return "Список пуст. Добавить: <code>/watch SOL</code>"
    lines = [f"{'Монета':<8} {'ATR%':>5} {'ΔATR':>5} {'Свеча':>5} {'Ход':>6} {'Объём':>5}"]
    for sym in symbols:
        m = metrics.get(sym)
        if m is None:
            lines.append(f"{_short(sym):<8}   нет данных")
            continue
        lines.append(
            f"{_short(sym):<8} {m.atr_pct:>4.1f}% {m.expansion_pct:>+4.0f}% {m.last_tr_pct:>4.1f}% {m.move_pct:>+5.1f}% {_vol(m.vol_ratio):>5}"
        )
    return (
        f"👀 <b>Мои монеты · {tf_name(interval)}</b>\n<pre>" + html.escape("\n".join(lines)) + "</pre>\n"
        "<i>Убрать: /unwatch SOL · очистить: /unwatch all</i>"
    )
