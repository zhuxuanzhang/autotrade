"""Screen downloaded closes and render candidates grouped by CNInfo industry."""
import argparse
import csv
import html
import json
from collections import defaultdict, Counter
from pathlib import Path
import time

from right_side import right_side_buy, read_prices
from update_risk import ROOT, china_today, refresh

BASE = Path(__file__).resolve().parent

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', default=str(BASE / 'data/a_share_20261114'))
    args = parser.parse_args()
    data = Path(args.data_dir)
    risk_path = ROOT / 'latest.json'
    risk = json.loads(risk_path.read_text(encoding='utf-8')) if risk_path.exists() else {}
    if risk.get('date') != china_today():
        risk = refresh()
    files = sorted((data / 'daily_hfq').glob('*.csv'))
    if not files:
        raise ValueError('No downloaded history')
    # Freeze the input set so the concurrent downloader does not change coverage.
    loaded, errors = [], []
    for path in files:
        try:
            rows, closes = read_prices(path)
            if not rows:
                raise ValueError('empty history')
            loaded.append((path.stem, rows, closes))
        except Exception as error:
            errors.append(dict(code=path.stem, error=str(error)))
    signal_date = max(rows[-1]['date'] for _, rows, _ in loaded)
    cache_dir = BASE / 'data/industry_profiles'
    cache_dir.mkdir(parents=True, exist_ok=True)
    selected, skipped = [], Counter()
    import akshare as ak
    for code, rows, closes in loaded:
        if rows[-1]['date'] != signal_date:
            skipped['older_price_date'] += 1
            continue
        kwargs = dict(code=code, as_of=signal_date, history_start=rows[0]['date'],
            risk_record=risk['stocks'].get(code), risk_date=risk['date'], screening_date=china_today())
        result = right_side_buy(closes, **kwargs)
        if not result['buy_signal']:
            skipped['not_selected'] += 1
            continue
        cache = cache_dir / f'{code}.json'
        profile = json.loads(cache.read_text(encoding='utf-8')) if cache.exists() else {}
        if profile.get('date') != china_today():
            try:
                frame = ak.stock_profile_cninfo(symbol=code)
                row = frame.iloc[0]
                profile = dict(date=china_today(), industry=str(row['所属行业']),
                    listing_date=str(row['上市日期']), source='巨潮资讯公司资料')
                cache.write_text(json.dumps(profile, ensure_ascii=False), encoding='utf-8')
                time.sleep(.2)
            except Exception as error:
                profile = dict(industry='未分类', error=str(error))
                errors.append(dict(code=code, error='Industry: '+str(error)))
        if profile.get('listing_date'):
            result = right_side_buy(closes, listing_date=profile['listing_date'], **kwargs)
            if not result['buy_signal']:
                skipped['listing_date_filter'] += 1
                continue
        industry = profile.get('industry') or '未分类'
        if industry in ('nan', 'None', '--'):
            industry = '未分类'
        selected.append(dict(code=code, name=risk['stocks'][code]['name'], industry=industry,
            signal_date=signal_date, deviation_pct=round(result['metrics']['deviation_from_ma20']*100, 2)))
    groups = defaultdict(list)
    for item in selected:
        groups[item['industry']].append(item)
    summary = dict(signal_date=signal_date, risk_date=risk['date'], downloaded=len(files),
        universe=len(risk['stocks']), selected=len(selected), sectors=len(groups), skipped=dict(skipped), errors=errors)
    out = BASE / 'reports'
    out.mkdir(exist_ok=True)
    (out/'right_side_sectors.json').write_text(json.dumps(dict(summary=summary, stocks=selected), ensure_ascii=False, indent=2), encoding='utf-8')
    with (out/'right_side_candidates.csv').open('w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=['code','name','industry','signal_date','deviation_pct'])
        writer.writeheader()
        writer.writerows(selected)
    esc = html.escape
    blocks = []
    for industry, stocks in sorted(groups.items(), key=lambda item: (-len(item[1]), item[0])):
        rows_html = ''.join(f"<tr><td>{esc(s['code'])}</td><td>{esc(s['name'])}</td><td>{s['signal_date']}</td><td>{s['deviation_pct']:.2f}%</td></tr>" for s in stocks)
        blocks.append(f'<details open><summary>{esc(industry)} <span>{len(stocks)}只</span></summary><table><thead><tr><th>代码</th><th>名称</th><th>信号日期</th><th>距20日均线</th></tr></thead><tbody>{rows_html}</tbody></table></details>')
    page = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>右侧候选 · 行业分组</title>
<style>body{max-width:1050px;margin:40px auto;padding:0 24px;background:#f4f6fa;color:#172338;font:16px/1.7 system-ui}h1{margin-bottom:4px}p{color:#58667b}.stats{font-size:22px;color:#174a85}input{width:95%;padding:14px;border:1px solid #ccd5e2;border-radius:9px;margin:16px 0}details{background:white;padding:18px 24px;margin:16px 0;border-radius:12px}summary{cursor:pointer;font-weight:650}span{float:right;color:#176e62}table{width:100%;border-collapse:collapse;text-align:left;margin-top:14px}th,td{padding:10px;border-bottom:1px solid #edf0f5}th{color:#657289;font-size:14px}</style>
<h1>右侧候选 · 行业分组</h1>'''
    page += f"<p>收盘信号日期 {signal_date} · 风险名单更新 {risk['date']} · 行业来源：巨潮资讯</p><div class='stats'>{len(selected)} 只候选 / {len(groups)} 个行业</div>"
    page += f"<p>本次快照覆盖已下载 {len(files)} / 股票名单 {len(risk['stocks'])} 只。下载尚未完成时，这不是全市场选股结果；行业入选数量不代表行业强度。旧日期行情不参与本次筛选。</p>"
    page += '<p>已过滤北交所、上市不足六个月、ST及已标记退市风险。名称筛查不等于完整公告风险审查。候选信号不构成成交指令。</p><input id="q" placeholder="搜索股票代码、名称或行业" aria-label="搜索">'
    page += ''.join(blocks) if blocks else '<p>本次没有符合条件的候选股票。</p>'
    page += '''<script>document.getElementById('q').addEventListener('input',e=>{const q=e.target.value.trim().toLowerCase();document.querySelectorAll('details').forEach(d=>{const sector=d.querySelector('summary').textContent.toLowerCase();let any=false;d.querySelectorAll('tbody tr').forEach(r=>{const show=sector.includes(q)||r.textContent.toLowerCase().includes(q);r.hidden=!show;any=any||show});d.hidden=!any})});</script></html>'''
    (out/'right_side_sectors.html').write_text(page, encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False))

if __name__ == '__main__':
    main()
