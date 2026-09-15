import pandas as pd, numpy as np, itertools
D=pd.read_pickle('conf.pkl'); F=pd.read_pickle('fvg_all.pkl'); H4=pd.read_pickle('h4.pkl'); m1=pd.read_parquet('m1.parquet')
mh,ml,mc=(m1[c].to_numpy(float) for c in ['high','low','close'])
H15=mh.reshape(-1,15).max(1); L15=ml.reshape(-1,15).min(1); C15=mc[14::15]; N15=len(C15)
O4,Hh,L4,C4=(H4[c].to_numpy(float) for c in ['open','high','low','close'])
tr=np.maximum(Hh-L4,np.maximum(abs(Hh-np.roll(C4,1)),abs(L4-np.roll(C4,1)))); ATR=pd.Series(tr).rolling(14).mean().to_numpy()
Fi=F.i.to_numpy(); Ft0=F.t0.to_numpy()
# тесный стоп: экстремум теста (от M15 касания до подтверждения) ; цели 1 ATR и 2R ; горизонт 7 дней ; комиссия 0.1% оборот
FEE=0.001; HOR=7*24*4
def tight(row):
    kind=row.kind; c=int(row.c); i=int(Fi[row.fid]); atr=ATR[i]; c0=int(Ft0[row.fid])*4
    entry=C15[c]
    stop=L15[c0:c+1].min() if kind=='bull' else H15[c0:c+1].max()
    R=abs(entry-stop)
    if R<=0: return pd.Series(dict(t_R=np.nan))
    sh,sl=H15[c+1:c+1+HOR],L15[c+1:c+1+HOR]
    s_hit=np.flatnonzero(sl<=stop) if kind=='bull' else np.flatnonzero(sh>=stop)
    si=s_hit[0] if s_hit.size else 10**9
    res={}
    for nm,tgt in [('1ATR',atr),('2R',2*R),('1R',R)]:
        t_hit=np.flatnonzero(sh>=entry+tgt) if kind=='bull' else np.flatnonzero(sl<=entry-tgt)
        ti=t_hit[0] if t_hit.size else 10**9
        if ti<si: r=tgt/R
        elif si<10**9: r=-1.0
        else: ex=C15[min(c+HOR,N15-1)]; r=((ex-entry) if kind=='bull' else (entry-ex))/R
        res[f'R_{nm}']=r-FEE*entry/R
    res['t_risk_pct']=R/entry*100; res['rr_1atr']=atr/R
    return pd.Series(res)
D=D.join(D.apply(tight,axis=1))
D.to_pickle('conf2.pkl')
pd.set_option('display.width',230)

def summ(d):
    return dict(n=len(d),react_1=round(d.react_1.mean()*100,1),react_05=round(d.react_05.mean()*100,1),held24=round(d.held24.mean()*100,1),
                win_1ATR=round((d.R_1ATR>0).mean()*100,1),avgR_1ATR=round(d.R_1ATR.mean(),3),avgR_2R=round(d.R_2R.mean(),3),
                risk_med=round(d.t_risk_pct.median(),2),rr_med=round(d.rr_1atr.median(),2))
print('=== ПОИСК: react≥1ATR ≥ 60%, n ≥ 80 (все комбинации фильтров × подтверждение) ===')
rows=[]
for conf in sorted(D.conf.unique()):
    for smin in (0.3,0.5,0.75,1.0):
        for dmax in (0.25,0.5,1.01):
            for trend in (None,True):
                for kind in (None,'bull','bear'):
                    d=D[(D.conf==conf)&(D.size_atr>=smin)&(D.depth<dmax)]
                    if trend: d=d[d.with_trend]
                    if kind: d=d[d.kind==kind]
                    if len(d)<80: continue
                    rows.append(dict(conf=conf[:2],size_min=smin,depth_max=dmax,trend=bool(trend),kind=kind or 'оба',**summ(d)))
G=pd.DataFrame(rows); G.to_csv('grid.csv',index=False)
top=G[G.react_1>=60].sort_values(['react_1'],ascending=False)
print(f'комбинаций всего {len(G)}, с react_1≥60%: {len(top)}')
print(top.head(25).to_string(index=False))
print('\n=== лучшие по EV сделки (стоп за экстремумом теста, цель 1 ATR, нетто), n≥80 ===')
print(G.sort_values('avgR_1ATR',ascending=False).head(12).to_string(index=False))
