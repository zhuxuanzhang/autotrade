"""Historical entry filter; only information strictly before the signal date."""
import pandas as pd
import numpy as np

CONFIG=dict(lookback_months=6,consecutive_sessions=3,consecutive_min_pct=9.,consecutive_max_pct=18.,
    peak_lookback_sessions=60,drawdown_min_pct=20.,drawdown_max_pct=30.,volume_min=1.2,volume_max=1.8,
    combination='OR',inclusive_bounds=True)

def describe_history_filter(config=CONFIG):
    months=config['lookback_months']
    recent=config.get('volume_recent_sessions',5)
    drawdown=(f"当日收跌且较此前{config['peak_lookback_sessions']}个交易日最高收盘价"
              f"回撤{config['drawdown_min_pct']:g}%—{config['drawdown_max_pct']:g}%")
    if config.get('consecutive_enabled',True):
        drawdown=(f"连续{config['consecutive_sessions']}日累计跌"
                  f"{config['consecutive_min_pct']:g}%—{config['consecutive_max_pct']:g}%，或"+drawdown)
    return (f"信号日前{months}个自然月内至少发生一次：{drawdown}。"
            f"事件{recent}日/前15日量比{config['volume_min']:.2f}—{config['volume_max']:.2f}，区间含边界。")


def historical_volume_down(df,signal_date,config=CONFIG):
    target=pd.Timestamp(signal_date)
    visible=df[pd.to_datetime(df.date)<target].copy()
    if visible.empty: return []
    dates=pd.to_datetime(visible.date)
    c=visible.close.astype(float)
    v=visible.volume.astype(float)
    recent=config.get('volume_recent_sessions',5)
    prior=v.shift(recent).rolling(15).mean()
    ratio=v.rolling(recent).mean()/prior
    volume=(prior>0)&np.isfinite(ratio)&ratio.between(config['volume_min'],config['volume_max'])
    falling=c.lt(c.shift(1))
    consecutive=falling&falling.shift(1,fill_value=False)&falling.shift(2,fill_value=False)
    decline=((1-c/c.shift(3))*100).round(10)
    drawdown=((1-c/c.shift(1).rolling(config['peak_lookback_sessions']).max())*100).round(10)
    window=dates.ge(target-pd.DateOffset(months=config['lookback_months']))
    events=[]
    branches=[]
    if config.get('consecutive_enabled',True):
        branches.append(('consecutive','连续3日累计下跌',
                         consecutive&decline.between(config['consecutive_min_pct'],config['consecutive_max_pct']),decline))
    branches.append(('drawdown',f"较此前{config['peak_lookback_sessions']}日最高收盘价回撤",
                     falling&drawdown.between(config['drawdown_min_pct'],config['drawdown_max_pct']),drawdown))
    for kind,label,mask,value in branches:
        matched=visible.index[volume&window&mask]
        if len(matched):
            i=matched[-1]
            events.append(dict(kind=kind,event_date=dates.loc[i].date().isoformat(),decline_pct=float(value.loc[i]),
                volume_ratio=float(ratio.loc[i]),reason=f"{dates.loc[i].date()} {label}{value.loc[i]:.2f}%，事件{recent}日/前15日量比{ratio.loc[i]:.3f}"))
    return events
