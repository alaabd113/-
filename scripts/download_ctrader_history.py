"""Safely fetch historical cTrader demo OHLC per timeframe in small chronological windows.
Requires OAuth env vars, symbol ID from symbols list and official cTrader SDK.
Each window uses separate SDK process to avoid Twisted reactor restart inside a process.
No orders are placed. Fail closed on missing windows or has_more.
"""
from __future__ import annotations
import argparse,sys,subprocess,json,os,time
from datetime import datetime,timezone,timedelta
from pathlib import Path
WINDOW_HOURS={'M1':6,'M5':24,'M15':72,'M30':120,'H1':336,'H4':720,'D1':4320}
NAMES={'M1':'1min','M5':'5min','M15':'15min','M30':'30min','H1':'1h','H4':'4h','D1':'1day'}

def dt(s):
    d=datetime.fromisoformat(s.replace('Z','+00:00'))
    if d.tzinfo is None:raise ValueError('Timestamp needs UTC timezone suffix')
    return d.astimezone(timezone.utc)

def windows(start,end,max_delta):
    cur=start
    while cur<end:
        nxt=min(end,cur+max_delta)
        yield int(cur.timestamp()*1000),int(nxt.timestamp()*1000)
        cur=nxt

def main():
    a=argparse.ArgumentParser();a.add_argument('--symbol-id',type=int,required=True)
    a.add_argument('--from-utc',required=True,help='e.g. 2026-10-01T00:00:00Z')
    a.add_argument('--to-utc',required=True,help='e.g. 2026-11-01T00:00:00Z')
    a.add_argument('--periods',default='M1,M5,M15,M30,H1,H4,D1')
    a.add_argument('--out-dir',default='data/ctrader_live');a.add_argument('--dry-run',action='store_true')
    args=a.parse_args();start=dt(args.from_utc);end=dt(args.to_utc)
    if start>=end:raise SystemExit('Invalid date range')
    if args.symbol_id<=0:raise SystemExit('Invalid broker symbol ID')
    ps=args.periods.split(',')
    if not ps or any(q not in WINDOW_HOURS for q in ps):raise SystemExit('Invalid periods')
    if not args.dry_run:
        required=['CTRADER_ACCOUNT_ID','CTRADER_CLIENT_ID','CTRADER_CLIENT_SECRET','CTRADER_ACCESS_TOKEN']
        if any(not os.environ.get(k) for k in required):raise SystemExit('Missing cTrader env credentials')
    for period in ps:
        folder=Path(args.out_dir);output=folder/(NAMES[period]+'.csv')
        for left,right in windows(start,end,timedelta(hours=WINDOW_HOURS[period])):
            cmd=[sys.executable,'-m','ctrader.demo_client','--task','bars','--symbol-id',str(args.symbol_id),
                 '--period',period,'--from-ms',str(left),'--to-ms',str(right),'--count','500','--output',str(output)]
            if args.dry_run:
                print('DRY_RUN',period,datetime.fromtimestamp(left/1000,timezone.utc).isoformat(),datetime.fromtimestamp(right/1000,timezone.utc).isoformat())
                continue
            res=subprocess.run(cmd,text=True,capture_output=True,timeout=80)
            if res.returncode:
                raise SystemExit(f'Historical download failed for {period} window at {left}: {res.stderr[:250]}')
            records=[json.loads(x) for x in res.stdout.splitlines() if x.startswith('{') and 'bars_received' in x]
            if len(records)!=1:
                raise SystemExit(f'Incomplete or failed SDK response for {period} window at {left}: {res.stderr[:220]}')
            if records[0].get('has_more'):
                raise SystemExit(f'Incomplete window (has_more=true) at {left} for {period}; use smaller windows and retry')
            print(period,'bars_received',records[0]['bars_received'],'stored',records[0]['stored'],flush=True)
            time.sleep(.3)  # conservative rate limit and broker load
if __name__=='__main__':main()
