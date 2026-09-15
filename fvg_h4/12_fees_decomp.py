import pandas as pd, numpy as np
E=pd.read_pickle('ev_all.pkl'); E['period']=pd.cut(E.year,[2019,2021,2023,2026],labels=['20-21','22-23','24-26'])
pd.set_option('display.width',250)
def sel(d,conf,smin,emin):
    m=(d.size_atr>=smin)&(d.ext_atr>=emin)&((d.conf.isin(['D','CH','E'])) if conf=='any' else (d.conf==conf))
    x=d[m]; return x.drop_duplicates('fid') if conf=='any' else x
def decomp(x,stop,tgt,label):
    col=f'{stop}|{tgt}'; risk=x[f'{stop}|risk']/100; ev_net=x[col]
    ev_gross=ev_net+0.001/risk                         # вернуть тейкер 0.05%×2
    out={'выборка':label,'n':len(x),'winrate':round((ev_gross>0).mean()*100,1)}
    wins=ev_gross[ev_gross>0]; out['RR медиана']=round(wins.median(),2) if len(wins) else np.nan   # размер выигрыша в R = цель/риск
    out['риск% мед']=round(risk.median()*100,2)
    for nm,fee in [('без комиссии',0.0),('мейкер 0.02%×2',0.0004),('тейкер 0.05%×2',0.001)]:
        ev=ev_gross-fee/risk; out[nm]=round(ev.mean(),3)
        out[nm+' мин.пер']=round((ev.groupby(x.period,observed=True).mean()).min(),2)
    return out
rows=[]
for lbl,conf,smin,emin,tf in [('H4 ETH: CH s≥0.5 ext≥4','CH',0.5,4,'H4'),('H4 5 монет: CH s≥0.5 ext≥4','CH',0.5,4,'H4'),('H4 5 монет: любое s≥0.75 ext≥3','any',0.75,3,'H4'),
                              ('H1 3 монеты: CH s≥0.5 ext≥3','CH',0.5,3,'H1'),('H1 3 монеты: любое s≥0.75 ext≥3','any',0.75,3,'H1'),('H1 3 монеты: любое s≥0.75 ext≥4','any',0.75,4,'H1')]:
    d=E[E.label==tf]; 
    if 'ETH' in lbl: d=d[d['sym']=='ETHUSDT']
    x=sel(d,conf,smin,emin)
    for stop,tgt in [('ext','1atr'),('ce','1atr'),('far','0.5atr')]:
        rows.append({**decomp(x,stop,tgt,lbl),'выход':f'{stop}|{tgt}'})
R=pd.DataFrame(rows)
print('=== ДЕКОМПОЗИЦИЯ: winrate, RR, риск и EV при разной комиссии (R на сделку, в скобках нет — отдельный столбец мин. по периодам) ===')
print(R[['выборка','выход','n','winrate','RR медиана','риск% мед','без комиссии','мейкер 0.02%×2','мейкер 0.02%×2 мин.пер','тейкер 0.05%×2','тейкер 0.05%×2 мин.пер']].to_string(index=False))
