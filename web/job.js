const $ = (id) => document.getElementById(id);

const modeLabel = {
  daily: "每日更新",
  range: "时间段",
  full: "全量采集",
};

const statusLabel = {
  queued: "排队中",
  running: "进行中",
  success: "已完成",
  failed: "失败",
  stopped: "已停止",
};

async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (!res.ok) {
    const t = await res.text();
    throw new Error(t || `HTTP ${res.status}`);
  }
  const ct = res.headers.get("content-type") || "";
  if (ct.includes("application/json")) return res.json();
  const text = await res.text();
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

function escapeHtml(s) {
  return String(s)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function getJobId() {
  const p = new URLSearchParams(location.search);
  return p.get("id") || "";
}

function renderJob(job) {
  $("job-id").textContent = `job_id=${job.id || ""}`;
  const st = job.status || "";
  $("job-status").textContent = `状态：${statusLabel[st] || st}`;

  $("job-summary").innerHTML = `
    <div>模式：${escapeHtml(modeLabel[job.mode] || job.mode || "")}</div>
    <div>创建：${escapeHtml(job.created_at || "")}</div>
    <div>开始：${escapeHtml(job.started_at || "")}</div>
    <div>结束：${escapeHtml(job.finished_at || "")}</div>
    <div>时间段：${escapeHtml(job.start_time || "")} ~ ${escapeHtml(job.end_time || "")}</div>
    <div>并发：${escapeHtml(String(job.concurrency || ""))}</div>
    <div>错误：${escapeHtml(job.error || "")}</div>
  `;

  const sources = job.sources || [];
  if (!sources.length) {
    $("job-sources").innerHTML = `<div class="muted">暂无数据</div>`;
    return;
  }
  let html = `<table class="table">
    <thead>
      <tr>
        <th>Source ID</th><th>状态</th><th>开始</th><th>结束</th><th>已拉取</th><th>已入库</th><th>跳过</th><th>错误</th>
      </tr>
    </thead><tbody>`;
  for (const s of sources) {
    const sst = s.status || "";
    html += `<tr>
      <td>${escapeHtml(String(s.source_id || ""))}</td>
      <td>${escapeHtml(statusLabel[sst] || sst)}</td>
      <td>${escapeHtml(s.started_at || "")}</td>
      <td>${escapeHtml(s.finished_at || "")}</td>
      <td>${escapeHtml(String(s.fetched || 0))}</td>
      <td>${escapeHtml(String(s.inserted || 0))}</td>
      <td>${escapeHtml(String(s.skipped || 0))}</td>
      <td>${escapeHtml(s.error || "")}</td>
    </tr>`;
  }
  html += `</tbody></table>`;
  $("job-sources").innerHTML = html;

  $("btn-stop").disabled = !(st === "running" || st === "queued");
}

let timer = null;

async function load() {
  const id = getJobId();
  if (!id) {
    $("job-summary").innerHTML = `<div class="muted">缺少参数：id</div>`;
    $("btn-stop").disabled = true;
    return;
  }
  const job = await api(`/api/jobs/${encodeURIComponent(id)}`);
  renderJob(job);
  if (timer) clearTimeout(timer);
  if (job.status === "running" || job.status === "queued") {
    timer = setTimeout(load, 2000);
  }
}

function bind() {
  $("btn-refresh").addEventListener("click", async () => {
    try {
      await load();
    } catch (e) {
      alert(String(e));
    }
  });
  $("btn-stop").addEventListener("click", async () => {
    const id = getJobId();
    if (!id) return;
    if (!confirm(`确认停止任务 ${id}？`)) return;
    try {
      await api(`/api/jobs/${encodeURIComponent(id)}/stop`, { method: "POST" });
      await load();
    } catch (e) {
      alert(String(e));
    }
  });
}

bind();
load();

