"""Diagnostic independent-trade backtest. NOT a funded portfolio simulation."""
import argparse
import json
from pathlib import Path
import pandas as pd
import numpy as np

BASE = Path(__file__).resolve().parent

def pullback_signals(close, levels, initial, trend, tolerance=.05, max_wait=10):
    """Fixed breakout anchor; retracement close, then a later recovery close.

    Active setups are not replaced by subsequent new highs. No same-bar
    retracement/recovery inference and no future pivot detection.
    """
    if not 0 < tolerance < 1 or max_wait < 2:
        raise ValueError('Invalid pullback parameters')
    anchors = pd.Series(np.nan, index=close.index)
    signals = pd.Series(False, index=close.index)
    setup = None
    c, lv, initial, trend = (np.asarray(x) for x in (close,levels,initial,trend))
    for i in range(len(c)):
        if setup is not None:
            origin, anchor, touched = setup
            if i-origin > max_wait or c[i] < anchor*(1-tolerance):
                setup = None
                continue
            if touched is not None and i > touched and c[i] > c[i-1] and c[i] > anchor and trend[i]:
                signals.iloc[i] = True
                anchors.iloc[i] = anchor
                setup = None
                continue
            if touched is None and i > origin and c[i] < c[i-1] and anchor*(1-tolerance) <= c[i] <= anchor*(1+tolerance):
                setup = (origin,anchor,i)
        elif initial[i]:
            setup = (i,lv[i],None)
    return anchors, signals


def indicators(df, lookback=20, confirmation_days=1, entry_mode='breakout', pullback_tolerance=.05,
               volume_ratio=None, volume_mode='five_vs_prior15', max_volume_ratio=1.8,
               volume_upper_inclusive=True):
    if lookback < 1 or confirmation_days not in (1, 2):
        raise ValueError('Invalid breakout parameters')
    c = df.close
    ma20, ma60 = c.rolling(20).mean(), c.rolling(60).mean()
    previous_high = c.shift(1).rolling(lookback).max()
    trend = ((c > ma20) & (ma20 > ma60) & (ma20 > ma20.shift(5)) &
              (ma60 >= ma60.shift(5)) & (c / ma20 - 1 <= .08))
    signal = trend & (c > previous_high)
    if volume_ratio is not None:
        if volume_ratio <= 0:
            raise ValueError('Volume ratio must be positive')
        if max_volume_ratio is not None and (not np.isfinite(max_volume_ratio) or max_volume_ratio < volume_ratio):
            raise ValueError('Maximum volume ratio must be finite and >= minimum')
        if volume_mode == 'five_vs_prior15':
            recent_volume = df.volume.rolling(5).mean()
            prior_volume = df.volume.shift(5).rolling(15).mean()
        elif volume_mode == 'day_vs_prior20':
            recent_volume = df.volume
            prior_volume = df.volume.shift(1).rolling(20).mean()
        else:
            raise ValueError('Unknown volume mode')
        signal &= (prior_volume > 0) & (recent_volume >= prior_volume * volume_ratio)
        if max_volume_ratio is not None:
            signal &= (recent_volume <= prior_volume * max_volume_ratio) if volume_upper_inclusive else (recent_volume < prior_volume * max_volume_ratio)
    if entry_mode == 'pullback':
        initial = signal & (df.date >= df.date.iloc[0] + pd.DateOffset(months=6))
        anchor, signal = pullback_signals(c, previous_high, initial, trend, pullback_tolerance)
        return ma20, anchor, signal
    if entry_mode != 'breakout':
        raise ValueError('Unknown entry mode')
    if confirmation_days == 2:
        # Confirm yesterday's breakout against the SAME fixed level; do not
        # accidentally demand a new high against a rolling, elevated level.
        anchor = previous_high.shift(1)
        signal = signal.shift(1, fill_value=False) & trend & (c > anchor)
        previous_high = anchor
    return ma20, previous_high, signal

def exit_reason(close, previous_close, ma, previous_ma, position, age, breakout_exit_fraction=.92):
    if close < position['stop']:
        return 'initial_stop'
    if age <= 5 and close < position['breakout']*breakout_exit_fraction:
        return 'failed_breakout'
    if close < ma and previous_close < previous_ma:
        return 'ma20_two_closes'
    if age >= 15 and close <= position['entry']:
        return 'time_exit'
    return None


