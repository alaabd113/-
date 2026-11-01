"""V9 isolated tests: deterministic structure, nonrepainting, measured volume only, opt-in gates."""
import json,tempfile,unittest
from datetime import datetime,timezone
from pathlib import Path
import numpy as np
import pandas as pd
from engine.smc_context import scan,latest
from engine.volume_profile import compute
from engine.context_integration import apply
from engine.signal_hub import parse_ctrader_csv
from engine.pipeline import Candidate

class TestV9Context(unittest.TestCase):
    def frame(self, n=100):
        times=pd.date_range('2026-01-01',periods=n,freq='5min',tz='UTC')
        ix=np.arange(n)
        close=4000+ix*.12+np.sin(ix/3)*3
        return pd.DataFrame({'open':close-.2,'high':close+1.2,'low':close-1.2,'close':close,'volume':np.full(n,20.)},index=times)
    def candidate(self,df):
        return Candidate('TEST','XAUUSD','M5',(df.index[-1]+pd.Timedelta(minutes=5)).to_pydatetime(),'BUY',3990.,4010.,True,True,'research',{})
    def test_prefix_past_unchanged(self):
        df=self.frame();a=scan(df.iloc[:80]);b=scan(df)
        self.assertEqual(a,b[:80])
    def test_confirmed_pivot_not_backdated(self):
        df=self.frame();out=scan(df,pivot_span=3)
        self.assertEqual(out[0].last_swing_high,None)
        self.assertEqual(out[0].last_swing_low,None)
    def test_fvg_formed_only_at_current_bar(self):
        df=self.frame(10)
        df.iloc[0,df.columns.get_loc('high')]=4000.
        df.iloc[0,df.columns.get_loc('low')]=3998.
        df.iloc[0,df.columns.get_loc('open')]=3999.
        df.iloc[0,df.columns.get_loc('close')]=3999.
        df.iloc[2,df.columns.get_loc('low')]=4010.
        df.iloc[2,df.columns.get_loc('high')]=4014.
        df.iloc[2,df.columns.get_loc('open')]=4011.
        df.iloc[2,df.columns.get_loc('close')]=4012.
        a=scan(df)
        self.assertIsNone(a[1].fvg)
        self.assertEqual(a[2].fvg,'BULL')
    def test_volume_histogram_conserves_total(self):
        d=self.frame()
        r=compute(d,lookback=80,rows=32)
        self.assertAlmostEqual(r.total_tick_volume,1600,places=6)
        self.assertLessEqual(r.val,r.poc)
        self.assertLessEqual(r.poc,r.vah)
    def test_volume_required(self):
        with self.assertRaisesRegex(ValueError,'NO_VOLUME_DATA'):
            compute(self.frame().drop(columns='volume'))
    def test_zero_volume_forbidden(self):
        d=self.frame();d['volume']=0
        with self.assertRaises(ValueError):compute(d)
    def test_cTrader_csv_preserves_volumes(self):
        d=self.frame(12);d=d.reset_index().rename(columns={'index':'timestamp_utc'})
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'m5.csv';d.to_csv(p,index=False)
            m={'account_id':13,'symbol_id':7,'period':'M5','price_source':'CTRADER_OPEN_API_DEMO'}
            p.with_name(p.name+'.meta.json').write_text(json.dumps(m))
            read=parse_ctrader_csv(p,expected_period='M5')
            self.assertIn('volume',read.columns)
            self.assertAlmostEqual(read['volume'].sum(),240)
    def test_no_context_gates_does_not_change_candidates(self):
        d=self.frame();c=self.candidate(d)
        result,audit=apply([c],{'5min':d},{'smc_gate':False,'vp_gate':False,'vp_lookback':50})
        self.assertEqual(result,[c]);self.assertEqual(len(audit),1)
    def test_vp_gate_fails_closed_missing_volume(self):
        d=self.frame().drop(columns='volume');c=self.candidate(d)
        a,b=apply([c],{'5min':d},{'smc_gate':False,'vp_gate':True,'vp_lookback':40})
        self.assertEqual(a,[])
        self.assertEqual(b[0]['vp']['status'],'UNAVAILABLE')
    def test_future_or_forming_candle_must_not_change_context(self):
        df=self.frame();c=self.candidate(df)
        conf={'smc_gate':False,'vp_gate':False,'vp_lookback':50}
        old=apply([c],{'5min':df},conf)[1][0]
        # Bar starts at signal closing time and is NOT closed at the signal time.
        bad=df.iloc[-1:].copy()
        bad.index=[df.index[-1]+pd.Timedelta(minutes=5)]
        bad[['open','close','low','high']]=[3999.,3999.,3998.,7000.]
        bad['volume']=1_000_000
        inflated=pd.concat([df,bad])
        new=apply([c],{'5min':inflated},conf)[1][0]
        self.assertEqual(old['smc'],new['smc'])
        self.assertEqual(old['vp'],new['vp'])
    def test_invalid_smc_ohlc_rejected(self):
        d=self.frame();d.loc[d.index[5],'low']=d.loc[d.index[5],'high']+1
        with self.assertRaises(ValueError):latest(d)
    def test_context_setting_type_checked(self):
        from engine.context_integration import read_settings
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'c.json';p.write_text('{"smc_gate":"no", "vp_gate":false}')
            with self.assertRaises(ValueError):read_settings(p)
