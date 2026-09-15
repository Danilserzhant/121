import pandas as pd, numpy as np
F=pd.read_pickle('fvg_all.pkl'); H4=pd.read_pickle('h4.pkl'); h=pd.read_pickle('h1s.pkl')
O,Hh,L,C=(H4[c].to_numpy(float) for c in ['open','high','low','close'])
tr=np.maximum(Hh-L,np.maximum(abs(Hh-np.roll(C,1)),abs(L-np.roll(C,1)))); ATR=pd.Series(tr).rolling(14).mean().to_numpy()
hi_,lo_=h.high.to_numpy(float),h.low.to_numpy(float); NH=len(h); h4s=h.index[h.open_time.isin(H4.h4)].to_numpy()
rng=np.random.default_rng(11)
def walk(kind,bot,top,s,atr,HMAX=168):
    near,far=(top,bot) if kind=='bull' else (bot,top)
    t=np.flatnonzero(lo_[s:]<=near) if kind=='bull' else np.flatnonzero(hi_[s:]>=near)
    if t.size==0: return None
    t0=s+t[0]; sliced=(lo_[t0]<far) if kind=='bull' else (hi_[t0]>far)
    sh,sl=hi_[t0+1:t0+1+HMAX],lo_[t0+1:t0+1+HMAX]
    fill=np.flatnonzero(sl<far) if kind=='bull' else np.flatnonzero(sh>far)
    exc=(sh-near) if kind=='bull' else (near-sl)
    upto=0 if sliced else (fill[0] if fill.size else len(exc)); mfe=exc[:upto].max() if upto>0 else 0
    fh=0 if sliced else (fill[0]+1 if fill.size else None)
    return dict(react_1=mfe>=atr, held24=(fh is None or fh>24))
rows=[]
for rep in range(3):                      # 3 теневых зоны на каждый FVG для устойчивости
    for r in F.itertuples():
        s=h4s[r.i]+4
        if s>=NH: continue
        off=rng.uniform(0.5,2.0)*ATR[r.i]
        bot,top=(r.bot-off,r.top-off) if r.kind=='bull' else (r.bot+off,r.top+off)
        w=walk(r.kind,bot,top,s,ATR[r.i])
        if w: w['size_atr']=r.size_atr; rows.append(w)
S=pd.DataFrame(rows)
T=F[F.touched.astype('boolean').fillna(False).astype(bool)].copy()
for c in ['react_1','held24']: T[c]=T[c].astype(bool)
edges=[0,.15,.3,.5,1,99]; labels=['<0.15','0.15-0.3','0.3-0.5','0.5-1','>1 ATR']
T['sz']=pd.cut(T.size_atr,edges,labels=labels,include_lowest=True); S['sz']=pd.cut(S.size_atr,edges,labels=labels,include_lowest=True)
a=T.groupby('sz',observed=True).agg(n=('react_1','size'),FVG_react1=('react_1','mean'),FVG_held24=('held24','mean'))
b=S.groupby('sz',observed=True).agg(BASE_react1=('react_1','mean'),BASE_held24=('held24','mean'))
g=a.join(b); 
for c in ['FVG_react1','BASE_react1','FVG_held24','BASE_held24']: g[c]=(g[c]*100).round(1)
g['лифт_react1_пп']=(g.FVG_react1-g.BASE_react1).round(1); g['лифт_held24_пп']=(g.FVG_held24-g.BASE_held24).round(1)
pd.set_option('display.width',200)
print('=== FVG vs СЛУЧАЙНАЯ ЗОНА ТОГО ЖЕ РАЗМЕРА, по корзинам размера (в % ) ===')
print(g.to_string())
