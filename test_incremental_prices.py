import unittest
import pandas as pd
from incremental_prices import assemble
class IncrementalTests(unittest.TestCase):
 def data(self):
  d=list(pd.bdate_range('2026-11-02',periods=7).strftime('%Y-%m-%d'))
  raw=pd.DataFrame(dict(date=d,open=[10.]*7,high=[11.]*7,low=[9.]*7,close=[10.]*7,volume=[1000.]*7))
  f=pd.DataFrame(dict(date=['1900-01-01'],factor=[2.]))
  base=raw.iloc[:6].copy()
  for k in ['open','high','low','close']:base[k]*=2
  return base,raw,f
 def test_append_preserves_existing_exactly(self):
  b,r,f=self.data();h,raw=assemble(b,r,f,r.date.iloc[-1]);pd.testing.assert_frame_equal(h.iloc[:6].reset_index(drop=True),b.reset_index(drop=True));self.assertEqual(len(h),7);self.assertEqual(h.close.iloc[-1],20.);self.assertEqual(raw.close.iloc[-1],10.)
 def test_factor_change_on_new_date(self):
  b,r,f=self.data();f=pd.concat([f,pd.DataFrame(dict(date=[r.date.iloc[-1]],factor=[4.]))],ignore_index=True);r.loc[6,['open','high','low','close']]/=2
  h,_=assemble(b,r,f,r.date.iloc[-1]);self.assertEqual(h.close.iloc[-1],20.)
 def test_mismatch_never_silently_splices(self):
  b,r,f=self.data();r.loc[2,'close']=9.
  with self.assertRaises(ValueError):assemble(b,r,f,r.date.iloc[-1])
 def test_volume_unit_mismatch_rejected(self):
  b,r,f=self.data();r.volume=r.volume*100
  with self.assertRaises(ValueError):assemble(b,r,f,r.date.iloc[-1])
 def test_stale_and_missing_overlap_rejected(self):
  b,r,f=self.data()
  with self.assertRaises(ValueError):assemble(b,r.iloc[:-1],f,r.date.iloc[-1])
  with self.assertRaises(ValueError):assemble(b,r.iloc[-1:],f,r.date.iloc[-1])
if __name__=='__main__':unittest.main()
