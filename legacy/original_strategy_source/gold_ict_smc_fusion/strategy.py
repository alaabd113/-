"""Causal M5 gold signal generator inspired by documented ICT/SMC concepts.
No unconfirmed pivots, no future bars, no live trade submission.
"""
from __future__ import annotations
from dataclasses import dataclass
from bisect import bisect_right
from datetime import datetime
from .core import Bar,Setup,Config,Gap
from .features import swing_at, atr_at, fvg_at, h4_bias_at, active_gap

@dataclass(frozen=True)
class Signal:
    strategy:str
    side:int
    signal_at:datetime
    sl_reference:float
    atr:float
    grade:str
    strength:float
    reason:str
    ref_at:datetime


def _favorable(x,side):return side*x

def _coherent(bs,i,k,config):
    # Require no large missing-data break inside a setup sequence.
    if k<0:return False
    return all((bs[j].t-bs[j-1].t).total_seconds()<=config.no_gap_max_minutes*60
               for j in range(max(k+1,1),i+1))


def generate_signals(m5:list[Bar],h4:list[Bar],cfg:Config=Config())->list[Signal]:
    cfg.validate()
    if any(b.timeframe!='5min' for b in m5) or any(b.timeframe!='4h' for b in h4):raise ValueError('unexpected frame')
    if any(m5[j].t<=m5[j-1].t for j in range(1,len(m5))):raise ValueError('bar order')
    # O(1) H4 bias after O(N) preprocessing, no completed-bar lookahead.
    h4_ends=[x.end for x in h4]
    h4_prefix=[0.0]
    for x in h4:h4_prefix.append(h4_prefix[-1]+x.c)
    def bias_at(t):
        k=bisect_right(h4_ends,t)
        if k<9:return 0
        ref=(h4_prefix[k-1]-h4_prefix[k-9])/8
        return 1 if h4[k-1].c>ref else -1 if h4[k-1].c<ref else 0
    last_hi=last_lo=None
    recent_fvg=[]
    sweeps=[]
    ob_events=[]
    po3_events=[]
    emitted=[]
    seen=set()
    for i,b in enumerate(m5):
        if i<cfg.atr_n+2:
            for sw in swing_at(m5,i,cfg.swing_n):
                if sw.side=='high':last_hi=sw
                else:last_lo=sw
            continue
        atr=atr_at(m5,i,cfg.atr_n)
        if not atr or atr<=0:continue
        bias=bias_at(b.end)
        gap=fvg_at(m5,i,max(.01,atr*cfg.fvg_min_atr))
        if gap:recent_fvg.append(gap)
        recent_fvg=[g for g in recent_fvg if i-g.formed_index<=cfg.retest_window_bars+5]
        keep=[]
        for st in sweeps:
            side=st['side']
            if i-st['i']>cfg.sweep_window_bars+cfg.retest_window_bars:continue
            if not _coherent(m5,i,st['i'],cfg):continue
            if st['status']=='swept' and i>st['i']:
                if (side==1 and b.c>st['mss']) or (side==-1 and b.c<st['mss']):
                    st['status']='mss';st['mss_idx']=i
            if st['status']=='mss':
                gg=[g for g in recent_fvg if g.side==side and g.formed_index>=st['i']
                    and g.formed_index<=i and i-g.formed_index<=4]
                if gg:
                    st['gap']=gg[-1];st['status']='ready'
                elif i-st.get('mss_idx',i)>4:continue
            if st['status']=='ready':
                g=st['gap']
                if not active_gap(g,m5,i,cfg.retest_window_bars):continue
                # Strictly AFTER gap is known, not on the same candle.
                hit=(b.l<=g.high and b.h>=g.low)
                confirm=(b.c>=(g.low+g.high)/2) if side==1 else (b.c<=(g.low+g.high)/2)
                if i>g.formed_index and hit and confirm:
                    if bias==side:
                        key=('GLS_SWEEP_MSS_FVG',side,b.end)
                        if key not in seen:
                            emitted.append(Signal(key[0],side,b.end,st['extreme'],atr,'A',0.82,
                              'confirmed sweep -> MSS close -> three-bar FVG -> later retest; H4 aligned',m5[st['i']].t))
                            seen.add(key)
                    continue
            keep.append(st)
        sweeps=keep
        # Order Block: opposite M5 candle before displacement breaking confirmed structure.
        keep=[]
        for ev in ob_events:
            if i-ev['i']>cfg.retest_window_bars or not _coherent(m5,i,ev['i'],cfg):continue
            if i>ev['i'] and b.l<=ev['top'] and b.h>=ev['bottom']:
                if bias==ev['side'] and ev['side']*(b.c-ev['mid'])>=0:
                    key=('H4_OB_M5_MSS',ev['side'],b.end)
                    if key not in seen:
                        emitted.append(Signal(key[0],ev['side'],b.end,ev['sl'],atr,'B',0.68,
                            'confirmed M5 structure break with displacement, opposite-candle OB retest and H4 alignment',m5[ev['i']].t))
                        seen.add(key)
                continue
            # invalidation by close through far edge
            if (ev['side']==1 and b.c<ev['bottom']) or (ev['side']==-1 and b.c>ev['top']):continue
            keep.append(ev)
        ob_events=keep
        keep=[]
        for ev in po3_events:
            if i-ev['i']>6 or not _coherent(m5,i,ev['i'],cfg):continue
            if i>ev['i'] and ev['side']*(b.c-ev['mid'])>0 and bias==ev['side']:
                key=('PO3_SWEEP_DISTRIBUTION',ev['side'],b.end)
                if key not in seen:
                    emitted.append(Signal(key[0],ev['side'],b.end,ev['extreme'],atr,'B',0.62,
                        'prior 12-bar consolidation -> failed liquidity break -> reclaim and distribution, H4 aligned',m5[ev['i']].t))
                    seen.add(key)
                continue
            keep.append(ev)
        po3_events=keep
        # Confirmed swing values from *previous* bars can be swept on this candle.
        if last_lo and last_hi and _coherent(m5,i,i-1,cfg):
            if b.l<last_lo.price-cfg.sweep_min_atr*atr and b.c>last_lo.price:
                sweeps.append(dict(i=i,side=1,extreme=b.l,mss=last_hi.price,status='swept'))
            if b.h>last_hi.price+cfg.sweep_min_atr*atr and b.c<last_hi.price:
                sweeps.append(dict(i=i,side=-1,extreme=b.h,mss=last_lo.price,status='swept'))
            # displacement + break through confirmed opposite swing, then later OB retest
            side=1 if b.c>b.o else -1
            broke=(b.c>last_hi.price) if side==1 else (b.c<last_lo.price)
            if broke and abs(b.c-b.o)>=atr*.75:
                opposite=[x for x in m5[max(0,i-6):i] if (x.c<x.o if side==1 else x.c>x.o)]
                if opposite:
                    ob=opposite[-1]
                    ob_events.append(dict(i=i,side=side,bottom=ob.l,top=ob.h,mid=(ob.h+ob.l)/2,
                                          sl=ob.l if side==1 else ob.h))
        if i>=13 and _coherent(m5,i,i-12,cfg):
            prior=m5[i-12:i]
            hi=max(x.h for x in prior);lo=min(x.l for x in prior)
            if hi-lo<=3.5*atr:
                if b.l<lo-cfg.sweep_min_atr*atr and b.c>lo and b.c<hi:
                    po3_events.append(dict(i=i,side=1,mid=(hi+lo)/2,extreme=b.l))
                if b.h>hi+cfg.sweep_min_atr*atr and b.c<hi and b.c>lo:
                    po3_events.append(dict(i=i,side=-1,mid=(hi+lo)/2,extreme=b.h))
        # The pivot at i-n becomes available *now*, never at its original timestamp.
        for sw in swing_at(m5,i,cfg.swing_n):
            if sw.side=='high':last_hi=sw
            else:last_lo=sw
    return emitted


