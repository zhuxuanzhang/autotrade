"""Direct breakout plus trailing-volume confirmation, same frozen cohort."""
import json
from pathlib import Path
import pandas as pd
import numpy as np
from backtest import simulate, stats

BASE=Path(__file__).resolve().parent

def main():
    original=json.loads((BASE/'reports/backtest/result.json').read_text(encoding='utf-8'))
    out=BASE/'reports/volume_comparison'
    out.mkdir(exist_ok=True)
    buckets={v:[] for v in (1.2,1.5,2.0)}
    positions={v:0 for v in buckets}
    for i,item in enumerate(original['inputs']):
        df=pd.read_csv(BASE/'data/a_share_20261114/daily_hfq'/f"{item['code']}.csv",
            usecols=['date','open','high','low','close','volume'],parse_dates=['date'])
        assert len(df)==item['rows'] and str(df.date.iloc[-1].date())==item['last_date']
        if not np.isfinite(df.volume).all() or (df.volume<0).any():
            raise ValueError(f"Invalid volume for {item['code']}")
        for ratio in buckets:
            t,p,_=simulate(df,item['code'],pd.Timestamp(original['start']),pd.Timestamp(original['end']),volume_ratio=ratio,breakout_exit_fraction=.98,volume_mode='day_vs_prior20',max_volume_ratio=None)
            buckets[ratio].extend(t)
            positions[ratio]+=bool(p)
        if (i+1)%200==0:
            print(f"{i+1}/{len(original['inputs'])}",flush=True)
    variants={'原20日突破':pd.read_csv(BASE/'reports/breakout_comparison/trades_20_1.csv')}
    for ratio,rows in buckets.items():
        df=pd.DataFrame(rows).sort_values(['entry_date','code'])
        df.to_csv(out/f'trades_{ratio}.csv',index=False,encoding='utf-8-sig')
        variants[f'突破日量比≥{ratio}']=df
    records=[]
    for name,df in variants.items():
        for period,start,end in [('全部','2016-01-01','2026-11-13'),('2016—2022','2016-01-01','2022-12-31'),('2023—2026','2023-01-01','2026-11-13')]:
            part=df[(df.entry_date>=start)&(df.exit_date<=end)]
            records.append(dict(variant=name,period=period,**stats(part),
                median_holding_bars=float(part.holding_bars.median()),
                failed_breakout_share=float((part.exit_reason=='failed_breakout').mean()),
                short_trade_share=float((part.holding_bars<=5).mean())))
    result=dict(stocks=len(original['inputs']),records=records,open_positions=positions,
        definition='Signal day volume / mean of preceding 20 session volumes, excluding signal day. Direct breakout, no pullback/recovery requirement. Other rules unchanged.',
        limitations='Partial current-listed cohort; no historical ST/delisting-risk filter; independent trades not portfolio; repeated historical comparisons are not untouched holdout; corporate share changes can affect volume comparability.')
    (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    pd.DataFrame(records).to_csv(out/'comparison.csv',index=False,encoding='utf-8-sig')
    sections=[]
    for period in ['全部','2016—2022','2023—2026']:
        rows=''.join(f"<tr><td>{r['variant']}</td><td>{r['trades']:,}</td><td>{r['win_rate']:.1%}</td><td>{r['mean_return']:.2%}</td><td>{r['mean_holding_bars']:.1f}</td><td>{r['profit_factor']:.2f}</td><td>{r['failed_breakout_share']:.1%}</td></tr>" for r in records if r['period']==period)
        sections.append(f'<section><h2>{period}</h2><table><tr><th>入场条件</th><th>交易数</th><th>胜率</th><th>平均单笔净收益</th><th>平均持有日</th><th>盈利因子</th><th>假突破退出占比</th></tr>{rows}</table></section>')
    page='''<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>成交量确认回测</title><style>body{font:15px/1.8 system-ui;max-width:1150px;margin:30px auto;padding:24px;color:#17283d;background:#f5f7fa}section{background:white;padding:22px;margin:20px 0;border-radius:12px;overflow:auto}table{width:100%;border-collapse:collapse;text-align:left;white-space:nowrap}th,td{padding:10px;border-bottom:1px solid #eee}.note{background:#fff2dc;padding:18px}</style><a href="/">返回看板</a><h1>直接突破 + 成交量确认</h1><p>同一批1,195只股票 · 2016-01-01至2026-11-13 · 每边综合成本0.2%</p><div class="note">不要求回踩企稳。未修改线上选股条件。部分当前上市股票样本缺少历史ST/退市风险过滤，不是账户收益，也不是独立样本外验证。</div>'''
    page+=''.join(sections)
    page+='''<section><h2>成交量口径</h2><p>突破日量比＝当天成交量÷此前20个交易日平均成交量，不包含当天。这里是日线相对成交量，不是行情软件的盘中量比。同一股票按同一来源计算，股/手单位的常数差异会相消；股本变化、异常成交量仍可能影响比较。</p><p>信号收盘后确认，下一交易日开盘尝试买入，原入场追高限制、初始止损、假突破退出、均线退出、时间退出与费用全部不变。分时段仅纳入进出场均在时段内的交易，未平仓不计入胜率。</p></section>'''
    (out/'index.html').write_text(page,encoding='utf-8')
    print(json.dumps(records,ensure_ascii=False),flush=True)

if __name__=='__main__':
    main()
