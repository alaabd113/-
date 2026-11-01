"""New (not previously evaluated) GitHub-inspired deterministic research hypotheses.
NOT byte-for-byte copies of remote repositories or claims about their original EAs.
Every signal at bar close, next-open fill. Source adaptations have explicit mapping.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from . import replay_base as b
from pathlib import Path
b.SRC=Path(__file__).resolve().parents[1]/'data/candles.db'


def E(s,n):return s.ewm(span=n,adjust=False,min_periods=n).mean()
def ATR(d):return b.atr(d)
def RSI(s,n=14):return b.rsi(s,n)
def S(d,side,stops,rr=2.0):return b.attach(d,side,stops,rr)
def cross_up(a,v):return (a>v)&(a.shift(1)<=v.shift(1))
def cross_down(a,v):return (a<v)&(a.shift(1)>=v.shift(1))
def macd(d):
 m=E(d.close,12)-E(d.close,26); sig=E(m,9);return m,sig

def ema_rsi_cross(d):
 f=E(d.close,20);slow=E(d.close,50);r=RSI(d.close);a=ATR(d)
 side=np.select([cross_up(f,slow)&r.between(50,70),cross_down(f,slow)&r.between(30,50)],[1,-1],0)
 return S(d,side,1.5*a,2)

def heikin_ashi_rsi(d):
 # HA close is causal, HA open recursively uses prior completed bar.
 ha_c=(d.open+d.high+d.low+d.close)/4
 ho=np.zeros(len(d));o=d.open.to_numpy();hc=ha_c.to_numpy();ho[0]=o[0]
 for i in range(1,len(d)):ho[i]=(ho[i-1]+hc[i-1])/2
 ha_o=pd.Series(ho,index=d.index);r=RSI(d.close);ma=E(ha_c,20)
 side=np.select([cross_up(ha_c,ma)&(ha_c>ha_o)&(r>52),cross_down(ha_c,ma)&(ha_c<ha_o)&(r<48)],[1,-1],0)
 return S(d,side,1.4*ATR(d),1.6)

def triple_confirmation(d):
 a=ATR(d);ema20=E(d.close,20);ema100=E(d.close,100);r=RSI(d.close)
 side=np.select([(ema20>ema100)&(d.low<=ema20)&(d.close>ema20)&r.between(51,68)&(d.close>d.open),
                 (ema20<ema100)&(d.high>=ema20)&(d.close<ema20)&r.between(32,49)&(d.close<d.open)],[1,-1],0)
 return S(d,side,1.25*a,2)

def ema9_rsi(d):
 f=E(d.close,9);slow=E(d.close,21);r=RSI(d.close);a=ATR(d)
 side=np.select([cross_up(f,slow)&(r>55),cross_down(f,slow)&(r<45)],[1,-1],0)
 return S(d,side,1.6*a,1.8)

def macd_ema_trend(d):
 m,s=macd(d); a=ATR(d);fast=E(d.close,20);slow=E(d.close,50)
 side=np.select([cross_up(m,s)&(fast>slow),cross_down(m,s)&(fast<slow)],[1,-1],0)
 return S(d,side,1.8*a,2)

def adx_di_ema(d):
 adx,p,m=b.adx(d);r=RSI(d.close);a=ATR(d);f=E(d.close,20);s=E(d.close,50)
 side=np.select([(adx>25)&(adx.shift(1)<=25)&(p>m)&(f>s)&(r>50),
                 (adx>25)&(adx.shift(1)<=25)&(m>p)&(f<s)&(r<50)],[1,-1],0)
 return S(d,side,1.6*a,2.1)

def boll_rsi_fade(d):
 mid=d.close.rolling(20).mean();sd=d.close.rolling(20).std(ddof=0);r=RSI(d.close)
 side=np.select([(d.low<mid-2*sd)&(d.close>mid-2*sd)&(r<35),
                 (d.high>mid+2*sd)&(d.close<mid+2*sd)&(r>65)],[1,-1],0)
 return S(d,side,1.5*ATR(d),1.6)

def atr_compression(d):
 a=ATR(d);m=E(d.close,30);r=d.high-d.low; prior=r.shift(1).rolling(10).mean()
 side=np.select([(prior<.55*a.shift(1))&(d.close>m)&(d.close>d.high.shift(1)),
                 (prior<.55*a.shift(1))&(d.close<m)&(d.close<d.low.shift(1))],[1,-1],0)
 return S(d,side,1.5*a,2)

def donchian_fast(d):
 a=ATR(d);hi=d.high.shift(1).rolling(20).max();lo=d.low.shift(1).rolling(20).min()
 side=np.select([cross_up(d.close,hi),cross_down(d.close,lo)],[1,-1],0)
 return S(d,side,2*a,2.0)

def donchian_slow(d):
 a=ATR(d);hi=d.high.shift(1).rolling(55).max();lo=d.low.shift(1).rolling(55).min()
 side=np.select([cross_up(d.close,hi),cross_down(d.close,lo)],[1,-1],0)
 return S(d,side,2.5*a,2.5)

def roc_ema(d):
 c=d.close;a=ATR(d);roc=c.pct_change(10);ef=E(c,20);es=E(c,80)
 side=np.select([cross_up(roc,pd.Series(0.0,index=d.index))&(ef>es)&(roc>.001),
                 cross_down(roc,pd.Series(0.0,index=d.index))&(ef<es)&(roc<-.001)],[1,-1],0)
 return S(d,side,1.7*a,2)

def zscore_reversion(d):
 mid=d.close.rolling(50).mean();sd=d.close.rolling(50).std(ddof=0);z=(d.close-mid)/sd.replace(0,np.nan)
 adx,_,_=b.adx(d);a=ATR(d)
 side=np.select([cross_up(z,pd.Series(-2.,index=d.index))&(adx<22),
                 cross_down(z,pd.Series(2.,index=d.index))&(adx<22)],[1,-1],0)
 return S(d,side,1.5*a,1.5)

def engulf_trend(d):
 p=d.shift(1);e=E(d.close,100)
 bull=(d.close>d.open)&(p.close<p.open)&(d.close>p.open)&(d.open<p.close)&(d.close>e)
 bear=(d.close<d.open)&(p.close>p.open)&(d.close<p.open)&(d.open>p.close)&(d.close<e)
 return S(d,np.select([bull,bear],[1,-1],0),1.4*ATR(d),1.8)

def wick_level_reject(d):
 a=ATR(d);hi=d.high.shift(1).rolling(24).max();lo=d.low.shift(1).rolling(24).min();rg=(d.high-d.low).replace(0,np.nan)
 side=np.select([(d.low<lo)&(d.close>lo)&((d.close-d.low)/rg>.7),
                 (d.high>hi)&(d.close<hi)&((d.high-d.close)/rg>.7)],[1,-1],0)
 return S(d,side,1.6*a,1.9)

def channel_reclaim(d):
 a=ATR(d);upper=d.high.shift(1).rolling(25).max();lower=d.low.shift(1).rolling(25).min()
 buy=(d.low<lower)&(d.close>lower)&(d.close>d.open);sell=(d.high>upper)&(d.close<upper)&(d.close<d.open)
 return S(d,np.select([buy,sell],[1,-1],0),1.5*a,2)

def mid_range_reclaim(d):
 a=ATR(d);hi=d.high.shift(1).rolling(35).max();lo=d.low.shift(1).rolling(35).min();mid=(hi+lo)/2
 bull=cross_up(d.close,mid)&(d.close> E(d.close,100))
 bear=cross_down(d.close,mid)&(d.close< E(d.close,100))
 return S(d,np.select([bull,bear],[1,-1],0),1.7*a,1.7)

def prev_day_breakout(d):
 # Session day based on data's naive broker timestamps; diagnostic only (timezone unverified).
 day=d.resample('1D',closed='left',label='right').agg({'high':'max','low':'min'})
 ph=day.high.reindex(d.index,method='ffill');pl=day.low.reindex(d.index,method='ffill')
 side=np.select([cross_up(d.close,ph),cross_down(d.close,pl)],[1,-1],0)
 return S(d,side,1.5*ATR(d),2)

def nr7(d):
 r=d.high-d.low; n=(r.shift(1)<=r.shift(2))&(r.shift(1)<=r.shift(3))&(r.shift(1)<=r.shift(4))&(r.shift(1)<=r.shift(5))&(r.shift(1)<=r.shift(6))&(r.shift(1)<=r.shift(7))
 side=np.select([n&(d.close>d.high.shift(1)),n&(d.close<d.low.shift(1))],[1,-1],0)
 return S(d,side,1.4*ATR(d),1.8)

def ha_momentum(d):
 hc=(d.open+d.high+d.low+d.close)/4;prev=hc.shift(1);r=RSI(d.close);a=ATR(d)
 side=np.select([(hc>prev)&(hc.shift(1)>hc.shift(2))&(d.close>E(d.close,50))&(r>55),
                 (hc<prev)&(hc.shift(1)<hc.shift(2))&(d.close<E(d.close,50))&(r<45)],[1,-1],0)
 return S(d,side,1.4*a,2)

def cci_reversion(d):
 tp=(d.high+d.low+d.close)/3;m=tp.rolling(20).mean();mad=(tp-m).abs().rolling(20).mean();cci=(tp-m)/(.015*mad.replace(0,np.nan))
 side=np.select([cross_up(cci,pd.Series(-100.,index=d.index)),cross_down(cci,pd.Series(100.,index=d.index))],[1,-1],0)
 return S(d,side,1.8*ATR(d),1.5)

def price_channel_momentum(d):
 a=ATR(d);slope=E(d.close,30)-E(d.close,30).shift(5)
 side=np.select([(d.close>d.high.shift(1).rolling(12).max())&(slope>0),
                 (d.close<d.low.shift(1).rolling(12).min())&(slope<0)],[1,-1],0)
 return S(d,side,1.5*a,2)

def ema_atr_confluence(d):
 a=ATR(d);r=RSI(d.close);adx,p,m=b.adx(d);e20=E(d.close,20);e100=E(d.close,100)
 side=np.select([(e20>e100)&(r>55)&(p>m)&(adx>20)&(d.low<=e20)&(d.close>e20),
                 (e20<e100)&(r<45)&(m>p)&(adx>20)&(d.high>=e20)&(d.close<e20)],[1,-1],0)
 return S(d,side,1.5*a,2)

def stochastic_rebound(d):
 a=ATR(d);lo=d.low.rolling(14).min();hi=d.high.rolling(14).max();k=100*(d.close-lo)/(hi-lo).replace(0,np.nan)
 side=np.select([cross_up(k,pd.Series(20.,index=d.index))&(d.close>E(d.close,200)),
                 cross_down(k,pd.Series(80.,index=d.index))&(d.close<E(d.close,200))],[1,-1],0)
 return S(d,side,1.6*a,1.8)

def pivot_center_break(d):
 a=ATR(d);hi=d.high.shift(1).rolling(20).max();lo=d.low.shift(1).rolling(20).min();cen=(hi+lo)/2
 side=np.select([cross_up(d.close,cen)&(d.close>E(d.close,50)),cross_down(d.close,cen)&(d.close<E(d.close,50))],[1,-1],0)
 return S(d,side,1.4*a,1.6)

# A hypothesis may be informed by multiple projects, but isn't an exact byte-for-byte port.
# Entries: (tf, callable, risk cap in XAUUSD price units, bar horizon, source, precise caveat).
CONFIG={
 'EMA20_RSI_CROSS_M15':('15min',ema_rsi_cross,10,36,'Aniket-Jaiswal2002/xauusd-trading-bot','EMA RSI crossover independent rules'),
 'HA_RSI_CROSS_M5':('5min',heikin_ashi_rsi,10,50,'manishsolanki1703/XAUUSD-Strategy','HA RSI adaptation'),
 'TRIPLE_CONFIRM_M15':('15min',triple_confirmation,10,48,'Turnipnator/Oanda_Gold','Triple confirmation variant'),
 'EMA9_RSI_CROSS_M5':('5min',ema9_rsi,10,48,'TLBSimon/Funded_EMA_RSI_ATR_EA','EMA RSI cross adaptation'),
 'MACD_EMA_M15':('15min',macd_ema_trend,10,50,'devadarshan-20/QuantEdge-XAUUSD','Explainable EMA MACD score subset'),
 'ADX_DI_EMA_M5':('5min',adx_di_ema,10,36,'AhsanAli013/MT5-XAUUSD-Scalping-EA','EMA ADX direction variant'),
 'BOLL_RSI_FADE_M5':('5min',boll_rsi_fade,10,36,'INDEPENDENT_BOLL_RSI_HYPOTHESIS','Generic Bollinger/RSI hypothesis; not Hillary project code'),
 'ATR_COMPRESSION_M5':('5min',atr_compression,10,40,'P1Piyush/XAUUSD-Trading-Bots','Mechanical volatility expansion proxy'),
 'DONCHIAN20_H1':('1h',donchian_fast,25,75,'NziCode/mt5-trading-bots','Donchian 20 independent hypothesis'),
 'DONCHIAN55_H4':('4h',donchian_slow,60,90,'INDEPENDENT_TURTLE_HYPOTHESIS','Generic Turtle channel hypothesis; not repo specific'),
 'ROC_EMA_H1':('1h',roc_ema,30,90,'Amirgh23/gold-trading-bot','Momentum adaptation'),
 'ZSCORE_H1':('1h',zscore_reversion,30,50,'blaster3618/Auri-GOLD','Mean reversion hypothesis'),
 'ENGULF_TREND_M15':('15min',engulf_trend,10,40,'erikoleci/gold-xauusd-ea','Price action engulf plus trend'),
 'WICK_LEVEL_M15':('15min',wick_level_reject,10,40,'NadirAliOfficial/trading-scanner','Liquidity sweep wick confirmation subset'),
 'CHANNEL_RECLAIM_M5':('5min',channel_reclaim,10,40,'lordgaruda/XAU-60','Mechanical liquidity reclaim'),
 'MID_RANGE_RECLAIM_H1':('1h',mid_range_reclaim,25,70,'RicardoBarato/xauusd-mt5-expert-advisor','Regime channel reclaim'),
 'PREV_DAY_BREAK_M5':('5min',prev_day_breakout,10,40,'Turnipnator/Oanda_Gold','Broker-time session diagnostic only'),
 'NR7_BREAK_M5':('5min',nr7,10,35,'NziCode/mt5-trading-bots','Narrow range volatility expansion'),
 'HA_MOMENTUM_H1':('1h',ha_momentum,25,70,'manishsolanki1703/XAUUSD-Strategy','HA momentum without AI'),
 'CCI_REVERSION_M15':('15min',cci_reversion,10,40,'Josewathome/XAUUSD-tradding-bot','Independent CCI mean reversion'),
 'PRICE_CHANNEL_M15':('15min',price_channel_momentum,10,45,'P1Piyush/XAUUSD-Trading-Bots','Channel momentum subset'),
 'EMA_ATR_CONFIRM_M5':('5min',ema_atr_confluence,10,40,'AhsanAli013/MT5-XAUUSD-Scalping-EA','EMA RSI ADX ATR entry'),
 'STOCH_REBOUND_M15':('15min',stochastic_rebound,10,40,'INDEPENDENT_STOCH_EMA_HYPOTHESIS','Generic stochastic EMA; referenced repository has no disclosed rules'),
 'PIVOT_CENTRE_M5':('5min',pivot_center_break,10,40,'mahmoud20138/Gold-MultiAgent-Analyzer','Mechanical pivot signal, not original agent'),
}
