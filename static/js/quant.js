/* ═════════════════════════════════════════════════════════════════════
   量化分析页 —— Markov + ARIMA 分析
   ═════════════════════════════════════════════════════════════════════ */

(function () {
  var state = {
    quantData: null,
    lastResult: null,
  };

  // ═══════════════════════════════════════════════════
  // 文件上传
  // ═══════════════════════════════════════════════════
  var uploadZone = document.getElementById("uploadZone");
  var uploadFile = document.getElementById("uploadFile");

  uploadZone.addEventListener("click", function () { uploadFile.click(); });
  uploadZone.addEventListener("dragover", function (e) {
    e.preventDefault();
    uploadZone.classList.add("drag-over");
  });
  uploadZone.addEventListener("dragleave", function () {
    uploadZone.classList.remove("drag-over");
  });
  uploadZone.addEventListener("drop", function (e) {
    e.preventDefault();
    uploadZone.classList.remove("drag-over");
    var file = e.dataTransfer.files[0];
    if (file) handleFile(file);
  });
  uploadFile.addEventListener("change", function () {
    var file = uploadFile.files[0];
    if (file) handleFile(file);
  });

  function handleFile(file) {
    if (!file.name.endsWith(".csv")) {
      showToast("请上传 CSV 格式的文件", "error");
      return;
    }
    var reader = new FileReader();
    reader.onload = function (e) {
      try {
        var text = e.target.result;
        var lines = text.trim().split(/\n+/);
        if (lines.length < 2) throw new Error("数据太少");
        var rawData = [];
        for (var i = 1; i < lines.length; i++) {
          var cols = lines[i].split(/[,，\t]+/);
          if (cols.length >= 2) {
            var dStr = cols[0].trim();
            var pVal = parseFloat(cols[1]);
            if (dStr && !isNaN(pVal)) {
              rawData.push({ date: dStr, price: pVal });
            }
          }
        }
        if (rawData.length < 20) throw new Error("至少需要 20 条有效数据");

        // 强制按时间升序排列（解决时间序列逆序问题）
        rawData.sort(function (a, b) {
          return new Date(a.date) - new Date(b.date);
        });

        var dates = rawData.map(function (item) { return item.date; });
        var prices = rawData.map(function (item) { return item.price; });

        state.quantData = { dates: dates, prices: prices };
        showPreview(dates, prices);
        showToast("已成功加载并按日期升序排列 " + prices.length + " 条数据", "success");
      } catch (err) {
        showToast("文件解析失败：" + err.message, "error");
      }
    };
    reader.readAsText(file);
  }

  function showPreview(dates, prices) {
    document.getElementById("dataPreview").style.display = "";
    document.getElementById("previewTotal").textContent = prices.length;
    var tbody = document.querySelector("#previewTable tbody");
    tbody.innerHTML = "";
    var start = Math.max(0, prices.length - 10);
    for (var i = start; i < prices.length; i++) {
      var tr = document.createElement("tr");
      tr.innerHTML = "<td>" + dates[i] + "</td><td>" + prices[i].toFixed(2) + "</td>";
      tbody.appendChild(tr);
    }
  }

  // ═══════════════════════════════════════════════════
  // 加载示例数据
  // ═══════════════════════════════════════════════════
  document.getElementById("btnQuantSample").addEventListener("click", async function () {
    try {
      showLoading("正在加载示例数据…");
      var resp = await apiGet("/api/quant/sample");
      hideLoading();
      if (!resp.ok) throw new Error(resp.error);
      state.quantData = resp.data;
      showPreview(state.quantData.dates, state.quantData.prices);
      showToast("已加载 Apple 示例数据（" + state.quantData.prices.length + " 条）", "success");
    } catch (err) {
      hideLoading();
      showToast("加载失败：" + err.message, "error");
    }
  });

  // ═══════════════════════════════════════════════════
  // 运行分析
  // ═══════════════════════════════════════════════════
  document.getElementById("btnQuantRun").addEventListener("click", async function () {
    if (!state.quantData) {
      showToast("请先上传数据或加载示例数据", "error");
      return;
    }

    var btn = document.getElementById("btnQuantRun");
    btn.disabled = true;
    showLoading("正在分析数据…");

    try {
      var payload = {
        prices: state.quantData.prices,
        dates: state.quantData.dates,
        arima_order: [
          Number(document.getElementById("inputP").value) || 2,
          Number(document.getElementById("inputD").value) || 1,
          Number(document.getElementById("inputQ").value) || 2,
        ],
        markov_states: Number(document.getElementById("inputMarkovStates").value) || 3,
        forecast_steps: Number(document.getElementById("inputForecastSteps").value) || 12,
      };

      var result = await apiPost("/api/quant/analyze", payload);
      if (!result.ok) throw new Error(result.error);
      state.lastResult = result.data;
      renderQuantResult(result.data);
    } catch (err) {
      showToast("分析失败：" + err.message, "error");
      document.getElementById("quantStatusBadge").textContent = "✗ " + err.message;
      document.getElementById("quantStatusBadge").className = "tag tag-err";
      document.getElementById("cardQuantResult").style.display = "";
    } finally {
      hideLoading();
      btn.disabled = false;
    }
  });

  // ═══════════════════════════════════════════════════
  // 渲染结果
  // ═══════════════════════════════════════════════════
  function renderQuantResult(data) {
    // 指标
    document.getElementById("qTotalRet").textContent = fmtPct(data.metrics.total_return);
    document.getElementById("qAnnRet").textContent = fmtPct(data.metrics.annualized_return);
    document.getElementById("qAnnVol").textContent = fmtPct(data.metrics.annualized_volatility);
    document.getElementById("qSharpe").textContent = fmtNum(data.metrics.sharpe_ratio, 2);
    document.getElementById("qAic").textContent = fmtNum(data.forecast.aic, 1);
    document.getElementById("qBic").textContent = fmtNum(data.forecast.bic, 1);
    var fc = data.forecast.forecast;
    document.getElementById("qFinalPrice").textContent = fc.length > 0 ? fmtPrice(fc[fc.length - 1]) : "--";

    // 市场状态图（ECharts）
    renderRegimeChart(data);
    // 转移矩阵
    renderTransitionMatrix(data);
    // 状态统计
    renderStateStats(data);
    // 预测图（ECharts）
    renderForecastChart(data);

    document.getElementById("quantStatusBadge").textContent = "✓ 分析完成";
    document.getElementById("quantStatusBadge").className = "tag tag-ok";
    document.getElementById("cardQuantResult").style.display = "";
    document.getElementById("cardQuantResult").scrollIntoView({ behavior: "smooth" });
  }

  function renderRegimeChart(data) {
    var container = document.getElementById("chartRegime");
    // 销毁旧图表实例，避免重复 init 和 resize 监听器堆积
    if (container._echartInstance) {
      container._echartInstance.dispose();
    }
    var chart = echarts.init(container);
    container._echartInstance = chart;

    var prices = data.prices;
    var regimes = data.regimes;   // 长度 = prices.length - 1
    var xData = data.dates || [];

    // 构建 markArea：regime[i] 表示从 price[i] 到 price[i+1] 之间的市场状态
    // markArea 的 xAxis 坐标：区间 [areaStart, i] 对应 regimes[areaStart..i-1]
    var markAreas = [];
    var currentRegime = regimes[0];
    var areaStart = 0;
    for (var i = 1; i <= regimes.length; i++) {
      if (i === regimes.length || regimes[i] !== currentRegime) {
        var color = currentRegime === "bull" ? "rgba(43,164,113,0.15)"
          : currentRegime === "bear" ? "rgba(232,69,60,0.12)"
          : "rgba(227,151,14,0.1)";
        markAreas.push([
          { xAxis: areaStart, itemStyle: { color: color } },
          { xAxis: i },
        ]);
        if (i < regimes.length) {
          currentRegime = regimes[i];
          areaStart = i;
        }
      }
    }

    var option = {
      tooltip: { trigger: "axis" },
      grid: { left: 60, right: 20, top: 20, bottom: 50 },
      xAxis: { type: "category", data: xData, name: "日期", axisLabel: { show: true } },
      yAxis: { type: "value", name: "价格", scale: true },
      textStyle: { fontFamily: "PingFang SC, Microsoft YaHei, sans-serif" },
      series: [{
        type: "line",
        data: prices,
        smooth: true,
        lineStyle: { color: "#366ef5", width: 2 },
        itemStyle: { color: "#366ef5" },
        markArea: {
          silent: true,
          label: { show: true, position: "insideTop", fontSize: 11 },
          data: markAreas,
        },
      }],
    };
    chart.setOption(option);

    // 使用具名函数避免重复绑定
    if (!container._resizeHandler) {
      container._resizeHandler = function () { chart.resize(); };
      window.addEventListener("resize", container._resizeHandler);
    }
  }

  function renderTransitionMatrix(data) {
    var matrix = data.transition_matrix;
    var labels = data.state_labels;
    if (!matrix || matrix.length === 0) return;

    var thead = document.querySelector("#transMatrixTable thead");
    var tbody = document.querySelector("#transMatrixTable tbody");
    thead.innerHTML = "";
    tbody.innerHTML = "";

    var trH = document.createElement("tr");
    trH.innerHTML = "<th>从 \\ 到</th>" + labels.map(function (l) { return "<th>" + l + "</th>"; }).join("");
    thead.appendChild(trH);

    for (var i = 0; i < matrix.length; i++) {
      var tr = document.createElement("tr");
      var h = labels[i] || ("状态" + i);
      tr.innerHTML = "<td><strong>" + h + "</strong></td>" + matrix[i].map(function (v) {
        return "<td>" + (v * 100).toFixed(1) + "%</td>";
      }).join("");
      tbody.appendChild(tr);
    }
  }

  function renderStateStats(data) {
    var tbody = document.querySelector("#stateStatsTable tbody");
    tbody.innerHTML = "";
    var labels = data.state_labels;
    var means = data.state_means || {};
    var dist = data.state_distribution || {};

    var cnNames = { bull: "🟢 牛市", bear: "🔴 熊市", sideways: "🟡 震荡" };
    labels.forEach(function (label) {
      var tr = document.createElement("tr");
      var meanVal = means[label] !== undefined ? fmtPct(means[label]) : "--";
      var distVal = dist[label] !== undefined ? fmtPct(dist[label]) : "--";
      tr.innerHTML = "<td><strong>" + (cnNames[label] || label) + "</strong></td>" +
        "<td>" + meanVal + "</td><td>" + distVal + "</td>";
      tbody.appendChild(tr);
    });
  }

  function renderForecastChart(data) {
    var container = document.getElementById("chartForecast");
    // 销毁旧图表实例
    if (container._echartInstance2) {
      container._echartInstance2.dispose();
    }
    var chart = echarts.init(container);
    container._echartInstance2 = chart;

    var prices = data.prices;
    var fc = data.forecast;
    var nHist = prices.length;
    var histX = data.dates || [];
    var fcX = fc.dates || [];

    var option = {
      tooltip: { trigger: "axis" },
      legend: { data: ["历史价格", "预测", "置信上界", "置信下界"], bottom: 0 },
      grid: { left: 60, right: 20, top: 20, bottom: 50 },
      xAxis: { type: "category", data: histX.concat(fcX), name: "日期", axisLabel: { show: true } },
      yAxis: { type: "value", name: "价格", scale: true },
      textStyle: { fontFamily: "PingFang SC, Microsoft YaHei, sans-serif" },
      series: [
        {
          name: "历史价格", type: "line", data: prices,
          lineStyle: { color: "#366ef5", width: 2.5 },
          itemStyle: { color: "#366ef5" },
        },
        {
          name: "预测", type: "line",
          data: (function () {
            var arr = new Array(nHist);
            for (var i = 0; i < fc.forecast.length; i++) { arr.push(fc.forecast[i]); }
            return arr;
          })(),
          lineStyle: { color: "#e8453c", width: 2.5, type: "dashed" },
          itemStyle: { color: "#e8453c" },
          connectNulls: false,
        },
        {
          name: "置信上界", type: "line",
          data: (function () {
            var arr = new Array(nHist);
            for (var i = 0; i < fc.upper_bound.length; i++) { arr.push(fc.upper_bound[i]); }
            return arr;
          })(),
          lineStyle: { color: "rgba(232,69,60,0.3)", width: 1, type: "dotted" },
          showSymbol: false,
        },
        {
          name: "置信下界", type: "line",
          data: (function () {
            var arr = new Array(nHist);
            for (var i = 0; i < fc.lower_bound.length; i++) { arr.push(fc.lower_bound[i]); }
            return arr;
          })(),
          lineStyle: { color: "rgba(232,69,60,0.3)", width: 1, type: "dotted" },
          areaStyle: { color: "rgba(232,69,60,0.08)" },
          showSymbol: false,
        },
      ],
    };
    chart.setOption(option);

    if (!container._resizeHandler2) {
      container._resizeHandler2 = function () { chart.resize(); };
      window.addEventListener("resize", container._resizeHandler2);
    }
  }
})();
