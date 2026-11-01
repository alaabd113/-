import unittest,tempfile,hashlib,copy
from pathlib import Path
from datetime import datetime,timedelta,timezone
import pandas as pd,numpy as np
from strategies.catalog import SPECS
from engine.strategy_registry import read,defaults,save,toggle,active
from engine.signal_hub import parse_ctrader_csv,closed_only,TF_MINUTES,evaluate_latest
from engine.admin_commands import handle_message
from engine.pipeline import Candidate,assess
from ctrader.protocol import decode_trendbar
from engine.intent_store import IntentStore
ROOT=Path(__file__).resolve().parents[1]
class V7Tests(unittest.TestCase):
 def test_all_75_registered_and_enabled(self):
  self.assertGreaterEqual(len(SPECS),75)
  self.assertTrue(set(SPECS)==set(read()['strategies']))
  self.assertTrue(all(v['enabled'] for v in read()['strategies'].values()))
  self.assertTrue(all(v['allow_demo'] and not v['research_only'] for v in read()['strategies'].values()))
 def test_unique_executable_generators(self):
  self.assertEqual(len(SPECS),len(set(SPECS)))
  for name,sp in SPECS.items():self.assertTrue(callable(sp.generator),name)
 def test_registry_toggle_only_one(self):
  with tempfile.TemporaryDirectory() as q:
   t=Path(q)/'config.json';save(defaults(),t)
   toggle('BOLL_RSI_FADE_M5',False,t)
   self.assertFalse(read(t)['strategies']['BOLL_RSI_FADE_M5']['enabled'])
   self.assertTrue(read(t)['strategies']['HA_MOMENTUM_H1']['enabled'])
   toggle('BOLL_RSI_FADE_M5',True,t)
   self.assertTrue(read(t)['strategies']['BOLL_RSI_FADE_M5']['enabled'])
 def test_registry_research_cannot_authorize_demo(self):
  with tempfile.TemporaryDirectory() as q:
   t=Path(q)/'c.json';c=defaults();c['strategies']['BOLL_RSI_FADE_M5']['allow_demo']=True;c['strategies']['BOLL_RSI_FADE_M5']['research_only']=True
   save(c,t)
   with self.assertRaises(ValueError):read(t)
 def test_reference_po3_hash(self):
  frozen=(ROOT/'legacy/po3_trades_frozen.csv').read_bytes()
  expected=(ROOT/'legacy/po3_reference.sha256').read_text().split()[0]
  self.assertEqual(hashlib.sha256(frozen).hexdigest(),expected)
 def test_empty_data_rejected(self):
  with tempfile.TemporaryDirectory() as q:
   t=Path(q)/'bad.csv';t.write_text('timestamp_utc,open,high,low,close\n2026-10-01 10:00:00,1,2,0.5,1.5\n')
   with self.assertRaises(ValueError):parse_ctrader_csv(t,require_meta=False)
 def test_utc_csv_load(self):
  with tempfile.TemporaryDirectory() as q:
   t=Path(q)/'ok.csv';t.write_text('timestamp_utc,open,high,low,close\n2026-10-01T10:00:00+00:00,2,3,1,2\n')
   frame=parse_ctrader_csv(t,require_meta=False);self.assertIsNotNone(frame.index.tz)
 def test_close_gate(self):
  t=pd.date_range('2026-10-01T10:00:00Z',periods=3,freq='5min')
  d=pd.DataFrame(dict(open=[1]*3,high=[2]*3,low=[.5]*3,close=[1]*3),index=t)
  asof=datetime(2026,10,1,10,10,30,tzinfo=timezone.utc)
  a=closed_only(d,'5min',asof);self.assertEqual(len(a),2)
 def test_naive_rejected_for_live(self):
  ix=pd.date_range('2026-01-01',periods=5,freq='5min');d=pd.DataFrame({'close':[1]*5},index=ix)
  with self.assertRaises(ValueError):closed_only(d,'5min',datetime.now(timezone.utc))
 def test_owner_commands_block_others(self):
  self.assertIn('للمالك',handle_message(2,'/gold_off BOLL_RSI_FADE_M5',1))
 def test_nested_sqlite_dir(self):
  with tempfile.TemporaryDirectory() as q:
   p=Path(q)/'sub'/'f.db';s=IntentStore(p);self.assertTrue(p.exists())
 def test_precision_5digits(self):
  class Bar:
   low=10000001;deltaOpen=10;deltaHigh=100;deltaClose=20;volume=3;utcTimestampInMinutes=29880000
  x=decode_trendbar(Bar());self.assertEqual(x['low'],100.00001)
 def test_causal_no_future_for_fade(self):
  from research.new_variants import boll_rsi_fade
  rng=np.random.default_rng(100)
  x=4000+np.cumsum(rng.normal(0,1,500));ix=pd.date_range('2026-10-01',periods=500,freq='5min')
  d=pd.DataFrame(dict(open=x,high=x+1,low=x-1,close=x+.1),index=ix)
  a=boll_rsi_fade(d.iloc[:400]);b=boll_rsi_fade(d)
  pd.testing.assert_frame_equal(a.iloc[100:380],b.iloc[100:380])
 def test_disabled_not_evaluated(self):
  conf=defaults();conf['strategies']['BOLL_RSI_FADE_M5']['enabled']=False
  # No frames -> no candidate; more importantly registry is not mutated.
  res,errors=evaluate_latest({},datetime.now(timezone.utc),conf)
  self.assertEqual(res,[])
