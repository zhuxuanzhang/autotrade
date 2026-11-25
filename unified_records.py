"""Read-only unified timeline and date-range trade statistics."""
import json,csv
from pathlib import Path
BASE=Path(__file__).resolve().parent
HIST_CONFIG=BASE/'data/daily_signals/history_view.json'
HIST=Path(json.loads(HIST_CONFIG.read_text(encoding='utf-8'))['daily_path']) if HIST_CONFIG.exists() else BASE/'experiments/current_rules_2026_20261116/daily'
def history_path(code):
    manifest=HIST/'sources.json'
    sources=read(manifest) if manifest.exists() else {}
    return Path(sources.get(code,str(BASE/'data/a_share_20261114/daily_hfq'/f'{code}.csv')))
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def archived_trades(index, *, include_open=True):
    root=HIST.parent/'results'
    if index.get('replace_previous_view'):
        return read(root/'trades.json')+(read(root/'open.json') if include_open else [])
    rows=[]
    for name in ('trades_01.csv','open_01.csv') if include_open else ('trades_01.csv',):
        with (root/name).open(encoding='utf-8-sig',newline='') as f:
            rows.extend(csv.DictReader(f))
    return rows

def active_trades(report,index,*,include_open=True):
    closed=report['closed_trades']
    if index.get('replace_previous_view'):
        closed=[trade for trade in closed if trade['exit_date']>index['end']]
    return closed+(report['positions'] if include_open else [])

def timeline():
    index=read(HIST/'index.json');dates=set(index['dates']);live={}
    replace=index.get('replace_previous_view',False)
    for path in sorted((BASE/'data/daily_signals/reports').glob('????-??-??.json')):
        r=read(path);day=r.get('signal_date','')
        if day>index['end'] or (not replace and day==index['end'] and r.get('entry_signal_snapshot')):
            live[day]=r;dates.add(day)
    latest=read(BASE/'data/daily_signals/latest.json')
    if latest.get('signal_date','')>index['end'] or (not replace and latest.get('signal_date')==index['end'] and latest.get('entry_signal_snapshot')):live[latest['signal_date']]=latest;dates.add(latest['signal_date'])
    return index,live,sorted(dates)
def snapshot(day):
    index,live,dates=timeline()
    if day not in dates:raise ValueError('该日期没有交易记录，休市不复制数据')
    if day<=index['end'] and day not in live:
        value=dict(read(HIST/f'{day}.json'))
        if index.get('entry_price_field')=='close':value.setdefault('coverage_note','历史按最终收盘信号与收盘买卖回放，遵守T+1。')
        return value
    r=live[day]
    def base(x):return dict(code=x['code'],name=x.get('name',x['code']),signal_date=x.get('signal_date'),entry_date=x.get('entry_date'),entry_open_hfq=x.get('entry_price'),quantity=x.get('quantity',100),position_source='历史持仓带入' if x.get('history_carry_id') else ('当日买入' if x.get('entry_date')==day else '前期持仓带入'))
    signals=[dict(x,date=x['signal_date'],close=x.get('raw_close'),breakout=x.get('breakout_reference'),stop=x.get('initial_stop_reference'),two_year_high_low_pct=x.get('two_year_range',{}).get('ratio_pct')) for x in r.get('selected_signals',r['buys']) if x['signal_date']==day]
    buys=[dict(base(x),entry_open_hfq=x.get('entry_price')) for x in r['positions']+r['closed_trades'] if x.get('entry_date')==day]
    sells=[dict(base(x),exit_date=x['exit_date'],exit_open_hfq=x['exit_price'],net_return=x['net_return'],holding_bars=x.get('holding_sessions'),reason='；'.join(x.get('exit_reasons',[]))) for x in r['closed_trades'] if x['exit_date']==day]
    positions=[]
    for x in r['positions']:
        m=x.get('mark',{});positions.append(dict(base(x),quote_date=m.get('mark_date'),close_hfq=m.get('last_raw_close'),net_return=m.get('net_return'),holding_bars=m.get('holding_sessions'),stale=m.get('mark_date')!=day))
    exits=[dict(code=x['code'],name=x['name'],entry_date=x.get('entry_date'),reason='；'.join(x.get('reasons',[]))) for x in r['sell_signals'] if x['signal_date']==day]
    if day==index['end']:
        baseline=read(HIST/f'{day}.json')
        def merge(a,b,key):return list({tuple(x.get(k) for k in key):x for x in a+b}.values())
        buys=merge(baseline['buys'],buys,['code','entry_date']);sells=merge(baseline['sells'],sells,['code','entry_date','exit_date'])
        exits=merge(baseline['exit_signals'],exits,['code','entry_date'])
    carries=r.get('history_carries',[])
    note='历史快照的期末持仓已按原买入日期和成本带入，每日按原规则继续跟踪。' if carries else '历史期末持仓续算信息待核验。'
    return dict(date=day,signals=signals,buys=buys,sells=sells,positions=positions,exit_signals=exits,
                price_basis='raw',coverage_note=note,history_start=index['start'],history_end=index['end'])
