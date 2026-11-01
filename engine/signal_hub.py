"""Unified strategy signal assembly, OHLC validation, and causal confluence evidence.
Enabled research strategies produce shadow signals from closed UTC cTrader candles.
No network calls or order dispatch in this module. Never treats historical unknown-TZ SQLite as UTC.
"""
from __future__ import annotations
from datetime import datetime,timezone,timedelta
import math
from pathlib import Path
import numpy as np
import pandas as pd
from strategies.catalog import SPECS
from engine.strategy_registry import read
from engine.pipeline import Candidate
from research import replay_base as b

TF_MINUTES={'1min':1,'5min':5,'15min':15,'30min':30,'1h':60,'4h':240,'1day':1440}

def parse_ctrader_csv(path, expected_period=None, require_meta=True):
    """Read cTrader API-decompressed candles; timestamps MUST be UTC & timezone aware."""
    path=Path(path)
    if require_meta:
        sidecar=path.with_name(path.name+'.meta.json')
        if not sidecar.exists():raise ValueError('Missing cTrader API identity sidecar')
        import json
        m=json.loads(sidecar.read_text(encoding='utf8'))
        if m.get('price_source')!='CTRADER_OPEN_API_DEMO' or not int(m.get('account_id',0)) or not int(m.get('symbol_id',0)):
            raise ValueError('Unverified cTrader DEMO data source')
        if expected_period and m.get('period')!=expected_period:
            raise ValueError('Timeframe sidecar mismatch')
    df=pd.read_csv(path)
    required={'timestamp_utc','open','high','low','close'}
    if not required.issubset(df.columns):raise ValueError('Missing columns '+str(required-set(df.columns)))
    ts=df['timestamp_utc'].astype(str)
    if not ts.str.contains(r'(?:Z|[+-]\d\d:?\d\d)$',regex=True).all():
        raise ValueError('Source must state UTC offset in EVERY timestamp')
    df['timestamp_utc']=pd.to_datetime(ts,utc=True,errors='raise')
    df=df.sort_values('timestamp_utc')
    if df.timestamp_utc.duplicated().any(): raise ValueError('Duplicate UTC candle timestamps')
    cols=['open','high','low','close']+(['volume'] if 'volume' in df.columns else [])
    d=df.set_index('timestamp_utc')[cols].astype(float)
    if d.empty or not np.isfinite(d.to_numpy()).all():raise ValueError('Empty/invalid candle prices')
    if 'volume' in d.columns and (d.volume<0).any():raise ValueError('Negative volume')
    if ((d.low<=0)|(d.high<d.low)|(d.open<d.low)|(d.open>d.high)|(d.close<d.low)|(d.close>d.high)).any():
        raise ValueError('OHLC consistency failure')
    return d

def closed_only(df, timeframe, asof_utc):
    if timeframe not in TF_MINUTES:raise ValueError('Unsupported TF')
    if asof_utc.tzinfo is None:raise ValueError('UTC-aware now is required')
    if not isinstance(df.index,pd.DatetimeIndex) or df.index.tz is None:
        raise ValueError('UTC-aware candle index required')
    x=df.copy();x.index=x.index.tz_convert('UTC')
    end=x.index+pd.to_timedelta(TF_MINUTES[timeframe],unit='min')
    x=x.loc[end<=pd.Timestamp(asof_utc).tz_convert('UTC')]
    if x.empty:raise ValueError('No fully closed candles')
    return x

def _completed_htf_bias(ctx,when,direction):
    if ctx is None or ctx.empty:return False
    # timestamp in context = bar OPEN, so availability delayed by entire HTF period
    x=ctx.loc[(ctx.index+pd.Timedelta(hours=4))<=when]
    if len(x)<51:return False
    e=x.close.ewm(span=50,adjust=False,min_periods=50).mean()
    return bool(np.isfinite(e.iloc[-1]) and direction*(x.close.iloc[-1]-e.iloc[-1])>0)

