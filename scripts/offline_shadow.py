"""Read-only last-signal inspector; NEVER submits orders."""
import argparse,json
from pathlib import Path
from research import new_variants as v,replay_base as b
from engine.pipeline import Candidate
b.SRC=Path(__file__).resolve().parents[1]/'data/candles.db'

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--strategy',choices=sorted(v.CONFIG),default='BOLL_RSI_FADE_M5');a=ap.parse_args()
 tf,fn,cap,hold,repo,note=v.CONFIG[a.strategy];d=b.load(tf);s=fn(d)
 # Candle times in historical DB have no confirmed timezone. Never fabricate 'now' decision from them.
 active=s.loc[s.side!=0].tail(5).copy()
 print(json.dumps({'mode':'HISTORICAL_SHADOW_ONLY','strategy':a.strategy,'source_repo':repo,'timeframe':tf,'time_zone_verified':False,'last_historical_signal_bars':[{'timestamp_unverified':str(i),'side':'BUY' if int(row.side)==1 else 'SELL','stop':float(row.stop),'target':float(row.target)} for i,row in active.iterrows()]},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
