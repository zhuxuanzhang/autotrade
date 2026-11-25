let chartTicket=0;
const chartEl=id=>document.getElementById(id);
const priceChart=chartEl('trade-chart'),priceRange=chartEl('chart-range');
const pricePlotWidth=680;
let priceView=null,priceDrag=null;

function resetPriceChart(){
  if(priceDrag&&priceChart.hasPointerCapture(priceDrag.id))priceChart.releasePointerCapture(priceDrag.id);
  priceView=null;
  priceDrag=null;
  priceChart.classList.remove('pannable','dragging');
  priceChart.replaceChildren();
  chartEl('chart-navigation').hidden=true;
}

function clearTradeChart(){
  chartTicket++;
  resetPriceChart();
  chartEl('chart-title').textContent='股价走势';
  chartEl('chart-message').textContent='';
}

function bindTradeRow(tr,row){
  tr.dataset.chart=row.code;
  tr.tabIndex=0;
  const select=()=>{document.querySelectorAll('.chart-selected').forEach(x=>x.classList.remove('chart-selected'));tr.classList.add('chart-selected');showTradeChart(row);};
  tr.onclick=select;
  tr.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();select();}};
}

async function showTradeChart(row){
  const ticket=++chartTicket;
  const basis=String(row.price_basis||report?.price_basis||'hfq').match(/raw|未复权/)?'raw':'hfq';
  resetPriceChart();
  chartEl('chart-title').textContent=`${row.name||row.code} · ${row.code}`;
  chartEl('chart-message').textContent='加载本地行情…';
  try{
    const replay=basis==='hfq'&&Boolean(report?.rules_version&&report?.history_end);
    const date=replay?report.history_end:'latest';
    const response=await fetch(`/api/chart?code=${encodeURIComponent(row.code)}&date=${encodeURIComponent(date)}&basis=${basis}${replay?'&source=replay':''}`);
    if(!response.ok)throw Error('行情暂不可用');
    const {rows}=await response.json();
    if(ticket!==chartTicket)return;
    if(!rows.length)throw Error('当前价格口径没有本地行情，需先拉取数据');
    const anchor=rows.findIndex(x=>x.date>=(row.entry_date||row.signal_date));
    const exitIndex=rows.findIndex(x=>x.date===row.exit_date);
    const span=anchor>=0&&exitIndex>=anchor?exitIndex-anchor+61:180;
    const count=Math.min(rows.length,Math.max(180,Math.min(span,360)));
    const maxStart=rows.length-count;
    const markers=[{date:row.entry_date,price:row.entry_price??row.entry_open_hfq,label:'B',color:'#d34e50'},
      {date:row.exit_date,price:row.exit_price??row.exit_open_hfq,label:'S',color:'#16836d'}]
      .filter(marker=>marker.date&&Number.isFinite(marker.price));
    const start=anchor>=0?Math.min(Math.max(0,anchor-30),maxStart):maxStart;
    priceView={rows,markers,count,maxStart,start,basis};
    priceRange.max=String(maxStart);
    chartEl('chart-navigation').hidden=maxStart===0;
    priceChart.classList.toggle('pannable',maxStart>0);
    renderPriceChart();
  }catch(error){if(ticket===chartTicket)chartEl('chart-message').textContent=error.message;}
}

