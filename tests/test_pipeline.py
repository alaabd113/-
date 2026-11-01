import unittest,tempfile,os
from datetime import datetime,timedelta,timezone
from pathlib import Path
from dataclasses import replace
from engine.pipeline import Quote,Candidate,Account,BrokerSymbol,assess
from engine.intent_store import IntentStore
from ctrader.protocol import decode_trendbar,relative_protection,normalize_volume
from ctrader.demo_client import DemoClient,send_ready_demo_order

class T(unittest.TestCase):
 def setUp(self):
  self.now=datetime(2026,11,1,12,1,tzinfo=timezone.utc)
  self.c=Candidate('PO3_FROZEN_M5','XAUUSD','M5',self.now-timedelta(seconds=30),'BUY',4000.,4010.,True,True,'trend',{'structure':True,'liquidity':True,'displacement':True,'higher_timeframe':True,'session':True,'entry_confirmation':True})
  self.q=Quote(4003.8,4004.0,self.now-timedelta(seconds=2))
  self.a=Account(123,False,10000,10000)
  self.s=BrokerSymbol(9,'XAUUSD',100,100,100000,10000)
  self.cfg={'mode':'OFFLINE','allow_demo_order':False,'approved_strategy_ids':['PO3_FROZEN_M5'],'max_price_age_sec':10,'max_spread_price_usd':0.6,'max_sl_price_usd':10.,'min_rr':1.5,'max_positions':1,'daily_loss_limit_pct':1.5,'risk_pct_per_trade':0.25}
 def check(self,c=None,q=None,a=None,s=None,cfg=None):return assess(c or self.c,q or self.q,a or self.a,s or self.s,cfg or self.cfg,self.now)
 def test_shadow_valid(self):
  x=self.check();self.assertEqual(x.status,'SHADOW');self.assertEqual(x.grade,'A');self.assertLessEqual(x.order['worst_risk_usd'],25)
 def test_demo_optin(self):
  c={**self.cfg,'mode':'DEMO','allow_demo_order':True};self.assertEqual(self.check(cfg=c).status,'DEMO_READY')
 def test_live_blocked(self):self.assertEqual(self.check(a=replace(self.a,is_live=True)).reason,'LIVE_ACCOUNT_NOT_ALLOWED')
 def test_stale_quote(self):self.assertEqual(self.check(q=replace(self.q,timestamp_utc=self.now-timedelta(seconds=30))).reason,'STALE_QUOTE')
 def test_high_spread(self):self.assertEqual(self.check(q=replace(self.q,ask=4005)).reason,'SPREAD_TOO_WIDE')
 def test_bad_stop(self):self.assertEqual(self.check(c=replace(self.c,stop_price=4010)).reason,'INVALID_SL_TP')
 def test_wide_stop(self):self.assertEqual(self.check(c=replace(self.c,stop_price=3990)).reason,'STOP_OVER_POLICY_CAP')
 def test_min_volume(self):self.assertEqual(self.check(s=replace(self.s,min_volume=2000)).reason,'MIN_VOLUME_EXCEEDS_RISK_BUDGET')
 def test_disapproved(self):self.assertEqual(self.check(c=replace(self.c,strategy_id='UNKNOWN')).reason,'STRATEGY_UNAPPROVED')
 def test_weak_evidence(self):
  x=self.check(c=replace(self.c,signals={'structure':True}));self.assertEqual(x.status,'SHADOW')
 def test_daily_loss(self):self.assertEqual(self.check(a=replace(self.a,equity_usd=9500)).reason,'DAILY_LOSS_CIRCUIT_BREAKER')
 def test_aware_utc(self):self.assertEqual(self.check(c=replace(self.c,signal_bar_end_utc=self.now.replace(tzinfo=None))).status,'REJECT')
 def test_ids_stable(self):self.assertEqual(self.check().order['client_order_id'],self.check().order['client_order_id'])
 def test_intent_idempotency(self):
  with tempfile.TemporaryDirectory() as td:
   store=IntentStore(Path(td)/'a.db');o=self.check().order
   self.assertTrue(store.reserve(o));self.assertFalse(store.reserve(o));self.assertEqual(store.all()[0][1],'SUBMIT_UNCERTAIN')
   store.update(o['client_order_id'],'CONFIRMED');self.assertFalse(store.reserve(o))
 def test_relative_protection(self):self.assertEqual(relative_protection(4004,4000,4010,'BUY'),{'relativeStopLoss':400000,'relativeTakeProfit':600000})
 def test_volume_rounding(self):self.assertEqual(normalize_volume(175,100,50,500),150)
 def test_order_locked_without_sdk(self):
  c=DemoClient('bars',123,'token','id','secret',9)
  x=self.check().order
  self.assertEqual(send_ready_demo_order(c,x,{}, {},':memory:',True)[1],'LEGACY_ORDER_ROUTE_DISABLED_USE_DEMO_WORKER')
class BAR:
 low=400000000;deltaOpen=200000;deltaHigh=400000;deltaClose=100000;volume=66;utcTimestampInMinutes=29880000
class TBar(unittest.TestCase):
 def test_delta_prices(self):
  b=decode_trendbar(BAR());self.assertEqual((b['open'],b['high'],b['low'],b['close']),(4002.,4004.,4000.,4001.))
if __name__=='__main__':unittest.main()
