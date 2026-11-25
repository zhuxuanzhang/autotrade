"""Local-only A-share dashboard. Run with the workspace Python."""
import records_store
import unified_records
import csv
import json
import re
import subprocess
import sys
import threading
from pathlib import Path
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

BASE = Path(__file__).resolve().parent
DATA = BASE / 'data/a_share_20261114/daily_hfq'
LOCK = threading.Lock()
PROCESS = None
LOG = None
DAILY_PROCESS = None
DAILY_LOG = None

class Handler(BaseHTTPRequestHandler):
    def send(self, value, status=200, content_type='application/json; charset=utf-8'):
        body = value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        route = urlparse(self.path)
        try:
            if route.path == '/':
                return self.send((BASE/'dashboard/daily.html').read_bytes(), content_type='text/html; charset=utf-8')
            if route.path == '/daily':
                return self.send((BASE/'dashboard/daily.html').read_bytes(), content_type='text/html; charset=utf-8')
            if route.path == '/pull-data.js':
                return self.send((BASE/'dashboard/pull-data.js').read_bytes(), content_type='application/javascript; charset=utf-8')
            if route.path == '/trade-chart.js':
                return self.send((BASE/'dashboard/trade-chart.js').read_bytes(), content_type='application/javascript; charset=utf-8')
            if route.path == '/market-amount.js':
                return self.send((BASE/'dashboard/market-amount.js').read_bytes(), content_type='application/javascript; charset=utf-8')
            if route.path == '/api/market-amount-marks':
                import market_amount_marks
                return self.send(market_amount_marks.snapshot())
            if route.path == '/api/chart':
                import chart_data
                q=parse_qs(route.query)
                return self.send(chart_data.history(q.get('code',[''])[0],q.get('date',[''])[0],q.get('basis',['hfq'])[0],
                                                    replay=q.get('source',[''])[0]=='replay'))
            if route.path == '/api/records-dates':
                return self.send(records_store.dates())
            if route.path == '/api/return-trades':
                import return_history
                q=parse_qs(route.query);day=q.get('date',[''])[0];year=q.get('year',[''])[0]
                if not re.fullmatch(r'\d{4}',year):return self.send({'error':'Invalid entry year'},400)
                try:return self.send(return_history.returns(day,int(year)))
                except ValueError as error:return self.send({'error':str(error)},400)
            if route.path == '/api/records-day':
                day=parse_qs(route.query).get('date',[''])[0]
                if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',day):return self.send({'error':'Invalid date'},400)
                try:return self.send(records_store.day(day))
                except ValueError as error:return self.send({'error':str(error)},404)
            if route.path == '/api/records-stats':
                q=parse_qs(route.query);start=q.get('start',[''])[0];end=q.get('end',[''])[0]
                if not all(re.fullmatch(r'\d{4}-\d{2}-\d{2}',d) for d in (start,end)) or start>end:return self.send({'error':'Invalid date range'},400)
                return self.send(records_store.stats(start,end))
            if route.path == '/api/capture-window':
                from capture_window import status
                return self.send(status())
            if route.path == '/api/daily-status':
                path=BASE/'data/daily_signals/run_status.json'
                status=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'status':'not_started'}
                if DAILY_PROCESS is not None:
                    code=DAILY_PROCESS.poll()
                    if code is None:
                        if status.get('status') != 'running':
                            status={'status':'running'}
                    elif code != 0 and status.get('status') != 'failed':
                        status={'status':'failed','error':'更新进程退出，请查看 reports/daily_update.log'}
                return self.send(status)
            if route.path == '/api/industries':
                profiles={}
                for profile_path in (BASE/'data/industry_profiles').glob('*.json'):
                    try:
                        profile=json.loads(profile_path.read_text(encoding='utf-8'))
                        profiles[profile_path.stem]=profile.get('industry') or '未分类'
                    except (OSError,ValueError):
                        continue
                return self.send(profiles)
            if route.path == '/api/daily-dates':
                return self.send(sorted([p.stem for p in (BASE/'data/daily_signals/reports').glob('????-??-??.json')],reverse=True))
            if route.path == '/api/daily':
                day=parse_qs(route.query).get('date',[''])[0]
                if day and not re.fullmatch(r'\d{4}-\d{2}-\d{2}',day):
                    return self.send({'error':'Invalid date'},400)
                path=(BASE/'data/daily_signals/reports'/f'{day}.json') if day else BASE/'data/daily_signals/latest.json'
                return self.send(json.loads(path.read_text(encoding='utf-8')))
            if route.path == '/backtest-daily-2026':
                self.send_response(302)
                self.send_header('Location','/daily?source=history')
                self.send_header('Content-Length','0')
                self.end_headers()
                return
            if route.path == '/api/backtest-daily-2026-dates':
                return self.send(json.loads((BASE/'experiments/current_rules_2026_20261116/daily/index.json').read_text(encoding='utf-8')))
            if route.path == '/api/backtest-daily-2026':
                day=parse_qs(route.query).get('date',[''])[0]
                if not re.fullmatch(r'2026-\d{2}-\d{2}',day):return self.send({'error':'Invalid date'},400)
                path=BASE/'experiments/current_rules_2026_20261116/daily'/f'{day}.json'
                if not path.exists():return self.send({'error':'No trading-session record'},404)
                return self.send(json.loads(path.read_text(encoding='utf-8')))
            if route.path == '/backtest-daily-2026-summary.csv':
                return self.send((BASE/'experiments/current_rules_2026_20261116/daily/summary.csv').read_bytes(), content_type='text/csv; charset=utf-8')
            if route.path == '/current-rules-2026':
                return self.send((BASE/'reports/current_rules/index.html').read_bytes(), content_type='text/html; charset=utf-8')
            replay_exports={
                '/current-rules-2026-annual.csv':'annual.csv',
                '/current-rules-2026-monthly.csv':'monthly.csv',
                '/current-rules-2026-trades.csv':'trades.csv',
            }
            if route.path in replay_exports:
                return self.send((BASE/'reports/current_rules'/replay_exports[route.path]).read_bytes(), content_type='text/csv; charset=utf-8')
            if route.path == '/two-year-range-200-400':
                return self.send((BASE/'experiments/two_year_range_200_400_20261116/results/index.html').read_bytes(), content_type='text/html; charset=utf-8')
            if route.path == '/two-year-range-200-400.csv':
                return self.send((BASE/'experiments/two_year_range_200_400_20261116/results/annual_comparison.csv').read_bytes(), content_type='text/csv; charset=utf-8')
            if route.path == '/two-year-range':
                return self.send((BASE/'experiments/two_year_range_2020_20261116/results/index.html').read_bytes(), content_type='text/html; charset=utf-8')
            if route.path == '/two-year-range.csv':
                return self.send((BASE/'experiments/two_year_range_2020_20261116/results/comparison.csv').read_bytes(), content_type='text/csv; charset=utf-8')
            if re.fullmatch(r'/two-year-range-trades/trades_0[0-9]\.csv',route.path):
                return self.send((BASE/'experiments/two_year_range_2020_20261116/results'/route.path.rsplit('/',1)[1]).read_bytes(), content_type='text/csv; charset=utf-8')
            if route.path == '/volume-down-bins-2020':
                return self.send((BASE/'experiments/volume_down_bins_2020_20261116/results/index.html').read_bytes(), content_type='text/html; charset=utf-8')
            if route.path == '/volume-down-bins-2020.csv':
                return self.send((BASE/'experiments/volume_down_bins_2020_20261116/results/comparison.csv').read_bytes(), content_type='text/csv; charset=utf-8')
            if re.fullmatch(r'/volume-down-bins-2020-trades/trades_(?:0[0-9]|1[0-4]|current)\.csv',route.path):
                return self.send((BASE/'experiments/volume_down_bins_2020_20261116/results'/route.path.rsplit('/',1)[1]).read_bytes(), content_type='text/csv; charset=utf-8')
            if route.path == '/execution-timing-2020':
                return self.send((BASE/'experiments/execution_timing_2020_20261116/results/index.html').read_bytes(), content_type='text/html; charset=utf-8')
            timing_files={'/execution-timing-2020.csv':'comparison.csv','/execution-timing-matched.csv':'matched_signals.csv',
                '/execution-timing-close_close.csv':'close_close_trades.csv','/execution-timing-open_open.csv':'open_open_trades.csv',
                '/execution-timing-close_open.csv':'close_open_trades.csv','/execution-timing-open_close.csv':'open_close_trades.csv'}
            if route.path in timing_files:
                return self.send((BASE/'experiments/execution_timing_2020_20261116/results'/timing_files[route.path]).read_bytes(), content_type='text/csv; charset=utf-8')
            if route.path == '/entry-month':
                return self.send((BASE/'experiments/volume_down_yearly_20261116/entry_month/index.html').read_bytes(), content_type='text/html; charset=utf-8')
            if route.path in ('/entry-month.csv','/entry-month-trades.csv'):
                filename='monthly.csv' if route.path=='/entry-month.csv' else 'trades.csv'
                return self.send((BASE/'experiments/volume_down_yearly_20261116/entry_month'/filename).read_bytes(), content_type='text/csv; charset=utf-8')
            if route.path == '/time-distribution':
                return self.send((BASE/'experiments/volume_down_yearly_20261116/time_distribution/index.html').read_bytes(), content_type='text/html; charset=utf-8')
            if route.path in ('/time-distribution-monthly.csv','/time-distribution-signals.csv','/time-distribution-buys.csv'):
                filename={'/time-distribution-monthly.csv':'monthly.csv','/time-distribution-signals.csv':'signals.csv','/time-distribution-buys.csv':'buys.csv'}[route.path]
                return self.send((BASE/'experiments/volume_down_yearly_20261116/time_distribution'/filename).read_bytes(), content_type='text/csv; charset=utf-8')
            if route.path in ('/volume-down-yearly', '/volume-down-study'):
                return self.send((BASE/'experiments/volume_down_yearly_20261116/results/index.html').read_bytes(), content_type='text/html; charset=utf-8')
            if route.path in ('/volume-down-yearly.csv', '/volume-down-study.csv'):
                return self.send((BASE/'experiments/volume_down_yearly_20261116/results/comparison.csv').read_bytes(), content_type='text/csv; charset=utf-8')
            if route.path == '/volume-down-same-year.csv':
                return self.send((BASE/'experiments/volume_down_yearly_20261116/results/same_year.csv').read_bytes(), content_type='text/csv; charset=utf-8')
            if route.path == '/volume-down-3y':
                return self.send((BASE/'experiments/volume_down_3y_20261116/results/index.html').read_bytes(), content_type='text/html; charset=utf-8')
            if route.path == '/volume-down-3y.csv':
                return self.send((BASE/'experiments/volume_down_3y_20261116/results/comparison.csv').read_bytes(), content_type='text/csv; charset=utf-8')
            if route.path == '/loss-analysis-2026':
                return self.send((BASE/'experiments/volume_down_3y_20261116/loss_analysis/index.html').read_bytes(), content_type='text/html; charset=utf-8')
            if route.path == '/loss-analysis-2026.csv':
                return self.send((BASE/'experiments/volume_down_3y_20261116/loss_analysis/trade_diagnostics.csv').read_bytes(), content_type='text/csv; charset=utf-8')
            if route.path == '/volume-down-study-original':
                return self.send((BASE/'experiments/volume_down_20261116/results/index.html').read_bytes(), content_type='text/html; charset=utf-8')
            if route.path == '/volume-down-study-original.csv':
                return self.send((BASE/'experiments/volume_down_20261116/results/comparison.csv').read_bytes(), content_type='text/csv; charset=utf-8')
            if route.path == '/backtest':
                return self.send((BASE/'reports/backtest/index.html').read_bytes(), content_type='text/html; charset=utf-8')
            if route.path == '/breakout-comparison':
                return self.send((BASE/'reports/breakout_comparison/index.html').read_bytes(), content_type='text/html; charset=utf-8')
            if route.path == '/pullback-comparison':
                return self.send((BASE/'reports/pullback_comparison/index.html').read_bytes(), content_type='text/html; charset=utf-8')
            if route.path == '/volume-comparison':
                return self.send((BASE/'reports/volume_comparison/index.html').read_bytes(), content_type='text/html; charset=utf-8')
            if route.path == '/exit-comparison':
                return self.send((BASE/'reports/exit_comparison/index.html').read_bytes(), content_type='text/html; charset=utf-8')
            if route.path == '/average-volume-comparison':
                return self.send((BASE/'reports/average_volume_comparison/index.html').read_bytes(), content_type='text/html; charset=utf-8')
            if route.path == '/volume-band-comparison':
                return self.send((BASE/'reports/volume_band_comparison/index.html').read_bytes(), content_type='text/html; charset=utf-8')
            if route.path == '/volume-bins':
                return self.send((BASE/'reports/volume_bins/index.html').read_bytes(), content_type='text/html; charset=utf-8')
            if route.path == '/backtest-trades.csv':
                return self.send((BASE/'reports/backtest/trades.csv').read_bytes(), content_type='text/csv; charset=utf-8')
            if route.path == '/api/state':
                report = json.loads((BASE/'reports/right_side_sectors.json').read_text(encoding='utf-8'))
                files = list(DATA.glob('*.csv'))
                report['download'] = dict(count=len(files), size_mb=round(sum(p.stat().st_size for p in files)/1048576, 1))
                report['refresh'] = dict(running=PROCESS is not None and PROCESS.poll() is None,
                    exit_code=PROCESS.poll() if PROCESS else None)
                report['download']['last_write'] = max((p.stat().st_mtime for p in files), default=0)
                return self.send(report)
            if route.path == '/api/history':
                code = parse_qs(route.query).get('code', [''])[0]
                if not re.fullmatch(r'\d{6}', code):
                    return self.send({'error': 'Invalid stock code'}, 400)
                with (DATA/f'{code}.csv').open(encoding='utf-8-sig', newline='') as handle:
                    rows = list(csv.DictReader(handle))[-120:]
                return self.send([dict(date=r['date'], close=float(r['close'])) for r in rows])
            if route.path == '/candidates.csv':
                return self.send((BASE/'reports/right_side_candidates.csv').read_bytes(), content_type='text/csv; charset=utf-8')
            return self.send({'error': 'Not found'}, 404)
        except (OSError, ValueError) as error:
            return self.send({'error': str(error)}, 503)

    def do_POST(self):
        global PROCESS, LOG
        global DAILY_PROCESS, DAILY_LOG
        if self.path == '/api/record-operation':
            return self.send({'error':'Manual operation tracking removed; executions follow strategy rules'},410)
        if self.path in ('/api/daily-update', '/api/daily-recalculate','/api/capture-1440-run'):
            if self.headers.get('Origin') != 'http://127.0.0.1:8765' or self.headers.get('Host') != '127.0.0.1:8765':
                return self.send({'error':'Local same-origin requests only'},403)
            if self.path == '/api/capture-1440-run':
                from capture_window import status
                gate=status()
                if not gate['enabled']:return self.send({'error':gate['reason']},409)
            with LOCK:
                if DAILY_PROCESS is not None and DAILY_PROCESS.poll() is None:
                    return self.send({'running':True},202)
                if self.path == '/api/daily-update':
                    from pull_fastpath import quick_pull_status
                    cached=quick_pull_status(BASE)
                    if cached is not None:return self.send(cached)
                if DAILY_LOG: DAILY_LOG.close()
                DAILY_LOG=(BASE/'reports/daily_update.log').open('w',encoding='utf-8')
                args=[sys.executable,'-B','-u',str(BASE/'daily_signals.py')]
                if self.path == '/api/capture-1440-run':
                    args=[sys.executable,'-B','-u',str(BASE/'manual_1440.py')]
                if self.path == '/api/daily-update':
                    args.extend(['--update','--pull-only'])
                DAILY_PROCESS=subprocess.Popen(args,cwd=BASE,
                    stdout=DAILY_LOG,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            return self.send({'running':True},202)
        if self.path != '/api/refresh':
            return self.send({'error': 'Not found'}, 404)
        if self.headers.get('Origin') != 'http://127.0.0.1:8765' or self.headers.get('Host') != '127.0.0.1:8765':
            return self.send({'error': 'Local same-origin requests only'}, 403)
        with LOCK:
            if PROCESS is not None and PROCESS.poll() is None:
                return self.send({'running': True}, 202)
            if LOG:
                LOG.close()
            LOG = (BASE/'reports/dashboard_refresh.log').open('w', encoding='utf-8')
            PROCESS = subprocess.Popen([sys.executable, '-u', str(BASE/'sector_report.py')], cwd=BASE,
                stdout=LOG, stderr=subprocess.STDOUT, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        self.send({'running': True}, 202)

if __name__ == '__main__':
    print('Local dashboard: http://127.0.0.1:8765', flush=True)
    ThreadingHTTPServer(('127.0.0.1', 8765), Handler).serve_forever()
