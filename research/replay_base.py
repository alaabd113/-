#!/usr/bin/env python3
"""Independent offline research replicas of public strategy rules, NOT exact third-party code.
NO LIVE BROKER, NO ORDERS. Frozen PO3 benchmark supplied by previous project; never retuned.
All signals must be based on the complete previous bar; entry next bar's open.
"""
from __future__ import annotations
import sqlite3, json, hashlib, sys, csv
from contextlib import closing
from pathlib import Path
import numpy as np, pandas as pd

ROOT=Path(__file__).resolve().parent
CANDIDATE_DBS=[
 ROOT.parent/'gold-system-export-2026-10-30/01_candles/candles.db',
 ROOT.parent/'01_candles/candles.db',
 Path('/mnt/data/gold_newresearch/gold-system-export-2026-10-30/01_candles/candles.db'),
]
SRC=next((p for p in CANDIDATE_DBS if p.exists()),CANDIDATE_DBS[0])
OUT=Path(__file__).resolve().parent
COSTS=[0.4,1.0]
CONFIG={
 'VIRGIN_REJECTION_M1': {'tf':'1min','source':'sivaram311/xauusd-virgin-rejection','rr':1.5,'cap':0.8,'horizon':90},
 'VIRGIN_REJECTION_M5': {'tf':'5min','source':'sivaram311/xauusd-virgin-rejection','rr':1.5,'cap':0.8,'horizon':35},
 'GOLD_REVERSION_GUARD_M5': {'tf':'5min','source':'ronnisnai-frog/Gold-Scalping','rr':'SMA50','cap':10.0,'horizon':40},
 'FIB_50_618_M15': {'tf':'15min','source':'MouadZaki/Fibonacci-Backtesting-XAUUSD','rr':1.5,'cap':10.0,'horizon':35},
 'FOUR_CANDLE_MOMENTUM_M5': {'tf':'5min','source':'Shivkeerth-Laj/XAUUSD-Backtesting','rr':1.5,'cap':10.0,'horizon':35},
 'FOUR_CANDLE_REVERSAL_M5': {'tf':'5min','source':'Shivkeerth-Laj/XAUUSD-Backtesting','rr':1.5,'cap':10.0,'horizon':35},
 'MTF_EMA_PULLBACK_M15': {'tf':'15min','source':'itsmustafa119/structure-scope','rr':1.5,'cap':10.0,'horizon':35},
 'SMC_DISCOUNT_PULLBACK_M15': {'tf':'15min','source':'itsmustafa119/structure-scope','rr':2.0,'cap':10.0,'horizon':45},
 'TWO_RSI_M5': {'tf':'5min','source':'scottfrancis90/scottx-trading-research','rr':2.0,'cap':10.0,'horizon':40},
 'PIN_BAR_M5': {'tf':'5min','source':'scottfrancis90/scottx-trading-research','rr':1.5,'cap':10.0,'horizon':35},
 'ENGULFING_M5': {'tf':'5min','source':'scottfrancis90/scottx-trading-research','rr':1.5,'cap':10.0,'horizon':35},
 'BOLL_SQUEEZE_M5': {'tf':'5min','source':'scottfrancis90/scottx-trading-research','rr':2.0,'cap':10.0,'horizon':40},
 'EMA50_200_TREND_H1': {'tf':'1h','source':'MoAbdullahi/Trading-Research','rr':2.0,'cap':10.0,'horizon':48},
 'DONCHIAN55_H4': {'tf':'4h','source':'MoAbdullahi/Trading-Research','rr':2.0,'cap':10.0,'horizon':50},
}


def load(tf):
 with closing(sqlite3.connect(SRC)) as con:
  z=pd.read_sql_query("SELECT ts,o,h,l,c,source FROM candles WHERE interval=? AND symbol LIKE '%XAU%' AND source='ctrader' ORDER BY ts",con,params=(tf,))
  if z.empty: z=pd.read_sql_query("SELECT ts,o,h,l,c,source FROM candles WHERE interval=? AND source='ctrader' ORDER BY ts",con,params=(tf,))
 z['ts']=pd.to_datetime(z.ts,errors='coerce');z=z.dropna(subset=['ts','o','h','l','c']).drop_duplicates('ts',keep='last').sort_values('ts');z=z.set_index('ts').rename(columns={'o':'open','h':'high','l':'low','c':'close'})
 z=z.loc[(z.high>=z.low)&(z.open>=z.low)&(z.open<=z.high)&(z.close>=z.low)&(z.close<=z.high)]
 return z

