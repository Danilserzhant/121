import pandas as pd, numpy as np, json, glob, zipfile
COLS=['open_time','open','high','low','close','volume','close_time','qv','n','tbv','tbqv','ig']
fr=[]
for z in sorted(glob.glob('data/1h/ETHUSDT-1h-*.zip')):
    zf=zipfile.ZipFile(z); df=pd.read_csv(zf.open(zf.namelist()[0]),header=None,names=COLS)
    if str(df.iloc[0,0])=='open_time': df=df.iloc[1:]
    fr.append(df)
h=pd.concat(fr,ignore_index=True)
for c in ['open_time','open','high','low','close']: h[c]=pd.to_numeric(h[c])
h=h[['open_time','open','high','low','close']].drop_duplicates('open_time')
# сшивка Bitget за часы, которых нет в архиве (закрытые бары)
bg=pd.DataFrame(sorted(json.load(open('bitget_1h.json'))['data'],key=lambda r:int(r[0])))[[0,1,2,3,4]]
bg.columns=['open_time','open','high','low','close']; bg=bg.astype(float); bg['open_time']=bg.open_time.astype(int)
last_archive=h.open_time.max(); now_ms=int(pd.Timestamp.utcnow().timestamp()*1000)
bg=bg[(bg.open_time>last_archive)&(bg.open_time+3600000<=now_ms)]
h=pd.concat([h,bg],ignore_index=True).sort_values('open_time').reset_index(drop=True)
assert (h.open_time.diff().dropna()==3600000).all(), 'дыра в часовом ряду'
h['ts']=pd.to_datetime(h.open_time,unit='ms',utc=True)
print('1h:',len(h),h.ts.iloc[0],'->',h.ts.iloc[-1],'| из Bitget:',len(bg),'часов')

# H4 по границам Binance (00/04/08/12/16/20 UTC); берём только полные бары
h['h4']=(h.open_time//14400000)*14400000
g=h.groupby('h4'); cnt=g.size()
full=cnt[cnt==4].index
H4=pd.DataFrame({'open':g.open.first(),'high':g.high.max(),'low':g.low.min(),'close':g.close.last()}).loc[full].reset_index()
H4['ts']=pd.to_datetime(H4.h4,unit='ms',utc=True)
O,Hh,L,C=(H4[c].to_numpy(float) for c in ['open','high','low','close'])
tr=np.maximum(Hh-L,np.maximum(abs(Hh-np.roll(C,1)),abs(L-np.roll(C,1)))); tr[0]=Hh[0]-L[0]
ATR=pd.Series(tr).rolling(14).mean().to_numpy()
EMA50=pd.Series(C).ewm(span=50).mean().to_numpy()
N4=len(H4); print('H4 полных баров:',N4,'| последний:',H4.ts.iloc[-1])
# индекс первого часа после закрытия H4-бара i
h4_start_hour=h.index[h.open_time.isin(H4.h4)].to_numpy()   # часовой индекс начала каждого H4
hi_,lo_=h.high.to_numpy(float),h.low.to_numpy(float); NH=len(h)

# ---- детекция FVG ----
fv=[]
for i in range(2,N4):
    if np.isnan(ATR[i]): continue
    if L[i]>Hh[i-2]:   fv.append(dict(i=i,kind='bull',bot=Hh[i-2],top=L[i]))
    if Hh[i]<L[i-2]:   fv.append(dict(i=i,kind='bear',bot=Hh[i],top=L[i-2]))
F=pd.DataFrame(fv)
F['size']=F.top-F.bot; F['size_atr']=F['size']/ATR[F.i]
F['disp_atr']=abs(C[F.i-1]-O[F.i-1])/ATR[F.i]          # тело средней (импульсной) свечи
F['with_trend']=np.where(F.kind=='bull',C[F.i]>EMA50[F.i],C[F.i]<EMA50[F.i])
F['ts']=H4.ts.iloc[F.i].values
print('FVG найдено:',len(F),' bull',(F.kind=='bull').sum(),' bear',(F.kind=='bear').sum())

# ---- прогон каждого FVG вперёд по часовым: первое касание и исход ----
HMAX=24*7
def walk(kind,bot,top,start_h,atr):
    """с часа start_h: первое касание ближней кромки; после — реакция до полного заполнения."""
    if kind=='bull': near,far,sgn=top,bot,1
    else:            near,far,sgn=bot,top,-1
    if kind=='bull':
        t=np.flatnonzero(lo_[start_h:]<=near)
    else:
        t=np.flatnonzero(hi_[start_h:]>=near)
    if t.size==0: return dict(touched=False)
    t0=start_h+t[0]
    sliced = (lo_[t0]<far) if kind=='bull' else (hi_[t0]>far)   # пробили насквозь тем же часом
    seg_hi=hi_[t0+1:t0+1+HMAX]; seg_lo=lo_[t0+1:t0+1+HMAX]
    if kind=='bull': fill=np.flatnonzero(seg_lo<far); exc=seg_hi-near
    else:            fill=np.flatnonzero(seg_hi>far); exc=near-seg_lo
    fill_h = 0 if sliced else (fill[0]+1 if fill.size else None)
    upto = 0 if sliced else (fill[0] if fill.size else len(exc))
    mfe = exc[:upto].max() if upto>0 else 0.0
    # проникновение в зону тем же часом (насколько глубоко зашли до реакции)
    depth = (near-lo_[t0])/(near-far) if kind=='bull' else (hi_[t0]-near)/(far-near)
    return dict(touched=True,t0=t0,age_h=t0-start_h,sliced=sliced,fill_h=fill_h,
                mfe_atr=mfe/atr, mfe_gap=mfe/(top-bot), depth=min(depth,1.0),
                held24=(fill_h is None or fill_h>24), held72=(fill_h is None or fill_h>72),
                react_05=mfe>=0.5*atr, react_1=mfe>=1.0*atr, react_2=mfe>=2.0*atr, react_gap=mfe>=(top-bot))
rows=[]
for r in F.itertuples():
    start=h4_start_hour[r.i]+4                # первый час после закрытия бара i
    if start>=NH: continue
    w=walk(r.kind,r.bot,r.top,start,ATR[r.i]); w['fid']=r.Index; rows.append(w)
W=pd.DataFrame(rows).set_index('fid'); F=F.join(W)
F.to_pickle('fvg_all.pkl'); H4.to_pickle('h4.pkl'); h.to_pickle('h1s.pkl')
T=F[F.touched==True]
print(f'\nкоснулись: {len(T)} из {len(F)} ({len(T)/len(F)*100:.1f}%)')
print(f'пробили насквозь тем же часом: {T.sliced.mean()*100:.1f}%')
for k in ['react_05','react_1','react_2','react_gap','held24','held72']:
    print(f'  P({k}) после первого касания = {T[k].mean()*100:.1f}%')
