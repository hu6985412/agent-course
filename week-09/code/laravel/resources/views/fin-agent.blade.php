<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<title>财报 Agent 查询</title>
<style>
  body { font-family: system-ui, -apple-system, sans-serif; margin: 2rem; color: #222; }
  h2 { font-weight: 600; }
  .bar { margin-bottom: 1rem; }
  input { padding: .4rem .6rem; font-size: 1rem; border: 1px solid #ccc; border-radius: 6px; }
  button { padding: .45rem 1rem; font-size: 1rem; border: 0; border-radius: 6px; background: #2d6cdf; color: #fff; cursor: pointer; }
  #log { white-space: pre-wrap; background: #f6f7f9; padding: 1rem; border-radius: 8px; font-family: ui-monospace, Menlo, monospace; font-size: .85rem; min-height: 8rem; }
  .row { margin: .25rem 0; }
  .ok { color: #1a7f37; }
  .warn { color: #9a6700; }
  .bad { color: #cf222e; }
</style>
</head>
<body>
<h2>财报 Agent 查询（Laravel SSE 转发 → Python 大脑）</h2>
<div class="bar">
  <input id="code" value="600519" size="8" placeholder="公司代码">
  <input id="year" value="2025" size="6" placeholder="年份">
  <button onclick="run()">查询</button>
</div>
<div id="log">点击「查询」开始…</div>

<script>
function run() {
  const code = document.getElementById('code').value.trim();
  const year = document.getElementById('year').value.trim();
  const log  = document.getElementById('log');
  log.textContent = '';

  // EventSource 只支持 GET + text/event-stream，正好对接 Laravel 的 SSE 转发端点
  const es = new EventSource(`/fin-agent/query?company_code=${code}&year=${year}`);

  es.onmessage = (e) => {
    let d;
    try { d = JSON.parse(e.data); } catch (_) { return; }
    const line = document.createElement('div');
    line.className = 'row';
    const tag = document.createElement('span');
    tag.textContent = '[' + d.step + '] ';
    line.appendChild(tag);
    const txt = document.createElement('span');
    txt.textContent = JSON.stringify(d.data);
    // 简单着色：verify 帧的 zero_mismatch 决定绿/红
    if (d.step === 'verify') {
      const v = (d.data.verification && d.data.verification[0]) || {};
      line.classList.add(v.zero_mismatch ? 'ok' : (v.zero_mismatch === false ? 'bad' : 'warn'));
    }
    line.appendChild(txt);
    log.appendChild(line);
    log.scrollTop = log.scrollHeight;

    if (d.step === 'done' || d.step === 'need_approval') es.close();
  };
  es.onerror = () => es.close();
}
</script>
</body>
</html>
