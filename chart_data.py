"""Load a single local price series for a selected trade, without network requests."""
import csv,re
from datetime import datetime,timezone,timedelta
from pathlib import Path
import unified_records
BASE=Path(__file__).resolve().parent

def history(code,day,basis='hfq',*,replay=False):
    if day=='latest':
        day=datetime.now(timezone(timedelta(hours=8))).date().isoformat()
    if not re.fullmatch(r'\d{6}',code) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}',day):
        raise ValueError('Invalid chart selection')
    kind='raw' if basis=='raw' else 'market'
    if replay and basis!='raw':
        paths=[unified_records.history_path(code)]
    else:
        paths=sorted((BASE/'data/daily_signals'/kind).glob(f'*/{code}.csv'),reverse=True)
        if basis!='raw':paths.append(unified_records.history_path(code))
    best=[]
    for path in dict.fromkeys(paths):
        if not path.exists():continue
        with path.open(encoding='utf-8-sig',newline='') as f:
            rows=[dict(date=r['date'],close=float(r['close'])) for r in csv.DictReader(f)
                  if r['date']<=day and float(r['close'])>0]
        if rows and (not best or rows[-1]['date']>best[-1]['date']):best=rows
        if best and best[-1]['date']==day:break
    return dict(rows=best,basis=basis)
