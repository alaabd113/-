"""Pre-registered *diagnostic* null tests. No claim of untouched out-of-sample performance.
Method: signal timing fixed, direction randomised with same stop distances/TP and costs;
bootstrap mean R interval (trade-level iid approximation) for data-snooping detection.
"""
from __future__ import annotations
import numpy as np,pandas as pd,json
from pathlib import Path
from . import new_variants as v,replay_base as b
R=Path(__file__).resolve().parents[1];b.SRC=R/'data/candles.db'
WINNERS=['BOLL_RSI_FADE_M5','HA_MOMENTUM_H1','DONCHIAN55_H4','DONCHIAN20_H1','TRIPLE_CONFIRM_M15']

def run(n_trials=200):
 rng=np.random.default_rng(20261101);report={'note':'Exploratory only. This market sample is NOT pristine OOS; random-direction baselines share entry times and never establish superiority to random entry. No model approved.'}
 for name in WINNERS:
  tf,fn,cap,hold,repo,note=v.CONFIG[name];d=b.load(tf);sig=fn(d)
  original,_=b.replay(d,sig,cap=cap,horizon=hold,rr=1.8,cost=1.0)
  original_r=np.array([r['net_R'] for r in original]);sums=[]
  sides=sig.side.to_numpy(dtype=int);stops=sig.stop.to_numpy(dtype=float)
  close=d.close.to_numpy(dtype=float);risks=np.abs(close-stops)
  for _ in range(n_trials):
   rand=np.where(sides!=0,sides*rng.choice([-1,1],size=len(sides)),0)
   flipped=sig.copy();flipped['side']=rand
   flipped['stop']=close-rand*risks
   flipped['target']=close+rand*risks*1.8
   tr,_=b.replay(d,flipped,cap=cap,horizon=hold,rr=1.8,cost=1.0)
   sums.append(sum(t['net_R'] for t in tr))
  boots=np.mean(rng.choice(original_r,size=(2000,len(original_r)),replace=True),axis=1) if len(original_r) else np.array([])
  orig=sum(original_r)
  report[name]={'repo_reference':repo,'trades':len(original),'net_R_at_1usd':round(float(orig),4),'expected_R':round(float(original_r.mean()),4) if len(original_r) else None,'bootstrap95_mean_R':np.percentile(boots,[2.5,97.5]).round(4).tolist() if len(boots) else None,'random_direction_mean_net_R':round(float(np.mean(sums)),4),'random_direction_p_upper':round((1+sum(x>=orig for x in sums))/(len(sums)+1),4),'trials':n_trials}
  print('STRESS',name,report[name],flush=True)
 (R/'results/stress.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
 return report
if __name__=='__main__':run()
