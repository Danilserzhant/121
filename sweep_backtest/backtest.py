"""Бэктест сетапа «закрытие свипом» на ETHUSDT Perp 1h.

Сетап (лонг): часовая свеча снимает минимум предыдущей часовой (low[i] < low[i-1])
и закрывается обратно выше него. Тестируются варианты строгости «закрытия»,
зеркальный шорт, разная глубина свипа и база сравнения «все свечи».

Вход  — по закрытию сигнальной свечи (тейкер).
Стоп  — экстремум сигнальной свечи (минимум для лонга).
Цель  — 1R / 2R / 3R, где R = |вход - стоп|.
Выход — по времени через 24 часа, если ни стоп, ни цель не задеты.
Очерёдность стоп/цель внутри часа определяется по минутным данным;
если оба уровня задеты одной минутой — считаем стоп (консервативно).
Комиссия — 0.05% тейкер с каждой стороны.
"""
import glob
import zipfile

import numpy as np
import pandas as pd

COLS = ['open_time', 'open', 'high', 'low', 'close', 'volume', 'close_time',
        'quote_volume', 'count', 'taker_buy_volume', 'taker_buy_quote_volume', 'ignore']
FEE = 0.0005
HORIZON = 24


def load(tf):
    frames = []
    for z in sorted(glob.glob(f'data/{tf}/ETHUSDT-{tf}-*.zip')):
        with zipfile.ZipFile(z) as zf:
            df = pd.read_csv(zf.open(zf.namelist()[0]), header=None, names=COLS)
        if str(df.iloc[0, 0]) == 'open_time':
            df = df.iloc[1:]
        frames.append(df)
    d = pd.concat(frames, ignore_index=True)
    for c in ['open_time', 'open', 'high', 'low', 'close', 'volume']:
        d[c] = pd.to_numeric(d[c], errors='coerce')
    d = d.dropna(subset=['open_time', 'open', 'high', 'low', 'close'])
    d['ts'] = pd.to_datetime(d['open_time'], unit='ms', utc=True)
    return (d.drop_duplicates(subset='open_time').sort_values('open_time')
             .reset_index(drop=True)[['open_time', 'ts', 'open', 'high', 'low', 'close', 'volume']])


class Book:
    def __init__(self, h, m):
        assert len(m) == len(h) * 60, 'минутный ряд должен быть выровнен по часам'
        self.h, self.n = h, len(h)
        self.O, self.H, self.L, self.C = (h[c].to_numpy(float) for c in ['open', 'high', 'low', 'close'])
        self.mH, self.mL, self.mC = (m[c].to_numpy(float) for c in ['high', 'low', 'close'])

    def sim(self, idx, side, rr, horizon=HORIZON, fee=FEE):
        rows = []
        for i in idx:
            if i + 1 + horizon >= self.n:
                continue
            entry = self.C[i]
            stop = self.L[i] if side == 'long' else self.H[i]
            risk = abs(entry - stop)
            if risk <= 0:
                continue
            tp = entry + rr * risk if side == 'long' else entry - rr * risk
            a, b = (i + 1) * 60, (i + 1) * 60 + horizon * 60
            hi, lo = self.mH[a:b], self.mL[a:b]
            s_hit = np.flatnonzero(lo <= stop) if side == 'long' else np.flatnonzero(hi >= stop)
            t_hit = np.flatnonzero(hi >= tp) if side == 'long' else np.flatnonzero(lo <= tp)
            si = s_hit[0] if s_hit.size else 10 ** 9
            ti = t_hit[0] if t_hit.size else 10 ** 9
            if si == ti == 10 ** 9:
                ex = self.mC[b - 1]
                r = (ex - entry) / risk if side == 'long' else (entry - ex) / risk
            elif ti < si:
                r = rr
            else:
                r = -1.0
            rows.append((i, r, r - fee * 2 * entry / risk, risk / entry * 100))
        return pd.DataFrame(rows, columns=['i', 'R', 'Rnet', 'risk_pct'])


def stats(d, label):
    if d.empty:
        return None
    gain = d.Rnet[d.Rnet > 0].sum()
    loss = -d.Rnet[d.Rnet < 0].sum()
    eq = d.sort_values('i').Rnet.cumsum()
    return dict(setup=label, n=len(d), winrate=round((d.Rnet > 0).mean() * 100, 1),
                avgR_gross=round(d.R.mean(), 4), avgR_net=round(d.Rnet.mean(), 4),
                sumR_net=round(d.Rnet.sum(), 1),
                PF=round(gain / loss, 2) if loss > 0 else np.inf,
                maxDD_R=round((eq - eq.cummax()).min(), 1),
                risk_pct_med=round(d.risk_pct.median(), 3),
                t_stat=round(d.Rnet.mean() / (d.Rnet.std() / np.sqrt(len(d))), 2))


