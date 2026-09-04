const $ = (selector) => document.querySelector(selector);
const uploadPanel = $("#uploadPanel");
const fileInput = $("#fileInput");
const progressPanel = $("#progressPanel");
const errorPanel = $("#errorPanel");
const results = $("#results");
const serviceStopped = $("#serviceStopped");
const exitProgramButton = $("#exitProgramButton");
let explorerState = null;
let timelineState = null;

const browserClientId = globalThis.crypto?.randomUUID?.()
  || `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
const browserClientPayload = JSON.stringify({ client_id: browserClientId });
let programExitRequested = false;

async function registerBrowserClient() {
  try {
    const response = await fetch("/api/browser-open", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-PX4-Health-Client": "browser",
      },
      body: browserClientPayload,
      cache: "no-store",
      keepalive: true,
    });
    if (!response.ok) throw new Error("browser registration failed");
  } catch (_error) {
    // The regular health check will show the stopped-service message if needed.
  }
}

window.addEventListener("pageshow", registerBrowserClient);
window.addEventListener("pagehide", () => {
  if (programExitRequested) return;
  navigator.sendBeacon(
    "/api/browser-close",
    new Blob([browserClientPayload], { type: "application/json" }),
  );
});

exitProgramButton?.addEventListener("click", async () => {
  exitProgramButton.disabled = true;
  try {
    const response = await fetch("/api/shutdown", {
      method: "POST",
      headers: { "X-PX4-Health-Client": "browser" },
    });
    if (!response.ok) throw new Error("shutdown failed");
    programExitRequested = true;
    window.clearInterval(backendHealthTimer);
    serviceStopped?.classList.remove("hidden");
  } catch (_error) {
    exitProgramButton.disabled = false;
  }
});

let backendHealthFailures = 0;
const backendHealthTimer = window.setInterval(async () => {
  try {
    const response = await fetch("/api/health", { cache: "no-store" });
    if (!response.ok) throw new Error("health check failed");
    backendHealthFailures = 0;
  } catch (_error) {
    backendHealthFailures += 1;
    if (backendHealthFailures >= 2) {
      window.clearInterval(backendHealthTimer);
      serviceStopped?.classList.remove("hidden");
    }
  }
}, 1000);

const escapeHtml = (value) => String(value ?? "")
  .replaceAll("&", "&amp;").replaceAll("<", "&lt;")
  .replaceAll(">", "&gt;").replaceAll('"', "&quot;");

let evidenceTooltipOwner = null;

function evidenceFloatingTooltip() {
  let tooltip = document.querySelector("#evidenceFloatingTooltip");
  if (!tooltip) {
    tooltip = document.createElement("div");
    tooltip.id = "evidenceFloatingTooltip";
    tooltip.className = "evidence-floating-tooltip";
    tooltip.setAttribute("role", "tooltip");
    document.body.appendChild(tooltip);
  }
  return tooltip;
}

function positionEvidenceTooltip(owner, tooltip) {
  const ownerRect = owner.getBoundingClientRect();
  const tooltipRect = tooltip.getBoundingClientRect();
  const gap = 9;
  const edge = 10;
  const left = Math.min(
    Math.max(ownerRect.left, edge),
    Math.max(edge, window.innerWidth - tooltipRect.width - edge),
  );
  const above = ownerRect.top - tooltipRect.height - gap;
  const top = above >= edge ? above : ownerRect.bottom + gap;
  tooltip.style.left = `${Math.round(left)}px`;
  tooltip.style.top = `${Math.round(top)}px`;
}

function showEvidenceTooltip(owner) {
  const fullValue = owner.dataset.fullValue;
  if (!fullValue) return;
  const tooltip = evidenceFloatingTooltip();
  evidenceTooltipOwner = owner;
  tooltip.textContent = fullValue;
  tooltip.classList.add("visible");
  positionEvidenceTooltip(owner, tooltip);
}

function hideEvidenceTooltip(owner) {
  if (owner && evidenceTooltipOwner !== owner) return;
  evidenceTooltipOwner = null;
  document.querySelector("#evidenceFloatingTooltip")?.classList.remove("visible");
}

document.addEventListener("mouseover", (event) => {
  const owner = event.target.closest?.(".evidence-value-wrap");
  if (!owner || owner.contains(event.relatedTarget)) return;
  showEvidenceTooltip(owner);
});

document.addEventListener("mouseout", (event) => {
  const owner = event.target.closest?.(".evidence-value-wrap");
  if (!owner || owner.contains(event.relatedTarget)) return;
  hideEvidenceTooltip(owner);
});

document.addEventListener("focusin", (event) => {
  const owner = event.target.closest?.(".evidence-value-wrap");
  if (owner) showEvidenceTooltip(owner);
});

document.addEventListener("focusout", (event) => {
  const owner = event.target.closest?.(".evidence-value-wrap");
  if (owner) hideEvidenceTooltip(owner);
});

window.addEventListener("scroll", () => hideEvidenceTooltip(), true);

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
  $("#progressText").textContent = "正在识别飞行阶段、计算六项健康指标";
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
  setTimelineData(data.timeline);
  $("#overallTitle").textContent = data.overall;
  $("#scopeText").textContent = data.meta.scope;
  $("#disclaimer").textContent = `安全提示：${data.disclaimer}`;
  const vehicleWarning = $("#vehicleWarning");
  const compatibilityWarning = data.meta.vehicle_compatibility_warning;
  vehicleWarning.textContent = compatibilityWarning || "";
  vehicleWarning.classList.toggle("hidden", !compatibilityWarning);
  const meta = [
    ["日志文件", data.meta.filename],
    ["机型", data.meta.vehicle_type],
    ["日志时长", `${data.meta.duration_s} 秒`],
    ["分析时段", `${data.meta.flight_duration_s} 秒`],
    ["规则 / 算法", `${data.meta.rule_version} / ${data.meta.algorithm_version || "v1"}`],
  ];
  if (data.meta.experimental_rule_versions?.magnetometer) {
    meta.push(["磁力计实验规则", data.meta.experimental_rule_versions.magnetometer]);
  }
  $("#metaGrid").innerHTML = meta.map(([label, value]) =>
    `<div class="meta-item"><span>${escapeHtml(label)}</span><div class="meta-value"><strong>${escapeHtml(value)}</strong></div></div>`
  ).join("");
  $("#metricGrid").innerHTML = data.metrics.map((metric, index) => metricCard(metric, index)).join("");
  $("#metricGrid").onclick = handleMetricChartAction;
  document.querySelectorAll(".metric-summary").forEach((button) => button.addEventListener("click", () => {
    const card = button.closest(".metric-card");
    card.classList.toggle("open");
    if (card.classList.contains("open")) requestAnimationFrame(() => updateAnomalyWindowControls(card));
  }));
  initExplorer(data.explorer);
  renderTimeline(data.timeline);
  document.querySelectorAll("[data-anomaly-start]").forEach((button) => button.addEventListener("click", jumpToAnomaly));
  document.querySelectorAll("[data-anomaly-more]").forEach((button) => button.addEventListener("click", toggleAnomalyWindows));
  showOnly(results);
  results.scrollIntoView({behavior: "smooth", block: "start"});
}

const timelineCategories = {
  flight: "飞行状态", failsafe: "失效保护", gps: "GPS / 定位", battery: "电池",
  estimator: "估计器", motor: "电机 / 电调", control: "控制", sensor: "传感器", system: "系统消息",
};

const timelineSeverities = {severe: "严重", warning: "警告", info: "信息"};
const TIMELINE_COLORS = {severe: "#b33c32", warning: "#b46b08", info: "#6a7472"};

function setTimelineData(timeline) {
  timelineState = timeline ? {data: timeline, scope: "important", category: "all"} : null;
}

function importantTimelineItems(start = -Infinity, end = Infinity) {
  if (!timelineState) return [];
  return (timelineState.data.items || []).filter((item) => {
    const time = Number(item.time_s);
    return item.important && Number.isFinite(time) && time >= start && time <= end;
  });
}

function timelineGroupSeverity(items) {
  if (items.some((item) => item.severity === "severe")) return "severe";
  if (items.some((item) => item.severity === "warning")) return "warning";
  return "info";
}

function groupTimelineItems(items, position, threshold = 4) {
  const groups = [];
  items.slice().sort((left, right) => Number(left.time_s) - Number(right.time_s)).forEach((item) => {
    const itemPosition = position(Number(item.time_s));
    const previous = groups.at(-1);
    if (previous && Math.abs(itemPosition - previous.position) <= threshold) {
      previous.items.push(item);
      previous.position = previous.items.reduce((sum, current) => sum + position(Number(current.time_s)), 0) / previous.items.length;
    } else {
      groups.push({position: itemPosition, items: [item]});
    }
  });
  return groups;
}

function timelineGroupDescription(items) {
  const first = Number(items[0].time_s);
  const last = Number(items.at(-1).time_s);
  const time = first === last
    ? formatTimelineTime(first)
    : `${formatTimelineTime(first)}–${formatTimelineTime(last)}`;
  const details = items.map((item) =>
    `[${timelineSeverities[item.severity] || item.severity} / ${timelineCategories[item.category] || item.category}] ${item.title}`
  );
  return `${time}\n${details.join("\n")}`;
}

function renderTimeline(timeline) {
  const panel = $("#flightTimeline");
  if (!timeline) {
    setTimelineData(null);
    panel.classList.add("hidden");
    return;
  }
  if (!timelineState || timelineState.data !== timeline) setTimelineData(timeline);
  panel.classList.remove("hidden");
  const summary = timeline.summary || {};
  $("#timelineSummaryText").textContent = summary.severe_count || summary.warning_count
    ? `记录到 ${summary.severe_count || 0} 条严重事件、${summary.warning_count || 0} 条警告。时间线不会改变六项健康总评。`
    : "没有记录到重要告警；可切换到“全部事件”查看模式和起降过程。";
  $("#timelineSummaryBadges").innerHTML = `
    <span class="severe">严重 ${escapeHtml(summary.severe_count || 0)}</span>
    <span class="warning">警告 ${escapeHtml(summary.warning_count || 0)}</span>
    <span>失效保护 ${escapeHtml(summary.failsafe_count || 0)}</span>
    <span>全部 ${escapeHtml(summary.total_count || 0)}</span>`;
  const categories = [...new Set((timeline.items || []).map((item) => item.category))];
  $("#timelineCategory").innerHTML = `<option value="all">全部分类</option>${categories.map((category) => `<option value="${escapeHtml(category)}">${escapeHtml(timelineCategories[category] || category)}</option>`).join("")}`;
  $("#timelineCategory").value = "all";
  $("#timelineCategory").onchange = (event) => {
    timelineState.category = event.target.value;
    renderTimelineItems();
  };
  panel.querySelectorAll("[data-timeline-scope]").forEach((button) => {
    button.classList.toggle("active", button.dataset.timelineScope === "important");
    button.onclick = () => {
      timelineState.scope = button.dataset.timelineScope;
      panel.querySelectorAll("[data-timeline-scope]").forEach((item) => item.classList.toggle("active", item === button));
      renderTimelineItems();
    };
  });
  const notices = [];
  if (timeline.truncated) notices.push(`事件超过显示上限，目前优先显示 ${summary.displayed_count} 条重要记录。`);
  if ((timeline.missing_sources || []).length) notices.push(`日志未包含部分事件源：${timeline.missing_sources.join("、")}。`);
  const notice = $("#timelineNotice");
  notice.textContent = notices.join(" ");
  notice.classList.toggle("hidden", !notices.length);
  $("#timelineItems").onclick = handleTimelineClick;
  renderTimelineItems();
}

function renderTimelineItems() {
  if (!timelineState) return;
  const items = (timelineState.data.items || []).filter((item) =>
    (timelineState.scope === "all" || item.important) &&
    (timelineState.category === "all" || item.category === timelineState.category));
  $("#timelineItems").innerHTML = items.length ? items.map((item, index) => `<details class="timeline-item ${escapeHtml(item.severity)}" data-timeline-index="${index}">
    <summary data-timeline-time="${escapeHtml(item.time_s)}">
      <time>${escapeHtml(formatTimelineTime(item.time_s))}</time>
      <span class="timeline-marker" aria-hidden="true"></span>
      <span class="timeline-title"><strong>${escapeHtml(item.title)}</strong><small>${escapeHtml(timelineCategories[item.category] || item.category)} · ${escapeHtml(item.source)}${item.count > 1 ? ` · 重复 ${escapeHtml(item.count)} 次` : ""}</small></span>
      <em>${escapeHtml(timelineSeverities[item.severity] || item.severity)}</em>
    </summary>
    <div class="timeline-detail">
      <div><small>PX4 原文</small><code>${escapeHtml(item.original || "无原文")}</code></div>
      <button type="button" data-timeline-fields="${escapeHtml((item.related_fields || []).join("|"))}" data-timeline-time="${escapeHtml(item.time_s)}">查看相关曲线</button>
    </div>
  </details>`).join("") : `<p class="timeline-empty">当前筛选条件下没有事件。</p>`;
}

function formatTimelineTime(seconds) {
  const value = Math.max(0, Number(seconds) || 0);
  const minutes = Math.floor(value / 60);
  const remainder = value - minutes * 60;
  return `${minutes}:${remainder.toFixed(1).padStart(4, "0")}`;
}

function handleTimelineClick(event) {
  const fieldsButton = event.target.closest("[data-timeline-fields]");
  if (fieldsButton) {
    event.preventDefault();
    event.stopPropagation();
    jumpToTimelineTime(Number(fieldsButton.dataset.timelineTime), true);
    addTimelineFields(fieldsButton.dataset.timelineFields.split("|").filter(Boolean));
    return;
  }
  const summary = event.target.closest("summary[data-timeline-time]");
  if (summary) jumpToTimelineTime(Number(summary.dataset.timelineTime));
}

function jumpToTimelineTime(time, scroll = false) {
  if (!explorerState || !Number.isFinite(time)) return;
  setExplorerRange(time - 5, time + 10);
  if (scroll) $("#logExplorer").scrollIntoView({behavior: "smooth", block: "start"});
  if (explorerState.selected.size) queueSeriesLoad(0);
  else showExplorerMessage(`已定位到事件附近 ${formatNumber(explorerState.viewStart)}–${formatNumber(explorerState.viewEnd)} s，可选择曲线或点击“查看相关曲线”。`);
}

function resolveTimelineField(key) {
  if (explorerState.fields.has(key)) return key;
  const match = key.match(/^(.+)\[\d+\]\.(.+)$/);
  if (!match) return null;
  const candidate = [...explorerState.fields.entries()].find(([, field]) => field.topic === match[1] && field.name === match[2]);
  return candidate ? candidate[0] : null;
}

function addTimelineFields(requested) {
  if (!explorerState) return;
  const resolved = [...new Set(requested.map(resolveTimelineField).filter(Boolean))];
  const added = [];
  for (const key of resolved) {
    if (explorerState.selected.has(key)) continue;
    if (explorerState.selected.size >= 12) break;
    if (addExplorerField(key, "auto")) added.push(key);
  }
  if (!resolved.length) showExplorerMessage("这份日志没有记录该事件对应的推荐曲线字段。", true);
  else if (!added.length) showExplorerMessage("相关曲线已经选中，或当前已达到 12 条曲线限制。", explorerState.selected.size >= 12);
  else {
    showExplorerMessage(`已添加 ${added.length} 条相关曲线。`);
    queueSeriesLoad(0);
  }
}

const percentileHelp = {
  "P10": "第 10 百分位：约 10% 的样本低于它、90% 的样本不低于它，通常用来观察偏低的一侧。",
  "P90": "第 90 百分位：约 90% 的样本不高于它、10% 的样本高于它，通常用来观察偏高的一侧。",
  "P95": "第 95 百分位：约 95% 的样本不高于它，只忽略最高 5% 的短暂极端值。它不是最大值的 95%。",
  "P90-P10": "第 90 百分位减第 10 百分位，表示中间约 80% 样本的典型变化范围，可减少两端偶然尖峰的影响。",
};

const evidenceLabelHelp = {
  "磁场模长中位数": "仅统计有效飞行阶段内三轴数值均有效的磁力计样本。每个采样点先按 B = √(X² + Y² + Z²) 计算磁场矢量模长，再对全部模长取中位数（P50）。优先使用校准后的 vehicle_magnetometer.magnetometer_ga[0..2]，缺失时回退到选中的 sensor_mag.x/y/z，单位为 Gauss（G）。例如 0.536 G 表示约一半有效样本的模长不高于它、另一半不低于它；模长可减少机体姿态旋转造成的单轴变化，但不能单独判定磁场是否受扰。",
  "磁力计创新检验比 P95": "读取当前主 EKF 的 estimator_status.mag_test_ratio。它是三轴中最大的磁力计观测偏差相对于 EKF 检验门限的比值，不是磁场强度。P95 表示约 95% 的样本不高于该值；达到或超过 1，说明飞行中至少出现过达到融合检验门限的时段。",
  "高低负载磁场模长差": "先将动力负载数据按时间插值到磁力计样本，再分别取负载最低 20% 与最高 20% 样本的磁场模长中位数；本值为高负载中位数减低负载中位数。正值表示高负载时磁场模长更大，负值则相反。",
  "磁场-负载秩相关系数 ρ": "对按时间对齐后的磁场模长和动力负载分别排序，再计算相关系数（Spearman 秩相关）。范围为 -1 到 1：接近 1 表示负载增大时磁场通常也增大，接近 -1 表示通常减小，接近 0 表示未见稳定的单调关系；相关性不能单独证明因果。",
};

const metricLevels = {
  "vibration": ["正常", "偏大", "严重", "数据不足"],
  "gps": ["良好", "较差", "异常", "数据不足"],
  "battery": ["正常", "明显", "严重", "数据不足"],
  "attitude": ["良好", "偏差较大", "严重偏差", "数据不足"],
  "motors": ["正常", "接近饱和", "饱和风险高", "数据不足"],
  "magnetometer": ["未见明显异常", "存在磁场异常", "严重磁场异常", "数据不足"],
};

function formatEvidenceLabel(label) {
  if (evidenceLabelHelp[label]) {
    return `<span class="stat-term" tabindex="0">${escapeHtml(label)}<sup>i</sup><span class="stat-tooltip" role="tooltip">${escapeHtml(evidenceLabelHelp[label])}</span></span>`;
  }
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
    ? `<div class="evidence-grid">${metric.evidence.map((item) => { const fullValue = item.full_value || item.value; return `<div class="evidence ${escapeHtml(item.status || "")}"><span class="evidence-label">${formatEvidenceLabel(item.label)}</span><span class="evidence-value-wrap" tabindex="0" data-full-value="${escapeHtml(fullValue)}" aria-label="${escapeHtml(fullValue)}"><strong class="evidence-value">${escapeHtml(item.value)}</strong></span>${item.result ? `<em>${escapeHtml(item.result)}</em>` : ""}</div>`; }).join("")}</div>`
    : "";
  const notes = detailHelp(metric.details || []);
  const sources = sourceSection(metric.data_sources || []);
  const explainability = explainabilitySection(metric);
  const charts = metric.series.length ? `<div class="chart-grid">${metric.series.map(chart).join("")}</div>` : "";
  const params = parameterSection(metric.parameters);
  return `<article class="metric-card ${escapeHtml(metric.status)}">
    <button class="metric-summary" type="button" aria-label="展开${escapeHtml(metric.name)}详情">
      <span class="metric-number">0${index + 1}</span>
      <span class="metric-name">${escapeHtml(metric.name)}</span>
      <span class="status-pill">${escapeHtml(metric.label)}<span class="status-tooltip" role="tooltip"><strong>全部判断等级</strong><span>${(metricLevels[metric.id] || ["正常", "提醒", "严重", "数据不足"]).map(escapeHtml).join("　/　")}</span></span></span>
      <span class="metric-brief">${escapeHtml(metric.summary)}</span>
      <span class="chevron">⌄</span>
    </button>
    <div class="metric-details">${evidence}${explainability}${sources}${notes}${charts}${params}</div>
  </article>`;
}

function explainabilitySection(metric) {
  const quality = metric.data_quality || {};
  const qualityItems = [];
  if (quality.coverage_percent !== undefined) qualityItems.push(["有效覆盖率", `${quality.coverage_percent}%`]);
  if (quality.sample_rate_hz !== undefined && quality.sample_rate_hz !== null) qualityItems.push(["采样率", `${quality.sample_rate_hz} Hz`]);
  if (quality.source) qualityItems.push([metric.experimental ? "磁场数据源" : "候选算法数据源", quality.source]);
  if (quality.confidence) qualityItems.push(["数据可信度", quality.confidence]);
  if (quality.load_source) qualityItems.push(["动力负载来源", quality.load_source]);
  if (quality.load_confidence) qualityItems.push(["动力关联可信度", quality.load_confidence]);
  const qualityHtml = qualityItems.map(([label, value]) => `<span><small>${escapeHtml(label)}</small><strong>${escapeHtml(value)}</strong></span>`).join("");
  const notes = (quality.notes || []).map((note) => `<li>${escapeHtml(note)}</li>`).join("");
  const hits = (metric.rule_hits || []).map((hit) => `<li>${escapeHtml(hit)}</li>`).join("");
  const windows = (metric.anomaly_windows || []).map((window) => `<button class="anomaly-jump ${escapeHtml(window.severity || "warning")}" type="button" data-anomaly-start="${escapeHtml(window.start_s)}" data-anomaly-end="${escapeHtml(window.end_s)}">${escapeHtml(window.label)} · ${escapeHtml(window.start_s)}–${escapeHtml(window.end_s)} s</button>`).join("");
  const candidate = candidateSection(metric.candidate_v2);
  return `<section class="explainability-section">
    <h4>结论可追溯信息</h4>
    ${qualityHtml ? `<div class="quality-grid">${qualityHtml}</div>` : ""}
    ${hits ? `<div class="rule-hit-list"><strong>${metric.experimental ? "实验规则（计入总评）" : "当前 v1 规则"}</strong><ul>${hits}</ul></div>` : ""}
    ${notes ? `<div class="quality-notes"><strong>数据限制</strong><ul>${notes}</ul></div>` : ""}
    ${windows ? `<div class="anomaly-windows"><strong>${metric.experimental ? "磁场异常时间段" : "候选算法发现的异常时间段"}</strong><div class="anomaly-window-list" data-expanded="false">${windows}</div><button class="anomaly-more" type="button" data-anomaly-more>更多</button></div>` : ""}
    ${candidate}
  </section>`;
}

function updateAnomalyWindowControls(scope = document) {
  scope.querySelectorAll(".anomaly-window-list").forEach((list) => {
    if (!list.offsetWidth) return;
    const items = [...list.querySelectorAll(".anomaly-jump")];
    const columns = Math.max(1, getComputedStyle(list).gridTemplateColumns.split(" ").filter(Boolean).length);
    const visibleLimit = columns * 3;
    const expanded = list.dataset.expanded === "true";
    items.forEach((item, index) => item.classList.toggle("anomaly-window-hidden", !expanded && index >= visibleLimit));
    const toggle = list.parentElement.querySelector("[data-anomaly-more]");
    const remaining = Math.max(0, items.length - visibleLimit);
    toggle.classList.toggle("hidden", remaining === 0);
    toggle.textContent = expanded ? "收起" : `更多（${remaining}）`;
    toggle.setAttribute("aria-expanded", String(expanded));
  });
}

function toggleAnomalyWindows(event) {
  const list = event.currentTarget.parentElement.querySelector(".anomaly-window-list");
  list.dataset.expanded = String(list.dataset.expanded !== "true");
  updateAnomalyWindowControls(event.currentTarget.parentElement);
}

function candidateSection(candidate) {
  if (!candidate) return "";
  const evidence = (candidate.evidence || []).map((item) => `<span><small>${escapeHtml(item.label)}</small><strong>${item.value === null || item.value === undefined ? "不可用" : `${escapeHtml(item.value)} ${escapeHtml(item.unit || "")}`}</strong></span>`).join("");
  const hits = (candidate.rule_hits || []).map((hit) => `<li>${escapeHtml(hit)}</li>`).join("");
  return `<details class="candidate-section">
    <summary><span>候选 v2 影子结果</span><em class="candidate-status ${escapeHtml(candidate.status)}">${escapeHtml(candidate.label)}</em><small>${escapeHtml(candidate.algorithm_version)} · 实验性，不影响总评</small></summary>
    ${hits ? `<ul class="candidate-hits">${hits}</ul>` : `<p>未触发候选 v2 的提醒或严重条件。</p>`}
    ${evidence ? `<div class="candidate-evidence">${evidence}</div>` : ""}
  </details>`;
}

function jumpToAnomaly(event) {
  if (!explorerState) return;
  const start = Number(event.currentTarget.dataset.anomalyStart);
  const end = Number(event.currentTarget.dataset.anomalyEnd);
  if (!Number.isFinite(start) || !Number.isFinite(end)) return;
  const margin = Math.max(.5, (end - start) * .2);
  setExplorerRange(start - margin, end + margin);
  $("#logExplorer").scrollIntoView({behavior: "smooth", block: "start"});
  if (explorerState.selected.size) queueSeriesLoad(0);
  else showExplorerMessage(`已定位到 ${formatNumber(explorerState.viewStart)}–${formatNumber(explorerState.viewEnd)} s，请从左侧选择要查看的字段。`);
}

function detailHelp(details) {
  if (!details.length) return "";
  return `<div class="detail-help" tabindex="0"><span class="detail-help-label">判断说明 <sup>i</sup></span><span class="detail-tooltip" role="tooltip">${details.map((note) => `<span>${escapeHtml(note)}</span>`).join("")}</span></div>`;
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
  const timelineItems = importantTimelineItems(minX, maxX);
  const timelineGroups = groupTimelineItems(timelineItems, x);
  const timelineMarkers = timelineGroups.map((group) => {
    const markerX = group.position.toFixed(1);
    const severity = timelineGroupSeverity(group.items);
    const description = timelineGroupDescription(group.items);
    return `<g class="chart-timeline-marker ${severity}" tabindex="0" role="img" aria-label="${escapeHtml(description)}">
      <line x1="${markerX}" x2="${markerX}" y1="${top}" y2="${height-bottom}"/>
      <path d="M ${markerX} ${height-bottom} l -4 7 h 8 z"/>
      <title>${escapeHtml(description)}</title>
    </g>`;
  }).join("");
  const legend = lines.length > 1 ? `<div class="chart-legend">${lines.map((line, index) => `<span><i class="legend-${index}"></i>${escapeHtml(line.name)}</span>`).join("")}</div>` : "";
  const timelineHint = timelineItems.length ? "显示事件与告警时间线" : "此图时间范围内没有重要事件";
  return `<div class="chart"><div class="chart-title"><h4>${escapeHtml(series.name)}${series.unit ? `（${escapeHtml(series.unit)}）` : ""}</h4><div class="chart-controls">${legend}
      <button class="timeline-toggle" type="button" data-toggle-chart-timeline aria-pressed="false" aria-label="${timelineHint}" title="${timelineHint}" ${timelineItems.length ? "" : "disabled"}>事件与告警</button>
    </div></div>
    <svg viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" role="img" aria-label="${escapeHtml(series.name)}曲线">
      ${grid}${polylines}<g class="chart-timeline-layer hidden" aria-hidden="true">${timelineMarkers}</g>
      <text x="${left}" y="${height-4}">${formatNumber(minX)}s</text><text x="${width-right-35}" y="${height-4}">${formatNumber(maxX)}s</text>
    </svg></div>`;
}

function handleMetricChartAction(event) {
  const button = event.target.closest("[data-toggle-chart-timeline]");
  if (!button || button.disabled) return;
  const layer = button.closest(".chart")?.querySelector(".chart-timeline-layer");
  if (!layer) return;
  const visible = button.getAttribute("aria-pressed") !== "true";
  button.setAttribute("aria-pressed", String(visible));
  button.setAttribute("aria-label", visible ? "隐藏事件与告警时间线" : "显示事件与告警时间线");
  button.title = visible ? "隐藏事件与告警时间线" : "显示事件与告警时间线";
  button.classList.toggle("active", visible);
  layer.classList.toggle("hidden", !visible);
  layer.setAttribute("aria-hidden", String(!visible));
}

function formatNumber(value) {
  const abs = Math.abs(value);
  if (abs >= 1000 || (abs > 0 && abs < .01)) return value.toExponential(1);
  return Number(value.toFixed(abs >= 100 ? 0 : abs >= 10 ? 1 : 2));
}

const EXPLORER_COLORS = ["#087b62", "#e08b25", "#3478c5", "#d1495b", "#7457b2", "#2196a6", "#7a8b28", "#a75d35", "#44546a", "#c05aa0", "#2d9b48", "#8b6c3e"];

function initExplorer(catalog) {
  const panel = $("#logExplorer");
  if (explorerState?.controller) explorerState.controller.abort();
  explorerState = null;
  if (!catalog) {
    panel.classList.add("hidden");
    return;
  }
  const fields = new Map();
  catalog.topics.forEach((topic) => topic.fields.forEach((field) => fields.set(field.key, {
    ...field, topic: topic.name, multiId: topic.multi_id,
  })));
  explorerState = {
    sessionId: catalog.session_id,
    catalog,
    fields,
    selected: new Map(),
    plots: new Map(),
    data: new Map(),
    hidden: new Set(),
    canvases: new Map(),
    topicOpen: new Map(),
    fullStart: Number(catalog.start_s) || 0,
    fullEnd: Number(catalog.end_s) || 1,
    viewStart: Number(catalog.start_s) || 0,
    viewEnd: Number(catalog.end_s) || 1,
    plotCounter: 1,
    requestCounter: 0,
    requestTimer: null,
    controller: null,
    hoverTime: null,
  };
  panel.classList.remove("hidden");
  $("#fieldCount").textContent = `${catalog.topics.length} 个 topic · ${catalog.field_count} 个字段`;
  $("#fieldSearch").value = "";
  $("#fieldSearch").oninput = () => {
    explorerState.topicOpen.clear();
    renderFieldTree();
  };
  $("#topicTree").onclick = handleFieldClick;
  $("#selectedSeries").onchange = handleSeriesMove;
  $("#selectedSeries").onclick = handleSeriesRemove;
  $("#explorerPlots").onclick = handlePlotAction;
  $("#resetViewButton").onclick = resetExplorerView;
  renderFieldTree();
  renderExplorerSelection();
}

function renderFieldTree() {
  if (!explorerState) return;
  const tree = $("#topicTree");
  const scrollTop = tree.scrollTop;
  const query = $("#fieldSearch").value.trim().toLowerCase();
  const groups = explorerState.catalog.topics.map((topic) => {
    const topicLabel = `${topic.name}[${topic.multi_id}]`;
    const topicMatch = topicLabel.toLowerCase().includes(query);
    const fields = topic.fields.filter((field) => !query || topicMatch || field.name.toLowerCase().includes(query));
    if (!fields.length) return "";
    const rows = fields.map((field) => {
      const selected = explorerState.selected.has(field.key);
      return `<button class="field-option${selected ? " selected" : ""}" type="button" data-field-key="${escapeHtml(field.key)}">
        <span class="field-toggle">${selected ? "✓" : "+"}</span>${curveFieldHelp(field.name, field)}
        <small>${escapeHtml(field.type)} · ${escapeHtml(field.unit || "单位未知")}</small>
      </button>`;
    }).join("");
    const open = explorerState.topicOpen.has(topicLabel)
      ? explorerState.topicOpen.get(topicLabel)
      : Boolean(query);
    return `<details class="topic-group" data-topic-key="${escapeHtml(topicLabel)}" ${open ? "open" : ""}><summary><span>${escapeHtml(topicLabel)}</span><em>${fields.length}</em></summary>${rows}</details>`;
  }).join("");
  tree.innerHTML = groups || `<p class="no-fields">没有匹配的字段。</p>`;
  tree.querySelectorAll(".topic-group").forEach((details) => {
    details.ontoggle = () => explorerState.topicOpen.set(details.dataset.topicKey, details.open);
  });
  tree.scrollTop = scrollTop;
}

function handleFieldClick(event) {
  const button = event.target.closest("[data-field-key]");
  if (!button || !explorerState) return;
  const key = button.dataset.fieldKey;
  if (explorerState.selected.has(key)) {
    removeExplorerField(key);
    return;
  }
  if (explorerState.selected.size >= 12) {
    showExplorerMessage("一次最多显示 12 条曲线，请先移除不需要的字段。", true);
    return;
  }
  addExplorerField(key, $("#plotTarget").value);
  queueSeriesLoad(0);
}

function addExplorerField(key, target = "auto") {
  const field = explorerState && explorerState.fields.get(key);
  if (!field || explorerState.selected.has(key) || explorerState.selected.size >= 12) return false;
  let plotId;
  if (target !== "auto" && target !== "new" && explorerState.plots.has(target)) {
    plotId = target;
  } else if (target === "auto" && field.unit) {
    plotId = `unit:${field.unit}`;
    ensurePlot(plotId, `${field.unit} 数据`, field.unit);
  } else if (target === "auto" && /\[\d+\]$/.test(field.name)) {
    const family = field.name.replace(/\[\d+\]$/, "[*]");
    plotId = `family:${field.topic}[${field.multiId}].${family}`;
    ensurePlot(plotId, `${field.topic}.${family}`, "");
  } else {
    plotId = createCustomPlot(field.unit, target === "new" ? "自定义图表" : `${field.topic}.${field.name}`);
  }
  explorerState.selected.set(key, {...field, plotId});
  renderFieldTree();
  renderExplorerSelection();
  return true;
}

function ensurePlot(id, title, unit = "") {
  if (!explorerState.plots.has(id)) explorerState.plots.set(id, {
    id, title, unit, legendVisible: true, timelineVisible: false, pinnedTimelineItems: null,
    number: explorerState.plotCounter++,
  });
  return id;
}

function createCustomPlot(unit = "", preferredTitle = "自定义图表") {
  const id = `custom:${explorerState.plotCounter}`;
  ensurePlot(id, preferredTitle, unit);
  return id;
}

function plotDisplayName(plot) {
  return `图表 ${plot.number} · ${plot.title}`;
}

function removeExplorerField(key) {
  explorerState.selected.delete(key);
  explorerState.data.delete(key);
  explorerState.hidden.delete(key);
  removeEmptyPlots();
  renderFieldTree();
  renderExplorerSelection();
  if (explorerState.selected.size) queueSeriesLoad(0);
  else renderExplorerPlots();
}

function removeEmptyPlots() {
  const used = new Set([...explorerState.selected.values()].map((field) => field.plotId));
  [...explorerState.plots.keys()].forEach((id) => { if (!used.has(id)) explorerState.plots.delete(id); });
}

function renderExplorerSelection() {
  if (!explorerState) return;
  const currentTarget = $("#plotTarget").value;
  const plotOptions = [...explorerState.plots.values()].map((plot) => `<option value="${escapeHtml(plot.id)}">${escapeHtml(plotDisplayName(plot))}</option>`).join("");
  $("#plotTarget").innerHTML = `<option value="auto">自动分组（推荐）</option><option value="new">单独新建图表</option>${plotOptions}`;
  if ([...$("#plotTarget").options].some((option) => option.value === currentTarget)) $("#plotTarget").value = currentTarget;
  const chips = [...explorerState.selected.values()].map((field) => `<div class="series-chip">
    <span><i style="background:${seriesColor(field.key)}"></i>${curveFieldHelp(field.key, field)}</span>
    <label class="series-plot-choice"><span>所在图表</span><select data-move-field="${escapeHtml(field.key)}" aria-label="移动曲线到其他图表">
        ${[...explorerState.plots.values()].map((plot) => `<option value="${escapeHtml(plot.id)}" ${plot.id === field.plotId ? "selected" : ""}>${escapeHtml(plotDisplayName(plot))}</option>`).join("")}
        <option value="__new">＋ 新建图表</option>
      </select></label>
    <button type="button" data-remove-field="${escapeHtml(field.key)}" aria-label="移除曲线">×</button>
  </div>`).join("");
  $("#selectedSeries").innerHTML = chips;
  renderExplorerPlots();
}

function handleSeriesMove(event) {
  const select = event.target.closest("[data-move-field]");
  if (!select) return;
  const field = explorerState.selected.get(select.dataset.moveField);
  if (!field) return;
  field.plotId = select.value === "__new" ? createCustomPlot(field.unit) : select.value;
  removeEmptyPlots();
  renderExplorerSelection();
}

function handleSeriesRemove(event) {
  const button = event.target.closest("[data-remove-field]");
  if (button) removeExplorerField(button.dataset.removeField);
}

function queueSeriesLoad(delay = 150) {
  clearTimeout(explorerState.requestTimer);
  explorerState.requestTimer = setTimeout(loadExplorerSeries, delay);
}

async function loadExplorerSeries() {
  if (!explorerState || !explorerState.selected.size) return;
  if (explorerState.controller) explorerState.controller.abort();
  explorerState.controller = new AbortController();
  const requestId = ++explorerState.requestCounter;
  showExplorerMessage("正在读取当前时间范围…");
  try {
    const response = await fetch("/api/explorer-series", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      signal: explorerState.controller.signal,
      body: JSON.stringify({
        session_id: explorerState.sessionId,
        fields: [...explorerState.selected.keys()],
        start_s: explorerState.viewStart,
        end_s: explorerState.viewEnd,
        max_points: 4000,
      }),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "曲线读取失败。");
    if (requestId !== explorerState.requestCounter) return;
    explorerState.data = new Map(payload.series.map((series) => [series.key, series]));
    showExplorerMessage("");
    renderExplorerPlots();
  } catch (error) {
    if (error.name !== "AbortError") showExplorerMessage(error.message || String(error), true);
  }
}

function showExplorerMessage(message, error = false) {
  const element = $("#explorerMessage");
  element.textContent = message;
  element.classList.toggle("error", error);
  element.classList.toggle("hidden", !message);
}

function renderExplorerPlots() {
  if (!explorerState) return;
  updateViewRangeLabel();
  const groups = new Map();
  explorerState.selected.forEach((field) => {
    if (!groups.has(field.plotId)) groups.set(field.plotId, []);
    groups.get(field.plotId).push(field);
  });
  if (!groups.size) {
    $("#explorerPlots").innerHTML = "";
    showExplorerMessage("从左侧选择字段开始绘图，最多同时显示 12 条。");
    return;
  }
  $("#explorerPlots").innerHTML = [...groups].map(([plotId, fields]) => {
    const plot = explorerState.plots.get(plotId);
    const legend = fields.map((field) => {
      const hidden = explorerState.hidden.has(field.key);
      return `<span class="${hidden ? "curve-hidden" : ""}" data-toggle-series="${escapeHtml(field.key)}" aria-label="点击${hidden ? "显示" : "隐藏"}这条曲线"><i style="background:${seriesColor(field.key)}"></i>${curveFieldHelp(field.key, field)}<button type="button" data-remove-field="${escapeHtml(field.key)}" title="移除曲线">×</button></span>`;
    }).join("");
    const enumFields = fields.filter((field) => field.enum_values && field.enum_values.length);
    const plotEnum = enumFields.length === 1 ? enumFields[0] : null;
    const hasTimeline = importantTimelineItems().length > 0;
    return `<article class="explorer-plot" data-plot-id="${escapeHtml(plotId)}">
      <header><div><h4>${curveFieldHelp(plotDisplayName(plot), plotEnum || (fields.length === 1 ? fields[0] : null), true)}</h4><small>${escapeHtml(plot.unit || "单位未知 / 自定义组合")}</small></div>
        <div class="explorer-plot-actions">
          <button class="timeline-toggle${plot.timelineVisible ? " active" : ""}" type="button" data-toggle-plot-timeline="${escapeHtml(plotId)}" aria-pressed="${plot.timelineVisible}" aria-label="${plot.timelineVisible ? "隐藏" : "显示"}事件与告警时间线" title="${hasTimeline ? `${plot.timelineVisible ? "隐藏" : "显示"}事件与告警时间线` : "这份日志没有重要事件"}" ${hasTimeline ? "" : "disabled"}>事件与告警</button>
          <button type="button" data-toggle-legend="${escapeHtml(plotId)}">${plot.legendVisible ? "隐藏图例" : "显示图例"}</button>
        </div></header>
      <div class="explorer-legend${plot.legendVisible ? "" : " hidden"}">${legend}</div>
      <div class="canvas-wrap"><canvas aria-label="${escapeHtml(plot.title)}曲线"></canvas></div>
      <div class="plot-readout">移动鼠标查看采样值</div>
    </article>`;
  }).join("");
  explorerState.canvases.clear();
  document.querySelectorAll(".explorer-plot").forEach((card) => {
    const plotId = card.dataset.plotId;
    const fields = groups.get(plotId);
    const canvas = card.querySelector("canvas");
    explorerState.canvases.set(plotId, {canvas, card, fields, plot: explorerState.plots.get(plotId)});
    bindCanvasInteractions(canvas);
  });
  drawAllExplorerPlots();
}

function enumFieldHelp(label, values, title = "各数字对应的状态", plain = false, note = "") {
  const hasValues = Boolean(values && values.length);
  if (!hasValues && !title && !note) return plain ? `<span>${escapeHtml(label)}</span>` : `<code>${escapeHtml(label)}</code>`;
  const unique = new Map((values || []).map((item) => [item.value, item]));
  const rows = [...unique.values()].sort((left, right) => Number(left.value) - Number(right.value)).map((item) =>
    `<span><b>${escapeHtml(item.value)}</b><i>${escapeHtml(item.label)}</i><small>${escapeHtml(item.code)}</small></span>`).join("");
  const helpTitle = title || "字段说明";
  const helpNote = note || (hasValues ? "未列出的数字按未知状态处理。" : "");
  const nativeHint = [helpTitle, helpNote].filter(Boolean).join("：");
  return `<span class="enum-field-help" tabindex="0" title="${escapeHtml(nativeHint)}"><code>${escapeHtml(label)}</code><b class="field-help-badge" aria-hidden="true">?</b><span class="enum-tooltip" role="tooltip"><strong>${escapeHtml(helpTitle)}</strong>${hasValues ? `<span class="enum-grid">${rows}</span>` : ""}${helpNote ? `<em>${escapeHtml(helpNote)}</em>` : ""}</span></span>`;
}

function curveFieldHelp(label, field, plain = false) {
  if (!field) return plain ? `<span>${escapeHtml(label)}</span>` : `<code>${escapeHtml(label)}</code>`;
  return enumFieldHelp(
    label,
    field.enum_values,
    field.enum_title || "",
    plain,
    field.enum_note || "",
  );
}

function handlePlotAction(event) {
  const clearPinnedEvent = event.target.closest("[data-clear-pinned-event]");
  if (clearPinnedEvent) {
    const plot = explorerState.plots.get(clearPinnedEvent.dataset.clearPinnedEvent);
    if (!plot) return;
    plot.pinnedTimelineItems = null;
    drawAllExplorerPlots();
    return;
  }
  const remove = event.target.closest("[data-remove-field]");
  if (remove) {
    removeExplorerField(remove.dataset.removeField);
    return;
  }
  const series = event.target.closest("[data-toggle-series]");
  if (series) {
    const key = series.dataset.toggleSeries;
    if (explorerState.hidden.has(key)) explorerState.hidden.delete(key);
    else explorerState.hidden.add(key);
    renderExplorerPlots();
    return;
  }
  const toggle = event.target.closest("[data-toggle-legend]");
  if (toggle) {
    const plot = explorerState.plots.get(toggle.dataset.toggleLegend);
    plot.legendVisible = !plot.legendVisible;
    renderExplorerPlots();
    return;
  }
  const timelineToggle = event.target.closest("[data-toggle-plot-timeline]");
  if (timelineToggle && !timelineToggle.disabled) {
    const plot = explorerState.plots.get(timelineToggle.dataset.togglePlotTimeline);
    if (!plot) return;
    plot.timelineVisible = !plot.timelineVisible;
    if (!plot.timelineVisible) plot.pinnedTimelineItems = null;
    renderExplorerPlots();
  }
}

function seriesColor(key) {
  let hash = 0;
  for (let i = 0; i < key.length; i++) hash = ((hash << 5) - hash + key.charCodeAt(i)) | 0;
  return EXPLORER_COLORS[Math.abs(hash) % EXPLORER_COLORS.length];
}

function bindCanvasInteractions(canvas) {
  canvas.onwheel = (event) => {
    event.preventDefault();
    const bounds = canvas.getBoundingClientRect();
    const fraction = Math.max(0, Math.min(1, (event.clientX - bounds.left - 54) / Math.max(1, bounds.width - 72)));
    const span = explorerState.viewEnd - explorerState.viewStart;
    const nextSpan = span * (event.deltaY > 0 ? 1.25 : .8);
    const focus = explorerState.viewStart + span * fraction;
    setExplorerRange(focus - nextSpan * fraction, focus + nextSpan * (1 - fraction));
    drawAllExplorerPlots();
    queueSeriesLoad();
  };
  canvas.onpointerdown = (event) => {
    canvas.setPointerCapture(event.pointerId);
    canvas._drag = {x: event.clientX, y: event.clientY, start: explorerState.viewStart, end: explorerState.viewEnd, moved: false};
  };
  canvas.onpointermove = (event) => {
    const bounds = canvas.getBoundingClientRect();
    if (canvas._drag) {
      canvas._drag.moved = canvas._drag.moved || Math.hypot(event.clientX - canvas._drag.x, event.clientY - canvas._drag.y) > 3;
      if (!canvas._drag.moved) return;
      const secondsPerPixel = (canvas._drag.end - canvas._drag.start) / Math.max(1, bounds.width - 72);
      const shift = (canvas._drag.x - event.clientX) * secondsPerPixel;
      setExplorerRange(canvas._drag.start + shift, canvas._drag.end + shift);
    } else {
      const fraction = Math.max(0, Math.min(1, (event.clientX - bounds.left - 54) / Math.max(1, bounds.width - 72)));
      explorerState.hoverTime = explorerState.viewStart + fraction * (explorerState.viewEnd - explorerState.viewStart);
      canvas.style.cursor = canvasTimelineGroupAt(canvas, event.clientX) ? "pointer" : "crosshair";
    }
    drawAllExplorerPlots();
  };
  canvas.onpointerup = (event) => {
    if (canvas._drag) {
      const moved = canvas._drag.moved;
      canvas.releasePointerCapture(event.pointerId);
      canvas._drag = null;
      canvas._suppressTimelineClick = moved;
      if (moved) {
        setTimeout(() => { canvas._suppressTimelineClick = false; }, 0);
        queueSeriesLoad(0);
      }
    }
  };
  canvas.onpointerleave = () => {
    if (!canvas._drag) {
      canvas.style.cursor = "crosshair";
      explorerState.hoverTime = null;
      drawAllExplorerPlots();
    }
  };
  canvas.onclick = (event) => {
    if (canvas._suppressTimelineClick) {
      canvas._suppressTimelineClick = false;
      return;
    }
    pinCanvasTimelineGroup(canvas, event.clientX);
  };
  canvas.ondblclick = resetExplorerView;
}

function canvasTimelineGroupAt(canvas, clientX) {
  const plotId = canvas.closest("[data-plot-id]")?.dataset.plotId;
  const plot = plotId ? explorerState.plots.get(plotId) : null;
  if (!plot?.timelineVisible) return null;
  const bounds = canvas.getBoundingClientRect();
  const markerX = clientX - bounds.left;
  const left = 54, right = 18;
  if (markerX < left - 7 || markerX > bounds.width - right + 7) return null;
  const plotWidth = Math.max(1, bounds.width - left - right);
  const x = (value) => left + (value - explorerState.viewStart) / (explorerState.viewEnd - explorerState.viewStart) * plotWidth;
  const groups = groupTimelineItems(importantTimelineItems(explorerState.viewStart, explorerState.viewEnd), x);
  return nearestTimelineGroup(groups, markerX);
}

function pinCanvasTimelineGroup(canvas, clientX) {
  const group = canvasTimelineGroupAt(canvas, clientX);
  if (!group) return;
  const plotId = canvas.closest("[data-plot-id]")?.dataset.plotId;
  const plot = plotId ? explorerState.plots.get(plotId) : null;
  if (!plot) return;
  plot.pinnedTimelineItems = group.items.slice();
  drawAllExplorerPlots();
}

function setExplorerRange(start, end) {
  const fullSpan = explorerState.fullEnd - explorerState.fullStart;
  let span = Math.max(Math.min(fullSpan, end - start), Math.min(.05, fullSpan));
  if (start < explorerState.fullStart) start = explorerState.fullStart;
  if (start + span > explorerState.fullEnd) start = explorerState.fullEnd - span;
  explorerState.viewStart = start;
  explorerState.viewEnd = start + span;
  updateViewRangeLabel();
}

function resetExplorerView() {
  if (!explorerState) return;
  explorerState.viewStart = explorerState.fullStart;
  explorerState.viewEnd = explorerState.fullEnd;
  explorerState.hoverTime = null;
  drawAllExplorerPlots();
  if (explorerState.selected.size) queueSeriesLoad(0);
}

function updateViewRangeLabel() {
  if (!explorerState) return;
  $("#viewRange").textContent = explorerState.selected.size
    ? `当前时间：${formatNumber(explorerState.viewStart)}–${formatNumber(explorerState.viewEnd)} s · ${explorerState.selected.size}/12 条曲线`
    : "请选择要显示的字段";
}

function drawAllExplorerPlots() {
  if (!explorerState) return;
  explorerState.canvases.forEach((entry) => drawExplorerPlot(entry));
}

function drawExplorerPlot({canvas, card, fields, plot}) {
  const bounds = canvas.getBoundingClientRect();
  const width = Math.max(320, Math.round(bounds.width || 700));
  const height = Math.max(260, Math.round(bounds.height || 320));
  const ratio = window.devicePixelRatio || 1;
  if (canvas.width !== Math.round(width * ratio) || canvas.height !== Math.round(height * ratio)) {
    canvas.width = Math.round(width * ratio);
    canvas.height = Math.round(height * ratio);
  }
  const context = canvas.getContext("2d");
  context.setTransform(ratio, 0, 0, ratio, 0, 0);
  context.clearRect(0, 0, width, height);
  const margin = {left: 54, right: 18, top: 16, bottom: 30};
  const plotWidth = width - margin.left - margin.right;
  const plotHeight = height - margin.top - margin.bottom;
  const visibleLines = fields
    .filter((field) => !explorerState.hidden.has(field.key))
    .map((field) => {
      const line = explorerState.data.get(field.key);
      return line ? {...line, enumKind: field.enum_kind, enumValues: field.enum_values} : null;
    }).filter(Boolean);
  const points = visibleLines.flatMap((line) => line.points.filter((point) => point[0] >= explorerState.viewStart && point[0] <= explorerState.viewEnd));
  let minY = points.length ? Math.min(...points.map((point) => point[1])) : -1;
  let maxY = points.length ? Math.max(...points.map((point) => point[1])) : 1;
  if (minY === maxY) { minY -= 1; maxY += 1; }
  const pad = (maxY - minY) * .08;
  minY -= pad; maxY += pad;
  const x = (value) => margin.left + (value - explorerState.viewStart) / (explorerState.viewEnd - explorerState.viewStart) * plotWidth;
  const y = (value) => margin.top + (maxY - value) / (maxY - minY) * plotHeight;
  const timelineGroups = plot.timelineVisible
    ? groupTimelineItems(importantTimelineItems(explorerState.viewStart, explorerState.viewEnd), x)
    : [];

  context.font = '11px Inter, "Microsoft YaHei UI", sans-serif';
  context.lineWidth = 1;
  for (let index = 0; index <= 4; index++) {
    const fraction = index / 4;
    const gy = margin.top + plotHeight * fraction;
    context.strokeStyle = "#e3e9e6";
    context.beginPath(); context.moveTo(margin.left, gy); context.lineTo(width - margin.right, gy); context.stroke();
    context.fillStyle = "#788581";
    context.fillText(String(formatNumber(maxY - fraction * (maxY - minY))), 4, gy + 4);
  }
  visibleLines.forEach((line) => {
    const linePoints = line.points.filter((point) => point[0] >= explorerState.viewStart && point[0] <= explorerState.viewEnd);
    if (!linePoints.length) return;
    context.strokeStyle = seriesColor(line.key);
    context.lineWidth = 1.6;
    context.beginPath();
    linePoints.forEach((point, index) => {
      if (index) context.lineTo(x(point[0]), y(point[1]));
      else context.moveTo(x(point[0]), y(point[1]));
    });
    context.stroke();
  });
  drawCanvasTimeline(context, timelineGroups, margin.top, height - margin.bottom);
  context.fillStyle = "#788581";
  context.fillText(`${formatNumber(explorerState.viewStart)} s`, margin.left, height - 7);
  const endText = `${formatNumber(explorerState.viewEnd)} s`;
  context.fillText(endText, width - margin.right - context.measureText(endText).width, height - 7);

  const readout = card.querySelector(".plot-readout");
  readout.classList.toggle("timeline-active", plot.timelineVisible);
  const pinnedEventGroup = plot.pinnedTimelineItems?.length ? {items: plot.pinnedTimelineItems} : null;
  if (explorerState.hoverTime !== null) {
    const cursorX = x(explorerState.hoverTime);
    context.strokeStyle = "#526761";
    context.setLineDash([4, 3]);
    context.beginPath(); context.moveTo(cursorX, margin.top); context.lineTo(cursorX, height - margin.bottom); context.stroke();
    context.setLineDash([]);
    const values = visibleLines.map((line) => {
      const point = nearestPoint(line.points, explorerState.hoverTime);
      if (!point) return "";
      const decoded = decodeCurveValue(line, point[1]);
      return `<span><i style="background:${seriesColor(line.key)}"></i>${escapeHtml(line.name)}: <strong>${escapeHtml(formatNumber(point[1]))}</strong>${decoded ? `<em>${escapeHtml(decoded)}</em>` : ""}</span>`;
    }).join("");
    const eventGroup = pinnedEventGroup || nearestTimelineGroup(timelineGroups, cursorX);
    const eventReadout = plot.timelineVisible
      ? timelineReadout(eventGroup, timelineGroups.length ? "将鼠标移到事件标记附近查看详情，点击可固定" : "当前时间范围没有重要事件", Boolean(pinnedEventGroup), plot.id)
      : "";
    readout.innerHTML = `<b>${formatNumber(explorerState.hoverTime)} s</b>${values}${eventReadout}`;
  } else {
    const hint = visibleLines.length
      ? `移动鼠标查看采样值${plot.timelineVisible ? "和事件" : ""}`
      : plot.timelineVisible && timelineGroups.length ? "移动鼠标查看事件" : "当前时间范围没有可显示的数据";
    const eventReadout = plot.timelineVisible
      ? timelineReadout(pinnedEventGroup, timelineGroups.length ? "将鼠标移到事件标记附近查看详情，点击可固定" : "当前时间范围没有重要事件", Boolean(pinnedEventGroup), plot.id)
      : "";
    readout.innerHTML = `<span>${escapeHtml(hint)}</span>${eventReadout}`;
  }
}

function drawCanvasTimeline(context, groups, top, bottom) {
  if (!groups.length) return;
  context.save();
  groups.forEach((group) => {
    const severity = timelineGroupSeverity(group.items);
    context.strokeStyle = TIMELINE_COLORS[severity];
    context.fillStyle = TIMELINE_COLORS[severity];
    context.globalAlpha = .78;
    context.lineWidth = 1;
    context.setLineDash([4, 3]);
    context.beginPath();
    context.moveTo(group.position, top);
    context.lineTo(group.position, bottom);
    context.stroke();
    context.setLineDash([]);
    context.beginPath();
    context.moveTo(group.position, bottom);
    context.lineTo(group.position - 5, bottom + 8);
    context.lineTo(group.position + 5, bottom + 8);
    context.closePath();
    context.fill();
  });
  context.restore();
}

function nearestTimelineGroup(groups, cursorX, tolerance = 7) {
  let nearest = null;
  let distance = tolerance + 1;
  groups.forEach((group) => {
    const current = Math.abs(group.position - cursorX);
    if (current <= tolerance && current < distance) {
      nearest = group;
      distance = current;
    }
  });
  return nearest;
}

function timelineReadout(group, emptyText = "将鼠标移到事件标记附近查看详情，点击可固定", pinned = false, plotId = "") {
  if (!group) {
    return `<section class="plot-event-readout empty">
      <header class="plot-event-header"><strong>事件与告警</strong></header>
      <div class="plot-event-empty">${escapeHtml(emptyText)}</div>
    </section>`;
  }
  const severity = timelineGroupSeverity(group.items);
  const rows = group.items.map((item) => {
    const itemSeverity = item.severity || "info";
    const repeated = Number(item.count) > 1 ? ` ×${Number(item.count)}` : "";
    return `<div class="plot-event-row" role="listitem">
      <span class="plot-event-severity ${escapeHtml(itemSeverity)}">${escapeHtml(timelineSeverities[itemSeverity] || itemSeverity)}</span>
      <span class="plot-event-category">${escapeHtml(timelineCategories[item.category] || item.category)}</span>
      <span class="plot-event-title">${escapeHtml(item.title)}${escapeHtml(repeated)}</span>
    </div>`;
  }).join("");
  const first = Number(group.items[0].time_s);
  const last = Number(group.items.at(-1).time_s);
  const time = first === last ? formatTimelineTime(first) : `${formatTimelineTime(first)}–${formatTimelineTime(last)}`;
  const pinnedControls = pinned
    ? `<span class="plot-event-pinned">已固定</span><button type="button" data-clear-pinned-event="${escapeHtml(plotId)}" aria-label="取消固定事件详情">取消固定</button>`
    : "";
  return `<section class="plot-event-readout ${severity}">
    <header class="plot-event-header"><strong>事件 ${escapeHtml(time)} · ${group.items.length} 条</strong><div class="plot-event-controls">${pinnedControls}</div></header>
    <div class="plot-event-list" role="list">${rows}</div>
  </section>`;
}

function decodeCurveValue(line, value) {
  if (!line.enumValues || !line.enumValues.length || !Number.isFinite(Number(value))) return "";
  if (line.enumKind === "annotation") return "";
  const numeric = Math.trunc(Number(value));
  if (line.enumKind === "bitmask") {
    if (numeric === 0) return (line.enumValues.find((item) => Number(item.value) === 0) || {}).label || "无故障";
    const active = line.enumValues.filter((item) => Number(item.value) > 0 && (numeric & Number(item.value)) === Number(item.value));
    const knownMask = active.reduce((mask, item) => mask | Number(item.value), 0);
    const labels = active.map((item) => item.label);
    if ((numeric & ~knownMask) !== 0) labels.push(`包含未知故障位 ${numeric & ~knownMask}`);
    return labels.join("；") || `未知组合值 ${numeric}`;
  }
  const item = line.enumValues.find((entry) => Number(entry.value) === numeric);
  return item ? item.label : "";
}

function nearestPoint(points, target) {
  if (!points.length) return null;
  let low = 0, high = points.length - 1;
  while (low < high) {
    const middle = Math.floor((low + high) / 2);
    if (points[middle][0] < target) low = middle + 1;
    else high = middle;
  }
  if (low > 0 && Math.abs(points[low - 1][0] - target) < Math.abs(points[low][0] - target)) return points[low - 1];
  return points[low];
}

window.addEventListener("resize", () => {
  drawAllExplorerPlots();
  document.querySelectorAll(".metric-card.open").forEach((card) => updateAnomalyWindowControls(card));
});
