/* ═════════════════════════════════════════════════════════════════════
   智能投资组合配置 —— 前端逻辑（面向普通投资者）
   ═════════════════════════════════════════════════════════════════════ */

const $ = (id) => document.getElementById(id);

// ── 工具函数 ──

function parseList(text) {
  return text.split(/[\n,，]+/).map((s) => s.trim()).filter(Boolean);
}

function parseNumbers(text) {
  return parseList(text).map(Number);
}

function parseReturns(text, cols) {
  const rows = text.trim().split(/\n+/).map((l) => l.trim()).filter(Boolean);
  return rows.map((line) => {
    const cells = line.split(/[,，\t]+/).map(Number);
    if (cells.length !== cols || cells.some(isNaN)) {
      throw new Error("历史数据每行需要 " + cols + " 个数字，与标的数量一致。");
    }
    return cells;
  });
}

function fmtPct(v) {
  if (!isFinite(v)) return "--";
  return (v >= 0 ? "+" : "") + (v * 100).toFixed(2) + "%";
}

function fmtNum(v, d) {
  return isFinite(v) ? v.toFixed(d) : "--";
}

// ── 状态 ──

const state = {
  lastResult: null,
  settingsOpen: false,
};

function showLoading() {
  $("loadingMask").classList.add("show");
}
function hideLoading() {
  $("loadingMask").classList.remove("show");
}

// ── 自动加载示例数据 ──

async function loadSample() {
  try {
    const resp = await fetch("/api/sample");
    const result = await resp.json();
    if (!result.ok) throw new Error(result.error);

    const d = result.data;
    $("inputAssets").value = d.assets.join(", ");
    $("inputWeights").value = d.market_weights.map((v) => v.toFixed(4)).join(", ");
    $("inputReturns").value = d.returns.map((r) => r.join(", ")).join("\n");
    $("inputMaxWeight").value = d.max_weight;
    $("inputTurnoverLimit").value = d.turnover_limit ?? "";
    $("inputRf").value = d.risk_free_rate_annual;
    $("inputLongOnly").checked = d.long_only;

    // 填入一条示例看法
    $("viewsContainer").innerHTML = "";
    (d.views || []).forEach((v) => addViewRow(v));
  } catch (err) {
    console.error("加载示例失败:", err);
  }
}

// ── 看法管理 ──

function addViewRow(view) {
  view = view || {};
  const row = document.createElement("div");
  row.className = "view-row";

  // 解析已有的 legs 格式（兼容旧数据）
  let assetA = "", assetB = "", q = 0.017, confidence = 0.8;
  if (view.legs && view.legs.length >= 2) {
    const pos = view.legs.find((l) => l.weight > 0);
    const neg = view.legs.find((l) => l.weight < 0);
    assetA = pos ? pos.asset : "";
    assetB = neg ? neg.asset : "";
  } else if (view.legs && view.legs.length === 1) {
    assetA = view.legs[0].asset;
  }
  if (view.q !== undefined) q = view.q;
  if (view.confidence !== undefined) confidence = view.confidence;

  const selHigh = confidence >= 0.7 ? "selected" : "";
  const selMid = confidence >= 0.4 && confidence < 0.7 ? "selected" : "";
  const selLow = confidence < 0.4 ? "selected" : "";

  row.innerHTML = `
    <label class="fld">
      <span class="fld-name">我看好</span>
      <input class="v-a" value="${assetA}" placeholder="如 AMZN">
    </label>
    <label class="fld">
      <span class="fld-name">胜过</span>
      <input class="v-b" value="${assetB}" placeholder="如 JPM">
    </label>
    <label class="fld">
      <span class="fld-name">预期多涨</span>
      <span class="pct-wrap"><input class="v-q" type="number" step="0.1" value="${(q * 100).toFixed(1)}"> %</span>
    </label>
    <label class="fld">
      <span class="fld-name">把握程度</span>
      <select class="v-conf">
        <option value="0.8" ${selHigh}>很有把握</option>
        <option value="0.5" ${selMid}>比较有把握</option>
        <option value="0.3" ${selLow}>不太确定</option>
      </select>
    </label>
    <button class="btn-remove" title="删除这条看法">×</button>
  `;
  row.querySelector(".btn-remove").addEventListener("click", () => row.remove());
  $("viewsContainer").appendChild(row);
}

function collectViews() {
  return Array.from(document.querySelectorAll(".view-row")).map((row) => {
    const assetA = row.querySelector(".v-a").value.trim();
    const assetB = row.querySelector(".v-b").value.trim();
    if (!assetA && !assetB) return null;

    const legs = [];
    if (assetA) legs.push({ asset: assetA, weight: 1 });
    if (assetB) legs.push({ asset: assetB, weight: -1 });

    const qPct = Number(row.querySelector(".v-q").value) || 0;
    const confidence = Number(row.querySelector(".v-conf").value) || 0.5;

    return {
      name: (assetA || "?") + " vs " + (assetB || "?"),
      legs,
      q: qPct / 100,
      confidence,
    };
  }).filter(Boolean);
}

// ── 表单收集 ──

