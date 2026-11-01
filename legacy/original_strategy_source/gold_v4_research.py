#!/usr/bin/env python3
"""Causal V4 research comparator, runs on real user-provided CSV. No API/trading.
Companion to gold_strategy.py (V3). Requires pandas, numpy.
Important: results are from OHLC approximation and do NOT prove executable profitability.
"""
from __future__ import annotations
import argparse
import json
from dataclasses import asdict, replace
from pathlib import Path
import sys
import numpy as np
import pandas as pd

# Place the verified V3 gold_strategy.py beside this file.
from gold_strategy import Settings, load_candles, features, signals as v3_signals, Simulator, performance

VARIANTS = (
    "v3_sweep", "v3_sweep_mss", "v3_sweep_mss_fvg", "v3_filtered",
    "v4_sweep_reclaim", "v4_micro_mss", "v4_bar_mss",
    "v4_micro_fvg", "v4_micro_retest", "v4_micro_h1"
)


def make_v4_signals(data: pd.DataFrame, cfg: Settings, variant: str) -> pd.DataFrame:
    if variant not in VARIANTS:
        raise ValueError(variant)
    if variant.startswith('v3_'):
        return v3_signals(data, cfg, variant[3:])
    x = data.copy().reset_index(drop=True)
    n = len(x)
    x['signal'] = 0
    x['stop'] = np.nan
    x['sweep_extreme'] = np.nan
    x['reason'] = ''
    x['signal_id'] = ''
    x['signal_confirmed_at'] = pd.Series(pd.NaT,index=x.index,dtype='datetime64[ns, UTC]')
    pending = {1: None, -1: None}
    tf = pd.Timedelta(minutes=cfg.timeframe_minutes)

    def emit(i, d, e, reason):
        if x.at[i,'signal'] != 0 or not np.isfinite(x.at[i,'atr']):
            return
        # Stop beyond the actual extreme swept during this event.
        spread = float(x.at[i,'spread_price'])
        buffer = max(2*cfg.tick_size,float(x.at[i,'atr'])*cfg.atr_stop_fraction)
        raw_stop = (e['extreme']-buffer) if d==1 else (e['extreme']+buffer+spread)
        from math import floor,ceil
        stop = (floor(raw_stop/cfg.tick_size+1e-9) if d==1 else ceil(raw_stop/cfg.tick_size-1e-9))*cfg.tick_size
        x.at[i,'signal'] = d
        x.at[i,'stop'] = stop
        x.at[i,'sweep_extreme'] = e['extreme']
        x.at[i,'reason'] = reason
        x.at[i,'signal_id'] = f'{variant}:{d}:{x.at[e["idx"],"time"].isoformat()}'
        x.at[i,'signal_confirmed_at'] = x.at[i,'time']+tf

    for i in range(1,n):
        r = x.iloc[i]
        p = x.iloc[i-1]
        if not np.isfinite(r.atr):
            continue
        # Events expire rather than surviving overnight/weekly gaps.
        if r.time-p.time != tf:
            pending={1:None,-1:None}
        for d in (1,-1):
            e=pending[d]
            if e is None: continue
            age=i-e['idx']
            # update extreme from observations up to present bar ONLY
            e['extreme'] = min(e['extreme'],float(r.low)) if d==1 else max(e['extreme'],float(r.high))
            if age>6 or ((d==1 and r.close <= e['level']) or (d==-1 and r.close >= e['level'])):
                pending[d]=None;continue
            if not e['confirmed']:
                if age>4: pending[d]=None;continue
                crossed = (r.close > e['break_level'] and p.close<=e['break_level']) if d==1 else (r.close < e['break_level'] and p.close>=e['break_level'])
                # Must close directionally, not merely intrabar spike.
                directional = r.close > r.open if d==1 else r.close < r.open
                if crossed and directional:
                    e['confirmed']=True; e['confirmed_idx']=i
                    if variant in ('v4_micro_mss','v4_bar_mss','v4_micro_h1'):
                        aligned = (int(r.trend_60)==d) if variant=='v4_micro_h1' else True
                        if aligned: emit(i,d,e,'SWEEP+INTERNAL_BREAK'+('+H1' if variant=='v4_micro_h1' else ''))
                        pending[d]=None
                        continue
            if e['confirmed'] and variant in ('v4_micro_fvg','v4_micro_retest'):
                if not e.get('fvg_idx') and i-e['confirmed_idx']<=2:
                    if bool(r.fvg_bull if d==1 else r.fvg_bear):
                        e['fvg_idx']=i
                        e['zone_top']=float(r.low) if d==1 else float(x.at[i-2,'low'])
                        e['zone_bottom']=float(x.at[i-2,'high']) if d==1 else float(r.high)
                        if variant=='v4_micro_fvg':
                            emit(i,d,e,'SWEEP+INTERNAL_BREAK+FVG');pending[d]=None
                            continue
                elif not e.get('fvg_idx') and i-e['confirmed_idx']>2:
                    pending[d]=None
                if variant=='v4_micro_retest' and e.get('fvg_idx') and i>e['fvg_idx']:
                    if i-e['fvg_idx']>3:
                        pending[d]=None;continue
                    mid=(e['zone_top']+e['zone_bottom'])/2
                    touched = (r.low<=e['zone_top'] and r.close>=mid) if d==1 else (r.high>=e['zone_bottom'] and r.close<=mid)
                    if touched:
                        emit(i,d,e,'SWEEP+INTERNAL_BREAK+FVG_RETEST');pending[d]=None
        prev_low=float(p.last_sl) if pd.notna(p.last_sl) else np.nan
        prev_high=float(p.last_sh) if pd.notna(p.last_sh) else np.nan
        buy=np.isfinite(prev_low) and r.low<prev_low and r.close>prev_low
        sell=np.isfinite(prev_high) and r.high>prev_high and r.close<prev_high
        if buy and sell: continue
        if buy or sell:
            d=1 if buy else -1
            level=prev_low if buy else prev_high
            if variant == 'v4_sweep_reclaim':
                e={'idx':i,'extreme':float(r.low if buy else r.high)}
                emit(i,d,e,'SWEEP_RECLAIM')
                continue
            # Small, local pre-sweep structure rather than remote opposing swing.
            prior=x.iloc[max(0,i-4):i]
            if prior.empty: continue
            micro_level = float(prior.high.max() if buy else prior.low.min())
            bar_level = float(r.high if buy else r.low)
            # micro level should be near sweep and never rely on future candles.
            ref = (min(micro_level,bar_level) if buy else max(micro_level,bar_level))
            if variant=='v4_bar_mss': ref=bar_level
            pending[d] = {'idx':i,'level':level, 'extreme':float(r.low if buy else r.high),
                          'break_level':ref,'confirmed':False,'confirmed_idx':None}
    return x


