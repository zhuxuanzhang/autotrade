"""Persistent trade journal plus precomputed daily views; no quote reads on HTTP requests."""
import json,sqlite3,hashlib
from pathlib import Path
import unified_records as u
BASE=Path(__file__).resolve().parent
DB=BASE/'data/daily_signals/records.sqlite3'
def connect():
    con=sqlite3.connect(DB,timeout=30);con.row_factory=sqlite3.Row;return con
def rebuild():
    DB.parent.mkdir(parents=True,exist_ok=True)
    index,live,dates=u.timeline()
    source_paths=[BASE/'unified_records.py',BASE/'records_store.py',u.HIST/'index.json']
    static=hashlib.sha256(b''.join(p.read_bytes() for p in source_paths)).hexdigest()
    dynamic=hashlib.sha256((BASE/'data/daily_signals/latest.json').read_bytes()).hexdigest()
    con=connect();con.executescript("""PRAGMA journal_mode=WAL;
    CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value TEXT);
    CREATE TABLE IF NOT EXISTS daily(date TEXT PRIMARY KEY,payload TEXT NOT NULL,buys INTEGER,sells INTEGER,positions INTEGER);
    CREATE TABLE IF NOT EXISTS trades(trade_id TEXT PRIMARY KEY,code TEXT,entry_date TEXT,exit_date TEXT,net_return REAL,holding REAL,payload TEXT);
    CREATE TABLE IF NOT EXISTS trade_days(date TEXT,trade_id TEXT,action TEXT,PRIMARY KEY(date,trade_id,action));
    CREATE TABLE IF NOT EXISTS signals(signal_id TEXT PRIMARY KEY,trade_id TEXT,side TEXT,date TEXT,payload TEXT);
    """)
    meta={r['key']:r['value'] for r in con.execute('SELECT * FROM metadata')}
    if meta.get('static')==static and meta.get('dynamic')==dynamic:
        con.close();return dict(status='unchanged',days=len(dates))
    full=meta.get('static')!=static
    refresh=dates if full else [d for d in dates if d>=index['end']]
    # Memoize JSON only during this single publication. HTTP never calls the calculation layer.
    from functools import lru_cache
    original_read=u.read;u.read=lru_cache(maxsize=1024)(original_read)
    if hasattr(u,'price_history'):u.price_history.cache_clear()
    if hasattr(u.entry_evidence,'cache_clear'):u.entry_evidence.cache_clear()
    if hasattr(u.resolve_buy_signal,'cache_clear'):u.resolve_buy_signal.cache_clear()
    latest=None
    try:
        prepared=[]
        for i,d in enumerate(refresh):
            value=u.linked_events(d)
            for x in value['transactions']:x['trade_id']=x['code']+'|'+x['entry_date']
            for x in value['operations']:
                x['trade_id']=x['code']+'|'+x['entry_date'] if x.get('entry_date') else None
            prepared.append(value)
            if d==dates[-1]:latest=value
            if (i+1)%25==0:print('prepared',i+1,'/',len(refresh),flush=True)
        if latest is None:latest=u.linked_events(dates[-1])
        # Publish all views and canonical records in one transaction; readers keep seeing old complete data until commit.
        with con:
            if full:
                con.execute('DELETE FROM daily')
                con.execute('DELETE FROM signals')
            for d in prepared:
                con.execute('INSERT OR REPLACE INTO daily VALUES(?,?,?,?,?)',(d['date'],json.dumps(d,ensure_ascii=False,allow_nan=False),len(d['buys']),len(d['sells']),len(d['positions'])))
            con.execute('DELETE FROM trades');con.execute('DELETE FROM trade_days')
            for t in latest['transactions']:
                trade_id=t['code']+'|'+t['entry_date'];t['trade_id']=trade_id
                con.execute('INSERT INTO trades VALUES(?,?,?,?,?,?,?)',(trade_id,t['code'],t['entry_date'],t.get('exit_date'),t.get('net_return'),t.get('holding_bars'),json.dumps(t,ensure_ascii=False)))
                con.execute('INSERT INTO trade_days VALUES(?,?,?)',(t['entry_date'],trade_id,'buy'))
                if t.get('exit_date'):con.execute('INSERT INTO trade_days VALUES(?,?,?)',(t['exit_date'],trade_id,'sell'))
            # Persist buy/sell signals and their resolved execution status, linked to the same trade when filled.
            for d in prepared:
                for side,key in [('buy','buy_events'),('sell','sell_events')]:
                    for e in d[key]:
                        signal_id=e['event_id'];entry=e.get('entry_date') or (e.get('execution_date') if side=='buy' else None)
                        trade_id=e['code']+'|'+entry if entry else None
                        con.execute('INSERT OR REPLACE INTO signals VALUES(?,?,?,?,?)',(signal_id,trade_id,side,e.get('signal_date'),json.dumps(e,ensure_ascii=False)))
            con.execute("UPDATE signals SET trade_id=(SELECT t.trade_id FROM trades t WHERE t.code=json_extract(signals.payload,'$.code') AND ((signals.side='buy' AND json_extract(t.payload,'$.signal_date')=signals.date) OR (signals.side='sell' AND t.entry_date=json_extract(signals.payload,'$.entry_date'))) LIMIT 1)")
            for key,value in [('static',static),('dynamic',dynamic),('cutoff',dates[-1]),('carry_complete',str(not bool(u.stats(dates[-1],dates[-1])['historical_open_not_extended'])))]:
                con.execute('INSERT OR REPLACE INTO metadata VALUES(?,?)',(key,value))
        return dict(status='complete',days=len(dates),refreshed=len(refresh),trades=len(latest['transactions']))
    finally:u.read=original_read;con.close()
def dates():
    with connect() as con:return {'dates':[r[0] for r in con.execute('SELECT date FROM daily ORDER BY date')]}
def day(date):
    with connect() as con:r=con.execute('SELECT payload FROM daily WHERE date=?',(date,)).fetchone()
    if not r:raise ValueError('该日期没有已生成的交易日记录')
    return json.loads(r[0])
def stats(start,end):
    with connect() as con:
        counts=con.execute('SELECT COUNT(*),COALESCE(SUM(buys),0),COALESCE(SUM(sells),0) FROM daily WHERE date BETWEEN ? AND ?',(start,end)).fetchone()
        last=con.execute('SELECT positions FROM daily WHERE date<=? ORDER BY date DESC LIMIT 1',(end,)).fetchone()
        def aggregate(where,args):
            r=con.execute('SELECT COUNT(*),AVG(CASE WHEN net_return>0 THEN 1.0 ELSE 0.0 END),AVG(net_return),AVG(holding) FROM trades WHERE '+where,args).fetchone()
            return dict(count=r[0],win_rate=r[1],mean_return=r[2],holding_days=r[3])
        realized=aggregate('exit_date BETWEEN ? AND ?',(start,end))
        cohort=aggregate('entry_date BETWEEN ? AND ? AND exit_date<=?',(start,end,end))
        return dict(start=start,end=end,trading_days=counts[0],buys=counts[1],sells=counts[2],realized=realized,entry_cohort=cohort,last_positions=last[0] if last else 0,historical_open_not_extended=0)
if __name__=='__main__':print(rebuild(),flush=True)
