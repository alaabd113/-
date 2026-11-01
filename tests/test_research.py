import unittest
from pathlib import Path
import pandas as pd, numpy as np
from research import new_variants as v,replay_base as b
b.SRC=Path(__file__).resolve().parents[1]/'data/candles.db'
class TResearch(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.d=b.load('5min').iloc[:800].copy()
 def test_source_is_ctrader(self):self.assertEqual(set(self.d.source.unique()),{'ctrader'})
 def test_source_ohlc(self):self.assertTrue(((self.d.low<=self.d.open)&(self.d.high>=self.d.close)).all())
 def test_future_invariance(self):
  fn=v.ema9_rsi
  s1=fn(self.d.iloc[:620]);s2=fn(self.d)
  pd.testing.assert_frame_equal(s1.iloc[100:610],s2.iloc[100:610],check_exact=False,rtol=1e-12,atol=1e-12)
 def test_no_same_bar_entry(self):
  d=self.d;s=v.ema9_rsi(d);tr,_=b.replay(d,s,10,1.8,40,0.4)
  for t in tr:
   i=d.index.get_loc(pd.Timestamp(t['entry_time']));self.assertGreater(i,0)
   self.assertNotEqual(int(s.side.iloc[i-1]),0)
 def test_cost_decreases_return_for_fixed_trades(self):
  d=self.d;s=v.ema9_rsi(d);p,_=b.replay(d,s,10,1.8,40,0.4);q,_=b.replay(d,s,10,1.8,40,1.0)
  self.assertEqual([t['entry_time'] for t in p],[t['entry_time'] for t in q])
  self.assertLess(sum(t['net_R'] for t in q),sum(t['net_R'] for t in p))
 def test_signal_tf_all(self):
  for key in ['HA_RSI_CROSS_M5','BOLL_RSI_FADE_M5','ATR_COMPRESSION_M5','NR7_BREAK_M5']:
   s=v.CONFIG[key][1](self.d);self.assertEqual(len(s),len(self.d));self.assertTrue(s.side.isin([-1,0,1]).all())
 def test_loss_first(self):
  d=pd.DataFrame({'open':[10,10,10,10,10],'high':[11,11,13,11,11],'low':[9,9,7,9,9],'close':[10,10,10,10,10]},index=pd.date_range('2025-01-01',periods=5,freq='5min'))
  sig=b.empty(d);sig.loc[d.index[1],['side','stop','target']]=[1,9,12]
  # replay starts at 100 bars -> create longer frame to ensure it can enter.
  dd=pd.concat([pd.concat([d.iloc[[0]]]*110,ignore_index=True),d],ignore_index=True)
  dd.index=pd.date_range('2025-01-01',periods=len(dd),freq='5min');ss=b.empty(dd);ss.loc[dd.index[111],['side','stop','target']]=[1,9,12]
  tr,_=b.replay(dd,ss,cap=10,rr=2,horizon=5,cost=0.4)
  self.assertEqual(len(tr),1)
  self.assertEqual(tr[0]['exit_reason'],'STOP')
if __name__=='__main__':unittest.main()
