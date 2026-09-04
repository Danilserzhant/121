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


def format_top(result: ScanResult, n: int, by: str = "atr") -> str:
    rows = result.top(n, by)
    if not rows:
        return "Не удалось получить данные — нет ни одной монеты с достаточной историей."
    tf = result.interval
    candle = _utc(rows[0].candle_time, tf)
    if by == "expansion":
        title = f"📈 <b>Топ по росту ATR · {tf_name(tf)}</b>"
    else:
        title = f"📊 <b>Топ по ATR в % цены · {tf_name(tf)}</b>"
    head = (
        f"{title}\n"
        f"Биржа: {html.escape(result.exchange)} · свеча {candle} UTC\n"
        f"ATR({result.atr_period}), сравнение с {_window(tf, result.lookback)} назад · "
        f"{len(result.ranked)} монет\n"
    )
    lines = [f"{'#':>2} {'Монета':<10} {'ATR%':>6} {'ΔATR':>7} {'Свеча':>6} {'Ход':>7}"]
    for i, m in enumerate(rows, start=1):
        sym = m.symbol.removesuffix("USDT") if m.symbol.endswith("USDT") else m.symbol
        lines.append(
            f"{i:>2} {sym:<10} {m.atr_pct:>5.2f}% {m.expansion_pct:>+6.0f}% {m.last_tr_pct:>5.1f}% {m.move_pct:>+6.1f}%"
        )
    table = "<pre>" + html.escape("\n".join(lines)) + "</pre>"
    legend = (
        f"\n<i>ATR% — средний ход за {TF_UNIT.get(tf, 'свечу')} в % цены · ΔATR — рост ATR к значению "
        f"{_window(tf, result.lookback)} назад · Свеча — диапазон последней свечи в % · "
        f"Ход — чистое движение цены за {_window(tf, result.lookback)}</i>"
    )
    return head + table + legend


def format_symbol(symbol: str, per_tf: dict[str, AtrMetrics | None], ranks: dict[str, tuple[int, int]]) -> str:
    """One coin across all timeframes. ranks: {interval: (rank, total)}."""
    first = next((m for m in per_tf.values() if m is not None), None)
    if first is None:
        return f"По <code>{html.escape(symbol)}</code> слишком мало истории."
    lines = [f"{'ТФ':<3} {'ATR%':>6} {'ΔATR':>6} {'Свеча':>6} {'Ход':>7} {'Место':>6}"]
    for tf, m in per_tf.items():
        if m is None:
            lines.append(f"{tf_name(tf):<3} {'—':>6}  мало истории")
            continue
        rank = ranks.get(tf)
        rank_txt = f"#{rank[0]}/{rank[1]}" if rank else "—"
        lines.append(
            f"{tf_name(tf):<3} {m.atr_pct:>5.2f}% {m.expansion_pct:>+5.0f}% {m.last_tr_pct:>5.1f}% {m.move_pct:>+6.1f}% {rank_txt:>6}"
        )
    return (
        f"🔎 <b>{html.escape(symbol)}</b> · цена <code>{_fmt_price(first.close)}</code> · "
        f"оборот 24ч {first.quote_volume/1e6:.1f}M\n"
        "<pre>" + html.escape("\n".join(lines)) + "</pre>\n"
        "<i>ATR% — средний ход за свечу в % цены · ΔATR — рост ATR к окну сравнения · "
        "Ход — движение цены за окно · Место — в рейтинге по ATR% (если сканировали)</i>"
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
        "Изменить: <code>/set период 14</code>, <code>/set окно 4h 6</code>, "
        "<code>/set топ 20</code>, <code>/set оборот 10000000</code>, <code>/set atr 1.5</code>"
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
    "/atr SOL — монета на всех таймфреймах сразу\n"
    "/sub — присылать часовой топ автоматически после закрытия свечи\n"
    "/unsub — отключить рассылку\n"
    "/myid — мой Telegram ID и роль\n"
    "/help — эта справка"
)
