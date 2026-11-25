"""User-specified +/-5% pullback and recovery versus prior fixed-cohort runs."""
import json
from pathlib import Path
import pandas as pd
from backtest import simulate, stats

BASE=Path(__file__).resolve().parent

def main():
    baseline=json.loads((BASE/'reports/backtest/result.json').read_text(encoding='utf-8'))
    out=BASE/'reports/pullback_comparison'
    out.mkdir(exist_ok=True)
    trades,positions=[],[]
    for i,item in enumerate(baseline['inputs']):
        df=pd.read_csv(BASE/'data/a_share_20261114/daily_hfq'/f"{item['code']}.csv",
            usecols=['date','open','high','low','close','volume'],parse_dates=['date'])
        assert len(df)==item['rows'] and str(df.date.iloc[-1].date())==item['last_date']
        t,p,_=simulate(df,item['code'],pd.Timestamp(baseline['start']),pd.Timestamp(baseline['end']),
            entry_mode='pullback',pullback_tolerance=.05,breakout_exit_fraction=.98)
        trades.extend(t)
        if p:
            positions.append(p)
        if (i+1)%200==0:
            print(f"{i+1}/{len(baseline['inputs'])}",flush=True)
    current=pd.DataFrame(trades).sort_values(['entry_date','code'])
    current.to_csv(out/'trades.csv',index=False,encoding='utf-8-sig')
    pd.DataFrame(positions).to_csv(out/'open_positions.csv',index=False,encoding='utf-8-sig')
    variants={
        '直接20日突破':pd.read_csv(BASE/'reports/breakout_comparison/trades_20_1.csv'),
        '突破后站稳两天':pd.read_csv(BASE/'reports/breakout_comparison/trades_20_2.csv'),
        '回踩±5%后企稳':current,
    }
    records=[]
    for name,df in variants.items():
        for period,start,end in [('全部','2016-01-01','2026-11-13'),('2016—2022','2016-01-01','2022-12-31'),('2023—2026','2023-01-01','2026-11-13')]:
            sub=df[(df.entry_date>=start)&(df.exit_date<=end)]
            records.append(dict(variant=name,period=period,**stats(sub),
                median_holding_bars=float(sub.holding_bars.median()),
                short_trade_share=float((sub.holding_bars<=5).mean()),
                exit_counts=sub.exit_reason.value_counts().to_dict()))
    result=dict(stocks=len(baseline['inputs']),start=baseline['start'],end=baseline['end'],
        records=records,open_positions=len(positions),
        parameters=dict(pullback_tolerance=.05, max_wait_bars=10, recovery='later close > previous close and original breakout level; trend filters pass',
            entry='next row open; original opening gap/risk guards unchanged', exits='unchanged, including post-entry failed breakout at -2%',cost_per_side=.002),
        limitations=['Partial current-listed code-order cohort; survivorship bias',
            'Historical ST/delisting filters unavailable', 'Independent trades, not portfolio returns',
            'Time slices are descriptive, not untouched holdout',
            'Adjusted OHLC execution approximation; no real limit-price reconstruction'])
    (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    pd.DataFrame([{k:v for k,v in r.items() if k!='exit_counts'} for r in records]).to_csv(out/'comparison.csv',index=False,encoding='utf-8-sig')
    sections=[]
    for period in ['全部','2016—2022','2023—2026']:
        rows=''.join(f"<tr><td>{r['variant']}</td><td>{r['trades']:,}</td><td>{r['win_rate']:.1%}</td><td>{r['mean_return']:.2%}</td><td>{r['mean_holding_bars']:.1f}</td><td>{r['median_holding_bars']:.0f}</td><td>{r['short_trade_share']:.1%}</td></tr>" for r in records if r['period']==period)
        sections.append(f'<section><h2>{period}</h2><table><tr><th>入场方式</th><th>交易数</th><th>胜率</th><th>平均单笔净收益</th><th>平均持有日</th><th>持有日中位数</th><th>≤5日退出</th></tr>{rows}</table></section>')
    page='''<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>回踩企稳回测</title><style>body{font:15px/1.8 system-ui;max-width:1150px;margin:30px auto;padding:24px;color:#17283d;background:#f5f7fa}section{padding:22px;background:white;border-radius:12px;margin:20px 0;overflow:auto}table{width:100%;border-collapse:collapse;text-align:left;white-space:nowrap}td,th{padding:10px;border-bottom:1px solid #eee}.note{background:#fff2dc;padding:20px}p{color:#65758a}</style><a href="/">返回看板</a><h1>突破 → 回踩±5% → 企稳买入</h1><p>固定同一批1,195只股票 · 2016-01-01至2026-11-13 · 每边综合成本0.2%</p><div class="note">仅改变入场方式。历史ST/退市风险资料缺失，样本存在幸存者偏差；这不是完整账户回测。分时段比较不等于独立样本外验证。线上策略未自动替换。</div>'''
    page+=''.join(sections)
    page+='''<section><h2>精确定义</h2><ol><li>首次满足20日突破和原均线条件后，固定原突破位，不随随后新高上移。</li><li>10个交易日内至少一天收盘较前一天下跌，并落在原突破位上下5%的区域。</li><li>回踩之后的另一天，收盘较前一日上涨、严格高于原突破位，且均线条件成立，才确认企稳。</li><li>次日开盘沿用原买入限制：高于突破位，不超过企稳日收盘价102%，距离企稳日近5日最低价不超过8%。</li><li>等待期间收盘跌破原突破位5%或超时，取消本次等待。已持仓后的2%假突破退出、初始止损、均线退出、时间退出均不变。</li></ol><p>同一股票不重叠持仓；等待回踩时间不计入持股时间。各时段仅统计进出场均在时段内的已平仓交易，期末未平仓不计入胜率。行情一字或无量时不买，卖出延后。</p></section>'''
    (out/'index.html').write_text(page,encoding='utf-8')
    print(json.dumps(records,ensure_ascii=False),flush=True)

if __name__=='__main__':
    main()