def stats(start,end):
    index,live,dates=timeline();selected=[d for d in dates if start<=d<=end]
    trades=[dict(code=x['code'],entry_date=x['entry_date'],exit_date=x['exit_date'],
                 net_return=float(x['net_return']),holding=float(x['holding_bars']))
            for x in archived_trades(index,include_open=False)]
    seen={(x['code'],x['entry_date'],x['exit_date']) for x in trades}
    for r in live.values():
        for x in active_trades(r,index,include_open=False):
            k=(x['code'],x['entry_date'],x['exit_date'])
            if k not in seen:trades.append(dict(code=x['code'],entry_date=x['entry_date'],exit_date=x['exit_date'],net_return=x['net_return'],holding=x.get('holding_sessions',0)));seen.add(k)
    closed=[x for x in trades if start<=x['exit_date']<=end]
    by_entry=[x for x in trades if start<=x['entry_date']<=end and x['exit_date']<=end]
    def calc(items):
        n=len(items);return dict(count=n,win_rate=sum(x['net_return']>0 for x in items)/n if n else None,mean_return=sum(x['net_return'] for x in items)/n if n else None,holding_days=sum(x['holding'] for x in items)/n if n else None)
    snaps=[snapshot(d) for d in selected]
    unextended=(0 if any(r.get('history_carries') for d,r in live.items() if d<=end) else 3) if end>index['end'] and not index.get('replace_previous_view') else 0
    return dict(start=start,end=end,trading_days=len(selected),buys=sum(len(x['buys']) for x in snaps),sells=sum(len(x['sells']) for x in snaps),realized=calc(closed),entry_cohort=calc(by_entry),last_positions=len(snaps[-1]['positions']) if snaps else 0,historical_open_not_extended=unextended)


