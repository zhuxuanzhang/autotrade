"""Predefined breakout variants on the exact prior backtest cohort."""
import json
from pathlib import Path
import pandas as pd
from backtest import simulate, stats

BASE = Path(__file__).resolve().parent
VARIANTS = [('20日突破',20,1),('40日突破',40,1),('60日突破',60,1),('20日突破后站稳两天',20,2)]

def main():
    original = json.loads((BASE/'reports/backtest/result.json').read_text(encoding='utf-8'))
    cohort = original['inputs']
    buckets = {name:[] for name,_,_ in VARIANTS}
    opens = {name:0 for name,_,_ in VARIANTS}
    out = BASE/'reports/breakout_comparison'
    out.mkdir(exist_ok=True)
    for i, item in enumerate(cohort):
        df = pd.read_csv(BASE/'data/a_share_20261114/daily_hfq'/f"{item['code']}.csv",
            usecols=['date','open','high','low','close','volume'],parse_dates=['date'])
        # Refuse silently changed data or different sample composition.
        assert len(df)==item['rows'] and str(df.date.iloc[-1].date())==item['last_date']
        for name,lookback,confirmation in VARIANTS:
            trades, pos, _ = simulate(df,item['code'],pd.Timestamp(original['start']),
                pd.Timestamp(original['end']),lookback=lookback,confirmation_days=confirmation,breakout_exit_fraction=.98)
            buckets[name].extend(trades)
            opens[name] += bool(pos)
        if (i+1)%200==0:
            print(f'{i+1}/{len(cohort)}',flush=True)
    records=[]
    for name, lookback, confirmation in VARIANTS:
        trades=pd.DataFrame(buckets[name])
        trades.to_csv(out/f'trades_{lookback}_{confirmation}.csv',index=False,encoding='utf-8-sig')
        # Historical time slices are descriptive, not a genuinely untouched test.
        for period, low, high in [('全部','2016-01-01','2026-11-13'),('2016—2022','2016-01-01','2022-12-31'),('2023—2026','2023-01-01','2026-11-13')]:
            part=trades[(trades.entry_date>=low)&(trades.exit_date<=high)]
            row=dict(variant=name,period=period,**stats(part))
            row['failed_breakout_share']=float((part.exit_reason=='failed_breakout').mean())
            row['initial_stop_share']=float((part.exit_reason=='initial_stop').mean())
            row['short_trade_share']=float((part.holding_bars<=5).mean())
            records.append(row)
    baseline=next(r for r in records if r['variant']=='20日突破' and r['period']=='全部')
    assert baseline['trades']==original['overall']['trades']
    assert abs(baseline['mean_return']-original['overall']['mean_return'])<1e-10
    result=dict(stocks=len(cohort),start=original['start'],end=original['end'],records=records,
        open_positions=opens,cohort=[x['code'] for x in cohort],
        note='Same 1195-stock prior cohort. Per-side cost 0.2%. Independent trades, no portfolio. Historical ST/risk unavailable, survivor bias and code-order sample. Time slices exclude crossing trades and are not untouched out-of-sample tests. Live strategy is unchanged.')
    (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    pd.DataFrame(records).to_csv(out/'comparison.csv',index=False,encoding='utf-8-sig')
    sections=[]
    for period in ['全部','2016—2022','2023—2026']:
        rows=''.join(f"<tr><td>{r['variant']}</td><td>{r['trades']:,}</td><td>{r['win_rate']:.1%}</td><td>{r['mean_return']:.2%}</td><td>{r['profit_factor']:.2f}</td><td>{r['mean_holding_bars']:.1f}</td><td>{r['failed_breakout_share']:.1%}</td></tr>" for r in records if r['period']==period)
        sections.append(f'<section><h2>{period}</h2><table><tr><th>突破规则</th><th>交易数</th><th>胜率</th><th>平均单笔净收益</th><th>盈利因子</th><th>平均持有交易日</th><th>假突破退出占比</th></tr>{rows}</table></section>')
    html='''<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>突破位规则对比</title><style>body{font:15px/1.8 system-ui;color:#17283d;background:#f5f7fa;max-width:1150px;padding:24px;margin:30px auto}section{background:white;padding:20px;margin:20px 0;border-radius:12px;overflow:auto}table{width:100%;border-collapse:collapse;text-align:left;white-space:nowrap}th,td{padding:10px;border-bottom:1px solid #eee}p{color:#63728a}.note{background:#fff3dd;padding:18px}</style><a href="/">返回看板</a><h1>突破位规则对比</h1><p>相同的1,195只历史样本 · 2016-01-01至2026-11-13 · 每边综合成本0.2%</p><div class="note">独立交易统计，不是账户收益。缺少历史ST及退市风险资料，样本仅包含部分当前上市股票。分时段结果不是独立样本外验证，当前线上策略未自动替换。</div>'''
    html+=''.join(sections)
    html+='<section><h2>如何比较</h2><p>20、40、60日版本采用此前N日最高收盘价，均不包含信号当日。两天确认版本在首次突破后的下一天，继续收在原突破位上方且趋势条件成立，再于之后的交易日开盘尝试入场。其他买卖条件与费用一致；5日初始止损仍以各自信号日计算。等待确认会改变买入时间和止损位。</p><p>盈利因子为所有盈利交易的收益率之和除以亏损交易收益率绝对值之和。按时段统计仅纳入入场和出场均处于该时段的交易，跨界交易不计入分时段表。期末未平仓交易不计入上述统计。</p></section>'
    (out/'index.html').write_text(html,encoding='utf-8')
    print(json.dumps(records,ensure_ascii=False),flush=True)

if __name__=='__main__':
    main()
