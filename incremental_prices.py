"""Raw daily prices + dated Sina HFQ factors; overlap-verified incremental updates."""
import ast,json
from pathlib import Path
import requests,pandas as pd,numpy as np
PRICE=['open','high','low','close']

def factors_for(dates,factors):
    f=factors.copy();f['date']=pd.to_datetime(f.date);f=f.sort_values('date').drop_duplicates('date',keep='last')
    d=pd.DataFrame({'date':pd.to_datetime(dates)})
    result=pd.merge_asof(d.sort_values('date'),f,on='date',direction='backward').factor.to_numpy(float)
    if not np.isfinite(result).all() or (result<=0).any():raise ValueError('Missing or invalid dated adjustment factor')
    return result

def assemble(base_hfq,recent_raw,factors,target):
    base=base_hfq.copy().reset_index(drop=True);raw=recent_raw.copy().reset_index(drop=True)
    raw['date']=pd.to_datetime(raw.date).dt.strftime('%Y-%m-%d');raw=raw[raw.date<=target].sort_values('date').drop_duplicates('date',keep='last')
    if raw.empty or raw.date.iloc[-1]!=target:raise ValueError('Incremental quote has not reached target session')
    hfq=raw.copy();mult=factors_for(raw.date,factors)
    for key in PRICE:hfq[key]=(raw[key].astype(float)*mult).round(2)
    overlap=base[['date']+PRICE].merge(hfq[['date']+PRICE],on='date',suffixes=('_old','_new'))
    if len(overlap)<min(5,len(base)):raise ValueError('Insufficient overlap for incremental validation')
    for key in PRICE:
        if (overlap[key+'_old']-overlap[key+'_new']).abs().gt(.011).any():raise ValueError('Adjustment/source mismatch; requires full snapshot: '+key)
    volumes=base[['date','volume']].merge(raw[['date','volume']],on='date',suffixes=('_old','_new'))
    volumes=volumes[(volumes.volume_old>0)&(volumes.volume_new>0)]
    if len(volumes):
        unit_ratio=float((volumes.volume_new/volumes.volume_old).median())
        if not .05<unit_ratio<20:raise ValueError('Volume unit mismatch; refuse100x or1/100 splice')
    # Preserve original HFQ history exactly; only append dates which were missing.
    added=hfq[hfq.date>base.date.iloc[-1]]
    merged=pd.concat([base,added],ignore_index=True)
    if merged.date.duplicated().any() or not merged.date.is_monotonic_increasing:raise ValueError('Duplicate or out-of-order incremental rows')
    # Historical raw prices recovered from stored HFQ + original dated factors are explicitly labelled derived.
    full_raw=base.copy();old_mult=factors_for(base.date,factors)
    if (old_mult<1).any():raise ValueError('Factor below1 makes cent-rounded inversion ambiguous')
    for key in PRICE:full_raw[key]=(base[key].astype(float)/old_mult).round(2)
    # Use provider raw prices wherever available, without discarding earlier recovered history.
    full_raw=pd.concat([full_raw[full_raw.date<raw.date.iloc[0]],raw],ignore_index=True)
    return merged,full_raw

def fetch_recent(code,target,last_date):
    import akshare as ak
    symbol=('sh' if code.startswith('6') else 'sz')+code
    start=(pd.Timestamp(last_date)-pd.Timedelta(days=45)).date().isoformat()
    response=requests.get('https://proxy.finance.qq.com/ifzqgtimg/appstock/app/newfqkline/get',params={'param':f'{symbol},day,{start},{target},640,'},timeout=15)
    response.raise_for_status();payload=response.json()['data'][symbol]
    rows=payload.get('day')
    if not rows:raise ValueError('Raw quote source missing day data')
    raw=pd.DataFrame([r[:6] for r in rows],columns=['date','open','close','high','low','volume'])
    for key in PRICE+['volume']:raw[key]=pd.to_numeric(raw[key],errors='coerce')
    raw.volume=raw.volume*(1 if code.startswith(('688','689')) else 100)
    url=ak.stock_zh_a_daily_sina.__globals__['zh_sina_a_stock_hfq_url'].format(symbol)
    response=requests.get(url,timeout=15);response.raise_for_status()
    value=ast.literal_eval(response.text.split('=',1)[1].split('\n')[0])['data']
    factors=pd.DataFrame(value).rename(columns={'d':'date','f':'factor'})[['date','factor']]
    factors.factor=pd.to_numeric(factors.factor,errors='coerce')
    return raw,factors

def atomic_csv(path,df):
    path.parent.mkdir(parents=True,exist_ok=True);tmp=path.with_suffix('.tmp');df.to_csv(tmp,index=False,encoding='utf-8-sig');tmp.replace(path)

def update(code,target,base_hfq,root,validate,store):
    raw,factors=fetch_recent(code,target,base_hfq.date.iloc[-1])
    raw=validate(raw[pd.to_datetime(raw.date)<=pd.Timestamp(target)])
    hfq,full_raw=assemble(base_hfq,raw,factors,target);hfq=validate(hfq);full_raw=validate(full_raw)
    folder=Path(root)/'price_store'
    # Publish the source factor table and paired datasets only after all validations pass.
    atomic_csv(folder/'factors'/f'{code}.csv',factors.sort_values('date'))
    atomic_csv(folder/'raw'/f'{code}.csv',full_raw)
    atomic_csv(folder/'hfq'/f'{code}.csv',hfq)
    meta=folder/f'{code}.json';meta.parent.mkdir(parents=True,exist_ok=True)
    temp=meta.with_suffix('.tmp');temp.write_text(json.dumps(dict(code=code,target=target,method='raw_times_dated_hfq_factor',historical_raw='derived from original rounded HFQ divided by dated factor; recent dates replaced by provider raw',recent_raw_source='Tencent',factor_source='Sina',overlap_verified=True),ensure_ascii=False),encoding='utf-8');temp.replace(meta)
    store(code,target,'market',hfq,'incremental:raw+dated_sina_factors')
    store(code,target,'raw',full_raw,'incremental:recent_provider_raw+derived_older_raw')
    return hfq,full_raw
