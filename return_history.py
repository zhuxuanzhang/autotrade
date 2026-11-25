"""Read-only return-chart data, with historical cohorts kept outside the live ledger."""
import bisect,json,re
from functools import lru_cache
from pathlib import Path
import records_store
BASE=Path(__file__).resolve().parent
HIST=BASE/'experiments/historical_close_2020_2025'

@lru_cache(maxsize=32)
def cached_json(path,mtime,size):return json.loads(Path(path).read_text(encoding='utf-8'))
def read(path):
 stat=path.stat();return cached_json(str(path),stat.st_mtime_ns,stat.st_size)

def returns(asof,year):
 if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',asof) or not 2020<=int(year)<=int(asof[:4]):raise ValueError('Invalid date or entry year')
 year=int(year)
 available=records_store.dates()['dates']
 if year>=2026 or (available and year>=int(available[0][:4])):
  i=bisect.bisect_right(available,asof)-1
  rows=records_store.day(available[i]).get('transactions',[]) if i>=0 else []
  return dict(date=asof,year=year,transactions=[x for x in rows if x.get('entry_date','')[:4]==str(year) and x['entry_date']<=asof],source='existing_daily_ledger')
 rows=read(HIST/'results/trades.json')+read(HIST/'results/open_positions.json')
 folder=HIST/('daily' if asof<'2026-01-01' else 'carry_2026/daily')
 index=read(folder/'index.json');dates=index['dates'];i=bisect.bisect_right(dates,asof)-1
 marks={}
 if i>=0:
  day=read(folder/f'{dates[i]}.json')
  marks={(x['code'],x['entry_date']):x for x in day['positions']}
 out=[]
 for trade in rows:
  entry=trade['entry_date']
  if entry[:4]!=str(year) or entry>asof:continue
  sold=bool(trade.get('exit_date') and trade['exit_date']<=asof)
  mark=marks.get((trade['code'],entry),{})
  out.append(dict(code=trade['code'],name=trade['name'],trade_id=trade['trade_id'],entry_date=entry,
   entry_price=trade['entry_price'],exit_date=trade.get('exit_date') if sold else None,
   exit_price=trade.get('exit_price') if sold else None,net_return=trade.get('net_return') if sold else None,
   floating_return=None if sold else mark.get('net_return'),quote_date=mark.get('quote_date'),
   status='已卖出' if sold else '持仓中',price_basis='后复权'))
 return dict(date=asof,year=year,transactions=out,source='historical_supplement')
