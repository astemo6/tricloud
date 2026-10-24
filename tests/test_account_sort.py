"""自测：账号手动排序（sort_order）。
覆盖：默认顺序与旧行为一致（provider 分组、组内 id 序）、reorder 后列表顺序变化且持久、
非法 ids（缺失 / 多余 / 重复 / 空）返回 400、新账号未排序时按 id 兜底排在组内末尾、
前端包含拖拽与上移/下移接线。
全部用 mock，不连接任何真实云。"""
import os
import sys
import tempfile

D = tempfile.mkdtemp()
os.environ.update(TRICLOUD_DATA=D, PANEL_PASSWORD="devpassword123",
                  AWS_ACCESS_KEY_ID="testing", AWS_SECRET_ACCESS_KEY="testing", AWS_DEFAULT_REGION="us-east-1")
for k in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy", "FERNET_KEY"):
    os.environ.pop(k, None)
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
from unittest import mock

from fastapi.testclient import TestClient

from app import core, main
from app.providers.aws_provider import AWSProvider
from app.providers.oci_provider import OCIProvider

R = []


def ok(name, cond):
    R.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name)


mock.patch.object(OCIProvider, "__init__", lambda self, cred, region=None: setattr(self, "cred", cred)).start()
mock.patch.object(AWSProvider, "__init__", lambda self, cred, region=None: setattr(self, "cred", cred)).start()

with TestClient(main.app) as c:
    c.post("/api/login", json={"password": "devpassword123"})
    with mock.patch.object(OCIProvider, "test", return_value={"ok": True}):
        o1 = c.post("/api/accounts", json={"provider": "oci", "name": "oci-a", "cred": {
            "user": "u", "tenancy": "t", "fingerprint": "f", "region": "ap-tokyo-1", "key_content": "k"}}).json()["id"]
        o2 = c.post("/api/accounts", json={"provider": "oci", "name": "oci-b", "cred": {
            "user": "u", "tenancy": "t", "fingerprint": "f", "region": "ap-tokyo-1", "key_content": "k"}}).json()["id"]
    with mock.patch.object(AWSProvider, "test", return_value={"ok": True}):
        a1 = c.post("/api/accounts", json={"provider": "aws", "name": "aws-a", "cred": {
            "access_key": "AKIAFAKEFAKE1234", "secret_key": "s3cr3t-fake", "region": "us-east-1"}}).json()["id"]

    ids = [r["id"] for r in c.get("/api/accounts").json()]
    ok("default order = provider groups, id order inside (legacy)", ids == [a1, o1, o2])

    r = c.post("/api/accounts/reorder", json={"ids": [o2, o1, a1]})
    ok("reorder: 200 ok", r.status_code == 200 and r.json()["ok"])
    ids = [r["id"] for r in c.get("/api/accounts").json()]
    ok("reorder: within-group order applied (oci-b before oci-a), groups intact", ids == [a1, o2, o1])
    ok("reorder: sort_order persisted", [r["sort_order"] for r in core.list_accounts()] == [20, 0, 10])

    ok("reorder: missing id -> 400", c.post("/api/accounts/reorder", json={"ids": [o2, o1]}).status_code == 400)
    ok("reorder: unknown id -> 400", c.post("/api/accounts/reorder", json={"ids": [o2, o1, 99999]}).status_code == 400)
    ok("reorder: duplicate id -> 400", c.post("/api/accounts/reorder", json={"ids": [o2, o1, o1]}).status_code == 400)
    ok("reorder: empty -> 400", c.post("/api/accounts/reorder", json={"ids": []}).status_code == 400)
    ids = [r["id"] for r in c.get("/api/accounts").json()]
    ok("reorder: failed attempts leave order untouched", ids == [a1, o2, o1])

    with mock.patch.object(OCIProvider, "test", return_value={"ok": True}):
        o3 = c.post("/api/accounts", json={"provider": "oci", "name": "oci-c", "cred": {
            "user": "u", "tenancy": "t", "fingerprint": "f", "region": "ap-tokyo-1", "key_content": "k"}}).json()["id"]
    ids = [r["id"] for r in c.get("/api/accounts").json()]
    ok("new account (sort_order NULL) falls back to id, lands at group end", ids == [a1, o2, o1, o3])

# ---- 前端接线 ----
web = open(os.path.join(ROOT, "web/js/router.js"), encoding="utf-8").read()
ok("web: sidebar accounts draggable + drop posts reorder", 'draggable="true"' in web and 'a[data-acc]' in web and '"/accounts/reorder"' in web)
acc = open(os.path.join(ROOT, "web/js/accounts.js"), encoding="utf-8").read()
ok("web: accounts page has up/down move buttons", "data-up=" in acc and "data-dn=" in acc and "moveAcc" in acc)

bad = [n for n, v in R if not v]
print(f"\n{len(R) - len(bad)}/{len(R)} passed")
sys.exit(1 if bad else 0)
