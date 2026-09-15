import pandas as pd, numpy as np
F=pd.read_pickle('fvg_all.pkl'); H4=pd.read_pickle('h4.pkl'); h1=pd.read_pickle('h1s.pkl')
m1=pd.read_parquet('m1.parquet'); hv=pd.read_parquet('h1.parquet')     # h1.parquet: с объёмом, до 09-11
NM=len(m1); mo,mh,ml,mc=(m1[c].to_numpy(float) for c in ['open','high','low','close'])
O15=mo[::15]; H15=mh.reshape(-1,15).max(1); L15=ml.reshape(-1,15).min(1); C15=mc[14::15]; N15=len(C15)
O4,Hh,L4,C4=(H4[c].to_numpy(float) for c in ['open','high','low','close'])
tr=np.maximum(Hh-L4,np.maximum(abs(Hh-np.roll(C4,1)),abs(L4-np.roll(C4,1)))); ATR=pd.Series(tr).rolling(14).mean().to_numpy()
EMA200=pd.Series(C4).ewm(span=200).mean().to_numpy(); EMA50=pd.Series(C4).ewm(span=50).mean().to_numpy()
# объём H4 из часового архива (выровнен по индексу с h1s)
vol1=np.zeros(len(h1)); vol1[:len(hv)]=hv.volume.to_numpy(float)
h4s=h1.index[h1.open_time.isin(H4.h4)].to_numpy()
V4=np.array([vol1[s:s+4].sum() for s in h4s]); V4rel=V4/pd.Series(V4).rolling(20).mean().to_numpy()
ts1=h1.ts
for c in ['touched','with_trend']: F[c]=F[c].astype('boolean').fillna(False).astype(bool)
T=F[F.touched].copy(); T=T[T.t0*60+60<NM]
WIN=16; HOR=7*24*4; FEE=0.001

def exits(kind,entry,c,atr,top,bot,test_ext):
    """набор выходов; всё нетто, в R своего стопа"""
    sh,sl=H15[c+1:c+1+HOR],L15[c+1:c+1+HOR]; res={}
    far=bot if kind=='bull' else top; ce=(top+bot)/2
    stops={'far':far,'ce':ce,'ext':test_ext,'ext-0.25atr':(test_ext-0.25*atr if kind=='bull' else test_ext+0.25*atr)}
    for sn,stop in stops.items():
        R=abs(entry-stop)
        if R<=0 or (kind=='bull' and stop>=entry) or (kind=='bear' and stop<=entry): 
            for tn in ('1atr','0.5atr','gap','2R'): res[f'{sn}|{tn}']=np.nan
            res[f'{sn}|risk']=np.nan; continue
        s_hit=np.flatnonzero(sl<=stop) if kind=='bull' else np.flatnonzero(sh>=stop); si=s_hit[0] if s_hit.size else 10**9
        for tn,tgt in [('1atr',atr),('0.5atr',0.5*atr),('gap',top-bot),('2R',2*R)]:
            t_hit=np.flatnonzero(sh>=entry+tgt) if kind=='bull' else np.flatnonzero(sl<=entry-tgt); ti=t_hit[0] if t_hit.size else 10**9
            if ti<si: r=tgt/R
            elif si<10**9: r=-1.0
            else: ex=C15[min(c+HOR,N15-1)]; r=((ex-entry) if kind=='bull' else (entry-ex))/R
            res[f'{sn}|{tn}']=r-FEE*entry/R
        res[f'{sn}|risk']=R/entry*100
    # реакция (как раньше): MFE до пробоя дальней кромки
    fill=np.flatnonzero(sl<far) if kind=='bull' else np.flatnonzero(sh>far)
    exc=(sh-entry) if kind=='bull' else (entry-sl); upto=fill[0] if fill.size else len(exc)
    mfe=exc[:upto].max() if upto>0 else 0.0
    res.update(react_1=mfe>=atr,react_05=mfe>=0.5*atr,react_gap=mfe>=(top-bot),held24=(not fill.size or fill[0]>=96))
    return res

