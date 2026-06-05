/* ═════════════════════════════════════════════════════════════════════
   智投 —— 共享 JS 工具
   ═════════════════════════════════════════════════════════════════════ */

const $ = (id) => document.getElementById(id);

// ── 加载动画 ──
function showLoading(msg) {
  const mask = $("loadingMask");
  if (msg && mask.querySelector("span")) {
    mask.querySelector("span").textContent = msg;
  }
  mask.classList.add("show");
}
function hideLoading() {
  $("loadingMask").classList.remove("show");
}

// ── Toast 通知 ──
function showToast(message, type) {
  type = type || "info";
  const container = $("toastContainer");
  const el = document.createElement("div");
  el.className = "toast toast-" + type;
  el.textContent = message;
  container.appendChild(el);
  setTimeout(function () {
    el.style.opacity = "0";
    el.style.transition = "opacity .3s";
    setTimeout(function () { el.remove(); }, 300);
  }, 3000);
}

// ── API 封装 ──
async function apiGet(url) {
  const resp = await fetch(url);
  return resp.json();
}

async function apiPost(url, body) {
  const resp = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return resp.json();
}

async function apiUpload(url, formData) {
  const resp = await fetch(url, {
    method: "POST",
    body: formData,
  });
  return resp.json();
}

// ── 格式化 ──
function fmtPct(v) {
  if (!isFinite(v)) return "--";
  return (v >= 0 ? "+" : "") + (v * 100).toFixed(2) + "%";
}

function fmtNum(v, d) {
  d = d || 2;
  return isFinite(v) ? v.toFixed(d) : "--";
}

function fmtPrice(v) {
  if (!isFinite(v)) return "--";
  return v.toFixed(2);
}

// ── 文本解析 ──
function parseList(text) {
  return text.split(/[\n,，]+/).map(function (s) { return s.trim(); }).filter(Boolean);
}

function parseNumbers(text) {
  return parseList(text).map(Number);
}

// ── 暗色模式 ──
(function () {
  var saved = localStorage.getItem("theme");
  if (saved === "dark") {
    document.documentElement.setAttribute("data-theme", "dark");
  }

  var toggle = document.getElementById("themeToggle");
  if (toggle) {
    toggle.addEventListener("click", function () {
      var current = document.documentElement.getAttribute("data-theme");
      var next = current === "dark" ? "light" : "dark";
      document.documentElement.setAttribute("data-theme", next);
      localStorage.setItem("theme", next);
      var icon = toggle.querySelector(".theme-icon");
      if (icon) {
        icon.textContent = next === "dark" ? "☀️" : "🌙";
      }
    });

    // 初始化图标
    var icon = toggle.querySelector(".theme-icon");
    if (icon) {
      icon.textContent = (document.documentElement.getAttribute("data-theme") === "dark") ? "☀️" : "🌙";
    }
  }
})();

// ── 高亮当前导航链接 ──
(function () {
  var path = window.location.pathname;
  var links = document.querySelectorAll(".nav-link");
  links.forEach(function (link) {
    var href = link.getAttribute("href");
    if (href === path || (href !== "/" && path.startsWith(href))) {
      link.classList.add("active");
    }
  });
})();
