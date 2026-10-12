// 配色：dark / light / system，localStorage 持久化（FR-07）。登录页与主页共用，尽早执行避免闪烁。
(function () {
  var KEY = "tc_theme";
  var mq = window.matchMedia("(prefers-color-scheme: dark)");
  function apply(mode) {
    var m = mode || localStorage.getItem(KEY) || "system";
    var dark = m === "dark" || (m === "system" && mq.matches);
    document.documentElement.setAttribute("data-theme", dark ? "dark" : "light");
  }
  window.TCTheme = {
    get: function () { return localStorage.getItem(KEY) || "system"; },
    set: function (m) { localStorage.setItem(KEY, m); apply(m); },
    apply: apply,
  };
  mq.addEventListener && mq.addEventListener("change", function () { apply(); });
  window.addEventListener("storage", function (e) { if (e.key === KEY) apply(); });
  apply();
})();
