"""Prepare dated Tencent-sheet exports locally; connector performs authorized uploads."""
import argparse,hashlib,json,sqlite3,sys
from pathlib import Path
from datetime import date
BASE=Path(__file__).resolve().parent
ROOT=BASE/'data/daily_signals'
SYNC=ROOT/'tencent_sync'
FILE_ID='DT25YR1dYeGZYVXpU'
def load(path,default=None):return json.loads(path.read_text(encoding='utf-8')) if path.exists() else default
def serial(value):return (date.fromisoformat(value)-date(1899,12,30)).days if value else None
def build(day,snapshot,report,market_entries=None):
 if market_entries is None:
  import market_amount_marks
  market_entries=market_amount_marks.snapshot()['entries']
 def market(x):
  value=market_entries.get(x.get('entry_date') or x.get('signal_date'))
  return [value['ratio'],'符合标记' if value['marked'] else '未标记'] if value else [None,'数据待补']
 marked_cells=[]
 source=(report.get('entry_signal_snapshot') or {}).get('source','历史收盘数据')
 rows=[['A股右侧策略每日记录',day],['信号口径','收盘兜底' if source=='final_close_fallback' else ('14:40信号' if (report.get('entry_signal_snapshot') or {}).get('quote_time')=='14:40' else source)],['成交口径','当日未复权收盘价；T+1；每笔100股；双边各0.2%估算成本'],['数据来源','本地网页每日策略账本'],[],['买卖操作'],['操作','代码','名称','买入日期','买入价格','买入量比','卖出日期','卖出价格','已实现净收益率','持股交易日','状态','沪深额比（买入前日）','额比标记']]
 operations=[dict(x) for x in snapshot.get('operations',[])]
 sell_events={(x['code'],x.get('entry_date')):x for x in snapshot.get('sell_events',[])}
 for x in operations:
  event=sell_events.get((x['code'],x.get('entry_date')))
  x['operation']='卖出' if x.get('exit_date')==day or event else ('买入' if not x.get('entry_date') or x.get('entry_date')==day else '持仓信号')
  if event and not x.get('exit_date'):
   x['sell_reason']=event.get('reason');x['status']='14:40卖出预警，待收盘确认'
 if (report.get('entry_signal_snapshot') or {}).get('quote_time')=='14:40':
  coverage=(report.get('entry_signal_snapshot') or {}).get('coverage',{})
  rows[3][1]+='；优先范围'+str(coverage.get('priority','未知'))+'只，有效14:40行情'+str(coverage.get('priority_quotes','未知'))+'只；缺价股票不伪造信号。'
 for x in operations:
  if market(x)[1]=='符合标记':marked_cells.append((len(rows),11,12))
  rows.append([x['operation'],x['code'],x.get('name'),serial(x.get('entry_date')),x.get('entry_price'),x.get('volume_ratio'),serial(x.get('exit_date')),x.get('exit_price'),x.get('net_return'),x.get('holding_bars'),x.get('status')]+market(x))
 if not operations:rows.append(['当日无买卖操作'])
 op_end=len(rows)-1
 rows.extend([[],['持仓与浮动收益'],['代码','名称','买入日期','买入价格','估值行情日','收盘价','估算净收益率','持股交易日','行情落后','沪深额比（买入前日）','额比标记']])
 if any(x.get('mark',{}).get('provisional') for x in report.get('positions',[])):rows[-1][5]='14:40价格'
 pos_header=len(rows)-1
 for x in snapshot.get('positions',[]):
  if market(x)[1]=='符合标记':marked_cells.append((len(rows),9,10))
  rows.append([x['code'],x.get('name'),serial(x.get('entry_date')),x.get('entry_open_hfq'),serial(x.get('quote_date')),x.get('close_hfq'),x.get('net_return'),x.get('holding_bars'),'是' if x.get('stale') else '否']+market(x))
 if not snapshot.get('positions'):rows.append(['当日无持仓'])
 pos_end=len(rows)-1
 rows.extend([[],['买卖原因'],['代码','名称','买入原因',None,None,None,'卖出原因']])
 reason_header=len(rows)-1
 for x in operations:
  rows.append([x['code'],x.get('name'),x.get('buy_reason'),None,None,None,x.get('sell_reason') if x.get('operation')=='卖出' else None])
 if not operations:rows.append(['当日无买卖原因记录'])
 reason_end=len(rows)-1
 merges=[]
 for r in range(reason_header,reason_end+1):
  for start,end in [(2,5),(6,10)]:merges.append(dict(start_row=r,end_row=r,start_col=start,end_col=end))
 for r in [1,2,3]:merges.append(dict(start_row=r,end_row=r,start_col=1,end_col=12))
 pending=[x for x in snapshot.get('buy_events',[]) if not x.get('execution_date') and '已有持仓' not in x.get('execution_status','')]
 if pending:
  rows.extend([[],['待收盘成交信号'],['代码','名称','信号日期','执行状态','沪深额比（信号前日）','额比标记']])
  for x in pending:rows.append([x['code'],x.get('name'),x.get('signal_date'),x.get('execution_status')]+market(x))
 rows[3][1]+='；沪深额比=买入前一交易日最近5日均额/此前10日均额（窗口不重叠）；1.13—1.20含边界或>1.45标绿；自2026-11-20起为正式买入条件。自2026-11-24起买入量比为1.40—1.70（含边界），且上证指数当日14:40须至少高于当日MA5的0.25%，盘中未通过或缺少报价时用同一阈值验证当日收盘信号；取消固定的5日最低价初始止损，均线退出改为连续三个交易日收盘低于各自MA20，时间退出改为持有满30个交易日且收盘不高于买入价。'
 if day>='2026-11-25': rows[3][1]+='；历史放量下跌仅保留信号日前4个自然月内当日收跌、较此前60日最高收盘价回撤20%—30%且事件3日均量/再往前15日均量为1.20—1.80，含边界。'
 cells=[]
 for r,row in enumerate(rows):
  for col,value in enumerate(row):
   cell=dict(row=r,col=col,value_type='NUMBER' if isinstance(value,(int,float)) and not isinstance(value,bool) else 'STRING')
   cell['number_value' if cell['value_type']=='NUMBER' else 'string_value']=value if value is not None else ''
   cells.append(cell)
 # Always blank a complete rectangular area to remove obsolete row/column tails.
 width=13
 occupied={(x['row'],x['col']) for x in cells}
 cells.extend(dict(row=r,col=c,value_type='STRING',string_value='') for r in range(len(rows)) for c in range(width) if (r,c) not in occupied)
 styles=[dict(start_row=0,end_row=len(rows)-1,start_col=0,end_col=12,font_family='Microsoft YaHei',font_size=11,vertical_align='top',wrap_text=True,number_format_pattern='General',bold=False,bg_color='FFFFFFFF',font_color='FF000000'),dict(start_row=0,end_row=0,start_col=0,end_col=12,bg_color='FF17365D',font_color='FFFFFFFF',bold=True,font_size=14)]
 for h in [5,6,pos_header-1,pos_header,reason_header-1,reason_header]:styles.append(dict(start_row=h,end_row=h,start_col=0,end_col=12,bg_color='FFDCE6F1',bold=True))
 for col in [3,6]:styles.append(dict(start_row=7,end_row=op_end,start_col=col,end_col=col,number_format_pattern='yyyy-mm-dd'))
 styles.extend([dict(start_row=7,end_row=op_end,start_col=8,end_col=8,number_format_pattern='0.00%'),dict(start_row=7,end_row=op_end,start_col=4,end_col=5,number_format_pattern='0.000'),dict(start_row=7,end_row=op_end,start_col=7,end_col=7,number_format_pattern='0.000')])
 for col in [2,4]:styles.append(dict(start_row=pos_header+1,end_row=pos_end,start_col=col,end_col=col,number_format_pattern='yyyy-mm-dd'))
 styles.append(dict(start_row=pos_header+1,end_row=pos_end,start_col=6,end_col=6,number_format_pattern='0.00%'))
 styles.extend([dict(start_row=7,end_row=op_end,start_col=11,end_col=11,number_format_pattern='0.0000'),dict(start_row=pos_header+1,end_row=pos_end,start_col=9,end_col=9,number_format_pattern='0.0000')])
 for row,left,right in marked_cells:styles.append(dict(start_row=row,end_row=row,start_col=left,end_col=right,bg_color='FFE5F5EF',font_color='FF087767',bold=True,number_format_pattern='0.0000'))
 dimensions=[dict(dimension_type='col',index=i,size=115) for i in range(13)]
 dimensions.extend(dict(dimension_type='row',index=i,size=(130 if reason_header<i<=reason_end and operations else 42 if i==0 else 32)) for i in range(len(rows)))
 dimensions.extend([dict(dimension_type='col',index=11,size=155),dict(dimension_type='col',index=12,size=115),dict(dimension_type='row',index=3,size=60)])
 payload=dict(date=day,file_id=FILE_ID,sheet_name=day,rows=len(rows),cols=width,values=cells,styles=styles,dimensions=dimensions,merges=merges,
  header_rows=[0,5,6,pos_header-1,pos_header,reason_header-1,reason_header],operation_end=op_end,position_header=pos_header,position_end=pos_end,reason_header=reason_header,reason_end=reason_end)
 payload['hash']=hashlib.sha256(json.dumps(payload,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
 return payload
def main():
 sys.stdout.reconfigure(encoding='utf-8')
 p=argparse.ArgumentParser();p.add_argument('--date');p.add_argument('--ack');p.add_argument('--sheet-id');p.add_argument('--hash');a=p.parse_args()
 SYNC.mkdir(parents=True,exist_ok=True)
 manifest=load(SYNC/'manifest.json',{})
 if a.ack:
  payload=load(SYNC/(a.ack+'.json'))
  if not payload or payload['hash']!=a.hash or not a.sheet_id:raise ValueError('Acknowledgement requires matching payload hash and sheet ID')
  manifest[a.ack]=dict(hash=a.hash,sheet_id=a.sheet_id,rows=payload['rows'],cols=payload['cols'])
  from daily_signals import save
  save(SYNC/'manifest.json',manifest)
  queue_path=ROOT/'intraday_supplement'/(a.ack+'.json');queue=load(queue_path)
  if queue and queue.get('status') in ('pending_sync','partial'):
   queue.update(status='ready_to_supplement',synced_hash=a.hash);save(queue_path,queue)
  completion_path=ROOT/'data_completion'/(a.ack+'.json');completion=load(completion_path)
  if completion and completion.get('status')=='pending_sync':
   completion.update(status='ready_to_supplement',synced_hash=a.hash);save(completion_path,completion)
  print(json.dumps(dict(acknowledged=a.ack)));return
 import market_amount_marks
 from datetime import datetime,timezone,timedelta
 market_amount_marks.refresh_missing(datetime.now(timezone(timedelta(hours=8))).date().isoformat())
 latest=load(ROOT/'latest.json',{})
 day=a.date or latest.get('signal_date')
 from daily_signals import save
 # Recheck dates already registered as well, so later corrections update their own tab.
 days={day}|set(manifest)|{p.stem for p in SYNC.glob('????-??-??.json')}
 con=sqlite3.connect(ROOT/'records.sqlite3')
 try:
  for current in sorted(days):
   row=con.execute('SELECT payload FROM daily WHERE date=?',(current,)).fetchone()
   if not row:
    if current==day:raise ValueError('No published report for '+str(current))
    continue
   report=load(ROOT/'reports'/(current+'.json'),{})
   payload=build(current,json.loads(row[0]),report)
   existing=load(SYNC/(current+'.json'),{})
   if existing.get('hash')!=payload['hash']:save(SYNC/(current+'.json'),payload)
 finally:con.close()
 pending=[]
 for path in sorted(SYNC.glob('????-??-??.json')):
  x=load(path);previous=manifest.get(x['date'],{})
  if previous.get('hash')!=x['hash']:
   x['previous_sync']=previous;pending.append(x)
 print(json.dumps(dict(pending=pending),ensure_ascii=False))
if __name__=='__main__':main()
