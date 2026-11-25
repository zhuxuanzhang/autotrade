import unittest,tempfile,json
from pathlib import Path
from datetime import datetime,timezone,timedelta
import pull_fastpath as f
class FastPullTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.base=Path(self.tmp.name);self.root=self.base/'data/daily_signals';self.now=datetime(2026,11,17,20,tzinfo=timezone(timedelta(hours=8)));f._CACHE=None
  self.write(self.root/'calendar.json',dict(dates=['2026-11-17'],expires_at='2026-11-18T16:00:00+08:00'))
  self.write(self.root/'ledger.json',dict(positions={},pending_buys=[]));self.write(self.root/'latest.json',dict(buys=[]))
  self.write(self.root/'run_status.json',dict(status='complete',mode='pull',target='2026-11-17'))
  self.write(self.base/'data/risk/latest.json',dict(date='2026-11-17',stocks={'000001':{'excluded':False}}))
  self.write(self.root/'pull_marks/2026-11-17.json',dict(version=1,target='2026-11-17',items={'market:000001':{'status':'complete'}}))
 def write(self,p,x):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(x),encoding='utf-8')
 def test_complete_returns_without_worker(self):self.assertTrue(f.quick_pull_status(self.base,self.now)['already_checked'])
 def test_new_security_invalidates_cached_response(self):
  self.assertIsNotNone(f.quick_pull_status(self.base,self.now))
  self.write(self.base/'data/risk/latest.json',dict(date='2026-11-17',stocks={'000001':{'excluded':False},'000002':{'excluded':False}}))
  self.assertIsNone(f.quick_pull_status(self.base,self.now))
 def test_retry_expiry_invalidates_cached_response(self):
  self.write(self.root/'pull_marks/2026-11-17.json',dict(version=1,target='2026-11-17',items={'market:000001':{'status':'stale','retry_after':'2026-11-17T20:10:00+08:00'}}))
  self.assertIsNotNone(f.quick_pull_status(self.base,self.now));self.assertIsNone(f.quick_pull_status(self.base,self.now+timedelta(minutes=11)))
 def test_running_or_missing_marks_never_shortcut(self):
  self.write(self.root/'run_status.json',dict(status='running',mode='pull',target='2026-11-17'));self.assertIsNone(f.quick_pull_status(self.base,self.now))
 def test_calendar_expired_or_new_risk_date_rechecks(self):
  self.assertIsNone(f.quick_pull_status(self.base,self.now+timedelta(days=1)))
if __name__=='__main__':unittest.main()