def atr(df,n=14):
 c=df.close.shift(1)
 tr=pd.concat([df.high-df.low,(df.high-c).abs(),(df.low-c).abs()],axis=1).max(axis=1)
 return tr.ewm(alpha=1/n,adjust=False).mean()
def rsi(c,n=14):
 d=c.diff();u=d.clip(lower=0).ewm(alpha=1/n,adjust=False).mean();v=(-d.clip(upper=0)).ewm(alpha=1/n,adjust=False).mean();rs=u/(v.replace(0,np.nan));return 100-100/(1+rs)
def adx(df,n=14):
 # Wilder-style smoothing, causal
 up=df.high.diff();down=-df.low.diff()
 pdm=up.where((up>down)&(up>0),0);mdm=down.where((down>up)&(down>0),0)
 aa=atr(df,n).replace(0,np.nan)
 pdi=100*pdm.ewm(alpha=1/n,adjust=False).mean()/aa
 mdi=100*mdm.ewm(alpha=1/n,adjust=False).mean()/aa
 dx=100*(pdi-mdi).abs()/(pdi+mdi).replace(0,np.nan)
 return dx.ewm(alpha=1/n,adjust=False).mean(),pdi,mdi

def empty(d): return pd.DataFrame({'side':np.zeros(len(d),dtype=np.int8),'stop':np.full(len(d),np.nan),'target':np.full(len(d),np.nan)},index=d.index)

def attach(d,side,risk,rr=1.5, target=None):
 out=empty(d);side=pd.Series(side,index=d.index).fillna(0).astype(int).clip(-1,1)
 risk=pd.Series(risk,index=d.index).astype(float)
 out['side']=side;out['stop']=d.close-side*risk
 out['target']=d.close+side*risk*rr if target is None else target
 out.loc[(side==0)|(~np.isfinite(risk))|(risk<=0),'side']=0
 return out

def virgin(d):
 # Fixed original's `high>=level OR low<=level` condition: tautology; correct is low<=level<=high.
 # Guard against expensive O(n²): track latest 150 completed candles and only candidate levels not touched in between.
 n=len(d);o=d.open.to_numpy();h=d.high.to_numpy();l=d.low.to_numpy();c=d.close.to_numpy()
 side=np.zeros(n,dtype=int);risk=np.full(n,np.nan)
 for i in range(10,n):
  lw=min(o[i],c[i])-l[i];uw=h[i]-max(o[i],c[i]);
  if lw<.30 and uw<.30:continue
  jrange=range(max(0,i-150),i-6)
  # recent descending candidates for speed, not exact original older-to-newer pick.
  for j in reversed(jrange):
   lvl=c[j]
   if not (l[i]<=lvl<=h[i]):continue
   if np.any((l[j+1:i]<=lvl)&(h[j+1:i]>=lvl)):continue
   if lw>=.30 and c[i]-l[i]+.01<=.8 and c[i]-l[i]+.01>.05:
    side[i]=1;risk[i]=c[i]-l[i]+.01;break
   if uw>=.30 and h[i]-c[i]+.01<=.8 and h[i]-c[i]+.01>.05:
    side[i]=-1;risk[i]=h[i]-c[i]+.01;break
 return attach(d,side,risk,1.5)

def reversion(d):
 m=d.close.rolling(50).mean();sd=d.close.rolling(50).std(ddof=0).replace(0,np.nan)
 z=(d.close-m)/sd; a=atr(d);av=a.rolling(50).mean();ax,_,_=adx(d)
 shift=(z.abs()<=z.abs().shift(1))
 ok=(ax<22)&(a>=.5*av)&(a<=2*av)&(sd>=1.2)&((d.close-m).abs()>=1.6)&shift
 side=np.select([ok&(z<=-2.2),ok&(z>=2.2)],[1,-1],0)
 risk=np.maximum(2.5*a,5.0)
 sig=attach(d,side,risk,1.5,target=m)
 # valid target must be past price (long > entry / short < entry)
 sig.loc[(sig.side*(sig.target-d.close)<=0),'side']=0
 return sig

def fib(d):
 # previous 50 bars only, no current candle in range. Use mid-level 50%, 61.8%.
 hi=d.high.shift(1).rolling(50).max();lo=d.low.shift(1).rolling(50).min();rg=hi-lo
 s=np.zeros(len(d),dtype=int);lv1=hi-.5*rg;lv2=hi-.618*rg
 long_touch=(d.low<=lv2)&(d.high>=lv2)&(d.close>lv2)&(d.close>d.open)
 short_touch=(d.low<=lv1)&(d.high>=lv1)&(d.close<lv1)&(d.close<d.open)
 s=np.select([long_touch,short_touch],[1,-1],0)
 return attach(d,s,2*atr(d),1.5)

