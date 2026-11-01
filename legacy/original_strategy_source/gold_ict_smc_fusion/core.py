"""Causal, deterministic ICT/SMC research primitives for XAUUSD.
Independent implementation from documented trading definitions; no third-party code copied.
Candle.t is the bar OPEN timestamp in broker/source-local time; bar is usable after close.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from typing import Optional
import math

MINUTES = {"1min": 1, "5min": 5, "15min": 15, "1h": 60, "4h": 240, "1day": 1440}

@dataclass(frozen=True)
class Bar:
    t: datetime
    o: float
    h: float
    l: float
    c: float
    timeframe: str = "5min"
    @property
    def end(self) -> datetime:
        return self.t + timedelta(minutes=MINUTES[self.timeframe])

    def __post_init__(self):
        if self.timeframe not in MINUTES or not all(math.isfinite(x) for x in (self.o,self.h,self.l,self.c)):
            raise ValueError('invalid timeframe/prices')
        if self.l > min(self.o,self.c) or self.h < max(self.o,self.c) or self.h < self.l or min(self.o,self.h,self.l,self.c) <= 0:
            raise ValueError('invalid OHLC')

@dataclass(frozen=True)
class Swing:
    side: str  # high or low
    price: float
    pivot_at: datetime
    known_at: datetime
    pivot_index: int
    confirmed_index: int

@dataclass(frozen=True)
class Gap:
    side: int  # 1 bullish, -1 bearish
    low: float
    high: float
    formed_at: datetime
    known_at: datetime
    formed_index: int

@dataclass(frozen=True)
class Setup:
    strategy: str
    side: int
    signal_at: datetime
    entry_at: datetime
    entry: float
    sl: float
    tps: tuple[float, float, float]
    grade: str
    strength: float  # heuristic, not calibrated probability
    reason: str
    ref_at: datetime
    @property
    def risk(self):return abs(self.entry-self.sl)
    def to_dict(self):
        d=asdict(self)
        for k in ('signal_at','entry_at','ref_at'):d[k]=d[k].isoformat(sep=' ')
        d['tps']=list(self.tps)
        return d

@dataclass(frozen=True)
class Config:
    swing_n: int = 2
    atr_n: int = 14
    max_sl_usd: float = 10.0
    min_sl_usd: float = 0.4
    spread_roundtrip_usd: float = 0.4
    sl_buffer_atr: float = 0.08
    fvg_min_atr: float = 0.04
    sweep_min_atr: float = 0.03
    sweep_window_bars: int = 10
    retest_window_bars: int = 10
    no_gap_max_minutes: int = 20  # don't chain patterns across session gaps
    max_hold_bars: int = 120
    same_bar_conservative: bool = True
    max_one_open: bool = True

    def validate(self):
        if self.swing_n < 1 or self.atr_n < 2 or self.max_sl_usd <= self.min_sl_usd or self.spread_roundtrip_usd < 0:
            raise ValueError('invalid parameters')