def evidence_for(d,position,side,tf,h4=None):
    """Causal completed-bar evidence. Heuristic indicators, not calibrated probabilities."""
    if position<60:return {}
    now=d.index[position]+pd.Timedelta(minutes=TF_MINUTES[tf])
    c=d.iloc[position];prior=d.iloc[:position]
    a=b.atr(d.iloc[:position+1]).iloc[-1]
    if not np.isfinite(a) or a<=0:return {}
    fast=d.close.iloc[:position+1].ewm(span=20,adjust=False).mean().iloc[-1]
    slow=d.close.iloc[:position+1].ewm(span=50,adjust=False).mean().iloc[-1]
    hi=prior.high.tail(20).max();lo=prior.low.tail(20).min()
    rng=max(c.high-c.low,1e-8)
    # Liquidity sweep only if prior levels are known BEFORE current bar.
    sweep=(c.low<lo and c.close>lo) if side==1 else (c.high>hi and c.close<hi)
    displacement=(abs(c.close-c.open)>=0.8*a)
    structure=(c.close>prior.high.tail(8).max()) if side==1 else (c.close<prior.low.tail(8).min())
    bias=(_completed_htf_bias(h4,now,side) if tf!='4h' and tf!='1day' else side*(fast-slow)>0)
    utc_hour=now.hour
    return {'structure':bool(structure),'liquidity':bool(sweep),'displacement':bool(displacement),
            'higher_timeframe':bool(bias),'session':7<=utc_hour<21,
            'entry_confirmation':bool(side*(c.close-c.open)>0)}

def evaluate_latest(frames,asof_utc,registry=None):
    """Evaluate every enabled independent strategy; never infer order permission."""
    registry=read() if registry is None else registry
    output=[]; errors={}
    for sid,spec in SPECS.items():
        if not registry['strategies'][sid]['enabled']:continue
        if spec.timeframe not in frames:continue
        try:
            d=closed_only(frames[spec.timeframe],spec.timeframe,asof_utc)
            if len(d)<250:continue
            if sid=='PO3_FROZEN_M5':
                # Original full-context PO3 requires validated M5/H4 UTC data; do not load unverified local historical DB.
                if '4h' not in frames:continue
                from strategies.legacy_gold.gold_ict_smc_fusion.core import Config,Bar
                from strategies.legacy_gold.gold_ict_smc_fusion.strategy import generate_signals
                h4=closed_only(frames['4h'],'4h',asof_utc)
                def bars(frame,tf):
                    return [Bar(t.to_pydatetime().replace(tzinfo=None),float(r.open),float(r.high),float(r.low),float(r.close),tf)
                            for t,r in frame.iterrows()]
                sigs=[s for s in generate_signals(bars(d,'5min'),bars(h4,'4h'),Config()) if s.strategy=='PO3_SWEEP_DISTRIBUTION']
                if not sigs:continue
                s=sigs[-1]
                if s.signal_at!=d.index[-1].tz_localize(None).to_pydatetime()+timedelta(minutes=5):continue
                side=int(s.side);stop=s.sl_reference-side*.08*s.atr
                risk=side*(float(d.close.iloc[-1])-stop)
                target=float(d.close.iloc[-1])+side*risk*2
            else:
                signals=spec.generator(d.copy().tz_localize(None))
                if len(signals)!=len(d):raise ValueError('Signal frame length mismatch')
                last=signals.iloc[-1]
                side=int(last['side']);stop=float(last['stop']);target=float(last['target'])
            if side==0 or not np.isfinite([stop,target]).all():continue
            when=(d.index[-1]+pd.Timedelta(minutes=TF_MINUTES[spec.timeframe])).to_pydatetime()
            side_text='BUY' if side==1 else 'SELL'
            ev=evidence_for(d,len(d)-1,side,spec.timeframe,frames.get('4h'))
            output.append(Candidate(sid,'XAUUSD',spec.timeframe.upper().replace('MIN','M'),when,side_text,stop,target,
                                    True,True,'UNCLASSIFIED_RESEARCH',ev))
        except Exception as ex:
            errors[sid]=str(ex)[:180]
    return output,errors
