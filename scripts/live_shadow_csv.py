"""Read newly downloaded (UTC-tagged) cTrader bars and show latest signals. NO ORDERS.
Example: python -m scripts.live_shadow_csv --source-dir data/ctrader_live --asof-now
Files: data/ctrader_live/5min.csv, 4h.csv, 15min.csv etc with timestamp_utc,OHLC.
"""
from __future__ import annotations
import argparse,json
from datetime import datetime,timezone
from pathlib import Path
from engine.signal_hub import parse_ctrader_csv,evaluate_latest,TF_MINUTES

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--source-dir',default='data/ctrader_live')
    ap.add_argument('--asof-now',action='store_true',required=True)
    a=ap.parse_args();root=Path(a.source_dir)
    frames={tf:parse_ctrader_csv(root/(tf+'.csv'), expected_period={'1min':'M1','5min':'M5','15min':'M15','30min':'M30','1h':'H1','4h':'H4','1day':'D1'}[tf]) for tf in TF_MINUTES if (root/(tf+'.csv')).exists()}
    if not frames:raise SystemExit('No UTC cTrader CSV history. Download bars first; see docs/CTRADER_AR.md')
    signals,errors=evaluate_latest(frames,datetime.now(timezone.utc))
    print(json.dumps({'mode':'SHADOW_ONLY','strategies_fired':[{'strategy':s.strategy_id,'tf':s.timeframe,'side':s.side,
      'candle_closed':s.signal_bar_end_utc.isoformat(),'stop':s.stop_price,'target':s.target_price,
      'evidence':s.signals} for s in signals], 'errors':errors},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
