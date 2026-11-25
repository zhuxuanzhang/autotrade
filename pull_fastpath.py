"""Instant repeat-pull response without importing quote libraries or starting workers."""
import json
from datetime import datetime,timezone,timedelta
_CACHE=None
def read(path):return json.loads(path.read_text(encoding='utf-8'))
def quick_pull_status(base,now=None):
    global _CACHE
    now=now or datetime.now(timezone(timedelta(hours=8)));day=now.date().isoformat()
    root=base/'data/daily_signals';paths=[root/'calendar.json',root/'ledger.json',root/'latest.json',root/'run_status.json',base/'data/risk/latest.json']
    try:
        if _CACHE and _CACHE['base']==str(base) and _CACHE['day']==day and now.isoformat()<_CACHE['expires']:
            check=paths+[_CACHE['manifest']]
            signature=tuple((str(p),p.stat().st_mtime_ns,p.stat().st_size) for p in check)
            if signature==_CACHE['signature']:return dict(_CACHE['result'])
        calendar=read(paths[0]);state=read(paths[1]);report=read(paths[2]);status=read(paths[3]);risk=read(paths[4])
        if status.get('status')!='complete' or status.get('mode')!='pull':return None
        if calendar.get('expires_at','')<=now.isoformat():return None
        target=calendar['dates'][-1]
        if risk.get('date') not in (day,target):return None
        if status.get('target')!=target:return None
        manifest=root/'pull_marks'/f'{target}.json';marks=read(manifest)
        if marks.get('target')!=target or marks.get('version')!=1:return None
        codes={c for c,r in risk['stocks'].items() if c.startswith(('0','3','6')) and not r['excluded']}
        raw=set(state.get('positions',{}))|{x['code'] for x in state.get('pending_buys',[])}|{x['code'] for x in report.get('buys',[])}
        codes|=raw;jobs=['market:'+c for c in codes]+['raw:'+c for c in raw]
        expires=calendar['expires_at']
        for key in jobs:
            item=marks['items'].get(key,{})
            if item.get('status')=='complete':continue
            retry=item.get('retry_after','')
            if retry<=now.isoformat():return None
            expires=min(expires,retry)
        result={**status,'running':False,'already_checked':True,'message':'已完成本交易日检查，无需重复启动；到期异常会重新检查'}
        check=paths+[manifest];signature=tuple((str(p),p.stat().st_mtime_ns,p.stat().st_size) for p in check)
        _CACHE=dict(base=str(base),day=day,expires=expires,signature=signature,result=result,manifest=manifest)
        return dict(result)
    except (OSError,ValueError,KeyError,TypeError):return None