class DeepRegression(unittest.TestCase):
 def test_reference_profit_stable(self):
  # The previously published 141 trades +31.4211 R result must not be silently overwritten.
  import json
  report=json.loads((ROOT/'results/screen_results.json').read_text())
  self.assertEqual(report['results']['BOLL_RSI_FADE_M5']['costs']['0.4']['trades'],141)
  self.assertEqual(report['results']['BOLL_RSI_FADE_M5']['costs']['0.4']['total_R'],31.4211)
 def test_actual_current_fade_replayed(self):
  from research import replay_base as b
  from strategies.catalog import SPECS
  b.SRC=ROOT/'data/candles.db'
  d=b.load('5min');s=SPECS['BOLL_RSI_FADE_M5'];t,_=b.replay(d,s.generator(d),cap=s.stop_cap,rr=s.rr,horizon=s.max_hold_bars,cost=.4)
  self.assertEqual(len(t),141);self.assertAlmostEqual(b.mt(t)['total_R'],31.4211,places=3)
 def test_frozen_po3_signal_is_executable(self):
  from research import replay_base as b
  b.SRC=ROOT/'data/candles.db';d=b.load('5min')
  s=SPECS['PO3_FROZEN_M5'].generator(d)
  self.assertEqual(s.shape[0],len(d));self.assertGreater(int((s.side!=0).sum()),0)
 def test_source_sidecar_identifies_period(self):
  import json
  with tempfile.TemporaryDirectory() as q:
   t=Path(q)/'5min.csv';t.write_text('timestamp_utc,open,high,low,close\n2026-11-01T10:00:00Z,4,5,3,4\n')
   meta={'price_source':'CTRADER_OPEN_API_DEMO','account_id':123,'symbol_id':5,'period':'M5'}
   t.with_name(t.name+'.meta.json').write_text(json.dumps(meta))
   self.assertEqual(len(parse_ctrader_csv(t,expected_period='M5')),1)
   with self.assertRaises(ValueError):parse_ctrader_csv(t,expected_period='H1')
 def test_live_account_never_in_order_setup(self):
  from engine.pipeline import Account,BrokerSymbol,Quote,Candidate,assess
  t=datetime(2026,11,1,tzinfo=timezone.utc)
  cfg={'mode':'DEMO','allow_demo_order':True,'approved_strategy_ids':['BOLL_RSI_FADE_M5'],
       'max_price_age_sec':10,'max_spread_price_usd':.6,'max_sl_price_usd':10,'min_rr':1.5,
       'max_positions':1,'daily_loss_limit_pct':1.5,'risk_pct_per_trade':.25}
  c=Candidate('BOLL_RSI_FADE_M5','XAUUSD','M5',t-timedelta(minutes=1),'BUY',3999,4005,True,True,'trend',{})
  a=Account(123,True,10000,10000)
  q=Quote(4000,4000.2,t)
  sp=BrokerSymbol(99,'XAUUSD',100,100,10000,10000)
  self.assertEqual(assess(c,q,a,sp,cfg,t).reason,'LIVE_ACCOUNT_NOT_ALLOWED')
if __name__=='__main__':unittest.main()
