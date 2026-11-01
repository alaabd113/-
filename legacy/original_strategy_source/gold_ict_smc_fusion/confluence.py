"""Optional M15 liquidity and M1 confirmation evidence. Metadata only in baseline:
these gates are NOT applied retrospectively to strategy performance to avoid cherry-picking.
Only completed candles can contribute at the signal's timestamp.
"""
from __future__ import annotations
from bisect import bisect_right
from datetime import datetime
from .core import Bar


def context_at(ts:datetime,side:int,m15:list[Bar],m1:list[Bar])->dict:
    f15=[x for x in m15 if x.end<=ts]
    f1=[x for x in m1 if x.end<=ts]
    has_m15=len(f15)>=20
    m15_sweep=False
    if has_m15:
        # Recent M15 wick through pre-existing M15 range with close back inside.
        for k in range(max(16,len(f15)-6),len(f15)):
            old=f15[k-16:k]
            lo=min(x.l for x in old);hi=max(x.h for x in old)
            x=f15[k]
            if (side==1 and x.l<lo and x.c>lo) or (side==-1 and x.h>hi and x.c<hi):
                m15_sweep=True;break
    m1_confirmed=None
    if len(f1)>=10 and (ts-f1[-1].end).total_seconds()<=5*60:
        curr=f1[-1];previous=f1[-10:-1]
        avg_body=sum(abs(x.c-x.o) for x in previous)/len(previous)
        m1_confirmed=side*(curr.c-curr.o)>max(.01,avg_body*1.1)
    return {'asof':ts.isoformat(sep=' '),'m15_history_available':has_m15,
            'm15_recent_liquidity_sweep':m15_sweep,
            'm1_confirmation_available':m1_confirmed is not None,
            'm1_displacement_confirmed':m1_confirmed,
            'note':'Descriptive only, not a calibrated win probability or backtested filter'}