def four(d,rev=False):
 up=d.close>d.open;dn=d.close<d.open
 four_up=(up.shift(1)&up.shift(2)&up.shift(3)&up.shift(4)).fillna(False)
 four_down=(dn.shift(1)&dn.shift(2)&dn.shift(3)&dn.shift(4)).fillna(False)
 # momentum signal after fourth candle only, or rejection for reversal
 if rev:
  side=np.select([four_down&up&(d.close>d.open.shift(1)),four_up&dn&(d.close<d.open.shift(1))],[1,-1],0)
 else:
  side=np.select([four_up&up&(d.close>d.high.shift(1)),four_down&dn&(d.close<d.low.shift(1))],[1,-1],0)
 return attach(d,side,1.5*atr(d),1.5)

def mtf_pullback(d):
 # H1/H4 EMA constructed on last completed source bar before M15 signal; timezone only impacts boundaries.
 e20=d.close.ewm(span=20,adjust=False).mean();e100=d.close.ewm(span=100,adjust=False).mean(); a=atr(d)
 ax,pdi,mdi=adx(d);rr=rsi(d.close)
 # resample completed 1h and 4h; signals available on boundary close only
 ctx=[]
 for tf in ['1h','4h']:
  b=d.close.resample(tf,label='right',closed='left').last();em=b.ewm(span=50,adjust=False).mean()
  cb=b.reindex(d.index,method='ffill');eb=em.reindex(d.index,method='ffill');sl=em.diff().reindex(d.index,method='ffill')
  ctx.append((cb,eb,sl))
 bull=(e20>e100)&(e20>e20.shift(1))&(ctx[0][0]>ctx[0][1])&(ctx[0][2]>0)&(ctx[1][0]>ctx[1][1])&(ctx[1][2]>0)
 bear=(e20<e100)&(e20<e20.shift(1))&(ctx[0][0]<ctx[0][1])&(ctx[0][2]<0)&(ctx[1][0]<ctx[1][1])&(ctx[1][2]<0)
 bull=bull&(ax>=22)&(pdi>mdi)&rr.between(45,70)&(((d.close-e20).abs()/a)<=.35)&(d.close>e20)&(d.close.shift(1)<=e20.shift(1))
 bear=bear&(ax>=22)&(mdi>pdi)&rr.between(30,55)&(((d.close-e20).abs()/a)<=.35)&(d.close<e20)&(d.close.shift(1)>=e20.shift(1))
 return attach(d,np.select([bull,bear],[1,-1],0),1.25*a,1.5)

def smc_pullback(d):
 # confirmed 3+3 pivots only, structure higher/lower via confirmed break, discount first close
 a=atr(d);hi=d.high.to_numpy();lo=d.low.to_numpy();c=d.close.to_numpy();n=len(d)
 sh=np.full(n,np.nan);sl=np.full(n,np.nan)
 last_hi=last_lo=np.nan;trend=0
 sides=np.zeros(n,dtype=int);stops=np.full(n,np.nan)
 for i in range(12,n):
  p=i-3
  if hi[p]>np.max(hi[p-3:p]) and hi[p]>np.max(hi[p+1:i+1]):last_hi=hi[p]
  if lo[p]<np.min(lo[p-3:p]) and lo[p]<np.min(lo[p+1:i+1]):last_lo=lo[p]
  if np.isfinite(last_hi) and np.isfinite(last_lo):
   if c[i]>last_hi:trend=1
   elif c[i]<last_lo:trend=-1
   mid=(last_hi+last_lo)/2
   if trend==1 and c[i]<mid and c[i-1]>=mid and c[i]>last_lo:
    sides[i]=1;stops[i]=min(last_lo-.1*a.iloc[i],c[i]-1.5*a.iloc[i])
   elif trend==-1 and c[i]>mid and c[i-1]<=mid and c[i]<last_hi:
    sides[i]=-1;stops[i]=max(last_hi+.1*a.iloc[i],c[i]+1.5*a.iloc[i])
 risk=np.where(sides==1,c-stops,stops-c)
 return attach(d,sides,risk,2)

