import json,copy,msvcrt
from datetime import datetime,timezone,timedelta
import pandas as pd
import daily_signals as s
from volume_down_filter import historical_volume_down
from two_year_range_filter import two_year_range
lock=(s.ROOT/'run.lock').open('a+b');lock.seek(0);lock.write(b'0');lock.flush();lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
state=s.load(s.ROOT/'ledger.json');before=copy.deepcopy(state)
key='2026-11-13-history-carry-v1'
if any(x.get('id')==key for x in state.get('history_carries',[])):
 print('ALREADY APPLIED');raise SystemExit(0)
now=datetime.now(timezone(timedelta(hours=8)));backup=s.ROOT/'migrations'/('history-carry-'+now.strftime('%Y%m%dT%H%M%S'))
s.save(backup/'ledger_before.json',state);s.save(backup/'latest_before.json',s.load(s.ROOT/'latest.json'))
opens=pd.read_csv(s.BASE/'experiments/current_rules_2026_20261116/results/open_01.csv',dtype={'code':str})
risk=s.load(s.RISK_ROOT/'latest.json');target=state['last_processed_market_date'];calendar=s.load(s.ROOT/'calendar.json')['dates']
imported=dict(positions={},pending_buys=[],closed_trades=[],cancelled=[],last_processed_market_date='2026-11-13',rules=copy.deepcopy(s.RULES))
frames={};raws={};details=[]
for t in opens.itertuples():
 code=t.code
 assert code not in state['positions'],'Existing position conflict '+code
 assert not any(x['code']==code and x.get('entry_date')==t.entry_date for x in state['closed_trades']),'Previously closed conflict'
 df=s.history(code,target,True);raw=s.raw_history(code,target,True)
 assert df.date.iloc[-1]==target and raw.date.iloc[-1]==target,'Current history incomplete '+code
 j=int(df.index[df.date.eq(t.signal_date)][0]);entry=s.row_at(raw,t.entry_date)
 assert entry is not None
 item=dict(code=code,name=risk['stocks'].get(code,{}).get('name',code),signal_date=t.signal_date,created_date=t.signal_date,
  breakout_hfq=float(df.close.iloc[j-20:j].max()),stop_hfq=float(df.low.iloc[j-4:j+1].min()),signal_close_hfq=float(df.close.iloc[j]),
  entry_date=t.entry_date,entry_price=float(entry.open),quantity=100,simulation=True,sell_order=None,trade_id=code+'-'+t.entry_date,
  entry_rule_version=s.RULES['version'],historical_volume_down_events=historical_volume_down(df,t.signal_date),two_year_range=two_year_range(df,t.signal_date),
  volume_ratio=float(df.volume.iloc[j-4:j+1].mean()/df.volume.iloc[j-19:j-4].mean()),
  provenance='historical_backtest_carry',history_carry_id=key,reasons=['2026年现行规则回测期末持仓带入；保留原买入日期和成本'])
 reasons,mark=s.sell_reasons(item,df,raw,'2026-11-13')
 if mark:item['mark']=mark
 if reasons:item['sell_order']=dict(signal_date='2026-11-13',reasons=reasons)
 # Reproduce original end-of-backtest HFQ return before any continuation.
 assert mark and abs(mark['net_return']-t.marked_net_return)<.0005,(code,mark,t.marked_net_return)
 imported['positions'][code]=item;frames[code]=df;raws[code]=raw
 details.append(dict(code=code,entry_date=t.entry_date,net_at_cutoff=mark['net_return'],exit_pending_at_cutoff=bool(reasons)))
for day in calendar:
 if '2026-11-13'<day<=target:s.process_day(imported,frames,raws,day,risk)
assert all(state['positions'].get(k)==v for k,v in before['positions'].items())
state['positions'].update(imported['positions']);state['closed_trades'].extend(imported['closed_trades'])
state.setdefault('history_carries',[]).append(dict(id=key,applied_at=now.isoformat(),cutoff='2026-11-13',continued_through=target,details=details,remaining=list(imported['positions']),closed=[x['code'] for x in imported['closed_trades']]))
s.save(s.ROOT/'ledger.json',state)
print(json.dumps(dict(imported=details,remaining=list(imported['positions']),closed=[x['code'] for x in imported['closed_trades']],total_positions=len(state['positions']),backup=str(backup)),ensure_ascii=True))
