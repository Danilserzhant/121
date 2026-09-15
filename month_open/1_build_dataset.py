import pandas as pd, numpy as np, glob, zipfile
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

def build(h,sym):
    h=h.copy(); h['ym']=h.ts.dt.strftime('%Y-%m')
    M=h.groupby('ym').agg(o=('open','first'),hi=('high','max'),lo=('low','min'),c=('close','last'),v=('volume','sum'))
    D=h.set_index('ts').resample('1D').agg(hh=('high','max'),ll=('low','min'),cc=('close','last')).dropna()
    tr=np.maximum(D.hh-D.ll,np.maximum(abs(D.hh-D.cc.shift()),abs(D.ll-D.cc.shift()))); D['atr']=tr.rolling(14).mean()
    D['ema200']=D.cc.ewm(span=200).mean()
    H,L,C,O=(h[c].to_numpy(float) for c in ['high','low','close','open']); TS=h.ts.dt.tz_convert(None).to_numpy()
    ms=list(M.index); rows=[]
    for i in range(2,len(ms)):
        prev,cur=ms[i-1],ms[i]; pp=ms[i-2]
        PH,PL,PC,PO=M.hi[prev],M.lo[prev],M.c[prev],M.o[prev]
        PPH,PPL=M.hi[pp],M.lo[pp]
        idx=h.index[h.ym==cur].to_numpy()
        if len(idx)<24*20: continue
        t0=int(idx[0]); atr=D.atr.asof(pd.Timestamp(TS[t0],tz='UTC')); ema=D.ema200.asof(pd.Timestamp(TS[t0],tz='UTC'))
        if not (atr>0): continue
        openp=O[t0]; rng=PH-PL
        if rng<=0: continue
        hi_i=np.flatnonzero(H[idx]>=PH); lo_i=np.flatnonzero(L[idx]<=PL)
        hi_i=hi_i[0] if len(hi_i) else 10**9; lo_i=lo_i[0] if len(lo_i) else 10**9
        if hi_i==10**9 and lo_i==10**9: tgt=None
        else: tgt=1 if hi_i<lo_i else 0          # 1 = сначала максимум, 0 = сначала минимум
        # первые N часов месяца
        f24=idx[:24]; f72=idx[:72]; f168=idx[:168]
        rows.append(dict(sym=sym,ym=cur,target=tgt,
            # --- признаки, известные НА ОТКРЫТИИ ---
            close_pos=(PC-PL)/rng,                       # где закрылся пред. месяц в своём диапазоне
            month_dir=1.0 if PC>PO else 0.0,             # зелёный/красный пред. месяц
            open_pos=(openp-PL)/rng,                     # где открылись
            rng_atr=rng/atr,                             # размер диапазона в ATR
            swept_pph=1.0 if PH>PPH else 0.0,            # пред. месяц снял максимум позапрошлого
            swept_ppl=1.0 if PL<PPL else 0.0,
            inside=1.0 if (PH<PPH and PL>PPL) else 0.0,  # внутренний бар
            outside=1.0 if (PH>PPH and PL<PPL) else 0.0,
            above200=1.0 if C[t0]>ema else 0.0,
            mom2=(M.c[prev]/M.c[pp]-1),                  # импульс за 2 месяца
            vol_rel=M.v[prev]/M.v[pp] if M.v[pp]>0 else np.nan,
            dist_hi=(PH-openp)/atr, dist_lo=(openp-PL)/atr,
            month_num=int(cur[5:7]),
            # --- признаки, доступные ПОЗЖЕ (для сравнения) ---
            d1=(C[f24[-1]]/openp-1) if len(f24)==24 else np.nan,
            d3=(C[f72[-1]]/openp-1) if len(f72)==72 else np.nan,
            w1=(C[f168[-1]]/openp-1) if len(f168)==168 else np.nan,
            w1_pos=(C[f168[-1]]-PL)/rng if len(f168)==168 else np.nan,
        ))
    return pd.DataFrame(rows)
