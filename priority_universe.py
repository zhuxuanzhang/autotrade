"""Proven next-session entry exclusions; unknown or changed data always stays eligible."""
import argparse,concurrent.futures,hashlib,json
from collections import Counter
from datetime import datetime,timezone,timedelta
from pathlib import Path
import pandas as pd
import daily_signals as s

def signature(path):
 try:
  stat=Path(path).stat();return [stat.st_size,stat.st_mtime_ns]
 except OSError:return None

def rule_key(day):return hashlib.sha256(json.dumps(s.rules_for_day(day),sort_keys=True).encode()).hexdigest()

def exclusion(df,day):
 """Only reject when no positive new-session price/volume can satisfy the rules."""
 if len(df)<64:return '历史不足65个交易日（含信号日）'
 if not s.listed_six_months(df.date.iloc[0],day):return '信号日上市未满六个自然月'
 history_rule=s.rules_for_day(day)['historical_volume_down']
 if not s.historical_volume_down(df,day,history_rule):return f"信号日前{history_rule['lookback_months']}个自然月内没有符合条件的历史放量下跌"
 dates=pd.to_datetime(df.date);past=df[dates>=pd.Timestamp(day)-pd.DateOffset(years=2)].close.astype(float)
 # Conservative margin protects equality/rounding boundaries; adding a price cannot shrink this range.
 if len(past) and float(past.max()/past.min()*100)>400.0000001:return '已有两年高低价比超过400%，加入当天价格也不会下降'
 c=df.close.astype(float).to_numpy();a=float(c[-19:].sum());b=float(c[-59:].sum())
 lower=max(float(c[-20:].max()),a/19,(b-3*a)/2,float(c[-24:-4].sum())-a,float(c[-64:-4].sum())-b,0.)
 upper=1.08*a/(20-1.08)
 if lower>upper*(1+1e-10):return '任意当天价格均无法同时满足突破、均线和8%偏离限制'
 prior=float(df.volume.iloc[-19:-4].mean())
 if prior>0 and float(df.volume.iloc[-4:].sum())>5*1.8*prior*(1+1e-10):return '此前四日成交量已使五日量比下限超过1.8'
 return None

def plan_path(day):return s.ROOT/'priority_universe'/day/'plan.json'

def prepare(day,previous):
 if day<=previous:raise ValueError('Preparation needs an upcoming signal date')
 risk=s.load(s.RISK_ROOT/'latest.json',{});state=s.load(s.ROOT/'ledger.json',{})
 held=set(state.get('positions',{}));codes=sorted({c for c,r in risk.get('stocks',{}).items() if c.startswith(('0','3','6')) and not r['excluded']}|held)
 folder=plan_path(day).parent;folder.mkdir(parents=True,exist_ok=True)
 key=rule_key(day)
 old=s.load(plan_path(day),{});reuse=old.get('rules_key')==key and old.get('previous')==previous
 def one(code):
  source=s.ROOT/'market'/previous/f'{code}.csv';sig=signature(source)
  item=old.get('stocks',{}).get(code,{}) if reuse else {}
  if sig and item.get('signature')==sig and item.get('source')==str(source) and (item.get('excluded_reason') or (item.get('compact_signature') and signature(item.get('compact_path',''))==item['compact_signature'])):return code,item
  try:
   if not sig:raise ValueError('缺少前一交易日的已落盘行情，保留优先获取')
   df=pd.read_csv(source,usecols=['date','open','high','low','close','volume'])
   df=df[df.date<=previous]
   if df.empty or df.date.iloc[-1]!=previous:raise ValueError('前一交易日行情落后，保留优先获取')
   reason=exclusion(df,day)
   item=dict(source=str(source),signature=sig,excluded_reason=reason,history_start=df.date.iloc[0])
   if reason is None or code in held:
    cutoff=(pd.Timestamp(day)-pd.DateOffset(years=2,months=6)).date().isoformat()
    compact=df[(df.date>=cutoff)|(df.index>=max(0,len(df)-200))]
    path=folder/f'{code}.csv';compact.to_csv(path,index=False,encoding='utf-8-sig');item['compact_path']=str(path);item['compact_signature']=signature(path)
   return code,item
  except Exception as e:return code,dict(source=str(source),signature=sig,excluded_reason=None,error=str(e))
 stocks={}
 with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
  for n,(code,item) in enumerate(pool.map(one,codes),1):
   stocks[code]=item
   if n%500==0:print(f'prepared {n}/{len(codes)}',flush=True)
 plan=dict(date=day,previous=previous,rules_key=key,stocks=stocks,created_at=datetime.now(timezone(timedelta(hours=8))).isoformat(),
  counts=dict(total=len(codes),possible=sum(not x.get('excluded_reason') for x in stocks.values()),excluded=dict(Counter(x['excluded_reason'] for x in stocks.values() if x.get('excluded_reason')))))
 s.save(plan_path(day),plan);return plan

def scope(codes,held,day,previous):
 plan=s.load(plan_path(day),{})
 valid=plan.get('rules_key')==rule_key(day) and plan.get('previous')==previous and plan.get('date')==day
 priority=[];deferred=[];entries={}
 for code in sorted(set(codes)|set(held)):
  item=plan.get('stocks',{}).get(code,{}) if valid else {}
  trusted=bool(item.get('signature')) and signature(item.get('source',''))==item['signature']
  if code not in held and trusted and item.get('excluded_reason'):deferred.append(code)
  else:priority.append(code)
  if trusted:entries[code]=item
 return priority,deferred,entries

def history(code,previous,entries):
 item=entries.get(code,{})
 if item.get('compact_path') and item.get('compact_signature') and signature(item.get('compact_path',''))==item['compact_signature'] and signature(item.get('source',''))==item.get('signature'):
  try:
   df=pd.read_csv(item['compact_path'])
   if not df.empty and df.date.iloc[-1]==previous:return df
  except (OSError,ValueError):pass
 return s.history(code,previous,False)

def main():
 p=argparse.ArgumentParser();p.add_argument('--day');p.add_argument('--previous');a=p.parse_args()
 day=a.day or s.china_today();calendar=s.load(s.ROOT/'calendar.json',{}).get('dates',[])
 previous=a.previous or max(d for d in calendar if d<day)
 result=prepare(day,previous);print(json.dumps(result['counts'],ensure_ascii=False),flush=True)
if __name__=='__main__':main()