def linked_events(day):
    data=snapshot(day)
    index,live,dates=timeline()
    trades=archived_trades(index)
    for date,r in live.items():
        if date<=day:trades+=active_trades(r,index)
    by_signal={(t['code'],t['signal_date']):t for t in trades if t.get('entry_date','')<=day}
    by_entry={(t['code'],t['entry_date']):t for t in trades if t.get('entry_date','')<=day}
    buys={};sells={}
    for row in data['signals']+data['buys']:
        signal=row.get('signal_date') or row.get('date')
        key=(row['code'],signal)
        if key in buys:buys[key].update({k:v for k,v in row.items() if v is not None})
        else:buys[key]=dict(row,signal_date=signal)
    for key,row in buys.items():
        trade=by_signal.get(key)
        row['event_id']='buy|'+row['code']+'|'+str(row['signal_date'])
        row['execution_date']=trade.get('entry_date') if trade else None
        row['execution_price']=row.get('entry_open_hfq') if trade else None
        if trade and row['execution_price'] is None:
            csvpath=history_path(row['code'])
            quote=price_history(row['code']).get(trade['entry_date'])
            if quote:row['execution_price']=float(quote[index.get('entry_price_field','open')])
        held=any(p['code']==row['code'] and p['entry_date']<=day for p in data['positions'])
        row['execution_status']='已模拟买入' if trade else ('已有持仓，未重复买入' if held else '收盘信号已产生，待后续开盘核验')
        if index.get('entry_price_field')=='close' and held and not trade:row['execution_status']='已有持仓，未重复买入'
        row['reason']=row.get('reason') or '满足现行选股条件；买入仍需后续开盘及持仓核验'
        if not trade and not held and row.get('entry_execution')=='same_day_close':
            row['execution_status']=row.get('status','14:40信号已锁定，等待当天收盘价')
        if not trade and not held and row.get('entry_execution')!='same_day_close':
            later=next((t for t in trades if t['code']==row['code'] and t.get('signal_date')==row['signal_date'] and day<t.get('entry_date','')<=dates[-1]),None)
            outcome=(dict(status='后续已于'+later['entry_date']+'模拟买入',date=later['entry_date'],reason='所选日期之后已完成模拟买入；本行买入日期和价格仍按所选日展示') if later else resolve_buy_signal(row['code'],row['signal_date'],dates[-1]))
            if outcome:
                row['execution_status']=outcome['status'];row['verification_date']=outcome['date'];row['unfilled_reason']=outcome['reason']

    for row in data['exit_signals']+data['sells']:
        trade=by_entry.get((row['code'],row['entry_date']))
        signal=(trade or {}).get('exit_signal_date') or row.get('signal_date') or day
        key=(row['code'],row['entry_date'],signal)
        if key in sells:sells[key].update(row)
        else:sells[key]=dict(row,signal_date=signal)
    for key,row in sells.items():
        trade=by_entry.get((row['code'],row['entry_date'])) or {}
        sold=trade.get('exit_date') and trade['exit_date']<=day
        row['event_id']='sell|'+row['code']+'|'+row['entry_date']+'|'+str(row['signal_date'])
        row['execution_date']=trade.get('exit_date') if sold else None
        row['execution_price']=row.get('exit_open_hfq') if sold else None
        if sold and row['execution_price'] is None:
            csvpath=history_path(row['code'])
            quote=price_history(row['code']).get(trade['exit_date'])
            if quote:row['execution_price']=float(quote[index.get('exit_price_field','open')])
        row['execution_status']='已模拟卖出' if sold else '卖出信号已产生，待后续可交易开盘'
    data['buy_events']=list(buys.values());data['sell_events']=list(sells.values())
    data['transactions']=complete_transactions(day,data)
    data['operations']=daily_operations(day,data)
    return data


def complete_transactions(day,data=None):
    data=data or snapshot(day)
    index,live,dates=timeline()
    names={}
    if not index.get('replace_previous_view'):
        with (BASE/'data/a_share_20261114/universe.csv').open(encoding='utf-8-sig',newline='') as f:
            names={r['code']:r['name'] for r in csv.DictReader(f)}
    records={}
    for t in archived_trades(index):
        if t['entry_date']<=day:records[(t['code'],t['entry_date'])]=dict(t,_historical=True)
    for date,r in sorted(live.items()):
        if date<=day:
            for t in active_trades(r,index):
                if t['entry_date']<=day:records[(t['code'],t['entry_date'])]=dict(t,_historical=False)
    positions={(p['code'],p['entry_date']):p for p in data['positions']}
    reason_names={'initial_stop':'跌破买入时固定5日最低价止损线','failed_breakout':'前5日跌破原突破位92%','ma20_two_closes':'连续2日收盘低于MA20','time_exit':'持有15日仍未盈利'}
    cache={};out=[]
    for key,t in records.items():
        code,entry=key;historical=t['_historical'];signal=t['signal_date'];sold=bool(t.get('exit_date') and t['exit_date']<=day)
        if historical and not t.get('entry_price'):
            if code not in cache:
                cache[code]=price_history(code)
            entry_price=float(cache[code][entry][index.get('entry_price_field','open')]);exit_price=float(cache[code][t['exit_date']][index.get('exit_price_field','open')]) if sold else None
            basis='后复权'
        else:entry_price=float(t['entry_price']);exit_price=float(t['exit_price']) if sold else None;basis='后复权' if historical else '未复权'
        pos=positions.get(key,{})
        exit_signal=t.get('exit_signal_date')
        if not exit_signal and t.get('sell_order'):exit_signal=t['sell_order'].get('signal_date')
        if exit_signal and exit_signal>day:exit_signal=None
        exit_reason=(t.get('exit_reason_text') or reason_names.get(t.get('exit_reason'),t.get('exit_reason')) if historical else
                     '；'.join(t.get('exit_reasons',[]) or (t.get('sell_order') or {}).get('reasons',[]))) if exit_signal else ''
        signal_data={}
        if (historical or not index.get('replace_previous_view')) and not t.get('buy_reason') and signal<=index['end'] and (HIST/f'{signal}.json').exists():
            signal_data=next((x for x in read(HIST/f'{signal}.json')['signals'] if x['code']==code),{})
        vr=t.get('volume_ratio',signal_data.get('volume_ratio'));ratio=(t.get('two_year_range') or {}).get('ratio_pct',t.get('two_year_high_low_pct',signal_data.get('two_year_high_low_pct')))
        history_reason='历史放量连跌9%—18%或回撤20%—30%条件通过'
        if not historical:
            from daily_signals import rules_for_day
            from volume_down_filter import describe_history_filter
            history_reason=describe_history_filter(rules_for_day(signal)['historical_volume_down'])+'，条件通过'
        buy_reason=t.get('buy_reason') if historical else None
        if not buy_reason:
            buy_reason=f'收盘突破前20日最高收盘价，均线趋势通过；{history_reason}；两年高低比[200%,400%)'
            if vr is not None:buy_reason+=f'；入场量比{float(vr):.3f}'
        holding=float(t.get('holding_bars',t.get('holding_sessions',0))) if sold else pos.get('holding_bars')
        out.append(dict(code=code,name=t.get('name',names.get(code,code)),signal_date=signal,entry_date=entry,entry_price=entry_price,exit_signal_date=exit_signal,exit_date=t.get('exit_date') if sold else None,exit_price=exit_price,buy_reason=buy_reason,sell_reason=exit_reason or '—',status='已卖出' if sold else ('待卖出' if exit_signal else '持有中'),quantity=t.get('quantity',100),price_basis=basis,holding_bars=holding,net_return=float(t['net_return']) if sold else None,floating_return=pos.get('net_return') if not sold else None,volume_ratio=float(vr) if vr is not None else None,two_year_high_low_pct=float(ratio) if ratio is not None else None))
    return sorted(out,key=lambda x:(x['entry_date'],x['code']),reverse=True)


