"""Single-position, three-target, no same-bar optimism, fixed USD round-trip cost.
Conservative OHLC rule: stop has priority if both it and targets are inside a bar.
"""
from __future__ import annotations
from bisect import bisect_left
from collections import Counter
from datetime import datetime
import statistics
from .core import Bar,Setup,Config


def _exit_r(setup:Setup,price:float)->float:
    return setup.side*(price-setup.entry)/setup.risk


def _touch_stop(b:Bar,side:int,stop:float)->bool:
    return b.l<=stop if side==1 else b.h>=stop


def _touch_tp(b:Bar,side:int,tp:float)->bool:
    return b.h>=tp if side==1 else b.l<=tp


def _simulate_one(setup:Setup,bars:list[Bar],idx:int,cfg:Config):
    sl=setup.sl;hits=[False,False,False];weights=(1/3,1/3,1/3)
    remaining=1.0;gross=0.0;exit_reason='timeout';exit_at=bars[idx].end
    end=min(idx+cfg.max_hold_bars,len(bars))
    for j in range(idx,end):
        b=bars[j]
        # If broker opens beyond stop, fill at the worse open (gaps).
        if j>idx and _exit_r(setup,b.o)<=_exit_r(setup,sl):
            stop_exec=b.o if _exit_r(setup,b.o)<_exit_r(setup,sl) else sl
            gross+=remaining*_exit_r(setup,stop_exec)
            exit_reason='gap_stop' if stop_exec!=sl else 'stop';exit_at=b.t
            break
        # Conservative adverse intra-bar ordering.
        if _touch_stop(b,setup.side,sl):
            gross+=remaining*_exit_r(setup,sl)
            exit_reason='stop';exit_at=b.end
            break
        for k,tp in enumerate(setup.tps):
            if not hits[k] and _touch_tp(b,setup.side,tp):
                hits[k]=True
                gross+=weights[k]*_exit_r(setup,tp)
                remaining-=weights[k]
                if k==0:sl=setup.entry # effective from the next iteration only
        if remaining<1e-8:
            exit_reason='tp3';exit_at=b.end;break
        # No time travel: stop change acts only next bar, after the current bar's decision.
    else:
        if end>idx:
            gross+=remaining*_exit_r(setup,bars[end-1].c)
            exit_at=bars[end-1].end
        exit_reason='timeout' if end< len(bars) else 'end_of_data'
    cost_r=cfg.spread_roundtrip_usd/setup.risk
    return {'strategy':setup.strategy,'grade':setup.grade,'signal_at':setup.signal_at.isoformat(sep=' '),
            'entry_at':setup.entry_at.isoformat(sep=' '),'exit_at':exit_at.isoformat(sep=' '),
            'side':'BUY' if setup.side==1 else 'SELL','entry':round(setup.entry,3),'sl':round(setup.sl,3),
            'tp1':round(setup.tps[0],3),'tp2':round(setup.tps[1],3),'tp3':round(setup.tps[2],3),
            'risk_usd':round(setup.risk,4),'gross_R':round(gross,5),'cost_R':round(cost_r,5),
            'net_R':round(gross-cost_r,5),'exit_reason':exit_reason,'strength_heuristic':setup.strength,
            'reason':setup.reason},exit_at


def replay(setups:list[Setup],bars:list[Bar],cfg:Config=Config())->list[dict]:
    # By default one slot shared across all 3 strategies; never simultaneously double-up exposure.
    starts=[b.t for b in bars];last_exit=None;trades=[]
    for s in sorted(setups,key=lambda x:(x.entry_at,-x.strength,x.strategy)):
        if last_exit is not None and s.entry_at < last_exit:continue
        idx=bisect_left(starts,s.entry_at)
        if idx>=len(bars) or bars[idx].t!=s.entry_at:continue
        t,last_exit=_simulate_one(s,bars,idx,cfg)
        trades.append(t)
    return trades


def evaluate(trades:list[dict])->dict:
    values=[float(t['net_R']) for t in trades]
    n=len(values);wins=sum(v>0 for v in values);gp=sum(v for v in values if v>0);gl=-sum(v for v in values if v<0)
    eq=peak=dd=0.0;streak=losestreak=0
    for v in values:
        eq+=v;peak=max(peak,eq);dd=max(dd,peak-eq)
        streak=streak+1 if v<0 else 0;losestreak=max(losestreak,streak)
    return {'trades':n,'wins':wins,'win_rate':round(wins/n,4) if n else None,
            'total_R':round(sum(values),4),'expectancy_R':round(sum(values)/n,4) if n else None,
            'profit_factor':round(gp/gl,4) if gl>0 else None,
            'max_drawdown_R':round(dd,4),'max_loss_streak':losestreak,
            'median_R':round(statistics.median(values),4) if n else None}
