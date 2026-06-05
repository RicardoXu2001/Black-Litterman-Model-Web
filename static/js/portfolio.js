/* ═════════════════════════════════════════════════════════════════════
   投资组合页 —— 单次优化 + 滚动回测
   ═════════════════════════════════════════════════════════════════════ */

(function () {
  var state = {
    lastResult: null,
    lastBtResult: null,
    settingsOpen: false,
    mode: "optimize",
  };

  // ═══════════════════════════════════════════════════
  // 模式切换
  // ═══════════════════════════════════════════════════
  var modeTabs = document.querySelectorAll(".mode-tab");
  modeTabs.forEach(function (tab) {
    tab.addEventListener("click", function () {
      modeTabs.forEach(function (t) { t.classList.remove("active"); });
      tab.classList.add("active");
      state.mode = tab.dataset.mode;
      document.getElementById("panelOptimize").style.display = state.mode === "optimize" ? "" : "none";
      document.getElementById("panelBacktest").style.display = state.mode === "backtest" ? "" : "none";
    });
  });

  // ═══════════════════════════════════════════════════
  // 工具函数
  // ═══════════════════════════════════════════════════
  function parseReturns(text, cols) {
    var rows = text.trim().split(/\n+/).map(function (l) { return l.trim(); }).filter(Boolean);
    return rows.map(function (line) {
      var cells = line.split(/[,，\t]+/).map(Number);
      if (cells.length !== cols || cells.some(isNaN)) {
        throw new Error("历史数据每行需要 " + cols + " 个数字，与标的数量一致。");
      }
      return cells;
    });
  }

  // ═══════════════════════════════════════════════════
  // 单次优化：加载示例数据
  // ═══════════════════════════════════════════════════
  async function loadSample() {
    try {
      var resp = await apiGet("/api/sample");
      if (!resp.ok) throw new Error(resp.error);
      var d = resp.data;

      document.getElementById("inputAssets").value = d.assets.join(", ");
      document.getElementById("inputWeights").value = d.market_weights.map(function (v) { return v.toFixed(4); }).join(", ");
      document.getElementById("inputReturns").value = d.returns.map(function (r) { return r.join(", "); }).join("\n");
      document.getElementById("inputMaxWeight").value = d.max_weight;
      document.getElementById("inputTurnoverLimit").value = d.turnover_limit != null ? d.turnover_limit : "";
      document.getElementById("inputRf").value = d.risk_free_rate_annual;
      document.getElementById("inputLongOnly").checked = d.long_only;

      document.getElementById("viewsContainer").innerHTML = "";
      (d.views || []).forEach(function (v) { addViewRow(v); });
    } catch (err) {
      showToast("加载示例失败：" + err.message, "error");
    }
  }

  // ═══════════════════════════════════════════════════
  // 看法管理
  // ═══════════════════════════════════════════════════
  function addViewRow(view) {
    view = view || {};
    var assetA = "", assetB = "", q = 0.017, confidence = 0.8;
    if (view.legs && view.legs.length >= 2) {
      var pos = view.legs.find(function (l) { return l.weight > 0; });
      var neg = view.legs.find(function (l) { return l.weight < 0; });
      assetA = pos ? pos.asset : "";
      assetB = neg ? neg.asset : "";
    } else if (view.legs && view.legs.length === 1) {
      assetA = view.legs[0].asset;
    }
    if (view.q !== undefined) q = view.q;
    if (view.confidence !== undefined) confidence = view.confidence;

    var selHigh = confidence >= 0.7 ? "selected" : "";
    var selMid = confidence >= 0.4 && confidence < 0.7 ? "selected" : "";
    var selLow = confidence < 0.4 ? "selected" : "";

    var row = document.createElement("div");
    row.className = "view-row";
    row.innerHTML =
      '<label class="fld"><span class="fld-name">我看好</span><input class="v-a" value="' + assetA + '" placeholder="如 AMZN"></label>' +
      '<label class="fld"><span class="fld-name">胜过</span><input class="v-b" value="' + assetB + '" placeholder="如 JPM"></label>' +
      '<label class="fld"><span class="fld-name">预期多涨</span><span class="pct-wrap"><input class="v-q" type="number" step="0.1" value="' + (q * 100).toFixed(1) + '"> %</span></label>' +
      '<label class="fld"><span class="fld-name">把握程度</span><select class="v-conf">' +
        '<option value="0.8" ' + selHigh + '>很有把握</option>' +
        '<option value="0.5" ' + selMid + '>比较有把握</option>' +
        '<option value="0.3" ' + selLow + '>不太确定</option>' +
      '</select></label>' +
      '<button class="btn-remove" title="删除这条看法">&times;</button>';
    row.querySelector(".btn-remove").addEventListener("click", function () { row.remove(); });
    document.getElementById("viewsContainer").appendChild(row);
  }

  function collectViews() {
    return Array.from(document.querySelectorAll("#panelOptimize .view-row")).map(function (row) {
      var assetA = row.querySelector(".v-a").value.trim();
      var assetB = row.querySelector(".v-b").value.trim();
      if (!assetA && !assetB) return null;
      var legs = [];
      if (assetA) legs.push({ asset: assetA, weight: 1 });
      if (assetB) legs.push({ asset: assetB, weight: -1 });
      var qPct = Number(row.querySelector(".v-q").value) || 0;
      var confidence = Number(row.querySelector(".v-conf").value) || 0.5;
      return {
        name: (assetA || "?") + " vs " + (assetB || "?"),
        legs: legs,
        q: qPct / 100,
        confidence: confidence,
      };
    }).filter(Boolean);
  }

  // ═══════════════════════════════════════════════════
  // 表单收集
  // ═══════════════════════════════════════════════════
  function collectPayload() {
    var assets = parseList(document.getElementById("inputAssets").value);
    if (assets.length < 2) throw new Error("至少需要输入 2 个标的。");

    var weightsText = document.getElementById("inputWeights").value.trim();
    var marketWeights;
    if (weightsText) {
      marketWeights = parseNumbers(weightsText);
    } else {
      marketWeights = assets.map(function () { return 1 / assets.length; });
    }
    if (marketWeights.length !== assets.length) {
      throw new Error("仓位数量（" + marketWeights.length + "）与标的数量（" + assets.length + "）不一致。");
    }

    var returnsText = document.getElementById("inputReturns").value.trim();
    if (!returnsText) {
      throw new Error("请填入历史涨跌数据，或点击「加载示例数据」自动填入。");
    }
    var returns = parseReturns(returnsText, assets.length);

    var turnoverRaw = document.getElementById("inputTurnoverLimit").value.trim();
    var turnoverLimit = turnoverRaw === "" ? null : Number(turnoverRaw);

    return {
      assets: assets,
      market_weights: marketWeights,
      returns: returns,
      views: collectViews(),
      tau: 0.3,
      periods_per_year: 52,
      risk_free_rate_annual: Number(document.getElementById("inputRf").value) || 0.0324,
      cov_shrinkage: 0.1,
      long_only: document.getElementById("inputLongOnly").checked,
      min_weight: 0,
      max_weight: Number(document.getElementById("inputMaxWeight").value) || 0.35,
      turnover_limit: turnoverLimit,
      turnover_penalty: 0.001,
    };
  }

  // ═══════════════════════════════════════════════════
  // 单次优化：运行与渲染
  // ═══════════════════════════════════════════════════
  async function runOptimization() {
    showLoading("正在计算最优方案…");
    var btn = document.getElementById("btnCalc");
    btn.disabled = true;
    try {
      var payload = collectPayload();
      var result = await apiPost("/api/optimize", payload);
      if (!result.ok) throw new Error(result.error);
      renderOptimizeResult(result.data);
    } catch (err) {
      var badge = document.getElementById("statusBadge");
      badge.textContent = "✗ " + err.message;
      badge.className = "tag tag-err";
      document.getElementById("cardResult").style.display = "";
      document.getElementById("cardResult").scrollIntoView({ behavior: "smooth" });
    } finally {
      hideLoading();
      btn.disabled = false;
    }
  }

  function renderOptimizeResult(data) {
    state.lastResult = data;

    document.getElementById("mAnnualReturn").textContent = fmtPct(data.metrics.expected_annual_return);
    document.getElementById("mAnnualVol").textContent = fmtPct(data.metrics.expected_annual_vol);
    document.getElementById("mSharpe").textContent = fmtNum(data.metrics.sharpe, 2);
    document.getElementById("mTurnover").textContent = fmtPct(data.turnover);

    // 权重条形图
    var container = document.getElementById("barChart");
    container.innerHTML = "";
    var items = data.assets.map(function (asset, i) {
      return { asset: asset, weight: data.weights[i], mkt: data.market_weights[i] };
    }).sort(function (a, b) { return b.weight - a.weight; });

    items.forEach(function (item) {
      var pct = (item.weight * 100).toFixed(1);
      var wrap = document.createElement("div");
      wrap.className = "bar-item";

      var label = document.createElement("div");
      label.className = "bar-label";
      label.textContent = item.asset;
      label.title = item.asset;

      var track = document.createElement("div");
      track.className = "bar-track";
      var fill = document.createElement("div");
      fill.className = "bar-fill";
      if (item.weight < 0.08) fill.classList.add("light");
      fill.style.width = item.weight * 100 + "%";
      var span = document.createElement("span");
      span.textContent = pct + "%";
      fill.appendChild(span);
      track.appendChild(fill);

      wrap.appendChild(label);
      wrap.appendChild(track);
      container.appendChild(wrap);
    });

    // 表格
    var tbody = document.getElementById("resultTable").querySelector("tbody");
    tbody.innerHTML = "";
    data.assets.forEach(function (asset, i) {
      var tr = document.createElement("tr");
      var ret = data.posterior_returns[i];
      tr.innerHTML =
        "<td>" + asset + "</td>" +
        "<td>" + fmtPct(data.market_weights[i]) + "</td>" +
        "<td class='col-suggest'>" + fmtPct(data.weights[i]) + "</td>" +
        "<td class='" + (ret >= 0 ? "up" : "down") + "'>" + fmtPct(ret) + "</td>";
      tbody.appendChild(tr);
    });

    document.getElementById("statusBadge").textContent = "✓ 计算完成";
    document.getElementById("statusBadge").className = "tag tag-ok";
    document.getElementById("cardResult").style.display = "";
    document.getElementById("cardResult").scrollIntoView({ behavior: "smooth" });
  }

  // ═══════════════════════════════════════════════════
  // 下载 CSV
  // ═══════════════════════════════════════════════════
  function downloadCsv() {
    if (!state.lastResult) return;
    var d = state.lastResult;
    var rows = [["标的", "当前仓位", "建议仓位", "预期涨跌"]];
    d.assets.forEach(function (asset, i) {
      rows.push([asset, d.market_weights[i], d.weights[i], d.posterior_returns[i]]);
    });
    var csv = "﻿" + rows.map(function (r) { return r.join(","); }).join("\n");
    var blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
    var a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "投资组合方案.csv";
    a.click();
    URL.revokeObjectURL(a.href);
  }

  // ═══════════════════════════════════════════════════
  // 滚动回测
  // ═══════════════════════════════════════════════════
  async function runBacktest() {
    showLoading("正在运行滚动回测（这需要几秒钟）…");
    var btn = document.getElementById("btnBtRun");
    btn.disabled = true;
    try {
      var payload = {
        use_sample_data: true,
        start_idx: Number(document.getElementById("inputBtStart").value) || 273,
        end_idx: Number(document.getElementById("inputBtEnd").value) || 324,
        window_T: Number(document.getElementById("inputBtWindow").value) || 200,
        view_type: Number(document.getElementById("inputBtViewType").value) || 2,
        max_weight: Number(document.getElementById("inputBtMaxWeight").value) || 0.35,
        turnover_limit: Number(document.getElementById("inputBtTurnoverLimit").value) || 0.5,
      };
      var result = await apiPost("/api/backtest", payload);
      if (!result.ok) throw new Error(result.error);
      state.lastBtResult = result.data;
      renderBacktestResult(result.data);
    } catch (err) {
      showToast("回测失败：" + err.message, "error");
      var badge = document.getElementById("btStatusBadge");
      badge.textContent = "✗ " + err.message;
      badge.className = "tag tag-err";
    } finally {
      hideLoading();
      btn.disabled = false;
    }
  }

  function renderBacktestResult(data) {
    var s = data.summary;
    var d = data;

    document.getElementById("btGrossRet").textContent = fmtNum(s.gross_total_return, 4);
    document.getElementById("btNetRet").textContent = fmtNum(s.net_total_return, 4);
    document.getElementById("btEqRet").textContent = fmtNum(s.eq_total_return, 4);
    document.getElementById("btAvgTurnover").textContent = fmtPct(s.average_turnover);
    document.getElementById("btTotalCost").textContent = fmtNum(s.total_transaction_cost, 6);

    // Plotly 累计收益图
    var x = d.dates;
    var traceGross = { x: x, y: d.gross_accumulated_return, mode: "lines", name: "BL 毛收益", line: { color: "#e8453c", dash: "dash", width: 2 } };
    var traceNet = { x: x, y: d.net_accumulated_return, mode: "lines", name: "BL 净收益", line: { color: "#e8453c", width: 2.5 } };
    var traceEq = { x: x, y: d.equal_weight_accumulated_return, mode: "lines", name: "等权重收益", line: { color: "#366ef5", width: 2 } };

    var layout = {
      title: "累计对数收益对比",
      xaxis: { title: "周次" },
      yaxis: { title: "累计对数收益" },
      legend: { orientation: "h", y: -0.2 },
      margin: { t: 50, r: 20, b: 60, l: 60 },
      paper_bgcolor: "transparent",
      plot_bgcolor: "transparent",
      font: { family: "PingFang SC, Microsoft YaHei, sans-serif" },
    };

    Plotly.newPlot("btChartReturn", [traceGross, traceNet, traceEq], layout, { responsive: true, displayModeBar: false });

    // 权重热力表格
    var weights = d.weights_over_time;
    var assetNames = state.lastResult ? state.lastResult.assets : [];
    if (assetNames.length === 0 && weights.length > 0) {
      assetNames = weights[0].map(function (_, i) { return "资产" + (i + 1); });
    }

    var thead = document.querySelector("#btWeightTable thead");
    var tbody = document.querySelector("#btWeightTable tbody");
    thead.innerHTML = "";
    tbody.innerHTML = "";

    // 表头
    var trH = document.createElement("tr");
    var thIdx = document.createElement("th");
    thIdx.textContent = "期数";
    trH.appendChild(thIdx);
    assetNames.forEach(function (name) {
      var th = document.createElement("th");
      th.textContent = name;
      trH.appendChild(th);
    });
    thead.appendChild(trH);

    // 每隔 4 期显示一行（避免表格过长）
    var step = Math.max(1, Math.floor(weights.length / 20));
    for (var i = 0; i < weights.length; i += step) {
      var tr = document.createElement("tr");
      var tdIdx = document.createElement("td");
      tdIdx.textContent = (i + 1);
      tr.appendChild(tdIdx);
      weights[i].forEach(function (w) {
        var td = document.createElement("td");
        td.className = "weight-cell";
        td.textContent = (w * 100).toFixed(1) + "%";
        // 颜色深度
        var alpha = Math.min(w * 2, 1);
        td.style.backgroundColor = "rgba(232,69,60," + alpha.toFixed(2) + ")";
        td.style.color = alpha > 0.5 ? "#fff" : "var(--c-text)";
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    }

    document.getElementById("btStatusBadge").textContent = "✓ 回测完成";
    document.getElementById("btStatusBadge").className = "tag tag-ok";
    document.getElementById("cardBtResult").style.display = "";
    document.getElementById("cardBtResult").scrollIntoView({ behavior: "smooth" });
  }

  // ═══════════════════════════════════════════════════
  // 事件绑定
  // ═══════════════════════════════════════════════════
  document.getElementById("btnCalc").addEventListener("click", runOptimization);
  document.getElementById("btnAddView").addEventListener("click", function () { addViewRow(); });
  document.getElementById("btnDownload").addEventListener("click", downloadCsv);
  document.getElementById("btnPreset").addEventListener("click", function () { loadSample(); });
  document.getElementById("btnBtRun").addEventListener("click", runBacktest);
  document.getElementById("btnBtPreset").addEventListener("click", function () {
    document.getElementById("inputBtStart").value = "273";
    document.getElementById("inputBtEnd").value = "324";
    document.getElementById("inputBtWindow").value = "200";
    showToast("已加载默认回测参数", "info");
  });

  document.getElementById("btnToggleSettings").addEventListener("click", function () {
    state.settingsOpen = !state.settingsOpen;
    document.getElementById("panelSettings").classList.toggle("open", state.settingsOpen);
    this.textContent = state.settingsOpen ? "▾ 收起设置" : "▸ 高级设置";
  });

  // ═══════════════════════════════════════════════════
  // 启动：自动加载示例
  // ═══════════════════════════════════════════════════
  loadSample();
})();
