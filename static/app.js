const $ = (selector) => document.querySelector(selector);
const uploadPanel = $("#uploadPanel");
const fileInput = $("#fileInput");
const progressPanel = $("#progressPanel");
const errorPanel = $("#errorPanel");
const results = $("#results");

const escapeHtml = (value) => String(value ?? "")
  .replaceAll("&", "&amp;").replaceAll("<", "&lt;")
  .replaceAll(">", "&gt;").replaceAll('"', "&quot;");

function showOnly(target) {
  [uploadPanel, progressPanel, errorPanel, results].forEach((element) => element.classList.add("hidden"));
  target.classList.remove("hidden");
}

function chooseFile() {
  fileInput.value = "";
  fileInput.click();
}

$("#pickButton").addEventListener("click", chooseFile);
$("#retryButton").addEventListener("click", chooseFile);
$("#newFileButton").addEventListener("click", chooseFile);
fileInput.addEventListener("change", () => fileInput.files[0] && analyze(fileInput.files[0]));

["dragenter", "dragover"].forEach((eventName) => uploadPanel.addEventListener(eventName, (event) => {
  event.preventDefault();
  uploadPanel.classList.add("dragging");
}));
["dragleave", "drop"].forEach((eventName) => uploadPanel.addEventListener(eventName, (event) => {
  event.preventDefault();
  uploadPanel.classList.remove("dragging");
}));
uploadPanel.addEventListener("drop", (event) => {
  const file = event.dataTransfer.files[0];
  if (file) analyze(file);
});

