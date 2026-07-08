const config = window.dashboardConfig || {};
const pollState = {
  captureVersion: "",
  pollTimer: null,
  busy: false,
  orderRequirementDirty: false,
};

function byId(id) {
  return document.getElementById(id);
}

function safeText(value, fallback = "--") {
  if (value === null || value === undefined || value === "") {
    return fallback;
  }
  return String(value);
}

function escapeHtml(value) {
  return safeText(value, "").replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function formatTime(value) {
  if (!value) {
    return "--";
  }
  const normalizedValue = typeof value === "number" && value < 1e12
    ? value * 1000
    : value;
  const date = new Date(normalizedValue);
  if (Number.isNaN(date.getTime())) {
    return safeText(value);
  }
  return date.toLocaleString("zh-CN", { hour12: false });
}

function formatPercent(value) {
  return typeof value === "number" ? `${(value * 100).toFixed(1)}%` : "--";
}

function formatNumber(value, digits = 2) {
  return typeof value === "number" ? value.toFixed(digits) : "--";
}

function prettyJson(value, fallback = "暂无数据") {
  if (value === null || value === undefined) {
    return fallback;
  }
  return JSON.stringify(value, null, 2);
}

function healthTone(value) {
  if (value === "green") {
    return "green";
  }
  if (value === "yellow") {
    return "yellow";
  }
  if (value === "red") {
    return "red";
  }
  return "neutral";
}

function comparisonTone(status) {
  if (status === "通过" || status === "已检测通过") {
    return "green";
  }
  if (status === "异常" || status === "NFC异常" || status === "异常分拣") {
    return "red";
  }
  if (status === "低置信度" || status === "无识别结果" || status === "待人工处理") {
    return "yellow";
  }
  return "neutral";
}

function boolTone(value) {
  return value ? "green" : "yellow";
}

function setText(id, value, fallback = "--") {
  const node = byId(id);
  if (node) {
    node.textContent = safeText(value, fallback);
  }
}

function setChip(id, text, tone) {
  const node = byId(id);
  if (!node) {
    return;
  }
  node.className = `status-chip ${tone || "neutral"}`;
  node.textContent = safeText(text, "暂无数据");
}

function setFeedback(message, tone = "neutral") {
  const node = byId("actionFeedback");
  if (!node) {
    return;
  }
  node.className = `feedback-box ${tone}`;
  node.textContent = safeText(message, "等待联调操作");
}

function hasMeaningfulObject(value) {
  return Boolean(value) && typeof value === "object" && Object.keys(value).length > 0;
}

function isUidFallbackSample(nfc) {
  return nfc?.raw?.material_id_source === "uid";
}

function hasReadableNfcText(nfc) {
  return Boolean(nfc?.text) && !isUidFallbackSample(nfc);
}

function isHistoricalNfcSource(source) {
  return source === "latest_history" || source === "buffered_reader";
}

function renderTagRow(id, items, emptyLabel = "暂无标签") {
  const node = byId(id);
  if (!node) {
    return;
  }
  if (!items || items.length === 0) {
    node.innerHTML = `<span class="tag neutral">${escapeHtml(emptyLabel)}</span>`;
    return;
  }
  node.innerHTML = items.map((item) => {
    const tone = item.tone || "neutral";
    return `<span class="tag ${tone}">${escapeHtml(item.text)}</span>`;
  }).join("");
}

function renderSpecList(id, spec) {
  const node = byId(id);
  if (!node) {
    return;
  }
  if (!spec) {
    node.innerHTML = '<div class="spec-row"><span>状态</span><strong>暂无数据</strong></div>';
    return;
  }
  const rows = [
    ["物料 ID", spec.material_id],
    ["材质/类型", spec.material_type],
    ["颜色", spec.color],
    ["形状", spec.shape],
    ["尺寸", spec.size],
    ["批次", spec.batch],
    ["备注", spec.remark],
  ].filter((item) => item[1] !== undefined && item[1] !== null && item[1] !== "");

  if (rows.length === 0) {
    node.innerHTML = '<div class="spec-row"><span>状态</span><strong>暂无数据</strong></div>';
    return;
  }

  node.innerHTML = `<div class="spec-list">${rows.map((row) => `
    <div class="spec-row">
      <span>${escapeHtml(row[0])}</span>
      <strong>${escapeHtml(row[1])}</strong>
    </div>
  `).join("")}</div>`;
}

function setJsonText(id, value, fallback) {
  const node = byId(id);
  if (node) {
    node.textContent = prettyJson(value, fallback);
  }
}

function comparisonBadge(tone, text) {
  return `<span class="tag ${tone}">${escapeHtml(text)}</span>`;
}

function formatSpecLabel(spec, fallback = "--") {
  if (!spec || typeof spec !== "object") {
    return fallback;
  }
  const parts = [spec.color, spec.shape, spec.material_type].filter(Boolean);
  return parts.length > 0 ? parts.join(" ") : fallback;
}

function fieldComparison(expected, actual, mismatchFields, key) {
  if (!expected && !actual) {
    return { tone: "neutral", text: "未提供" };
  }
  if (mismatchFields.has(key)) {
    return { tone: "red", text: "不一致" };
  }
  if (!actual) {
    return { tone: "yellow", text: "待识别" };
  }
  if (!expected) {
    return { tone: "blue", text: "仅检测" };
  }
  return expected === actual
    ? { tone: "green", text: "一致" }
    : { tone: "red", text: "不一致" };
}

function orderResultTone(status) {
  if (status === "matched") {
    return "green";
  }
  if (status === "anomaly") {
    return "red";
  }
  if (status === "manual") {
    return "yellow";
  }
  return "neutral";
}

function orderResultLabel(status) {
  if (status === "matched") {
    return "已匹配";
  }
  if (status === "anomaly") {
    return "不一致";
  }
  if (status === "manual") {
    return "待复核";
  }
  if (status === "pending") {
    return "待执行";
  }
  return safeText(status, "--");
}

function buildOrderRowMarkup(entry = {}, index = 0) {
  const summary = formatSpecLabel(entry.spec, "--");
  return `
    <tr>
      <td>${index + 1}</td>
      <td>
        <input
          class="order-row-input"
          type="text"
          value="${escapeHtml(entry.raw_text || "")}"
          placeholder="例如 黄色正方形"
        >
      </td>
      <td>${escapeHtml(summary)}</td>
      <td><button type="button" class="order-remove-button">删除</button></td>
    </tr>
  `;
}

function extractOrderEditorRows() {
  return Array.from(document.querySelectorAll("#orderRequirementRows .order-row-input"))
    .map((node) => node.value.trim())
    .filter(Boolean);
}

function appendOrderEditorRow(entry = {}) {
  const body = byId("orderRequirementRows");
  if (!body) {
    return;
  }
  const index = body.querySelectorAll("tr").length;
  body.insertAdjacentHTML("beforeend", buildOrderRowMarkup(entry, index));
}

function normalizeOrderEditorIndices() {
  const rows = Array.from(document.querySelectorAll("#orderRequirementRows tr"));
  rows.forEach((row, index) => {
    const firstCell = row.querySelector("td");
    if (firstCell) {
      firstCell.textContent = String(index + 1);
    }
  });
}

function ensureAtLeastOneOrderEditorRow() {
  const body = byId("orderRequirementRows");
  if (!body) {
    return;
  }
  if (body.querySelectorAll("tr").length === 0) {
    appendOrderEditorRow({});
  }
  normalizeOrderEditorIndices();
}

function renderOrderRequirementEditor(queueState) {
  if (pollState.orderRequirementDirty) {
    return;
  }
  const body = byId("orderRequirementRows");
  if (!body) {
    return;
  }
  const entries = Array.isArray(queueState?.entries) ? queueState.entries : [];
  if (entries.length === 0) {
    body.innerHTML = "";
    appendOrderEditorRow({});
    return;
  }
  body.innerHTML = entries.map((entry, index) => buildOrderRowMarkup(entry, index)).join("");
}

function renderOrderRequirementHistory(queueState) {
  const body = byId("orderRequirementHistoryBody");
  if (!body) {
    return;
  }
  const history = Array.isArray(queueState?.history) ? queueState.history : [];
  if (history.length === 0) {
    body.innerHTML = '<tr><td colspan="4" class="empty-cell">暂无订单历史</td></tr>';
    return;
  }

  body.innerHTML = history.slice(0, 8).map((item) => `
    <tr>
      <td>${escapeHtml(item.raw_text || "--")}</td>
      <td>${comparisonBadge(orderResultTone(item.status), orderResultLabel(item.status))}</td>
      <td>${escapeHtml(formatTime(item.completed_at))}</td>
      <td>${escapeHtml(item.last_result?.reason || "--")}</td>
    </tr>
  `).join("");
}

function renderComparisonMatrix(latest, orderRequirement) {
  const node = byId("comparisonMatrix");
  if (!node) {
    return;
  }

  const nfc = latest.nfc || {};
  const vision = latest.vision || {};
  const comparison = latest.comparison || {};
  const referenceSpec = comparison.order_params || orderRequirement?.spec || {};
  const orderEnabled = Boolean(orderRequirement?.enabled);
  const nfcParams = comparison.nfc_params || {};
  const mismatchFields = new Set(comparison.mismatch_fields || []);
  const nfcUidFallback = isUidFallbackSample(nfc);
  const nfcTextReady = hasReadableNfcText(nfc);

  const nfcBadge = nfcTextReady
    ? { tone: "green", text: "直接比对文本" }
    : nfcUidFallback
      ? { tone: "yellow", text: "仅识别UID" }
      : !nfc.success
        ? { tone: "red", text: "读卡失败" }
        : { tone: "yellow", text: "文本未就绪" };

  const rows = [
    {
      title: "文本来源",
      order: orderEnabled ? (orderRequirement.raw_text || "已启用") : "未启用",
      nfc: nfc.text || nfc.error || "--",
      vision: vision.label || vision.details || "--",
      badge: nfcBadge,
    },
    {
      title: "物料类型",
      order: referenceSpec.material_type || (orderEnabled ? "--" : "未启用"),
      nfc: nfcParams.material_type || "--",
      vision: vision.material_type || "--",
      badge: fieldComparison(referenceSpec.material_type, vision.material_type, mismatchFields, "material_type"),
    },
    {
      title: "颜色",
      order: referenceSpec.color || (orderEnabled ? "--" : "未启用"),
      nfc: nfcParams.color || "--",
      vision: vision.color || "--",
      badge: fieldComparison(referenceSpec.color, vision.color, mismatchFields, "color"),
    },
    {
      title: "形状",
      order: referenceSpec.shape || (orderEnabled ? "--" : "未启用"),
      nfc: nfcParams.shape || "--",
      vision: vision.shape || "--",
      badge: fieldComparison(referenceSpec.shape, vision.shape, mismatchFields, "shape"),
    },
  ];

  node.innerHTML = rows.map((row) => `
    <div class="matrix-row">
      <div class="matrix-title">${escapeHtml(row.title)}</div>
      <div class="matrix-cell">${escapeHtml(row.order)}</div>
      <div class="matrix-cell">${escapeHtml(row.nfc)}</div>
      <div class="matrix-cell">${escapeHtml(row.vision)}</div>
      <div>${comparisonBadge(row.badge.tone, row.badge.text)}</div>
    </div>
  `).join("");
}

function buildComparisonVerdict(latest, orderRequirement) {
  const nfc = latest.nfc || {};
  const comparison = latest.comparison || {};
  const vision = latest.vision || {};
  const orderEnabled = Boolean(orderRequirement?.enabled);
  const orderLabel = orderEnabled ? formatSpecLabel(orderRequirement.spec, orderRequirement.raw_text || "已启用") : "未启用";
  const nfcTextReady = Boolean(hasReadableNfcText(nfc));
  const uidFallback = isUidFallbackSample(nfc);
  const visionReady = Boolean(
    vision.success
      || vision.label
      || vision.color
      || vision.shape
      || vision.material_type,
  );
  const visionLabel = vision.label || vision.shape || vision.material_type || "未识别";

  if (!nfcTextReady) {
    return {
      tone: uidFallback ? "yellow" : (nfc.success ? "yellow" : "red"),
      title: uidFallback ? "NFC 仅识别 UID" : "NFC 文本未就绪",
      detail: nfc.error || (orderEnabled
        ? "需要先读到 NFC 标签文本，才能和订单、视觉一起判定。"
        : "需要先读到 NFC 标签文本，才能判定是否与视觉结果一致。"),
      orderSignal: orderLabel,
      nfcSignal: uidFallback ? "仅 UID" : (nfc.success ? "缺少文本" : "读取失败"),
      visionSignal: visionReady ? visionLabel : "等待识别",
      matchSignal: "待判定",
    };
  }

  if (!visionReady) {
    return {
      tone: "yellow",
      title: "视觉结果未就绪",
      detail: orderEnabled
        ? "订单与 NFC 已准备好，但视觉侧还没有形成有效识别结果。"
        : "NFC 已读到文本，但视觉侧还没有形成有效识别结果。",
      orderSignal: orderLabel,
      nfcSignal: "文本已读到",
      visionSignal: "未识别",
      matchSignal: "待判定",
    };
  }

  if (comparison.status === "通过") {
    return {
      tone: "green",
      title: orderEnabled ? "订单 / NFC / 视觉一致" : "NFC 与视觉一致",
      detail: comparison.details || (orderEnabled
        ? "订单目标、NFC 文本与视觉结果一致，将沿主线放行。"
        : "NFC 文本与视觉结果一致，将沿主线放行。"),
      orderSignal: orderLabel,
      nfcSignal: "文本已读到",
      visionSignal: visionLabel,
      matchSignal: "一致",
    };
  }

  if (comparison.status === "异常") {
    return {
      tone: "red",
      title: orderEnabled ? "订单 / NFC / 视觉不一致" : "NFC 与视觉不一致",
      detail: comparison.details || (orderEnabled
        ? "订单目标、NFC 文本或视觉结果之间存在不一致，当前物料将拨入异常区。"
        : "视觉结果与 NFC 标签文本不匹配，当前物料将拨入异常区。"),
      orderSignal: orderLabel,
      nfcSignal: "文本已读到",
      visionSignal: visionLabel,
      matchSignal: "不一致",
    };
  }

  if (comparison.status === "低置信度" || comparison.status === "无识别结果") {
    return {
      tone: "yellow",
      title: "视觉结果不足以判定",
      detail: comparison.details || "视觉结果还不够稳定，当前暂时不能下结论。",
      orderSignal: orderLabel,
      nfcSignal: "文本已读到",
      visionSignal: visionLabel,
      matchSignal: "待复核",
    };
  }

  if (comparison.status === "无比对目标") {
    return {
      tone: "blue",
      title: "缺少可比对目标",
      detail: comparison.details || "当前 NFC 文本里没有足够的颜色/形状/类型信息。",
      orderSignal: orderLabel,
      nfcSignal: "文本已读到",
      visionSignal: visionLabel,
      matchSignal: "待补充",
    };
  }

  if (comparison.status === "NFC异常") {
    return {
      tone: "red",
      title: "NFC 读取异常",
      detail: comparison.details || "当前没有拿到可用于比对的 NFC 结果。",
      orderSignal: orderLabel,
      nfcSignal: "读取失败",
      visionSignal: visionLabel,
      matchSignal: "无法判定",
    };
  }

  return {
    tone: "neutral",
    title: "等待判定",
    detail: comparison.details || (orderEnabled
      ? "系统正在等待完整的订单、NFC 与视觉上下文。"
      : "系统正在等待完整的 NFC 与视觉上下文。"),
    orderSignal: orderLabel,
    nfcSignal: nfcTextReady ? "文本已读到" : "等待 NFC",
    visionSignal: visionReady ? visionLabel : "等待识别",
    matchSignal: "等待中",
  };
}

function updateMetrics(data) {
  const decisions = data.system?.decisions || {};
  const historyCount = data.history?.length ?? data.system?.history?.count ?? 0;

  setText("metricTotalOrders", historyCount, "0");
  setText("metricPassed", decisions.pass ?? 0, "0");
  setText("metricAnomaly", decisions.sort ?? 0, "0");
  setText("metricManual", decisions.manual ?? 0, "0");
  setText("metricDecisions", decisions.total ?? 0, "0");
  setText("metricProcessed", historyCount, "0");
}

function updateHero(data) {
  const systemStatus = data.system?.status;
  const mode = data.system?.mode;
  const health = data.latest?.health?.overall || data.device?.health;

  setText("heroSystemStatus", systemStatus);
  setChip("heroHealthBadge", `设备健康 ${safeText(health, "未知")}`, healthTone(health));
  setText(
    "heroMetaLine",
    `模式 ${safeText(mode)} · 最近刷新 ${formatTime(data.generated_at)}`,
    "--",
  );
}

function updateStage(data) {
  const latest = data.latest || {};
  const cameraPreview = data.camera_preview || {};
  const cameraStatus = cameraPreview.status || {};
  const history = latest.history || {};
  const decision = latest.decision || {};
  const stageMode = latest.stage_mode;
  const stageUrl = latest.stage_url;
  const previewPending = stageMode === "live" && !cameraPreview.ready;

  setText("latestCheckedAt", formatTime(history.checked_at || data.generated_at));
  setText("latestMaterialId", history.material_id || latest.nfc?.material_id || data.system?.current_material_id);
  setText("latestRoute", decision.route || history.route || "--");
  setText("latestDecisionStatus", decision.order_status || history.final_status || "--");
  setText("latestMode", data.system?.mode);
  setChip(
    "stageModeChip",
    previewPending
      ? "预览准备中"
      : stageMode === "live"
        ? "实时预览"
        : stageMode === "capture"
          ? "最近抓拍"
          : "等待画面",
    previewPending
      ? "yellow"
      : stageMode === "live"
        ? "blue"
        : stageMode === "capture"
          ? "green"
          : "neutral",
  );

  const image = byId("capturePreview");
  const fallback = byId("captureFallback");
  const fallbackTitle = byId("captureFallbackTitle");
  const fallbackText = byId("captureFallbackText");
  if (!image || !fallback) {
    return;
  }

  if (!stageUrl) {
    image.hidden = true;
    image.removeAttribute("src");
    fallback.hidden = false;
    pollState.captureVersion = "";
    if (fallbackTitle) {
      fallbackTitle.textContent = !cameraPreview.available
        ? "摄像头预览不可用"
        : cameraPreview.running
          ? "摄像头画面未就绪"
          : "摄像头预览已关闭";
    }
    if (fallbackText) {
      fallbackText.textContent = cameraStatus.last_error
        ? `预览状态: ${cameraStatus.last_error}`
        : cameraPreview.processing
          ? "实时识别仍在后台运行，当前仅关闭了网页画面回传。"
        : "正在等待实时预览或最近抓拍图像。";
    }
    return;
  }

  if (previewPending) {
    image.hidden = true;
    image.removeAttribute("src");
    fallback.hidden = false;
    pollState.captureVersion = "";
    if (fallbackTitle) {
      fallbackTitle.textContent = "实时预览准备中";
    }
    if (fallbackText) {
      fallbackText.textContent = cameraStatus.last_error
        ? `预览状态: ${cameraStatus.last_error}`
        : "预览流已开启，正在等待第一帧图像回传。";
    }
    return;
  }

  const version = stageMode === "live"
    ? `${data.generated_at || Date.now()}|live`
    : `${history.checked_at || ""}|${latest.capture_path || ""}|capture`;
  if (pollState.captureVersion !== version || stageMode === "live") {
    image.src = `${stageUrl}?t=${encodeURIComponent(version)}`;
    pollState.captureVersion = stageMode === "live" ? "" : version;
  }
  image.hidden = false;
  fallback.hidden = true;
}

function updateNfcPanel(data) {
  const nfcStatus = data.nfc_sample || {};
  const nfcRuntime = data.nfc_runtime || {};
  const nfc = nfcStatus.sample || data.latest?.nfc || {};
  const hasPayload = hasMeaningfulObject(nfc);
  const liveSample = hasMeaningfulObject(nfcStatus.sample);
  const historyFallback = isHistoricalNfcSource(nfcStatus.source)
    || (!liveSample && hasMeaningfulObject(data.latest?.nfc));
  const success = nfc.success === true;
  const hasError = nfc.success === false;
  const uidFallback = isUidFallbackSample(nfc);
  const textReady = hasReadableNfcText(nfc);
  const textWithoutMaterialId = textReady && !nfc.material_id;
  const noTagDetected = hasError && /No NFC tag detected/i.test(safeText(nfc.error, ""));
  const chipText = !hasPayload
    ? "等待采样"
    : historyFallback
      ? "历史结果"
      : textReady && !textWithoutMaterialId
        ? "文本读取成功"
        : textWithoutMaterialId
          ? "已读到标签文本"
          : uidFallback
            ? "仅识别到 UID"
            : noTagDetected
              ? "未检测到标签"
              : hasError
                ? "读取异常"
                : success
                  ? "已检测到标签"
                  : "已采样";
  const chipTone = !hasPayload
    ? "neutral"
    : historyFallback
      ? "blue"
      : textReady && !textWithoutMaterialId
        ? "green"
        : textWithoutMaterialId || uidFallback
          ? "yellow"
          : noTagDetected
            ? "neutral"
            : hasError
              ? "red"
              : "blue";
  const resultText = !hasPayload
    ? "等待数据"
    : historyFallback
      ? "当前显示最近一次历史结果"
      : textReady && !textWithoutMaterialId
        ? "成功"
        : textWithoutMaterialId
          ? "已读文本，未解析出物料 ID"
          : uidFallback
            ? "仅读到 UID，未读到标签文本"
            : noTagDetected
              ? "请放置 NFC 标签"
              : hasError
                ? "失败"
                : success
                  ? "已检测到标签"
                  : "已采样";

  setChip("nfcStatusChip", chipText, chipTone);
  setText("nfcMaterialId", nfc.material_id);
  setText("nfcTextContent", textReady ? nfc.text : "--");
  setText("nfcResultText", resultText);
  setText("nfcSampleTime", formatTime(nfcStatus.sampled_at));
  setText(
    "nfcErrorText",
    nfc.error || (uidFallback ? "仅读到 UID，未读到标签文本" : !hasPayload ? "--" : "无"),
  );
  renderTagRow("nfcMetaTags", [
    nfcRuntime.configured_backend
      ? { text: `配置 ${nfcRuntime.configured_backend}`, tone: "green" }
      : { text: "未配置真实 NFC 后端", tone: "yellow" },
    nfcStatus.backend ? { text: `后端 ${nfcStatus.backend}`, tone: "blue" } : null,
    nfcRuntime.i2c_bus !== null && nfcRuntime.i2c_bus !== undefined
      ? { text: `I2C-${safeText(nfcRuntime.i2c_bus)}`, tone: "blue" }
      : null,
    nfcRuntime.i2c_address
      ? { text: `地址 ${safeText(nfcRuntime.i2c_address)}`, tone: "neutral" }
      : null,
    nfcRuntime.fallback_to_uid
      ? { text: "UID 回退开启", tone: "yellow" }
      : { text: "UID 回退关闭", tone: "green" },
    nfcStatus.source ? { text: `来源 ${nfcStatus.source}`, tone: "neutral" } : null,
    nfc.raw?.material_id_source
      ? { text: `ID来源 ${safeText(nfc.raw.material_id_source)}`, tone: uidFallback ? "yellow" : "green" }
      : null,
    historyFallback
      ? { text: "当前为历史回退结果", tone: "yellow" }
      : liveSample
        ? { text: "当前为实时采样结果", tone: "green" }
        : null,
    nfcStatus.suspended
      ? { text: "主流程接管中", tone: "blue" }
      : nfcStatus.polling
        ? { text: "持续采样中", tone: "green" }
        : { text: "手动采样", tone: "yellow" },
  ].filter(Boolean), "暂无采样上下文");
  setJsonText("nfcPayloadDebug", hasPayload ? nfc : null, "暂无 NFC 原始数据");
}

function resolveVisionData(data) {
  const latestVision = data.latest?.vision;
  const liveVision = data.camera_preview?.live_vision_result || data.camera_preview?.status?.live_vision_result;
  if (hasMeaningfulObject(liveVision) && liveVision.success) {
    return liveVision;
  }
  if (hasMeaningfulObject(latestVision)) {
    return latestVision;
  }
  if (hasMeaningfulObject(liveVision)) {
    return liveVision;
  }
  return {};
}

function resolveVisionPanelData(data) {
  const liveVision = data.camera_preview?.live_vision_result || data.camera_preview?.status?.live_vision_result;
  if (hasMeaningfulObject(liveVision)) {
    return liveVision;
  }
  return data.latest?.vision || {};
}

function updateVisionPanel(data) {
  const vision = resolveVisionPanelData(data);
  const success = Boolean(vision.success);
  const isLive = vision.source === "live_preview";
  const hasVision = hasMeaningfulObject(vision);
  const chipText = !hasVision
    ? "等待识别"
    : success
      ? (isLive ? "实时识别" : "识别成功")
      : (isLive ? "未检测到物品" : "识别为空");
  const chipTone = !hasVision ? "neutral" : success ? "green" : isLive ? "yellow" : "yellow";

  setChip("visionStatusChip", chipText, chipTone);
  setText("visionLabel", vision.label);
  setText("visionColor", vision.color);
  setText("visionShape", vision.shape);
  setText("visionType", vision.material_type);
  setText("visionConfidence", formatPercent(vision.confidence));
  setText("visionDetailsText", vision.details || (isLive ? "当前画面未检测到物品" : "无"));
  renderTagRow(
    "visionTagRow",
    [
      isLive
        ? { text: "来源 实时预览", tone: "blue" }
        : hasVision
          ? { text: "来源 最近检测", tone: "green" }
          : null,
      hasVision ? { text: `总体置信度 ${formatPercent(vision.confidence)}`, tone: "blue" } : null,
      vision.color_confidence !== undefined
        ? { text: `颜色 ${formatPercent(vision.color_confidence)}`, tone: "green" }
        : null,
      vision.shape_confidence !== undefined
        ? { text: `形状 ${formatPercent(vision.shape_confidence)}`, tone: "green" }
        : null,
      vision.detection_confidence !== undefined
        ? { text: `检测 ${formatPercent(vision.detection_confidence)}`, tone: "blue" }
        : null,
      vision.detection_count !== undefined
        ? { text: `目标 ${safeText(vision.detection_count)}`, tone: "neutral" }
        : null,
    ].filter(Boolean),
    "暂无视觉标签",
  );

  setJsonText("visionPayloadDebug", vision, "暂无视觉原始数据");
}

function updateComparisonPanel(data) {
  const latest = data.latest || {};
  const history = latest.history || {};
  const comparison = latest.comparison || {};
  const orderRequirement = comparison.order_requirement || data.order_requirement || {};
  const frozenNfc = history.nfc_snapshot || latest.nfc;
  const frozenVision = history.vision_snapshot || latest.vision;
  const displayLatest = {
    ...latest,
    nfc: frozenNfc || data.nfc_sample?.sample || latest.nfc,
    vision: frozenVision || resolveVisionData(data),
  };
  const decision = latest.decision || {};
  const status = comparison.status || history.final_status || "暂无结果";
  const reason = comparison.details || decision.reason || history.reason || "暂无比对说明";
  const reasons = comparison.reasons || history.anomaly_reasons || [];
  const mismatchFields = comparison.mismatch_fields || [];
  const verdict = buildComparisonVerdict(displayLatest, orderRequirement);

  const verdictCard = byId("comparisonVerdictCard");
  if (verdictCard) {
    verdictCard.className = `compare-verdict ${verdict.tone}`;
  }

  setChip("comparisonStatusChip", status, comparisonTone(status));
  setText("comparisonVerdictText", verdict.title);
  setText("comparisonVerdictDetail", verdict.detail);
  setText("comparisonOrderSignal", verdict.orderSignal);
  setText("comparisonNfcSignal", verdict.nfcSignal);
  setText("comparisonVisionSignal", verdict.visionSignal);
  setText("comparisonMatchSignal", verdict.matchSignal);
  setText("comparisonHeadline", status);
  setText("comparisonReason", reason);
  renderTagRow("comparisonReasonTags", [
    ...reasons.map((item) => ({ text: item, tone: "yellow" })),
    ...mismatchFields.map((item) => ({ text: `字段 ${item}`, tone: "red" })),
    decision.route ? { text: `路线 ${decision.route}`, tone: "blue" } : null,
    decision.requires_manual_review ? { text: "需人工复核", tone: "yellow" } : null,
  ].filter(Boolean), "暂无异常原因");

  renderComparisonMatrix(displayLatest, orderRequirement);
  renderSpecList("expectedSpec", orderRequirement.enabled ? orderRequirement.spec : comparison.order_params || null);
  renderSpecList("actualSpec", displayLatest.vision ? {
    material_type: displayLatest.vision.material_type,
    color: displayLatest.vision.color,
    shape: displayLatest.vision.shape,
    remark: displayLatest.vision.details,
  } : null);
}

function updateOrderRequirementPanel(data) {
  const requirement = data.order_requirement || {};
  const queueState = data.order_queue || {};
  const enabled = Boolean(queueState.enabled);
  const spec = requirement.spec || {};

  setChip("orderRequirementChip", enabled ? "订单队列开启" : "订单队列关闭", enabled ? "green" : "neutral");
  setText(
    "orderRequirementTextView",
    requirement.raw_text || (queueState.exhausted ? "队列已完成" : ""),
    enabled ? (queueState.exhausted ? "队列已完成" : "等待订单") : "未启用",
  );
  setText("orderRequirementType", spec.material_type);
  setText("orderRequirementColor", spec.color);
  setText("orderRequirementShape", spec.shape);
  setText("orderRequirementPendingCount", queueState.pending_count !== undefined ? String(queueState.pending_count) : "--");
  setText("orderRequirementHistoryCount", queueState.history_count !== undefined ? String(queueState.history_count) : "--");
  setText("orderRequirementUpdatedAt", formatTime(queueState.updated_at || requirement.updated_at));

  const enabledInput = byId("orderRequirementEnabled");
  if (enabledInput && !pollState.orderRequirementDirty) {
    enabledInput.checked = enabled;
  }

  renderOrderRequirementEditor(queueState);
  renderOrderRequirementHistory(queueState);

  renderTagRow("orderRequirementTags", [
    enabled
      ? { text: "当前按订单 / NFC / 视觉并行校验", tone: "green" }
      : { text: "当前仅按 NFC / 视觉校验", tone: "blue" },
    queueState.pending_count ? { text: `剩余 ${queueState.pending_count} 项`, tone: "neutral" } : null,
    queueState.history_count ? { text: `历史 ${queueState.history_count} 项`, tone: "neutral" } : null,
    queueState.exhausted ? { text: "订单队列已完成", tone: "green" } : null,
    requirement.raw_text ? { text: `当前 ${requirement.raw_text}`, tone: "neutral" } : null,
    spec.material_type ? { text: `材质 ${spec.material_type}`, tone: "blue" } : null,
    spec.color ? { text: `颜色 ${spec.color}`, tone: "green" } : null,
    spec.shape ? { text: `形状 ${spec.shape}`, tone: "green" } : null,
  ].filter(Boolean), "暂无订单目标");
}

function sensorText(snapshot, key) {
  const item = snapshot?.[key];
  if (!item) {
    return "--";
  }
  const unit = key === "current" ? "A" : "g";
  return `${formatNumber(item.value)} ${unit}`;
}

function sensorLevelText(snapshot, key) {
  const item = snapshot?.[key];
  return item?.level ? safeText(item.level) : "--";
}

function sensorAverageText(snapshot, key) {
  const item = snapshot?.[key];
  if (typeof item?.average !== "number") {
    return "--";
  }
  const unit = key === "current" ? "A" : "g";
  return `${formatNumber(item.average)} ${unit}`;
}

function simplifyBackendName(name) {
  if (!name) {
    return "--";
  }
  const text = String(name);
  if (text === "MPU6050VibrationSensor") {
    return "MPU6050";
  }
  if (text === "VibrationSensor" || text === "MockVibrationSensor") {
    return "Mock";
  }
  return text;
}

function updateDevicePanel(data) {
  const device = data.device || {};
  const system = data.system || {};
  const conveyor = device.conveyor || {};
  const health = data.latest?.health || device.last_health_snapshot || {};
  const overall = health.overall || device.health;
  const reasons = health.reasons || [];
  const latestHistory = data.latest?.history || {};
  const historyList = Array.isArray(data.history) ? data.history : [];
  const lastProcessing = system.last_processing_result || {};
  const sortTiming = device.sort_timing || {};
  const primarySortAngle = device.servo_sort_angle;
  const secondarySortAngle = device.servo_sort_secondary_angle;
  const oscillationInterval = device.sort_servo_oscillation_interval;
  const recentStopEntry = historyList.find((item) => item?.action === "stop") || null;
  const activeStop = lastProcessing.action === "stop" ? lastProcessing : null;
  const stopReason = activeStop?.reason
    || recentStopEntry?.reason
    || (latestHistory.action === "stop" ? latestHistory.reason : "")
    || "--";
  const stopReasonDetails = (activeStop?.reasons && activeStop.reasons.length > 0)
    ? activeStop.reasons.join("、")
    : (recentStopEntry?.anomaly_reasons && recentStopEntry.anomaly_reasons.length > 0)
      ? recentStopEntry.anomaly_reasons.join("、")
      : (latestHistory.action === "stop" && latestHistory.anomaly_reasons?.length)
        ? latestHistory.anomaly_reasons.join("、")
        : "暂无故障停机详情";
  const stopAt = activeStop?.health_snapshot?.sampled_at
    || recentStopEntry?.checked_at
    || (latestHistory.action === "stop" ? latestHistory.checked_at : null);

  setChip("deviceHealthChip", `健康 ${safeText(overall, "未知")}`, healthTone(overall));
  setText("deviceConveyorState", conveyor.state);
  setText("deviceConveyorSpeed", conveyor.speed !== undefined ? String(conveyor.speed) : "--");
  setText("deviceServoAngle", device.servo_angle !== undefined ? `${device.servo_angle}°` : "--");
  setText("deviceRunningText", device.running ? "运行中" : "未运行");
  setText("deviceVibrationBackend", simplifyBackendName(device.vibration_backend));
  setText("deviceVibration", sensorText(health, "vibration"));
  setText("deviceVibrationLevel", sensorLevelText(health, "vibration"));
  setText("deviceVibrationAverage", sensorAverageText(health, "vibration"));
  setText("deviceCurrent", sensorText(health, "current"));
  setText("deviceStopReason", stopReason, "暂无故障停机");
  setText("deviceStopReasonDetails", stopReasonDetails, "暂无故障停机详情");
  setText("deviceStopAt", formatTime(stopAt), "暂无故障停机记录");
  setText("deviceHealthSampledAt", formatTime(health.sampled_at));
  renderTagRow("deviceReasonTags", [
    { text: device.running ? "设备运行中" : "设备未运行", tone: boolTone(device.running) },
    device.alert_latched ? { text: "故障已锁存", tone: "red" } : { text: "未锁存故障", tone: "green" },
    activeStop?.reason ? { text: `停机 ${safeText(activeStop.reason)}`, tone: overall === "red" ? "red" : "yellow" } : null,
    device.vibration_backend
      ? { text: `振动 ${simplifyBackendName(device.vibration_backend)}`, tone: "blue" }
      : null,
    health.vibration?.level
      ? { text: `振动 ${safeText(health.vibration.level)}`, tone: healthTone(health.vibration.level) }
      : null,
    typeof health.vibration?.average === "number"
      ? { text: `均值 ${formatNumber(health.vibration.average)}`, tone: "neutral" }
      : null,
    device.servo_normal_angle !== undefined && device.servo_normal_angle !== null
      ? { text: `常态 ${safeText(device.servo_normal_angle)}°`, tone: "blue" }
      : null,
    primarySortAngle !== undefined && primarySortAngle !== null
      ? {
        text: secondarySortAngle !== undefined && secondarySortAngle !== null
          ? `异常 ${safeText(primarySortAngle)}°<->${safeText(secondarySortAngle)}°`
          : `异常 ${safeText(primarySortAngle)}°`,
        tone: "yellow",
      }
      : null,
    oscillationInterval !== undefined && oscillationInterval !== null && Number(oscillationInterval) > 0
      ? { text: `间隔 ${formatNumber(oscillationInterval, 1)}s`, tone: "neutral" }
      : null,
    sortTiming.conveyor_advance_time !== undefined
      ? { text: `摆动 ${formatNumber(sortTiming.conveyor_advance_time, 1)}s`, tone: "neutral" }
      : null,
    ...reasons.map((item) => ({ text: item, tone: overall === "red" ? "red" : "yellow" })),
  ].filter(Boolean), "暂无健康告警");
}

function updateDebugPanel(data) {
  const debug = data.debug || {};
  const device = data.device || {};
  const checks = device.last_startup_check || {};
  const container = byId("startupChecks");

  setText("statePathText", `状态文件: ${safeText(debug.state_path, "--")}`, "--");

  if (container) {
    const entries = Object.entries(checks);
    if (entries.length === 0) {
      container.innerHTML = '<div class="startup-item"><div><strong>启动自检</strong><span>暂无自检记录</span></div></div>';
    } else {
      container.innerHTML = entries.map(([key, value]) => `
        <div class="startup-item">
          <div>
            <strong>${escapeHtml(key)}</strong>
            <span>${escapeHtml(value.message || "无消息")}</span>
          </div>
          ${comparisonBadge(value.ok ? "green" : "red", value.ok ? "通过" : "失败")}
        </div>
      `).join("");
    }
  }

  const box = byId("debugPayload");
  if (box) {
    box.textContent = prettyJson(
      {
        latest: data.latest,
        camera_preview: data.camera_preview,
        debug,
        device,
      },
      "暂无调试上下文",
    );
  }
}

function updatePreviewToggleButton(data) {
  const button = byId("previewToggleButton");
  if (!button) {
    return;
  }
  const cameraPreview = data.camera_preview || {};
  if (!cameraPreview.available) {
    button.disabled = true;
    button.textContent = "预览不可用";
    button.dataset.running = "false";
    return;
  }

  const running = Boolean(cameraPreview.running);
  button.disabled = false;
  button.dataset.running = running ? "true" : "false";
  button.textContent = running ? "关闭画面" : "打开画面";
}

function updateHistoryTable(data) {
  const body = byId("historyTableBody");
  const history = data.history || [];

  setText("historyCountText", `${history.length} 条`, "0 条");
  if (!body) {
    return;
  }

  if (history.length === 0) {
    body.innerHTML = '<tr><td colspan="7" class="empty-cell">等待处理记录</td></tr>';
    return;
  }

  body.innerHTML = history.map((item) => {
    const nfc = item.nfc_snapshot || {};
    const vision = item.vision_snapshot || {};
    const comparison = item.comparison_snapshot || {};
    return `
      <tr>
        <td>${escapeHtml(formatTime(item.checked_at))}</td>
        <td>${escapeHtml(item.material_id || "--")}</td>
        <td>${escapeHtml(nfc.material_id || (nfc.success === false ? "读取失败" : "--"))}</td>
        <td>${escapeHtml(vision.label || vision.details || "--")}</td>
        <td>${escapeHtml(comparison.status || item.final_status || "--")}</td>
        <td>${escapeHtml(item.route || "--")}</td>
        <td>${escapeHtml(item.reason || "--")}</td>
      </tr>
    `;
  }).join("");
}

function applyDashboard(data) {
  updateHero(data);
  updateMetrics(data);
  updateStage(data);
  updateNfcPanel(data);
  updateVisionPanel(data);
  updateComparisonPanel(data);
  updateOrderRequirementPanel(data);
  updateDevicePanel(data);
  updateDebugPanel(data);
  updatePreviewToggleButton(data);
  updateHistoryTable(data);
}

async function fetchDashboard(showFeedback = false) {
  if (pollState.busy) {
    return;
  }

  pollState.busy = true;
  try {
    const response = await fetch(config.dashboardUrl, { cache: "no-store" });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || `HTTP ${response.status}`);
    }
    applyDashboard(payload);
    if (showFeedback) {
      setFeedback("看板数据已刷新", "green");
    }
  } catch (error) {
    console.error(error);
    setFeedback(`刷新失败: ${error.message}`, "red");
  } finally {
    pollState.busy = false;
  }
}

