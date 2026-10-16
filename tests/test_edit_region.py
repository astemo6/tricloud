"""账号编辑的区域字段：Azure 没有默认区域，编辑不回显、不要求；OCI / AWS 空区域仍报错。全部 mock，不连接真实云。"""
import json
import os
import sys
import tempfile

D = tempfile.mkdtemp()
os.environ.update(TRICLOUD_DATA=D, PANEL_PASSWORD="devpassword123")
for k in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy", "FERNET_KEY"):
    os.environ.pop(k, None)
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
import asyncio
from unittest import mock

from fastapi.testclient import TestClient

from app import core, main, tasks, telegram
from app.providers.aws_provider import AWSProvider
from app.providers.azure_provider import AzureProvider
from app.providers.oci_provider import OCIProvider

R = []
core.init_db()


def ok(name, cond):
    R.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name)


async def noop():
    await asyncio.sleep(3600)


for f in ("task_loop", "monitor_loop", "schedule_loop"):
    setattr(tasks, f, noop)
telegram.poll_loop = noop

for cls in (OCIProvider, AWSProvider, AzureProvider):
    mock.patch.object(cls, "__init__", lambda self, cred, region=None: setattr(self, "cred", cred)).start()
    mock.patch.object(cls, "test", return_value={"ok": True}).start()

with TestClient(main.app) as c:
    c.post("/api/login", json={"password": "devpassword123"})
    zid = c.post("/api/accounts", json={"provider": "azure", "name": "az", "cred": {
        "tenant_id": "t-000000000001", "client_id": "c-000000000002", "client_secret": "s3", "subscription_id": "sub-000000000003"}}).json()["id"]
    det = c.get(f"/api/accounts/{zid}/detail").json()
    ok("azure detail: no region field in edit form", "region" not in det["fields"] and "tenant_id" in det["fields"])
    r = c.patch(f"/api/accounts/{zid}", json={"name": "az2", "cred": {"tenant_id": "", "client_id": "", "client_secret": "", "subscription_id": ""}})
    ok("azure edit without region saves", r.status_code == 200 and core.get_account(zid)["name"] == "az2")
    r = c.patch(f"/api/accounts/{zid}", json={"cred": {"region": ""}})
    ok("azure edit with empty region (old client) does not error", r.status_code == 200)
    # 已存了 region 的旧 Azure 账号：编辑后 region 原样保留
    acc = core.get_account(zid, with_cred=True)
    cred = dict(acc["cred"], region="eastasia")
    core.ex("UPDATE accounts SET cred_enc=?, region=? WHERE id=?", (core.encrypt(cred), "eastasia", zid))
    r = c.patch(f"/api/accounts/{zid}", json={"name": "az3", "cred": {"client_secret": "new-secret"}})
    a2 = core.get_account(zid, with_cred=True)
    ok("azure legacy account: stored region kept after edit", r.status_code == 200 and a2["cred"].get("region") == "eastasia"
       and a2["cred"]["client_secret"] == "new-secret")
    oid = c.post("/api/accounts", json={"provider": "oci", "name": "o", "cred": {
        "user": "ocid1.user.oc1..fakeuser123456", "tenancy": "ocid1.tenancy.oc1..faketen654321", "fingerprint": "aa:bb",
        "key_content": "-----BEGIN PRIVATE KEY-----\nFAKE\n-----END PRIVATE KEY-----\n", "region": "ap-tokyo-1"}}).json()["id"]
    aid = c.post("/api/accounts", json={"provider": "aws", "name": "a", "cred": {
        "access_key": "AKIAFAKEFAKE1234", "secret_key": "s", "region": "us-east-1"}}).json()["id"]
    r1 = c.patch(f"/api/accounts/{oid}", json={"cred": {"region": ""}})
    r2 = c.patch(f"/api/accounts/{aid}", json={"cred": {"region": " "}})
    ok("oci edit: empty region still 400", r1.status_code == 400 and "区域不能为空" in r1.text)
    ok("aws edit: empty region still 400", r2.status_code == 400 and "区域不能为空" in r2.text)
    ok("oci/aws detail: region still echoed", c.get(f"/api/accounts/{oid}/detail").json()["fields"]["region"] == "ap-tokyo-1"
       and c.get(f"/api/accounts/{aid}/detail").json()["fields"]["region"] == "us-east-1")
    ok("oci edit: region change still saved", c.patch(f"/api/accounts/{oid}", json={"cred": {"region": "ap-osaka-1"}}).status_code == 200
       and core.get_account(oid)["region"] == "ap-osaka-1")
    print(json.dumps({"azure_fields": sorted(det["fields"])}, ensure_ascii=False))

print(f"\n{sum(x[1] for x in R)}/{len(R)} passed")
sys.exit(0 if all(x[1] for x in R) else 1)