def simulate(df, code, start, end, cost=.002, lookback=20, confirmation_days=1,
             entry_mode='breakout', pullback_tolerance=.05, volume_ratio=None,
             breakout_exit_fraction=.92, volume_mode='five_vs_prior15', max_volume_ratio=1.8,
             volume_upper_inclusive=True):
    if not 0 < breakout_exit_fraction < 1:
        raise ValueError('Breakout exit fraction must be between zero and one')
    ma, high, signals = indicators(df, lookback, confirmation_days, entry_mode, pullback_tolerance, volume_ratio, volume_mode, max_volume_ratio, volume_upper_inclusive)
    stop = df.low.rolling(5).min()
    eligible = df.date.iloc[0] + pd.DateOffset(months=6)
    dates = df.date.to_numpy()
    op, cl, lo, hi = (df[col].to_numpy(float) for col in ('open','close','low','high'))
    vol = df.volume.to_numpy(float)
    ma, high, signals, stop = (s.to_numpy() for s in (ma, high, signals, stop))
    trades, position, pending_buy, pending_sell = [], None, None, None
    skipped_locked = 0
    for i in range(65, len(df)):
        day = pd.Timestamp(dates[i])
        if day > end:
            break
        if day < start:
            continue
        # Conservative execution: defer sales/cancel buys on any one-price bar.
        tradable = vol[i] > 0 and abs(hi[i]-lo[i]) > 1e-8
        sold_today = False
        if position is not None and pending_sell is not None and i > position['index']:
            if tradable:
                gross = op[i] / position['entry'] - 1
                net = op[i] * (1-cost) / (position['entry'] * (1+cost)) - 1
                trades.append(dict(code=code, signal_date=position['signal_date'],
                    entry_date=position['entry_date'], exit_date=str(day.date()),
                    gross_return=gross, net_return=net, holding_bars=i-position['index'],
                    exit_reason=pending_sell))
                position, pending_sell, sold_today = None, None, True
            else:
                skipped_locked += 1
        if pending_buy is not None and position is None and not sold_today:
            j = pending_buy
            if tradable and op[i] > high[j] and op[i] <= cl[j]*1.02 and 0 < (op[i]-stop[j])/op[i] <= .08:
                position = dict(index=i, entry=op[i], stop=stop[j], breakout=high[j],
                    signal_date=str(pd.Timestamp(dates[j]).date()), entry_date=str(day.date()))
            elif not tradable:
                skipped_locked += 1
        pending_buy = None
        if position is not None and pending_sell is None:
            age = i-position['index']+1
            pending_sell = exit_reason(cl[i],cl[i-1],ma[i],ma[i-1],position,age,breakout_exit_fraction)
        if position is None and signals[i] and day >= eligible:
            pending_buy = i
    unrealized = None
    if position:
        last = df[df.date <= end].iloc[-1]
        unrealized = dict(code=code, entry_date=position['entry_date'], mark_date=str(last.date.date()),
            marked_gross_return=float(last.close/position['entry']-1), exit_pending=pending_sell)
    return trades, unrealized, skipped_locked

