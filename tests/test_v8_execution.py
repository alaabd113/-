"""V8 offline SDK-state tests; none sends a network request or real trade."""
import json,os,tempfile,unittest
from pathlib import Path
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace
from unittest.mock import patch
from ctrader.demo_worker import DemoWorker
from ctrader.local_secrets import save_tokens,load_env
from ctrader.protocol import relative_protection
from engine.pipeline import Candidate,Quote,Account,BrokerSymbol,assess
from engine.intent_store import IntentStore
from scripts.run_demo import daily_baseline, approve_candidates, configured_strategies, load_configuration, period_due

class FakeReq:
    def __init__(self):self.__dict__={}
class FakeEnum:
    @staticmethod
    def Value(s):return 5 if s=='MARKET_RANGE' else 1
class FakeOA:
    @staticmethod
    def ProtoOANewOrderReq():return FakeReq()
class V8Execution(unittest.TestCase):
    def snapshot(self):
        return {'account_id':123,'is_live':False,'currency':'USD','balance_usd':10000.0,
          'full_access':True,'limited_risk':False,'open_positions':0,'pending_orders':0,
          'symbol':{'symbol_id':1,'symbol_name':'XAUUSD','min_volume':100,'max_volume':100000,
          'step_volume':100,'lot_size':10000,'digits':2,'trade_allowed':True,'short_allowed':True,
          'sl_distance':0,'tp_distance':0,'distance_set_in':1},
          'quote':{'bid':4000.0,'ask':4000.20,'timestamp_ms':int(datetime.now(timezone.utc).timestamp()*1000)}}
    def candidate(self):
        now=datetime.now(timezone.utc)
        return Candidate('BOLL_RSI_FADE_M5','XAUUSD','M5',now-timedelta(seconds=15),
                         'BUY',3995.,4012.,True,True,'TREND',{
                         'structure':True,'liquidity':True,'displacement':True,
                         'higher_timeframe':True,'session':True,'entry_confirmation':True})
    def make_payload(self,temp,snap=None):
        snap=snap or self.snapshot();now=datetime.now(timezone.utc)
        from dataclasses import asdict
        c=self.candidate();cfg=load_configuration()
        picks,denials=approve_candidates([c],snap,10000,now,cfg)
        self.assertIsNotNone(picks,str(denials))
        cand,dec,cfg=picks
        row=asdict(cand);row['signal_bar_end_utc']=cand.signal_bar_end_utc.isoformat()
        p=Path(temp)/'intent.json'
        p.write_text(json.dumps({'candidate':row,'config':cfg,'order_id':dec.order['client_order_id'],
                                 'day_start_balance_usd':10000}))
        return p,dec.order['client_order_id']
    def fake_worker(self,temp,intent_file):
        w=DemoWorker.__new__(DemoWorker)
        w.account_id=123;w.symbol_id=1;w.task='submit';w.intent_path=str(intent_file)
        w.ledger_path=str(Path(temp)/'ledger.db')
        w.saw_order=False;w.finish_status=None;w.fields={};w.parts=set()
        w.oa=FakeOA();w.om=SimpleNamespace(ProtoOAOrderType=FakeEnum(),ProtoOATradeSide=FakeEnum())
        w.sent=[];w.send=lambda req:w.sent.append(req)
        w.complete=lambda status,result=None:setattr(w,'finish_status',status)
        return w
    def test_all_75_demo_switches_are_user_controllable(self):
        a=configured_strategies();self.assertGreaterEqual(len(a),75)
    def test_cannot_execute_without_operator_flags(self):
        with tempfile.TemporaryDirectory() as td:
            snap=self.snapshot();p,_=self.make_payload(td,snap);w=self.fake_worker(td,p)
            with patch.dict(os.environ,{'CTRADER_ALLOW_DEMO_ORDER':'NO','CTRADER_DEMO_CONFIRMED':'NO'}):
                w._submit_with_fresh_quote(snap)
            self.assertEqual(w.finish_status,'ORDER_FLAGS_NOT_ENABLED');self.assertFalse(w.sent)
    def test_send_protected_market_range_and_reserve_once(self):
        with tempfile.TemporaryDirectory() as td:
            snap=self.snapshot();p,oid=self.make_payload(td,snap);w=self.fake_worker(td,p)
            with patch.dict(os.environ,{'CTRADER_ALLOW_DEMO_ORDER':'YES','CTRADER_DEMO_CONFIRMED':'YES'}):
                w._submit_with_fresh_quote(snap)
                self.assertTrue(w.saw_order);self.assertEqual(len(w.sent),1)
                x=w.sent[0];self.assertEqual(x.clientOrderId,oid)
                self.assertGreater(x.relativeStopLoss,0);self.assertGreater(x.relativeTakeProfit,0)
                self.assertEqual(x.baseSlippagePrice,4000.2)
                self.assertEqual(IntentStore(w.ledger_path).all()[0][1],'SUBMIT_UNCERTAIN')
                w2=self.fake_worker(td,p);w2._submit_with_fresh_quote(snap)
                self.assertEqual(w2.finish_status,'DUPLICATE_ORDER');self.assertFalse(w2.sent)
    def test_open_position_blocks(self):
        with tempfile.TemporaryDirectory() as td:
            snap=self.snapshot();p,_=self.make_payload(td,snap);snap['open_positions']=1;w=self.fake_worker(td,p)
            with patch.dict(os.environ,{'CTRADER_ALLOW_DEMO_ORDER':'YES','CTRADER_DEMO_CONFIRMED':'YES'}):w._submit_with_fresh_quote(snap)
            self.assertEqual(w.finish_status,'BROKER_ALREADY_HAS_EXPOSURE')
    def test_unsupported_risk_account_blocks(self):
        w=DemoWorker.__new__(DemoWorker)
        w.fields={};w.parts={'trader','assets','symbol','name','positions','quote'}
        w.fields={'balance':100,'deposit_asset_id':7,'asset_map':{7:'EUR'},'full_access':True,'limited_risk':False,
                  'open_positions':0,'pending_orders':0,'symbol_name':'XAUUSD','symbol':self.snapshot()['symbol'],
                  'quote':self.snapshot()['quote']}
        w.account_id=123;w.demo_verified=True;w.task='snapshot';w.finish_status=None
        w.complete=lambda status,result=None:setattr(w,'finish_status',status)
        w._maybe_ready();self.assertEqual(w.finish_status,'UNSUPPORTED_ACCOUNT_CURRENCY')
    def test_invalid_broker_minimum_distance_blocks(self):
        with tempfile.TemporaryDirectory() as td:
            snap=self.snapshot();p,_=self.make_payload(td,snap);snap['symbol']['sl_distance']=2000;w=self.fake_worker(td,p)
            with patch.dict(os.environ,{'CTRADER_ALLOW_DEMO_ORDER':'YES','CTRADER_DEMO_CONFIRMED':'YES'}):w._submit_with_fresh_quote(snap)
            self.assertEqual(w.finish_status,'BROKER_MIN_STOP_DISTANCE')
    def test_higher_cost_quote_no_longer_matches_order_id_does_not_submit(self):
        with tempfile.TemporaryDirectory() as td:
            snap=self.snapshot();p,_=self.make_payload(td,snap);snap['quote']['bid']=4004.2;snap['quote']['ask']=4004.4
            w=self.fake_worker(td,p)
            with patch.dict(os.environ,{'CTRADER_ALLOW_DEMO_ORDER':'YES','CTRADER_DEMO_CONFIRMED':'YES'}):w._submit_with_fresh_quote(snap)
            self.assertEqual(w.finish_status,'DECISION_RR_TOO_SMALL')
    def test_daily_baseline_is_not_reset_on_restart(self):
        with tempfile.TemporaryDirectory() as td:
            t=datetime(2026,11,1,tzinfo=timezone.utc)
            self.assertEqual(daily_baseline(99,10000,t,Path(td)),10000)
            self.assertEqual(daily_baseline(99,9500,t,Path(td)),10000)
            self.assertEqual(daily_baseline(99,9500,t+timedelta(days=1),Path(td)),9500)
    def test_secrets_are_written_private(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'.env';p.write_text('CTRADER_CLIENT_ID=id\n')
            save_tokens(p,{'accessToken':'new.access-token','refreshToken':'new.refresh-token'})
            self.assertEqual(p.stat().st_mode&0o777,0o600)
            with patch.dict(os.environ,{},clear=True):
                load_env(p);self.assertEqual(os.environ['CTRADER_ACCESS_TOKEN'],'new.access-token')
    def test_quote_timeout_blocks(self):
        snap=self.snapshot();snap['quote']['timestamp_ms']-=60_000
        cand=self.candidate();choice,errors=approve_candidates([cand],snap,10000,datetime.now(timezone.utc),load_configuration())
        self.assertIsNone(choice);self.assertIn(errors[0]['reason'],('STALE_QUOTE','FUTURE_SIGNAL'))
    def test_live_broker_account_rejected_by_core(self):
        now=datetime.now(timezone.utc);c=self.candidate();q=Quote(4000,4000.2,now)
        broker=BrokerSymbol(1,'XAUUSD',100,100,100000,10000)
        res=assess(c,q,Account(123,True,10000,10000),broker,load_configuration(),now)
        self.assertEqual(res.reason,'LIVE_ACCOUNT_NOT_ALLOWED')
    def test_relative_bracket_sides(self):
        self.assertEqual(relative_protection(4000,3995,4010,'BUY'),{'relativeStopLoss':500000,'relativeTakeProfit':1000000})
        self.assertEqual(relative_protection(4000,4005,3990,'SELL'),{'relativeStopLoss':500000,'relativeTakeProfit':1000000})
if __name__=='__main__':unittest.main()
