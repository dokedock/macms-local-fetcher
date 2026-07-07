const $ = (id) => document.getElementById(id);

let editingSourceId = null;
let sourcesCache = [];

const modeLabel = {
  daily: "每日更新",
  range: "时间段采集",
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

function sourcePayloadFromForm() {
  const name = $("src-name").value.trim();
  const base_url = $("src-base-url").value.trim();
  const format = $("src-format").value;
  const enabled = $("src-enabled").value === "1";
  const proxy = $("src-proxy").value.trim();
  const headersText = $("src-headers").value.trim();
  let headers = {};
  if (headersText) {
    headers = JSON.parse(headersText);
  }
  return { name, base_url, format, enabled, proxy: proxy || null, headers };
}

function fillSourceForm(s) {
  $("src-name").value = s.name || "";
  $("src-base-url").value = s.base_url || "";
  $("src-format").value = s.format || "auto";
  $("src-enabled").value = s.enabled ? "1" : "0";
  $("src-proxy").value = s.proxy || "";
  $("src-headers").value = s.headers ? JSON.stringify(s.headers) : "";
}

function resetSourceForm() {
  editingSourceId = null;
  fillSourceForm({ format: "auto", enabled: true, headers: {} });
  $("src-editing").textContent = "";
}

async function loadSources() {
  const sources = await api("/api/sources");
  sourcesCache = sources;
  const el = $("sources");
  if (!sources.length) {
    el.innerHTML = `<div class="muted">暂无采集源</div>`;
    $("job-sources-select").innerHTML = `<div class="muted">暂无采集源</div>`;
    return;
  }
  let html = `<table class="table">
    <thead>
      <tr>
        <th>ID</th><th>名称</th><th>Base URL</th><th>格式</th><th>启用</th><th>Cursor</th><th>操作</th>
      </tr>
    </thead><tbody>`;
  for (const s of sources) {
    html += `<tr>
      <td>${s.id}</td>
      <td>${escapeHtml(s.name)}</td>
      <td>${escapeHtml(s.base_url)}</td>
      <td>${escapeHtml(s.format)}</td>
      <td>${s.enabled ? "是" : "否"}</td>
      <td>${escapeHtml(s.last_cursor_time || "")}</td>
      <td class="actions">
        <a href="/source?id=${encodeURIComponent(s.id)}" target="_blank">今日更新</a>
        <button class="secondary" data-act="edit" data-id="${s.id}">编辑</button>
        <button class="danger" data-act="del" data-id="${s.id}">删除</button>
      </td>
    </tr>`;
  }
  html += `</tbody></table>`;
  el.innerHTML = html;

  el.querySelectorAll("button").forEach((b) => {
    b.addEventListener("click", async () => {
      const act = b.dataset.act;
      const id = Number(b.dataset.id);
      const src = sources.find((x) => x.id === id);
      if (act === "edit") {
        editingSourceId = id;
        fillSourceForm(src);
        $("src-editing").textContent = `正在编辑：${id}`;
      } else if (act === "del") {
        if (!confirm(`确认删除源 ${id}？`)) return;
        await api(`/api/sources/${id}`, { method: "DELETE" });
        if (editingSourceId === id) resetSourceForm();
        await loadSources();
      }
    });
  });

  renderJobSourceSelector(sources);
}

function renderJobSourceSelector(sources) {
  const el = $("job-sources-select");
  let html = `<div class="checkbox-list">`;
  for (const s of sources) {
    const disabled = !s.enabled;
    html += `<label class="checkbox">
      <input type="checkbox" data-source-id="${s.id}" ${disabled ? "disabled" : ""} />
      <span>${escapeHtml(s.name)} (#${s.id})</span>
    </label>`;
  }
  html += `</div>`;
  el.innerHTML = html;
}

function selectedSourceIds() {
  const el = $("job-sources-select");
  const inputs = Array.from(el.querySelectorAll("input[type='checkbox'][data-source-id]"));
  return inputs.filter((x) => x.checked && !x.disabled).map((x) => Number(x.dataset.sourceId));
}

function selectAllSources(flag) {
  const el = $("job-sources-select");
  const inputs = Array.from(el.querySelectorAll("input[type='checkbox'][data-source-id]"));
  inputs.forEach((x) => {
    if (!x.disabled) x.checked = flag;
  });
}

async function saveSource() {
  const payload = sourcePayloadFromForm();
  if (editingSourceId) {
    await api(`/api/sources/${editingSourceId}`, { method: "PUT", body: JSON.stringify(payload) });
  } else {
    await api("/api/sources", { method: "POST", body: JSON.stringify(payload) });
  }
  resetSourceForm();
  await loadSources();
}

async function runJob() {
  const source_ids = selectedSourceIds();
  if (!source_ids.length) {
    alert("请先选择要采集的源");
    return;
  }
  const payload = {
    mode: $("job-mode").value,
    concurrency: Number($("job-concurrency").value || 5),
    start_time: $("job-start").value.trim() || null,
    end_time: $("job-end").value.trim() || null,
    source_ids,
  };
  const r = await api("/api/collect", { method: "POST", body: JSON.stringify(payload) });
  $("job-current").textContent = `job_id=${r.job_id}`;
  await loadJobs();
}

async function loadJobs() {
  const jobs = await api("/api/jobs");
  const el = $("jobs");
  if (!jobs.length) {
    el.innerHTML = `<div class="muted">暂无任务</div>`;
    return;
  }
  let html = `<table class="table">
    <thead>
      <tr>
        <th>时间</th><th>job_id</th><th>状态</th><th>模式</th><th>开始</th><th>结束</th><th>并发</th><th>操作</th>
      </tr>
    </thead><tbody>`;
  for (const j of jobs) {
    const st = j.status || "";
    html += `<tr>
      <td>${escapeHtml(j.created_at || "")}</td>
      <td>${escapeHtml(j.id || "")}</td>
      <td>${escapeHtml(statusLabel[st] || st)}</td>
      <td>${escapeHtml(modeLabel[j.mode] || j.mode || "")}</td>
      <td>${escapeHtml(j.start_time || "")}</td>
      <td>${escapeHtml(j.end_time || "")}</td>
      <td>${escapeHtml(String(j.concurrency || ""))}</td>
      <td class="actions">
        <a href="/job?id=${encodeURIComponent(j.id || "")}" target="_blank">查看</a>
        ${(st === "running" || st === "queued") ? `<button class="danger" data-act="stop" data-id="${escapeHtml(j.id || "")}">停止</button>` : ""}
        <button class="secondary" data-act="delete" data-id="${escapeHtml(j.id || "")}">删除</button>
      </td>
    </tr>`;
  }
  html += `</tbody></table>`;
  el.innerHTML = html;

  el.querySelectorAll("button[data-act='stop']").forEach((b) => {
    b.addEventListener("click", async () => {
      const id = b.dataset.id;
      if (!id) return;
      if (!confirm(`确认停止任务 ${id}？`)) return;
      await api(`/api/jobs/${encodeURIComponent(id)}/stop`, { method: "POST" });
      await loadJobs();
    });
  });

  el.querySelectorAll("button[data-act='delete']").forEach((b) => {
    b.addEventListener("click", async () => {
      const id = b.dataset.id;
      if (!id) return;
      if (!confirm(`确认删除任务 ${id}？（不会删除采集数据）`)) return;
      await api(`/api/jobs/${encodeURIComponent(id)}`, { method: "DELETE" });
      await loadJobs();
    });
  });
}

async function dedup() {
  const r = await api("/api/dedup", { method: "POST", body: JSON.stringify({ mode: "title" }) });
  alert(`已删除重复：${r.deleted}`);
}

async function clearAll() {
  if (!confirm("确认清空所有采集数据？（会清空 items 和任务记录，并重置游标）")) return;
  await api("/api/clear", { method: "POST" });
  alert("已清空");
  await loadSources();
  await loadJobs();
}

async function exportCsv() {
  const payload = {
    keyword: $("export-keyword").value.trim() || null,
    source_id: $("export-source-id").value.trim() || null,
    start_time: $("export-start").value.trim() || null,
    end_time: $("export-end").value.trim() || null,
  };
  const r = await api("/api/export", { method: "POST", body: JSON.stringify(payload) });
  const link = $("export-link");
  link.href = r.file;
  link.textContent = `${r.file} (${r.count})`;
}

function escapeHtml(s) {
  return String(s)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function bind() {
  $("btn-save-source").addEventListener("click", async () => {
    try {
      await saveSource();
    } catch (e) {
      alert(String(e));
    }
  });
  $("btn-reset-source").addEventListener("click", resetSourceForm);
  $("btn-run-job").addEventListener("click", async () => {
    try {
      await runJob();
    } catch (e) {
      alert(String(e));
    }
  });
  $("btn-refresh-jobs").addEventListener("click", async () => {
    try {
      await loadJobs();
    } catch (e) {
      alert(String(e));
    }
  });
  $("btn-dedup").addEventListener("click", async () => {
    try {
      await dedup();
    } catch (e) {
      alert(String(e));
    }
  });
  $("btn-clear").addEventListener("click", async () => {
    try {
      await clearAll();
    } catch (e) {
      alert(String(e));
    }
  });
  $("btn-export").addEventListener("click", async () => {
    try {
      await exportCsv();
    } catch (e) {
      alert(String(e));
    }
  });
  $("btn-job-select-all").addEventListener("click", () => selectAllSources(true));
  $("btn-job-select-none").addEventListener("click", () => selectAllSources(false));
}

async function init() {
  resetSourceForm();
  bind();
  await loadSources();
  await loadJobs();
}

init();
