"""Download current mainland A-share daily history via AKShare/Eastmoney."""
import argparse
import concurrent.futures
import json
import time
import os
from pathlib import Path

import akshare as ak
import pandas as pd
import requests

# Bound each underlying HTTP request, including list requests.
_request = requests.sessions.Session.request
def bounded_request(self, method, url, **kwargs):
    kwargs.setdefault('timeout', 30)
    return _request(self, method, url, **kwargs)
requests.sessions.Session.request = bounded_request

FIELDS = {'日期': 'date', '股票代码': 'code', '开盘': 'open', '收盘': 'close',
          '最高': 'high', '最低': 'low', '成交量': 'volume', '成交额': 'amount',
          '振幅': 'amplitude', '涨跌幅': 'pct_change', '涨跌额': 'change', '换手率': 'turnover'}

def atomic_json(path, value):
    temp = path.with_name(path.name + f'.{os.getpid()}.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    for attempt in range(10):
        try:
            temp.replace(path)
            return
        except PermissionError:
            if attempt == 9:
                raise
            time.sleep(0.2 * (attempt + 1))

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--end', default='20261114')
    parser.add_argument('--workers', type=int, default=2)
    parser.add_argument('--limit', type=int, default=0)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent / 'data' / ('a_share_' + args.end)
    daily = root / 'daily_hfq'
    daily.mkdir(parents=True, exist_ok=True)
    universe_path = root / 'universe.csv'
    if universe_path.exists():
        universe = pd.read_csv(universe_path, dtype={'code': str})
    else:
        universe = ak.stock_info_a_code_name()
        universe['code'] = universe['code'].astype(str).str.zfill(6)
        if len(universe) < 4000 or universe['code'].duplicated().any():
            raise ValueError('Universe validation failed')
        universe.to_csv(universe_path, index=False, encoding='utf-8-sig')
    codes = universe['code'].tolist()
    if args.limit:
        codes = codes[:args.limit]
    print(f'Universe={len(universe)}, requested={len(codes)}', flush=True)

    def download(code):
        path = daily / f'{code}.csv'
        meta = daily / f'{code}.json'
        if path.exists() and meta.exists():
            return json.loads(meta.read_text(encoding='utf-8'))
        for attempt in range(3):
            try:
                prefix = 'sh' if code.startswith('6') else 'sz' if code.startswith(('0', '3')) else 'bj'
                frame = ak.stock_zh_a_daily_sina(symbol=prefix+code,
                    start_date='19900101', end_date=args.end, adjust='hfq')
                if frame.empty:
                    raise ValueError('Empty history')
                frame = frame.rename(columns=FIELDS)
                frame['date'] = pd.to_datetime(frame['date']).dt.strftime('%Y-%m-%d')
                frame = frame.sort_values('date')
                if frame['date'].duplicated().any() or frame['close'].isna().any() or (frame['close'] <= 0).any():
                    raise ValueError('Invalid dates or closes')
                if frame['date'].max().replace('-', '') > args.end:
                    raise ValueError('History exceeds requested cutoff')
                frame['code'] = code
                temp = path.with_suffix('.tmp')
                frame.to_csv(temp, index=False, encoding='utf-8-sig')
                temp.replace(path)
                result = dict(code=code, status='ok', rows=len(frame),
                    first_date=frame['date'].iloc[0], last_date=frame['date'].iloc[-1],
                    source='AKShare/Sina', adjustment='hfq', requested_end=args.end)
                atomic_json(meta, result)
                time.sleep(0.8)
                return result
            except Exception as error:
                if attempt == 2:
                    return dict(code=code, status='failed', error=str(error))
                time.sleep(2 ** attempt)

    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        for result in pool.map(download, codes):
            results.append(result)
            if len(results) % 25 == 0 or result['status'] != 'ok':
                print(f"{len(results)}/{len(codes)} {result['code']} {result['status']}", flush=True)
            try:
                atomic_json(root / 'manifest.json', results)
            except PermissionError as error:
                # Per-stock JSON remains the resumable source of truth.
                print(f'Progress snapshot temporarily unavailable: {error}', flush=True)
    failed = [r for r in results if r['status'] != 'ok']
    summary = dict(universe=len(universe), requested=len(codes), succeeded=len(results)-len(failed),
                   failed=len(failed), total_rows=sum(r.get('rows', 0) for r in results),
                   scope='Currently listed A shares; delisted securities excluded',
                   adjustment='hfq', cutoff=args.end, akshare_version=ak.__version__)
    atomic_json(root / 'summary.json', summary)
    atomic_json(root / 'failures.json', failed)
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    return bool(failed)

if __name__ == '__main__':
    raise SystemExit(main())
