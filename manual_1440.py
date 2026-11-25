"""Acquire latest-session14:40 node only during14:40-15:00, then run daily strategy."""
import json,concurrent.futures,sys,msvcrt,argparse,copy
from datetime import datetime,timezone,timedelta
import requests,pandas as pd
import daily_signals as s
from close_entry import locked_signals
from capture_1440 import provisional,parse_quotes
from capture_window import status as capture_status,in_window,local_now
import priority_universe as priority

def minute_quote(payload,code,day):
    symbol=s.symbol(code);data=payload.get('data',{}).get(symbol,{})
    series=data.get('data',{})
    if series.get('date')!=day.replace('-',''):raise ValueError('分时交易日期不匹配')
    rows=[line.split() for line in series.get('data',[]) if line.split()[0]<='1440']
    last=next((r for r in rows if r[0]=='1440'),None)
    if not last:raise ValueError('缺少14:40历史节点')
    qt=data.get('qt',{}).get(symbol,[])
    price=float(last[1]);volume=float(last[2])*(1 if code.startswith(('688','689')) else 100)
    if len(qt)<6 or price<=0 or volume<=0:raise ValueError('行情字段无效')
    prices=[float(r[1]) for r in rows]
    return dict(code=code,timestamp=day+'T14:40:00',price=price,previous_close=float(qt[4]),open=float(qt[5]),volume=volume,
        high=max(prices),low=min(prices),ohlc_basis='minute sampled price extrema only; unused for entry selection; stop initialized from final close-day OHLC',source='Tencent same-day historical14:40 minute node')

def acquire(supplement=False):
    now=datetime.now(timezone(timedelta(hours=8)));day=now.date().isoformat()
    gate=capture_status(now)
    if not gate['enabled']:raise ValueError(gate['reason'])
    with (s.ROOT/'run.lock').open('a+b') as lock:
        lock.seek(0);lock.write(b'0');lock.flush();lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
        return acquire_locked(now,day,supplement)

