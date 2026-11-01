"""Unattended DEMO scheduler: acquire fresh cTrader bars, compute enabled signal
layers, verify broker snapshot & daily risk, and dispatch at most one protected order.

Run from project root: python -m scripts.run_demo
It NEVER connects to live cTrader endpoint. Credentials loaded privately from .env.
"""
from __future__ import annotations
import argparse, csv, json, os, subprocess, sys, time
from datetime import datetime,timedelta,timezone
from pathlib import Path
from dataclasses import asdict,replace
from math import isfinite

from engine.pipeline import Candidate,Account,BrokerSymbol,Quote,assess
from engine.signal_hub import TF_MINUTES,evaluate_latest,parse_ctrader_csv
from engine.context_integration import apply as apply_context
from engine.strategy_registry import read as switches
from engine.intent_store import IntentStore
from strategies.catalog import SPECS
from ctrader.local_secrets import load_env,save_tokens
from ctrader.credentials import refresh_token
from engine.telegram_control import start_optional,notify_owner

ROOT=Path(__file__).resolve().parents[1]
PERIODS={'1min':'M1','5min':'M5','15min':'M15','30min':'M30','1h':'H1','4h':'H4','1day':'D1'}
BOOTSTRAP_DAYS={'M1':3,'M5':30,'M15':35,'M30':50,'H1':75,'H4':160,'D1':420}
STATE=ROOT/'runtime'

def event(typ,**fields):
    print(json.dumps({'time_utc':datetime.now(timezone.utc).isoformat(),'event':typ,**fields},ensure_ascii=False,default=str),flush=True)

def worker(args, timeout=65):
    result=subprocess.run([sys.executable,*args],cwd=ROOT,env=os.environ.copy(),capture_output=True,text=True,timeout=timeout)
    if result.returncode:
        # Never display potentially sensitive SDK raw error text.
        raise RuntimeError('BROKER_WORKER_EXIT_'+str(result.returncode))
    records=[line.removeprefix('RESULT_JSON:') for line in result.stdout.splitlines() if line.startswith('RESULT_JSON:')]
    if len(records)!=1:raise RuntimeError('BROKER_RESULT_MISSING')
    return json.loads(records[0])

def load_configuration():
    cfg=json.loads((ROOT/'config/settings.json').read_text(encoding='utf8'))
    cfg['mode']='DEMO'; cfg['allow_demo_order']=True
    if cfg.get('allow_live_order') is not False:raise RuntimeError('LIVE_EXECUTION_MUST_BE_DISABLED')
    return cfg

def configured_strategies():
    registry=switches()
    return {k:v for k,v in registry['strategies'].items() if v['enabled'] and v['allow_demo'] and not v['research_only']}

def period_due(tf,now,folder):
    path=folder/(tf+'.csv')
    if not path.exists():return True
    try:
        with path.open(encoding='utf8') as f:
            row=next(reversed(list(csv.DictReader(f))))
        last=datetime.fromisoformat(row['timestamp_utc'].replace('Z','+00:00'))
        return last+timedelta(minutes=TF_MINUTES[tf])<=now-timedelta(seconds=10)
    except Exception: return True

def acquire_candles(folder,now,initial=False):
    """Fetch each due timeframe. Historical downloader validates data source & windows."""
    folder.mkdir(parents=True,exist_ok=True)
    for tf,period in PERIODS.items():
        path=folder/(tf+'.csv')
        if not initial and not period_due(tf,now,folder):continue
        stamp=folder/('.last_fetch_'+period)
        minimum_seconds=max(55,min(TF_MINUTES[tf]*60,300))
        if not initial and stamp.exists() and now.timestamp()-float(stamp.read_text())<minimum_seconds:continue
        if not path.exists(): start=now-timedelta(days=BOOTSTRAP_DAYS[period])
        else:
            # Preserve context in CSV; fetch only an overlapping tail, not the whole last two days.
            with path.open(encoding='utf8') as f:
                rows=list(csv.DictReader(f))
            last=datetime.fromisoformat(rows[-1]['timestamp_utc'].replace('Z','+00:00')) if rows else now-timedelta(days=2)
            start=max(last-timedelta(minutes=TF_MINUTES[tf]*5), now-timedelta(days=10))
        cmd=[sys.executable,'-m','scripts.download_ctrader_history',
             '--symbol-id',os.environ['CTRADER_SYMBOL_ID'],
             '--from-utc',start.isoformat(), '--to-utc',now.isoformat(),
             '--periods',period, '--out-dir',str(folder)]
        outcome=subprocess.run(cmd,cwd=ROOT,env=os.environ.copy(),capture_output=True,text=True,timeout=600)
        if outcome.returncode:
            raise RuntimeError('HISTORY_FAILED_'+period+'_'+str(outcome.returncode))
        stamp.write_text(str(now.timestamp()))

