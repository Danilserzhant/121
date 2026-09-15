"""Обобщённый пайплайн: HTF FVG + LTF подтверждение. HTF строится из LTF (n баров LTF на 1 бар HTF)."""
import pandas as pd, numpy as np, glob, zipfile, sys
COLS=['open_time','open','high','low','close','volume','ct','qv','n','tbv','tbqv','ig']
TF_MS={'5m':300000,'15m':900000}

def load_ltf(sym,tf):
    fr=[]
    for z in sorted(glob.glob(f'mdata/{sym}/{tf}/*.zip')):
        zf=zipfile.ZipFile(z); df=pd.read_csv(zf.open(zf.namelist()[0]),header=None,names=COLS)
        if str(df.iloc[0,0])=='open_time': df=df.iloc[1:]
        fr.append(df[['open_time','open','high','low','close','volume']])
    d=pd.concat(fr,ignore_index=True).apply(pd.to_numeric,errors='coerce').dropna().drop_duplicates('open_time').sort_values('open_time')
    ms=TF_MS[tf]; grid=np.arange(d.open_time.iloc[0],d.open_time.iloc[-1]+ms,ms)
    d=d.set_index('open_time').reindex(grid)
    gaps=d.close.isna().sum(); d['close']=d.close.ffill()
    for c in ['open','high','low']: d[c]=d[c].fillna(d.close)
    d['volume']=d.volume.fillna(0)
    return d.reset_index().rename(columns={'index':'open_time'}), gaps

