from pathlib import Path
import shutil,datetime
b=Path('D:/张竹轩')
backup=b/'data/daily_signals/migrations'/('close-fallback-'+datetime.datetime.now().strftime('%Y%m%dT%H%M%S'))
backup.mkdir(parents=True,exist_ok=True)
for name in ['daily_signals.py','close_entry.py','unified_records.py','dashboard/daily.html','data/daily_signals/ledger.json','data/daily_signals/latest.json','data/daily_signals/reports/2026-11-17.json']:
 p=b/name
 if p.exists():shutil.copy2(p,backup/name.replace('/','__'))
p=b/'daily_signals.py';s=p.read_text(encoding='utf-8')
needle='_request=requests.sessions.Session.request'
s=s.replace(needle,"PRE_FALLBACK_RULES=copy.deepcopy(RULES)\nRULES={**RULES,'version':'2026-11-17-close-v8','missing_intraday_signal':'final_close_fallback'}\n"+needle)
s=s.replace("    args=parser.parse_args()","    parser.add_argument('--as-of',help='Recalculate the latest completed trading date only')\n    args=parser.parse_args()")
s=s.replace("if risk.get('date')!=today: risk=refresh()","if risk.get('date') not in (today,args.as_of): risk=refresh()")
s=s.replace("        target=calendar[-1]","        target=calendar[-1]\n        if args.as_of and args.as_of!=target: raise ValueError('--as-of must be the latest confirmed completed trading date')")
s=s.replace("        migration_needed=state['rules']!=RULES","        if state['rules']==PRE_FALLBACK_RULES:\n            backup=ROOT/'migrations'/('fallback-policy-'+now.strftime('%Y%m%dT%H%M%S'))\n            save(backup/'ledger_before.json',state)\n            state.setdefault('rule_migrations',[]).append(dict(date=today,from_rules=copy.deepcopy(state['rules']),to_rules=copy.deepcopy(RULES),positions_preserved=len(state['positions']),reason='用户确认：缺少14:40快照时按最终收盘信号与收盘价成交'))\n            state['rules']=copy.deepcopy(RULES)\n        migration_needed=state['rules']!=RULES")
s=s.replace("from close_entry import locked_signals,fill_close_orders","from close_entry import locked_signals,fill_close_orders,closing_fallback")
s=s.replace("        candidates=locked.get('candidates',[]) if locked else []","        if locked is None:\n            locked=closing_fallback(target,now,RULES['version'],frames,risk,state,today,errors)\n        candidates=locked.get('candidates',[]) if locked else []")
s=s.replace("report_date=today,signal_date=target,is_trading_day=target==today","report_date=target,signal_date=target,is_trading_day=True")
s=s.replace("save(ROOT/'reports'/f'{today}.json',report)","save(ROOT/'reports'/f'{target}.json',report)")
s=s.replace('成交展示为原始开盘价','成交展示为未复权收盘价')
s=s.replace('没有当日14:40快照时不补造信号。','没有有效14:40快照时，按该交易日最终收盘价与全天成交量计算信号并按收盘价成交，标记为收盘兜底，不冒充盘中快照。')
p.write_text(s,encoding='utf-8')
p=b/'close_entry.py';s=p.read_text(encoding='utf-8')
s=s.replace("if x.get('rules_version')!=version or x.get('date')!=day:","if (x.get('rules_version')!=version and not (version=='2026-11-17-close-v8' and x.get('rules_version')=='2026-11-17-close-v7')) or x.get('date')!=day:")
s+='''

def closing_fallback(day,now,version,frames,risk,state,screening_date,errors):
    """Persist final daily-bar signals separately; never fabricate intraday quotes."""
    from datetime import timezone,timedelta
    from daily_signals import candidate,save,load
    local=now.astimezone(timezone(timedelta(hours=8)))
    if day>local.date().isoformat() or (day==local.date().isoformat() and local.hour<16):
        raise ValueError('Closing fallback requires a confirmed completed trading session')
    path=ROOT/'close_signals'/f'{day}.json'
    saved=load(path)
    if saved is not None:
        if saved.get('rules_version')!=version or saved.get('date')!=day:raise ValueError('Closing snapshot rule/date mismatch')
        return saved
    held=set(state['positions'])|{x['code'] for x in state['closed_trades'] if x.get('exit_date')==day}
    selected=[]
    for code,df in sorted(frames.items()):
        try:
            visible=df[df.date<=day]
            item=candidate(code,visible,risk,screening_date,day)
            if item:
                prior=visible.iloc[-2]
                item.update(reference_previous_date=prior.date,reference_previous_hfq=float(prior.close),
                    entry_execution='same_day_close',signal_source='final_close_fallback',
                    status='已有持仓，不重复买入' if code in held else '收盘兜底信号，按当日收盘价模拟买入')
                selected.append(item)
        except Exception as e:errors.append(dict(code=code,error='Closing selection: '+str(e)))
    snapshot=dict(date=day,rules_version=version,captured_at=local.isoformat(),quote_time='close',
        source='final_close_fallback',candidates=[x for x in selected if x['code'] not in held],
        all_selected=selected,coverage=dict(requested=len(frames),errors=len(errors)))
    save(path,snapshot)
    return snapshot
'''
p.write_text(s,encoding='utf-8')
p=b/'unified_records.py';s=p.read_text(encoding='utf-8')
s=s.replace("    if frozen.exists():\n        saved=read(frozen)","    if not frozen.exists():frozen=BASE/'data/daily_signals/close_signals'/f'{signal_date}.json'\n    if frozen.exists():\n        saved=read(frozen)")
s=s.replace('parts=[f"14:40信号价{item[', 'label="收盘兜底信号价" if saved.get("source")=="final_close_fallback" else "14:40信号价"\n            parts=[f"{label}{item[')
p.write_text(s,encoding='utf-8')
p=b/'dashboard/daily.html';s=p.read_text(encoding='utf-8').replace('14:40—15:00采集14:40信号，当日收盘价记模拟成交','14:40—15:00采集14:40信号；未采集时用最终收盘信号兜底，均按当日收盘价记模拟成交').replace('现行买入为14:40信号（仅当天14:40—15:00采集）、当天收盘价成交','现行买入优先使用14:40信号，缺少时按最终收盘信号兜底；均按当天收盘价成交').replace('T+1，T+1','T+1')
p.write_text(s,encoding='utf-8')
print(str(backup))
