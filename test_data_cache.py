import tempfile
import unittest
from pathlib import Path
from datetime import datetime, timezone, timedelta
from unittest.mock import patch
import pandas as pd
import daily_signals as signals
from incremental_prices import update as real_incremental_update


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root=Path(self.temp.name)
        for name,value in [('ROOT',root/'daily'),('ARCHIVE',root/'archive')]:
            patcher=patch.object(signals,name,value)
            patcher.start()
            self.addCleanup(patcher.stop)
        incremental_patcher=patch('incremental_prices.update',side_effect=ValueError('legacy test exercises full-source fallback'))
        incremental_patcher.start();self.addCleanup(incremental_patcher.stop)
        self.frame=pd.DataFrame(dict(date=['2026-11-12','2026-11-13'],
            open=[10.,10.],high=[11.,11.],low=[9.,9.],close=[10.,10.],volume=[100.,100.]))

    def write(self,path,frame):
        path.parent.mkdir(parents=True,exist_ok=True)
        frame.to_csv(path,index=False)

    def test_fresh_archive_avoids_network(self):
        self.write(signals.ARCHIVE/'000001.csv',self.frame)
        with patch.object(signals.ak,'stock_zh_a_daily_sina') as fetch:
            result=signals.history('000001','2026-11-13',True)
        fetch.assert_not_called()
        self.assertEqual(result.date.iloc[-1],'2026-11-13')

    def test_stale_snapshot_is_refetched(self):
        self.write(signals.ROOT/'market/2026-11-13/000001.csv',self.frame.iloc[:1])
        with patch.object(signals.ak,'stock_zh_a_daily_sina',return_value=self.frame) as fetch, patch.object(signals.time,'sleep'):
            result=signals.history('000001','2026-11-13',True)
        fetch.assert_called_once()
        self.assertEqual(result.date.iloc[-1],'2026-11-13')

    def test_invalid_snapshot_is_repaired(self):
        bad=self.frame.copy();bad.loc[0,'open']=0
        self.write(signals.ROOT/'market/2026-11-13/000001.csv',bad)
        with patch.object(signals.ak,'stock_zh_a_daily_sina',return_value=self.frame) as fetch, patch.object(signals.time,'sleep'):
            signals.history('000001','2026-11-13',True)
        fetch.assert_called_once()

    def test_incremental_pair_avoids_full_download_and_is_reused(self):
        self.write(signals.ROOT/'market/2026-11-12/000001.csv',self.frame.iloc[:1])
        factors=pd.DataFrame(dict(date=['1900-01-01'],factor=[1.]))
        stats=dict(local=0,requested=0,downloaded=0)
        with patch('incremental_prices.update',side_effect=real_incremental_update), patch('incremental_prices.fetch_recent',return_value=(self.frame.copy(),factors)) as recent, patch.object(signals,'remote_history') as full:
            result=signals.history('000001','2026-11-13',True,stats)
            self.assertEqual(result.date.iloc[-1],'2026-11-13')
            self.assertEqual(stats['incremental'],1);self.assertEqual(stats['appended_rows'],1)
            self.assertTrue((signals.ROOT/'price_store/raw/000001.csv').exists())
            self.assertTrue((signals.ROOT/'price_store/hfq/000001.csv').exists())
            self.assertTrue((signals.ROOT/'price_store/factors/000001.csv').exists())
            signals.history('000001','2026-11-13',True,stats)
            signals.raw_history('000001','2026-11-13',True,stats)
            recent.assert_called_once();full.assert_not_called()

    def test_local_strategy_does_not_download_missing_raw(self):
        with patch.object(signals.ak,'stock_zh_a_daily_sina') as fetch:
            with self.assertRaises(ValueError):
                signals.raw_history('000001','2026-11-13',False)
        fetch.assert_not_called()

    def test_calendar_cache_expires_at_close_check(self):
        now=datetime(2026,11,16,10,tzinfo=timezone(timedelta(hours=8)))
        index=pd.DataFrame({'date':['2026-11-12','2026-11-13','2026-11-16']})
        with patch.object(signals.ak,'index_zh_daily_sina',return_value=index) as fetch:
            self.assertEqual(signals.market_calendar(now)[-1],'2026-11-13')
            signals.market_calendar(now+timedelta(hours=1))
            self.assertEqual(fetch.call_count,1)
            self.assertEqual(signals.market_calendar(now+timedelta(hours=6))[-1],'2026-11-16')
            self.assertEqual(fetch.call_count,2)

    def test_index_gate_uses_same_session_price_and_four_previous_closes(self):
        day='2026-11-24'
        dates=['2026-11-17','2026-11-18','2026-11-19','2026-11-20','2026-11-23',day]
        index=pd.DataFrame(dict(date=dates,close=[40,100,100,100,100,110]))
        with patch.object(signals.ak,'index_zh_daily_sina',return_value=index) as fetch:
            with patch.object(signals,'index_1440_price',return_value=95):
                intraday=signals.index_buy_gate(day,dates,quote_time='14:40')
            self.assertFalse(intraday['allowed'])
            self.assertEqual(intraday['ma5'],99)
            self.assertEqual(intraday['reference_date'],day)
            close=signals.index_buy_gate(day,dates,quote_time='close')
            self.assertTrue(close['allowed'])
            self.assertEqual(close['ma5'],102)
            self.assertEqual(close['reference_date'],day)
            self.assertEqual(fetch.call_count,2)
        with patch.object(signals.ak,'index_zh_daily_sina',return_value=index.iloc[:-1]):
            self.assertEqual(signals.index_buy_gate(day,dates)['status'],'missing')

    def test_index_gate_applies_same_point25_percent_threshold_at_both_times(self):
        day='2026-11-24'
        dates=['2026-11-18','2026-11-19','2026-11-20','2026-11-23',day]
        for price,expected in [(100.20,False),(100.32,True)]:
            with self.subTest(price=price),patch.object(signals.ak,'index_zh_daily_sina',
                 return_value=pd.DataFrame(dict(date=dates,close=[100,100,100,100,price]))),patch.object(
                 signals,'index_1440_price',return_value=price):
                for quote_time in ('14:40','close'):
                    gate=signals.index_buy_gate(day,dates,quote_time=quote_time)
                    self.assertEqual(gate['allowed'],expected)
                    self.assertEqual(gate['minimum_above_ma5'],.0025)

    def test_index_minute_uses_exact_timestamp(self):
        symbol='sh000001'
        day='2026-11-24'
        with patch.object(signals.requests,'get') as get:
            response=get.return_value
            response.json.return_value={'data':{symbol:{'data':{
                'date':'20261124','data':['1439 90 1','1440 110 2','1441 120 3']}}}}
            self.assertEqual(signals.index_1440_price(symbol,day),110)
            with self.assertRaises(ValueError):
                signals.index_1440_price(symbol,'2026-11-25')

    def test_snapshot_metadata_avoids_csv_reads_on_first_pull(self):
        signals.store_history('000001','2026-11-13','market',self.frame,'sina')
        now=datetime(2026,11,16,10,tzinfo=timezone(timedelta(hours=8)))
        risk={'stocks':{'000001':{'excluded':False}}}
        with patch.object(signals,'cached_history',side_effect=AssertionError('must not load CSV')):
            result=signals.pull_daily_data('2026-11-13',risk,now)
        self.assertEqual(result['transfer']['metadata_reused'],1)
        self.assertEqual(result['coverage']['current'],1)
    def test_changed_snapshot_metadata_not_trusted(self):
        signals.store_history('000001','2026-11-13','market',self.frame,'sina')
        path=signals.ROOT/'market/2026-11-13/000001.csv'
        path.write_text(path.read_text()+'\n',encoding='utf-8')
        self.assertIsNone(signals.verified_snapshot_metadata('000001','2026-11-13','market'))

    def test_daily_marks_skip_all_csv_reads_on_repeat(self):
        now=datetime(2026,11,16,10,tzinfo=timezone(timedelta(hours=8)))
        risk={'stocks':{'000001':{'excluded':False}}}
        with patch.object(signals,'cached_history',return_value=self.frame) as fetch:
            signals.pull_daily_data('2026-11-13',risk,now)
        fetch.assert_called_once()
        with patch.object(signals,'cached_history',side_effect=AssertionError('must not open CSV')):
            result=signals.pull_daily_data('2026-11-13',risk,now+timedelta(minutes=1))
        self.assertEqual(result['transfer']['marked'],1)
        self.assertEqual(result['transfer']['requested'],0)

    def test_retry_only_failed_item_after_cooldown(self):
        now=datetime(2026,11,16,10,tzinfo=timezone(timedelta(hours=8)))
        risk={'stocks':{'000001':{'excluded':False},'000002':{'excluded':False}}}
        with patch.object(signals,'cached_history',side_effect=[self.frame,ValueError('bad source')]):
            first=signals.pull_daily_data('2026-11-13',risk,now)
        self.assertEqual(first['coverage']['errors'],1)
        with patch.object(signals,'cached_history') as fetch:
            second=signals.pull_daily_data('2026-11-13',risk,now+timedelta(minutes=1))
        fetch.assert_not_called()
        self.assertEqual(second['coverage']['errors'],1)
        with patch.object(signals,'cached_history',return_value=self.frame) as fetch:
            third=signals.pull_daily_data('2026-11-13',risk,now+timedelta(minutes=31))
        fetch.assert_called_once()
        self.assertEqual(fetch.call_args.args[0],'000002')
        self.assertEqual(third['coverage']['errors'],0)

    def test_new_session_does_not_reuse_old_marks(self):
        now=datetime(2026,11,16,10,tzinfo=timezone(timedelta(hours=8)))
        risk={'stocks':{'000001':{'excluded':False}}}
        with patch.object(signals,'cached_history',return_value=self.frame) as fetch:
            signals.pull_daily_data('2026-11-13',risk,now)
            signals.pull_daily_data('2026-11-16',risk,now)
        self.assertEqual(fetch.call_count,2)

    def test_invalid_primary_falls_back_without_splicing(self):
        bad=self.frame.copy();bad.loc[0,'open']=0
        with patch.object(signals.ak,'stock_zh_a_daily_sina',return_value=bad), patch.object(signals.ak,'stock_zh_a_hist_tx',return_value=self.frame) as backup:
            frame,source=signals.remote_history('000001','2026-11-13','market')
        self.assertEqual(source,'tencent')
        self.assertEqual(len(frame),len(self.frame))
        self.assertEqual(backup.call_args.kwargs['adjust'],'hfq')

    def test_preferred_source_and_raw_adjustment(self):
        signals.save(signals.ROOT/'source_preferences.json',{'000001':'tencent'})
        with patch.object(signals.ak,'stock_zh_a_daily_sina') as primary, patch.object(signals.ak,'stock_zh_a_hist_tx',return_value=self.frame) as backup:
            frame,source=signals.remote_history('000001','2026-11-13','raw')
        primary.assert_not_called()
        self.assertEqual(backup.call_args.kwargs['adjust'],'')
        self.assertEqual(source,'tencent')

    def test_invalid_replacement_preserves_existing_snapshot(self):
        path=signals.ROOT/'market/2026-11-13/000001.csv'
        self.write(path,self.frame)
        original=path.read_bytes()
        bad=self.frame.copy();bad.loc[0,'open']=0
        with self.assertRaises(ValueError):
            signals.store_history('000001','2026-11-13','market',bad,'tencent')
        self.assertEqual(path.read_bytes(),original)


if __name__=='__main__': unittest.main()
