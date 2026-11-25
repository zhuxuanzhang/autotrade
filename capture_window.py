"""Latest-session-only14:40 evidence may be acquired14:40<=time<15:00 Shanghai."""
from datetime import datetime,timezone,timedelta
from functools import lru_cache
import time,requests
ZONE=timezone(timedelta(hours=8))
def local_now():return datetime.now(ZONE)
def in_window(now):return now.weekday()<5 and (14,40)<=(now.hour,now.minute)<(15,0)
@lru_cache(maxsize=4)
def latest_source_date(bucket):
    response=requests.get('https://web.ifzq.gtimg.cn/appstock/app/minute/query',params={'code':'sz000001'},timeout=5)
    response.raise_for_status();value=response.json()['data']['sz000001']['data']['date']
    return datetime.strptime(value,'%Y%m%d').date().isoformat()
def status(now=None,source_date=None):
    now=now or local_now();day=now.date().isoformat()
    if not in_window(now):return dict(enabled=False,date=day,reason='仅最新交易日当天14:40至15:00前可采集，使用14:40分时数据；历史按收盘价计算')
    try:latest=source_date or latest_source_date(int(time.monotonic()//30))
    except Exception as e:return dict(enabled=False,date=day,reason='无法核实最新交易日，暂不采集：'+str(e))
    if latest!=day:return dict(enabled=False,date=day,latest_trading_date=latest,reason='今天不是行情源的最新交易日，不补采过去交易日')
    return dict(enabled=True,date=day,latest_trading_date=latest,reason='可采集最新交易日14:40数据并运行策略')
