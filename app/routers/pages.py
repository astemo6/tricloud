"""静态页：/ 与 /login（静态资源带内容哈希版本号防缓存）。"""
import hashlib
import json
import os
import re

from fastapi import APIRouter
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles

router = APIRouter()


WEB_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "web")
MODULE_DIR = "js"   # 前端 ES 模块目录（web/js/*.js）

_PAGE_CACHE = {}


def _hash(rel):
    with open(os.path.join(WEB_DIR, rel), "rb") as f:
        return hashlib.sha1(f.read()).hexdigest()[:10]


def _module_files():
    d = os.path.join(WEB_DIR, MODULE_DIR)
    return sorted(f"{MODULE_DIR}/{n}" for n in os.listdir(d) if n.endswith(".js")) if os.path.isdir(d) else []


def _stamp(name):
    """页面缓存失效依据：页面本身与所有前端模块的修改时间。"""
    files = [name] + _module_files()
    return tuple(os.path.getmtime(os.path.join(WEB_DIR, f)) for f in files) + (len(files),)


def _versioned_page(name):
    """给 /static/*.js|css 加内容哈希 ?v=，避免浏览器 / Cloudflare 缓存旧前端；页面本身不缓存。
    前端拆成 ES 模块后，模块之间的 import 也要带版本：在 <!-- tc:importmap --> 处生成 import map，
    把每个 /static/js/x.js 映射到 /static/js/x.js?v=内容哈希。"""
    path = os.path.join(WEB_DIR, name)
    mt = _stamp(name)
    hit = _PAGE_CACHE.get(name)
    if not hit or hit[0] != mt:
        html = open(path, encoding="utf-8").read()

        def _v(m):
            try:
                h = _hash(m.group(2))
            except OSError:
                return m.group(0)
            return f'{m.group(1)}/static/{m.group(2)}?v={h}"'
        html = re.sub(r'((?:src|href)=")/static/((?:[\w-]+/)?[\w.-]+\.(?:js|css))"', _v, html)
        if "<!-- tc:importmap -->" in html:
            imports = {f"/static/{f}": f"/static/{f}?v={_hash(f)}" for f in _module_files()}
            html = html.replace("<!-- tc:importmap -->",
                                '<script type="importmap">' + json.dumps({"imports": imports}, separators=(",", ":")) + "</script>")
        hit = _PAGE_CACHE[name] = (mt, html)
    return Response(hit[1], media_type="text/html; charset=utf-8", headers={"Cache-Control": "no-cache"})


class StaticWithModules(StaticFiles):
    """/static 静态文件。前端模块（/static/js/*）额外加 Cache-Control: no-cache：
    不支持 import map 的旧 WebView 拿到的是不带版本号的模块地址，每次都向服务器校验（ETag 未变则 304），不会用到旧模块。"""

    def file_response(self, full_path, stat_result, scope, status_code=200):
        resp = super().file_response(full_path, stat_result, scope, status_code)
        if os.path.relpath(full_path, self.directory).startswith(MODULE_DIR + os.sep):
            resp.headers["Cache-Control"] = "no-cache"
        return resp


@router.get("/")
def index():
    return _versioned_page("index.html")


@router.get("/login")
def login_page():
    return _versioned_page("login.html")