from functools import lru_cache
@lru_cache(maxsize=2048)
def entry_evidence(code,signal_date):
    index=read(HIST/'index.json')
    if index.get('replace_previous_view') and index['start']<=signal_date<=index['end']:
        path=HIST/f'{signal_date}.json'
        if path.exists():
            item=next((x for x in read(path)['signals'] if x['code']==code),None)
            if item:return item['reason'],item.get('volume_ratio')
    for folder in ('intraday_signals','close_signals'):
        frozen=BASE/'data/daily_signals'/folder/f'{signal_date}.json'
        if not frozen.exists():continue
        saved=read(frozen)
        item=next((x for x in saved.get('all_selected',saved.get('candidates',[])) if x['code']==code),None)
        if item:
            label="收盘兜底信号价" if saved.get("source")=="final_close_fallback" else "14:40信号价"
            parts=[f"{label}{item['signal_close_hfq']:.3f}，突破参考{item['breakout_hfq']:.3f}（后复权）",f"MA20 {item['ma20']:.3f}、MA60 {item['ma60']:.3f}，偏离{item['deviation']:.2%}"]
            parts.extend(e['reason'] for e in item.get('historical_volume_down_events',[]))
            info=item.get('two_year_range')
            if info:parts.append(f"近两年高低比{info['ratio_pct']:.2f}%")
            return '；'.join(parts),item.get('volume_ratio')
    import pandas as pd
    from daily_signals import rules_for_day
    from volume_down_filter import historical_volume_down
    from two_year_range_filter import two_year_range
    paths=[history_path(code)]
    if signal_date>'2026-11-13':paths=sorted((BASE/'data/daily_signals/market').glob(f'*/{code}.csv'),reverse=True)+paths
    for path in paths:
        if not path.exists():continue
        df=pd.read_csv(path);df=df[df.date<=signal_date]
        if df.empty or df.date.iloc[-1]!=signal_date or len(df)<65:continue
        c=df.close.astype(float);v=df.volume.astype(float)
        ma20=float(c.iloc[-20:].mean());ma60=float(c.iloc[-60:].mean());anchor=float(c.iloc[-21:-1].max())
        prior=float(v.iloc[-20:-5].mean());vr=float(v.iloc[-5:].mean()/prior) if prior>0 else None
        ratio=two_year_range(df,signal_date)
        parts=[f'信号收盘{c.iloc[-1]:.3f}，前20日最高收盘{anchor:.3f}',f'MA20 {ma20:.3f}、MA60 {ma60:.3f}，偏离MA20 {(c.iloc[-1]/ma20-1)*100:.2f}%']
        for event in historical_volume_down(df,signal_date,rules_for_day(signal_date)['historical_volume_down']):
            label='连续3日累计下跌' if event['kind']=='consecutive' else '较此前60日高点回撤'
            parts.append(f"{event['event_date']} {label}{event['decline_pct']:.2f}%，当时量比{event['volume_ratio']:.3f}")
        if ratio:parts.append(f"近两年最高/最低收盘价比例{ratio['ratio_pct']:.2f}%")
        return '；'.join(parts)+'（价格为后复权）',vr
    return '信号日行情缺失，具体买入数据待核验',None

