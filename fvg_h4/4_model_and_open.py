import pandas as pd, numpy as np
F=pd.read_pickle('fvg_all.pkl'); H4=pd.read_pickle('h4.pkl'); h=pd.read_pickle('h1s.pkl')
LIVE=float(open('live.txt').read().split()[-1])
O,Hh,L,C=(H4[c].to_numpy(float) for c in ['open','high','low','close'])
tr=np.maximum(Hh-L,np.maximum(abs(Hh-np.roll(C,1)),abs(L-np.roll(C,1)))); ATR=pd.Series(tr).rolling(14).mean().to_numpy()
ATR_NOW=ATR[-1]
hi_,lo_=h.high.to_numpy(float),h.low.to_numpy(float); NH=len(h); h4s=h.index[h.open_time.isin(H4.h4)].to_numpy()
for c in ['touched','react_1','held24','with_trend']: F[c]=F[c].astype('boolean').fillna(False).astype(bool)
T=F[F.touched].copy()

def X_of(d):
    return np.column_stack([np.ones(len(d)), np.log(d.size_atr.clip(0.02)), np.log(d.disp_atr.clip(0.05)),
                            d.with_trend.astype(float), (d.kind=='bull').astype(float), np.log1p(d.age_h.clip(0))])
NAMES=['const','log size/ATR','log disp/ATR','по тренду','bull','log1p возраст ч']
def fit(X,y,it=50,l2=1e-3):
    w=np.zeros(X.shape[1])
    for _ in range(it):
        p=1/(1+np.exp(-X@w)); W=p*(1-p)
        H=X.T@(X*W[:,None])+l2*np.eye(len(w)); g=X.T@(y-p)-l2*w
        w+=np.linalg.solve(H,g)
    return w
def auc(p,y):
    r=pd.Series(p).rank().to_numpy(); n1=y.sum(); n0=len(y)-n1
    return (r[y==1].sum()-n1*(n1+1)/2)/(n1*n0)
T['ts']=pd.to_datetime(T.ts,utc=True); cut=pd.Timestamp('2025-01-01',tz='UTC'); tr_=T[T.ts<cut]; te_=T[T.ts>=cut]
print(f'обучение ≤2024: {len(tr_)} касаний, тест 2025-26: {len(te_)} касаний')
models={}
for tgt in ['react_1','held24']:
    w=fit(X_of(tr_),tr_[tgt].astype(float).to_numpy())
    pte=1/(1+np.exp(-X_of(te_)@w)); a=auc(pte,te_[tgt].astype(int).to_numpy())
    # калибровка на тесте по децилям
    q=pd.qcut(pte,5,labels=False,duplicates='drop'); cal=pd.DataFrame({'p':pte,'y':te_[tgt].values}).groupby(q).agg(предск=('p','mean'),факт=('y','mean'),n=('y','size'))
    print(f'\n[{tgt}] AUC out-of-sample = {a:.3f}'); print((cal[['предск','факт']]*100).round(1).join(cal.n).to_string())
    wf=fit(X_of(T),T[tgt].astype(float).to_numpy()); models[tgt]=wf
    print('  коэф. (на всей выборке):', ', '.join(f'{n}={v:+.2f}' for n,v in zip(NAMES,wf)))

# ---- открытые FVG сейчас ----
rows=[]
for r in F.itertuples():
    s=h4s[r.i]+4
    if s>=NH: s=NH   # сформирован последним баром — ещё ничего не проверялось
    seg_lo,seg_hi=lo_[s:],hi_[s:]
    if r.kind=='bull':
        filled=seg_lo.size>0 and seg_lo.min()<r.bot; touched=seg_lo.size>0 and seg_lo.min()<=r.top
        dist=(LIVE-r.top)/LIVE*100; inside=r.bot<=LIVE<=r.top
        remain=(min(seg_lo.min(),r.top)-r.bot)/(r.top-r.bot) if touched else 1.0   # непокрытая часть
    else:
        filled=seg_hi.size>0 and seg_hi.max()>r.top; touched=seg_hi.size>0 and seg_hi.max()>=r.bot
        dist=(r.bot-LIVE)/LIVE*100; inside=r.bot<=LIVE<=r.top
        remain=(r.top-max(seg_hi.max(),r.bot))/(r.top-r.bot) if touched else 1.0
    if filled: continue
    age_now=NH-s
    rows.append(dict(kind=r.kind,bot=r.bot,top=r.top,size=r.size,size_atr=r.size_atr,disp_atr=r.disp_atr,with_trend=r.with_trend,
                     age_h=age_now,formed=r.ts,dist_pct=(0 if inside else dist),dist_atr=(0 if inside else dist/100*LIVE/ATR_NOW),
                     touched=touched,remain=remain))
Op=pd.DataFrame(rows)
Op['P_react_1ATR']=1/(1+np.exp(-X_of(Op)@models['react_1'])); Op['P_held24']=1/(1+np.exp(-X_of(Op)@models['held24']))
Op.to_pickle('open_fvg.pkl')
near=Op[Op.dist_pct<=10].sort_values('P_react_1ATR',ascending=False)
print(f'\nLIVE {LIVE}  ATR14 H4 = {ATR_NOW:.1f}$ ({ATR_NOW/LIVE*100:.2f}%)')
print(f'открытых H4 FVG всего: {len(Op)} | в пределах ±10% от цены: {len(near)} (bull {(near.kind=="bull").sum()}, bear {(near.kind=="bear").sum()})')
pd.set_option('display.width',250); pd.set_option('display.max_rows',100)
out=near.copy()
out['зона']=out.apply(lambda r:f'{r.bot:.0f}–{r.top:.0f}',axis=1)
out['дист%']=out.dist_pct.round(2); out['дистATR']=out.dist_atr.round(1)
out['размерATR']=out.size_atr.round(2); out['импульсATR']=out.disp_atr.round(2)
out['возраст']=out.age_h.apply(lambda x:f'{x/24:.0f}д' if x>=48 else f'{x:.0f}ч')
out['сформ.']=pd.to_datetime(out.formed,utc=True).dt.strftime('%m-%d %H:%M')
out['тренд']=out.with_trend.map({True:'да',False:'нет'}); out['тестир.']=out.apply(lambda r:'нет' if not r.touched else f'частично ({r.remain*100:.0f}% ост.)',axis=1)
out['P_react≥1ATR']=(out.P_react_1ATR*100).round(0).astype(int); out['P_held24']=(out.P_held24*100).round(0).astype(int)
print(out[['kind','зона','дист%','дистATR','размерATR','импульсATR','тренд','возраст','сформ.','тестир.','P_react≥1ATR','P_held24']].to_string(index=False))