class RiskCappedSimulator(Simulator):
    """Fixed ex-ante maximum price distance, not a guarantee against gap loss."""
    def __init__(self, cfg, max_stop_price=15.0):
        super().__init__(cfg)
        self.max_stop_price=max_stop_price
    def enter(self,row,signal_row):
        d=int(signal_row.signal)
        if d not in (-1,1):return
        entry=float(row.open)+(float(row.spread_price) if d==1 else 0)+d*self.c.entry_slippage
        distance=(entry-float(signal_row.stop))*d
        if not np.isfinite(distance) or distance<=0:
            self.reject('INVALID_STOP');return
        if self.max_stop_price>0 and distance>self.max_stop_price:
            self.reject('STOP_OVER_MAX_PRICE_DISTANCE');return
        return super().enter(row,signal_row)


def evaluate(df,cfg,output,holdout_fraction=.30,max_stop_price=15):
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    f=features(df,cfg)
    split=int(len(f)*(1-holdout_fraction))
    split_time=str(f.time.iloc[split])
    reports={'data_bars':len(df),'split_time':split_time, 'spec':asdict(cfg),
             'max_stop_price':max_stop_price,'results':{}}
    for variant in VARIANTS:
        x=make_v4_signals(f,cfg,variant)
        reports['results'][variant]={}
        for part in ('dev','holdout'):
            if part=='dev': data=x.iloc[:split].reset_index(drop=True)
            else:
                data=x.iloc[split-1:].reset_index(drop=True).copy()
                data.loc[0,'signal']=0 # only first real holdout bar may open
            sim=RiskCappedSimulator(cfg,max_stop_price=max_stop_price)
            trades,equity=sim.run(data)
            result=performance(trades,equity,cfg)
            result['signals']=int((data.signal!=0).sum())
            result['rejected']=sim.rejected
            reports['results'][variant][part]=result
            trades.to_csv(output/f'{variant}_{part}_trades.csv',index=False)
            if variant in ('v4_micro_mss','v3_sweep_mss'):
                data.loc[data.signal!=0,['time','signal','stop','sweep_extreme','reason','signal_id']].to_csv(output/f'{variant}_{part}_signals.csv',index=False)
        dev=reports['results'][variant]['dev']
        test=reports['results'][variant]['holdout']
        print(f'{variant:22} DEV n={dev["trades"]:3} R={str(dev["avg_r"]):>7} PF={str(dev["profit_factor"]):>5} | HOLD n={test["trades"]:3} R={str(test["avg_r"]):>7} PF={str(test["profit_factor"]):>5}')
    # Choose pre-specified threshold on development only; never peek at holdout to choose.
    eligible=[(v,reports['results'][v]['dev']) for v in VARIANTS if reports['results'][v]['dev']['trades']>=30 and (reports['results'][v]['dev']['avg_r'] or -999)>0 and (reports['results'][v]['dev']['profit_factor'] or 0)>1.05]
    reports['dev_choice']=max(eligible,key=lambda z:(z[1]['avg_r'] if z[1]['avg_r'] is not None else float('-inf')))[0] if eligible else None
    reports['caution']='ARCHIVE XAU snapshot source, NOT confirmed JustMarkets/cTrader. 1-month limited sample. Assumed bid spread, no ticks, bar OHLC stop-first.'
    (output/'report.json').write_text(json.dumps(reports,indent=2,ensure_ascii=False),encoding='utf-8')
    print('DEV_CHOICE', reports['dev_choice'] or 'NONE — no positive development edge after costs', '(would still require independent forward confirmation)')
    return reports


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--csv',required=True)
    ap.add_argument('--table')
    ap.add_argument('--symbol')
    ap.add_argument('--timeframe-name')
    ap.add_argument('--out',default='v4_results')
    ap.add_argument('--spread-price',type=float,default=.20)
    ap.add_argument('--max-stop',type=float,default=15.)
    ap.add_argument('--commission-rt',type=float,default=7.)
    ap.add_argument('--capital',type=float,default=10000.)
    args=ap.parse_args()
    cfg=Settings(assumed_spread_price=args.spread_price,commission_roundtrip_per_lot=args.commission_rt,initial_capital=args.capital)
    bars,quality=load_candles(args.csv,cfg,table=args.table,symbol=args.symbol,timeframe_name=args.timeframe_name)
    print('DATA',json.dumps(quality,ensure_ascii=False))
    report=evaluate(bars,cfg,args.out,max_stop_price=args.max_stop)
    report['data_quality']=quality
    (Path(args.out)/'report.json').write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8')

if __name__=='__main__':main()
