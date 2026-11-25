"""Signal-time trailing calendar-year closing-price range."""
import pandas as pd
import numpy as np
CONFIG=dict(years=2,minimum_pct=200.,maximum_pct=400.,minimum_inclusive=True,maximum_inclusive=False,price='hfq_close',include_signal_day=True,short_history='available_history')
def two_year_range(df,signal_date):
    target=pd.Timestamp(signal_date)
    dates=pd.to_datetime(df.date)
    visible=df[(dates>=target-pd.DateOffset(years=2))&(dates<=target)]
    if visible.empty or pd.Timestamp(visible.date.iloc[-1])!=target:return None
    c=visible.close.astype(float)
    if not np.isfinite(c).all() or (c<=0).any():return None
    low=float(c.min());high=float(c.max());ratio=round(high/low*100,10)
    return dict(ratio_pct=ratio,minimum_close_hfq=low,maximum_close_hfq=high,
        window_start=(target-pd.DateOffset(years=2)).date().isoformat(),observed_start=pd.Timestamp(visible.date.iloc[0]).date().isoformat(),
        window_end=target.date().isoformat(),passed=200<=ratio<400,
        reason=f'近两年最高/最低收盘价={ratio:.2f}%，要求≥200%且<400%（后复权）')
