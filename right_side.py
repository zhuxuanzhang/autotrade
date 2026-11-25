"""Close-only daily breakout signals; signals are available after the close.

CSV: date,close (ISO dates, oldest first). Use consistently adjusted prices.
Run: python right_side.py prices.csv
"""

import argparse
import csv
import json
import math
import calendar
from datetime import date


def right_side_buy(closes, max_deviation=0.08, *, code=None,
                   listing_date=None, as_of=None, history_start=None,
                   risk_record=None, risk_date=None, screening_date=None):
    """Assess the latest completed session, using no future data.

    Requires code and a listing date (or an observed history start), as_of,
    and 65 closes. history_start is a conservative fallback, not an IPO date.
    This is an entry candidate, not a position manager.
    Thresholds are illustrative and have not been validated by backtesting.
    """
    if not math.isfinite(max_deviation) or max_deviation < 0:
        raise ValueError("max_deviation must be finite and nonnegative")
    prices = [float(value) for value in closes]
    if any(not math.isfinite(value) or value <= 0 for value in prices):
        raise ValueError("All closes must be finite and positive")
    symbol = str(code or '').strip().lower()
    for prefix in ('sh', 'sz', 'bj'):
        if symbol.startswith(prefix):
            symbol = symbol[2:]
            break
    for suffix in ('.sh', '.sz', '.bj'):
        if symbol.endswith(suffix):
            symbol = symbol[:-3]
            break
    valid_code = len(symbol) == 6 and symbol.isdigit()
    # Mainland A-share codes: Shanghai 6xxxxx; Shenzhen 0xxxxx/3xxxxx.
    # Exclude legacy Beijing 4/8 codes and the newer 920xxx codes.
    eligible_exchange = valid_code and symbol.startswith(('0', '3', '6'))
    eligible_exchange = eligible_exchange and not (
        str(code).lower().startswith('bj') or str(code).lower().endswith('.bj'))
    def parse_date(value):
        return value if isinstance(value, date) else date.fromisoformat(value)
    start = listing_date or history_start
    eligible_age = False
    eligibility_date = None
    if start is not None and as_of is not None:
        start = parse_date(start)
        end = parse_date(as_of)
        if start > end:
            raise ValueError('Listing/history start must not be after as_of')
        month_index = start.year * 12 + start.month - 1 + 6
        year, month = divmod(month_index, 12)
        month += 1
        eligibility_date = date(year, month, min(start.day, calendar.monthrange(year, month)[1]))
        eligible_age = end >= eligibility_date
    filters = {
        'mainland_sh_sz_a_share': eligible_exchange,
        'listed_at_least_six_calendar_months': eligible_age,
        'risk_snapshot_current': bool(risk_date and str(risk_date) == str(screening_date or as_of)),
        'not_st_or_flagged_delisting_risk': bool(
            isinstance(risk_record, dict) and risk_record.get('excluded') is False
            and risk_record.get('name')
            and 'ST' not in ''.join(risk_record['name'].upper().split())
            and '退' not in risk_record['name']),
    }
    eligibility = {
        'code': symbol,
        'checks': filters,
        'age_basis': 'listing_date' if listing_date else 'history_start_conservative' if history_start else 'missing',
        'eligible_from': eligibility_date.isoformat() if eligibility_date else None,
        'risk_record': risk_record,
        'risk_date': risk_date,
    }
    if not all(filters.values()):
        return dict(buy_signal=False, ready=False, eligibility=eligibility,
                    reason='Stock eligibility filter failed or metadata missing',
                    failed_checks=[name for name, passed in filters.items() if not passed])
    if len(prices) < 65:
        return {
            "buy_signal": False,
            "ready": False,
            "reason": "At least 65 trading-day closes are required",
            "observations": len(prices),
            "eligibility": eligibility,
        }

    close = prices[-1]
    ma20 = sum(prices[-20:]) / 20
    ma60 = sum(prices[-60:]) / 60
    ma20_previous = sum(prices[-25:-5]) / 20
    ma60_previous = sum(prices[-65:-5]) / 60
    # Exclude the signal day from the breakout reference.
    previous_high = max(prices[-21:-1])
    deviation = close / ma20 - 1
    checks = {
        "above_ma20": close > ma20,
        "ma20_above_ma60": ma20 > ma60,
        "ma20_rising": ma20 > ma20_previous,
        "ma60_not_falling": ma60 >= ma60_previous,
        "breakout_previous_20_closes": close > previous_high,
        "not_overextended": deviation <= max_deviation,
    }
    return {
        "buy_signal": all(checks.values()),
        "ready": True,
        "eligibility": eligibility,
        "checks": checks,
        "failed_checks": [name for name, passed in checks.items() if not passed],
        "metrics": {
            "close": close,
            "ma20": ma20,
            "ma60": ma60,
            "previous_20_close_high": previous_high,
            "deviation_from_ma20": deviation,
        },
    }


def read_prices(path):
    with open(path, encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not {"date", "close"}.issubset(reader.fieldnames or []):
            raise ValueError("CSV requires date and close columns")
        rows = list(reader)
    dates = [date.fromisoformat(row["date"]) for row in rows]
    if any(current <= previous for previous, current in zip(dates, dates[1:])):
        raise ValueError("Dates must be unique and sorted oldest first")
    return rows, [float(row["close"]) for row in rows]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_path")
    parser.add_argument("--max-deviation", type=float, default=0.08)
    parser.add_argument("--code", help="Six-digit stock code; defaults to CSV code column")
    parser.add_argument("--listing-date", help="Actual listing date YYYY-MM-DD; otherwise use earliest CSV date conservatively")
    args = parser.parse_args()
    from update_risk import ROOT, china_today, refresh
    rows, closes = read_prices(args.csv_path)
    codes = {row['code'].strip() for row in rows if row.get('code')}
    if len(codes) > 1:
        parser.error('CSV must contain only one stock')
    if args.code and codes and args.code not in codes:
        parser.error('--code conflicts with CSV code')
    risk_path = ROOT / 'latest.json'
    snapshot = json.loads(risk_path.read_text(encoding='utf-8')) if risk_path.exists() else {}
    if snapshot.get('date') != china_today():
        try:
            snapshot = refresh()
        except Exception as error:
            # Fail closed: stale risk information cannot generate a buy signal.
            snapshot = {'date': None, 'stocks': {}, 'error': str(error)}
    stock_code = args.code or next(iter(codes), None)
    result = right_side_buy(closes, args.max_deviation,
        code=stock_code, listing_date=args.listing_date,
        risk_record=snapshot.get('stocks', {}).get(stock_code),
        risk_date=snapshot.get('date'), screening_date=china_today(),
        as_of=rows[-1]['date'] if rows else None,
        history_start=rows[0]['date'] if rows else None)
    result["date"] = rows[-1]["date"] if rows else None
    print(json.dumps(result, ensure_ascii=False, indent=2))