def signals(b):
    L, H, C = b.L, b.H, b.C
    pl, ph, pc = np.roll(L, 1), np.roll(H, 1), np.roll(C, 1)
    top = (C - L) / np.where(H - L > 0, H - L, np.nan)
    return {
        'L0 свип+реклейм (C>prevLow)':      ((L < pl) & (C > pl), 'long'),
        'L1 свип+C>prevClose':              ((L < pl) & (C > pc), 'long'),
        'L2 свип+C>prevHigh (outside bar)': ((L < pl) & (C > ph), 'long'),
        'L3 свип+реклейм+закр. верх.25%':   ((L < pl) & (C > pl) & (top >= 0.75), 'long'),
        'L4 свип+C>prevHigh+верх.25%':      ((L < pl) & (C > ph) & (top >= 0.75), 'long'),
        'S0 свип+реклейм (C<prevHigh)':     ((H > ph) & (C < ph), 'short'),
        'S2 свип+C<prevLow (outside bar)':  ((H > ph) & (C < pl), 'short'),
        'S4 свип+C<prevLow+нижн.25%':       ((H > ph) & (C < pl) & (top <= 0.25), 'short'),
    }


def forward_returns(b, sig):
    """Направленный эдж без стопов: форвардная доходность против базы «все свечи»."""
    rows = []
    for k in (1, 4, 12, 24):
        fwd = np.full(b.n, np.nan)
        fwd[:b.n - k] = (b.C[k:] / b.C[:b.n - k] - 1) * 100
        base = fwd[1:b.n - k]
        rows.append(dict(выборка='БАЗА все свечи', гориз=f'+{k}ч', n=len(base),
                         ср_проц=round(np.nanmean(base), 4), доля_плюс=round(np.nanmean(base > 0) * 100, 1), t=np.nan))
        for name, (mask, side) in sig.items():
            v = fwd[np.flatnonzero(mask[1:b.n - k]) + 1]
            v = v[~np.isnan(v)]
            if side == 'short':
                v = -v
            rows.append(dict(выборка=name, гориз=f'+{k}ч', n=len(v), ср_проц=round(v.mean(), 4),
                             доля_плюс=round((v > 0).mean() * 100, 1),
                             t=round(v.mean() / (v.std() / np.sqrt(len(v))), 2)))
    return pd.DataFrame(rows)


def sweep_depth(b, side='long', rr=2.0, depths=(1, 3, 6, 12, 24, 48, 72)):
    """Свип экстремума N часов вместо только предыдущей свечи."""
    rows = []
    for k in depths:
        if side == 'long':
            prior = pd.Series(b.L).shift(1).rolling(k).min().to_numpy()
            mask = (b.L < prior) & (b.C > prior)
        else:
            prior = pd.Series(b.H).shift(1).rolling(k).max().to_numpy()
            mask = (b.H > prior) & (b.C < prior)
        d = b.sim(np.flatnonzero(mask[1:]) + 1, side, rr)
        st = stats(d, f'{side} свип экстремума {k}ч | TP {rr:g}R')
        if st:
            rows.append(st)
    return pd.DataFrame(rows)


def main():
    h, m = load('1h'), load('1m')
    b = Book(h, m)
    sig = signals(b)
    print(f'данные: {b.n} часовых свечей, {h.ts.min()} -> {h.ts.max()}\n')

    print('=== ЧАСТОТА СИГНАЛА ===')
    for name, (mask, _) in sig.items():
        print(f'  {name:35s} {mask[1:].sum():6d} = {mask[1:].mean() * 100:5.1f}% всех часов')

    core = []
    for rr in (1.0, 2.0, 3.0):
        for name, (mask, side) in sig.items():
            st = stats(b.sim(np.flatnonzero(mask[1:]) + 1, side, rr), f'{name} | TP {rr:g}R')
            if st:
                core.append(st)
        for side in ('long', 'short'):
            st = stats(b.sim(np.arange(1, b.n - HORIZON - 1), side, rr),
                       f'ZZ БАЗА все свечи {side} | TP {rr:g}R')
            if st:
                core.append(st)
    core = pd.DataFrame(core).sort_values('setup')
    core.to_csv('results_core.csv', index=False)

    fwd = forward_returns(b, sig)
    fwd.to_csv('results_forward.csv', index=False)
    depth = pd.concat([sweep_depth(b, 'long'), sweep_depth(b, 'short')], ignore_index=True)
    depth.to_csv('results_depth.csv', index=False)

    pd.set_option('display.width', 250)
    for title, df in [('ОСНОВНОЙ ПРОГОН', core), ('ФОРВАРДНАЯ ДОХОДНОСТЬ vs БАЗА', fwd),
                      ('ГЛУБИНА СВИПА', depth)]:
        print(f'\n=== {title} ===')
        print(df.to_string(index=False))


if __name__ == '__main__':
    main()
