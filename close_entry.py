"""Frozen 14:40 signals and same-session closing-price paper entries."""
from pathlib import Path
import copy,json,math
import pandas as pd
from market_amount_marks import BUY_FILTER, buy_gate, selected as amount_selected
ROOT=Path(__file__).resolve().parent/'data/daily_signals'
def locked_signals(day,version):
    p=ROOT/'intraday_signals'/f'{day}.json'
    if not p.exists():return None
    x=json.loads(p.read_text(encoding='utf-8'))
    if (x.get('rules_version')!=version and not (version=='2026-11-17-close-v8' and x.get('rules_version')=='2026-11-17-close-v7')) or x.get('date')!=day:raise ValueError('Intraday snapshot rule/date mismatch')
    if any(x.get(key,{}).get('status')=='missing' for key in ('market_amount_gate','market_index_gate')):
        return None
    return x

def index_snapshot_allows_buy(snapshot,day,rule):
    from daily_signals import index_meets_ma5
    gate=snapshot.get('market_index_gate',{})
    quote_time=gate.get('quote_time')
    return (gate.get('status')=='passed' and gate.get('reference_date')==day
            and quote_time in ('14:40','close') and quote_time==snapshot.get('quote_time')
            and index_meets_ma5(gate.get('close'),gate.get('ma5'),rule))


def fill_close_orders(state,snapshot,frames,raws,day):
    if not snapshot or snapshot.get('date')!=day:return []
    gate=snapshot.get('market_amount_gate',{})
    if day>=BUY_FILTER['effective_from']:
        ratio=gate.get('ratio')
        if (gate.get('status')!='passed' or not gate.get('reference_date')
                or gate['reference_date']>=day or ratio is None or not amount_selected(ratio)):
            return []
    from daily_signals import row_at,sell_reasons,rules_for_day
    entry_rules=rules_for_day(day)
    index_gate=snapshot.get('market_index_gate',{})
    index_rule=entry_rules.get('market_index_filter')
    if index_rule and not index_snapshot_allows_buy(snapshot,day,index_rule):
        return []
    outcomes=[]
    done={(x['code'],x['signal_date']) for x in state['positions'].values()}
    done|={(x['code'],x['signal_date']) for x in state['closed_trades']}
    for item in snapshot['candidates']:
        if index_rule:
            volume_ratio=item.get('volume_ratio')
            if volume_ratio is None or not entry_rules['volume_min']<=volume_ratio<=entry_rules['volume_max']:
                continue
        code=item['code'];key=(code,item['signal_date'])
        if key in done or code in state['positions']:continue
        df=frames.get(code);raw=raws.get(code)
        row=row_at(df,day) if df is not None else None
        quote=row_at(raw,day) if raw is not None else None
        if row is None or quote is None or quote.volume<=0 or not math.isfinite(float(quote.close)) or quote.close<=0:
            outcomes.append(dict(code=code,signal_date=day,status='缺少有效收盘价，待补齐行情',execution_date=None));continue
        previous=row_at(df,item['reference_previous_date'])
        if previous is None:raise ValueError('Missing previous-session adjustment anchor '+code)
        scale=float(previous.close)/item['reference_previous_hfq']
        position={**copy.deepcopy(item),'entry_date':day,'entry_price':float(quote.close),'quantity':100,'simulation':True,
            'trade_id':code+'-'+day,'sell_order':None,'execution_mode':'same_day_close',
            'breakout_hfq':item['breakout_hfq']*scale,'stop_hfq':float(df[df.date<=day].low.iloc[-5:].min()),
            'signal_close_hfq':float(row.close),'intraday_signal_close_hfq':item['signal_close_hfq']}
        if day>=BUY_FILTER['effective_from']:
            position.update(market_amount_ratio=gate['ratio'],market_amount_reference_date=gate['reference_date'])
        if index_rule:
            position['market_index_gate']=copy.deepcopy(index_gate)
        reasons,mark=sell_reasons(position,df,raw,day)
        if mark:position['mark']=mark
        if reasons:position['sell_order']=dict(signal_date=day,reasons=reasons)
        state['positions'][code]=position;done.add(key)
        outcomes.append(dict(code=code,signal_date=day,status='已按当日收盘价模拟买入',execution_date=day,execution_price=float(quote.close)))
    return outcomes