def two_rsi(d):
 r14=rsi(d.close,14);r35=rsi(d.close,35);a=atr(d)
 # simple dual confirmation, threshold preselected and no tuning
 sides=np.select([(r14>r35)&(r14.shift(1)<=r35.shift(1))&(r14<65), (r14<r35)&(r14.shift(1)>=r35.shift(1))&(r14>35)],[1,-1],0)
 return attach(d,sides,1.5*a,2)

def pinbar(d):
 rg=(d.high-d.low).replace(0,np.nan);body=(d.close-d.open).abs();lw=np.minimum(d.open,d.close)-d.low;uw=d.high-np.maximum(d.open,d.close)
 side=np.select([(lw>.6*rg)&(body<.3*rg)&(d.close>=d.low+.6*rg),(uw>.6*rg)&(body<.3*rg)&(d.close<=d.high-.6*rg)],[1,-1],0)
 return attach(d,side,1.5*atr(d),1.5)

def engulfing(d):
 p=d.shift(1);bull=(d.close>d.open)&(p.close<p.open)&(d.close>p.open)&(d.open<p.close)
 bear=(d.close<d.open)&(p.close>p.open)&(d.close<p.open)&(d.open>p.close)
 return attach(d,np.select([bull,bear],[1,-1],0),1.5*atr(d),1.5)

def boll_squeeze(d):
 mid=d.close.rolling(20).mean();sd=d.close.rolling(20).std();bwidth=4*sd/mid
 narrow=bwidth.shift(1)<bwidth.rolling(100).quantile(.20).shift(1)
 up=mid+2*sd;low=mid-2*sd
 side=np.select([narrow&(d.close>up.shift(1))&(d.close.shift(1)<=up.shift(2)),narrow&(d.close<low.shift(1))&(d.close.shift(1)>=low.shift(2))],[1,-1],0)
 return attach(d,side,1.5*atr(d),2)

def ema_h1(d):
 e50=d.close.ewm(span=50,adjust=False).mean();e200=d.close.ewm(span=200,adjust=False).mean();a=atr(d)
 side=np.select([(e50>e200)&(e50.shift(1)<=e200.shift(1)),(e50<e200)&(e50.shift(1)>=e200.shift(1))],[1,-1],0)
 return attach(d,side,1.5*a,2)

def donchian_h4(d):
 u=d.high.shift(1).rolling(55).max();l=d.low.shift(1).rolling(55).min();a=atr(d)
 side=np.select([(d.close>u)&(d.close.shift(1)<=u.shift(1)),(d.close<l)&(d.close.shift(1)>=l.shift(1))],[1,-1],0)
 return attach(d,side,2*a,2)

FUNCS={'VIRGIN_REJECTION_M1':virgin,'VIRGIN_REJECTION_M5':virgin,'GOLD_REVERSION_GUARD_M5':reversion,'FIB_50_618_M15':fib,'FOUR_CANDLE_MOMENTUM_M5':lambda d:four(d,False),'FOUR_CANDLE_REVERSAL_M5':lambda d:four(d,True),'MTF_EMA_PULLBACK_M15':mtf_pullback,'SMC_DISCOUNT_PULLBACK_M15':smc_pullback,'TWO_RSI_M5':two_rsi,'PIN_BAR_M5':pinbar,'ENGULFING_M5':engulfing,'BOLL_SQUEEZE_M5':boll_squeeze,'EMA50_200_TREND_H1':ema_h1,'DONCHIAN55_H4':donchian_h4}

