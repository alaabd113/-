#!/usr/bin/env python3
"""Research-only extra Github-inspired strategy screening on existing cTrader-only XAUUSD.
Dependencies pandas/numpy; refers to earlier GoldStation wide_research.py for fixed replay methodology.
No broker integration and no orders. Strategy implementations are adaptations, not executions of original repos.
"""
from __future__ import annotations
import json,sqlite3,importlib.util,sys,hashlib
from pathlib import Path
import numpy as np,pandas as pd
ROOT=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('gold_previous_replay',ROOT/'wide_research.py');base=importlib.util.module_from_spec(spec);sys.modules[spec.name]=base;spec.loader.exec_module(base)
base.SRC=ROOT/'candles.db'
atr=base.atr;rsi=base.rsi;adx=base.adx;attach=base.attach;replay=base.replay;mt=base.mt

# risk is based on completed signal bar; entry next open, original R determined by next open
# avoid forward fill of incomplete H1: reindex only completed H1 close states, at right-hand boundary.
def ema(s,n):return s.ewm(span=n,adjust=False,min_periods=n).mean()
def bb(d,n=20):
 m=d.close.rolling(n).mean();s=d.close.rolling(n).std(ddof=0);return m,s

def completed_htf(d,tf='1h',n1=50,n2=200):
 b=d.close.resample(tf,label='right',closed='left').last().dropna();a=ema(b,n1).reindex(d.index,method='ffill');f=ema(b,n2).reindex(d.index,method='ffill');return a,f

def fvg_quality(d,threshold=50):
 # simplified analog of FvgGold (not exact EA): true 3-bar FVG, ATR-scaled gap, impulse, H1 EMA bias.
 # Signal ONLY on first later return to a previously created zone.
 a=atr(d); m50,m200=completed_htf(d,'1h');c=d.close.to_numpy();h=d.high.to_numpy();l=d.low.to_numpy();o=d.open.to_numpy();av=a.to_numpy()
 mfast=m50.to_numpy();mslow=m200.to_numpy();n=len(d);side=np.zeros(n,int);risk=np.full(n,np.nan)
 # active zones [direction,bottom,top,age,score] newest first; loop only past and current close
 zones=[]
 for i in range(202,n):
  av_i=av[i]
  if not np.isfinite(av_i) or av_i<.1:continue
  # first retest occurs AFTER detection (cannot reenter same candle)
  keep=[]
  for z in zones:
   dire,bot,top,created,score=z
   if i-created>20:continue
   if i-created>=2 and l[i]<=top and h[i]>=bot:
    if side[i]==0 and score>=threshold and ((dire>0 and c[i]>=bot) or (dire<0 and c[i]<=top)):
     st=bot-0.25*av_i if dire==1 else top+0.25*av_i
     r=dire*(c[i]-st)
     if .2<r<=10:side[i]=dire;risk[i]=r
    continue # first touch consumes zone whether signal or not
   keep.append(z)
  zones=keep
  dire=0;bot=top=0
  if l[i]>h[i-2]:dire=1;bot=h[i-2];top=l[i]
  elif h[i]<l[i-2]:dire=-1;bot=h[i];top=l[i-2]
  if dire and np.isfinite(mfast[i]) and np.isfinite(mslow[i]):
   gap=top-bot; body=abs(c[i-1]-o[i-1]);rng=max(.001,h[i-1]-l[i-1]);trend=1 if mfast[i]>mslow[i] else -1
   sc=min(30,gap/max(av_i,.01)*30)+30*min(1,body/rng)+(20 if trend==dire else 0)+10 # no guessed pd/ob bonus
   zones.append((dire,bot,top,i,sc))
  zones=zones[-60:]
 return attach(d,side,risk,1.5)

