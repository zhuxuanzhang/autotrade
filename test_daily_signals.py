import copy
import unittest
import pandas as pd
from daily_signals import process_day,sell_reasons,COST,listed_six_months

class PaperTests(unittest.TestCase):
    def data(self):
        dates=list(pd.bdate_range('2026-01-01',periods=30).strftime('%Y-%m-%d'))
        dates[0]='2025-01-01'
        return pd.DataFrame(dict(date=dates,open=[10.]*30,high=[10.2]*30,low=[9.8]*30,close=[10.]*30,volume=[1000.]*30))
    def state(self,df):
        day=df.date.iloc[24]
        order=dict(code='000001',name='测试',signal_date=day,created_date=day,breakout_hfq=9.9,stop_hfq=9.5,signal_close_hfq=10.,execution_date=df.date.iloc[25],reasons=['测试'])
        return dict(positions={},pending_buys=[order],closed_trades=[],cancelled=[],last_processed_market_date=day)
    def test_listing_age_at_execution(self):
        self.assertFalse(listed_six_months('2026-05-16','2026-11-15'))
        self.assertTrue(listed_six_months('2026-05-15','2026-11-15'))
        self.assertTrue(listed_six_months('2025-08-31','2026-02-28'))
        df=self.data();df.loc[0,'date']='2026-01-01'
        state=self.state(df);risk={'stocks':{'000001':{'excluded':False}}}
        process_day(state,{'000001':df},{'000001':df},df.date.iloc[25],risk)
        self.assertFalse(state['positions'])
        self.assertEqual(len(state['cancelled']),1)

    def test_no_same_day_fill_and_idempotence(self):
        df=self.data(); state=self.state(df); risk={'stocks':{'000001':{'excluded':False}}}
        process_day(state,{'000001':df},{'000001':df},df.date.iloc[24],risk)
        self.assertFalse(state['positions'])
        process_day(state,{'000001':df},{'000001':df},df.date.iloc[25],risk)
        self.assertEqual(len(state['positions']),1)
        self.assertEqual(state['positions']['000001']['quantity'],100)
        before=copy.deepcopy(state)
        process_day(state,{'000001':df},{'000001':df},df.date.iloc[25],risk)
        self.assertEqual(state,before)
    def test_sell_next_open_and_costs(self):
        df=self.data(); state=self.state(df); risk={'stocks':{'000001':{'excluded':False}}}
        process_day(state,{'000001':df},{'000001':df},df.date.iloc[25],risk)
        df.loc[26,['open','high','low','close']]=[9.6,9.7,9.3,9.4]
        process_day(state,{'000001':df},{'000001':df},df.date.iloc[26],risk)
        self.assertTrue(state['positions']['000001']['sell_order'])
        self.assertFalse(state['closed_trades'])
        df.loc[27,['open','high','low','close']]=[9.3,9.5,9.2,9.4]
        process_day(state,{'000001':df},{'000001':df},df.date.iloc[27],risk)
        trade=state['closed_trades'][0]
        self.assertAlmostEqual(trade['gross_return'],-.07)
        self.assertAlmostEqual(trade['net_return'],.93*(1-COST)/(1+COST)-1)
        self.assertFalse(state['positions'])
    def test_invalid_open_cancels(self):
        df=self.data(); state=self.state(df); risk={'stocks':{'000001':{'excluded':False}}}
        df.loc[25,'open']=11.
        process_day(state,{'000001':df},{'000001':df},df.date.iloc[25],risk)
        self.assertFalse(state['positions']);self.assertEqual(len(state['cancelled']),1)
    def test_beijing_cannot_fill_even_if_queued(self):
        df=self.data();state=self.state(df)
        state['pending_buys'][0]['code']='920000'
        risk={'stocks':{'920000':{'excluded':False}}}
        process_day(state,{'920000':df},{'920000':df},df.date.iloc[25],risk)
        self.assertFalse(state['positions'])
        self.assertEqual(len(state['cancelled']),1)

    def test_missing_raw_never_fabricates_fill(self):
        df=self.data();state=self.state(df);risk={'stocks':{'000001':{'excluded':False}}}
        process_day(state,{'000001':df},{},df.date.iloc[25],risk)
        self.assertFalse(state['positions']);self.assertEqual(len(state['pending_buys']),1)

if __name__=='__main__': unittest.main()
