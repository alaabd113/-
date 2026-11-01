"""Read-only demo account readiness & exposure check. No order send."""
from pathlib import Path
import os,json
from ctrader.local_secrets import load_env
from scripts.run_demo import worker,ROOT

def main():
    load_env(ROOT/'.env')
    r=worker(['-m','ctrader.demo_worker','--task','snapshot',
              '--symbol-id',os.environ['CTRADER_SYMBOL_ID']])
    x=r['snapshot'];q=x['quote']
    print(json.dumps({'mode':'DEMO','account_id':x['account_id'],'currency':x['currency'],
        'balance':x['balance_usd'],'open_positions':x['open_positions'],
        'pending_orders':x['pending_orders'],'symbol':x['symbol']['symbol_name'],
        'spread':q['ask']-q['bid'],'timestamp_ms':q['timestamp_ms']},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
