import copy,json,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from datetime import datetime,timezone,timedelta
from unittest.mock import patch
import pandas as pd
import manual_1440 as m
import daily_signals as s
import unified_records as u

class PriorityCaptureTests(unittest.TestCase):
 def test_publish_priority_before_remaining_and_never_execute_intraday_sale(self):
  day='2026-11-18';previous='2026-11-17';now=datetime(2026,11,18,14,40,tzinfo=timezone(timedelta(hours=8)))
  dates=pd.bdate_range(end=previous,periods=100).strftime('%Y-%m-%d')
  frame=pd.DataFrame(dict(date=dates,open=10.,high=10.,low=10.,close=10.,volume=1000.))
  position=dict(code='000001',name='持仓股',entry_date='2026-11-16',entry_price=10.,signal_date='2026-11-16')
  state=dict(positions={'000001':position},closed_trades=[],pending_buys=[])
  risk=dict(date=day,stocks={c:dict(name=c,excluded=False) for c in ['000001','000002','000003']})
  quote=dict(timestamp=day+'T14:40:10',price=11.,previous_close=10.,open=10.,high=11.,low=10.,volume=2000.)
  selected=dict(code='000002',name='候选股',signal_date=day,signal_close_hfq=11.,breakout_hfq=10.,stop_hfq=10.)
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);s.save(root/'ledger.json',state);s.save(root/'latest.json',dict(positions=[position],closed_trades=[],rules=s.RULES))
   s.save(root/'risk/latest.json',risk)
   response=SimpleNamespace(text='mock bulk',encoding=None,raise_for_status=lambda:None)
   with patch.object(s,'ROOT',root),patch.object(s,'RISK_ROOT',root/'risk'),patch.object(m,'datetime') as clock,patch.object(m,'local_now',return_value=now),patch.object(m,'capture_status',return_value={'enabled':True}),patch.object(m.msvcrt,'locking'),patch.object(m,'locked_signals',return_value=None),patch.object(s,'market_calendar',return_value=[previous]),patch.object(m.priority,'scope',return_value=(['000001','000002'],['000003'],{})),patch.object(m.priority,'history',return_value=frame),patch.object(s,'history',return_value=frame),patch.object(s,'raw_history',return_value=frame),patch.object(s,'candidate',side_effect=lambda code,*args:copy.deepcopy(selected) if code=='000002' else None),patch.object(s,'sell_reasons',return_value=(['跌破止损'],dict(mark_date=day,last_raw_close=11.,net_return=.09))),patch.object(u,'snapshot',return_value={'positions':[]}),patch.object(m,'parse_quotes',return_value={c:dict(quote,code=c) for c in ['000001','000002']}),patch.object(m.requests,'get',return_value=response) as network:
    clock.now.return_value=now
    self.assertEqual(m.acquire(),day)
    self.assertNotIn('sz000003',network.call_args.args[0]);self.assertEqual(network.call_count,1)
    self.assertEqual(s.load(root/'ledger.json'),state)
    report=s.load(root/'latest.json');snapshot=report['entry_signal_snapshot']
    self.assertEqual(len(snapshot['candidates']),1);self.assertEqual(snapshot['coverage']['deferred'],1)
    self.assertEqual(report['sell_signals'][0]['signal_basis'],'14:40_preview')
    self.assertEqual(s.load(root/'intraday_supplement'/f'{day}.json')['status'],'pending_sync')
    with patch.object(m,'locked_signals',return_value=snapshot):
     with self.assertRaisesRegex(ValueError,'尚未确认同步'):m.acquire(supplement=True)
    self.assertEqual(network.call_count,1)
if __name__=='__main__':unittest.main()
