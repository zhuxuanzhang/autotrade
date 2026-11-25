"""Capture timestamped 14:40 quotes, then lock paper entry signals once per session."""
import concurrent.futures,json,re,msvcrt
from datetime import datetime,timezone,timedelta
import pandas as pd
import requests
import daily_signals as s
from close_entry import locked_signals

def parse_quotes(text,day):
    quotes={}
    for line in text.split(';'):
        if '="' not in line:continue
        fields=line.split('="',1)[1].strip().strip('"').split('~')
        if len(fields)<35:continue
        try:
            stamp=datetime.strptime(fields[30],'%Y%m%d%H%M%S')
            if stamp.strftime('%Y-%m-%d')!=day or stamp.hour!=14 or stamp.minute!=40:continue
            values=[float(fields[i]) for i in [3,4,5,6,33,34]]
            if not all(pd.notna(v) and v>0 for v in values):continue
            quotes[fields[2]]=dict(code=fields[2],timestamp=stamp.isoformat(),price=values[0],previous_close=values[1],open=values[2],volume=values[3]*(1 if fields[2].startswith(('688','689')) else 100),high=values[4],low=values[5])
        except (ValueError,IndexError):continue
    return quotes

def provisional(history,quote,day):
    visible=history[history.date<day].copy()
    if visible.empty:raise ValueError('No previous history')
    factor=float(visible.close.iloc[-1])/quote['previous_close']
    row=dict(date=day,open=quote['open']*factor,high=quote['high']*factor,low=quote['low']*factor,close=quote['price']*factor,volume=quote['volume'])
    return pd.concat([visible,pd.DataFrame([row])],ignore_index=True),visible.iloc[-1]

def main():
    now=datetime.now(timezone(timedelta(hours=8)));day=now.date().isoformat()
    if now.weekday()>=5 or not(now.hour==14 and now.minute==40):
        print(json.dumps(dict(status='skipped',reason='Only capture in the14:40 minute; never backfill with closing quotes')));return
    lock=(s.ROOT/'run.lock').open('a+b');lock.seek(0);lock.write(b'0');lock.flush();lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
    rules=s.rules_for_day(day)
    if locked_signals(day,rules['version']):print('Already captured');return
    risk=s.load(s.RISK_ROOT/'latest.json',{})
    if risk.get('date')!=day:risk=s.refresh()
    calendar=s.market_calendar(now);previous=calendar[-1]
    market_gate=s.buy_gate(day,calendar)
    codes=sorted(c for c,r in risk['stocks'].items() if c.startswith(('0','3','6')) and not r['excluded'])
    batches=[codes[i:i+60] for i in range(0,len(codes),60)]
    def fetch(batch):
        response=requests.get('https://qt.gtimg.cn/q='+','.join(s.symbol(c) for c in batch),timeout=10);response.raise_for_status();response.encoding='gbk'
        return parse_quotes(response.text,day)
    quotes={};errors=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        for future in concurrent.futures.as_completed([pool.submit(fetch,b) for b in batches]):
            try:quotes.update(future.result())
            except Exception as e:errors.append(str(e))
    s.save(s.ROOT/'intraday_quotes'/f'{day}.json',dict(date=day,source='Tencent timestamped batch quotes',captured_at=now.isoformat(),volume_unit='shares (source lots multiplied by100)',quotes=quotes,errors=errors))
    if not quotes:raise ValueError('No valid14:40 quotes; closed or delayed source. No signals fabricated')
    state=s.load(s.ROOT/'ledger.json');selected=[];skipped=[]
    index_gate=s.index_buy_gate(day,calendar,quote_time='14:40')
    for code,quote in quotes.items() if market_gate["allowed"] and index_gate["allowed"] else ():
        try:
            history=s.history(code,previous,False)
            if history.date.iloc[-1]!=previous:raise ValueError('Previous session data stale')
            df,prior=provisional(history,quote,day)
            item=s.candidate(code,df,risk,day,day)
            if item:
                item.update(quote_timestamp=quote['timestamp'],raw_signal_price=quote['price'],reference_previous_date=prior.date,reference_previous_hfq=float(prior.close),entry_execution='same_day_close')
                if code in state['positions']:item['status']='已持仓，不重复买入'
                else:item['status']='14:40信号已锁定，待当天收盘价记模拟买入'
                selected.append(item)
        except Exception as e:skipped.append(dict(code=code,error=str(e)))
    snapshot=dict(date=day,rules_version=rules['version'],market_amount_gate=market_gate,market_index_gate=index_gate,captured_at=now.isoformat(),quote_time='14:40',candidates=[x for x in selected if x['code'] not in state['positions']],all_selected=selected,coverage=dict(requested=len(codes),quotes=len(quotes),errors=len(skipped)),errors=skipped)
    s.save(s.ROOT/'intraday_signals'/f'{day}.json',snapshot)
    report=s.load(s.ROOT/'latest.json',{})
    report.update(report_date=day,signal_date=day,is_trading_day=True,generated_at=datetime.now(timezone(timedelta(hours=8))).isoformat(),rules=rules,entry_signal_snapshot=snapshot,selected_signals=selected,buys=snapshot['candidates'])
    report.setdefault('notes',[]).append('14:40信号快照；收盘尚未入账，持仓估值保留各自原行情日期。')
    s.save(s.ROOT/'latest.json',report);s.save(s.ROOT/'reports'/f'{day}.json',report)
    import records_store
    print(records_store.rebuild())
    print(json.dumps(dict(status='locked',date=day,signals=len(selected),queued=len(snapshot['candidates']),coverage=snapshot['coverage']),ensure_ascii=False))
if __name__=='__main__':
    from manual_1440 import main as windowed_capture_and_run
    windowed_capture_and_run()
