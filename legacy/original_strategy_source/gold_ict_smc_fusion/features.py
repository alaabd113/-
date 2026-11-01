"""Incremental event features. Only completed bars are accepted by callers."""
from __future__ import annotations
from .core import Bar,Swing,Gap


def true_range(b: Bar, prev: Bar|None) -> float:
    return (b.h-b.l) if prev is None else max(b.h-b.l,abs(b.h-prev.c),abs(b.l-prev.c))


def atr_at(bs: list[Bar], i: int, n:int=14) -> float|None:
    if i < n:return None
    return sum(true_range(bs[k],bs[k-1] if k else None) for k in range(i-n+1,i+1))/n


def swing_at(bs:list[Bar], confirm_idx:int, n:int=2)->list[Swing]:
    """A pivot at p=confirm_idx-n is discoverable only at bs[confirm_idx].end."""
    p=confirm_idx-n
    if p-n<0:return []
    w=bs[p-n:confirm_idx+1]
    if len(w)!=2*n+1:return []
    r=[]
    if all(bs[p].h>x.h for j,x in enumerate(w) if j!=n):
        r.append(Swing('high',bs[p].h,bs[p].t,bs[confirm_idx].end,p,confirm_idx))
    if all(bs[p].l<x.l for j,x in enumerate(w) if j!=n):
        r.append(Swing('low',bs[p].l,bs[p].t,bs[confirm_idx].end,p,confirm_idx))
    return r


def fvg_at(bs:list[Bar],i:int,min_width:float=0.0)->Gap|None:
    """Three-bar displacement: bull low[i]>high[i-2]; bear high[i]<low[i-2]."""
    if i<2:return None
    a,b=bs[i-2],bs[i]
    if b.l-a.h>=min_width and b.l>a.h:
        return Gap(1,a.h,b.l,b.t,b.end,i)
    if a.l-b.h>=min_width and b.h<a.l:
        return Gap(-1,b.h,a.l,b.t,b.end,i)
    return None


def h4_bias_at(h4:list[Bar], t, lookback:int=8)->int:
    """Higher-timeframe bias solely from H4 bars CLOSED by t, 0 if insufficient."""
    closed=[b for b in h4 if b.end<=t]
    if len(closed)<lookback+1:return 0
    last=closed[-1]
    ref=sum(x.c for x in closed[-(lookback+1):-1])/lookback
    return (1 if last.c>ref else -1 if last.c<ref else 0)


def active_gap(g:Gap, bars:list[Bar],i:int,valid_bars:int=10)->bool:
    if g.formed_index>=i or i-g.formed_index>valid_bars:return False
    for q in bars[g.formed_index+1:i]:
        # Invalidation by close beyond far edge; retest allowed.
        if (g.side==1 and q.c<g.low) or (g.side==-1 and q.c>g.high):return False
    return True