def acquire_locked(now,day,supplement):
    rules=s.rules_for_day(day)
    frozen=locked_signals(day,rules['version'])
    if frozen is not None and not supplement:return day
    if supplement and frozen is None:raise ValueError('先完成优先结果并同步，再补充其余数据')
    queue_before=s.load(s.ROOT/'intraday_supplement'/f'{day}.json',{})
    if supplement and (queue_before.get('status') not in ('ready_to_supplement','partial') or not queue_before.get('synced_hash')):raise ValueError('优先结果尚未确认同步文档，不开始剩余采集')
    risk=s.load(s.RISK_ROOT/'latest.json',{})
    if risk.get('date')!=day:risk=s.refresh()
    calendar=s.market_calendar(now);previous=max(d for d in calendar if d<day)
    market_gate=frozen['market_amount_gate'] if frozen and 'market_amount_gate' in frozen else s.buy_gate(day,calendar)
    state=s.load(s.ROOT/'ledger.json');held=set(state['positions'])
    universe=sorted({c for c,r in risk['stocks'].items() if c.startswith(('0','3','6')) and not r['excluded']}|held)
    priority_codes,deferred,entries=priority.scope(universe,held,day,previous)
    stored=s.load(s.ROOT/'intraday_quotes'/f'{day}.json',{}) if supplement else {}
    existing=stored.get('quotes',{})
    codes=([c for c in priority_codes+deferred if c not in existing] if supplement else sorted(priority_codes,key=lambda c:(c not in held,c)))
    folder=s.ROOT/'intraday_minutes'/day;folder.mkdir(parents=True,exist_ok=True)
    def fetch(code):
        if not in_window(local_now()):return code,None,'已过采集时段，未补采历史节点'
        path=folder/f'{code}.json'
        if path.exists():
            saved=s.load(path)
            if saved.get('quote',{}).get('timestamp','').startswith(day+'T14:40:'):return code,saved['quote'],None
        try:
            response=requests.get('https://web.ifzq.gtimg.cn/appstock/app/minute/query',params={'code':s.symbol(code)},timeout=12);response.raise_for_status();payload=response.json()
            quote=minute_quote(payload,code,day)
            if not in_window(local_now()):return code,None,'采集响应超过15:00，未采纳'
            s.save(path,dict(date=day,quote=quote,raw=payload))
            return code,quote,None
        except Exception as e:return code,None,str(e)
    quotes=dict(existing);issues=[]
    # At14:40, use approximately84 bulk requests for5000 stocks instead of5000 individual minute-history calls.
    if local_now().hour==14 and local_now().minute==40:
        batches=[codes[i:i+60] for i in range(0,len(codes),60)]
        def bulk(batch):
            if not in_window(local_now()):return {}
            response=requests.get('https://qt.gtimg.cn/q='+','.join(s.symbol(c) for c in batch),timeout=10);response.raise_for_status();response.encoding='gbk'
            parsed=parse_quotes(response.text,day)
            if not in_window(local_now()):return {}
            s.save(folder/('batch_'+batch[0]+'.json'),dict(date=day,source='timestamped14:40 batch quote',raw=response.text))
            return {c:q for c,q in parsed.items() if c in batch}
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            for future in concurrent.futures.as_completed([pool.submit(bulk,b) for b in batches]):
                try:quotes.update(future.result())
                except Exception as e:issues.append(dict(code='batch',error=str(e)))
        for code,q in quotes.items():
            q['source']='timestamped14:40 batch quote'
            s.save(folder/f'{code}.json',dict(date=day,quote=q,source=q['source']))
    remaining=[c for c in codes if c not in quotes]
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        futures=[pool.submit(fetch,c) for c in remaining]
        for n,f in enumerate(concurrent.futures.as_completed(futures),1):
            code,quote,error=f.result()
            if error:issues.append(dict(code=code,error=error))
            else:quotes[code]=quote
            if n%100==0:
                s.save(s.ROOT/'run_status.json',dict(status='running',mode='capture1440',date=day,target=day,processed=n,total=len(codes),phase='采集最新交易日14:40分时',errors=len(issues)));print(n,'/',len(codes),flush=True)
    if not quotes and codes:raise ValueError('当日没有可核实的14:40分时数据')
    s.save(s.ROOT/'intraday_quotes'/f'{day}.json',dict(date=day,source='timestamped14:40 batch snapshot or exact14:40 minute node',quotes=quotes,errors=issues))
    # For post-close backfill, exclude positions held before today's close, including those sold at today's close.
    import unified_records as u
    try:held.update(p['code'] for p in u.snapshot(previous)['positions'])
    except ValueError:pass
    index_gate=(frozen['market_index_gate'] if frozen and 'market_index_gate' in frozen
                else s.index_buy_gate(day,calendar,quote_time='14:40'))
    selected=copy.deepcopy(frozen.get('all_selected',[])) if supplement else []
    known={x['code'] for x in selected}
    if market_gate['status']=='missing':
        issues.append(dict(code='market_amount',error='沪深额比待核验：'+market_gate['reason']))
    if index_gate['status']=='missing':
        issues.append(dict(code='market_index',error='上证MA5待核验：'+index_gate['reason']))
    for code,quote in quotes.items() if market_gate['allowed'] and index_gate['allowed'] else ():
        if code not in priority_codes or code in known:continue
        try:
            df=priority.history(code,previous,entries)
            if df.date.iloc[-1]!=previous:raise ValueError('前一交易日行情未补齐')
            provisional_df,prior=provisional(df,quote,day);item=s.candidate(code,provisional_df,risk,day,day)
            if item:
                item.update(quote_timestamp=quote['timestamp'],raw_signal_price=quote['price'],reference_previous_date=prior.date,reference_previous_hfq=float(prior.close),entry_execution='same_day_close',signal_source=quote.get('source','historical14:40 minute node'),status='已有持仓，不重复买入' if code in held else '14:40信号已锁定，等待当天收盘价')
                selected.append(item);known.add(code)
        except Exception as e:issues.append(dict(code=code,error=str(e)))
    snapshot=dict(date=day,rules_version=rules['version'],market_amount_gate=market_gate,market_index_gate=index_gate,captured_at=now.isoformat(),quote_time='14:40',source='windowed14:40 batch snapshot with minute-node fallback',
      candidates=[x for x in selected if x['code'] not in held],all_selected=selected,coverage=dict(requested=len(universe),priority=len(priority_codes),deferred=len(deferred),priority_quotes=sum(c in quotes for c in priority_codes),quotes=len(quotes),errors=len(issues)),errors=issues,
      acquisition_phase='supplement' if supplement else 'priority_published')
    s.save(s.ROOT/'intraday_signals'/f'{day}.json',snapshot)
    if now.hour<16:
        # Sell calculation touches held stocks only. Intraday warnings never execute a sale.
        positions=copy.deepcopy(state['positions']);sells=[]
        for code,p in positions.items():
            if code not in quotes:continue
            try:
                df=s.history(code,previous,False);raw=s.raw_history(code,previous,False)
                projected,_=provisional(df,quotes[code],day)
                q=quotes[code];raw_today=dict(date=day,open=q['open'],high=q['high'],low=q['low'],close=q['price'],volume=q['volume'])
                raw=pd.concat([raw[raw.date<day],pd.DataFrame([raw_today])],ignore_index=True)
                reasons,mark=s.sell_reasons(p,projected,raw,day)
                if mark:p['mark']={**mark,'quote_time':'14:40','provisional':True}
                if reasons and day>p['entry_date']:sells.append(dict(code=code,name=p['name'],entry_date=p['entry_date'],entry_price=p['entry_price'],signal_date=day,reasons=['14:40卖出预警，待收盘确认：'+r for r in reasons],mark=mark,signal_basis='14:40_preview'))
            except Exception as e:issues.append(dict(code=code,error='持仓14:40预警：'+str(e)))
        report=s.load(s.ROOT/'latest.json');report.update(report_date=day,signal_date=day,is_trading_day=True,generated_at=local_now().isoformat(),rules=rules,entry_signal_snapshot=snapshot,selected_signals=selected,buys=snapshot['candidates'],sell_signals=sells,positions=list(positions.values()),coverage=snapshot['coverage'])
        s.save(s.ROOT/'latest.json',report);s.save(s.ROOT/'reports'/f'{day}.json',report)
    queue=s.ROOT/'intraday_supplement'/f'{day}.json'
    s.save(queue,{**queue_before,**dict(date=day,status=('complete' if all(c in quotes for c in universe) else 'partial') if supplement else 'pending_sync',priority=priority_codes,deferred=deferred,remaining=[c for c in universe if c not in quotes],note='优先结果先同步腾讯文档；确认后才采集余下行情。超过15:00不补采盘中，交由收盘日线更新。')})
    return day

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--supplement',action='store_true');args=parser.parse_args()
    day=datetime.now(timezone(timedelta(hours=8))).date().isoformat();status=s.ROOT/'run_status.json'
    gate=capture_status()
    if not gate['enabled']:
        if args.supplement and not in_window(local_now()):
            path=s.ROOT/'intraday_supplement'/f'{day}.json';queue=s.load(path)
            if queue and queue.get('status')!='complete':queue.update(status='awaiting_close',note='已过14:40—15:00采集时段，剩余数据由收盘日线任务补齐');s.save(path,queue)
        print(json.dumps(dict(status='skipped',reason=gate['reason']),ensure_ascii=False));return
    s.save(status,dict(status='running',mode='capture1440',date=day,target=day,phase='正在读取14:40数据',processed=0))
    try:
        acquire(args.supplement)
        import records_store
        records_store.rebuild()
        value=dict(status='complete',mode='capture1440',date=day,target=day,phase='supplement' if args.supplement else 'priority_published',note='优先买卖信号已发布；先同步腾讯文档，再补充剩余数据' if not args.supplement else '补充数据已保存')
        s.save(status,value);print(json.dumps(value,ensure_ascii=False),flush=True)
    except Exception as e:
        s.save(status,dict(status='failed',mode='capture1440',date=day,target=day,error=str(e)));raise
if __name__=='__main__':main()
