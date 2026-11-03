"""CloudFront 回源端口分开 + WebSocket 节点模式自测（moto，只测 provider 层，不连真实 AWS）。

覆盖：
a) cf_create(http_port=8080, https_port=39955, ws_mode=True) 且故意传 cache_mode="optimized"、
   compress=True —— ws_mode 应强制 CachingDisabled + AllViewer + Compress=False，端口按填入值生效；
b) cf_create 不传新参时仍是 80/443（向后兼容）；
c) http_port=888 抛 ValueError；
d) cf_get_config 回显 http_port/https_port/ws_mode 与 a) 一致；cf_update 改 https_port 到 8443 生效。
"""
import os
import sys

os.environ.update(AWS_ACCESS_KEY_ID="testing", AWS_SECRET_ACCESS_KEY="testing", AWS_DEFAULT_REGION="us-east-1")
for k in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy"):
    os.environ.pop(k, None)
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)

from moto import mock_aws  # noqa: E402

from app.providers.aws_provider import AWSProvider  # noqa: E402

CACHING_DISABLED = "4135ea2d-6df8-44a3-9df3-4b5a84be39ad"
ALL_VIEWER = "216adef6-5c7f-47e4-b989-5492eafa07d3"

R = []


def ok(name, cond):
    R.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name)


def dist_cfg(p, dist_id):
    return p._cf().get_distribution_config(Id=dist_id)["DistributionConfig"]


with mock_aws():
    p = AWSProvider({"access_key": "testing", "secret_key": "testing", "region": "us-east-1"})

    # a) 自定义端口 + ws 模式（故意传 optimized/True 验证强制覆盖）
    r = p.cf_create("node.example.com", comment="ws node", http_port=8080, https_port=39955,
                    ws_mode=True, cache_mode="optimized", compress=True)
    cfg = dist_cfg(p, r["id"])
    coc = cfg["Origins"]["Items"][0]["CustomOriginConfig"]
    dcb = cfg["DefaultCacheBehavior"]
    ok("a: custom origin ports applied", coc["HTTPPort"] == 8080 and coc["HTTPSPort"] == 39955)
    ok("a: ws_mode forces CachingDisabled + AllViewer + Compress=False",
       dcb["CachePolicyId"] == CACHING_DISABLED and dcb["OriginRequestPolicyId"] == ALL_VIEWER
       and dcb["Compress"] is False)

    # d-1) get_config 回显
    g = p.cf_get_config(r["id"])
    ok("d: cf_get_config echoes ports + ws_mode",
       g["http_port"] == 8080 and g["https_port"] == 39955 and g["ws_mode"] is True)

    # d-2) update 改 https_port
    p.cf_update(r["id"], {"https_port": 8443})
    coc2 = dist_cfg(p, r["id"])["Origins"]["Items"][0]["CustomOriginConfig"]
    ok("d: cf_update changes https_port to 8443", coc2["HTTPSPort"] == 8443 and coc2["HTTPPort"] == 8080)

    # b) 不传新参向后兼容
    r2 = p.cf_create("plain.example.com")
    coc3 = dist_cfg(p, r2["id"])["Origins"]["Items"][0]["CustomOriginConfig"]
    ok("b: default ports stay 80/443", coc3["HTTPPort"] == 80 and coc3["HTTPSPort"] == 443)
    ok("b: default get_config ws_mode is True (panel default = disabled cache + AllViewer)",
       p.cf_get_config(r2["id"])["ws_mode"] is True)

    # c) 非法端口
    try:
        p.cf_create("bad.example.com", http_port=888)
        ok("c: http_port=888 raises ValueError", False)
    except ValueError:
        ok("c: http_port=888 raises ValueError", True)
    try:
        p.cf_update(r["id"], {"http_port": "abc"})
        ok("c: cf_update http_port='abc' raises ValueError", False)
    except ValueError:
        ok("c: cf_update http_port='abc' raises ValueError", True)

print(f"\n{sum(x[1] for x in R)}/{len(R)} passed")
sys.exit(0 if all(x[1] for x in R) else 1)
