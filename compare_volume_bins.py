"""Disjoint volume bands on the original fixed cohort; descriptive comparison."""
import json
from pathlib import Path
import pandas as pd
import numpy as np
from backtest import simulate,stats

BASE=Path(__file__).resolve().parent
BINS=[(1.,1.2,False),(1.2,1.4,False),(1.4,1.6,False),(1.6,1.8,True)]

def main():
    original=json.loads((BASE/'reports/backtest/result.json').read_text(encoding='utf-8'))
    out=BASE/'reports/volume_bins'
    out.mkdir(exist_ok=True)
    buckets={i:[] for i in range(len(BINS))}
    positions={i:0 for i in buckets}
    for n,item in enumerate(original['inputs']):
        df=pd.read_csv(BASE/'data/a_share_20261114/daily_hfq'/f"{item['code']}.csv",
            usecols=['date','open','high','low','close','volume'],parse_dates=['date'])
        assert len(df)==item['rows'] and str(df.date.iloc[-1].date())==item['last_date']
        assert np.isfinite(df.volume).all() and (df.volume>=0).all()
        for i,(low,high,inclusive) in enumerate(BINS):
            trades,pos,_=simulate(df,item['code'],pd.Timestamp(original['start']),pd.Timestamp(original['end']),
                volume_ratio=low,max_volume_ratio=high,volume_upper_inclusive=inclusive,
                volume_mode='five_vs_prior15',breakout_exit_fraction=.92)
            buckets[i].extend(trades)
            positions[i]+=bool(pos)
        if (n+1)%200==0:
            print(f"{n+1}/{len(original['inputs'])}",flush=True)
    records=[]
    years=[]
    for i,(low,high,inclusive) in enumerate(BINS):
        label=f'[{low:.1f}, {high:.1f}'+(']' if inclusive else ')')
        trades=pd.DataFrame(buckets[i]).sort_values(['entry_date','code'])
        trades.to_csv(out/f'trades_{low:.1f}_{high:.1f}.csv',index=False,encoding='utf-8-sig')
        for period,start,end in [('全部','2016-01-01','2026-11-13'),('2016—2022','2016-01-01','2022-12-31'),('2023—2026','2023-01-01','2026-11-13')]:
            sub=trades[(trades.entry_date>=start)&(trades.exit_date<=end)]
            records.append(dict(band=label,period=period,**stats(sub),
                median_holding_bars=float(sub.holding_bars.median()),
                unique_stocks=int(sub.code.nunique()),short_trade_share=float((sub.holding_bars<=5).mean())))
        for year,group in trades.groupby(trades.exit_date.str[:4]):
            years.append(dict(band=label,exit_year=year,**stats(group)))
    result=dict(stocks=len(original['inputs']),records=records,yearly=years,open_positions=positions,
        bins=BINS,breakout_exit_fraction=.92,volume_definition='mean V[t-4:t] / mean V[t-19:t-5]; non-overlapping windows',
        limitations='Separate strategy run for each band, not partition of one pooled strategy trade list. Partial current-listed cohort; historical ST/risk unavailable; survivor bias; independent trades not portfolio. Repeated historical tuning, not untouched out-of-sample testing.')
    (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    pd.DataFrame(records).to_csv(out/'comparison.csv',index=False,encoding='utf-8-sig')
    pd.DataFrame(years).to_csv(out/'yearly.csv',index=False,encoding='utf-8-sig')
    sections=[]
    for period in ['全部','2016—2022','2023—2026']:
        rows=''.join(f"<tr><td>{r['band']}</td><td>{r['trades']:,}</td><td>{r['win_rate']:.1%}</td><td>{r['mean_return']:.2%}</td><td>{r['mean_holding_bars']:.1f}</td><td>{r['profit_factor']:.2f}</td><td>{r['unique_stocks']}</td></tr>" for r in records if r['period']==period)
        sections.append(f'<section><h2>{period}</h2><table><tr><th>量比区间</th><th>交易数</th><th>胜率</th><th>平均单笔净收益</th><th>平均持有日</th><th>盈利因子</th><th>交易股票数</th></tr>{rows}</table></section>')
    page='''<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>成交量区间细分</title><style>body{font:15px/1.8 system-ui;max-width:1150px;margin:30px auto;padding:24px;background:#f5f7fa;color:#17283d}section{padding:22px;background:white;border-radius:12px;margin:20px 0;overflow:auto}table{width:100%;text-align:left;border-collapse:collapse;white-space:nowrap}td,th{padding:10px;border-bottom:1px solid #eee}.note{background:#fff2dc;padding:20px}</style><a href="/">返回看板</a><h1>成交量区间细分 · 每0.2倍一组</h1><p>同一批1,195只股票 · 2016—2026年 · 每边综合成本0.2% · 统一92%退出线</p><div class="note">每个区间单独运行策略，不能将交易数直接相加视为合并区间的结果。区间左端包含，右端不包含，只有最后一组包含1.8。尚未更改网页实时选股。</div>'''
    page+=''.join(sections)
    page+='''<section><h2>保持一致的条件</h2><p>量比＝信号日及前4日平均成交量÷再往前15日平均成交量；突破和均线条件、次日开盘成交条件、其他止损均保持不变。各区间独立执行，同一股票不重叠持仓。</p><p>分时段只纳入入场和出场都落在该时段的交易，期末未平仓不纳入胜率；年度CSV按退出年份统计。样本缺少历史ST/退市风险筛查，并有幸存者偏差。这里不是完整账户收益，也不是独立样本外验证，反复细分同一历史样本存在过拟合风险。</p></section>'''
    (out/'index.html').write_text(page,encoding='utf-8')
    print(json.dumps(records,ensure_ascii=False),flush=True)

if __name__=='__main__':
    main()