def engulf_retest(d):
 # adaptation of NadirAli Official: original engulf creates zone, later retest and NEW engulf on confirmed bar.
 c=d.close.to_numpy();o=d.open.to_numpy();h=d.high.to_numpy();l=d.low.to_numpy();n=len(d)
 e=ema(d.close,50).to_numpy();side=np.zeros(n,int);risk=np.full(n,np.nan);zones=[]
 for i in range(55,n):
  bull=c[i]>o[i] and c[i-1]<o[i-1] and c[i]>o[i-1] and o[i]<=c[i-1]
  bear=c[i]<o[i] and c[i-1]>o[i-1] and c[i]<o[i-1] and o[i]>=c[i-1]
  zones2=[]
  for dr,bot,top,created,left in zones:
   if i-created>30:continue
   if not left:
    if (dr==1 and c[i]>top) or (dr==-1 and c[i]<bot):left=True
   elif l[i]<=top and h[i]>=bot:
    if side[i]==0 and ((dr==1 and bull and c[i]>e[i]) or (dr==-1 and bear and c[i]<e[i])):
     stop=bot-.1 if dr==1 else top+.1
     r=dr*(c[i]-stop)
     if .2<r<=10:side[i]=dr;risk[i]=r
    continue
   zones2.append((dr,bot,top,created,left))
  zones=zones2
  if bull and c[i]>e[i]:zones.append((1,l[i],h[i],i,False))
  if bear and c[i]<e[i]:zones.append((-1,l[i],h[i],i,False))
  zones=zones[-50:]
 return attach(d,side,risk,1.0)

def pine_ema_rsi(d,hours=False):
 # Paulaustin Pine strategy without trade_on_close, matches entry logic; optional hours require verified UTC (unverified here)
 a=atr(d);ef=ema(d.close,9);es=ema(d.close,18);m,_=bb(d);r=rsi(d.close,14)
 bull=((ef.shift(1)<=es.shift(1))&(ef>es))|((ef>es)&(d.close>ef)&(d.close>m)&(r>45)&(r<70))
 bear=((ef.shift(1)>=es.shift(1))&(ef<es))|((ef<es)&(d.close<ef)&(d.close<m)&(r>30)&(r<55))
 if hours:bull &= pd.Series(d.index.hour,index=d.index).isin([2,8,15,18,19,21]);bear &= pd.Series(d.index.hour,index=d.index).isin([2,8,15,18,19,21])
 return attach(d,np.select([bull,bear],[1,-1],0),2*a,1.25)

def macd(d):
 f=ema(d.close,12);s=ema(d.close,26);mac=f-s;signal=ema(mac,9);return mac,signal

def macd_adx_long(d):
 a=atr(d);m,s=macd(d);ax,pdi,mdi=adx(d)
 trend=(ema(d.close,50)>ema(d.close,200))&(ax>20)&(pdi>mdi)
 cross=(m>s)&(m.shift(1)<=s.shift(1))
 return attach(d,(trend&cross).astype(int),1.5*a,2)

def stoch_ema(d):
 lo=d.low.rolling(14).min();hi=d.high.rolling(14).max();k=100*(d.close-lo)/(hi-lo).replace(0,np.nan);d3=k.rolling(3).mean()
 trend=d.close>ema(d.close,100);side=(trend&(k>d3)&(k.shift(1)<=d3.shift(1))&(k<50)).astype(int)
 return attach(d,side,1.5*atr(d),2)

def supertrend_pullback(d):
 # simplified Supertrend 25,3 plus DEMA250 trend and close after line flip. Omits M5 confirmation, pyramiding, exact author stop.
 a=atr(d,25).to_numpy();cl=d.close.to_numpy();hi=d.high.to_numpy();lo=d.low.to_numpy();n=len(d)
 bas=(hi+lo)/2;ub=bas+3*a;lb=bas-3*a;fu=ub.copy();fl=lb.copy();trend=np.ones(n,int)
 for i in range(1,n):
  if np.isfinite(fu[i-1]) and (ub[i]>=fu[i-1] and cl[i-1]<=fu[i-1]):fu[i]=fu[i-1]
  if np.isfinite(fl[i-1]) and (lb[i]<=fl[i-1] and cl[i-1]>=fl[i-1]):fl[i]=fl[i-1]
  if cl[i]>fu[i-1]:trend[i]=1
  elif cl[i]<fl[i-1]:trend[i]=-1
  else:trend[i]=trend[i-1]
 de=2*ema(d.close,250)-ema(ema(d.close,250),250);dv=de.to_numpy()
 side=np.zeros(n,int);risk=np.full(n,np.nan)
 for i in range(520,n):
  if trend[i]!=trend[i-1]:continue
  # near prior ema20 in trend, after a flip in last 12 bars, resumed momentum
  if trend[i]>0 and cl[i]>dv[i] and cl[i]>cl[i-1] and lo[i]<=cl[i-1]-.3*a[i]:side[i]=1;risk[i]=1.5*a[i]
  if trend[i]<0 and cl[i]<dv[i] and cl[i]<cl[i-1] and hi[i]>=cl[i-1]+.3*a[i]:side[i]=-1;risk[i]=1.5*a[i]
 return attach(d,side,risk,2)

