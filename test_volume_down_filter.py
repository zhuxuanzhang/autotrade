import copy
import unittest
from unittest.mock import patch
import pandas as pd
import numpy as np
from volume_down_filter import historical_volume_down
from daily_signals import (migrate_volume_down_rules,LEGACY_RULES,SIX_MONTH_DRAWDOWN_RULES,
                           FIVE_DAY_EVENT_VOLUME_RULES,candidate,rules_for_day)
from priority_universe import exclusion,rule_key

class VolumeDownTests(unittest.TestCase):
    def fixture(self,pct=12,kind='consecutive',ratio=1.5):
        c=np.full(400,100.)
        if kind=='consecutive':c[78:80]=[99.,98.]
        c[80]=100*(1-pct/100)
        v=np.full(400,100.);v[76:81]=ratio*100
        return pd.DataFrame(dict(date=pd.date_range('2025-01-01',periods=400).strftime('%Y-%m-%d'),close=c,volume=v))
    def test_boundaries_and_or(self):
        for kind,valid,invalid in [('consecutive',[9,12,18],[8.99,18.01]),('drawdown',[20,25,30],[19.99,30.01])]:
            for pct in valid:
                df=self.fixture(pct,kind)
                self.assertTrue(any(e['kind']==kind for e in historical_volume_down(df,df.date.iloc[81])))
            for pct in invalid:
                df=self.fixture(pct,kind)
                self.assertFalse(any(e['kind']==kind for e in historical_volume_down(df,df.date.iloc[81])))
    def test_prior_only_calendar_window(self):
        df=self.fixture()
        self.assertFalse(historical_volume_down(df,df.date.iloc[80]))
        end=pd.Timestamp(df.date.iloc[80])+pd.DateOffset(months=6)
        self.assertTrue(historical_volume_down(df,end))
        self.assertFalse(historical_volume_down(df,end+pd.Timedelta(days=1)))
        self.assertEqual(historical_volume_down(df,df.date.iloc[81]),historical_volume_down(df.iloc[:82],df.date.iloc[81]))
    def test_new_version_keeps_only_drawdown_with_closed_bounds(self):
        old=rules_for_day('2026-11-24')
        new=rules_for_day('2026-11-25')
        self.assertEqual({k for k in new if new[k]!=old.get(k)},{'version','historical_volume_down'})
        history=new['historical_volume_down']
        for pct,expected in [(19.99,False),(20,True),(25,True),(30,True),(30.01,False),(80,False)]:
            with self.subTest(pct=pct):
                df=self.fixture(pct,'drawdown')
                self.assertEqual(bool(historical_volume_down(df,df.date.iloc[81],history)),expected)
                self.assertFalse(historical_volume_down(df,df.date.iloc[80],history))
        df=self.fixture()
        self.assertTrue(historical_volume_down(df,df.date.iloc[81],old['historical_volume_down']))
        self.assertFalse(historical_volume_down(df,df.date.iloc[81],history))
        df=self.fixture(25,'drawdown')
        df.loc[79,'close']=75
        df.loc[76:79,'volume']=100
        df.loc[80,'volume']=350
        self.assertFalse(historical_volume_down(df,df.date.iloc[81],history))
    def test_priority_prefilter_uses_signal_date_rule(self):
        df=self.fixture(12,'consecutive').iloc[:160].copy()
        df['date']=pd.bdate_range(end='2026-11-24',periods=len(df)).strftime('%Y-%m-%d')
        self.assertIsNone(exclusion(df.iloc[:-1],'2026-11-24'))
        self.assertIsNotNone(exclusion(df,'2026-11-25'))
        df.loc[80,'close']=75
        self.assertIsNone(exclusion(df,'2026-11-25'))
        df.loc[80,'close']=60
        self.assertIsNotNone(exclusion(df,'2026-11-25'))
        self.assertNotEqual(rule_key('2026-11-24'),rule_key('2026-11-25'))
    def test_four_calendar_month_window_keeps_exact_cutoff(self):
        new=rules_for_day('2026-11-25')
        six_month_history={**SIX_MONTH_DRAWDOWN_RULES['historical_volume_down'],'volume_recent_sessions':3}
        history=new['historical_volume_down']
        self.assertEqual({k for k in history if history[k]!=six_month_history[k]},{'lookback_months'})
        self.assertEqual(history['lookback_months'],4)
        df=self.fixture(25,'drawdown')
        cutoff=pd.Timestamp(df.date.iloc[80])+pd.DateOffset(months=4)
        day_after=cutoff+pd.Timedelta(days=1)
        self.assertTrue(historical_volume_down(df,cutoff,history))
        self.assertFalse(historical_volume_down(df,day_after,history))
        self.assertTrue(historical_volume_down(df,day_after,six_month_history))
    def test_three_event_days_and_disjoint_fifteen_day_baseline(self):
        prior=FIVE_DAY_EVENT_VOLUME_RULES
        current=rules_for_day('2026-11-25')
        self.assertEqual({k for k in current if current[k]!=prior.get(k)},{'version','historical_volume_down'})
        history=current['historical_volume_down']
        self.assertEqual({k for k in history if history[k]!=prior['historical_volume_down'].get(k)},
                         {'volume_recent_sessions'})
        for recent_volume in (120,180):
            df=self.fixture(25,'drawdown',ratio=1)
            df.loc[78:80,'volume']=recent_volume
            df.loc[62,'volume']=10000
            df.loc[81,'volume']=10000
            day=df.date.iloc[81]
            event,=historical_volume_down(df,day,history)
            self.assertAlmostEqual(event['volume_ratio'],recent_volume/100)
            self.assertIn('事件3日/前15日',event['reason'])
        df.loc[78:80,'volume']=120
        self.assertFalse(historical_volume_down(df,day,prior['historical_volume_down']))
        df.loc[77,'volume']=160
        self.assertFalse(historical_volume_down(df,day,history))
    def test_volume_and_consecutive(self):
        for ratio,expected in [(1.19,False),(1.2,True),(1.8,True),(1.81,False)]:
            df=self.fixture(ratio=ratio)
            self.assertEqual(bool(historical_volume_down(df,df.date.iloc[81])),expected)
        df=self.fixture();df.loc[79,'close']=99.5
        self.assertFalse(historical_volume_down(df,df.date.iloc[81]))
    def test_migration_preserves_history_and_is_idempotent(self):
        df=self.fixture()
        old=dict(rules=copy.deepcopy(LEGACY_RULES),pending_buys=[dict(code='000001',signal_date=df.date.iloc[81]),dict(code='000002',signal_date=df.date.iloc[81])],positions={'600000':{'entry_date':'2025-01-03'}},closed_trades=[{'code':'600001'}],cancelled=[])
        before=copy.deepcopy(old)
        new=migrate_volume_down_rules(old,{'000001':df},'2026-11-16')
        self.assertEqual(old,before)
        self.assertEqual(new['positions'],before['positions']);self.assertEqual(new['closed_trades'],before['closed_trades'])
        self.assertEqual(len(new['pending_buys']),1);self.assertEqual(len(new['cancelled']),1)
        self.assertEqual(new['rules'],rules_for_day('2026-11-16'))
        self.assertEqual(migrate_volume_down_rules(new,{},'2026-11-16'),new)
        old['rules']={'version':'unknown'}
        with self.assertRaises(ValueError):migrate_volume_down_rules(old,{},'2026-11-16')
    def test_candidate_requires_event_and_records_evidence(self):
        df=self.fixture().iloc[:100].copy();df['low']=df.close*.99;df.loc[95:99,'volume']=150
        target=df.date.iloc[-1]
        metrics=dict(previous_20_close_high=99,ma20=98,ma60=97,deviation_from_ma20=.02)
        risk=dict(stocks={'000001':{'name':'测试'}},date=target)
        with patch('daily_signals.right_side_buy',return_value=dict(buy_signal=True,metrics=metrics)), patch('daily_signals.two_year_range',return_value=dict(passed=True,reason='range passed')):
            result=candidate('000001',df,risk,target,target)
            self.assertTrue(result['historical_volume_down_events'])
            self.assertEqual(result['entry_rule_version'],rules_for_day(df.date.iloc[-1])['version'])
            df['close']=100.
            self.assertIsNone(candidate('000001',df,risk,target,target))
if __name__=='__main__':unittest.main()
