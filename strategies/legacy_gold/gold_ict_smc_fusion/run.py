"""Offline replay entrypoint. Never submits orders or writes to legacy gold_ledger."""
from __future__ import annotations
import argparse,csv,json,sys
from pathlib import Path
from datetime import datetime
from collections import defaultdict
from dataclasses import asdict
from .core import Config
from .loader import load_bars
from .strategy import generate_signals,signals_to_setups
from .execution import replay,evaluate
from .confluence import context_at

def main(argv=None):
    p=argparse.ArgumentParser()
    p.add_argument('--db',required=True)
    p.add_argument('--out',default='fusion_results')
    p.add_argument('--asof',help='YYYY-MM-DD HH:MM:SS (source local)',default=None)
    a=p.parse_args(argv)
    cfg=Config();asof=datetime.strptime(a.asof,'%Y-%m-%d %H:%M:%S') if a.asof else None
    m5=load_bars(a.db,'5min',asof=asof);h4=load_bars(a.db,'4h',asof=asof)
    if len(m5)<100 or len(h4)<10:raise RuntimeError('insufficient cTrader candles')
    sig=generate_signals(m5,h4,cfg)
    setups=signals_to_setups(sig,m5,cfg)
    trades=replay(setups,m5,cfg)
    by_strategy_isolated={name:evaluate(replay([x for x in setups if x.strategy==name],m5,cfg)) for name in
        ('GLS_SWEEP_MSS_FVG','H4_OB_M5_MSS','PO3_SWEEP_DISTRIBUTION')}
    m15=load_bars(a.db,'15min',asof=asof);m1=load_bars(a.db,'1min',asof=asof)
    context_rows=[]
    for item in sig:
        context_rows.append({'strategy':item.strategy,'side':item.side,'signal_at':item.signal_at.isoformat(sep=' '),
                             'context':context_at(item.signal_at,item.side,m15,m1)})
    # Predeclared chronological split, not parameter tuning.
    cut=m5[int(len(m5)*0.7)].t
    by_strategy={s:evaluate([t for t in trades if t['strategy']==s]) for s in
                 ['GLS_SWEEP_MSS_FVG','H4_OB_M5_MSS','PO3_SWEEP_DISTRIBUTION']}
    summary={'status':'RESEARCH_ONLY_NOT_LIVE_VALIDATED','source':'ctrader','data_note':'source-local Asia/Damascus timestamps',
             'input_bars':{'5min':len(m5),'4h':len(h4)},'first_bar':m5[0].t.isoformat(sep=' '),
             'last_completed_bar':m5[-1].end.isoformat(sep=' '),'cutoff_70pct':cut.isoformat(sep=' '),
             'config':asdict(cfg),'signal_count':len(sig),'risk_eligible_setups':len(setups),
             'overall':evaluate(trades),'by_strategy':by_strategy,'by_strategy_isolated':by_strategy_isolated,
             'by_strategy_isolated_split':{name:{'development':evaluate([t for t in replay([x for x in setups if x.strategy==name],m5,cfg) if datetime.fromisoformat(t['entry_at'])<cut]),
                                        'holdout':evaluate([t for t in replay([x for x in setups if x.strategy==name],m5,cfg) if datetime.fromisoformat(t['entry_at'])>=cut])}
                                        for name in ('GLS_SWEEP_MSS_FVG','H4_OB_M5_MSS','PO3_SWEEP_DISTRIBUTION')},
             'development':evaluate([t for t in trades if datetime.fromisoformat(t['entry_at'])<cut]),
             'holdout':evaluate([t for t in trades if datetime.fromisoformat(t['entry_at'])>=cut]),
             'warnings':['M1 overlap period is short; M1 confirmation not enabled in this baseline.',
                         '70/30 split is a diagnostic only, not statistically reliable with small samples.',
                         'No tick data or actual broker fills: same-bar stop-first and fixed assumed round-trip cost.',
                         'Heuristic strength scores are NOT probability of winning.',
                         'No optimization or win-rate guarantees.','Not connected to broker or legacy live ledger.']}
    out=Path(a.out);out.mkdir(parents=True,exist_ok=True)
    (out/'metrics.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf8')
    (out/'context_evidence.json').write_text(json.dumps(context_rows,ensure_ascii=False,indent=1),encoding='utf8')
    (out/'config.json').write_text(json.dumps(asdict(cfg),indent=2),encoding='utf8')
    (out/'signals.json').write_text(json.dumps([dict(strategy=s.strategy,side=s.side,signal_at=s.signal_at.isoformat(sep=' '),ref_at=s.ref_at.isoformat(sep=' '),reason=s.reason) for s in sig],ensure_ascii=False,indent=1),encoding='utf8')
    (out/'setups.json').write_text(json.dumps([x.to_dict() for x in setups],ensure_ascii=False,indent=1),encoding='utf8')
    with (out/'trades.csv').open('w',newline='',encoding='utf-8') as f:
        if trades:
            w=csv.DictWriter(f,fieldnames=trades[0].keys());w.writeheader();w.writerows(trades)
        else:f.write('strategy,entry_at,net_R\n')
    print(json.dumps({k:summary[k] for k in ('input_bars','signal_count','risk_eligible_setups','overall','development','holdout','by_strategy','by_strategy_isolated')},indent=2))
    return summary
if __name__=='__main__':main()
