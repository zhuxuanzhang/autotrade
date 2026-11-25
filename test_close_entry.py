import copy,unittest
import pandas as pd
from close_entry import fill_close_orders,fill_close_sales
from capture_1440 import parse_quotes,provisional
class CloseTests(unittest.TestCase):
 def fixture(self):
  dates=list(pd.bdate_range('2026-01-01',periods=30).strftime('%Y-%m-%d'));df=pd.DataFrame(dict(date=dates,open=10.,high=10.,low=10.,close=10.,volume=1000.))
  item=dict(code='000001',name='测试',signal_date=dates[-1],reference_previous_date=dates[-2],reference_previous_hfq=10.,signal_close_hfq=10.5,stop_hfq=9.,breakout_hfq=10.2)
  state=dict(positions={},closed_trades=[]);snapshot=dict(date=dates[-1],candidates=[item])
  return state,snapshot,df
 def test_close_not_next_open_filter_and_idempotent(self):
  state,snap,df=self.fixture();df.loc[29,'close']=8.;df.loc[29,'open']=12.
  result=fill_close_orders(state,snap,{'000001':df},{'000001':df},snap['date'])
  p=state['positions']['000001'];self.assertEqual(p['entry_price'],8.);self.assertEqual(p['entry_date'],snap['date']);self.assertTrue(p['sell_order'])
  before=copy.deepcopy(state);self.assertEqual(fill_close_orders(state,snap,{'000001':df},{'000001':df},snap['date']),[]);self.assertEqual(state,before)
 def test_close_sale_uses_close_and_tplus1(self):
  state,snap,df=self.fixture();df.loc[29,'close']=8.;fill_close_orders(state,snap,{'000001':df},{'000001':df},snap['date'])
  fill_close_sales(state,{'000001':df},{'000001':df},snap['date']);self.assertTrue(state['positions']);self.assertFalse(state['closed_trades'])
  following=(pd.Timestamp(snap['date'])+pd.offsets.BDay()).date().isoformat();df=pd.concat([df,pd.DataFrame([dict(date=following,open=12.,high=12.,low=7.,close=7.,volume=1000.)])],ignore_index=True)
  fill_close_sales(state,{'000001':df},{'000001':df},following)
  self.assertFalse(state['positions']);self.assertEqual(state['closed_trades'][0]['exit_price'],7.)
  self.assertEqual(state['closed_trades'][0]['entry_price'],8.)
 def test_missing_close_keeps_explicit_issue(self):
  state,snap,df=self.fixture();r=fill_close_orders(state,snap,{'000001':df},{},snap['date']);self.assertFalse(state['positions']);self.assertIn('缺少',r[0]['status'])
  self.assertEqual(fill_close_orders(state,snap,{}, {},'2026-12-01'),[])
 def test_timestamp_and_volume(self):
  fields=['0']*40;fields[2]='000001';fields[3]='10';fields[4]='9';fields[5]='9.5';fields[6]='123';fields[33]='10.5';fields[34]='9.4';fields[30]='20261117144030'
  q=parse_quotes('v_sz000001="'+'~'.join(fields)+'";','2026-11-17');self.assertEqual(q['000001']['volume'],12300)
  fields[30]='20261117144100';self.assertFalse(parse_quotes('v_sz000001="'+'~'.join(fields)+'";','2026-11-17'))
 def test_provisional_excludes_later_prices(self):
  df=pd.DataFrame(dict(date=['2026-11-16','2026-11-17'],open=[20.,100.],high=[20.,100.],low=[20.,100.],close=[20.,100.],volume=[1000.,99999.]))
  q=dict(previous_close=10.,price=11.,open=10.,high=11.,low=9.5,volume=2000.)
  x,prev=provisional(df,q,'2026-11-17');self.assertEqual(x.close.iloc[-1],22.);self.assertEqual(x.volume.iloc[-1],2000.);self.assertEqual(prev.date,'2026-11-16')
 def test_initial_stop_removed_only_from_effective_session(self):
  from daily_signals import INITIAL_STOP_REASON, sell_reasons, rules_for_day
  days=list(pd.bdate_range(end='2026-11-24',periods=30).strftime('%Y-%m-%d'))
  df=pd.DataFrame(dict(date=days,close=9.,volume=1000.))
  df.loc[27:,'close']=[10.,9.5,9.5]
  p=dict(code='000001',entry_date=days[27],entry_price=10.,signal_date=days[27],
         signal_close_hfq=10.,stop_hfq=9.8,breakout_hfq=9.8)
  before,_=sell_reasons(p,df,df,'2026-11-23')
  after,mark=sell_reasons(p,df,df,'2026-11-24')
  self.assertEqual(before,[INITIAL_STOP_REASON])
  self.assertEqual(after,[])
  self.assertNotIn('initial_stop_hfq',mark)
  self.assertEqual(rules_for_day('2026-11-23')['version'],'2026-11-20-close-v9')
  self.assertFalse(rules_for_day('2026-11-24')['initial_stop_enabled'])
  bars={'000001':df}
  for other_reason in (None,'买入后前5日收盘跌破原突破位92%'):
   with self.subTest(other_reason=other_reason):
    order=dict(signal_date='2026-11-23',reasons=[INITIAL_STOP_REASON]+([other_reason] if other_reason else []))
    state=dict(positions={'000001':dict(p,sell_order=order)},closed_trades=[])
    fill_close_sales(state,bars,bars,'2026-11-24')
    if other_reason:
     self.assertEqual(state['closed_trades'][0]['exit_reasons'],[other_reason])
    else:
     self.assertEqual(state['closed_trades'],[])
     self.assertIsNone(state['positions']['000001']['sell_order'])

 def test_time_exit_changes_from_fifteen_to_thirty_sessions(self):
  from daily_signals import TIME_EXIT_REASON, sell_reasons
  entry_date=pd.bdate_range(end='2026-11-23',periods=15)[0]
  dates=list(pd.bdate_range(start=entry_date-pd.offsets.BDay(25),periods=55).strftime('%Y-%m-%d'))
  df=pd.DataFrame(dict(date=dates,close=9.,volume=1000.))
  df.loc[25,'close']=10.
  p=dict(code='000001',entry_date=dates[25],entry_price=10.,signal_date=dates[25],
         signal_close_hfq=10.,stop_hfq=8.,breakout_hfq=8.)
  old_reason=TIME_EXIT_REASON.format(days=15)
  new_reason=TIME_EXIT_REASON.format(days=30)
  self.assertEqual(dates[39],'2026-11-23')
  self.assertIn(old_reason,sell_reasons(p,df,df,dates[39])[0])
  self.assertNotIn(old_reason,sell_reasons(p,df,df,dates[40])[0])
  self.assertNotIn(new_reason,sell_reasons(p,df,df,dates[53])[0])
  df.loc[54,'close']=10.
  self.assertIn(new_reason,sell_reasons(p,df,df,dates[54])[0])
  df.loc[54,'close']=10.01
  self.assertNotIn(new_reason,sell_reasons(p,df,df,dates[54])[0])
  state=dict(positions={'000001':dict(p,sell_order=dict(signal_date=dates[39],reasons=[old_reason]))},closed_trades=[])
  bars={'000001':df}
  # Make today's close qualify only for the retired 15-session rule.
  df.loc[40,'close']=9.5
  fill_close_sales(state,bars,bars,dates[40])
  self.assertFalse(state['closed_trades'])
  self.assertIsNone(state['positions']['000001']['sell_order'])

 def test_three_ma20_closes_from_effective_session(self):
  from daily_signals import MA20_EXIT_REASONS, sell_reasons
  days=list(pd.bdate_range(end='2026-11-25',periods=40).strftime('%Y-%m-%d'))
  df=pd.DataFrame(dict(date=days,close=10.,volume=1000.))
  e=days[28]
  p=dict(code='000001',entry_date=e,entry_price=10.,signal_date=e,
         signal_close_hfq=10.,stop_hfq=8.,breakout_hfq=8.)
  df.loc[df.date=='2026-11-20','close']=9.6
  df.loc[df.date.isin(['2026-11-23','2026-11-24','2026-11-25']),'close']=[9.5,9.4,9.3]
  self.assertEqual(sell_reasons(p,df,df,'2026-11-23')[0],[MA20_EXIT_REASONS[2]])
  df.loc[df.date=='2026-11-20','close']=10.
  self.assertEqual(sell_reasons(p,df,df,'2026-11-24')[0],[])
  state=dict(positions={'000001':dict(p,sell_order=dict(
      signal_date='2026-11-23',reasons=[MA20_EXIT_REASONS[2]]))},closed_trades=[])
  bars={'000001':df}
  fill_close_sales(state,bars,bars,'2026-11-24')
  self.assertFalse(state['closed_trades'])
  fill_close_sales(state,bars,bars,'2026-11-25')
  self.assertEqual(state['closed_trades'][0]['exit_reasons'],[MA20_EXIT_REASONS[3]])

if __name__=='__main__':unittest.main()
