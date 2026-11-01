"""Unified runnable registry: 24 V6 variants, 14 V5 variants, 22 prior variants,
14 wide-stop configurations, original PO3 M5. All run SHADOW/BACKTEST until explicit broker authorization.
References are research inspirations, not claims of identical EA implementations.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Callable
from datetime import timedelta
import pandas as pd
import numpy as np
from research import new_variants as latest, replay_base as b
from strategies import previous_extended as prev

@dataclass(frozen=True)
class StrategySpec:
    sid: str
    timeframe: str
    generator: Callable
    stop_cap: float
    max_hold_bars: int
    rr: float | None
    source: str
    source_type: str = 'RULE_ADAPTATION'
    note: str = ''

SPECS = {}
def add(spec):
    if spec.sid in SPECS: raise ValueError('Duplicate strategy ID: '+spec.sid)
    SPECS[spec.sid] = spec

for sid, (tf, fn, cap, hold, repo, note) in latest.CONFIG.items():
    add(StrategySpec(sid, tf, fn, float(cap), int(hold), 1.8, repo, note=note))
for sid, c in b.CONFIG.items():
    add(StrategySpec(('V5_'+sid) if sid in SPECS else sid, c['tf'], b.FUNCS[sid], float(c['cap']), int(c['horizon']),
                     float(c['rr']) if isinstance(c['rr'], (int,float)) else None,
                     c['source'], note='Old V5 rule adaptation; original TP used if rr=None'))
for sid, (tf, fn, rr, hold, repo, note) in prev.SETS.items():
    add(StrategySpec(('PREV_'+sid) if sid in SPECS else sid, tf, fn, 10., int(hold), float(rr), repo, note=note))

# Research profiles with wider protective stops - separate from $10 scalp risk policies.
_wide = {
 'WIDE_D1_DONCHIAN20_LONG':('1day',prev.long_d1_donchian,3,80,250),
 'WIDE_H4_DONCHIAN10_COMP':('4h',prev.donchian_compression,2,45,50),
 'WIDE_H4_STOCH_EMA':('4h',prev.stoch_ema,2,35,50),
 'WIDE_H4_MACD_ADX_LONG':('4h',prev.macd_adx_long,2,35,50),
 'WIDE_D1_EMA20_LONG':('1day',prev.long_d1_trend,2,50,250),
 'WIDE_H4_EMA50_PB':('4h',prev.ema50_pullback,1.5,35,50),
 'WIDE_H1_MACD_ADX_LONG':('1h',prev.macd_adx_long,2,35,30),
 'WIDE_M15_RSI2_REVERSION':('15min',prev.rsi2_reversion,1.5,25,10),
 'WIDE_M30_EMA50_PB':('30min',prev.ema50_pullback,1.5,35,10),
 'WIDE_M15_EMA50_PB':('15min',prev.ema50_pullback,1.5,35,10),
 'WIDE_D1_EMA50_PB':('1day',prev.ema50_pullback,1.5,35,250),
 'WIDE_H1_STOCH_EMA':('1h',prev.stoch_ema,2,35,30),
 'WIDE_H1_EMA50_PB':('1h',prev.ema50_pullback,1.5,35,30),
 'WIDE_M5_MACD_HIST_TREND':('5min',prev.macd_hist_cross,1.5,35,10),
}
for sid,(tf,fn,rr,hold,cap) in _wide.items():
    add(StrategySpec(sid,tf,fn,float(cap),int(hold),float(rr),'PREVIOUS_WIDE_STOP_RESEARCH',
                     note='Wider stop research profile; requires separate swing risk policy'))

# Exact original PO3 signal generator extracted UNCHANGED from prior complete source.
def frozen_po3(d):
    from strategies.legacy_gold.gold_ict_smc_fusion.loader import load_bars
    from strategies.legacy_gold.gold_ict_smc_fusion.strategy import generate_signals
    from strategies.legacy_gold.gold_ict_smc_fusion.core import Config
    from research import replay_base as b
    if len(d)<40: return b.empty(d)
    db=str(b.SRC)
    m5=load_bars(db,'5min');h4=load_bars(db,'4h')
    # Ensure historical snapshot not extended past the requested sample end.
    cutoff=d.index.max()+pd.Timedelta(minutes=5)
    m5=[x for x in m5 if x.end <= cutoff.to_pydatetime()]
    h4=[x for x in h4 if x.end <= cutoff.to_pydatetime()]
    signals=generate_signals(m5,h4,Config())
    out=b.empty(d)
    for s in signals:
        if s.strategy!='PO3_SWEEP_DISTRIBUTION':continue
        ts=pd.Timestamp(s.signal_at)-pd.Timedelta(minutes=5)
        if ts not in out.index:continue
        dr=int(s.side)
        stop=s.sl_reference-dr*Config().sl_buffer_atr*s.atr
        risk=dr*(float(d.loc[ts,'close'])-stop)
        if risk<=0:continue
        out.loc[ts,['side','stop','target']]=[dr,stop,float(d.loc[ts,'close'])+dr*risk*2.0]
    return out
add(StrategySpec('PO3_FROZEN_M5','5min',frozen_po3,10.,120,2.,'ORIGINAL_GOLDSTATION_PO3_ENGINE',
                 source_type='ORIGINAL_PO3_LOGIC', note='Exact original detection; legacy benchmark results are frozen; new replay differs in fill/exits'))

# Original PO3 case is a separate reference, not automatically claimed revalidated by generic replay.
