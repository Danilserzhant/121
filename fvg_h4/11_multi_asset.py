import pandas as pd, numpy as np, glob
E=pd.concat([pd.read_pickle(f) for f in sorted(glob.glob('ev_*.pkl'))],ignore_index=True)
E['period']=pd.cut(E.year,[2019,2021,2023,2026],labels=['20-21','22-23','24-26'])
YRS={'ETHUSDT':6.7,'BTCUSDT':6.7,'BNBUSDT':6.6,'XRPUSDT':6.7,'SOLUSDT':6.0}
EX=['ext|1atr','ce|1atr','far|0.5atr']
pd.set_option('display.width',250)
def sel(d,conf,smin,emin,kind=None):
    m=(d.size_atr>=smin)&(d.ext_atr>=emin)
    m&=(d.conf.isin(['D','CH','E'])) if conf=='any' else (d.conf==conf)
    if kind: m&=(d.kind==kind)
    x=d[m]
    return x.drop_duplicates('fid') if conf=='any' else x
def st(x,yrs):
    if len(x)<30: return None
    per=x.groupby('period',observed=True).react_1.mean()
    r=dict(n=len(x),в_год=round(len(x)/yrs,1),react=round(x.react_1.mean()*100,1),min_per=round(per.min()*100,1) if len(per)==3 else np.nan)
    for e in EX: r[e]=round(x[e].mean(),2); r[e+'_min']=round(x.groupby('period',observed=True)[e].mean().min(),2)
    return r

print('=== 1. ETH H4/M15: КРИВАЯ ЧАСТОТА↔КАЧЕСТВО (подтв. = любое из D/CH/E, одно событие на гэп) ===')
d=E[(E['sym']=='ETHUSDT')&(E.label=='H4')]; rows=[]
for smin in (0.5,0.75):
    for emin in (0,1,2,3,4):
        r=st(sel(d,'any',smin,emin),6.7)
        if r: rows.append(dict(size=smin,ext=emin,**r))
print(pd.DataFrame(rows).to_string(index=False))
print('\n   то же, только CH:'); rows=[]
for emin in (0,2,3,4):
    r=st(sel(d,'CH',0.5,emin),6.7)
    if r: rows.append(dict(size=0.5,ext=emin,**r))
print(pd.DataFrame(rows).to_string(index=False))

print('\n=== 2. КРОСС-МОНЕТНАЯ ПРОВЕРКА, H4/M15 ===')
for nm,conf,smin,emin in [('R-H: CH, size≥0.5, ext≥4','CH',0.5,4),('R-H\': CH, size≥0.5, ext≥3','CH',0.5,3),('R-I\': любое D/CH/E, size≥0.75, ext≥3','any',0.75,3),('контроль: любое, size≥0.5, ext≥0','any',0.5,0)]:
    print(f'\n-- {nm}'); rows=[]
    for sym in ['ETHUSDT','BTCUSDT','SOLUSDT','BNBUSDT','XRPUSDT']:
        r=st(sel(E[(E['sym']==sym)&(E.label=='H4')],conf,smin,emin),YRS[sym])
        if r: rows.append(dict(sym=sym,**r))
    pool=sel(E[E.label=='H4'],conf,smin,emin); rp=st(pool,1); 
    if rp: rp['в_год']=round(len(pool)/6.5,1); rows.append(dict(sym='ВСЕ 5 (сумма)',**rp))
    print(pd.DataFrame(rows).to_string(index=False))

print('\n=== 3. H1 FVG / M5 подтверждение (ETH, BTC, SOL) ===')
for nm,conf,smin,emin in [('CH, size≥0.5, ext≥4','CH',0.5,4),('CH, size≥0.5, ext≥3','CH',0.5,3),('любое D/CH/E, size≥0.75, ext≥3','any',0.75,3),('любое, size≥0.75, ext≥4','any',0.75,4),('контроль: любое, size≥0.5, ext≥0','any',0.5,0)]:
    print(f'\n-- {nm}'); rows=[]
    for sym in ['ETHUSDT','BTCUSDT','SOLUSDT']:
        r=st(sel(E[(E['sym']==sym)&(E.label=='H1')],conf,smin,emin),YRS[sym])
        if r: rows.append(dict(sym=sym,**r))
    pool=sel(E[E.label=='H1'],conf,smin,emin); rp=st(pool,1)
    if rp: rp['в_год']=round(len(pool)/6.5,1); rows.append(dict(sym='ВСЕ 3 (сумма)',**rp))
    print(pd.DataFrame(rows).to_string(index=False))
E.to_pickle('ev_all.pkl')
