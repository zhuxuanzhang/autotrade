"""Refresh today's name-based ST/delisting screen; preserves price history."""
import json
import os
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent / 'data' / 'risk'

def china_today():
    return datetime.now(timezone(timedelta(hours=8))).date().isoformat()

def name_is_risky(name):
    name = re.sub(r'\s+', '', str(name)).upper()
    return 'ST' in name or '退' in name

def refresh():
    import akshare as ak
    ROOT.mkdir(parents=True, exist_ok=True)
    frame = ak.stock_info_a_code_name()
    frame['code'] = frame['code'].astype(str).str.zfill(6)
    if len(frame) < 4000 or frame['code'].duplicated().any() or frame['name'].isna().any():
        raise ValueError('Incomplete or invalid stock name snapshot; not publishing')
    extra_path = ROOT / 'extra_exclusions.json'
    extra = json.loads(extra_path.read_text(encoding='utf-8')) if extra_path.exists() else {}
    if not isinstance(extra, dict):
        raise ValueError('extra_exclusions.json must map stock codes to reasons')
    snapshot = dict(date=china_today(), source='AKShare current exchange stock names',
        coverage='ST/*ST/delisting name markers plus explicit supplemental exclusions; not a complete announcement risk assessment',
        stocks={})
    for row in frame.itertuples(index=False):
        snapshot['stocks'][row.code] = dict(name=row.name,
            excluded=name_is_risky(row.name) or row.code in extra,
            reason=extra.get(row.code) or ('ST or delisting name marker' if name_is_risky(row.name) else ''))
    for filename in (snapshot['date'] + '.json', 'latest.json'):
        path = ROOT / filename
        temp = path.with_name(path.name + f'.{os.getpid()}.tmp')
        temp.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding='utf-8')
        temp.replace(path)
    print(json.dumps(dict(date=snapshot['date'], stocks=len(frame),
        excluded=sum(s['excluded'] for s in snapshot['stocks'].values())), ensure_ascii=False))
    return snapshot

if __name__ == '__main__':
    refresh()
