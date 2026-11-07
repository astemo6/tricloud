"""自测：2FA 开通接口附带二维码（SVG）。
POST /2fa/setup 在原有 secret/uri 之外返回 qr_svg（segno 生成），密钥不以明文出现在 SVG 里；
requirements 含 segno；前端弹窗引用 qr_svg 并带扫码文案（中英各一）。"""
import os
import sys
import tempfile

os.environ.update(TRICLOUD_DATA=tempfile.mkdtemp())
for k in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy", "FERNET_KEY"):
    os.environ.pop(k, None)
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)

from app import core
from app.routers.security import tfa_setup

core.init_db()
R = []


def ok(name, cond):
    R.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name)


r = tfa_setup()
ok("setup returns secret + otpauth uri", r["secret"] and r["uri"].startswith("otpauth://totp/TriCloud?secret=" + r["secret"]))
ok("pending secret stored for enable step", core.get_secret_setting("totp_pending") == r["secret"])
svg = r.get("qr_svg") or ""
ok("qr_svg present and is an svg", svg.lstrip().startswith("<svg") and len(svg) > 500)
ok("secret not leaked as text in svg", r["secret"] not in svg)
import base64 as _b64
png = _b64.b64decode(r.get("qr_png") or "")
ok("qr_png present and is a png (app)", png[:8] == b"\x89PNG\r\n\x1a\n" and len(png) > 300)

req = open(os.path.join(ROOT, "requirements.txt"), encoding="utf-8").read()
ok("requirements has segno", "segno" in req)
settings = open(os.path.join(ROOT, "web/js/settings.js"), encoding="utf-8").read()
ok("web: modal renders qr_svg with scan caption", "r.qr_svg" in settings and "set.totpScan" in settings)
i18n = open(os.path.join(ROOT, "web/js/i18n.js"), encoding="utf-8").read()
ok("i18n pair", i18n.count('"set.totpScan"') == 2)

import app.main  # noqa: F401
ok("app.main imports cleanly", True)

bad = [n for n, v in R if not v]
print(f"\n{len(R) - len(bad)}/{len(R)} passed")
sys.exit(1 if bad else 0)
