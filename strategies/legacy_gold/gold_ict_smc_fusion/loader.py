"""cTrader-only input: never merge vendor prices without explicit separate research."""
from __future__ import annotations
import sqlite3
from contextlib import closing
from datetime import datetime
from .core import Bar,MINUTES

FMT='%Y-%m-%d %H:%M:%S'

def load_bars(db:str,tf:str,source='ctrader',asof:datetime|None=None)->list[Bar]:
    if tf not in MINUTES:raise ValueError('invalid timeframe')
    with closing(sqlite3.connect(f'file:{db}?mode=ro',uri=True)) as conn:
        rows=conn.execute('SELECT ts,o,h,l,c FROM candles WHERE symbol=? AND interval=? AND source=? ORDER BY ts',('XAUUSD',tf,source)).fetchall()
    bars=[]
    for ts,o,h,l,c in rows:
        x=Bar(datetime.strptime(ts,FMT),float(o),float(h),float(l),float(c),tf)
        if bars and x.t<=bars[-1].t:raise ValueError('duplicates/disordered candles')
        if asof is None or x.end<=asof:bars.append(x)
    return bars
