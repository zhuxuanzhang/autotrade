import copy,json,msvcrt
from datetime import datetime,timezone,timedelta
import daily_signals as s
lock=(s.ROOT/'run.lock').open('a+b');lock.seek(0);lock.write(b'0');lock.flush();lock.seek(0)
msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
state=s.load(s.ROOT/'ledger.json');latest=s.load(s.ROOT/'latest.json');today=s.china_today()
now=datetime.now(timezone(timedelta(hours=8)))
backup=s.ROOT/'migrations'/('range-v3-'+now.strftime('%Y%m%dT%H%M%S'))
s.save(backup/'ledger_before.json',state);s.save(backup/'latest_before.json',latest)
frames={}
for order in state['pending_buys']:
 try:frames[order['code']]=s.history(order['code'],order['signal_date'],False)
 except Exception:pass
new=s.migrate_two_year_range_rules(state,frames,today)
assert new['positions']==state['positions'] and new['closed_trades']==state['closed_trades']
report=copy.deepcopy(latest);report['rules']=copy.deepcopy(s.RULES);report['buys']=copy.deepcopy(new['pending_buys']);report['cancelled']=new['cancelled'][-100:];report['rule_migrations']=new.get('rule_migrations',[])
report['notes']=report.get('notes',[])+['追加两年最高/最低收盘价比例≥200%且<400%，待买入已核验；该报告行情日期仍为原快照，新行情更新正在恢复。']
report['rules_updated_at']=now.isoformat()
s.save(s.ROOT/'ledger.json',new);s.save(s.ROOT/'latest.json',report)
if report.get('report_date')==today:s.save(s.ROOT/'reports'/f'{today}.json',report)
print(json.dumps(dict(version=new['rules']['version'],pending_before=len(state['pending_buys']),pending_after=len(new['pending_buys']),positions=len(new['positions']),signal_date=report['signal_date'],backup=str(backup)),ensure_ascii=True))