def current_frames(folder,account_id,symbol_id):
    frames={}
    for tf,period in PERIODS.items():
        path=folder/(tf+'.csv')
        if path.exists():
            m=json.loads(path.with_name(path.name+'.meta.json').read_text())
            if int(m['account_id'])!=account_id or int(m['symbol_id'])!=symbol_id or m['period']!=period:
                raise ValueError('MIXED_ACCOUNT_OR_SYMBOL_DATA_'+tf)
            frames[tf]=parse_ctrader_csv(path,expected_period=period)
    return frames

def daily_baseline(account_id,balance,now,folder=STATE):
    folder.mkdir(parents=True,exist_ok=True)
    path=folder/'day_start_usd.json'; date=now.date().isoformat()
    if path.exists():
        data=json.loads(path.read_text(encoding='utf8'))
        if data.get('account_id')==account_id and data.get('day_utc')==date:
            return float(data['start_balance_usd'])
    state={'day_utc':date,'account_id':account_id,'start_balance_usd':float(balance)}
    tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(state));tmp.replace(path)
    return float(balance)

def approve_candidates(candidates,snapshot,baseline,now,cfg):
    symbol=snapshot['symbol']; q=snapshot['quote']
    bs=BrokerSymbol(int(symbol['symbol_id']),symbol['symbol_name'],int(symbol['min_volume']),
                    int(symbol['step_volume']),int(symbol['max_volume']),int(symbol['lot_size']),
                    int(symbol['digits']),bool(symbol['trade_allowed']))
    quote=Quote(float(q['bid']),float(q['ask']),datetime.fromtimestamp(q['timestamp_ms']/1000,timezone.utc))
    account=Account(snapshot['account_id'],False,float(snapshot['balance_usd']),baseline,
                    int(snapshot['open_positions'])+int(snapshot['pending_orders']),snapshot['currency'])
    active=configured_strategies()
    authorized={sid for sid in active}
    picks=[];rejections=[]
    for c in candidates:
        if c.strategy_id not in authorized:continue
        spec=SPECS[c.strategy_id]
        this_cfg={**cfg,'approved_strategy_ids':sorted(authorized),'enabled_strategy_ids':sorted(authorized),
                  'max_sl_price_usd':min(float(spec.stop_cap), float(cfg.get('max_swing_sl_price_usd',250)))}
        new_c=replace(c,symbol_name=symbol['symbol_name'])
        result=assess(new_c,quote,account,bs,this_cfg,now)
        if result.status=='DEMO_READY':picks.append((new_c,result,this_cfg))
        else:rejections.append({'strategy':c.strategy_id,'reason':result.reason})
    picks.sort(key=lambda z:(-z[1].evidence['score'],z[0].strategy_id))
    if len({x[0].side for x in picks})>1:return None,rejections+[{'reason':'CONFLICTING_STRATEGY_DIRECTIONS'}]
    return (picks[0] if picks else None),rejections

def rotate_token_if_needed(force=False):
    """Refresh on startup / each 12h; failure stops execution rather than using stale keys."""
    if not all(os.getenv(k) for k in ('CTRADER_REFRESH_TOKEN','CTRADER_CLIENT_ID','CTRADER_CLIENT_SECRET')):
        return False
    stamp=STATE/'token_refresh_at.txt'
    if not force and stamp.exists() and time.time()-float(stamp.read_text())<12*3600:
        return False
    tok=refresh_token(os.environ['CTRADER_CLIENT_ID'],os.environ['CTRADER_CLIENT_SECRET'],os.environ['CTRADER_REFRESH_TOKEN'])
    save_tokens(ROOT/'.env',tok)
    stamp.parent.mkdir(parents=True,exist_ok=True);stamp.write_text(str(time.time()))
    return True

