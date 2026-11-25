"""Persistent, independent paper trades; never submits broker orders."""
import argparse
import concurrent.futures
import copy
import json
import math
import os
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
import pandas as pd
import numpy as np
import akshare as ak
import requests
from right_side import right_side_buy
from volume_down_filter import historical_volume_down, describe_history_filter, CONFIG as VOLUME_DOWN_CONFIG
from two_year_range_filter import two_year_range, CONFIG as TWO_YEAR_RANGE_CONFIG
from update_risk import refresh, china_today, ROOT as RISK_ROOT
from market_amount_marks import BUY_FILTER, buy_gate

BASE=Path(__file__).resolve().parent
ROOT=BASE/'data/daily_signals'
ARCHIVE=BASE/'data/a_share_20261114/daily_hfq'
COST=.002
RULES=dict(volume_min=1.4,volume_max=1.8,breakout_exit_fraction=.92,cost_per_side=COST,
    mode='independent_paper_trades',quantity_per_trade=100,version='2026-11-17-close-v7',
    historical_volume_down=VOLUME_DOWN_CONFIG,two_year_range=TWO_YEAR_RANGE_CONFIG,entry_execution='same_day_close',signal_time='14:40 latest trading date; acquire14:40-15:00 Asia/Shanghai',sell_execution='signal_day_close_Tplus1')
V3_RULES={k:v for k,v in RULES.items() if k not in ('entry_execution','signal_time','sell_execution')}
V3_RULES['version']='2026-11-16-range-v3'
PREVIOUS_RULES={k:v for k,v in RULES.items() if k not in ('two_year_range','entry_execution','signal_time','sell_execution')}
PREVIOUS_RULES['version']='2026-11-16-volume-down-v2'
LEGACY_RULES={k:v for k,v in RULES.items() if k not in ('historical_volume_down','two_year_range','entry_execution','signal_time','sell_execution')}
LEGACY_RULES['version']='2026-11-15-v1'
PRE_FALLBACK_RULES=copy.deepcopy(RULES)
PRE_AMOUNT_RULES={**RULES,'version':'2026-11-17-close-v8','missing_intraday_signal':'final_close_fallback'}
PRE_NO_STOP_RULES={**PRE_AMOUNT_RULES,'version':'2026-11-20-close-v9','market_amount_filter':BUY_FILTER}
NO_INITIAL_STOP_FROM='2026-11-24'
INITIAL_STOP_REASON='收盘跌破买入时固定的5日最低价止损线'
MA20_EXIT_REASONS={2:'连续两个交易日收盘低于各自MA20',3:'连续三个交易日收盘低于各自MA20'}
LEGACY_MA20_EXIT_DAYS=2
LEGACY_TIME_EXIT_DAYS=15
TIME_EXIT_REASON='持有满{days}个交易日，收盘仍未高于买入价'
PRE_DRAWDOWN_RULES={**PRE_NO_STOP_RULES,'version':'2026-11-24-close-v10',
       'initial_stop_enabled':False,'time_exit_days':30,'ma20_exit_days':3,'volume_max':1.70,
       'market_index_filter':dict(symbol='sh000001',ma_sessions=5,reference='same_day_1440_or_close',
                                  minimum_above_ma5=.0025)}
DRAWDOWN_ONLY_FROM='2026-11-25'
SIX_MONTH_DRAWDOWN_RULES={**PRE_DRAWDOWN_RULES,'version':'2026-11-25-close-v12',
       'historical_volume_down':{**VOLUME_DOWN_CONFIG,'consecutive_enabled':False,
                                 'combination':'drawdown_only'}}
SUPERSEDED_DRAWDOWN_RULES={**SIX_MONTH_DRAWDOWN_RULES,'version':'2026-11-25-close-v11',
       'historical_volume_down':{**SIX_MONTH_DRAWDOWN_RULES['historical_volume_down'],'drawdown_max_pct':80.}}
FIVE_DAY_EVENT_VOLUME_RULES={**SIX_MONTH_DRAWDOWN_RULES,'version':'2026-11-25-close-v13',
       'historical_volume_down':{**SIX_MONTH_DRAWDOWN_RULES['historical_volume_down'],'lookback_months':4}}
RULES={**FIVE_DAY_EVENT_VOLUME_RULES,'version':'2026-11-25-close-v14',
       'historical_volume_down':{**FIVE_DAY_EVENT_VOLUME_RULES['historical_volume_down'],'volume_recent_sessions':3}}


def rules_for_day(day):
    if day >= DRAWDOWN_ONLY_FROM:
        return RULES
    if day >= NO_INITIAL_STOP_FROM:
        return PRE_DRAWDOWN_RULES
    if day >= BUY_FILTER['effective_from']:
        return PRE_NO_STOP_RULES
    return PRE_AMOUNT_RULES


_request=requests.sessions.Session.request
def bounded_request(self,method,url,**kwargs):
    kwargs.setdefault('timeout',30)
    return _request(self,method,url,**kwargs)
requests.sessions.Session.request=bounded_request

