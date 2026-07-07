const $ = (id) => document.getElementById(id);

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

function getSourceId() {
  const p = new URLSearchParams(location.search);
  return p.get("id") || "";
}

function render(data) {
  $("source-id").textContent = `source_id=${data.source_id || ""}`;
  $("summary").textContent = `数量：${data.count || 0}，格式：${data.format || ""}，扫描页数：${data.pages_scanned || 0}`;
  const items = data.items || [];
  if (!items.length) {
    $("items").innerHTML = `<div class="muted">今日暂无更新或无法获取</div>`;
    return;
  }
  let html = `<table class="table">
    <thead>
      <tr>
        <th>时间</th><th>标题</th><th>分类</th><th>来源</th><th>缩略图</th><th>播放链接</th><th>vod_id</th>
      </tr>
    </thead><tbody>`;
  for (const it of items) {
    const thumb = it.thumb_url ? `<a href="${escapeHtml(it.thumb_url)}" target="_blank">查看</a>` : "";
    const play = it.play_url ? `<a href="${escapeHtml(it.play_url)}" target="_blank">播放</a>` : "";
    html += `<tr>
      <td>${escapeHtml(it.vod_time || "")}</td>
      <td>${escapeHtml(it.title || "")}</td>
      <td>${escapeHtml(it.type_name || "")}</td>
      <td>${escapeHtml(it.play_from || "")}</td>
      <td>${thumb}</td>
      <td>${play}</td>
      <td>${escapeHtml(it.vod_id || "")}</td>
    </tr>`;
  }
  html += `</tbody></table>`;
  $("items").innerHTML = html;
}

async function load() {
  const id = getSourceId();
  if (!id) {
    $("items").innerHTML = `<div class="muted">缺少参数：id</div>`;
    return;
  }
  const data = await api(`/api/sources/${encodeURIComponent(id)}/today`);
  render(data);
}

$("btn-refresh").addEventListener("click", async () => {
  try {
    await load();
  } catch (e) {
    alert(String(e));
  }
});

load();
