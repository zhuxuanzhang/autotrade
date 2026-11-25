import unittest,tempfile,json
from unittest.mock import patch
from pathlib import Path
import numpy as np,pandas as pd
import priority_universe as p
from right_side import right_side_buy
class PriorityTests(unittest.TestCase):
 def fixture(self):
  n=300;return pd.DataFrame(dict(date=pd.bdate_range(end='2026-11-17',periods=n).strftime('%Y-%m-%d'),open=10.,high=10.,low=10.,close=np.linspace(9,12,n),volume=1000.))
 def test_known_event_required_before_new_day(self):
  df=self.fixture()
  with patch.object(p.s,'historical_volume_down',return_value=[]):self.assertIn('放量下跌',p.exclusion(df,'2026-11-18'))
 def test_no_false_rejection_of_price_volume_feasible_cases(self):
  rng=np.random.default_rng(48)
  with patch.object(p.s,'historical_volume_down',return_value=[{}]):
   for n in range(35):
    df=self.fixture();df['close']=np.exp(np.cumsum(rng.normal(.0008,.014,len(df))))*10
    reason=p.exclusion(df,'2026-11-18')
    if not reason:continue
    self.assertIn('任意当天价格',reason)
    prior=df.close.tolist()
    for x in np.linspace(min(prior[-64:])*.6,max(prior[-64:])*1.5,100):
     result=right_side_buy(prior+[x],code='000001',as_of='2026-11-18',history_start=df.date.iloc[0],risk_record=dict(excluded=False,name='测试'),risk_date='2026-11-18')
     self.assertFalse(result['buy_signal'],(reason,x))
 def test_held_and_changed_sources_always_priority(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);source=root/'source.csv';source.write_text('old')
   entries={c:dict(source=str(source),signature=p.signature(source),excluded_reason='proven') for c in ['000001','000002']}
   path=root/'plan.json';path.write_text(json.dumps(dict(date='2026-11-18',previous='2026-11-17',rules_key=p.rule_key('2026-11-18'),stocks=entries)))
   with patch.object(p,'plan_path',return_value=path):
    a,b,_=p.scope(entries,{'000001'},'2026-11-18','2026-11-17');self.assertEqual(a,['000001']);self.assertEqual(b,['000002'])
    source.write_text('new data')
    a,b,_=p.scope(entries,set(),'2026-11-18','2026-11-17');self.assertEqual(len(a),2);self.assertEqual(b,[])
    a,b,_=p.scope(entries,set(),'2026-11-19','2026-11-18');self.assertEqual(len(a),2)
 def test_volume_minimum_bound(self):
  df=self.fixture();df.loc[df.index[-4:],'volume']=100000
  with patch.object(p.s,'historical_volume_down',return_value=[{}]):self.assertIn('成交量',p.exclusion(df,'2026-11-18'))
if __name__=='__main__':unittest.main()
