"""Offline screen of PRE-DECLARED rule adaptations. Neither broker connection nor order execution."""
import json,hashlib,sys,math,csv,traceback
from pathlib import Path
from datetime import datetime,timezone
import pandas as pd
from . import replay_base as b
from . import new_variants as v
ROOT=Path(__file__).resolve().parents[1]
b.SRC=ROOT/'data/candles.db'
DAYS={'1min':1,'5min':5,'15min':15,'30min':30,'1h':60,'4h':240,'1day':1440}

def run():
 out=ROOT/'results';out.mkdir(exist_ok=True)
 cache={tf:b.load(tf) for tf in sorted(set(x[0] for x in v.CONFIG.values()))}
 result={'created_utc':datetime.now(timezone.utc).isoformat(),'source_db_sha256':hashlib.sha256(b.SRC.read_bytes()).hexdigest(),'framework':'independent mechanical adaptations, NOT byte-for-byte Github code','risk_policy':'max stop USD-price 10 intraday, 25 H1, 60 H4; fixed-cost USD-price per round-trip','data':{},'results':{},'errors':{},'cost_sensitivity':[0.4,1.0,2.0],'audit_remarks':['PIP/TICK SIZE not interchangeable with price USD.','No real bid/ask spread in archived OHLC: only assumed prices.','Close-of-bar signal, NEXT bar open entry; stop-first on double touch.','Timezone unconfirmed; session-dependent result diagnostic only.','Examined past bars are research data, cannot be considered untouched holdout.','Volume and model-based claims cannot be reproduced on OHLC alone.','30 repositories classified; 24 synthetic research hypotheses evaluated.']}
 for tf,d in cache.items():
  step=d.index.to_series().diff().dropna();delta=step.median()
  result['data'][tf]={'bars':len(d),'first':str(d.index.min()),'last':str(d.index.max()),'median_delta_minutes':round(delta.total_seconds()/60,3),'nonpositive':int((step<=pd.Timedelta(0)).sum()),'invalid_ohlc':int(((d.high<d.low)|(d.open>d.high)|(d.open<d.low)|(d.close>d.high)|(d.close<d.low)).sum()),'source_counts':d.source.value_counts().to_dict()}
 for name,(tf,func,cap,hold,repo,note) in v.CONFIG.items():
  d=cache[tf]
  try:
   sig=func(d)
   entry={'timeframe':tf,'repository_reference':repo,'method':'rule-adaptation not original EA','caveat':note,'bars':len(d),'costs':{}}
   for cost in [0.4,1.0,2.0]:
    trades,ex=b.replay(d,sig,cap=cap,horizon=hold,rr=1.8,cost=cost) # hold same for candidate, TP standardized to 1.8R
    stats=b.mt(trades)
    # descriptive split, historical data were consulted during iterative work (not pristine holdout)
    boundary=d.index[int(len(d)*0.65)]
    l=[t for t in trades if pd.Timestamp(t['entry_time'])<boundary]
    r=[t for t in trades if pd.Timestamp(t['entry_time'])>=boundary]
    stats.update({'early_65pct':b.mt(l),'late_35pct':b.mt(r),'rejected':ex['rejected_risk_or_target'],'signal_candidates':ex['candidates']})
    entry['costs'][str(cost)]=stats
    if cost==0.4:
     with (out/f'{name}.csv').open('w',newline='',encoding='utf-8') as f:
      ww=csv.DictWriter(f,fieldnames=['entry_time','exit_time','side','entry','stop','target','risk_price','exit','exit_reason','net_R']);ww.writeheader();ww.writerows(trades)
   result['results'][name]=entry
   m=entry['costs']['0.4'];print(f'{name:32s} {m["trades"]:4d} {m["total_R"]:>9.2f}R',flush=True)
  except Exception as e:
   result['errors'][name]=traceback.format_exc(limit=4)
   print(name,'ERROR',str(e),flush=True)
 (out/'screen_results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
 rows=[]
 for name,e in result['results'].items():
  m=e['costs']['0.4'];m2=e['costs']['1.0']; m3=e['costs']['2.0'];rows.append({'strategy':name,'timeframe':e['timeframe'],'source_repo':e['repository_reference'],'trades':m['trades'],'win_rate':m['win_rate'],'total_R_cost0.4':m['total_R'],'total_R_cost1.0':m2['total_R'],'total_R_cost2.0':m3['total_R'],'PF_cost0.4':m['PF'],'late35_R':m['late_35pct']['total_R'],'maxDD_R':m['max_DD_R'],'method':'independent adaptation'})
 pd.DataFrame(rows).sort_values('total_R_cost0.4',ascending=False).to_csv(out/'screen_summary.csv',index=False)
 return result
if __name__=='__main__':run()
