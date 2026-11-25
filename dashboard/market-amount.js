// Display-only market turnover ratio, anchored to the original entry date.
const marketAmountState={entries:{},signature:''};
function setMarketAmounts(data){marketAmountState.entries=data?.entries||{};marketAmountState.signature=data?.signature||'';}
function marketAmountFor(row){return marketAmountState.entries[row.entry_date||row.signal_date]||null;}
function marketAmountDescription(row){
  const x=marketAmountFor(row);if(!x)return '沪深成交额量比暂缺';
  return `买入前沪深成交额量比 ${x.ratio.toFixed(6)} · 截至 ${x.reference_date} · 最近5日均额 ${(x.recent5_mean/1e8).toFixed(2)}亿元 / 此前10日均额 ${(x.preceding10_mean/1e8).toFixed(2)}亿元`;
}
function marketAmountCell(tr,row){
  const td=document.createElement('td'),x=marketAmountFor(row);td.className='market-amount-cell';
  if(x&&Number.isFinite(x.ratio)){
    const span=document.createElement('span');span.textContent=x.ratio.toFixed(4);
    span.className=x.marked?'market-amount-mark':'market-amount-neutral';
    span.title=marketAmountDescription(row)+(x.marked?' · 符合展示标记条件':'');td.append(span);
  }else{td.textContent='—';td.title='前一交易日或15日窗口成交额尚未齐备，不使用较旧数据替代';}
  tr.append(td);
}