def donchian_compression(d):
 a=atr(d);up=d.high.shift(1).rolling(10).max();dn=d.low.shift(1).rolling(10).min()
 width=d.high.rolling(20).max()-d.low.rolling(20).min();q=width.shift(1).rolling(200).quantile(.5)
 press=width.shift(1)<q
 side=np.select([press&(d.close>up),press&(d.close<dn)],[1,-1],0)
 return attach(d,side,1*a,2)

def rsi2_reversion(d):
 a=atr(d);r2=rsi(d.close,2);m=ema(d.close,200)
 side=np.select([(d.close>m)&(r2<10)&(d.close>d.open),(d.close<m)&(r2>90)&(d.close<d.open)],[1,-1],0)
 return attach(d,side,1.3*a,1.5)

def keltner_breakout(d):
 a=atr(d);m=ema(d.close,20);ax,p,mn=adx(d);upper=m+1.5*a;lower=m-1.5*a
 s=np.select([(d.close>upper.shift(1))&(d.close.shift(1)<=upper.shift(2))&(ax>20),(d.close<lower.shift(1))&(d.close.shift(1)>=lower.shift(2))&(ax>20)],[1,-1],0)
 return attach(d,s,1.3*a,2)

def inside_break(d):
 prev=d.shift(1);mother=d.shift(2);inside=(prev.high<mother.high)&(prev.low>mother.low)
 s=np.select([inside&(d.close>mother.high),inside&(d.close<mother.low)],[1,-1],0)
 return attach(d,s,np.maximum(1.25*atr(d),d.high.shift(2)-d.low.shift(2)),1.5)

def nr4_break(d):
 r=d.high-d.low; narrow=(r.shift(1)<r.shift(2))&(r.shift(1)<r.shift(3))&(r.shift(1)<r.shift(4))
 s=np.select([narrow&(d.close>d.high.shift(1))&(d.close>d.open),narrow&(d.close<d.low.shift(1))&(d.close<d.open)],[1,-1],0)
 return attach(d,s,1.4*atr(d),1.5)

def squeeze_keltner(d):
 a=atr(d);m,sd=bb(d);u=m+2*sd;l=m-2*sd;ku=m+1.5*a;kl=m-1.5*a
 sq=(u.shift(1)<ku.shift(1))&(l.shift(1)>kl.shift(1))
 s=np.select([sq&(d.close>u.shift(1))&(d.close>d.open),sq&(d.close<l.shift(1))&(d.close<d.open)],[1,-1],0)
 return attach(d,s,1.4*a,2)

def rsi_trend(d):
 r=rsi(d.close);e=ema(d.close,50);a=atr(d)
 s=np.select([(d.close>e)&(r>55)&(r.shift(1)<=55),(d.close<e)&(r<45)&(r.shift(1)>=45)],[1,-1],0)
 return attach(d,s,1.5*a,2)

def atr_expansion(d):
 a=atr(d);avg=a.rolling(60).mean();v=(d.high-d.low)>2*a.shift(1)
 s=np.select([v&(d.close>d.high.shift(1))&(d.close>d.open)&(a>avg),(v)&(d.close<d.low.shift(1))&(d.close<d.open)&(a>avg)],[1,-1],0)
 return attach(d,s,1.5*a,1.5)

def macd_hist_cross(d):
 m,s=macd(d);hist=m-s; e=ema(d.close,100);a=atr(d)
 x=np.select([(hist>0)&(hist.shift(1)<=0)&(d.close>e),(hist<0)&(hist.shift(1)>=0)&(d.close<e)],[1,-1],0)
 return attach(d,x,1.5*a,1.5)

def pivot_prev_day(d):
 # previous completed daily levels; 1min/5min bars. No intrabar entries on old daily highs.
 dt=d.index.floor('D');prev=d.resample('1D',label='right',closed='left').agg({'high':'max','low':'min','close':'last'})
 pp=((prev.high+prev.low+prev.close)/3).reindex(d.index,method='ffill')
 a=atr(d);hi=pp+.5*a;lo=pp-.5*a
 s=np.select([(d.low<=pp)&(d.close>pp)&(d.close>d.open)&(d.close.shift(1)<pp.shift(1)),(d.high>=pp)&(d.close<pp)&(d.close<d.open)&(d.close.shift(1)>pp.shift(1))],[1,-1],0)
 return attach(d,s,1.5*a,1.5)