function schedulePoll() {
  clearTimeout(pollState.pollTimer);
  const delay = document.hidden ? 4000 : 1600;
  pollState.pollTimer = setTimeout(async () => {
    await fetchDashboard(false);
    schedulePoll();
  }, delay);
}

async function postJson(url, payload = {}) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok || data.success === false) {
    throw new Error(data.error || data.message || `HTTP ${response.status}`);
  }
  return data;
}

function bindButtons() {
  const buttonMap = [
    ["refreshButton", async () => {
      await fetchDashboard(true);
    }],
    ["nfcSampleButton", async () => {
      const result = await postJson(config.nfcSampleUrl);
      setFeedback(result.message || "已触发一次 NFC 采样", "blue");
      await fetchDashboard(false);
    }],
    ["previewToggleButton", async (node) => {
      const running = node.dataset.running === "true";
      await postJson(config.cameraControlUrl, { enabled: !running });
      setFeedback(
        running ? "已关闭网页预览回传，后台实时识别继续运行" : "已打开实时预览回传",
        running ? "yellow" : "blue",
      );
      await fetchDashboard(false);
    }],
    ["startButton", async () => {
      await postJson(config.startUrl);
      setFeedback("设备启动指令已发送", "green");
      await fetchDashboard(false);
    }],
    ["stopButton", async () => {
      await postJson(config.stopUrl);
      setFeedback("停止请求已发送", "yellow");
      await fetchDashboard(false);
    }],
    ["resetButton", async () => {
      await postJson(config.resetUrl);
      setFeedback("告警复位完成", "green");
      await fetchDashboard(false);
    }],
  ];

  buttonMap.forEach(([id, handler]) => {
    const node = byId(id);
    if (!node) {
      return;
    }
    node.addEventListener("click", async () => {
      try {
        await handler(node);
      } catch (error) {
        console.error(error);
        setFeedback(`操作失败: ${error.message}`, "red");
      }
    });
  });
}