function renderPriceChart(){
  const {rows,markers,count,start,basis}=priceView;
  const visible=rows.slice(start,start+count);
  const indices=new Map(visible.map((row,index)=>[row.date,index]));
  const mappedMarkers=markers.filter(marker=>indices.has(marker.date));
  const values=[...visible.map(row=>row.close),...mappedMarkers.map(marker=>marker.price)];
  const low=Math.min(...values),high=Math.max(...values),span=high-low||1;
  const x=i=>56+i/Math.max(1,visible.length-1)*pricePlotWidth,y=v=>250-(v-low)/span*210;
  const ns='http://www.w3.org/2000/svg',fragment=document.createDocumentFragment();
  const priceBasis=basis==='raw'?'未复权':'后复权';
  const range=`${visible[0].date} 至 ${visible.at(-1).date}`;
  function add(tag,attrs,text){
    const el=document.createElementNS(ns,tag);
    for(const [key,value] of Object.entries(attrs))el.setAttribute(key,value);
    if(text!==undefined)el.textContent=text;
    fragment.append(el);
    return el;
  }
  for(let i=0;i<4;i++){
    const value=low+span*i/3;
    add('line',{x1:56,x2:736,y1:y(value),y2:y(value),stroke:'#e5eaf0'});
    add('text',{x:4,y:y(value)+4,fill:'#748198'},value.toFixed(2));
  }
  add('polyline',{points:visible.map((row,i)=>`${x(i)},${y(row.close)}`).join(' '),fill:'none',stroke:'#245ada','stroke-width':2});
  for(const marker of mappedMarkers){
    const cx=x(indices.get(marker.date)),cy=y(marker.price);
    const label=marker.label==='B'?'模拟买入':'模拟卖出';
    const description=`${label} · ${marker.date} · ${marker.price.toFixed(2)}元 · ${priceBasis}`;
    const dot=add('circle',{cx,cy,r:6,fill:marker.color,stroke:'white','stroke-width':2,
      role:'button',tabindex:0,'aria-label':description});
    const title=document.createElementNS(ns,'title');
    title.textContent=description;
    dot.append(title);
    dot.onclick=()=>{chartEl('chart-message').textContent=description;};
    dot.onkeydown=event=>{
      if(event.key==='Enter'||event.key===' '){event.preventDefault();dot.onclick();}
    };
    add('text',{x:cx,y:Math.max(16,cy-12),fill:marker.color,'text-anchor':'middle',
      'font-weight':'bold','pointer-events':'none'},marker.label);
  }
  add('text',{x:56,y:284,fill:'#748198'},visible[0].date);
  add('text',{x:736,y:284,fill:'#748198','text-anchor':'end'},visible.at(-1).date);
  priceChart.replaceChildren(fragment);
  priceRange.value=String(start);
  priceRange.setAttribute('aria-valuetext',range);
  chartEl('chart-message').textContent=`${priceBasis} · ${range}`;
}

function movePriceChart(start){
  if(!priceView)return;
  const next=Math.max(0,Math.min(priceView.maxStart,start));
  if(next===priceView.start)return;
  priceView.start=next;
  renderPriceChart();
}

priceRange.addEventListener('input',()=>movePriceChart(Number(priceRange.value)));
priceChart.addEventListener('pointerdown',event=>{
  if(!priceView?.maxStart||priceDrag||!event.isPrimary||event.button!==0)return;
  priceDrag={id:event.pointerId,x:event.clientX,start:priceView.start,active:false};
});
priceChart.addEventListener('pointermove',event=>{
  if(!priceDrag||event.pointerId!==priceDrag.id)return;
  const delta=event.clientX-priceDrag.x;
  if(!priceDrag.active){
    if(Math.abs(delta)<5)return;
    priceDrag.active=true;
    priceChart.setPointerCapture(event.pointerId);
    priceChart.classList.add('dragging');
  }
  const scale=priceChart.getScreenCTM()?.a||1;
  const sessions=Math.round(delta*(priceView.count-1)/(pricePlotWidth*scale));
  movePriceChart(priceDrag.start-sessions);
});
function endPriceDrag(event){
  if(priceDrag?.id!==event.pointerId)return;
  priceDrag=null;
  priceChart.classList.remove('dragging');
}
for(const event of ['pointerup','pointercancel','lostpointercapture'])priceChart.addEventListener(event,endPriceDrag);
priceChart.addEventListener('pointerleave',event=>{
  if(!priceDrag?.active)endPriceDrag(event);
});

chartEl('toggle-stats').onclick=()=>{const panel=chartEl('stats-panel');panel.hidden=!panel.hidden;chartEl('toggle-stats').setAttribute('aria-expanded',String(!panel.hidden));chartEl('toggle-stats').textContent=panel.hidden?'统计数据':'隐藏统计';};