def save(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_name(path.name+f'.{os.getpid()}.tmp')
    temp.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    for attempt in range(10):
        try:
            temp.replace(path)
            return
        except PermissionError:
            if attempt==9: raise
            time.sleep(.3*(attempt+1))

def load(path,default=None):
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else default

def validate(df):
    df=df.copy()
    df['date']=pd.to_datetime(df.date).dt.strftime('%Y-%m-%d')
    if df.empty or df.date.duplicated().any() or not df.date.is_monotonic_increasing:
        raise ValueError('Empty or unordered price history')
    values=df[['open','high','low','close','volume']].to_numpy(float)
    invalid=(~np.isfinite(values).all(axis=1))|(values[:,:4]<=0).any(axis=1)|(values[:,4]<0)
    if invalid.any():
        raise ValueError('价格或成交量无效，日期：'+', '.join(df.loc[invalid,'date'].head(3)))
    inconsistent=(df.high<df[['open','close','low']].max(axis=1)-.011)|(df.low>df[['open','close','high']].min(axis=1)+.011)
    if inconsistent.any():
        raise ValueError('开高低收价格矛盾，日期：'+', '.join(df.loc[inconsistent,'date'].head(3)))
    return df

def symbol(code):
    return ('sh' if code.startswith('6') else 'sz')+code

def confirmed_intraday_session(day):
    snapshot=load(ROOT/'intraday_signals'/f'{day}.json',{})
    quotes=load(ROOT/'intraday_quotes'/f'{day}.json',{}).get('quotes',{})
    return snapshot.get('date')==day and snapshot.get('quote_time')=='14:40' and any(
        q.get('timestamp','').startswith(day+'T14:40:') and q.get('price',0)>0 and q.get('volume',0)>0 for q in quotes.values())

def market_calendar(now):
    """Cache confirmed sessions until the next local close-check boundary."""
    path=ROOT/'calendar.json'
    cached=load(path,{})
    if cached.get('expires_at','')>now.isoformat() and cached.get('dates'):
        today=now.date().isoformat()
        if now.hour>=16 and cached['dates'][-1]<today and confirmed_intraday_session(today):
            cached['dates']=sorted(set(cached['dates'])|{today})
            cached['expires_at']=(now+timedelta(days=1)).replace(hour=16,minute=0,second=0,microsecond=0).isoformat()
            cached['session_evidence']='Saved verified current-day14:40 quotes; confirmed session after16:00'
            save(path,cached)
        return cached['dates']
    index=ak.index_zh_daily_sina(symbol='sh000001')
    today=now.date().isoformat()
    dates=sorted(d for d in pd.to_datetime(index.date).dt.strftime('%Y-%m-%d').unique()
                 if d<today or (d==today and now.hour>=16))
    if now.hour>=16 and dates and dates[-1]<today and confirmed_intraday_session(today):dates.append(today)
    if not dates or (pd.Timestamp(today)-pd.Timestamp(dates[-1])).days>10:
        raise ValueError('Market calendar source is stale')
    boundary=now.replace(hour=16,minute=0,second=0,microsecond=0)
    if now>=boundary:
        # A late source may not have published today's close yet.
        boundary=(boundary+timedelta(days=1)) if dates[-1]==today else now+timedelta(minutes=30)
    save(path,dict(dates=dates,expires_at=boundary.isoformat(),
                   index_closes=index_closes(index,dates[-30:])))
    return dates


def index_closes(index, sessions):
    if 'close' not in index.columns:
        return {}
    dates=pd.to_datetime(index.date).dt.strftime('%Y-%m-%d')
    rows=index.assign(session=dates).loc[dates.isin(sessions),['session','close']]
    if rows.session.duplicated().any():
        return {}
    close=pd.to_numeric(rows.close,errors='coerce')
    return {day:float(value) for day,value in zip(rows.session,close)
            if np.isfinite(value) and value>0}


def index_1440_price(symbol, day):
    response=requests.get('https://web.ifzq.gtimg.cn/appstock/app/minute/query',
                          params={'code':symbol},timeout=8)
    response.raise_for_status()
    data=response.json().get('data',{}).get(symbol,{}).get('data',{})
    if data.get('date')!=day.replace('-',''):
        raise ValueError('上证指数分时交易日期不匹配')
    observations=[line.split() for line in data.get('data',[])]
    match=[row for row in observations if len(row)>=2 and row[0]=='1440']
    if len(match)!=1:
        raise ValueError('上证指数缺少可核验的14:40报价')
    price=float(match[0][1])
    if not np.isfinite(price) or price<=0:
        raise ValueError('上证指数14:40价格无效')
    return price


def index_meets_ma5(price, ma, rule):
    if not all(isinstance(value,(float,int)) and math.isfinite(value) and value>0
               for value in (price,ma)):
        return False
    minimum=rule['minimum_above_ma5']
    threshold=ma*(1+minimum)
    return price>=threshold or math.isclose(price,threshold,rel_tol=1e-12)


def index_buy_gate(day,sessions,*,quote_time='close'):
    rule=rules_for_day(day).get('market_index_filter')
    if rule is None:
        return dict(status='inactive',allowed=True)
    if quote_time not in ('14:40','close'):
        raise ValueError('Unsupported index quote time')
    prior_count=rule['ma_sessions']-1
    previous=sorted({session for session in sessions if session<day})[-prior_count:]
    if len(previous)!=prior_count:
        return dict(status='missing',allowed=False,reason='买入日前不足4个已确认交易日')
    try:
        required=previous+[day] if quote_time=='close' else previous
        closes=load(ROOT/'calendar.json',{}).get('index_closes',{})
        if not all(d in closes for d in required):
            closes=index_closes(ak.index_zh_daily_sina(symbol=rule['symbol']),required)
        if not all(d in closes and np.isfinite(closes[d]) and closes[d]>0 for d in required):
            raise ValueError('所需交易日的上证指数收盘价缺失或无效')
        price=closes[day] if quote_time=='close' else index_1440_price(rule['symbol'],day)
        ma=(sum(closes[d] for d in previous)+price)/rule['ma_sessions']
    except Exception as error:
        return dict(status='missing',allowed=False,reason=str(error),quote_time=quote_time)
    allowed=index_meets_ma5(price,ma,rule)
    return dict(status='passed' if allowed else 'blocked',allowed=allowed,
                reference_date=day,quote_time=quote_time,close=price,ma5=ma,
                minimum_above_ma5=rule['minimum_above_ma5'])


def remote_history(code,target,kind):
    preferences=load(ROOT/'source_preferences.json',{})
    sources=['tencent','sina'] if preferences.get(code)=='tencent' else ['sina','tencent']
    failures=[]
    for source in sources:
        fetch=ak.stock_zh_a_hist_tx if source=='tencent' else ak.stock_zh_a_daily_sina
        try:
            df=fetch(symbol=symbol(code),start_date='19900101',end_date=target.replace('-',''),
                adjust='hfq' if kind=='market' else '')
            df=validate(df[pd.to_datetime(df.date)<=pd.Timestamp(target)])
            return df,source
        except Exception as error:
            failures.append(f'{source}: {error}')
    raise ValueError('；'.join(failures))


def store_history(code,target,kind,df,source):
    df=validate(df)
    if df.date.iloc[-1]>target:
        raise ValueError('History exceeds requested cutoff')
    path=ROOT/kind/target/f'{code}.csv'
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix('.tmp')
    df.to_csv(tmp,index=False,encoding='utf-8-sig')
    tmp.replace(path)
    save(path.with_suffix('.json'),dict(code=code,source=source,
        adjustment='hfq' if kind=='market' else 'raw',volume_unit='shares',
        first_date=df.date.iloc[0],last_date=df.date.iloc[-1],rows=len(df),
        file_size=path.stat().st_size,file_mtime_ns=path.stat().st_mtime_ns,validated=True,
        saved_at=datetime.now(timezone(timedelta(hours=8))).isoformat()))


def cached_history(code,target,update,kind,stats=None):
    path=ROOT/kind/target/f'{code}.csv'
    candidates=[path]+sorted((ROOT/kind).glob(f'*/{code}.csv'),reverse=True)
    if kind=='market': candidates.append(ARCHIVE/f'{code}.csv')
    best=None
    local_error=None
    for local in dict.fromkeys(candidates):
        if not local.exists(): continue
        try:
            df=pd.read_csv(local)
            df=df[pd.to_datetime(df.date)<=pd.Timestamp(target)]
            df=validate(df)
            if best is None or df.date.iloc[-1]>best.date.iloc[-1]: best=df
            if df.date.iloc[-1]==target:
                if stats is not None: stats['local']+=1
                return df
        except (ValueError,KeyError,pd.errors.ParserError) as error:
            local_error=error
            continue
    if not update:
        if best is not None:
            if stats is not None: stats['local']+=1
            return best
        raise ValueError(str(local_error) if local_error else '本地行情缺失，请先主动拉取数据')
    if stats is not None: stats['requested']+=1
    if kind=='market' and best is not None:
        try:
            from incremental_prices import update as incremental_update
            frame,_=incremental_update(code,target,best,ROOT,validate,store_history)
            if stats is not None:
                stats['downloaded']+=1
                stats['incremental']=stats.get('incremental',0)+1
                stats['appended_rows']=stats.get('appended_rows',0)+len(frame)-len(best)
            return frame
        except Exception as incremental_error:
            if stats is not None:stats['full_snapshot_fallbacks']=stats.get('full_snapshot_fallbacks',0)+1
            save(ROOT/'price_store/errors'/f'{code}_{target}.json',dict(code=code,target=target,error=str(incremental_error),action='fall back to original complete snapshot; do not splice incompatible prices'))
    for attempt in range(3):
        try:
            # Bootstrap/mismatch fallback: retain complete provider history when validated increments are unavailable.
            df,source=remote_history(code,target,kind)
            store_history(code,target,kind,df,source)
            if stats is not None: stats['downloaded']+=1
            time.sleep(.5)
            return df
        except Exception:
            if attempt==2: raise
            time.sleep(2**attempt)


def history(code,target,update,stats=None):
    return cached_history(code,target,update,'market',stats)


def raw_history(code,target,update=True,stats=None):
    return cached_history(code,target,update,'raw',stats)


def verified_snapshot_metadata(code,target,kind):
    """Read lightweight validated sidecar, never load the historical CSV for a pull check."""
    path=ROOT/kind/target/f'{code}.csv'
    sidecar=path.with_suffix('.json')
    if not path.exists() or not sidecar.exists():return None
    try:
        meta=load(sidecar);stat=path.stat()
        if meta.get('code')!=code or meta.get('last_date')!=target or meta.get('rows',0)<=0:return None
        if 'file_size' in meta and 'file_mtime_ns' in meta:
            if meta['file_size']!=stat.st_size or meta['file_mtime_ns']!=stat.st_mtime_ns:return None
        else:
            # Existing sidecars were written by store_history only after validating and atomically replacing the CSV.
            known=('sina','tencent','incremental:raw+dated_sina_factors','incremental:recent_provider_raw+derived_older_raw')
            if meta.get('source') not in known or stat.st_mtime_ns>sidecar.stat().st_mtime_ns:return None
        return dict(status='complete',last_date=target,file_size=stat.st_size,file_mtime_ns=stat.st_mtime_ns,validation='stored validated snapshot metadata')
    except (OSError,ValueError,TypeError):return None


def pull_daily_data(target,risk,now):
    """Persist per-session outcomes so repeated pulls never rescan completed CSVs."""
    manifest_path=ROOT/'pull_marks'/f'{target}.json'
    manifest=load(manifest_path,{})
    if manifest.get('version')!=1 or manifest.get('target')!=target:
        manifest=dict(version=1,target=target,items={})
    marks=manifest['items']
    ledger=load(ROOT/'ledger.json',{})
    report=load(ROOT/'latest.json',{})
    codes={c for c,r in risk['stocks'].items() if c.startswith(('0','3','6')) and not r['excluded']}
    raw_codes=set(ledger.get('positions',{}))|{p['code'] for p in ledger.get('pending_buys',[])}
    raw_codes|={p['code'] for p in report.get('buys',[])}
    codes|=raw_codes
    jobs=[('market',c) for c in sorted(codes)]+[('raw',c) for c in sorted(raw_codes)]
    transfer=dict(local=0,requested=0,downloaded=0,marked=0,metadata_reused=0)
    status_path=ROOT/'run_status.json'

    def status(state,processed):
        active=[marks.get(kind+':'+code,{}) for kind,code in jobs]
        issues=[dict(code=code,kind=kind,error=marks[kind+':'+code]['error'])
                for kind,code in jobs if marks.get(kind+':'+code,{}).get('error')]
        return dict(status=state,mode='pull',date=now.date().isoformat(),target=target,
            processed=processed,total=len(jobs),transfer=transfer,issues=issues,
            coverage=dict(current=sum(m.get('status')=='complete' for m in active),
                stale=sum(m.get('status')=='stale' for m in active),errors=len(issues)))

    for n,(kind,code) in enumerate(jobs,1):
        key=kind+':'+code
        mark=marks.get(key,{})
        if mark.get('status')=='complete' or mark.get('retry_after','')>now.isoformat():
            transfer['marked']+=1
        elif verified_snapshot_metadata(code,target,kind) is not None:
            marks[key]={**verified_snapshot_metadata(code,target,kind),'checked_at':now.isoformat()}
            transfer['metadata_reused']+=1
        else:
            try:
                frame=cached_history(code,target,True,kind,transfer)
                latest=frame.date.iloc[-1]
                marks[key]=dict(status='complete' if latest==target else 'stale',last_date=latest,
                    checked_at=now.isoformat(),retry_after=(now+timedelta(minutes=30)).isoformat())
            except Exception as error:
                marks[key]=dict(status='failed',error=str(error),checked_at=now.isoformat(),
                    retry_after=(now+timedelta(minutes=30)).isoformat())
        if n%100==0:
            save(manifest_path,manifest)
            save(status_path,status('running',n))
    save(manifest_path,manifest)
    result=status('complete',len(jobs))
    save(status_path,result)
    return result


def row_at(df,day):
    rows=df[df.date==day]
    return None if rows.empty else rows.iloc[-1]

def listed_six_months(history_start, buy_date):
    # Earliest observed history is a conservative fallback for listing date.
    return pd.Timestamp(buy_date) >= pd.Timestamp(history_start)+pd.DateOffset(months=6)

def tradable(row):
    return row is not None and row.volume>0 and row.high-row.low>1e-8

def candidate(code,df,risk,today,target):
    if len(df)<65 or df.date.iloc[-1]!=target: return None
    record=risk['stocks'].get(code)
    result=right_side_buy(df.close.tolist(),code=code,as_of=target,history_start=df.date.iloc[0],
        risk_record=record,risk_date=risk['date'],screening_date=today)
    if not result['buy_signal']: return None
    recent=float(df.volume.iloc[-5:].mean())
    previous=float(df.volume.iloc[-20:-5].mean())
    if previous<=0: return None
    ratio=recent/previous
    entry_rules=rules_for_day(target)
    volume_min,volume_max=entry_rules['volume_min'],entry_rules['volume_max']
    if not volume_min<=ratio<=volume_max: return None
    history_rule=entry_rules['historical_volume_down']
    events=historical_volume_down(df,target,history_rule)
    if not events: return None
    range_info=two_year_range(df,target)
    if not range_info or not range_info['passed']: return None
    m=result['metrics']
    return dict(code=code,name=record['name'],signal_date=target,created_date=today,
        entry_rule_version=entry_rules['version'],historical_volume_down_events=events,two_year_range=range_info,
        volume_ratio=ratio,breakout_hfq=m['previous_20_close_high'],stop_hfq=float(df.low.iloc[-5:].min()),
        signal_close_hfq=float(df.close.iloc[-1]),ma20=m['ma20'],ma60=m['ma60'],deviation=m['deviation_from_ma20'],
        reasons=[f"收盘价高于前20日最高收盘价 {m['previous_20_close_high']:.2f}（后复权）",
            '收盘价 > MA20 > MA60，MA20上行，MA60不下降',
            f"距MA20 {m['deviation_from_ma20']:.2%}，不超过8%",
            f'最近5日均量/此前15日均量={ratio:.3f}，在[{volume_min:.2f},{volume_max:.2f}]内',
            '已通过沪深、上市满六个月、当天ST/退市名称标记筛查',
            describe_history_filter(history_rule)]+[e['reason'] for e in events]+[range_info['reason']])

def migrate_volume_down_rules(state,frames,today,signal_day=None):
    active_rules=rules_for_day(signal_day or today)
    history_rule=active_rules['historical_volume_down']
    if state['rules']==active_rules: return state
    if state['rules']!=LEGACY_RULES: raise ValueError('Unsupported source rule version')
    migrated=copy.deepcopy(state)
    remaining=[]
    for order in migrated['pending_buys']:
        df=frames.get(order['code'])
        events=historical_volume_down(df,order['signal_date'],history_rule) if df is not None else []
        if events:
            order['entry_rule_version']=active_rules['version']
            order['historical_volume_down_events']=events
            order['reasons']=order.get('reasons',[])+['新增放量下跌入场条件已核验']+[e['reason'] for e in events]
            remaining.append(order)
        else:
            migrated['cancelled'].append({**order,'cancel_date':today,
                'cancel_reason':f'规则升级：未通过{describe_history_filter(history_rule)}，取消待买入'})
    migrated['pending_buys']=remaining
    migrated.setdefault('rule_migrations',[]).append(dict(date=today,from_rules=state['rules'],to_rules=copy.deepcopy(active_rules),
        pending_before=len(state['pending_buys']),pending_after=len(remaining),positions_preserved=len(state['positions'])))
    migrated['rules']=copy.deepcopy(active_rules)
    return migrated


def migrate_two_year_range_rules(state,frames,today):
    active_rules=rules_for_day(today)
    if state['rules']==active_rules:return state
    if state['rules']!=PREVIOUS_RULES:raise ValueError('Unsupported source rule version for range migration')
    migrated=copy.deepcopy(state)
    remaining=[]
    for order in migrated['pending_buys']:
        df=frames.get(order['code'])
        info=two_year_range(df,order['signal_date']) if df is not None else None
        if info and info['passed']:
            order['two_year_range']=info
            order['entry_rule_version']=active_rules['version']
            order['reasons']=order.get('reasons',[])+[info['reason']]
            remaining.append(order)
        else:
            migrated['cancelled'].append({**order,'cancel_date':today,'cancel_reason':'规则升级：近两年最高/最低收盘价比例未通过[200%,400%)核验，取消待买入'})
    migrated['pending_buys']=remaining
    migrated.setdefault('rule_migrations',[]).append(dict(date=today,from_rules=state['rules'],to_rules=copy.deepcopy(active_rules),pending_before=len(state['pending_buys']),pending_after=len(remaining),positions_preserved=len(state['positions'])))
    migrated['rules']=copy.deepcopy(active_rules)
    return migrated


def enrich(item,df,raw):
    row=row_at(raw,item['signal_date'])
    if row is None: raise ValueError('Missing raw signal-day price')
    factor=item['signal_close_hfq']/float(row.close)
    lower=max(item['breakout_hfq'],item['stop_hfq'])/factor
    upper=min(item['signal_close_hfq']*1.02,item['stop_hfq']/.92)/factor
    if upper<=lower: return None
    item.update(raw_close=float(row.close),breakout_reference=item['breakout_hfq']/factor,
        initial_stop_reference=item['stop_hfq']/factor,buy_above=lower,buy_at_most=upper,
        price_note='按信号日复权比例折算的参考区间；次日若除权需重算，非挂单价格')
    return item

def sell_reasons(position,df,raw,day):
    visible=df[df.date<=day]
    current=row_at(visible,day)
    entry=row_at(df,position['entry_date'])
    raw_entry=row_at(raw,position['entry_date'])
    if current is None or entry is None or raw_entry is None or len(visible)<21:
        return [],None
    entry_adj=position['entry_price']*float(entry.close/raw_entry.close)
    anchor=row_at(df,position['signal_date'])
    if anchor is None: return [],None
    scale=float(anchor.close)/position['signal_close_hfq']
    stop=position['stop_hfq']*scale
    breakout=position['breakout_hfq']*scale
    age=int(((visible.date>=position['entry_date'])&(visible.date<=day)).sum())
    closes=visible.close
    reasons=[]
    active_rules=rules_for_day(day)
    ma20_exit_days=active_rules.get('ma20_exit_days',LEGACY_MA20_EXIT_DAYS)
    initial_stop_enabled=active_rules.get('initial_stop_enabled',True)
    time_exit_days=active_rules.get('time_exit_days',LEGACY_TIME_EXIT_DAYS)
    if initial_stop_enabled and current.close<stop:
        reasons.append(INITIAL_STOP_REASON)
    if age<=5 and current.close<breakout*.92: reasons.append('买入后前5日收盘跌破原突破位92%')
    if len(closes)>=19+ma20_exit_days and all(
        closes.iloc[-offset-1]<closes.iloc[len(closes)-20-offset:len(closes)-offset].mean()
        for offset in range(ma20_exit_days)
    ):
        reasons.append(MA20_EXIT_REASONS[ma20_exit_days])
    if age>=time_exit_days and current.close<=entry_adj:
        reasons.append(TIME_EXIT_REASON.format(days=time_exit_days))
    gross=float(current.close/entry_adj-1)
    mark=dict(mark_date=day,holding_sessions=age,gross_return=gross,
        net_return=float((1+gross)*(1-COST)/(1+COST)-1),
        entry_hfq_current_basis=entry_adj)
    if initial_stop_enabled:
        mark['initial_stop_hfq']=stop
    raw_current=row_at(raw,day)
    mark['last_raw_close']=float(raw_current.close) if raw_current is not None else None
    return reasons,mark

def process_day(state,frames,raws,day,risk):
    """Execute previously known orders first, then generate close-based exits."""
    for code,position in list(state['positions'].items()):
        if code not in frames or code not in raws: continue
        df,raw=frames[code],raws[code]
        order=position.get('sell_order')
        current=row_at(df,day)
        raw_current=row_at(raw,day)
        if state.get('rules',{}).get('sell_execution')!='signal_day_close_Tplus1' and order and order['signal_date']<day and day>position['entry_date'] and tradable(current) and tradable(raw_current):
            entry=row_at(df,position['entry_date'])
            raw_entry=row_at(raw,position['entry_date'])
            if entry is None or raw_entry is None: continue
            entry_adj=position['entry_price']*float(entry.close/raw_entry.close)
            gross=float(current.open/entry_adj-1)
            trade={**position,'exit_date':day,'exit_price':float(raw_current.open),
                'exit_signal_date':order['signal_date'],'exit_reasons':order['reasons'],
                'gross_return':gross,'net_return':float((1+gross)*(1-COST)/(1+COST)-1),
                'holding_sessions':int(((df.date>=position['entry_date'])&(df.date<=day)).sum())-1}
            state['closed_trades'].append(trade)
            del state['positions'][code]
    remaining=[]
    for order in state['pending_buys']:
        if day<=order['signal_date'] or day<order['created_date']:
            remaining.append(order)
            continue
        code=order['code']
        if code in state['positions']: continue
        if code not in frames or code not in raws:
            order['status']='等待补齐数据核验，未记为成交'
            remaining.append(order)
            continue
        df,raw=frames[code],raws[code]
        current,raw_current=row_at(df,day),row_at(raw,day)
        anchor=row_at(df,order['signal_date'])
        if current is None or raw_current is None:
            # Missing row could be source outage rather than suspension: never infer a fill.
            order['status']='执行日行情缺失，需核验；未记为成交'
            remaining.append(order)
            continue
        if order.get('execution_date') and order['execution_date']!=day:
            order['status']='原计划执行日数据待核验，不在之后的日期追买'
            remaining.append(order)
            continue
        scale=float(anchor.close)/order['signal_close_hfq'] if anchor is not None else 1
        stop=order['stop_hfq']*scale
        price=float(current.open)
        permitted=listed_six_months(df.date.iloc[0],day) and code.startswith(('0','3','6')) and tradable(current) and tradable(raw_current) and price>order['breakout_hfq']*scale and price<=order['signal_close_hfq']*scale*1.02 and 0<(price-stop)/price<=.08
        history_rule=rules_for_day(order['signal_date'])['historical_volume_down']
        if state.get('rules',{}).get('historical_volume_down') and not historical_volume_down(df,order['signal_date'],history_rule): permitted=False
        if state.get('rules',{}).get('two_year_range'):
            range_info=two_year_range(df,order['signal_date'])
            if not range_info or not range_info['passed']:permitted=False
        if risk['stocks'].get(code,{}).get('excluded',True): permitted=False
        if permitted:
            state['positions'][code]={**order,'entry_date':day,'entry_price':float(raw_current.open),
                'trade_id':code+'-'+day,'quantity':100,'simulation':True,'sell_order':None}
        else:
            state['cancelled'].append({**order,'cancel_date':day,'cancel_reason':'上市未满六个月、市场范围、开盘价格、风险标记、历史放量下跌、两年高低价比例或成交条件不满足，取消本次买入'})
    state['pending_buys']=remaining
    for code,position in state['positions'].items():
        if code not in frames or code not in raws: continue
        reasons,mark=sell_reasons(position,frames[code],raws[code],day)
        if mark: position['mark']=mark
        if reasons and not position.get('sell_order'):
            position['sell_order']=dict(signal_date=day,reasons=reasons)
    if state.get('rules',{}).get('sell_execution')=='signal_day_close_Tplus1':
        from close_entry import fill_close_sales
        fill_close_sales(state,frames,raws,day)
    state['last_processed_market_date']=day

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--update',action='store_true',help='Fetch missing current history, preserving old snapshots')
    parser.add_argument('--pull-only',action='store_true',help='Update daily-marked data without recalculating strategies')
    parser.add_argument('--migrate-volume-down',action='store_true',help='Apply explicitly approved entry-only rule migration with backups')
    parser.add_argument('--as-of',help='Recalculate the latest completed trading date only')
    parser.add_argument('--priority-only',action='store_true',help='Publish held exits and mathematically possible entries before market-wide data supplementation')
    args=parser.parse_args()
    ROOT.mkdir(parents=True,exist_ok=True)
    # OS-owned lock is released even if the process crashes.
    import msvcrt
    lock=(ROOT/'run.lock').open('a+b')
    lock.seek(0); lock.write(b'0'); lock.flush(); lock.seek(0)
    try: msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
    except OSError: raise SystemExit('Daily update already running')
    today=china_today()
    now=datetime.now(timezone(timedelta(hours=8)))
    status_path=ROOT/'run_status.json'
    save(status_path,dict(status='running',started_at=now.isoformat(),date=today))
    try:
        risk=load(RISK_ROOT/'latest.json',{})
        if risk.get('date') not in (today,args.as_of): risk=refresh()
        calendar=market_calendar(now)
        target=calendar[-1]
        if now.hour>=16 and target<today and load(ROOT/'latest.json',{}).get('signal_date')==today:
            save(status_path,dict(status='waiting_calendar',date=today,target=target,note='收盘日历尚未确认今天，保留今天已发布报告，不回写上一交易日'))
            return
        if args.as_of and args.as_of!=target: raise ValueError('--as-of must be the latest confirmed completed trading date')
        if args.pull_only:
            result=pull_daily_data(target,risk,now)
            queue_path=ROOT/'data_completion'/f'{target}.json';queue=load(queue_path)
            if queue:
                queue.update(status='retry_needed' if result['coverage']['errors'] else 'complete',coverage=result['coverage']);save(queue_path,queue)
            print(json.dumps(result,ensure_ascii=False),flush=True)
            return
        if now.hour<16 and (ROOT/'intraday_signals'/f'{today}.json').exists():
            import records_store
            records_store.rebuild()
            save(status_path,dict(status='complete',date=today,target=today,note='14:40信号已锁定，等待收盘价；保留盘中报告'))
            return
        transfer=dict(local=0,requested=0,downloaded=0)
        active_rules=rules_for_day(target)
        state=load(ROOT/'ledger.json',dict(start_date=today,rules=active_rules,positions={},pending_buys=[],closed_trades=[],cancelled=[],last_processed_market_date=None))
        if state['rules']==PRE_FALLBACK_RULES:
            backup=ROOT/'migrations'/('fallback-policy-'+now.strftime('%Y%m%dT%H%M%S'))
            save(backup/'ledger_before.json',state)
            state.setdefault('rule_migrations',[]).append(dict(date=today,from_rules=copy.deepcopy(state['rules']),to_rules=copy.deepcopy(PRE_AMOUNT_RULES),positions_preserved=len(state['positions']),reason='用户确认：缺少14:40快照时按最终收盘信号与收盘价成交'))
            state['rules']=copy.deepcopy(PRE_AMOUNT_RULES)
        if state['rules']==PRE_AMOUNT_RULES and 'market_amount_filter' in active_rules:
            backup=ROOT/'migrations'/('market-amount-'+now.strftime('%Y%m%dT%H%M%S'))
            save(backup/'ledger_before.json',state)
            state.setdefault('rule_migrations',[]).append(dict(
                date=target,from_rules=copy.deepcopy(PRE_AMOUNT_RULES),to_rules=copy.deepcopy(PRE_NO_STOP_RULES),
                positions_preserved=len(state['positions']),reason='沪深额比纳入正式买入条件'))
            state['rules']=copy.deepcopy(PRE_NO_STOP_RULES)
        if state['rules']==PRE_NO_STOP_RULES and active_rules in (PRE_DRAWDOWN_RULES,RULES):
            backup=ROOT/'migrations'/('entry-and-exit-rules-'+now.strftime('%Y%m%dT%H%M%S'))
            save(backup/'ledger_before.json',state)
            state.setdefault('rule_migrations',[]).append(dict(
                date=NO_INITIAL_STOP_FROM,from_rules=copy.deepcopy(PRE_NO_STOP_RULES),to_rules=copy.deepcopy(PRE_DRAWDOWN_RULES),
                positions_preserved=len(state['positions']),reason='量比上限1.70，上证指数高于当日MA5至少0.25%；取消初始止损，连续三日低于MA20退出，时间退出延长至30个交易日'))
            state['rules']=copy.deepcopy(PRE_DRAWDOWN_RULES)
        if state['rules']==PRE_DRAWDOWN_RULES and active_rules==RULES:
            backup=ROOT/'migrations'/('drawdown-only-'+now.strftime('%Y%m%dT%H%M%S'))
            save(backup/'ledger_before.json',state)
            state.setdefault('rule_migrations',[]).append(dict(
                date=DRAWDOWN_ONLY_FROM,from_rules=copy.deepcopy(PRE_DRAWDOWN_RULES),to_rules=copy.deepcopy(RULES),
                positions_preserved=len(state['positions']),
                reason='历史放量下跌回看4个自然月，只保留20%—30%回撤分支，事件量比改为3日均量/再往前15日均量'))
            state['rules']=copy.deepcopy(RULES)
        migration_needed=state['rules']!=active_rules
        if migration_needed and (not args.migrate_volume_down or state['rules']!=LEGACY_RULES):
            raise ValueError('Ledger rule version differs; explicit migration required')
        codes=[c for c in risk['stocks'] if c.startswith(('0','3','6')) and not risk['stocks'][c]['excluded']]
        codes=sorted(set(codes)|set(state['positions'])|{x['code'] for x in state['pending_buys']})
        full_universe=len(codes);deferred_codes=[]
        if args.priority_only:
            import priority_universe
            previous=max(d for d in calendar if d<target)
            codes,deferred_codes,_=priority_universe.scope(codes,set(state['positions']),target,previous)
            # Frozen entry signals take precedence even if an offline plan was later regenerated.
            from close_entry import locked_signals
            frozen=locked_signals(target,active_rules['version'])
            codes=sorted(set(codes)|{x['code'] for x in (frozen or {}).get('candidates',[])})
        frames,errors={},[]
        def fetch(code):
            try: return code,history(code,target,args.update,transfer),None
            except Exception as e: return code,None,str(e)
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            for n,(code,df,error) in enumerate(pool.map(fetch,codes),1):
                if error: errors.append(dict(code=code,error=error))
                else: frames[code]=df
                if n%100==0:
                    save(status_path,dict(status='running',date=today,target=target,processed=n,total=len(codes),errors=len(errors),transfer=transfer))
                    print(f'{n}/{len(codes)}',flush=True)
        if migration_needed:
            backup=ROOT/'migrations'/('volume-down-'+now.strftime('%Y%m%dT%H%M%S'))
            save(backup/'ledger_before.json',state)
            save(backup/'latest_before.json',load(ROOT/'latest.json',{}))
            state=migrate_volume_down_rules(state,frames,today,signal_day=target)
        from close_entry import entry_snapshot_for_close,fill_close_orders
        locked=entry_snapshot_for_close(target,now,active_rules['version'],frames,risk,state,today,errors,sessions=calendar)
        candidates=locked.get('candidates',[]) if locked else []
        raw_codes=set(state['positions'])|{p['code'] for p in state['pending_buys']}|{p['code'] for p in candidates}
        raws={}
        for code in sorted(raw_codes):
            try: raws[code]=raw_history(code,target,args.update,transfer)
            except Exception as e: errors.append(dict(code=code,error='Raw price: '+str(e)))
        # Replay only orders actually recorded previously; never invent past buys.
        if state['last_processed_market_date']:
            for day in calendar:
                if day>state['last_processed_market_date'] and day>=state['start_date']:
                    for order in state['pending_buys']:
                        if not order.get('execution_date') and day>order['signal_date'] and day>=order['created_date']:
                            order['execution_date']=day
                    process_day(state,frames,raws,day,risk)
        else:
            state['last_processed_market_date']=target
        close_outcomes=fill_close_orders(state,locked,frames,raws,target) if locked else []
        if locked:
            from close_entry import fill_close_sales
            fill_close_sales(state,frames,raws,target)
        # Position marks may be refreshed without executing an order twice.
        for code,position in state['positions'].items():
            if code in frames and code in raws:
                reasons,mark=sell_reasons(position,frames[code],raws[code],target)
                if mark: position['mark']=mark
        stale=[code for code,df in frames.items() if df.date.iloc[-1]!=target]
        sells=[dict(code=p['code'],name=p['name'],entry_date=p['entry_date'],entry_price=p['entry_price'],
            **p['sell_order'],mark=p.get('mark')) for p in state['positions'].values() if p.get('sell_order')]
        report=dict(generated_at=datetime.now(timezone(timedelta(hours=8))).isoformat(),report_date=target,signal_date=target,is_trading_day=True,
            data_phase='priority_published' if args.priority_only else 'complete',deferred_data_count=len(deferred_codes),full_universe=full_universe,
            rules=active_rules,rule_migrations=state.get('rule_migrations',[]),history_carries=state.get('history_carries',[]),coverage=dict(requested=len(codes),loaded=len(frames),current=len(frames)-len(stale),stale=len(stale),errors=len(errors)),
            entry_signal_snapshot=locked,close_entry_outcomes=close_outcomes,selected_signals=(locked.get('all_selected',candidates) if locked else []),buys=state['pending_buys'],sell_signals=sells,positions=list(state['positions'].values()),closed_trades=state['closed_trades'],
            cancelled=state['cancelled'][-100:],errors=errors,stale_codes=stale,
            notes=['近两年（含信号日）最高/最低后复权收盘价比例≥200%且<400%；不足两年使用已有行情，仍要求上市满六个月。',
                describe_history_filter(active_rules['historical_volume_down']),
                '独立信号模拟，不连接券商，不代表真实成交；无资金或仓位约束，不汇总为账户收益。',
                '每笔模拟100股，不限资金；以收益比例为主。买卖各0.2%为费用及滑点估算，不是实际券商收费。',
                '收益按后复权价格比例估算，成交展示为未复权收盘价；含企业行为近似，不是实际分红现金流核算。',
                '仅最新交易日14:40至15:00间采集14:40价格和累计成交量锁定信号，当日有效收盘价记录模拟买入，不再执行次日开盘价格筛选；卖出在信号触发当日收盘，买入当天禁止卖出。没有有效14:40快照时，按该交易日最终收盘价与全天成交量计算信号并按收盘价成交，标记为收盘兜底，不冒充盘中快照。',
                '风险筛查覆盖当天名称ST/退市标记及补充名单，不能完整识别所有公告风险。',
                '缺失行情不产生新买入或伪造卖出；停牌与接口缺失可能无法区分，详见数据异常。'])
        save(ROOT/'ledger.json',state)
        save(ROOT/'reports'/f'{target}.json',report)
        save(ROOT/'latest.json',report)
        import records_store
        records_store.rebuild()
        if args.priority_only:
            save(ROOT/'data_completion'/f'{target}.json',dict(date=target,status='pending_sync',deferred=len(deferred_codes),note='等待优先买卖结果同步腾讯文档后再补齐全市场日线；不重算已发布交易'))
        if not args.priority_only:pull_daily_data(target,risk,now)
        save(status_path,dict(status='complete',date=today,target=target,coverage=report['coverage'],transfer=transfer,
            buys=len(report['buys']),sells=len(sells),positions=len(state['positions']),closed=len(state['closed_trades'])))
        print(json.dumps(load(status_path),ensure_ascii=False),flush=True)
    except Exception as e:
        save(status_path,dict(status='failed',date=today,error=str(e)))
        raise

if __name__=='__main__': main()
