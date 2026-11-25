"""Display-only SH+SZ turnover annotations; never reads or writes trade decisions."""
import csv
import io
import json
import math
import threading
import time
import warnings
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent
ROOT = BASE / 'data/market_amount'
LOCK = threading.Lock()
REFRESHING = False
LAST_ATTEMPT = 0.
CACHE = None
CACHE_KEY = None


BUY_FILTER = dict(minimum=1.13, maximum=1.20, above=1.45,
                  recent_sessions=5, previous_sessions=10, effective_from='2026-11-20')


def selected(ratio):
    return math.isfinite(ratio) and (
        BUY_FILTER['minimum'] <= ratio <= BUY_FILTER['maximum'] or ratio > BUY_FILTER['above']
    )


def buy_gate(day, sessions):
    """Decide whether the confirmed preceding sessions permit a new buy."""
    if day < BUY_FILTER['effective_from']:
        return dict(status='inactive', allowed=True)
    window = sorted({date for date in sessions if date < day})[-15:]
    if len(window) != 15:
        return dict(status='missing', allowed=False, reason='买入日前不足15个已确认交易日')
    try:
        rows = amounts()
        for date in window:
            if date not in rows:
                rows[date] = fetch_day(date, save_raw=False)
        value = entry_values(rows, [*window, day], day)[day]
    except Exception as error:
        return dict(status='missing', allowed=False, reason=str(error))
    return dict(status='passed' if value['marked'] else 'blocked',
                allowed=value['marked'], ratio=value['ratio'],
                reference_date=value['reference_date'])



def calendar():
    dates = list(json.loads((BASE/'data/daily_signals/calendar.json').read_text(encoding='utf-8'))['dates'])
    report_path = BASE/'data/daily_signals/latest.json'
    if report_path.exists():
        report = json.loads(report_path.read_text(encoding='utf-8'))
        day = report.get('signal_date', '')
        if report.get('is_trading_day') and dates and day > dates[-1]:
            dates.append(day)
    return dates


def amounts():
    path = ROOT/'amounts.csv'
    if not path.exists():
        return {}
    with path.open(encoding='utf-8-sig', newline='') as handle:
        rows = list(csv.DictReader(handle))
    result = {}
    for row in rows:
        values = [float(row[k]) for k in ('sh_amount', 'sz_amount', 'amount')]
        if not all(math.isfinite(v) and v > 0 for v in values):
            raise ValueError('成交额无效：'+row['date'])
        if not math.isclose(values[0]+values[1], values[2], rel_tol=1e-12):
            raise ValueError('沪深成交额合计不一致：'+row['date'])
        if row['date'] in result:
            raise ValueError('成交额日期重复：'+row['date'])
        result[row['date']] = row
    return result


def entry_values(rows, dates, today):
    result = {}
    for i, day in enumerate(dates):
        if day < '2020-01-01' or day > today or i < 15:
            continue
        window = dates[i-15:i]
        # Require all 15 actual sessions. No forward fill, zero fill or skipping gaps.
        if not all(d in rows for d in window):
            continue
        values = [float(rows[d]['amount']) for d in window]
        recent, earlier = sum(values[-5:])/5, sum(values[:10])/10
        ratio = recent/earlier
        result[day] = dict(ratio=ratio, marked=selected(ratio), reference_date=window[-1],
                           recent5_mean=recent, preceding10_mean=earlier)
    return result


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False), encoding='utf-8')
    temp.replace(path)


