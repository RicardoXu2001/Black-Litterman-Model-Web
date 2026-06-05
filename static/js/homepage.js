/* ═════════════════════════════════════════════════════════════════════
   首页 —— 滚动动画
   ═════════════════════════════════════════════════════════════════════ */

(function () {
  // 为需要动画的元素添加 fade-in 类
  var targets = document.querySelectorAll(".feature-card, .step-item");
  targets.forEach(function (el, i) {
    el.classList.add("fade-in");
    el.style.transitionDelay = (i * 0.1) + "s";
  });

  var observer = new IntersectionObserver(function (entries) {
    entries.forEach(function (entry) {
      if (entry.isIntersecting) {
        entry.target.classList.add("visible");
        observer.unobserve(entry.target);
      }
    });
  }, { threshold: 0.15 });

  targets.forEach(function (el) { observer.observe(el); });

  // 卡片点击涟漪效果
  document.querySelectorAll(".feature-card").forEach(function (card) {
    card.addEventListener("click", function (e) {
      var ripple = document.createElement("span");
      ripple.style.cssText =
        "position:absolute;border-radius:50%;background:rgba(232,69,60,.15);" +
        "width:20px;height:20px;left:" + (e.clientX - card.getBoundingClientRect().left - 10) + "px;" +
        "top:" + (e.clientY - card.getBoundingClientRect().top - 10) + "px;" +
        "animation:ripple .6s ease-out;pointer-events:none;";
      card.appendChild(ripple);
      setTimeout(function () { ripple.remove(); }, 600);
    });
  });

  // ripple keyframe
  var style = document.createElement("style");
  style.textContent =
    "@keyframes ripple { to { transform: scale(30); opacity: 0; } }";
  document.head.appendChild(style);
})();