async function analyze(file) {
  if (!file.name.toLowerCase().endsWith(".ulg")) {
    showError("请选择扩展名为 .ulg 的 PX4 日志。");
    return;
  }
  showOnly(progressPanel);
  $("#progressTitle").textContent = `正在分析 ${file.name}`;
  $("#progressText").textContent = "正在识别飞行阶段、计算五项健康指标…";
  try {
    const response = await fetch("/api/analyze", {
      method: "POST",
      headers: {"Content-Type": "application/octet-stream", "X-Filename": encodeURIComponent(file.name)},
      body: file,
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "分析失败。");
    renderResults(payload);
  } catch (error) {
    showError(error.message || String(error));
  }
}

function showError(message) {
  $("#errorText").textContent = message;
  showOnly(errorPanel);
}

function renderResults(data) {
  $("#overallTitle").textContent = data.overall;
  $("#scopeText").textContent = data.meta.scope;
  $("#disclaimer").textContent = `安全提示：${data.disclaimer}`;
  const meta = [
    ["日志文件", data.meta.filename],
    ["机型", data.meta.vehicle_type],
    ["日志时长", `${data.meta.duration_s} 秒`],
    ["分析时段", `${data.meta.flight_duration_s} 秒`],
    ["规则版本", data.meta.rule_version],
  ];
  $("#metaGrid").innerHTML = meta.map(([label, value]) =>
    `<div class="meta-item"><span>${escapeHtml(label)}</span><strong title="${escapeHtml(value)}">${escapeHtml(value)}</strong></div>`
  ).join("");
  $("#metricGrid").innerHTML = data.metrics.map((metric, index) => metricCard(metric, index)).join("");
  document.querySelectorAll(".metric-summary").forEach((button) => button.addEventListener("click", () => {
    button.closest(".metric-card").classList.toggle("open");
  }));
  showOnly(results);
  results.scrollIntoView({behavior: "smooth", block: "start"});
}

const percentileHelp = {
  "P10": "第 10 百分位：约 10% 的样本低于它、90% 的样本不低于它，通常用来观察偏低的一侧。",
  "P90": "第 90 百分位：约 90% 的样本不高于它、10% 的样本高于它，通常用来观察偏高的一侧。",
  "P95": "第 95 百分位：约 95% 的样本不高于它，只忽略最高 5% 的短暂极端值。它不是最大值的 95%。",
  "P90-P10": "第 90 百分位减第 10 百分位，表示中间约 80% 样本的典型变化范围，可减少两端偶然尖峰的影响。",
};

function formatEvidenceLabel(label) {
  const pattern = /P90-P10|P10|P90|P95/g;
  let result = "", cursor = 0, match;
  while ((match = pattern.exec(label)) !== null) {
    result += escapeHtml(label.slice(cursor, match.index));
    const term = match[0];
    result += `<span class="stat-term" tabindex="0">${term}<sup>i</sup><span class="stat-tooltip" role="tooltip">${escapeHtml(percentileHelp[term])}</span></span>`;
    cursor = match.index + term.length;
  }
  return result + escapeHtml(label.slice(cursor));
}

function metricCard(metric, index) {
  const evidence = metric.evidence.length
    ? `<div class="evidence-grid">${metric.evidence.map((item) => `<div class="evidence ${escapeHtml(item.status || "")}"><span class="evidence-label">${formatEvidenceLabel(item.label)}</span><strong>${escapeHtml(item.value)}</strong>${item.result ? `<em>${escapeHtml(item.result)}</em>` : ""}</div>`).join("")}</div>`
    : "";
  const notes = metric.details.map((note) => `<p class="detail-note">${escapeHtml(note)}</p>`).join("");
  const sources = sourceSection(metric.data_sources || []);
  const charts = metric.series.length ? `<div class="chart-grid">${metric.series.map(chart).join("")}</div>` : "";
  const params = parameterSection(metric.parameters);
  return `<article class="metric-card ${escapeHtml(metric.status)}">
    <button class="metric-summary" type="button" aria-label="展开${escapeHtml(metric.name)}详情">
      <span class="metric-number">0${index + 1}</span>
      <span class="metric-name">${escapeHtml(metric.name)}</span>
      <span class="status-pill">${escapeHtml(metric.label)}</span>
      <span class="metric-brief">${escapeHtml(metric.summary)}</span>
      <span class="chevron">⌄</span>
    </button>
    <div class="metric-details">${evidence}${sources}${notes}${charts}${params}</div>
  </article>`;
}

function sourceSection(sources) {
  if (!sources.length) return "";
  const rows = sources.map((source) => `<div class="source-row">
    <span class="source-topic">${escapeHtml(source.topic)}</span>
    <span class="source-dot">.</span>
    <span class="source-field" tabindex="0">${escapeHtml(source.field)}
      <span class="field-tooltip" role="tooltip"><strong>${escapeHtml(source.zh)}</strong><span>单位：${escapeHtml(source.unit || "无")}</span><span>${escapeHtml(source.usage)}</span></span>
    </span>
  </div>`).join("");
  return `<section class="source-section"><h4>ULog 计算数据来源</h4><div class="source-list">${rows}</div></section>`;
}

function parameterSection(parameters) {
  if (!parameters.length) {
    return `<details class="parameter-section"><summary>相关 PX4 参数</summary><p class="empty-params">这份日志未记录词典中对应参数的值。</p></details>`;
  }
  const rows = parameters.map((item) => `<tr>
    <td><code>${escapeHtml(item.name)}</code></td><td>${escapeHtml(item.zh)}</td>
    <td>${escapeHtml(item.value)} ${escapeHtml(item.unit)}</td><td>${escapeHtml(item.note)}</td>
  </tr>`).join("");
  return `<details class="parameter-section"><summary>相关 PX4 参数（${parameters.length}）</summary>
    <table class="parameter-table"><thead><tr><th>参数</th><th>中文名</th><th>日志值</th><th>说明</th></tr></thead><tbody>${rows}</tbody></table>
  </details>`;
}

function chart(series) {
  const lines = series.lines || [{name: series.name, points: series.points || []}];
  const allPoints = lines.flatMap((line) => line.points);
  if (!allPoints.length) return "";
  const width = 540, height = 175, left = 43, right = 10, top = 12, bottom = 25;
  const xs = allPoints.map((point) => point[0]), ys = allPoints.map((point) => point[1]);
  let minX = Math.min(...xs), maxX = Math.max(...xs), minY = Math.min(...ys), maxY = Math.max(...ys);
  if (maxX === minX) maxX = minX + 1;
  if (maxY === minY) { maxY += 1; minY -= 1; }
  const padY = (maxY - minY) * .08; minY -= padY; maxY += padY;
  const x = (value) => left + (value - minX) / (maxX - minX) * (width - left - right);
  const y = (value) => top + (maxY - value) / (maxY - minY) * (height - top - bottom);
  const polylines = lines.map((line, index) => {
    const points = line.points.map((point) => `${x(point[0]).toFixed(1)},${y(point[1]).toFixed(1)}`).join(" ");
    return `<polyline class="plot-line line-${index}" points="${points}"/>`;
  }).join("");
  const grid = [0, .5, 1].map((fraction) => {
    const gy = top + fraction * (height - top - bottom);
    const value = maxY - fraction * (maxY - minY);
    return `<line class="grid-line" x1="${left}" x2="${width-right}" y1="${gy}" y2="${gy}"/><text x="2" y="${gy+3}">${formatNumber(value)}</text>`;
  }).join("");
  const legend = lines.length > 1 ? `<div class="chart-legend">${lines.map((line, index) => `<span><i class="legend-${index}"></i>${escapeHtml(line.name)}</span>`).join("")}</div>` : "";
  return `<div class="chart"><div class="chart-title"><h4>${escapeHtml(series.name)}${series.unit ? `（${escapeHtml(series.unit)}）` : ""}</h4>${legend}</div>
    <svg viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" role="img" aria-label="${escapeHtml(series.name)}曲线">
      ${grid}${polylines}
      <text x="${left}" y="${height-4}">${formatNumber(minX)}s</text><text x="${width-right-35}" y="${height-4}">${formatNumber(maxX)}s</text>
    </svg></div>`;
}

function formatNumber(value) {
  const abs = Math.abs(value);
  if (abs >= 1000 || (abs > 0 && abs < .01)) return value.toExponential(1);
  return Number(value.toFixed(abs >= 100 ? 0 : abs >= 10 ? 1 : 2));
}