function collectPayload() {
  const assets = parseList($("inputAssets").value);
  if (assets.length < 2) throw new Error("至少需要输入 2 个标的。");

  const weightsText = $("inputWeights").value.trim();
  let marketWeights;
  if (weightsText) {
    marketWeights = parseNumbers(weightsText);
  } else {
    marketWeights = assets.map(() => 1 / assets.length);
  }
  if (marketWeights.length !== assets.length) {
    throw new Error("仓位数量（" + marketWeights.length + "）与标的数量（" + assets.length + "）不一致。");
  }

  const returnsText = $("inputReturns").value.trim();
  if (!returnsText) {
    throw new Error("请填入历史涨跌数据，或点击上方「加载示例数据」按钮自动填入真实数据。");
  }
  const returns = parseReturns(returnsText, assets.length);

  return {
    assets,
    market_weights: marketWeights,
    returns,
    views: collectViews(),
    tau: 0.3,
    periods_per_year: 52,
    risk_free_rate_annual: Number($("inputRf").value) || 0.0324,
    cov_shrinkage: 0.1,
    long_only: $("inputLongOnly").checked,
    min_weight: 0,
    max_weight: Number($("inputMaxWeight").value) || 0.35,
    turnover_limit: $("inputTurnoverLimit").value === "" ? null : Number($("inputTurnoverLimit").value),
    turnover_penalty: 0.001,
  };
}

// ── 计算与渲染 ──

async function runOptimization() {
  showLoading();
  $("btnCalc").disabled = true;
  try {
    const payload = collectPayload();
    const resp = await fetch("/api/optimize", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const result = await resp.json();
    if (!result.ok) throw new Error(result.error);
    renderResult(result.data);
  } catch (err) {
    $("statusBadge").textContent = "✗ " + err.message;
    $("statusBadge").className = "tag tag-err";
    $("cardResult").style.display = "";
    $("cardResult").scrollIntoView({ behavior: "smooth" });
  } finally {
    hideLoading();
    $("btnCalc").disabled = false;
  }
}

function renderResult(data) {
  state.lastResult = data;

  // 四大指标
  $("mAnnualReturn").textContent = fmtPct(data.metrics.expected_annual_return);
  $("mAnnualVol").textContent = fmtPct(data.metrics.expected_annual_vol);
  $("mSharpe").textContent = fmtNum(data.metrics.sharpe, 2);
  $("mTurnover").textContent = fmtPct(data.turnover);

  // 权重条形图
  const container = $("barChart");
  container.innerHTML = "";

  const items = data.assets
    .map((asset, i) => ({ asset, weight: data.weights[i], mkt: data.market_weights[i] }))
    .sort((a, b) => b.weight - a.weight);

  items.forEach((item) => {
    const pct = (item.weight * 100).toFixed(1);

    const wrap = document.createElement("div");
    wrap.className = "bar-item";

    const label = document.createElement("div");
    label.className = "bar-label";
    label.textContent = item.asset;
    label.title = item.asset;

    const track = document.createElement("div");
    track.className = "bar-track";

    const fill = document.createElement("div");
    fill.className = "bar-fill";
    if (item.weight < 0.08) fill.classList.add("light");
    fill.style.width = item.weight * 100 + "%";

    const span = document.createElement("span");
    span.textContent = pct + "%";
    fill.appendChild(span);

    track.appendChild(fill);
    wrap.appendChild(label);
    wrap.appendChild(track);
    container.appendChild(wrap);
  });

  // 简易表格
  const tbody = $("resultTable").querySelector("tbody");
  tbody.innerHTML = "";
  data.assets.forEach((asset, i) => {
    const tr = document.createElement("tr");
    const ret = data.posterior_returns[i];
    tr.innerHTML = `
      <td>${asset}</td>
      <td>${fmtPct(data.market_weights[i])}</td>
      <td class="col-suggest">${fmtPct(data.weights[i])}</td>
      <td class="${ret >= 0 ? "up" : "down"}">${fmtPct(ret)}</td>
    `;
    tbody.appendChild(tr);
  });

  $("statusBadge").textContent = "✓ 计算完成";
  $("statusBadge").className = "tag tag-ok";
  $("cardResult").style.display = "";
  $("cardResult").scrollIntoView({ behavior: "smooth" });
}

// ── 下载 ──

function downloadCsv() {
  if (!state.lastResult) return;
  const d = state.lastResult;
  const rows = [["标的", "当前仓位", "建议仓位", "预期涨跌"]];
  d.assets.forEach((asset, i) => {
    rows.push([asset, d.market_weights[i], d.weights[i], d.posterior_returns[i]]);
  });
  const csv = "﻿" + rows.map((r) => r.join(",")).join("\n");
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "投资组合方案.csv";
  a.click();
  URL.revokeObjectURL(a.href);
}

// ── 事件绑定 ──

$("btnCalc").addEventListener("click", runOptimization);
$("btnAddView").addEventListener("click", () => addViewRow());
$("btnDownload").addEventListener("click", downloadCsv);
$("btnPreset").addEventListener("click", () => loadSample());

$("btnToggleSettings").addEventListener("click", function () {
  state.settingsOpen = !state.settingsOpen;
  $("panelSettings").classList.toggle("open", state.settingsOpen);
  this.textContent = state.settingsOpen ? "▾ 收起设置" : "▸ 更多设置";
});

// ── 启动 ──
loadSample();
