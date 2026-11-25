import unittest,tempfile,copy
from pathlib import Path
from datetime import datetime,timezone,timedelta
from unittest.mock import patch
import pandas as pd
import close_entry as c
class FallbackTests(unittest.TestCase):
 def test_closed_session_snapshot_and_idempotent(self):
  now=datetime(2026,11,18,0,20,tzinfo=timezone(timedelta(hours=8)))
  df=pd.DataFrame(dict(date=['2026-11-16','2026-11-17','2026-11-18'],close=[10.,11.,99.]))
  item=dict(code='000001',signal_date='2026-11-17',signal_close_hfq=11.)
  state=dict(positions={},closed_trades=[])
  with tempfile.TemporaryDirectory() as tmp,patch.object(c,'ROOT',Path(tmp)),patch('daily_signals.candidate',return_value=item.copy()) as select:
   snap=c.closing_fallback('2026-11-17',now,'v8',{'000001':df},{},state,'2026-11-18',[])
   self.assertEqual(select.call_args.args[1].close.tolist(),[10.,11.])
   self.assertEqual(snap['source'],'final_close_fallback');self.assertEqual(snap['quote_time'],'close')
   self.assertEqual(snap['candidates'][0]['reference_previous_hfq'],10.)
   self.assertFalse((Path(tmp)/'intraday_signals').exists())
   self.assertEqual(c.closing_fallback('2026-11-17',now,'v8',{}, {},state,'2026-11-18',[]),snap)
   self.assertEqual(select.call_count,1)
 def test_reject_today_before_close(self):
  with self.assertRaises(ValueError):c.closing_fallback('2026-11-18',datetime(2026,11,18,14,50,tzinfo=timezone(timedelta(hours=8))),'v8',{}, {},{},'2026-11-18',[])
 def test_already_sold_today_not_rebought(self):
  now=datetime(2026,11,18,tzinfo=timezone(timedelta(hours=8)))
  df=pd.DataFrame(dict(date=['2026-11-16','2026-11-17'],close=[10.,11.]))
  with tempfile.TemporaryDirectory() as tmp,patch.object(c,'ROOT',Path(tmp)),patch('daily_signals.candidate',return_value=dict(code='000001',signal_date='2026-11-17')):
   snap=c.closing_fallback('2026-11-17',now,'v8',{'000001':df},{},dict(positions={},closed_trades=[dict(code='000001',exit_date='2026-11-17')]),'2026-11-18',[])
   self.assertEqual(len(snap['all_selected']),1);self.assertEqual(snap['candidates'],[])
 def test_empty_intraday_is_valid_snapshot(self):
  import json
  with tempfile.TemporaryDirectory() as tmp,patch.object(c,'ROOT',Path(tmp)):
   p=Path(tmp)/'intraday_signals/2026-11-17.json';p.parent.mkdir();p.write_text(json.dumps(dict(date='2026-11-17',rules_version='2026-11-17-close-v7',candidates=[])))
   self.assertIsNotNone(c.locked_signals('2026-11-17','2026-11-17-close-v8'))
 def test_market_gate_controls_new_close_entries_and_missing_data_can_retry(self):
  day='2026-11-20'
  now=datetime(2026,11,20,17,tzinfo=timezone(timedelta(hours=8)))
  df=pd.DataFrame(dict(date=['2026-11-19',day],close=[10.,11.]))
  state=dict(positions={},closed_trades=[])
  item=dict(code='000001',signal_date=day)
  gates=[
   dict(status='missing',allowed=False,reason='成交额待补'),
   dict(status='passed',allowed=True,ratio=1.13,reference_date='2026-11-19'),
  ]
  with tempfile.TemporaryDirectory() as tmp,patch.object(c,'ROOT',Path(tmp)),patch.object(c,'buy_gate',side_effect=gates),patch('daily_signals.candidate',return_value=item) as select:
   args=(day,now,'2026-11-20-close-v9',{'000001':df},{},state,day,[])
   self.assertEqual(c.closing_fallback(*args)['candidates'],[])
   select.assert_not_called()
   self.assertFalse((Path(tmp)/'close_signals'/f'{day}.json').exists())
   passed=c.closing_fallback(*args)
   self.assertEqual(len(passed['candidates']),1)
   self.assertEqual(passed['market_amount_gate']['ratio'],1.13)

 def test_close_order_requires_approved_market_ratio(self):
  day='2026-11-20'
  snapshot=dict(date=day,candidates=[dict(code='000001',signal_date=day)])
  self.assertEqual(c.fill_close_orders({},snapshot,{},{},day),[])
  snapshot['market_amount_gate']=dict(status='passed',ratio=1.45,reference_date='2026-11-19')
  self.assertEqual(c.fill_close_orders({},snapshot,{},{},day),[])

 def test_sse_ma5_gate_blocks_final_close_and_accepts_exact_volume_limit(self):
  from daily_signals import RULES
  day='2026-11-24'
  prev='2026-11-23'
  now=datetime(2026,11,24,17,tzinfo=timezone(timedelta(hours=8)))
  df=pd.DataFrame(dict(date=[prev,day],close=[10.,11.],volume=[1000.,1000.],low=[9.,10.]))
  state=dict(positions={},closed_trades=[])
  amount=dict(status='passed',allowed=True,ratio=1.15,reference_date=prev)
  trend=dict(status='passed',allowed=True,close=3100.,ma5=3000.,reference_date=day,quote_time='close')
  candidate=dict(code='000001',signal_date=day,signal_close_hfq=11.,breakout_hfq=10.,volume_ratio=1.70)
  error_gate=dict(status='missing',allowed=False,reason='missing')
  with tempfile.TemporaryDirectory() as tmp,patch.object(c,'ROOT',Path(tmp)),patch.object(c,'buy_gate',return_value=amount),patch('daily_signals.index_buy_gate',side_effect=[error_gate,trend]),patch('daily_signals.candidate',return_value=candidate) as select,patch('daily_signals.sell_reasons',return_value=([],None)):
   args=(day,now,RULES['version'],{'000001':df},{},state,day,[])
   self.assertEqual(c.closing_fallback(*args)['candidates'],[])
   select.assert_not_called()
   self.assertFalse((Path(tmp)/'close_signals'/f'{day}.json').exists())
   snapshot=c.closing_fallback(*args)
   self.assertEqual(len(snapshot['candidates']),1)
   frames={'000001':df}
   invalid=dict(snapshot,market_index_gate=dict(trend,close=3007.49))
   self.assertEqual(c.fill_close_orders(state,invalid,frames,frames,day),[])
   invalid=dict(snapshot,candidates=[dict(snapshot['candidates'][0],volume_ratio=1.701)])
   self.assertEqual(c.fill_close_orders(state,invalid,frames,frames,day),[])
   self.assertEqual(len(c.fill_close_orders(state,snapshot,frames,frames,day)),1)
   self.assertEqual(state['positions']['000001']['market_index_gate'],trend)

 def test_blocked_intraday_uses_same_day_close_fallback(self):
  day='2026-11-24'
  version='2026-11-24-close-v10'
  intraday=dict(date=day,quote_time='14:40',market_index_gate=dict(
      status='passed',reference_date=day,quote_time='14:40',close=3007.49,ma5=3000.),candidates=[])
  close=dict(date=day,candidates=[dict(code='000001')])
  with patch.object(c,'locked_signals',return_value=intraday),patch.object(c,'closing_fallback',return_value=close) as fallback:
   self.assertIs(c.entry_snapshot_for_close(day,None,version,{},{},{},day,[]),close)
   fallback.assert_called_once()
   fallback.reset_mock()
   intraday['market_index_gate']['close']=3007.50
   self.assertIs(c.entry_snapshot_for_close(day,None,version,{},{},{},day,[]),intraday)
   fallback.assert_not_called()

if __name__=='__main__':unittest.main()
