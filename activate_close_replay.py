import copy,json,msvcrt,sqlite3
from datetime import datetime,timezone,timedelta
from pathlib import Path
import pandas as pd
import daily_signals as s
from volume_down_filter import historical_volume_down
from two_year_range_filter import two_year_range
root=s.BASE/'experiments/historical_close_2026_20261116';target='2026-11-16'
lock=(s.ROOT/'run.lock').open('a+b');lock.seek(0);lock.write(b'0');lock.flush();lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
old=s.load(s.ROOT/'ledger.json');latest=s.load(s.ROOT/'latest.json')
key='historical-close-close2026-through20261116'
if old.get('history_replay_id')==key:print('ALREADY ACTIVE');raise SystemExit(0)
backup=s.ROOT/'migrations'/('close-replay-'+datetime.now(timezone(timedelta(hours=8))).strftime('%Y%m%dT%H%M%S'))
s.save(backup/'ledger_before.json',old);s.save(backup/'latest_before.json',latest)
config=s.ROOT/'history_view.json'
if config.exists():s.save(backup/'history_view_before.json',s.load(config))
if (s.ROOT/'records.sqlite3').exists():
 source=sqlite3.connect(s.ROOT/'records.sqlite3');dest=sqlite3.connect(backup/'records_before.sqlite3');source.backup(dest);dest.close();source.close()
sources=s.load(root/'daily/sources.json');opens=pd.read_csv(root/'results/open_01.csv',dtype={'code':str});risk=s.load(s.RISK_ROOT/'latest.json')
state=dict(start_date='2026-01-01',rules=copy.deepcopy(s.RULES),positions={},pending_buys=[],closed_trades=[],cancelled=[],last_processed_market_date=target,history_replay_id=key,
 history_carries=[dict(id=key,cutoff=target,continued_through=target,remaining=opens.code.tolist(),closed=[],source='close-signal/close-execution replay, not14:40 history')],rule_migrations=old.get('rule_migrations',[]))
for t in opens.itertuples():
 df=s.validate(pd.read_csv(sources[t.code]));raw=s.raw_history(t.code,target,True)
 assert raw.date.iloc[-1]==target and df.date.iloc[-1]==target,'Missing latest data '+t.code
 j=int(df.index[df.date.eq(t.signal_date)][0]);rawentry=s.row_at(raw,t.entry_date)
 assert rawentry is not None
 c=df.close;v=df.volume
 item=dict(code=t.code,name=risk['stocks'].get(t.code,{}).get('name',t.code),signal_date=t.signal_date,created_date=t.signal_date,
  breakout_hfq=float(c.iloc[j-20:j].max()),stop_hfq=float(df.low.iloc[j-4:j+1].min()),signal_close_hfq=float(c.iloc[j]),
  entry_date=t.entry_date,entry_price=float(rawentry.close),quantity=100,simulation=True,sell_order=None,trade_id=t.code+'-'+t.entry_date,
  entry_rule_version=s.RULES['version'],historical_volume_down_events=historical_volume_down(df,t.signal_date),two_year_range=two_year_range(df,t.signal_date),
  volume_ratio=float(v.iloc[j-4:j+1].mean()/v.iloc[j-19:j-4].mean()),execution_mode='same_day_close',
  provenance='historical_close_replay',history_carry_id=key,reasons=['历史按当日收盘信号与收盘价重算；未来14:40锁定后收盘买入'])
 reasons,mark=s.sell_reasons(item,df,raw,target)
 if mark:item['mark']=mark
 if reasons:item['sell_order']=dict(signal_date=target,reasons=reasons)
 assert mark and abs(mark['net_return']-t.marked_net_return)<.001,(t.code,mark,t.marked_net_return)
 state['positions'][t.code]=item
s.save(s.ROOT/'ledger.json',state)
report=copy.deepcopy(latest);report.update(rules=s.RULES,history_carries=state['history_carries'],history_replay_id=key,positions=list(state['positions'].values()),closed_trades=[],cancelled=[],buys=[],selected_signals=[],sell_signals=[],generated_at=datetime.now(timezone(timedelta(hours=8))).isoformat())
report['notes']=['2026历史已按最终收盘信号及收盘买卖重新回放；历史不存在14:40快照，不能视作14:40回测。','以重算的期末8笔持仓继续跟踪；未来14:40锁定买入信号，收盘买入与卖出，T+1。旧记录已完整备份。']
s.save(s.ROOT/'latest.json',report);s.save(s.ROOT/'reports'/f'{target}.json',report)
s.save(config,dict(daily_path=str(root/'daily'),execution='close/close',signal_basis='historical final daily close',start='2026-01-01',end=target,replay_id=key))
print(json.dumps(dict(status='activated',open_positions=len(opens),backup=str(backup)),ensure_ascii=True))
