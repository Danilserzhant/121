import pandas as pd, numpy as np, glob, zipfile, os
COLS=['open_time','open','high','low','close','volume','ct','qv','n','tbv','tbqv','ig']
def load(pat):
    fr=[]
    for z in sorted(glob.glob(pat)):
        try:
            zf=zipfile.ZipFile(z); d=pd.read_csv(zf.open(zf.namelist()[0]),header=None,names=COLS)
        except Exception: continue
        if str(d.iloc[0,0])=='open_time': d=d.iloc[1:]
        fr.append(d[['open_time','open','high','low','close','volume']])
    if not fr: return None
    d=pd.concat(fr,ignore_index=True).apply(pd.to_numeric,errors='coerce').dropna()
    d['open_time']=np.where(d.open_time>1e15,d.open_time/1000,d.open_time).astype('int64')
    d=d.drop_duplicates('open_time').sort_values('open_time').reset_index(drop=True)
    d['ts']=pd.to_datetime(d.open_time,unit='ms',utc=True); return d
def weekly(h,sym):
    h=h.copy()
    W=h.set_index('ts').resample('W-MON',label='left',closed='left').agg(
        o=('open','first'),hi=('high','max'),lo=('low','min'),c=('close','last'),v=('volume','sum')).dropna()
    M=h.copy(); M['ym']=M.ts.dt.strftime('%Y-%m')
    Mo=M.groupby('ym').agg(o=('open','first'),hi=('high','max'),lo=('low','min'),c=('close','last'))
    D=h.set_index('ts').resample('1D').agg(hh=('high','max'),ll=('low','min'),cc=('close','last')).dropna()
    tr=np.maximum(D.hh-D.ll,np.maximum(abs(D.hh-D.cc.shift()),abs(D.ll-D.cc.shift()))); D['atr']=tr.rolling(14).mean()
    D['e50']=D.cc.ewm(span=50).mean()
    hi_a=h.high.to_numpy(); lo_a=h.low.to_numpy(); ts=h.ts
    rows=[]
    for i in range(3,len(W)):
        p=W.iloc[i-1]; pp=W.iloc[i-2]; cur=W.index[i]
        rng=p.hi-p.lo
        if rng<=0: continue
        seg=h[(h.ts>=cur)&(h.ts<cur+pd.Timedelta(days=7))]
        if len(seg)<24*5: continue
        op=seg.open.iloc[0]; atr=D.atr.asof(cur); e50=D.e50.asof(cur)
        if not (atr>0): continue
        a=np.flatnonzero(seg.high.to_numpy()>=p.hi); b=np.flatnonzero(seg.low.to_numpy()<=p.lo)
        ai=a[0] if len(a) else 10**9; bi=b[0] if len(b) else 10**9
        if ai==10**9 and bi==10**9: tgt=None
        else: tgt=1 if ai<bi else 0
        # месячный контекст
        ym=cur.strftime('%Y-%m'); prev_ym=(cur-pd.Timedelta(days=cur.day)).strftime('%Y-%m')
        mpos=np.nan; m_bias=0
        if prev_ym in Mo.index:
            A=Mo.loc[prev_ym]; mr=A.hi-A.lo
            if mr>0:
                mpos=(A.c-A.lo)/mr
                m_bias=1 if mpos>0.6 else (-1 if mpos<=0.25 else 0)
        # положение открытия недели в МЕСЯЧНОМ диапазоне
        mo_pos=np.nan
        if prev_ym in Mo.index:
            A=Mo.loc[prev_ym]; mr=A.hi-A.lo
            if mr>0: mo_pos=(op-A.lo)/mr
        rows.append(dict(sym=sym,wk=cur.strftime('%Y-%m-%d'),target=tgt,
            wpos=(p.c-p.lo)/rng,                          # позиция закрытия пред. недели
            open_pos=(op-p.lo)/rng,
            rng_atr=rng/atr,
            w_green=1.0 if p.c>p.o else 0.0,
            swept_pph=1.0 if p.hi>pp.hi else 0.0, swept_ppl=1.0 if p.lo<pp.lo else 0.0,
            hh_hl=1.0 if (p.hi>pp.hi and p.lo>pp.lo) else 0.0,
            lh_ll=1.0 if (p.hi<pp.hi and p.lo<pp.lo) else 0.0,
            mom3=(p.c/W.iloc[i-3].c-1),
            above50=1.0 if op>e50 else 0.0,
            mpos=mpos, m_bias=m_bias, mo_pos=mo_pos,
            vol_rel=p.v/pp.v if pp.v>0 else np.nan))
    return pd.DataFrame(rows)
