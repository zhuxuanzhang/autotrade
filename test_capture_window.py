import unittest
from datetime import datetime,timezone,timedelta
from unittest.mock import patch
from capture_window import status
from manual_1440 import minute_quote
class WindowTests(unittest.TestCase):
 def now(self,h,m):return datetime(2026,11,16,h,m,tzinfo=timezone(timedelta(hours=8)))
 def test_boundaries_and_latest_date(self):
  for h,m,ok in [(14,39,False),(14,40,True),(14,59,True),(15,0,False),(23,0,False)]:self.assertEqual(status(self.now(h,m),'2026-11-16')['enabled'],ok)
  self.assertFalse(status(self.now(14,45),'2026-11-13')['enabled'])
  self.assertFalse(status(datetime(2026,11,15,14,45,tzinfo=timezone(timedelta(hours=8))),'2026-11-13')['enabled'])
 def test_closed_window_never_fetches(self):
  with patch('capture_window.latest_source_date',side_effect=AssertionError('Should not fetch')):self.assertFalse(status(self.now(23,0))['enabled'])
 def test_exact1440_not_later_node(self):
  qt=['0']*6;qt[4]='9';qt[5]='10'
  payload={'data':{'sz000001':{'data':{'date':'20261116','data':['1439 10.0 100','1440 11.0 200','1450 20.0 500']},'qt':{'sz000001':qt}}}}
  q=minute_quote(payload,'000001','2026-11-16');self.assertEqual(q['price'],11.);self.assertEqual(q['volume'],20000.);self.assertEqual(q['high'],11.)
  with self.assertRaises(ValueError):minute_quote(payload,'000001','2026-11-13')
 def test_star_volume_already_shares(self):
  qt=['0']*6;qt[4]='9';qt[5]='10'
  payload={'data':{'sh688001':{'data':{'date':'20261116','data':['1440 11.0 200']},'qt':{'sh688001':qt}}}}
  self.assertEqual(minute_quote(payload,'688001','2026-11-16')['volume'],200.)
if __name__=='__main__':unittest.main()
