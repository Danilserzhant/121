import pandas as pd, numpy as np
F=pd.read_pickle('fvg_all.pkl'); H4=pd.read_pickle('h4.pkl')
m1=pd.read_parquet('m1.parquet')                      # архив 1m до 2026-09-13
h1=pd.read_pickle('h1s.pkl')
NM=len(m1); assert NM%15==0
mo,mh,ml,mc=(m1[c].to_numpy(float) for c in ['open','high','low','close'])
# M15 из минуток
O15=mo[::15]; H15=mh.reshape(-1,15).max(1); L15=ml.reshape(-1,15).min(1); C15=mc[14::15]; N15=len(C15)
O4,Hh,L4,C4=(H4[c].to_numpy(float) for c in ['open','high','low','close'])
tr=np.maximum(Hh-L4,np.maximum(abs(Hh-np.roll(C4,1)),abs(L4-np.roll(C4,1)))); ATR=pd.Series(tr).rolling(14).mean().to_numpy()
EMA50=pd.Series(C4).ewm(span=50).mean().to_numpy()
h4s=h1.index[h1.open_time.isin(H4.h4)].to_numpy()
for c in ['touched','with_trend']: F[c]=F[c].astype('boolean').fillna(False).astype(bool)
T=F[F.touched].copy(); T=T[T.t0*60+60<NM]        # только касания внутри архива 1m

WIN=16      # окно поиска подтверждения: 16 баров M15 = 4 часа после касания
HOR=7*24*4  # горизонт исхода: 7 дней в барах M15

def outcomes(kind,entry,far,c,atr,top,bot):
    """исход от закрытия подтверждающей свечи c: MFE до пробоя дальней кромки, стоп за дальней кромкой."""
    sh,sl=H15[c+1:c+1+HOR],L15[c+1:c+1+HOR]
    if kind=='bull': fill=np.flatnonzero(sl<far); exc=sh-entry
    else:            fill=np.flatnonzero(sh>far); exc=entry-sl
    upto=fill[0] if fill.size else len(exc)
    mfe=exc[:upto].max() if upto>0 else 0.0
    R=abs(entry-far)
    # цель 2R до стопа (стоп = дальняя кромка), пессимистично внутри бара
    if kind=='bull': tp=np.flatnonzero(sh>=entry+2*R)
    else:            tp=np.flatnonzero(sl<=entry-2*R)
    ti=tp[0] if tp.size else 10**9; si=fill[0] if fill.size else 10**9
    if ti<si: r2=2.0
    elif si<10**9: r2=-1.0
    else: ex=C15[min(c+HOR,N15-1)]; r2=((ex-entry) if kind=='bull' else (entry-ex))/R
    return dict(react_1=mfe>=atr, react_05=mfe>=0.5*atr, held24=(not fill.size or fill[0]>=96), R2=r2, risk_pct=R/entry*100)

rows=[]
for r in T.itertuples():
    kind,bot,top=r.kind,r.bot,r.top; near,far=(top,bot) if kind=='bull' else (bot,top)
    atr=ATR[r.i]; c0=int(r.t0)*4                 # первый M15 бар часа касания
    # точный M15 бар касания
    seg=L15[c0:c0+4]<=near if kind=='bull' else H15[c0:c0+4]>=near
    if not seg.any(): continue
    c0+=int(np.argmax(seg))
    base=dict(fid=r.Index,kind=kind,size_atr=r.size_atr,disp_atr=r.disp_atr,with_trend=r.with_trend,age_h=r.age_h)
    # без подтверждения: вход по закрытию свечи касания (если не пробили насквозь)
    filled0=(L15[c0]<far) if kind=='bull' else (H15[c0]>far)
    if not filled0:
        rows.append({**base,'conf':'0 без подтверждения (закрытие M15 касания)','c':c0,'depth':(near-L15[c0])/(top-bot) if kind=='bull' else (H15[c0]-near)/(top-bot),
                     **outcomes(kind,C15[c0],far,c0,atr,top,bot)})
    # подтверждения в окне
    found={}
    touch_hi,touch_lo=H15[c0],L15[c0]
    for c in range(c0,min(c0+WIN,N15-1)):
        lo,hi,cl,op=L15[c],H15[c],C15[c],O15[c]
        pen=(near-L15[c0:c+1].min())/(top-bot) if kind=='bull' else (H15[c0:c+1].max()-near)/(top-bot)
        if pen>=1.0: break                                        # заполнили — подтверждений больше нет
        if kind=='bull':
            A = lo<=near and cl>near                              # тень в зоне, закрытие над ближней кромкой
            B = c>c0 and lo<L15[c-1] and cl>L15[c-1] and lo<=near # свип минимума пред. M15 в зоне + реклейм
            Cc= c>c0 and cl>O15[c] and cl>H15[c-1] and O15[c]<=C15[c-1] and lo<=near  # бычье поглощение в зоне
            D = c>c0 and cl>touch_hi                              # закрытие выше хая свечи касания
            E = c>=c0+2 and (C15[c-2:c+1]>near).all() and L15[c-1:c+1].min()>=L15[c0:c-1].min()  # 3 закрытия над кромкой, лоу не обновлён
        else:
            A = hi>=near and cl<near
            B = c>c0 and hi>H15[c-1] and cl<H15[c-1] and hi>=near
            Cc= c>c0 and cl<O15[c] and cl<L15[c-1] and O15[c]>=C15[c-1] and hi>=near
            D = c>c0 and cl<touch_lo
            E = c>=c0+2 and (C15[c-2:c+1]<near).all() and H15[c-1:c+1].max()<=H15[c0:c-1].max()
        for nm,ok in [('A закрытие M15 обратно за кромку',A),('B свип пред. M15 + реклейм в зоне',B),
                      ('C поглощение M15 в зоне',Cc),('D закрытие M15 за экстремум свечи касания',D),('E 3 закрытия за кромкой без нового экстремума',E)]:
            if ok and nm not in found:
                found[nm]=1
                rows.append({**base,'conf':nm,'c':c,'depth':min(pen,1.0),'wait':c-c0,**outcomes(kind,cl,far,c,atr,top,bot)})
D=pd.DataFrame(rows); D.to_pickle('conf.pkl')
pd.set_option('display.width',220)
def summ(d):
    return pd.Series(dict(n=len(d),react_1=d.react_1.mean()*100,react_05=d.react_05.mean()*100,held24=d.held24.mean()*100,
                          avgR_2R=d.R2.mean(),win2R=(d.R2>0).mean()*100,risk_med=d.risk_pct.median()))
print('=== ВСЕ H4 FVG, по типу подтверждения (исход от закрытия подтверждающей свечи) ===')
print(D.groupby('conf').apply(summ,include_groups=False).round(2).to_string())
print('\n=== ТОЛЬКО size ≥ 0.5 ATR ===')
print(D[D.size_atr>=0.5].groupby('conf').apply(summ,include_groups=False).round(2).to_string())
print('\n=== size ≥ 0.5 ATR И глубина захода на момент подтверждения < 50% ===')
print(D[(D.size_atr>=0.5)&(D.depth<0.5)].groupby('conf').apply(summ,include_groups=False).round(2).to_string())