def replay(d,sig,cap=10,rr=1.5,horizon=48,cost=0.4):
 # Single-position execution, stop-first and adverse gap, signals after close, fill next-open.
 # Any gap across weekend during open trade exits at next opening price if stop crossed.
 if cost<0 or cap<=0 or horizon<1:raise ValueError('Bad replay costs or risk policy')
 n=len(d);o,h,l,c=[d[k].to_numpy(dtype=float) for k in ['open','high','low','close']];ss=sig.side.to_numpy(dtype=int);st=sig.stop.to_numpy(dtype=float);tg=sig.target.to_numpy(dtype=float)
 ts=d.index.to_numpy();i=100;trades=[];candidates=int(np.sum(ss!=0));rejected=0
 while i<n-1:
  if not ss[i] or not np.isfinite(st[i]):i+=1;continue
  side=int(ss[i]);entry=o[i+1]
  # Stop computed using signal close; risk checked again from achievable entry price.
  stop=st[i];risk=side*(entry-stop)
  if risk<=.20 or risk>cap:
   rejected+=1;i+=1;continue
  target=entry+side*risk*rr if isinstance(rr,(float,int)) else tg[i]
  if not np.isfinite(target) or side*(target-entry)<=0:
   rejected+=1;i+=1;continue
  exit_k=min(n-1,i+1+int(horizon));px=c[exit_k];reason='TIME'
  for k in range(i+1,exit_k+1):
   # Stop at open gap is worse; then intrabar stop before target.
   if side*(o[k]-stop)<=0:
    px=min(stop,o[k]) if side==1 else max(stop,o[k]);reason='GAP_STOP';exit_k=k;break
   if (l[k]<=stop if side==1 else h[k]>=stop):
    px=stop;reason='STOP';exit_k=k;break
   if (h[k]>=target if side==1 else l[k]<=target):
    px=target;reason='TARGET';exit_k=k;break
  net=side*(px-entry)/risk-cost/risk
  trades.append({'entry_time':str(ts[i+1]),'exit_time':str(ts[exit_k]),'side':'BUY' if side==1 else 'SELL','entry':round(entry,5),'stop':round(stop,5),'target':round(target,5),'risk_price':round(risk,5),'exit':round(float(px),5),'exit_reason':reason,'net_R':round(float(net),7)})
  i=exit_k+1
 return trades,{'candidates':candidates,'rejected_risk_or_target':rejected}

def mt(tr):
 r=np.array([x['net_R'] for x in tr],dtype=float)
 if len(r)==0:return {'trades':0,'win_rate':None,'total_R':0,'avg_R':None,'PF':None,'max_DD_R':None}
 cs=np.r_[0,r.cumsum()];win=r[r>0].sum();loss=-r[r<0].sum()
 return {'trades':len(r),'win_rate':round(float(np.mean(r>0)),4),'total_R':round(float(r.sum()),4),'avg_R':round(float(r.mean()),4),'PF':round(float(win/loss),3) if loss>0 else None,'max_DD_R':round(float((np.maximum.accumulate(cs)-cs).max()),3)}

def main():
 dbsha=hashlib.sha256(SRC.read_bytes()).hexdigest();d_cache={tf:load(tf) for tf in ['1min','5min','15min','1h','4h']}
 output={'database_sha256':dbsha,'data':{tf:{'bars':len(d),'start':str(d.index.min()),'end':str(d.index.max()),'source_counts':d.source.value_counts().to_dict()} for tf,d in d_cache.items()},'setup_experiments':{},'notes':['Offline rule adaptations from public Github, NOT original GitHub executable code nor exact author performance.','Calendar/news filters not executed: missing reliable timezone/news timestamps.','No true bid-ask or volume; assumed fixed 0.4 / 1.0 USD-price roundtrip, stops conservative.','All entry signals evaluated on completed bar and filled at next open.','Parameters selected before looking at current scan results; do not optimize against this sample.','Chronological 60/40 split is descriptive (other variants already researched on overlapping period), not pristine independent holdout.','No demo or live orders sent.','Stops greater than 10 XAUUSD price units rejected; no profit guarantee.']}
 for name,conf in CONFIG.items():
  df=d_cache[conf['tf']];sig=FUNCS[name](df)
  rec={'source':conf['source'],'timeframe':conf['tf'],'bars':len(df),'variant_kind':'independent rule adaptation','cost_results':{}}
  for cost in COSTS:
   tr,stats=replay(df,sig,cap=conf['cap'],rr=conf['rr'],horizon=conf['horizon'],cost=cost)
   cut=int(len(df)*.6);dtcut=df.index[cut]
   # split by entry time; trades may cross boundary; diagnostic only.
   d1=[t for t in tr if pd.Timestamp(t['entry_time'])<dtcut];d2=[t for t in tr if pd.Timestamp(t['entry_time'])>=dtcut]
   k=str(cost);rec['cost_results'][k]={**mt(tr),'pre_60pct':mt(d1),'post_40pct':mt(d2),**stats}
   if cost==COSTS[0]:
    f=OUT/f'{name}.csv'
    with open(f,'w',newline='',encoding='utf-8') as fh:
     writer=csv.DictWriter(fh,fieldnames=['entry_time','exit_time','side','entry','stop','target','risk_price','exit','exit_reason','net_R']);writer.writeheader();writer.writerows(tr)
  output['setup_experiments'][name]=rec
  print(name,rec['cost_results']['0.4']['trades'],rec['cost_results']['0.4']['total_R'],flush=True)
 (OUT/'results.json').write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf8')
 print('COMPLETE',len(output['setup_experiments']))
if __name__=='__main__':main()