def run(sym,tf,n,label):
    d,gaps=load_ltf(sym,tf); ms=TF_MS[tf]; htf_ms=ms*n
    first=int(np.argmax(d.open_time.values%htf_ms==0)); d=d.iloc[first:]; d=d.iloc[:len(d)//n*n].reset_index(drop=True)
    lo,lh,ll,lc,lv=(d[c].to_numpy(float) for c in ['open','high','low','close','volume'])
    NL=len(d)
    O=lo[::n]; H=lh.reshape(-1,n).max(1); L=ll.reshape(-1,n).min(1); C=lc[n-1::n]; V=lv.reshape(-1,n).sum(1); NH=len(C)
    ts=pd.to_datetime(d.open_time.values[::n],unit='ms',utc=True)
    tr=np.maximum(H-L,np.maximum(abs(H-np.roll(C,1)),abs(L-np.roll(C,1)))); tr[0]=H[0]-L[0]
    ATR=pd.Series(tr).rolling(14).mean().to_numpy(); E50=pd.Series(C).ewm(span=50).mean().to_numpy(); E200=pd.Series(C).ewm(span=200).mean().to_numpy()
    Vrel=V/pd.Series(V).rolling(20).mean().to_numpy()
    WIN=n; HOR=42*n; FEE=0.001
    rows=[]
    for i in range(20,NH):
        atr=ATR[i]
        if not atr>0: continue
        for kind,bot,top in ([('bull',H[i-2],L[i])] if L[i]>H[i-2] else [])+([('bear',H[i],L[i-2])] if H[i]<L[i-2] else []):
            near,far=(top,bot) if kind=='bull' else (bot,top); gap=top-bot; ce=(top+bot)/2
            s=(i+1)*n
            if s>=NL-1: continue
            t=np.flatnonzero(ll[s:]<=near) if kind=='bull' else np.flatnonzero(lh[s:]>=near)
            if t.size==0: continue
            c0=s+t[0]
            base=dict(sym=sym,label=label,kind=kind,size_atr=gap/atr,disp_atr=abs(C[i-1]-O[i-1])/atr,ext_atr=abs(C[i]-E50[i])/atr,
                      vol_rel=Vrel[i-1],above200=(C[i]>E200[i]) if kind=='bull' else (C[i]<E200[i]),year=ts[i].year,age_bars=(c0-s)/n,fid=f'{sym}{label}{i}{kind}')
            def exits(entry,c,ext):
                sh,sl=lh[c+1:c+1+HOR],ll[c+1:c+1+HOR]; res={}
                fill=np.flatnonzero(sl<far) if kind=='bull' else np.flatnonzero(sh>far)
                exc=(sh-entry) if kind=='bull' else (entry-sl); upto=fill[0] if fill.size else len(exc)
                mfe=exc[:upto].max() if upto>0 else 0.0
                res.update(react_1=mfe>=atr,react_05=mfe>=0.5*atr,held=(not fill.size or fill[0]>=6*n))
                for sn,stop in [('far',far),('ce',ce),('ext',ext)]:
                    R=abs(entry-stop)
                    if R<=0 or (kind=='bull' and stop>=entry) or (kind=='bear' and stop<=entry):
                        for tn in ('1atr','0.5atr'): res[f'{sn}|{tn}']=np.nan
                        continue
                    sh_=np.flatnonzero(sl<=stop) if kind=='bull' else np.flatnonzero(sh>=stop); si=sh_[0] if sh_.size else 10**9
                    for tn,tgt in [('1atr',atr),('0.5atr',0.5*atr)]:
                        th=np.flatnonzero(sh>=entry+tgt) if kind=='bull' else np.flatnonzero(sl<=entry-tgt); ti=th[0] if th.size else 10**9
                        if ti<si: r=tgt/R
                        elif si<10**9: r=-1.0
                        else: ex=lc[min(c+HOR,NL-1)]; r=((ex-entry) if kind=='bull' else (entry-ex))/R
                        res[f'{sn}|{tn}']=r-FEE*entry/R
                    res[f'{sn}|risk']=R/entry*100
                return res
            touch_hi,touch_lo=lh[c0],ll[c0]; found=set(); seenA=False
            filled0=(ll[c0]<far) if kind=='bull' else (lh[c0]>far)
            if not filled0: rows.append({**base,'conf':'0','wait':0,**exits(lc[c0],c0,ll[c0] if kind=='bull' else lh[c0])})
            for c in range(c0,min(c0+WIN,NL-1)):
                ext=ll[c0:c+1].min() if kind=='bull' else lh[c0:c+1].max()
                pen=(near-ext)/gap if kind=='bull' else (ext-near)/gap
                if pen>=1.0: break
                cl=lc[c]
                if kind=='bull':
                    A=ll[c]<=near and cl>near; D=c>c0 and cl>touch_hi
                    E=c>=c0+2 and (lc[c-2:c+1]>near).all() and ll[c-1:c+1].min()>=ll[c0:c-1].min()
                    CH=c>=c0+3 and cl>lh[c-3:c].max() and ll[c-3:c].min()>=ext
                else:
                    A=lh[c]>=near and cl<near; D=c>c0 and cl<touch_lo
                    E=c>=c0+2 and (lc[c-2:c+1]<near).all() and lh[c-1:c+1].max()<=lh[c0:c-1].max()
                    CH=c>=c0+3 and cl<ll[c-3:c].min() and lh[c-3:c].max()<=ext
                if A: seenA=True
                for nm,ok in [('D',D),('CH',CH),('E',E),('A→D',D and seenA)]:
                    if ok and nm not in found:
                        found.add(nm); rows.append({**base,'conf':nm,'wait':c-c0,'depth':min(pen,1),**exits(cl,c,ext)})
    out=pd.DataFrame(rows); out.to_pickle(f'ev_{sym}_{label}.pkl')
    yrs=(ts[-1]-ts[0]).days/365.25
    print(f'{sym} {label}: LTF баров {NL} (дыр {gaps}), HTF {NH}, {yrs:.1f} лет, событий {len(out)}, FVG с касанием {out.fid.nunique()}')
    return out

if __name__=='__main__':
    sym,tf,n,label=sys.argv[1],sys.argv[2],int(sys.argv[3]),sys.argv[4]
    run(sym,tf,n,label)