def one_cycle(folder=ROOT/'data/ctrader_live', acquire=True):
    now=datetime.now(timezone.utc)
    if acquire: acquire_candles(folder,now)
    frames=current_frames(folder,int(os.environ['CTRADER_ACCOUNT_ID']),int(os.environ['CTRADER_SYMBOL_ID']))
    proposals,errors=evaluate_latest(frames,now)
    proposals,context_audit=apply_context(proposals,frames)
    if context_audit:
        # Bounded telemetry: one summary per cycle, not 75 full SMC snapshots per minute.
        event('CONTEXT_LAYERS', checked=len(context_audit),
              smc_agree=sum(1 for x in context_audit if x.get('smc_agrees')),
              vp_agree=sum(1 for x in context_audit if x.get('vp_agrees')),
              volume_unavailable=sum(1 for x in context_audit if x.get('vp',{}).get('status')=='UNAVAILABLE'))
    event('SCAN',enabled=len(configured_strategies()),candidates=len(proposals),errors=errors)
    if not proposals:return {'status':'NO_CANDIDATES'}
    ledger=IntentStore(STATE/'demo_intents.sqlite')
    if any(status in ('SUBMIT_UNCERTAIN','CONFIRMED') for _,status in ledger.all()):
        event('HALT_UNRESOLVED_ORDER');return {'status':'HALT_UNRESOLVED_ORDER'}
    resp=worker(['-m','ctrader.demo_worker','--task','snapshot','--symbol-id',os.environ['CTRADER_SYMBOL_ID'],
                 '--ledger',str(STATE/'demo_intents.sqlite')])
    snap=resp['snapshot']
    if snap['open_positions'] or snap['pending_orders']:
        event('BROKER_EXPOSURE_PRESENT',positions=snap['open_positions'],orders=snap['pending_orders'])
        return {'status':'BROKER_EXPOSURE_PRESENT'}
    if not snap['full_access'] or snap['limited_risk'] or snap['currency']!='USD':
        return {'status':'BROKER_ACCOUNT_NOT_SUPPORTED'}
    baseline=daily_baseline(snap['account_id'],snap['balance_usd'],now)
    chosen,rejected=approve_candidates(proposals,snap,baseline,now,load_configuration())
    event('RISK_GATE',approved=bool(chosen),rejections=rejected[:30])
    if not chosen:return {'status':'NO_RISK_APPROVED'}
    cand,dec,cfg=chosen
    payload={'candidate':{
        **{k:v for k,v in asdict(cand).items() if k!='signal_bar_end_utc'},
        'signal_bar_end_utc':cand.signal_bar_end_utc.isoformat()},
        'config':cfg,'order_id':dec.order['client_order_id'],
        'day_start_balance_usd':baseline}
    STATE.mkdir(parents=True,exist_ok=True)
    tmp=STATE/'candidate_pending.tmp';dst=STATE/'candidate_pending.json'
    tmp.write_text(json.dumps(payload,ensure_ascii=False));tmp.replace(dst)
    result=worker(['-m','ctrader.demo_worker','--task','submit','--symbol-id',os.environ['CTRADER_SYMBOL_ID'],
                   '--intent-file',str(dst),'--ledger',str(STATE/'demo_intents.sqlite')],timeout=70)
    event('BROKER_RESULT',**result)
    notify_owner('🥇 GoldStation DEMO\n'+str(result.get('event'))+'\n'+str(cand.strategy_id)+' '+cand.side+'\n'+str(result.get('client_order_id',''))[:35])
    return result

def main():
    p=argparse.ArgumentParser();p.add_argument('--once',action='store_true')
    p.add_argument('--poll-seconds',type=int,default=30)
    p.add_argument('--skip-refresh',action='store_true',help='Diagnostics only; use valid access token')
    a=p.parse_args()
    if a.poll_seconds<20:raise SystemExit('poll-seconds >=20')
    load_env(ROOT/'.env')
    keys=('CTRADER_CLIENT_ID','CTRADER_CLIENT_SECRET','CTRADER_ACCOUNT_ID',
          'CTRADER_ACCESS_TOKEN','CTRADER_REFRESH_TOKEN','CTRADER_SYMBOL_ID')
    missing=[k for k in keys if not os.environ.get(k)]
    if missing:raise SystemExit('Missing keys in private .env: '+', '.join(missing))
    if os.environ.get('CTRADER_DEMO_CONFIRMED')!='YES' or os.environ.get('CTRADER_ALLOW_DEMO_ORDER')!='YES':
        raise SystemExit('DEMO consent flags must be YES in .env')
    STATE.mkdir(parents=True,exist_ok=True)
    # Portable one-instance lock: mkdir holds until normal exit. Stale locks are not auto-recovered.
    lock=STATE/'demo_instance.lock'
    try: lock.mkdir()
    except FileExistsError:raise SystemExit('Already running or stale lock: remove after verifying no runner is active')
    try:
        event('START_DEMO',available_strategies=len(configured_strategies()),live_endpoint=False)
        start_optional()
        if not a.skip_refresh:rotate_token_if_needed()
        while True:
            try:one_cycle()
            except (RuntimeError,ValueError,subprocess.TimeoutExpired,KeyError) as exc:
                event('CYCLE_ERROR',reason=str(exc)[:220])
            if a.once:break
            if not a.skip_refresh:
                try:rotate_token_if_needed()
                except Exception as exc:event('TOKEN_REFRESH_ERROR',reason=type(exc).__name__)
            time.sleep(a.poll_seconds)
    finally:
        lock.rmdir()
if __name__=='__main__':main()
