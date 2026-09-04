"""Telegram (HTML) message formatting."""

from __future__ import annotations

import html
from datetime import datetime, timezone

from .indicators import AtrMetrics
from .scanner import ScanResult


def _fmt_price(p: float) -> str:
    if p >= 1000:
        return f"{p:,.1f}"
    if p >= 1:
        return f"{p:.4f}"
    return f"{p:.6g}"


def _sign(v: float, digits: int = 1) -> str:
    return f"{v:+.{digits}f}%"


def _utc(ts_ms: int) -> str:
    return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).strftime("%d.%m %H:%M")


def format_top(result: ScanResult, n: int, by: str = "atr") -> str:
    rows = result.top(n, by)
    if not rows:
        return "Не удалось получить данные — нет ни одной монеты с достаточной историей."
    candle = _utc(rows[0].candle_time)
    if by == "expansion":
        title = f"📈 <b>Топ по росту ATR, {result.interval} свечи</b>"
    else:
        title = f"📊 <b>Топ по ATR в % цены, {result.interval} свечи</b>"
    head = (
        f"{title}\n"
        f"Биржа: {html.escape(result.exchange)} · свеча {candle} UTC\n"
        f"ATR({result.atr_period}), сравнение с {result.lookback} свеч назад · "
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
        "\n<i>ATR% — средний ход за час в % цены · ΔATR — рост ATR к значению "
        f"{result.lookback}ч назад · Свеча — диапазон последней свечи в % · "
        f"Ход — чистое движение цены за {result.lookback}ч</i>"
    )
    return head + table + legend


def format_symbol(m: AtrMetrics, result: ScanResult | None, interval: str) -> str:
    rank = result.rank_of(m.symbol) if result else None
    rank_line = f"Место в рейтинге: <b>#{rank}</b> из {len(result.ranked)}\n" if rank else ""
    return (
        f"🔎 <b>{html.escape(m.symbol)}</b> · {interval} · свеча {_utc(m.candle_time)} UTC\n"
        f"{rank_line}"
        f"Цена: <code>{_fmt_price(m.close)}</code>\n"
        f"ATR: <code>{_fmt_price(m.atr)}</code> = <b>{m.atr_pct:.2f}%</b> цены\n"
        f"ATR раньше: {m.atr_prev_pct:.2f}% → расширение <b>{_sign(m.expansion_pct, 0)}</b>\n"
        f"Последняя свеча: {m.last_tr_pct:.2f}% ({m.last_tr_ratio:.1f}× старого ATR)\n"
        f"Чистый ход: <b>{_sign(m.move_pct)}</b>\n"
        f"Оборот 24ч: {m.quote_volume/1e6:.1f}M"
    )


def format_settings(s) -> str:  # noqa: ANN001 - Settings, avoid circular import in typing
    return (
        "⚙️ <b>Настройки сканера</b>\n"
        f"Биржа: <code>{html.escape(s.exchange)}</code> · котировка {s.quote_asset}\n"
        f"Таймфрейм: <code>{s.interval}</code>\n"
        f"ATR период: <code>{s.atr_period}</code>\n"
        f"Окно расширения: <code>{s.lookback}</code> свеч\n"
        f"Топ по умолчанию: <code>{s.top_n}</code>\n"
        f"Мин. оборот 24ч: <code>{s.min_quote_volume:,.0f}</code> {s.quote_asset}\n"
        f"Мин. ATR%: <code>{s.min_atr_pct}</code>\n"
        f"Кэш результата: <code>{s.cache_ttl}</code> с\n\n"
        "Изменить: <code>/set период 14</code>, <code>/set окно 24</code>, "
        "<code>/set топ 20</code>, <code>/set оборот 10000000</code>, <code>/set atr 1.5</code>"
    )


HELP = (
    "🤖 <b>ATR Expansion Bot</b>\n"
    "Считаю ATR по часовым свечам для всех монет биржи и показываю самые "
    "волатильные — ATR в % цены, то есть чистое движение за час.\n\n"
    "<b>Команды</b>\n"
    "/top [N] — топ N монет с самым высоким ATR в % цены (средний ход за час)\n"
    "/exp [N] — топ N монет по росту ATR (волатильность расширяется)\n"
    "/atr SYMBOL — подробности по монете, например <code>/atr SOL</code>\n"
    "/sub — присылать топ автоматически после закрытия каждой часовой свечи\n"
    "/unsub — отключить рассылку\n"
    "/settings — текущие параметры\n"
    "/set параметр значение — изменить параметр (только админы)\n"
    "/help — эта справка"
)
