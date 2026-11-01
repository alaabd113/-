"""List, enable, disable and backtest individual strategy generators.
Never sends trading orders. A disabled strategy is never evaluated by scan.
"""
from __future__ import annotations
import argparse,json,csv,sys
from pathlib import Path
from engine.strategy_registry import read,toggle,active
from strategies.catalog import SPECS
from research import replay_base as b
ROOT=Path(__file__).resolve().parents[1]; b.SRC=ROOT/'data/candles.db'

def main():
    ap=argparse.ArgumentParser()
    sub=ap.add_subparsers(dest='cmd',required=True)
    sub.add_parser('list')
    for c in ('enable','disable','backtest'):
        sub.add_parser(c).add_argument('id',choices=sorted(SPECS))
    q=sub.add_parser('scan');q.add_argument('--all',action='store_true');q.add_argument('--cost',type=float,default=0.4)
    a=ap.parse_args()
    if a.cmd=='list':
        cfg=read()
        for sid,v in sorted(cfg['strategies'].items()):
            print(('ON ' if v['enabled'] else 'OFF'),sid,v['timeframe'],'DEMO_FORBIDDEN' if not v['allow_demo'] else 'DEMO_PERMITTED')
        print('TOTAL',len(SPECS),'ENABLED',sum(x['enabled'] for x in cfg['strategies'].values()))
    elif a.cmd in ('enable','disable'):
        print(json.dumps({a.id:toggle(a.id,a.cmd=='enable')},ensure_ascii=False))
    else:
        selected=SPECS if a.cmd=='backtest' else active()
        if a.cmd=='backtest':selected={a.id:SPECS[a.id]}
        dcache={};out=[]
        for sid,spec in selected.items():
            if spec.timeframe not in dcache:dcache[spec.timeframe]=b.load(spec.timeframe)
            d=dcache[spec.timeframe];signals=spec.generator(d)
            if list(signals.columns)!=['side','stop','target']:
                raise ValueError('Invalid signal schema: '+sid)
            if a.cmd=='scan' and not a.all:
                recent=signals[signals.side!=0].tail(1)
                print(json.dumps({'id':sid,'timeframe':spec.timeframe,'latest_historical_signal':str(recent.index[-1]) if len(recent) else None,'signals_in_dataset':int((signals.side!=0).sum()),'mode':'HISTORICAL_SHADOW'},ensure_ascii=False))
                continue
            trades,ex=b.replay(d,signals,cap=spec.stop_cap,horizon=spec.max_hold_bars,cost=a.cost if a.cmd=='scan' else 0.4,rr=spec.rr)
            res={'id':sid,'tf':spec.timeframe,'source':spec.source,'trades':len(trades),**b.mt(trades),'hypothesis_only':True}
            out.append(res);print(json.dumps(res,ensure_ascii=False))
        if out:
            folder=ROOT/'results';folder.mkdir(exist_ok=True)
            (folder/'strategy_registry_scan.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf8')
if __name__=='__main__':main()