function bindForms() {
  const orderForm = byId("orderRequirementForm");
  if (orderForm) {
    const orderEnabledInput = byId("orderRequirementEnabled");
    const addRowButton = byId("orderRequirementAddRow");
    const rowsBody = byId("orderRequirementRows");

    [orderEnabledInput].forEach((node) => {
      if (!node) {
        return;
      }
      node.addEventListener("input", () => {
        pollState.orderRequirementDirty = true;
      });
      node.addEventListener("change", () => {
        pollState.orderRequirementDirty = true;
      });
    });

    if (rowsBody) {
      rowsBody.addEventListener("input", (event) => {
        if (event.target instanceof HTMLInputElement) {
          pollState.orderRequirementDirty = true;
        }
      });
      rowsBody.addEventListener("change", (event) => {
        if (event.target instanceof HTMLInputElement) {
          pollState.orderRequirementDirty = true;
        }
      });
      rowsBody.addEventListener("click", (event) => {
        const target = event.target;
        if (!(target instanceof HTMLElement) || !target.classList.contains("order-remove-button")) {
          return;
        }
        const row = target.closest("tr");
        if (row) {
          row.remove();
          ensureAtLeastOneOrderEditorRow();
          pollState.orderRequirementDirty = true;
        }
      });
    }

    if (addRowButton) {
      addRowButton.addEventListener("click", () => {
        appendOrderEditorRow({});
        normalizeOrderEditorIndices();
        pollState.orderRequirementDirty = true;
      });
    }

    orderForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      const enabled = Boolean(orderEnabledInput?.checked);
      const orders = extractOrderEditorRows().map((text) => ({ text }));
      try {
        await postJson(config.orderRequirementUrl, { enabled, orders });
        pollState.orderRequirementDirty = false;
        setFeedback(enabled ? "订单队列已保存并启用" : "订单队列已保存，当前未启用", enabled ? "green" : "blue");
        await fetchDashboard(false);
      } catch (error) {
        console.error(error);
        setFeedback(`订单保存失败: ${error.message}`, "red");
      }
    });
    ensureAtLeastOneOrderEditorRow();
  }

}

function bindCaptureFallback() {
  const image = byId("capturePreview");
  const fallback = byId("captureFallback");
  if (!image || !fallback) {
    return;
  }
  image.addEventListener("load", () => {
    image.hidden = false;
    fallback.hidden = true;
  });
  image.addEventListener("error", () => {
    image.hidden = true;
    fallback.hidden = false;
    const fallbackTitle = byId("captureFallbackTitle");
    const fallbackText = byId("captureFallbackText");
    if (fallbackTitle) {
      fallbackTitle.textContent = "画面加载失败";
    }
    if (fallbackText) {
      fallbackText.textContent = "请检查实时回传接口或最近抓拍文件。";
    }
  });
}

async function initializeDashboard() {
  bindButtons();
  bindForms();
  bindCaptureFallback();
  await fetchDashboard(false);
  schedulePoll();

  document.addEventListener("visibilitychange", () => {
    schedulePoll();
  });
}

initializeDashboard();
