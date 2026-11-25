// Shared manual update control, independent of report availability.
(() => {
  const button = document.getElementById('pull-data');
  const capture = document.getElementById('capture-1440');
  const status = document.getElementById('pull-status');
  let checking = false, submitting = false, fastPullNotice='';
  async function check() {
    if (checking || submitting) return;
    checking = true;
    try {
      const response = await fetch('/api/daily-status');
      if (!response.ok) throw Error('无法读取拉取状态');
      const data = await response.json();
      if (submitting) return;
      const running = data.status === 'running';
      button.disabled = running;
      const windowResponse=await fetch('/api/capture-window');const gate=windowResponse.ok?await windowResponse.json():{enabled:false,reason:'无法读取采集时段'};
      capture.disabled=running||!gate.enabled;capture.title=gate.reason||'';
      capture.textContent = running && data.mode==='capture1440' ? '正在采集14:40并运行…' : '采集14:40数据并运行策略';


      button.textContent = running ? '正在拉取数据…' : '主动拉取数据';
      status.className = data.status === 'failed' ? 'error' : 'muted';
      status.textContent = running
        ? `正在处理行情与策略信号 ${data.processed || 0} / ${data.total || '…'}`
        : data.status === 'failed' ? `任务失败：${data.error || '请重试'}`
        : data.status === 'complete' ? `任务完成 · 行情截至 ${data.target || data.date} · 买入候选 ${data.buys || 0} · 卖出信号 ${data.sells || 0} · 异常 ${data.coverage?.errors || 0} 项；结果请查看每日信号页。`
        : '主动拉取按交易日标记补齐行情；当日允许时段内可采集14:40数据并计算信号。';
      if(data.mode==='capture1440')status.textContent=data.status==='failed'?`14:40采集失败：${data.error}`:running?`${data.phase||'处理14:40数据'} ${data.processed||0}/${data.total||'…'}；异常${data.errors||0}`:`${data.note||'14:40采集完成'} · 行情截至${data.target||data.date}`;
      if (data.mode === 'pull') {
        status.textContent = running ? `正在按交易日标记拉取 ${data.processed || 0} / ${data.total || '…'}`
          : `行情检查完成 · 截至 ${data.target} · 异常 ${data.coverage?.errors || 0} 项 · 较旧 ${data.coverage?.stale || 0} 份。当日采集时段内，可点击“采集14:40数据并运行策略”。`;
        if (data.issues?.length) status.textContent += ' 异常：' + data.issues.map(x => `${x.code}：${x.error}`).join('；') + '。异常及较旧行情30分钟后可重试。';
      }
      if(!running&&fastPullNotice)status.textContent=fastPullNotice;
      if (data.transfer) status.textContent += ` 按日标记跳过 ${data.transfer.marked || 0} 份，快照信息复用 ${data.transfer.metadata_reused || 0} 份，本地复用 ${data.transfer.local} 份，需拉取 ${data.transfer.requested} 份，成功 ${data.transfer.downloaded} 份。`;
    } catch (error) {
      status.textContent = error.message;
      status.className = 'error';
    } finally { checking = false; }
  }
  async function start(endpoint) {
    if (submitting || button.disabled) return;
    submitting = true;fastPullNotice='';
    capture.disabled = true;
    button.disabled = true;

    button.textContent = '正在检查本地数据…';
    try {
      const response = await fetch(endpoint, {method: 'POST'});
      if (!response.ok){let message='无法启动任务，请稍后重试';try{message=(await response.json()).error||message;}catch(e){}throw Error(message);}
      const result=await response.json();if(result.already_checked){fastPullNotice=`最新已收盘交易日${result.target}已检查完成，无需重复拉取`+(result.coverage?.stale?`；${result.coverage.stale}只行情较旧，将在重试到期后重新检查。`:'。');status.textContent=fastPullNotice;return;}
      status.textContent = endpoint === '/api/daily-update' ? '正在读取交易日标记并补齐行情…' : '正在计算选股与卖出策略…';
    } catch (error) {
      status.textContent = error.message;
      status.className = 'error';
      button.disabled = false;

      button.textContent = '主动拉取数据';
    } finally { submitting = false;check(); }
  };
  capture.onclick = () => start('/api/capture-1440-run');
  button.onclick = () => start('/api/daily-update');

  check();
  setInterval(check, 3000);
})();