def long_d1_trend(d):
 m=ema(d.close,20);a=atr(d)
 side=((d.close>ema(d.close,200))&(d.close>m)&(d.low<=m)&(d.close>d.open)).astype(int)
 return attach(d,side,2*a,2)

def long_d1_donchian(d):
 a=atr(d);u=d.high.shift(1).rolling(20).max();side=(d.close>u)&(d.close.shift(1)<=u.shift(1))
 return attach(d,side.astype(int),2.5*a,3)

def ema50_pullback(d):
 a=atr(d);e=ema(d.close,50);e200=ema(d.close,200)
 s=np.select([(e>e200)&(d.low<e)&(d.close>e)&(d.close>d.open),(e<e200)&(d.high>e)&(d.close<e)&(d.close<d.open)],[1,-1],0)
 return attach(d,s,1.4*a,1.5)

def h1_orb(d):
 # Hourly opening range: use first bar of day, subsequent two bars must fit inside first range;
 # late breakout; No timezone certainty: session diagnostic only.
 dates=d.index.normalize();n=len(d);side=np.zeros(n,int);risk=np.full(n,np.nan)
 for _,idx in pd.Series(np.arange(n),index=d.index).groupby(dates):
  q=idx.to_numpy()
  if len(q)<6:continue
  first=q[0];hi=d.high.iloc[first];lo=d.low.iloc[first];r=hi-lo
  if r<=.5:continue
  if not (d.high.iloc[q[1:3]]<=hi).all() or not (d.low.iloc[q[1:3]]>=lo).all():continue
  for i in q[3:]:
   if d.close.iloc[i]>hi:side[i]=1;risk[i]=min(1.5*atr(d).iloc[i], d.close.iloc[i]-lo);break
   if d.close.iloc[i]<lo:side[i]=-1;risk[i]=min(1.5*atr(d).iloc[i],hi-d.close.iloc[i]);break
 return attach(d,side,risk,1.5)

# Public repo linkage is inspiration; every variant is explicitly a replica/adaptation.
SETS={
'FVG_SCORE50_M15':('15min',fvg_quality,1.5,35,'foeed/FvgGold-EA','FVG score approximation; H1 trend, no OB/killzone'),
'FVG_SCORE70_M15':('15min',lambda d:fvg_quality(d,70),1.5,35,'foeed/FvgGold-EA','FVG 70 score approximation'),
'ENGULF_ZONE_RETEST_M5':('5min',engulf_retest,1,35,'NadirAliOfficial/engulfing-zone-ea','Simplified EMA50 trend instead of full HH/HL confirmation'),
'PINE_EMA9_18_ALL_M5':('5min',pine_ema_rsi,1.25,3,'Paulaustin3977/OANDA-XAUUSD-Optimized-5m','Frozen EMA RSI BB logic; all hours; source params optimized elsewhere'),
'PINE_EMA9_18_HOURS_M5':('5min',lambda d:pine_ema_rsi(d,True),1.25,3,'Paulaustin3977/OANDA-XAUUSD-Optimized-5m','Source-selected UTC hours; local timestamps unverified'),
'MACD_ADX_LONG_H1':('1h',macd_adx_long,2,35,'maker-tung/xauusd-trend-follow','MACD entry + ADX/EMA; no EA live risk controls'),
'STOCH_EMA_LONG_H1':('1h',stoch_ema,2,35,'maker-tung/xauusd-trend-follow','Stochastic EMA pullback long-only'),
'SUPERTREND_DEMA_M30':('30min',supertrend_pullback,2,45,'WayneTradeFr/quant-research','Simplification without M5 triggers/pyramiding'),
'DONCHIAN10_COMPRESS_M30':('30min',donchian_compression,2,45,'WayneTradeFr/quant-research','Partial exits/trailing not replicated; fixed RR'),
'RSI2_REVERSION_M5':('5min',rsi2_reversion,1.5,25,'Sorama4012/xauusd-strategy-lab','Generic RSI2 reversal hypothesis, not original strategy'),
'KELTNER_BREAKOUT_M5':('5min',keltner_breakout,2,30,'LORD-ZYTHOZ/goldvein','Independent channel-breakout candidate'),
'INSIDE_BAR_BREAK_M5':('5min',inside_break,1.5,35,'NadirAliOfficial/engulfing-zone-ea','Price-action alternate, independent hypothesis'),
'NR4_BREAKOUT_M5':('5min',nr4_break,1.5,35,'yulz008/GOLD_ORB','Compression breakout independent extension, not original ORB'),
'BB_KELTNER_SQUEEZE_M15':('15min',squeeze_keltner,2,32,'LORD-ZYTHOZ/goldvein','Bollinger/Keltner alternate squeeze'),
'RSI14_EMA50_TREND_M15':('15min',rsi_trend,2,32,'Isyakuahmad/xauusd-ema-rsi-algorithm','EMA+RSI threshold variant, not original complete code'),
'ATR_EXPANSION_M5':('5min',atr_expansion,1.5,35,'LORD-ZYTHOZ/goldvein','ATR expansion momentum candidate'),
'MACD_HIST_TREND_M15':('15min',macd_hist_cross,1.5,35,'maker-tung/xauusd-trend-follow','MACD histogram cross extension'),
'PREV_DAY_PIVOT_M5':('5min',pivot_prev_day,1.5,35,'Sorama4012/xauusd-strategy-lab','Prior-completed-day pivot rebound, distinct from author strategy'),
'D1_EMA20_LONG':('1day',long_d1_trend,2,50,'MoAbdullahi/Trading-Research','Daily long-only baseline, outside M5 peer comparison'),
'D1_DONCHIAN20_LONG':('1day',long_d1_donchian,3,80,'MoAbdullahi/Trading-Research','Daily long-only breakout baseline'),
'EMA50_PB_M5':('5min',ema50_pullback,1.5,35,'sagarmeravi/XAUUSD-Pullback-Strategy-Development-Analysis-','EMA50 pullback family, rule-based adaptation'),
'H1_ORB_3CONSOL':('1h',h1_orb,1.5,14,'yulz008/GOLD_ORB','Simplified ORB; unverified session timezone'),
}

