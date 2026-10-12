# 生成单文件演示页 demo/index.html（mock + theme + style + 登录覆盖层 + app）
import re, pathlib
W = pathlib.Path(__file__).resolve().parent.parent / "web"
D = pathlib.Path(__file__).resolve().parent
mock = (D / "mock.js").read_text(); theme = (W / "theme.js").read_text(); css = (W / "style.css").read_text()
app = (W / "app.js").read_text().replace('location.href = "/login"', 'TCDemo.toLogin()')
body = re.search(r"<body>(.*)<script src=\"/static/app.js\"></script>", (W / "index.html").read_text(), re.S).group(1)
login = '''<div id="demoLogin" class="login-wrap" style="position:fixed;inset:0;z-index:60;background:var(--bg)">
  <div class="card login" id="lf">
    <h3 class="brand">Tri<span>Cloud</span> 面板</h3>
    <div class="muted">OCI · AWS · Azure 三合一管理 · 演示 v1.6.0</div>
    <label>面板密码</label>
    <div class="pw-wrap"><input type="password" class="pw-in" id="lpw" autocomplete="current-password" placeholder="演示模式：任意密码"><button type="button" class="pw-eye" aria-label="显示密码" title="显示密码" onclick="var i=this.previousElementSibling,s=i.type==='password';i.type=s?'text':'password';this.textContent=s?'🙈':'👁';this.title=this.ariaLabel=s?'隐藏密码':'显示密码';i.focus()">👁</button></div>
    <div id="otpBox" style="display:none"><label>二次验证码（6 位）</label>
    <input id="otp" inputmode="numeric" autocomplete="one-time-code" maxlength="6" placeholder="演示：任意 6 位数字"></div>
    <div id="lmsg" class="muted" style="color:var(--bad);min-height:20px;margin-top:8px"></div>
    <button type="button" class="btn primary" id="lbtn">登录</button>
  </div>
</div>'''
glue = '''<script>
window.TCDemo = { toLogin: function () { var l = document.getElementById("demoLogin"); l.style.display = ""; document.getElementById("otpBox").style.display = "none"; document.getElementById("lpw").value = ""; document.getElementById("otp").value = ""; } };
// 演示页运行在没有 allow-forms 的沙箱 iframe 里，表单提交会被浏览器直接拦截，所以登录不用表单元素
async function demoLogin() {
  var r = await fetch("/api/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ password: document.getElementById("lpw").value, otp: document.getElementById("otp").value }) });
  if (r.ok) { document.getElementById("demoLogin").style.display = "none"; document.getElementById("lmsg").textContent = ""; return; }
  var j = await r.json().catch(function () { return {}; });
  if (j.detail === "需要二次验证码") { document.getElementById("otpBox").style.display = ""; document.getElementById("otp").focus(); document.getElementById("lmsg").textContent = "已开启二次验证，请输入验证码"; return; }
  document.getElementById("lmsg").textContent = j.detail || "登录失败";
}
document.getElementById("lbtn").onclick = demoLogin;
["lpw", "otp"].forEach(function (id) { document.getElementById(id).addEventListener("keydown", function (e) { if (e.key === "Enter") { e.preventDefault(); demoLogin(); } }); });
</script>'''
html = f'''<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#f8fafd">
<title>TriCloud 面板演示 v1.6.0</title>
<script>{mock}</script>
<script>{theme}</script>
<style>{css}</style>
</head>
<body>
<div class="demo-banner">演示模式 · v1.6.0 · 全部为模拟数据，操作只改内存</div>
{body}
{login}
<script>{app}</script>
{glue}
</body>
</html>
'''
(D / "index.html").write_text(html)
print(len(html))
