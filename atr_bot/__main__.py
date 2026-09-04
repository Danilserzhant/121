"""Entry point.

    python -m atr_bot            # run the Telegram bot
    python -m atr_bot scan       # one-off scan printed to stdout (no Telegram needed)
    python -m atr_bot scan --top 30 --exchange okx
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import re
import sys

from .config import settings
from .exchanges import ExchangeError
from .scanner import Scanner


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text)


async def _scan_cli(args: argparse.Namespace) -> None:
    from .formatting import format_symbol, format_top

    if args.exchange:
        settings.exchange = args.exchange
    if args.period:
        settings.atr_period = args.period
    if args.lookback:
        settings.lookbacks[args.interval or settings.interval] = args.lookback
    if args.interval:
        settings.interval = args.interval
    if args.volume is not None:
        settings.min_quote_volume = args.volume
    async with Scanner(settings) as scanner:
        if args.symbol:
            per_tf = await scanner.symbol_metrics(args.symbol)
            print(_strip_html(format_symbol(scanner.normalize_symbol(args.symbol), per_tf, {})) if per_tf else "symbol not found")
            return
        result = await scanner.scan(settings.interval, force=True)
        print(_strip_html(format_top(result, args.top or settings.top_n, view=args.view)))
        print(f"\n{len(result.ranked)} coins ranked, {result.errors} errors, {result.duration:.1f}s")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="atr_bot", description="ATR expansion Telegram bot")
    sub = parser.add_subparsers(dest="cmd")
    scan = sub.add_parser("scan", help="run one scan and print it")
    scan.add_argument("--top", type=int, default=None)
    scan.add_argument("--exchange", default=None, help="binance_futures | binance_spot | bybit | okx")
    scan.add_argument("--interval", "-i", default=None, help="1h | 4h | 1d | 1w")
    scan.add_argument("--period", type=int, default=None)
    scan.add_argument("--lookback", type=int, default=None)
    scan.add_argument("--volume", type=float, default=None, help="min 24h quote volume")
    scan.add_argument("--symbol", default=None, help="details for one symbol instead of the ranking")
    scan.add_argument("--view", default="list", choices=["list", "table"])
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    if args.cmd == "scan":
        try:
            asyncio.run(_scan_cli(args))
        except ExchangeError as exc:
            print(f"Exchange error: {exc}", file=sys.stderr)
            sys.exit(2)
    else:
        from .bot import run_bot

        try:
            asyncio.run(run_bot(settings))
        except (KeyboardInterrupt, SystemExit) as exc:
            if isinstance(exc, SystemExit) and exc.code:
                print(exc.code, file=sys.stderr)
                sys.exit(1)


if __name__ == "__main__":
    main()