def materialize(sig:Signal,next_open_bar:Bar,cfg:Config)->Setup|None:
    """Entry at the NEXT bar's real open, never at retrospectively selected retest price."""
    if next_open_bar.t < sig.signal_at:return None
    entry=next_open_bar.o;sl=sig.sl_reference - cfg.sl_buffer_atr*sig.atr if sig.side==1 else sig.sl_reference+cfg.sl_buffer_atr*sig.atr
    risk=sig.side*(entry-sl)
    if not (cfg.min_sl_usd<=risk<=cfg.max_sl_usd):return None
    tps=tuple(entry+sig.side*risk*r for r in (1.0,2.0,3.0))
    return Setup(sig.strategy,sig.side,sig.signal_at,next_open_bar.t,entry,sl,tps,sig.grade,sig.strength,sig.reason,sig.ref_at)


def signals_to_setups(signals:list[Signal],m5:list[Bar],cfg:Config=Config())->list[Setup]:
    """Next bar open is only accessible in the replay, never inside the signal generator."""
    starts=[b.t for b in m5]
    output=[]
    for sig in signals:
        # Find first bar opening >= close of the signal bar, conservatively reject gaps.
        k=bisect_right(starts,sig.signal_at)
        if k and starts[k-1]==sig.signal_at:k-=1
        nxt=m5[k] if k<len(m5) else None
        if nxt is None or (nxt.t-sig.signal_at).total_seconds()>cfg.no_gap_max_minutes*60:continue
        x=materialize(sig,nxt,cfg)
        if x:output.append(x)
    return sorted(output,key=lambda x:(x.entry_at, -x.strength,x.strategy))


def generate_setups(m5:list[Bar],h4:list[Bar],cfg:Config=Config())->list[Setup]:
    return signals_to_setups(generate_signals(m5,h4,cfg),m5,cfg)
