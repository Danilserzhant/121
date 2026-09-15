import pandas as pd, numpy as np, itertools
D=pd.read_pickle('conf3.pkl')
D['period']=pd.cut(D.year,[2019,2021,2023,2026],labels=['20-21','22-23','24-26'])
D['session']=pd.cut(D.hour,[-1,7,12,20,23],labels=['Asia 0-7','London 8-12','NY 13-20','late 21-23'])
D['weekend']=D.wday>=5
EXITS=['far|0.5atr','far|1atr','far|gap','ce|0.5atr','ce|1atr','ext|1atr','ext|2R','ext-0.25atr|1atr']
pd.set_option('display.width',250); pd.set_option('display.max_columns',40)

print('=== ОДИНОЧНЫЕ ФАКТОРЫ КОНТЕКСТА, D при size≥0.5 (react≥1ATR %, n) ===')
d=D[(D.conf=='D')&(D.size_atr>=0.5)]
for col in ['session','weekend','fresh','above200','with_trend','kind']:
    g=d.groupby(col,observed=True).react_1.agg(['mean','size']); print(f'  {col:11s}: '+' | '.join(f'{k}: {v["mean"]*100:.0f}% ({v["size"]})' for k,v in g.iterrows()))
d['vol_b']=pd.cut(d.vol_rel,[0,1,1.5,2.5,99],labels=['<1x','1-1.5x','1.5-2.5x','>2.5x']); g=d.groupby('vol_b',observed=True).react_1.agg(['mean','size'])
print('  объём импульса/ср20: '+' | '.join(f'{k}: {v["mean"]*100:.0f}% ({v["size"]})' for k,v in g.iterrows()))
d['dist_b']=pd.cut(d.dist_ema50_atr,[0,1,2,4,99],labels=['<1','1-2','2-4','>4 ATR']); g=d.groupby('dist_b',observed=True).react_1.agg(['mean','size'])
print('  растяжение от EMA50: '+' | '.join(f'{k}: {v["mean"]*100:.0f}% ({v["size"]})' for k,v in g.iterrows()))

print('\n=== ПОДТВЕРЖДЕНИЯ при size≥0.5: react/EV по выходам (нетто R) ===')
g=D[D.size_atr>=0.5].groupby('conf').agg(n=('react_1','size'),react_1=('react_1','mean'),held24=('held24','mean'),**{e:(e,'mean') for e in EXITS})
g['react_1']*=100; g['held24']*=100; print(g.round(2).sort_values('react_1',ascending=False).to_string())

# ---- перебор с устойчивостью ----
def evalrule(d):
    if len(d)<60: return None
    per=d.groupby('period',observed=True).react_1.mean()
    if len(per)<3: return None
    out=dict(n=len(d),react_1=d.react_1.mean()*100,min_per=per.min()*100,held24=d.held24.mean()*100)
    for e in EXITS: out[e]=d[e].mean()
    pe={e:d.groupby('period',observed=True)[e].mean().min() for e in EXITS}
    out['best_exit']=max(pe,key=pe.get); out['best_exit_minEV']=pe[out['best_exit']]; out['best_exit_EV']=d[out['best_exit']].mean()
    return out
ctx={'—':None,'тренд':'with_trend','EMA200':'above200','свежий≤24ч':'fresh','не выходные':'~weekend','заход<50%':'depth<0.5','объём≥1.5x':'vol_rel>=1.5','сессия Asia':"session=='Asia 0-7'",'сессия NY':"session=='NY 13-20'"}
rows=[]
for conf in D.conf.unique():
    for smin in (0.5,0.75,1.0,1.5):
        for kind in (None,'bull','bear'):
            for cn,cq in ctx.items():
                d=D[(D.conf==conf)&(D.size_atr>=smin)]
                if kind: d=d[d.kind==kind]
                if cq: d=d.query(cq) if cq[0]!='~' else d[~d[cq[1:]]]
                r=evalrule(d)
                if r: rows.append(dict(conf=conf,size=smin,kind=kind or 'оба',ctx=cn,**r))
G=pd.DataFrame(rows); G.to_csv('grid2.csv',index=False)
print(f'\nправил проверено: {len(G)}')
cols=['conf','size','kind','ctx','n','react_1','min_per','held24','best_exit','best_exit_EV','best_exit_minEV']
print('\n=== УСТОЙЧИВЫЕ ПРАВИЛА НА РЕАКЦИЮ: react_1≥60% И ≥55% в каждом периоде ===')
S=G[(G.react_1>=60)&(G.min_per>=55)].sort_values('react_1',ascending=False); print(S[cols].round(2).head(20).to_string(index=False))
print('\n=== УСТОЙЧИВЫЕ ПРАВИЛА НА EV: лучший выход с EV≥+0.1R в среднем И ≥0 в каждом периоде ===')
E=G[(G.best_exit_EV>=0.1)&(G.best_exit_minEV>=0)].sort_values('best_exit_EV',ascending=False); print(E[cols].round(2).head(20).to_string(index=False))