def daily_operations(day,data):
    records=data['transactions'];out={}
    for event in data['buy_events']+data['sell_events']:
        # Repeated qualification of an existing holding is evidence, not a new operation.
        if event in data['buy_events'] and not event.get('execution_date') and (
            '已有持仓' in event.get('execution_status','') or '未重复买入' in event.get('execution_status','')
        ):
            continue
        side='卖出' if event in data['sell_events'] else '买入'
        code=event['code'];entry=event.get('entry_date');signal=event.get('signal_date')
        candidates=[t for t in records if t['code']==code and ((entry and t['entry_date']==entry) or (not entry and t['signal_date']==signal))]
        if candidates:
            row=dict(candidates[0]);key=code+'|'+row['entry_date']
        else:
            row=dict(code=code,name=event.get('name',code),signal_date=signal,entry_date=None,entry_price=None,exit_date=None,exit_price=None,sell_reason=None,net_return=None,status=event.get('execution_status','待成交'),price_basis='后复权');key=code+'|signal|'+str(signal)
        row['operation']=side
        reason,vr=entry_evidence(code,row['signal_date'])
        row['buy_reason']=reason;row['volume_ratio']=vr
        row['verification_date']=event.get('verification_date')
        row['execution_note']=event.get('unfilled_reason','')
        if not row.get('exit_date'):
            row['exit_date']=None;row['exit_price']=None;row['sell_reason']=None
        out[key]=row
    return sorted(out.values(),key=lambda x:(x.get('entry_date') or x['signal_date'],x['code']),reverse=True)


@lru_cache(maxsize=4096)
def resolve_buy_signal(code,signal_date,latest_date):
    import pandas as pd
    paths=[history_path(code)]
    if signal_date>='2026-11-13':paths=sorted((BASE/'data/daily_signals/market').glob(f'*/{code}.csv'),reverse=True)+paths
    for path in paths:
        if not path.exists():continue
        df=pd.read_csv(path)
        found=df.index[df.date.eq(signal_date)]
        if not len(found):continue
        j=int(found[0])
        if j+1>=len(df) or df.date.iloc[j+1]>latest_date:continue
        current=df.iloc[j+1];signal=df.iloc[j]
        anchor=float(df.close.iloc[j-20:j].max());stop=float(df.low.iloc[j-4:j+1].min());price=float(current.open);risk=(price-stop)/price
        reasons=[]
        if current.volume<=0 or current.high-current.low<=1e-8:reasons.append('执行日无有效成交量或为一字行情')
        if price<=anchor:reasons.append(f'开盘{price:.3f}未高于突破位{anchor:.3f}')
        if price>signal.close*1.02:reasons.append(f'开盘{price:.3f}超过信号收盘价102%（{signal.close*1.02:.3f}）')
        if not 0<risk<=.08:reasons.append(f'开盘至止损{stop:.3f}距离{risk:.2%}，不满足大于0且不超过8%')
        if reasons:return dict(date=current.date,status='未成交（买入已取消）',reason='；'.join(reasons)+'（后复权）')
        # Other rejection causes must not be guessed from prices alone.
        return dict(date=current.date,status='未成交（执行记录待核验）',reason='开盘价格条件通过，但没有对应模拟成交记录，需核对当时持仓与执行记录')
    return None


@lru_cache(maxsize=1024)
def price_history(code):
    import pandas as pd
    df=pd.read_csv(history_path(code),usecols=['date','open','close'])
    df=df[(df.date>='2026-01-01')&(df.date<='2026-11-16')]
    return {r.date:dict(open=float(r.open),close=float(r.close)) for r in df.itertuples()}