def main():
 db_hash=hashlib.sha256((ROOT/'candles.db').read_bytes()).hexdigest()
 dcache={tf:base.load(tf) for tf in sorted({x[0] for x in SETS.values()})}
 out={'dataset_sha256':db_hash,'data':{tf:{'n':len(d),'min':str(d.index.min()),'max':str(d.index.max())} for tf,d in dcache.items()},'runs':{},'warnings':['All are adaptations/research models, not original EA execution.','Not a fresh OOS because prior investigation has used overlapping candles.','Only cTrader candles used; no real spread, bid/ask, tick volume or verified session time.','Cost 0.4 or 1.0 USD per XAU price unit round-trip; not broker quote.','PO3 remains locked, reference from previous research, not recomputed or re-optimized.','No demo or live trades.','Large-scale screening causes multiple-testing bias; positive results are hypotheses only.']}
 for name,(tf,fn,rr,horizon,repo,notes) in SETS.items():
  d=dcache[tf]
  try:
   sg=fn(d)
   rd={'repo':repo,'notes':notes,'timeframe':tf,'bars':len(d),'results':{},'signals':int((sg.side!=0).sum())}
   for cost in (0.4,1.0,1.5):
    t,detail=replay(d,sg,cap=10.0,rr=rr,horizon=horizon,cost=cost)
    stats=mt(t);cut=d.index[int(.6*len(d))]
    stats['last40_total_R']=round(float(sum(x['net_R'] for x in t if pd.Timestamp(x['entry_time'])>=cut)),4)
    stats['last40_trades']=sum(pd.Timestamp(x['entry_time'])>=cut for x in t)
    stats['max_trade_R']=round(float(max([x['net_R'] for x in t],default=0)),4)
    stats['without_top3_R']=round(float(stats['total_R']-sum(sorted([x['net_R'] for x in t],reverse=True)[:3])),4)
    stats.update(detail)
    rd['results'][str(cost)]=stats
    if cost==0.4:
     import csv
     with (ROOT/(name+'.csv')).open('w',newline='',encoding='utf-8') as f:
      wr=csv.DictWriter(f,fieldnames=list(t[0]) if t else ['entry_time','exit_time','side','entry','stop','target','risk_price','exit','exit_reason','net_R']);wr.writeheader();wr.writerows(t)
   out['runs'][name]=rd
   print(name,tf,rd['results']['0.4']['trades'],rd['results']['0.4']['total_R'],rd['results']['1.0']['total_R'],flush=True)
  except Exception as e:
   out['runs'][name]={'repo':repo,'notes':notes,'error':repr(e)}
   print('ERROR',name,repr(e),flush=True)
 (ROOT/'additional_results.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
 print('finished',len(out['runs']),flush=True)
if __name__=='__main__':main()
