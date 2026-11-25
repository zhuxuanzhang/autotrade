import copy,unittest
import pandas as pd
from two_year_range_filter import two_year_range
from daily_signals import PREVIOUS_RULES,migrate_two_year_range_rules,rules_for_day
class RangeTests(unittest.TestCase):
 def data(self,ratio=200):return pd.DataFrame(dict(date=['2024-02-29','2025-03-01','2026-02-28'],close=[100.,ratio,100.]))
 def test_bounds(self):
  for ratio,ok in [(199.99,False),(200,True),(399.99,True),(400,False)]:self.assertEqual(two_year_range(self.data(ratio),'2026-02-28')['passed'],ok)
 def test_calendar_and_future(self):
  df=self.data();self.assertEqual(two_year_range(df,'2026-02-28')['observed_start'],'2024-02-29')
  future=pd.concat([df,pd.DataFrame(dict(date=['2026-03-02'],close=[10000.]))],ignore_index=True)
  self.assertEqual(two_year_range(df,'2026-02-28'),two_year_range(future,'2026-02-28'))
  self.assertIsNone(two_year_range(df,'2026-03-01'))
 def test_migration_preserves_and_idempotent(self):
  state=dict(rules=copy.deepcopy(PREVIOUS_RULES),pending_buys=[dict(code='000001',signal_date='2026-02-28'),dict(code='000002',signal_date='2026-02-28')],positions={'a':{'entry_date':'2025-01-01'}},closed_trades=[{'a':1}],cancelled=[])
  before=copy.deepcopy(state);new=migrate_two_year_range_rules(state,{'000001':self.data(),'000002':self.data(400)},'2026-11-16')
  self.assertEqual(state,before);self.assertEqual(new['positions'],state['positions']);self.assertEqual(new['closed_trades'],state['closed_trades'])
  self.assertEqual(len(new['pending_buys']),1);self.assertEqual(len(new['cancelled']),1);self.assertEqual(new['rules'],rules_for_day('2026-11-16'))
  self.assertEqual(new,migrate_two_year_range_rules(new,{},'2026-11-16'))
if __name__=='__main__':unittest.main()
