"""Independent, causal market-structure context on fully CLOSED OHLC bars.
No LuxAlgo source copied. This is NOT pixel/alert parity with LuxAlgo.
All event timestamps are at their detection/confirmation candle, not backdated pivots.
"""
from dataclasses import dataclass, asdict
import math
import pandas as pd

@dataclass(frozen=True)
class StructureSnapshot:
    bar_time: str
    structure: str
    bias: int
    last_swing_high: float | None
    last_swing_low: float | None
    sweep: str | None
    fvg: str | None
    fvg_low: float | None
    fvg_high: float | None
    equal_high: bool
    equal_low: bool
    order_block: dict | None
    premium_discount: str | None


def _check(df: pd.DataFrame):
    if not {'open','high','low','close'} <= set(df.columns):
        raise ValueError('OHLC required')
    if df.empty or not df.index.is_unique or not df.index.is_monotonic_increasing:
        raise ValueError('Nonempty chronological unique bars required')
    cols=df[['open','high','low','close']]
    if not cols.notna().all().all() or not cols.map(math.isfinite).all().all():
        raise ValueError('Invalid bar values')
    if ((df.high < df.low) | (df.low > df[['open','close']].min(axis=1)) | (df.high < df[['open','close']].max(axis=1))).any():
        raise ValueError('Inconsistent OHLC')


def scan(df: pd.DataFrame, *, pivot_span:int=3, equal_tolerance:float=0.10) -> list[StructureSnapshot]:
    """Once a pivot has *pivot_span bars AFTER it*, it's confirmed on this bar.
    BOS/CHoCH uses the PREVIOUS confirmed pivot; FVG known only on third closed bar.
    Bullish/bearish OB is most recent opposite candle before a confirmed break.
    """
    _check(df)
    if pivot_span<1 or not 0<=equal_tolerance<=1:raise ValueError('Bad SMC parameters')
    arr=df[['open','high','low','close']].to_numpy(dtype=float)
    result=[]; prev_h=None; prev_l=None; bias=0; h_crossed=l_crossed=False
    last_ob=None; tr_hist=[]; prev_c=None
    for i,(o,h,l,c) in enumerate(arr):
        tr=max(h-l, abs(h-prev_c),abs(l-prev_c)) if prev_c is not None else h-l
        tr_hist.append(tr); atr=sum(tr_hist[-14:])/min(14,len(tr_hist));prev_c=c
        old_h,old_l=prev_h,prev_l
        event='NONE';sweep=None;eqh=eql=False;fvg=None;fl=fh=None
        # First evaluate the bar against only previously confirmed pivots.
        if old_h is not None and h>old_h and c<old_h:sweep='BUY_SIDE'
        if old_l is not None and l<old_l and c>old_l:sweep='SELL_SIDE' if sweep is None else 'BOTH'
        if old_h is not None and not h_crossed and c>old_h:
            event='BULL_BOS' if bias>=0 else 'BULL_CHOCH';bias=1;h_crossed=True
            j=next((j for j in range(i-1,max(-1,i-8),-1) if arr[j,3]<arr[j,0]),None)
            if j is not None:last_ob={'side':'BUY','low':float(arr[j,2]),'high':float(arr[j,1]),'known_at':str(df.index[i])}
        elif old_l is not None and not l_crossed and c<old_l:
            event='BEAR_BOS' if bias<=0 else 'BEAR_CHOCH';bias=-1;l_crossed=True
            j=next((j for j in range(i-1,max(-1,i-8),-1) if arr[j,3]>arr[j,0]),None)
            if j is not None:last_ob={'side':'SELL','low':float(arr[j,2]),'high':float(arr[j,1]),'known_at':str(df.index[i])}
        if i>=2:
            if l>arr[i-2,1]:fvg='BULL';fl=float(arr[i-2,1]);fh=float(l)
            elif h<arr[i-2,2]:fvg='BEAR';fl=float(h);fh=float(arr[i-2,2])
        p=i-pivot_span
        if p>=pivot_span:
            w=arr[p-pivot_span:i+1]
            if all(arr[p,1]>v for k,v in enumerate(w[:,1]) if k!=pivot_span):
                eqh=old_h is not None and abs(arr[p,1]-old_h)<=equal_tolerance*atr
                prev_h=float(arr[p,1]);h_crossed=False
            if all(arr[p,2]<v for k,v in enumerate(w[:,2]) if k!=pivot_span):
                eql=old_l is not None and abs(arr[p,2]-old_l)<=equal_tolerance*atr
                prev_l=float(arr[p,2]);l_crossed=False
        zone=None
        if prev_l is not None and prev_h is not None and prev_h>prev_l:
            pct=(c-prev_l)/(prev_h-prev_l)
            zone='DISCOUNT' if pct<0.45 else 'PREMIUM' if pct>0.55 else 'EQUILIBRIUM'
        result.append(StructureSnapshot(str(df.index[i]),event,bias,prev_h,prev_l,sweep,fvg,fl,fh,eqh,eql,last_ob,zone))
    return result


def latest(df:pd.DataFrame,**kwargs) -> dict:
    return asdict(scan(df,**kwargs)[-1])
