"""Local file-based research daemon, **never** sends broker orders.
Feed data/ctrader_live/*.csv using read-only cTrader API or an authorized external fetcher.
Every closed candle is only announced once (checkpoint file).
Stop it with Ctrl+C; strategy on/off controls config/strategy_switches.json.
"""
from __future__ import annotations
from datetime import datetime,timezone
from pathlib import Path
import argparse,json,time,os
from engine.signal_hub import evaluate_latest,parse_ctrader_csv,TF_MINUTES
ROOT=Path(__file__).resolve().parents[1]

def run_once(source_dir,ledger_path):
    source=Path(source_dir);ledger_path=Path(ledger_path)
    frames={tf:parse_ctrader_csv(source/f'{tf}.csv', expected_period={'1min':'M1','5min':'M5','15min':'M15','30min':'M30','1h':'H1','4h':'H4','1day':'D1'}[tf]) for tf in TF_MINUTES if (source/f'{tf}.csv').exists()}
    if not frames:return {'status':'NO_CTRADER_CSV','emitted':0,'checked':0}
    proposals,errors=evaluate_latest(frames,datetime.now(timezone.utc))
    last=json.loads(ledger_path.read_text()) if ledger_path.exists() else {}
    new=[]
    for p in proposals:
        key=p.strategy_id+'|'+p.timeframe+'|'+p.signal_bar_end_utc.isoformat()+'|'+p.side
        if key in last:continue
        last[key]='SHADOW_ONLY';new.append({'id':p.strategy_id,'side':p.side,'timeframe':p.timeframe,'bar_end_utc':p.signal_bar_end_utc.isoformat(),'stop':p.stop_price,'target':p.target_price,'evidence':p.signals})
    ledger_path.parent.mkdir(parents=True,exist_ok=True)
    temp=ledger_path.with_suffix('.tmp');temp.write_text(json.dumps(last,ensure_ascii=False,indent=2));temp.replace(ledger_path)
    for e in new:print(json.dumps({'event':'NEW_RESEARCH_SIGNAL',**e},ensure_ascii=False),flush=True)
    return {'status':'SHADOW','emitted':len(new),'checked':len(proposals),'errors':errors}

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--source-dir',default='data/ctrader_live');ap.add_argument('--ledger',default='runtime/paper_seen.json');ap.add_argument('--poll-seconds',type=int,default=30);ap.add_argument('--once',action='store_true')
    a=ap.parse_args()
    if a.poll_seconds<10:raise SystemExit('poll-seconds must be >=10')
    while True:
        try: print(json.dumps(run_once(a.source_dir,a.ledger),ensure_ascii=False),flush=True)
        except (ValueError,OSError) as e: print(json.dumps({'error':str(e)[:200],'mode':'SHADOW_ONLY'}),flush=True)
        if a.once:break
        time.sleep(a.poll_seconds)
if __name__=='__main__':main()