const returnOverviewState={data:null,sourceReport:null,selected:null,signature:null,ticket:0,cache:new Map()};
function returnDate(value){return /^\d{4}-\d{2}-\d{2}$/.test(value||'')?Date.parse(value+'T00:00:00Z'):NaN;}
function returnTrades(data){
  const asof=data.date||data.report_date,unique=new Map();
  for(const trade of data.transactions||[]){
    if(!trade.entry_date||trade.entry_date<'2020-01-01'||trade.entry_date>asof||!Number.isFinite(returnDate(trade.entry_date)))continue;
    const closed=Boolean(trade.exit_date&&trade.exit_date<=asof),value=closed?trade.net_return:trade.floating_return;
    unique.set(trade.code+'|'+trade.entry_date,{...trade,key:trade.code+'|'+trade.entry_date,closed,value:Number.isFinite(value)?value:null,time:returnDate(trade.entry_date)});
  }
  return [...unique.values()];
}
function clearReturnOverview(){
  returnOverviewState.data=null;returnOverviewState.sourceReport=null;returnOverviewState.selected=null;returnOverviewState.signature=null;returnOverviewState.ticket++;
  for(const id of ['return-scatter','return-table-body'])chartEl(id)?.replaceChildren();
  for(const id of ['return-asof','return-count','return-detail'])if(chartEl(id))chartEl(id).textContent='';
  if(chartEl('return-empty'))chartEl('return-empty').hidden=true;
}
async function renderReturnOverview(data){
  if(!data)return;
  returnOverviewState.sourceReport=data;
  const asof=data.date||data.report_date,select=chartEl('return-year'),lastYear=Number(asof.slice(0,4));
  const selectedYear=Number(select.value),year=selectedYear>=2020&&selectedYear<=lastYear?selectedYear:lastYear;
  const years=Array.from({length:Math.max(0,lastYear-2019)},(_,i)=>lastYear-i);
  if([...select.options].map(x=>Number(x.value)).join()!==years.join()){
    select.replaceChildren(...years.map(y=>{const option=document.createElement('option');option.value=y;option.textContent=y+'年';return option;}));
  }
  select.value=String(year);select.onchange=()=>{returnOverviewState.selected=null;renderReturnOverview(returnOverviewState.sourceReport);};
  const signature=JSON.stringify([asof,year,marketAmountState.signature,(data.transactions||[]).map(x=>[x.code,x.name,x.entry_date,x.exit_date,x.net_return,x.floating_return])]);
  if(returnOverviewState.signature===signature)return;
  returnOverviewState.signature=signature;
  const ticket=++returnOverviewState.ticket;
  if(year>=2026){returnOverviewState.data=data;drawReturnOverview();return;}
  chartEl('return-asof').textContent='截至 '+asof;chartEl('return-count').textContent='正在读取'+year+'年…';
  chartEl('return-scatter').replaceChildren();chartEl('return-table-body').replaceChildren();chartEl('return-detail').textContent='';chartEl('return-empty').hidden=true;
  try{
    const key=asof+'|'+year;
    let history=returnOverviewState.cache.get(key);
    if(!history){history=await get('/api/return-trades?date='+encodeURIComponent(asof)+'&year='+year);returnOverviewState.cache.set(key,history);}
    if(ticket!==returnOverviewState.ticket)return;
    returnOverviewState.data=history;drawReturnOverview();
  }catch(error){if(ticket===returnOverviewState.ticket){returnOverviewState.signature=null;chartEl('return-count').textContent=error.message;}}
}
function drawReturnOverview(){
  const data=returnOverviewState.data;if(!data||!chartEl('return-scatter'))return;
  const year=chartEl('return-year').value;
  const rows=returnTrades(data).filter(x=>x.entry_date.slice(0,4)===year);
  const points=rows.filter(x=>Number.isFinite(x.value));
  const asof=data.date||data.report_date;
  chartEl('return-asof').textContent='截至 '+asof;
  chartEl('return-count').textContent=`${rows.length}笔交易 · 已卖出${rows.filter(x=>x.closed).length}笔 · 持仓${rows.filter(x=>!x.closed).length}笔`+(rows.length!==points.length?` · ${rows.length-points.length}笔缺少估值`:'');
  chartEl('return-empty').hidden=rows.length>0;
  const svg=chartEl('return-scatter'),body=chartEl('return-table-body'),rowElements=new Map(),dotElements=new Map(),ns='http://www.w3.org/2000/svg';
  svg.replaceChildren();body.replaceChildren();
  const description=x=>`${x.name||x.code}（${x.code}） · 买入 ${x.entry_date}`+(x.closed?` · 卖出 ${x.exit_date}`:' · 持仓中')+` · ${x.closed?'已实现':'浮动'}净收益 ${pct(x.value)} · ${marketAmountDescription(x)}`;
  function choose(x,scroll){
    returnOverviewState.selected=x.key;
    for(const [key,tr]of rowElements)tr.style.background=key===x.key?'#eef3ff':'';
    for(const [key,dot]of dotElements){dot.setAttribute('r',key===x.key?7:4.5);dot.setAttribute('stroke',key===x.key?'#17283d':dot.dataset.marketMarked==='true'?'#087767':'white');}
    chartEl('return-detail').textContent=description(x);
    if(scroll){const tr=rowElements.get(x.key),area=chartEl('return-table-scroll');if(tr)area.scrollTop+=tr.getBoundingClientRect().top-area.getBoundingClientRect().top-42;}
  }
  for(const x of [...rows].sort((a,b)=>b.entry_date.localeCompare(a.entry_date)||a.code.localeCompare(b.code))){
    const tr=document.createElement('tr');tr.tabIndex=0;tr.style.cursor='pointer';tr.dataset.returnTrade=x.key;
    for(const text of [x.code,x.name||x.code,x.entry_date,x.closed?x.exit_date:'',pct(x.value),Number.isFinite(x.value)?(x.closed?'已实现净收益':'持仓浮动净收益'):'缺少估值']){const td=document.createElement('td');td.textContent=text;tr.append(td);}
    marketAmountCell(tr,x);
    tr.children[4].className=x.value>0?'positive':x.value<0?'negative':'';
    tr.onclick=()=>{choose(x,false);showTradeChart(x);};tr.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();tr.click();}};
    body.append(tr);rowElements.set(x.key,tr);
  }
  function add(tag,attrs,text){const element=document.createElementNS(ns,tag);for(const [key,value]of Object.entries(attrs))element.setAttribute(key,String(value));if(text!==undefined)element.textContent=text;svg.append(element);return element;}
  add('text',{x:10,y:18,fill:'#697a90','font-size':13},'净收益率');
  add('text',{x:1080,y:342,fill:'#697a90','font-size':13,'text-anchor':'end'},'买入日期');
  if(points.length){
    const left=76,right=1078,top=32,bottom=286;
    let first=Math.min(...points.map(x=>x.time)),last=Math.max(...points.map(x=>x.time));
    if(first===last){first-=86400000;last+=86400000;}
    const low=Math.min(0,...points.map(x=>x.value)),high=Math.max(0,...points.map(x=>x.value)),padding=Math.max((high-low)*.09,.01);
    const min=low-padding,max=high+padding,px=time=>left+(time-first)/(last-first)*(right-left),py=value=>bottom-(value-min)/(max-min)*(bottom-top);
    for(let i=0;i<=5;i++){const value=min+(max-min)*i/5;add('line',{x1:left,x2:right,y1:py(value),y2:py(value),stroke:'#e4e9f1'});add('text',{x:left-10,y:py(value)+4,'text-anchor':'end',fill:'#748198','font-size':12},(value*100).toFixed(1)+'%');}
    add('line',{x1:left,x2:right,y1:py(0),y2:py(0),stroke:'#8997aa','stroke-dasharray':'5 4'});
    if(Array.from({length:6},(_,i)=>Math.abs(py(min+(max-min)*i/5)-py(0))).every(distance=>distance>14))add('text',{x:left-10,y:py(0)+4,'text-anchor':'end',fill:'#52657e','font-size':12},'0%');
    const ticks=[first],cursor=new Date(first);cursor.setUTCDate(1);cursor.setUTCMonth(cursor.getUTCMonth()+1);
    while(cursor.getTime()<last){if(cursor.getTime()-first>(last-first)*.055&&last-cursor.getTime()>(last-first)*.055)ticks.push(cursor.getTime());cursor.setUTCMonth(cursor.getUTCMonth()+1);}
    ticks.push(last);
    const stride=Math.max(1,Math.ceil(ticks.length/10));
    for(let i=0;i<ticks.length;i++){if(i!==ticks.length-1&&i%stride)continue;const tick=ticks[i];add('line',{x1:px(tick),x2:px(tick),y1:bottom,y2:bottom+5,stroke:'#8997aa'});add('text',{x:px(tick),y:bottom+24,'text-anchor':i===0?'start':i===ticks.length-1?'end':'middle',fill:'#748198','font-size':12},new Date(tick).toISOString().slice(0,10));}
    for(const x of points){
      const dot=add('circle',{cx:px(x.time),cy:py(x.value),r:4.5,fill:x.closed?'#245ada':'#c27914',opacity:.76,stroke:marketAmountFor(x)?.marked?'#087767':'white','stroke-width':marketAmountFor(x)?.marked?2.8:1.2,'data-market-marked':Boolean(marketAmountFor(x)?.marked),tabindex:0,role:'button','aria-label':description(x),'data-return-trade':x.key});
      const title=document.createElementNS(ns,'title');title.textContent=description(x);dot.append(title);dot.style.cursor='pointer';dot.onclick=()=>choose(x,true);dot.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();choose(x,true);}};dotElements.set(x.key,dot);
    }
    add('desc',{},`截至${asof}，${points.length}笔交易，横轴买入日期、纵轴净收益率。`);
  }else add('text',{x:550,y:160,'text-anchor':'middle',fill:'#8290a3','font-size':14},rows.length?'当前记录缺少可用收益率':'没有匹配的已买入交易');
  const selected=rows.find(x=>x.key===returnOverviewState.selected);
  if(selected)choose(selected,false);else chartEl('return-detail').textContent='';
}
