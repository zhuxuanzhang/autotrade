import unittest
import pandas as pd
import numpy as np
from backtest import indicators, simulate, pullback_signals, exit_reason
from right_side import right_side_buy

class BacktestTests(unittest.TestCase):
    def test_volume_bin_boundaries_do_not_overlap(self):
        bins=[(1.,1.2,False),(1.2,1.4,False),(1.4,1.6,False),(1.6,1.8,True)]
        for value,expected in [(1.,0),(1.2,1),(1.4,2),(1.6,3),(1.8,3),(1.801,None),(.999,None)]:
            df=pd.DataFrame({'close':np.linspace(10,12,100),'volume':[100.]*95+[100*value]*5})
            matches=[i for i,(lo,hi,inclusive) in enumerate(bins) if indicators(df,
                volume_ratio=lo,max_volume_ratio=hi,volume_upper_inclusive=inclusive)[2].iloc[-1]]
            self.assertEqual(matches,[] if expected is None else [expected])

    def test_volume_ceiling_is_inclusive(self):
        df=pd.DataFrame({'close':np.linspace(10,12,100),'volume':[100.]*95+[180.]*5})
        self.assertTrue(indicators(df,volume_ratio=1.2)[2].iloc[-1])
        df.loc[99,'volume']=180.01
        self.assertFalse(indicators(df,volume_ratio=1.2)[2].iloc[-1])
        self.assertTrue(indicators(df,volume_ratio=1.2,max_volume_ratio=None)[2].iloc[-1])
        with self.assertRaises(ValueError):
            indicators(df,volume_ratio=2.,max_volume_ratio=1.8)

    def test_five_vs_prior_fifteen_nonoverlap(self):
        # Last 5 sessions average 150, preceding 15 average 100.
        df=pd.DataFrame({'close':np.linspace(10,12,100),'volume':[100.]*95+[150.]*5})
        self.assertTrue(indicators(df,volume_ratio=1.5)[2].iloc[-1])
        self.assertFalse(indicators(df,volume_ratio=1.51)[2].iloc[-1])
        changed=df.copy()
        changed.loc[80,'volume']=115. # Included in prior window: index 80..94.
        self.assertFalse(indicators(changed,volume_ratio=1.5)[2].iloc[-1])
        outside=df.copy()
        outside.loc[79,'volume']=100000.
        self.assertTrue(indicators(outside,volume_ratio=1.5)[2].iloc[-1])
        scaled=df.copy()
        scaled.volume*=100
        pd.testing.assert_series_equal(indicators(df,volume_ratio=1.5)[2],indicators(scaled,volume_ratio=1.5)[2])
        pd.testing.assert_series_equal(indicators(df.iloc[:98],volume_ratio=1.5)[2],indicators(df,volume_ratio=1.5)[2].iloc[:98])

    def test_breakout_exit_threshold_and_window(self):
        position={'stop':90.,'breakout':100.,'entry':101.}
        self.assertEqual(exit_reason(97,100,95,95,position,3,.98),'failed_breakout')
        self.assertIsNone(exit_reason(97,100,95,95,position,3,.92))
        self.assertIsNone(exit_reason(92,100,80,80,position,5,.92))
        self.assertEqual(exit_reason(91.9,100,80,80,position,5,.92),'failed_breakout')
        self.assertIsNone(exit_reason(91.9,100,80,80,position,6,.92))
        self.assertEqual(exit_reason(89,100,80,80,position,3,.92),'initial_stop')

    def test_volume_uses_prior_twenty_days_and_scale_invariance(self):
        df=pd.DataFrame({'close':np.linspace(10,12,100),'volume':[100.]*99+[150.]})
        self.assertTrue(indicators(df,volume_ratio=1.5,volume_mode='day_vs_prior20',max_volume_ratio=None)[2].iloc[-1])
        self.assertFalse(indicators(df,volume_ratio=2.,volume_mode='day_vs_prior20',max_volume_ratio=None)[2].iloc[-1])
        scaled=df.copy()
        scaled.volume*=100
        pd.testing.assert_series_equal(indicators(df,volume_ratio=1.5,volume_mode='day_vs_prior20',max_volume_ratio=None)[2],indicators(scaled,volume_ratio=1.5,volume_mode='day_vs_prior20',max_volume_ratio=None)[2])
        pd.testing.assert_series_equal(indicators(df.iloc[:95],volume_ratio=1.5,volume_mode='day_vs_prior20',max_volume_ratio=None)[2],indicators(df,volume_ratio=1.5,volume_mode='day_vs_prior20',max_volume_ratio=None)[2].iloc[:95])

    def test_pullback_sequence_and_fixed_anchor(self):
        c=pd.Series([106.,103.,104.,105.])
        lv=pd.Series([100.,106.,106.,106.])
        initial=pd.Series([True,True,False,False])
        trend=pd.Series([True]*4)
        anchor,sig=pullback_signals(c,lv,initial,trend,.05)
        self.assertEqual(sig.tolist(),[False,False,True,False])
        self.assertEqual(anchor.iloc[2],100.)
        self.assertFalse(pullback_signals(c,lv,initial,trend,.02)[1].any())
        pd.testing.assert_series_equal(pullback_signals(c[:2],lv[:2],initial[:2],trend[:2])[1],sig[:2])

    def test_pullback_invalidated_or_expired(self):
        for prices in ([106.,94.,103.,104.],[106.,107.,103.,104.]):
            c=pd.Series(prices)
            _,sig=pullback_signals(c,pd.Series([100.]*4),pd.Series([True,False,False,False]),pd.Series([True]*4),.05,2)
            self.assertFalse(sig.any())

    def test_confirmation_uses_fixed_breakout_level(self):
        c=np.linspace(10,12,100)
        c[-1]=c[-2]-.005
        df=pd.DataFrame({'close':c})
        _, anchor, signal=indicators(df,20,2)
        self.assertAlmostEqual(anchor.iloc[-1],c[-3])
        self.assertTrue(signal.iloc[-1])
        self.assertFalse(indicators(df,20,1)[2].iloc[-1])
        for lookback,confirmation in ((20,2),(40,1),(60,1)):
            pd.testing.assert_series_equal(indicators(df.iloc[:90],lookback,confirmation)[2],
                indicators(df,lookback,confirmation)[2].iloc[:90])

    def test_signals_match_and_no_future_leakage(self):
        rng=np.random.default_rng(42)
        c=10*np.exp(np.cumsum(rng.normal(.001,.01,300)))
        dates=pd.bdate_range('2020-01-01',periods=300)
        df=pd.DataFrame(dict(date=dates,close=c,open=c,high=c*1.01,low=c*.99,volume=1000))
        signals=indicators(df)[2]
        for i in range(140,300):
            result=right_side_buy(c[:i+1],code='000001',listing_date='2010-01-01',
                as_of=str(dates[i].date()),risk_date=str(dates[i].date()),
                risk_record={'name':'普通股票','excluded':False})
            self.assertEqual(bool(signals.iloc[i]),result['buy_signal'])
        pd.testing.assert_series_equal(indicators(df.iloc[:200])[2],signals.iloc[:200])

    def test_execution_after_signal_and_no_overlap(self):
        c=np.r_[np.linspace(10,14,180),np.linspace(14,10,40)]
        df=pd.DataFrame(dict(date=pd.bdate_range('2020-01-01',periods=len(c)),
            close=c,open=c,high=c*1.01,low=c*.99,volume=1000))
        trades,_,_=simulate(df,'000001',pd.Timestamp('2020-01-01'),pd.Timestamp('2022-01-01'))
        self.assertTrue(trades)
        last_exit=''
        for trade in trades:
            self.assertLess(trade['signal_date'],trade['entry_date'])
            self.assertLess(trade['entry_date'],trade['exit_date'])
            self.assertGreater(trade['entry_date'],last_exit)
            self.assertLess(trade['net_return'],trade['gross_return'])
            last_exit=trade['exit_date']

if __name__=='__main__':
    unittest.main()