def fetch_day(day, *, save_raw=True):
    """Only the two exchanges' stock statistics, excluding B shares/funds/bonds."""
    import requests
    import pandas as pd
    headers = {'Referer':'https://www.sse.com.cn/', 'User-Agent':'Mozilla/5.0'}
    if day < '2021-12-27':
        response = requests.get('https://query.sse.com.cn/marketdata/tradedata/queryTradingByProdTypeData.do',
                                params={'prodType':'gp','searchDate':day}, headers=headers, timeout=20)
        response.raise_for_status()
        raw = response.json()
        sh = {str(x['productType']):x for x in raw['result']}
        if any(sh[k]['searchDate'] != day for k in ('1','37')):
            raise ValueError('沪市成交额日期不一致')
        sh_amount = sum(float(sh[k]['trdAmt1'])*1e8 for k in ('1','37'))
    else:
        response = requests.get('https://query.sse.com.cn/commonQuery.do', params={
            'sqlId':'COMMON_SSE_SJ_GPSJ_CJGK_MRGK_C','PRODUCT_CODE':'01,02,03,11,17',
            'type':'inParams','SEARCH_DATE':day}, headers=headers, timeout=20)
        response.raise_for_status()
        raw = response.json()
        sh = {str(x['PRODUCT_CODE']):x for x in raw['result']}
        if any(sh[k]['TRADE_DATE'] != day.replace('-','') for k in ('01','03')):
            raise ValueError('沪市成交额日期不一致')
        sh_amount = sum(float(sh[k]['TRADE_AMT'])*1e8 for k in ('01','03'))
    response = requests.get('https://www.szse.cn/api/report/ShowReport', params={
        'SHOWTYPE':'xlsx','CATALOGID':'1803_sczm','TABKEY':'tab1','txtQueryDate':day}, timeout=25)
    response.raise_for_status()
    with warnings.catch_warnings():
        warnings.filterwarnings('ignore', message='Workbook contains no default style')
        frame = pd.read_excel(io.BytesIO(response.content))
    parts = {}
    for row in frame.to_dict('records'):
        name = str(row['证券类别']).strip()
        if name in ('主板A股','创业板A股','中小板','中小企业板','中小板A股'):
            parts[name] = float(str(row['成交金额(元)']).replace(',',''))
    if not {'主板A股','创业板A股'} <= parts.keys():
        raise ValueError('深市A股成交额分项缺失')
    if day < '2021-04-06' and not any(k in parts for k in ('中小板','中小企业板','中小板A股')):
        raise ValueError('深市历史中小板成交额缺失')
    sz_amount = sum(parts.values())
    if not all(math.isfinite(v) and v > 0 for v in (sh_amount, sz_amount)):
        raise ValueError('沪深成交额缺失或无效')
    if save_raw:
        atomic_json(ROOT/'official'/f'{day}.json', dict(date=day, sh_raw=raw, sz_parts=parts))
    return dict(date=day, sh_amount=sh_amount, sz_amount=sz_amount, amount=sh_amount+sz_amount)


def refresh_missing(today):
    global REFRESHING
    try:
        dates = [d for d in calendar() if d <= today]
        rows = amounts()
        # Only data before the latest known trade date is needed for entry annotations.
        missing = [d for d in dates[:-1] if d >= '2019-12-01' and d not in rows]
        for day in missing:
            rows[day] = fetch_day(day)
            path = ROOT/'amounts.csv'
            temp = path.with_suffix('.tmp')
            with temp.open('w', encoding='utf-8-sig', newline='') as handle:
                writer = csv.DictWriter(handle, fieldnames=['date','sh_amount','sz_amount','amount'])
                writer.writeheader()
                writer.writerows(rows[d] for d in sorted(rows))
            temp.replace(path)
        atomic_json(ROOT/'status.json', dict(status='complete', last_amount_date=max(rows, default=None)))
    except Exception as error:
        atomic_json(ROOT/'status.json', dict(status='unavailable', error=str(error)))
    finally:
        with LOCK:
            REFRESHING = False


def snapshot():
    global CACHE, CACHE_KEY, REFRESHING, LAST_ATTEMPT
    today = datetime.now(timezone(timedelta(hours=8))).date().isoformat()
    path = ROOT/'amounts.csv'
    cal_path = BASE/'data/daily_signals/calendar.json'
    latest_path = BASE/'data/daily_signals/latest.json'
    key = (path.stat().st_mtime_ns if path.exists() else 0, cal_path.stat().st_mtime_ns, latest_path.stat().st_mtime_ns if latest_path.exists() else 0, today)
    with LOCK:
        if CACHE_KEY != key:
            rows, dates = amounts(), calendar()
            CACHE = dict(signature='|'.join(map(str,key)), entries=entry_values(rows,dates,today),
                         last_amount_date=max(rows,default=None))
            CACHE_KEY = key
        # Background-only network I/O; HTTP serves cached annotations immediately.
        if not REFRESHING and time.monotonic()-LAST_ATTEMPT >= 300:
            REFRESHING = True
            LAST_ATTEMPT = time.monotonic()
            threading.Thread(target=refresh_missing, args=(today,), daemon=True).start()
        return CACHE