def stats(trades):
    if not len(trades):
        return dict(trades=0)
    r = trades.net_return
    wins, losses = r[r>0], r[r<0]
    return dict(trades=len(trades), win_rate=float((r>0).mean()),
        mean_return=float(r.mean()), median_return=float(r.median()),
        mean_win=float(wins.mean()) if len(wins) else None,
        mean_loss=float(losses.mean()) if len(losses) else None,
        payoff_ratio=float(wins.mean()/-losses.mean()) if len(wins) and len(losses) else None,
        profit_factor=float(wins.sum()/-losses.sum()) if len(losses) else None,
        worst_trade=float(r.min()), best_trade=float(r.max()),
        mean_holding_bars=float(trades.holding_bars.mean()))

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--start', default='2016-01-01')
    p.add_argument('--end', default='2026-11-13')
    p.add_argument('--breakout-exit-fraction', type=float, default=.92)
    args = p.parse_args()
    files = sorted((BASE/'data/a_share_20261114/daily_hfq').glob('*.csv'))
    # Preserve the original 98% baseline used by comparison experiments.
    out = BASE/'reports'/f'backtest_exit_{args.breakout_exit_fraction:g}'
    out.mkdir(exist_ok=True)
    all_trades, open_positions, errors, input_manifest = [], [], [], []
    skipped = 0
    for idx, path in enumerate(files):
        code = path.stem
        if not code.startswith(('0','3','6')):
            continue
        try:
            df = pd.read_csv(path, usecols=['date','open','high','low','close','volume'], parse_dates=['date'])
            if df.date.duplicated().any() or not df.date.is_monotonic_increasing:
                raise ValueError('Invalid date ordering')
            values = df[['open','high','low','close']]
            if not np.isfinite(values.to_numpy()).all() or (values<=0).any().any():
                raise ValueError('Nonpositive/nonfinite prices')
            if (df.high < values[['open','close','low']].max(axis=1)-1e-6).any() or (df.low > values[['open','close','high']].min(axis=1)+1e-6).any():
                raise ValueError('Inconsistent OHLC')
            t, o, s = simulate(df, code, pd.Timestamp(args.start), pd.Timestamp(args.end),
                breakout_exit_fraction=args.breakout_exit_fraction)
            all_trades.extend(t)
            if o:
                open_positions.append(o)
            skipped += s
            input_manifest.append(dict(code=code, rows=len(df), first_date=str(df.date.iloc[0].date()),last_date=str(df.date.iloc[-1].date())))
        except Exception as error:
            errors.append(dict(code=code,error=str(error)))
        if (idx+1)%200 == 0:
            print(f'{idx+1}/{len(files)}', flush=True)
    trades = pd.DataFrame(all_trades)
    if trades.empty:
        raise ValueError('No completed trades')
    trades = trades.sort_values(['entry_date','code'])
    trades.to_csv(out/'trades.csv',index=False,encoding='utf-8-sig')
    pd.DataFrame(open_positions).to_csv(out/'open_positions.csv',index=False,encoding='utf-8-sig')
    yearly = {str(year):stats(g) for year,g in trades.groupby(trades.exit_date.str[:4])}
    # Sensitivity: same executions, change only proportional transaction costs.
    sensitivity = {}
    for cost in (.001,.002,.003):
        temp = trades.copy()
        temp['net_return'] = (1+temp.gross_return)*(1-cost)/(1+cost)-1
        sensitivity[str(cost)] = stats(temp)
    report = dict(start=args.start,end=args.end,breakout_exit_fraction=args.breakout_exit_fraction,
        snapshot_files=len(files), tested_stocks=len(input_manifest),
        errors=errors,overall=stats(trades),yearly=yearly,cost_sensitivity=sensitivity,
        open_positions=len(open_positions),untradable_events=skipped,
        methodology='Independent non-overlapping trades within each stock, next available row open execution; not a portfolio. Six calendar months from earliest observed history. Fixed all-in fee/slippage 0.2% each side. No historical ST/risk filter. Current-listed partial universe. Adjusted-price approximate returns; no lot sizing or limit-price reconstruction.',
        inputs=input_manifest)
    (out/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    s=report['overall']
    rows=''.join(f"<tr><td>{year}</td><td>{v['trades']}</td><td>{v['win_rate']:.1%}</td><td>{v['mean_return']:.2%}</td><td>{v['median_return']:.2%}</td></tr>" for year,v in yearly.items())
    page=f'''<!doctype html><meta charset="utf-8"><title>右侧策略历史回测</title><style>body{{font:16px/1.8 system-ui;max-width:1000px;margin:40px auto;padding:24px;color:#17283d;background:#f5f7fa}}section{{background:white;padding:24px;border-radius:12px;margin:20px 0}}table{{width:100%;text-align:left;border-collapse:collapse}}td,th{{padding:10px;border-bottom:1px solid #eee}}.warning{{background:#fff2db;padding:20px}}a{{color:#245ada}}</style><a href="/">← 返回选股看板</a><h1>右侧策略 · 历史诊断回测</h1><p>{args.start} — {args.end} · 已下载样本 {len(files)} 只 / 有效 {len(input_manifest)} 只</p><p class="warning">这不是完整策略或账户收益回测：缺少历史ST/退市风险名单，当前上市股票池存在幸存者偏差，下载样本不完整且按代码顺序形成。后复权价格和一字行情过滤不能完整复原真实成交。</p><section><h2>已平仓交易</h2><p>交易次数 {s['trades']:,} · 胜率 {s['win_rate']:.1%} · 平均单笔净收益 {s['mean_return']:.2%}<br>中位数 {s['median_return']:.2%} · 平均持有 {s['mean_holding_bars']:.1f} 个交易日<br>期末未平仓 {len(open_positions)} 笔，未计入已平仓胜率和平均收益。</p></section><section><h2>按平仓年份统计</h2><table><tr><th>年份</th><th>交易数</th><th>胜率</th><th>平均单笔</th><th>单笔中位数</th></tr>{rows}</table></section><section><h2>规则与口径</h2><p>入场沿用收盘价突破、MA20/MA60与8%偏离限制；信号后下一条行情开盘高于突破位、较信号收盘涨幅≤2%、距5日最低价风险≤8%时进入。每只股票只持有一笔。</p><p>退出：跌破初始5日最低价；买入后前5个交易日跌破突破位{args.breakout_exit_fraction:.0%}；连续2日收盘低于MA20；持有15日仍未盈利。收盘触发，下一可交易开盘退出。一字行情不买入，卖出延后。</p><p>费用与滑点合计按每边0.2%固定估算，并非复原各年真实费率。未模拟账户资金、行业仓位、100股交易单位或历史涨跌停价格，因此不报告账户年化收益和账户最大回撤。</p><a href="/backtest-trades.csv">下载逐笔交易CSV</a></section>'''
    (out/'index.html').write_text(page,encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in ('inputs','yearly')},ensure_ascii=False),flush=True)

if __name__=='__main__':
    main()
