"""Compare requested 92% breakout exit against the preserved 98% baseline."""
import json
from pathlib import Path
import pandas as pd
from backtest import simulate,stats

BASE=Path(__file__).resolve().parent

def main():
    original=json.loads((BASE/'reports/backtest/result.json').read_text(encoding='utf-8'))
    out=BASE/'reports/exit_comparison'
    out.mkdir(exist_ok=True)
    buckets={'直接突破92%':[], '1.5倍量确认92%':[]}
    positions={name:0 for name in buckets}
    for i,item in enumerate(original['inputs']):
        df=pd.read_csv(BASE/'data/a_share_20261114/daily_hfq'/f"{item['code']}.csv",
            usecols=['date','open','high','low','close','volume'],parse_dates=['date'])
        assert len(df)==item['rows'] and str(df.date.iloc[-1].date())==item['last_date']
        for name,ratio in [('直接突破92%',None),('1.5倍量确认92%',1.5)]:
            t,p,_=simulate(df,item['code'],pd.Timestamp(original['start']),pd.Timestamp(original['end']),
                volume_ratio=ratio,breakout_exit_fraction=.92,volume_mode='day_vs_prior20',max_volume_ratio=None)
            buckets[name].extend(t)
            positions[name]+=bool(p)
        if (i+1)%200==0:
            print(f"{i+1}/{len(original['inputs'])}",flush=True)
    variants={'直接突破98%':pd.read_csv(BASE/'reports/breakout_comparison/trades_20_1.csv'),
        '1.5倍量确认98%':pd.read_csv(BASE/'reports/volume_comparison/trades_1.5.csv')}
    for index,(name,rows) in enumerate(buckets.items()):
        df=pd.DataFrame(rows).sort_values(['entry_date','code'])
        assert not (df.exit_reason=='failed_breakout').any(), '92% line should be dominated by initial stop under current entry guard'
        df.to_csv(out/f'trades_92_{index}.csv',index=False,encoding='utf-8-sig')
        variants[name]=df
    order=['直接突破98%','直接突破92%','1.5倍量确认98%','1.5倍量确认92%']
    records=[]
    for name in order:
        df=variants[name]
        for period,start,end in [('全部','2016-01-01','2026-11-13'),('2016—2022','2016-01-01','2022-12-31'),('2023—2026','2023-01-01','2026-11-13')]:
            sub=df[(df.entry_date>=start)&(df.exit_date<=end)]
            records.append(dict(variant=name,period=period,**stats(sub),
                median_holding_bars=float(sub.holding_bars.median()),exit_counts=sub.exit_reason.value_counts().to_dict()))
    result=dict(stocks=len(original['inputs']),records=records,open_positions=positions,
        new_default=.92,old_default=.98,
        note='Entry-day-inclusive first five bars. 92% breakout exit is dominated by initial stop under unchanged <=8% entry-risk guard. All other rules unchanged. Partial current-listed cohort, historical ST/risk unavailable, independent trades not portfolio.')
    (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    pd.DataFrame([{k:v for k,v in r.items() if k!='exit_counts'} for r in records]).to_csv(out/'comparison.csv',index=False,encoding='utf-8-sig')
    sections=[]
    for period in ['全部','2016—2022','2023—2026']:
        rows=''.join(f"<tr><td>{r['variant']}</td><td>{r['trades']:,}</td><td>{r['win_rate']:.1%}</td><td>{r['mean_return']:.2%}</td><td>{r['mean_holding_bars']:.1f}</td><td>{r['profit_factor']:.2f}</td><td>{r['mean_loss']:.2%}</td></tr>" for r in records if r['period']==period)
        sections.append(f'<section><h2>{period}</h2><table><tr><th>入场与退出版本</th><th>交易数</th><th>胜率</th><th>平均单笔净收益</th><th>平均持有日</th><th>盈利因子</th><th>亏损交易平均收益</th></tr>{rows}</table></section>')
    page='''<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>突破位退出线 98% → 92%</title><style>body{font:15px/1.8 system-ui;max-width:1150px;margin:30px auto;padding:24px;background:#f5f7fa;color:#17283d}section{padding:22px;background:white;border-radius:12px;margin:20px 0;overflow:auto}table{width:100%;text-align:left;border-collapse:collapse;white-space:nowrap}td,th{padding:10px;border-bottom:1px solid #eee}.note{background:#fff2dc;padding:20px}</style><a href="/">返回看板</a><h1>突破位退出线：98% → 92%</h1><p>同一批1,195只股票 · 2016—2026年 · 每边综合成本0.2%</p><div class="note">已将回测默认值改为92%，成交量确认仍为对比实验。买入后前5个交易日（含买入日）收盘跌破原突破位92%时安排次日开盘退出。初始止损、均线退出和时间退出保持不变。</div>'''
    page+=''.join(sections)
    page+='''<section><h2>与初始止损的关系</h2><p>原入场条件要求：买入价P高于突破位B，并且初始止损线S≥0.92P。因此S&gt;0.92B，收盘跌破92%突破位时必然已跌破初始止损线。该规则在当前组合中被初始止损覆盖；不能理解为允许所有持仓一直跌到92%才卖。</p><p>收盘触发，下一可交易开盘退出。样本缺少历史ST/退市风险过滤，包含幸存者偏差；这里是独立交易统计，不是账户收益。时段结果不是独立样本外验证，未平仓不计入胜率。</p></section>'''
    (out/'index.html').write_text(page,encoding='utf-8')
    print(json.dumps(records,ensure_ascii=False),flush=True)

if __name__=='__main__':
    main()