def fill_close_sales(state,frames,raws,day):
    from daily_signals import (row_at,sell_reasons,COST,INITIAL_STOP_REASON,
                               LEGACY_TIME_EXIT_DAYS,TIME_EXIT_REASON,LEGACY_MA20_EXIT_DAYS,MA20_EXIT_REASONS,rules_for_day)
    active_rules=rules_for_day(day)
    retired_reasons=set()
    if not active_rules.get('initial_stop_enabled',True):
        retired_reasons.add(INITIAL_STOP_REASON)
    if active_rules.get('time_exit_days',LEGACY_TIME_EXIT_DAYS)>LEGACY_TIME_EXIT_DAYS:
        retired_reasons.add(TIME_EXIT_REASON.format(days=LEGACY_TIME_EXIT_DAYS))
    if active_rules.get('ma20_exit_days',LEGACY_MA20_EXIT_DAYS)>LEGACY_MA20_EXIT_DAYS:
        retired_reasons.add(MA20_EXIT_REASONS[LEGACY_MA20_EXIT_DAYS])
    for code,position in list(state['positions'].items()):
        if day<=position['entry_date']:continue
        order=position.get('sell_order')
        if order and retired_reasons.intersection(order['reasons']):
            remaining=[reason for reason in order['reasons'] if reason not in retired_reasons]
            position['sell_order']={**order,'reasons':remaining} if remaining else None
        if code not in frames or code not in raws:continue
        df,raw=frames[code],raws[code]
        row=row_at(df,day);quote=row_at(raw,day)
        if row is None or quote is None or quote.volume<=0:continue
        reasons,mark=sell_reasons(position,df,raw,day)
        if mark:position['mark']=mark
        order=position.get('sell_order')
        if not reasons and not order:continue
        entry=row_at(df,position['entry_date']);raw_entry=row_at(raw,position['entry_date'])
        if entry is None or raw_entry is None:continue
        entry_adj=position['entry_price']*float(entry.close/raw_entry.close)
        gross=float(row.close/entry_adj-1)
        signal_date=order['signal_date'] if order else day
        state['closed_trades'].append({**position,'exit_date':day,'exit_price':float(quote.close),
            'exit_signal_date':signal_date,'exit_reasons':(order['reasons'] if order else reasons),
            'gross_return':gross,'net_return':float((1+gross)*(1-COST)/(1+COST)-1),
            'holding_sessions':int(((df.date>=position['entry_date'])&(df.date<=day)).sum())-1,'exit_execution_mode':'signal_day_close'})
        del state['positions'][code]


def closing_fallback(day,now,version,frames,risk,state,screening_date,errors,*,sessions=()):
    """Persist final daily-bar signals separately; never fabricate intraday quotes."""
    from datetime import timezone,timedelta
    from daily_signals import candidate,save,load,index_buy_gate
    local=now.astimezone(timezone(timedelta(hours=8)))
    if day>local.date().isoformat() or (day==local.date().isoformat() and local.hour<16):
        raise ValueError('Closing fallback requires a confirmed completed trading session')
    path=ROOT/'close_signals'/f'{day}.json'
    saved=load(path)
    if saved is not None:
        if saved.get('rules_version')!=version or saved.get('date')!=day:raise ValueError('Closing snapshot rule/date mismatch')
        return saved
    held=set(state['positions'])|{x['code'] for x in state['closed_trades'] if x.get('exit_date')==day}
    gate=buy_gate(day,sessions)
    index_gate=index_buy_gate(day,sessions,quote_time='close')
    if gate['status']=='missing':
        errors.append(dict(code='market_amount',error='沪深额比待核验：'+gate['reason']))
    if index_gate['status']=='missing':
        errors.append(dict(code='market_index',error='上证MA5待核验：'+index_gate['reason']))
    selected=[]
    for code,df in sorted(frames.items()) if gate['allowed'] and index_gate['allowed'] else ():
        try:
            visible=df[df.date<=day]
            # A midnight replay may reuse the exact prior-session risk snapshot.
            selection_date=day if risk.get('date')==day else screening_date
            item=candidate(code,visible,risk,selection_date,day)
            if item:
                prior=visible.iloc[-2]
                item.update(reference_previous_date=prior.date,reference_previous_hfq=float(prior.close),
                    entry_execution='same_day_close',signal_source='final_close_fallback',
                    status='已有持仓，不重复买入' if code in held else '收盘兜底信号，按当日收盘价模拟买入')
                selected.append(item)
        except Exception as e:errors.append(dict(code=code,error='Closing selection: '+str(e)))
    snapshot=dict(date=day,rules_version=version,captured_at=local.isoformat(),quote_time='close',
        source='final_close_fallback',market_amount_gate=gate,market_index_gate=index_gate,candidates=[x for x in selected if x['code'] not in held],
        all_selected=selected,coverage=dict(requested=len(frames),errors=len(errors)))
    if gate['status']!='missing' and index_gate['status']!='missing':
        save(path,snapshot)
    return snapshot


def entry_snapshot_for_close(day,now,version,frames,risk,state,screening_date,errors,*,sessions=()):
    from daily_signals import rules_for_day
    intraday=locked_signals(day,version)
    index_rule=rules_for_day(day).get('market_index_filter')
    if intraday and (not index_rule or index_snapshot_allows_buy(intraday,day,index_rule)):
        return intraday
    return closing_fallback(day,now,version,frames,risk,state,screening_date,errors,sessions=sessions)
