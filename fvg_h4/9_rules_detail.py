import pandas as pd, numpy as np
D=pd.read_pickle('conf3.pkl')
D['period']=pd.cut(D.year,[2019,2021,2023,2026],labels=['20-21','22-23','24-26'])
D['session']=pd.cut(D.hour,[-1,7,12,20,23],labels=['Asia','London','NY','late'])
D['ext4']=D.dist_ema50_atr>4
# частичный выход: 50% на 0.5 ATR + 50% на 1 ATR, общий стоп (приближение без переноса в БУ)
for s in ['far','ce','ext']: D[f'{s}|part']=0.5*D[f'{s}|0.5atr']+0.5*D[f'{s}|1atr']
YEARS=6.7; pd.set_option('display.width',250)
rules={
 'R-A: D, size≥0.75, сторона EMA200':          (D.conf=='D')&(D.size_atr>=0.75)&D.above200,
 'R-B: A→D, size≥0.75, сторона EMA200':        (D.conf=='A→D')&(D.size_atr>=0.75)&D.above200,
 'R-C: CH, size≥1.5':                          (D.conf=='CH')&(D.size_atr>=1.5),
 'R-D: CH, size≥0.75, bull, NY':               (D.conf=='CH')&(D.size_atr>=0.75)&(D.kind=='bull')&(D.session=='NY'),
 'R-E: E, size≥1.0, bull, сторона EMA200':     (D.conf=='E')&(D.size_atr>=1.0)&(D.kind=='bull')&D.above200,
 'R-F: C, size≥1.0, bull':                     (D.conf=='C')&(D.size_atr>=1.0)&(D.kind=='bull'),
 'R-G: D, size≥0.5, растяжение>4ATR':          (D.conf=='D')&(D.size_atr>=0.5)&D.ext4,
 'R-H: CH, size≥0.5, растяжение>4ATR':         (D.conf=='CH')&(D.size_atr>=0.5)&D.ext4,
 'R-I: любое из D/CH/E, size≥0.75, растяж>4':  (D.conf.isin(['D','CH','E']))&(D.size_atr>=0.75)&D.ext4,
 'R-J: D, size≥0.75, объём≥2.5x':              (D.conf=='D')&(D.size_atr>=0.75)&(D.vol_rel>=2.5),
 'R-K: D, size≥0.75, EMA200, объём≥1.5x':      (D.conf=='D')&(D.size_atr>=0.75)&D.above200&(D.vol_rel>=1.5),
}
EX=['far|0.5atr','far|1atr','far|part','ce|1atr','ce|part','ext|1atr','ext|part','ext-0.25atr|1atr']
print('=== РЕАКЦИЯ ПО ПЕРИОДАМ (react≥1ATR %, n) и сделок/год ===')
for nm,m in rules.items():
    d=D[m]; 
    if nm.startswith('R-I'): d=d.drop_duplicates('fid')     # одно событие на гэп
    per=d.groupby('period',observed=True).react_1.agg(['mean','size'])
    cells=' | '.join(f'{k}: {v["mean"]*100:4.0f}% ({int(v["size"]):3d})' for k,v in per.iterrows())
    print(f'{nm:45s} всего {d.react_1.mean()*100:4.1f}% (n={len(d):3d}, {len(d)/YEARS:4.1f}/год) | {cells}')
print('\n=== EV ПО ВЫХОДАМ (нетто R; в скобках — минимум по периодам) ===')
hdr=f'{"правило":45s}'+''.join(f'{e:>18s}' for e in EX); print(hdr)
for nm,m in rules.items():
    d=D[m]
    if nm.startswith('R-I'): d=d.drop_duplicates('fid')
    cells=''
    for e in EX:
        mn=d.groupby('period',observed=True)[e].mean().min(); cells+=f'{d[e].mean():+6.2f} ({mn:+5.2f})'.rjust(18)
    print(f'{nm:45s}'+cells)
print('\n=== риск на сделку (медиана, % от цены) по стопам ===')
for nm,m in list(rules.items())[:6]:
    d=D[m]; print(f'{nm:45s} far {d["far|risk"].median():.2f}%  ce {d["ce|risk"].median():.2f}%  ext {d["ext|risk"].median():.2f}%')
