import pandas as pd, numpy as np
F=pd.read_pickle('fvg_all.pkl'); H4=pd.read_pickle('h4.pkl'); h=pd.read_pickle('h1s.pkl')
for c in ['touched','sliced','held24','held72','react_05','react_1','react_2','react_gap','with_trend']:
    F[c]=F[c].astype('boolean').fillna(False).astype(bool)
T=F[F.touched].copy()
pd.set_option('display.width',200)
print(f'касаний: {len(T)}  | насквозь тем же часом: {T.sliced.mean()*100:.1f}%')
print('после ПЕРВОГО касания:  react≥0.5ATR %.1f%%  react≥1ATR %.1f%%  react≥2ATR %.1f%%  react≥gap %.1f%%  held24 %.1f%%  held72 %.1f%%'%tuple(T[c].mean()*100 for c in ['react_05','react_1','react_2','react_gap','held24','held72']))

# ---- базовая линия: теневая зона того же размера, сдвинутая дальше от цены на U(0.5,2)*ATR ----
O,Hh,L,C=(H4[c].to_numpy(float) for c in ['open','high','low','close'])
tr=np.maximum(Hh-L,np.maximum(abs(Hh-np.roll(C,1)),abs(L-np.roll(C,1)))); ATR=pd.Series(tr).rolling(14).mean().to_numpy()
hi_,lo_=h.high.to_numpy(float),h.low.to_numpy(float); NH=len(h)
h4s=h.index[h.open_time.isin(H4.h4)].to_numpy()
rng=np.random.default_rng(7)
def walk(kind,bot,top,start_h,atr,HMAX=168):
    near,far=(top,bot) if kind=='bull' else (bot,top)
    t=np.flatnonzero(lo_[start_h:]<=near) if kind=='bull' else np.flatnonzero(hi_[start_h:]>=near)
    if t.size==0: return None
    t0=start_h+t[0]; sliced=(lo_[t0]<far) if kind=='bull' else (hi_[t0]>far)
    sh,sl=hi_[t0+1:t0+1+HMAX],lo_[t0+1:t0+1+HMAX]
    fill=np.flatnonzero(sl<far) if kind=='bull' else np.flatnonzero(sh>far)
    exc=(sh-near) if kind=='bull' else (near-sl)
    upto=0 if sliced else (fill[0] if fill.size else len(exc)); mfe=exc[:upto].max() if upto>0 else 0
    fh=0 if sliced else (fill[0]+1 if fill.size else None)
    return dict(react_1=mfe>=atr, react_gap=mfe>=(top-bot), held24=(fh is None or fh>24))
sh=[]
for r in F.itertuples():
    off=rng.uniform(0.5,2.0)*ATR[r.i]; s=h4s[r.i]+4
    if s>=NH: continue
    bot,top=(r.bot-off,r.top-off) if r.kind=='bull' else (r.bot+off,r.top+off)
    w=walk(r.kind,bot,top,s,ATR[r.i]); 
    if w: sh.append(w)
S=pd.DataFrame(sh)
print(f'\nБАЗА (теневая зона того же размера рядом, n={len(S)}): react≥1ATR {S.react_1.mean()*100:.1f}%  react≥gap {S.react_gap.mean()*100:.1f}%  held24 {S.held24.mean()*100:.1f}%')
print(f'FVG:                                          react≥1ATR {T.react_1.mean()*100:.1f}%  react≥gap {T.react_gap.mean()*100:.1f}%  held24 {T.held24.mean()*100:.1f}%')

# ---- факторы ----
def bucket(s,edges,labels): return pd.cut(s,edges,labels=labels,include_lowest=True)
T['sz']=bucket(T.size_atr,[0,.15,.3,.5,1,99],['<0.15','0.15-0.3','0.3-0.5','0.5-1','>1 ATR'])
T['dp']=bucket(T.disp_atr,[0,.5,1,1.5,2.5,99],['<0.5','0.5-1','1-1.5','1.5-2.5','>2.5 ATR'])
T['ag']=bucket(T.age_h,[0,4,24,72,168,720,1e9],['≤4ч','4-24ч','1-3д','3-7д','7-30д','>30д'])
T['dep']=bucket(T.depth,[0,.25,.5,.75,.999,1],['<25%','25-50%','50-75%','75-99%','100%'])
for col,ttl in [('sz','РАЗМЕР ГЭПА (в ATR H4)'),('dp','ИМПУЛЬС средней свечи (тело/ATR)'),('ag','ВОЗРАСТ на момент касания'),
                ('with_trend','ПО ТРЕНДУ (цена vs EMA50 H4 при формировании)'),('kind','НАПРАВЛЕНИЕ'),('dep','ГЛУБИНА захода в зону первым часом')]:
    g=T.groupby(col,observed=True).agg(n=('react_1','size'),react_1ATR=('react_1','mean'),react_gap=('react_gap','mean'),held24=('held24','mean'),held72=('held72','mean'))
    for c in ['react_1ATR','react_gap','held24','held72']: g[c]=(g[c]*100).round(1)
    print(f'\n== {ttl} =='); print(g.to_string())
T.to_pickle('touched.pkl')
