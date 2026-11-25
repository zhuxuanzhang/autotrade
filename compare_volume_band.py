"""Compare inclusive volume bands 1.2-1.8 and 1.5-1.8, 92% exit."""
import json
from pathlib import Path
import pandas as pd
import numpy as np
from backtest import simulate,stats

BASE=Path(__file__).resolve().parent

def main():
    original=json.loads((BASE/'reports/backtest/result.json').read_text(encoding='utf-8'))
    out=BASE/'reports/volume_band_comparison'
    out.mkdir(exist_ok=True)
    buckets={v:[] for v in (1.2,1.5)}
    positions={v:0 for v in buckets}
    for i,item in enumerate(original['inputs']):
        df=pd.read_csv(BASE/'data/a_share_20261114/daily_hfq'/f"{item['code']}.csv",
            usecols=['date','open','high','low','close','volume'],parse_dates=['date'])
        assert len(df)==item['rows'] and str(df.date.iloc[-1].date())==item['last_date']
        assert np.isfinite(df.volume).all() and (df.volume>=0).all()
        for ratio in buckets:
            t,p,_=simulate(df,item['code'],pd.Timestamp(original['start']),pd.Timestamp(original['end']),
                volume_ratio=ratio,volume_mode='five_vs_prior15',breakout_exit_fraction=.92,max_volume_ratio=1.8)
            buckets[ratio].extend(t)
            positions[ratio]+=bool(p)
        if (i+1)%200==0:
            print(f"{i+1}/{len(original['inputs'])}",flush=True)
    variants={'无量能过滤':pd.read_csv(BASE/'reports/exit_comparison/trades_92_0.csv'),
        '量比≥1.2（无上限）':pd.read_csv(BASE/'reports/average_volume_comparison/trades_1.2.csv'),
        '量比≥1.5（无上限）':pd.read_csv(BASE/'reports/average_volume_comparison/trades_1.5.csv')}
    for ratio,trades in buckets.items():
        df=pd.DataFrame(trades).sort_values(['entry_date','code'])
        df.to_csv(out/f'trades_{ratio}.csv',index=False,encoding='utf-8-sig')
        variants[f'{ratio}≤量比≤1.8']=df
    records=[]
    for name,df in variants.items():
        for period,start,end in [('全部','2016-01-01','2026-11-13'),('2016—2022','2016-01-01','2022-12-31'),('2023—2026','2023-01-01','2026-11-13')]:
            sub=df[(df.entry_date>=start)&(df.exit_date<=end)]
            records.append(dict(variant=name,period=period,**stats(sub),
                median_holding_bars=float(sub.holding_bars.median()),
                short_trade_share=float((sub.holding_bars<=5).mean())))
    result=dict(stocks=len(original['inputs']),records=records,open_positions=positions,
        breakout_exit_fraction=.92,volume_mode='five_vs_prior15',max_volume_ratio=1.8,
        definition='Mean V[t-4:t] / mean V[t-19:t-5], inclusive endpoints. Non-overlapping 5 and 15 trading-session windows. Signal day included in 5-day window. No pullback confirmation. Inclusive upper bound 1.8.',
        limitations='Partial current-listed cohort; no historical ST/risk filters; independent trades not portfolio; repeated historical comparisons not untouched holdout.')
    (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    pd.DataFrame(records).to_csv(out/'comparison.csv',index=False,encoding='utf-8-sig')
    sections=[]
    for period in ['全部','2016—2022','2023—2026']:
        rows=''.join(f"<tr><td>{r['variant']}</td><td>{r['trades']:,}</td><td>{r['win_rate']:.1%}</td><td>{r['mean_return']:.2%}</td><td>{r['mean_holding_bars']:.1f}</td><td>{r['profit_factor']:.2f}</td></tr>" for r in records if r['period']==period)
        sections.append(f'<section><h2>{period}</h2><table><tr><th>成交量规则</th><th>交易数</th><th>胜率</th><th>平均单笔净收益</th><th>平均持有日</th><th>盈利因子</th></tr>{rows}</table></section>')
    page='''<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>量比上限1.8倍回测</title><style>body{font:15px/1.8 system-ui;max-width:1150px;margin:30px auto;padding:24px;background:#f5f7fa;color:#17283d}section{padding:22px;background:white;border-radius:12px;margin:20px 0;overflow:auto}table{width:100%;text-align:left;border-collapse:collapse;white-space:nowrap}td,th{padding:10px;border-bottom:1px solid #eee}.note{background:#fff2dc;padding:20px}</style><a href="/">返回看板</a><h1>持续量能区间：排除超过1.8倍</h1><p>同一批1,195只股票 · 2016—2026年 · 所有版本统一92%退出线 · 每边综合成本0.2%</p><div class="note">独立交易回测，不是账户收益。样本不完整且存在幸存者偏差，未包含历史ST/退市风险过滤；反复比较参数的结果不等于独立样本外验证。成交量回测默认上限已改为1.8，等于1.8保留；两个下限继续对比。网页实时选股尚未启用量能过滤。</div>'''
    page+=''.join(sections)
    page+='''<section><h2>两个窗口不重叠，严格剔除量比大于1.8</h2><p>分子：信号日及前4个交易日成交量均值。分母：信号日前第5至第19个交易日成交量均值，共15日。即最近20条行情中，后5日均量除以前15日均量。</p><pre>recent = volume.rolling(5).mean()
previous = volume.shift(5).rolling(15).mean()
ratio = recent / previous</pre><p>收盘后产生信号，下一交易日开盘尝试买入。不要求回踩企稳，原价格突破、均线方向、追高限制和其他退出规则保留。这里不使用重叠的MA5(volume)/MA15(volume)。期间股本变化仍可能影响成交量可比性。</p></section>'''
    (out/'index.html').write_text(page,encoding='utf-8')
    print(json.dumps(records,ensure_ascii=False),flush=True)

if __name__=='__main__':
    main()