rows=[]
for r in T.itertuples():
    kind,bot,top=r.kind,r.bot,r.top; near,far=(top,bot) if kind=='bull' else (bot,top); atr=ATR[r.i]
    c0=int(r.t0)*4; seg=L15[c0:c0+4]<=near if kind=='bull' else H15[c0:c0+4]>=near
    if not seg.any(): continue
    c0+=int(np.argmax(seg))
    t0=int(r.t0); touch_ts=ts1.iloc[t0]
    base=dict(fid=r.Index,kind=kind,size_atr=r.size_atr,disp_atr=r.disp_atr,with_trend=r.with_trend,age_h=r.age_h,
              hour=touch_ts.hour,wday=touch_ts.weekday(),fresh=r.age_h<=24,
              above200=(C4[r.i]>EMA200[r.i]) if kind=='bull' else (C4[r.i]<EMA200[r.i]),   # FVG по сторону EMA200
              vol_rel=V4rel[r.i-1] if r.i-1<len(V4rel) else np.nan,                          # объём импульсной свечи / ср.20
              dist_ema50_atr=abs(C4[r.i]-EMA50[r.i])/atr, year=touch_ts.year)
    touch_hi,touch_lo=H15[c0],L15[c0]; found={}; seenA=None
    for c in range(c0,min(c0+WIN,N15-1)):
        lo,hi,cl,op=L15[c],H15[c],C15[c],O15[c]
        ext=L15[c0:c+1].min() if kind=='bull' else H15[c0:c+1].max()
        pen=(near-ext)/(top-bot) if kind=='bull' else (ext-near)/(top-bot)
        if pen>=1.0: break
        if kind=='bull':
            A=lo<=near and cl>near
            Cc=c>c0 and cl>op and cl>H15[c-1] and op<=C15[c-1] and lo<=near
            D=c>c0 and cl>touch_hi
            E=c>=c0+2 and (C15[c-2:c+1]>near).all() and L15[c-1:c+1].min()>=L15[c0:c-1].min()
            CH=c>=c0+3 and cl>H15[c-3:c].max() and L15[c-3:c].min()>=ext          # CHoCH: закрытие над хаем последних 3 M15 после того, как лоу теста устоял
            NF=c>=c0+2 and L15[c]>H15[c-2] and L15[c-1]<=near                       # вложенный бычий M15 FVG, средняя свеча в зоне
            D2=D and seenA is not None                                               # A уже было, затем D
            Dd=D and pen<0.5                                                         # D при заходе <50%
        else:
            A=hi>=near and cl<near
            Cc=c>c0 and cl<op and cl<L15[c-1] and op>=C15[c-1] and hi>=near
            D=c>c0 and cl<touch_lo
            E=c>=c0+2 and (C15[c-2:c+1]<near).all() and H15[c-1:c+1].max()<=H15[c0:c-1].max()
            CH=c>=c0+3 and cl<L15[c-3:c].min() and H15[c-3:c].max()<=ext
            NF=c>=c0+2 and H15[c]<L15[c-2] and H15[c-1]>=near
            D2=D and seenA is not None; Dd=D and pen<0.5
        if A and seenA is None: seenA=c
        for nm,ok in [('A',A),('C',Cc),('D',D),('E',E),('CH',CH),('NF',NF),('A→D',D2),('D<50%',Dd)]:
            if ok and nm not in found:
                found[nm]=1
                rows.append({**base,'conf':nm,'c':c,'depth':min(pen,1.0),'wait':c-c0,**exits(kind,cl,c,atr,top,bot,ext)})
    if not((L15[c0]<far) if kind=='bull' else (H15[c0]>far)):
        rows.append({**base,'conf':'0',c:c0,'c':c0,'depth':(near-touch_lo)/(top-bot) if kind=='bull' else (touch_hi-near)/(top-bot),'wait':0,
                     **exits(kind,C15[c0],c0,atr,top,bot,touch_lo if kind=='bull' else touch_hi)})
D=pd.DataFrame(rows); D.to_pickle('conf3.pkl'); print('событий:',len(D)); print(D.conf.value_counts().to_string())
