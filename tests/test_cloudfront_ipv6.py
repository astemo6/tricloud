"""CloudFront 源站 IP 类型（IPv6 回源）自测（moto，只测 provider 层，不连真实 AWS）。

覆盖：
a) cf_create(ip_address_type="ipv6") —— 提交给 AWS 的 CustomOriginConfig 带 IpAddressType=ipv6；
b) cf_create 不传新参 —— 提交体 IpAddressType=ipv4（默认值显式下发，向后兼容），get_config 回显 ipv4；
c) cf_create / cf_update 传非法值 "ipv5" 抛 ValueError；
d) cf_update 改 ip_address_type 能写进待提交配置（dualstack、ipv6 各一次，双向可改）；
e) 往返不丢（核心回归）：伪造 get_distribution_config 返回一份 IpAddressType=ipv6 的配置，
   cf_update 只改 comment，断言最终提交给 update_distribution 的配置里 IpAddressType 仍是 ipv6，
   且 cf_get_config 对这份配置回显 ipv6
   （旧 botocore 模型不认此字段时，get→update 往返会把它悄悄丢掉、源站被冲回 ipv4）。

注：moto 的 CloudFront 实现不保存/不回读 IpAddressType（回读时该字段消失），
故涉及该字段的断言都放在拦截到的提交体与伪造配置上，不依赖 moto 回读——同
test_cloudfront_ports_ws.py 对 TTL 字段的处理。
"""
import copy
import os
import sys
import types

os.environ.update(AWS_ACCESS_KEY_ID="testing", AWS_SECRET_ACCESS_KEY="testing", AWS_DEFAULT_REGION="us-east-1")
for k in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy"):
    os.environ.pop(k, None)
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)

from moto import mock_aws  # noqa: E402

from app.providers.aws_provider import AWSProvider  # noqa: E402

R = []


def ok(name, cond):
    R.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name)


def coc_of(cfg):
    return cfg["Origins"]["Items"][0]["CustomOriginConfig"]


with mock_aws():
    p = AWSProvider({"access_key": "testing", "secret_key": "testing", "region": "us-east-1"})

    # 拦截 create/update 的提交体（moto 回读不保留 IpAddressType，断言看提交体）
    real_client = p._cf()
    submitted_create, submitted_update = {}, {}
    real_create, real_update = real_client.create_distribution, real_client.update_distribution

    def spy_create(**kw):
        submitted_create.clear()
        submitted_create.update(kw)
        return real_create(**kw)

    def spy_update(**kw):
        submitted_update.clear()
        submitted_update.update(kw)
        return real_update(**kw)

    real_client.create_distribution = spy_create
    real_client.update_distribution = spy_update
    orig_cf = p._cf
    p._cf = lambda: real_client
    try:
        # a) ipv6 新建
        r = p.cf_create("v6.example.com", comment="v6 node", ip_address_type="ipv6")
        ok("a: cf_create submits IpAddressType=ipv6",
           coc_of(submitted_create["DistributionConfig"]).get("IpAddressType") == "ipv6")

        # b) 默认 ipv4 + get_config 回显（moto 里无此字段时按缺省 ipv4 回显）
        r2 = p.cf_create("plain.example.com")
        ok("b: default create submits IpAddressType=ipv4",
           coc_of(submitted_create["DistributionConfig"]).get("IpAddressType") == "ipv4")
        ok("b: cf_get_config echoes default ipv4", p.cf_get_config(r2["id"])["ip_address_type"] == "ipv4")

        # c) 非法值
        try:
            p.cf_create("bad.example.com", ip_address_type="ipv5")
            ok("c: cf_create ip_address_type='ipv5' raises ValueError", False)
        except ValueError:
            ok("c: cf_create ip_address_type='ipv5' raises ValueError", True)
        try:
            p.cf_update(r["id"], {"ip_address_type": "ipv5"})
            ok("c: cf_update ip_address_type='ipv5' raises ValueError", False)
        except ValueError:
            ok("c: cf_update ip_address_type='ipv5' raises ValueError", True)

        # d) cf_update 双向可改：ipv4 -> dualstack -> ipv6，看提交体
        p.cf_update(r2["id"], {"ip_address_type": "dualstack"})
        ok("d: cf_update submits dualstack",
           coc_of(submitted_update["DistributionConfig"]).get("IpAddressType") == "dualstack")
        p.cf_update(r2["id"], {"ip_address_type": "ipv6"})
        ok("d: cf_update then submits ipv6",
           coc_of(submitted_update["DistributionConfig"]).get("IpAddressType") == "ipv6")
    finally:
        p._cf = orig_cf

    # e) 往返不丢：伪造一份 IpAddressType=ipv6 的 get_distribution_config 返回，
    #    cf_update 只改 comment，提交体里必须原样保留 ipv6
    canned_cfg = {
        "CallerReference": "roundtrip-v6", "Comment": "before", "Enabled": True,
        "Origins": {"Quantity": 1, "Items": [{
            "Id": "origin-1", "DomainName": "v6only.example.com", "OriginPath": "",
            "CustomHeaders": {"Quantity": 0},
            "CustomOriginConfig": {"HTTPPort": 80, "HTTPSPort": 443,
                                   "OriginProtocolPolicy": "https-only",
                                   "OriginSslProtocols": {"Quantity": 1, "Items": ["TLSv1.2"]},
                                   "OriginReadTimeout": 30, "OriginKeepaliveTimeout": 5,
                                   "IpAddressType": "ipv6"},
            "ConnectionAttempts": 3, "ConnectionTimeout": 10,
        }]},
        "DefaultCacheBehavior": {
            "TargetOriginId": "origin-1", "ViewerProtocolPolicy": "allow-all",
            "CachePolicyId": "4135ea2d-6df8-44a3-9df3-4b5a84be39ad",
            "OriginRequestPolicyId": "216adef6-5c7f-47e4-b989-5492eafa07d3",
            "AllowedMethods": {"Quantity": 2, "Items": ["GET", "HEAD"],
                               "CachedMethods": {"Quantity": 2, "Items": ["GET", "HEAD"]}},
            "Compress": False, "TrustedSigners": {"Enabled": False, "Quantity": 0},
        },
        "PriceClass": "PriceClass_All", "HttpVersion": "http2and3",
        "DefaultRootObject": "", "Aliases": {"Quantity": 0}, "WebACLId": "",
    }
    rt_update = {}

    def fake_get(**kw):
        return {"DistributionConfig": copy.deepcopy(canned_cfg), "ETag": "ETAG-ROUNDTRIP"}

    def fake_update(**kw):
        rt_update.update(kw)
        return {}

    fake_cf = types.SimpleNamespace(get_distribution_config=fake_get,
                                    update_distribution=fake_update,
                                    exceptions=real_client.exceptions)
    p._cf = lambda: fake_cf
    try:
        out = p.cf_update("EFAKEV6", {"comment": "仅改备注"})
        echo = p.cf_get_config("EFAKEV6")["ip_address_type"]
    finally:
        p._cf = orig_cf
    ok("e: cf_get_config on v6 config echoes ipv6", echo == "ipv6")
    ok("e: comment-only update reports only 备注 changed", out["changed"] == ["备注"])
    ok("e: round-trip keeps IpAddressType=ipv6 in submitted config",
       coc_of(rt_update["DistributionConfig"]).get("IpAddressType") == "ipv6")

print(f"\n{sum(x[1] for x in R)}/{len(R)} passed")
sys.exit(0 if all(x[1] for x in R) else 1)
