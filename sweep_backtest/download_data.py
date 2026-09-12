"""Скачивает историю ETHUSDT USDT-M Perp (Binance) 1h и 1m из bulk-архива.

REST api (fapi.binance.com) может быть недоступен по гео-ограничению,
но статический архив data.binance.vision отдаётся без ограничений.
"""
import datetime, os, subprocess, sys

BASE = "https://data.binance.vision/data/futures/um"
SYMBOL = "ETHUSDT"
START = datetime.date(2020, 1, 1)


def months(end: datetime.date):
    d = START
    while d <= end:
        yield d.strftime("%Y-%m")
        d = (d.replace(day=28) + datetime.timedelta(days=6)).replace(day=1)


def fetch(url: str, dest: str) -> bool:
    if os.path.exists(dest):
        return True
    r = subprocess.run(["curl", "-sS", "-f", "--max-time", "180", "-o", dest, url])
    return r.returncode == 0


def main(tf: str, last_full_month: datetime.date, last_day: datetime.date):
    out = f"data/{tf}"
    os.makedirs(out, exist_ok=True)
    for mth in months(last_full_month):
        fetch(f"{BASE}/monthly/klines/{SYMBOL}/{tf}/{SYMBOL}-{tf}-{mth}.zip",
              f"{out}/{SYMBOL}-{tf}-{mth}.zip")
    day = last_full_month.replace(day=28) + datetime.timedelta(days=6)
    day = day.replace(day=1)
    while day <= last_day:
        fetch(f"{BASE}/daily/klines/{SYMBOL}/{tf}/{SYMBOL}-{tf}-{day}.zip",
              f"{out}/{SYMBOL}-{tf}-{day}.zip")
        day += datetime.timedelta(days=1)


if __name__ == "__main__":
    last_full = datetime.date(2026, 8, 1)
    last_day = datetime.date(2026, 9, 11)
    for tf in ("1h", "1m"):
        main(tf, last_full, last_day)
        print(tf, "ok")
