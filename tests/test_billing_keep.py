"""保号账单（OCI PAYG）自测：multipart 流式上传全零对象、续传 / 停止 / 中止、删除、PAYG 限制、路由与后台任务；
以及弹窗遮罩「按下和松开都在遮罩上才关闭」的静态检查。全部用假客户端，不连接任何真实云。"""
import asyncio
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
from unittest import mock

import oci
from fastapi.testclient import TestClient

from app import core, main, services, tasks, telegram
from app.providers.oci_provider import OCIProvider
from app.routers import oci as oci_routes

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


async def no_tg(*a, **kw):
    return None
telegram.send = no_tg


class Obj:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def se(status):
    return oci.exceptions.ServiceError(status, "NotFound" if status == 404 else "Err", {}, "x")


class FakeOS:
    """对象存储假客户端：记录调用、分片与内存中最大的分片体积。"""
    def __init__(self, bucket=None, obj_size=None, uploads=None):
        self.bucket = bucket            # None = 不存在；否则 Obj(storage_tier, public_access_type, auto_tiering)
        self.obj_size = obj_size
        self.uploads = uploads or {}    # upload_id -> {part_no: size}
        self.calls, self.max_body, self.fail_at = [], 0, None

    def get_namespace(self, **kw):
        return Obj(data="ns1")

    def get_bucket(self, ns, b):
        self.calls.append(("get_bucket", b))
        if self.bucket is None:
            raise se(404)
        return Obj(data=self.bucket)

    def create_bucket(self, ns, det):
        self.calls.append(("create_bucket", det.name, det.storage_tier, det.public_access_type, det.auto_tiering))
        self.bucket = Obj(storage_tier=det.storage_tier, public_access_type=det.public_access_type, auto_tiering=det.auto_tiering)

    def update_bucket(self, ns, b, det):
        self.calls.append(("update_bucket", det.auto_tiering))
        self.bucket.auto_tiering = det.auto_tiering

    def head_object(self, ns, b, o):
        if self.obj_size is None:
            raise se(404)
        return Obj(headers={"content-length": str(self.obj_size)})

    def list_multipart_uploads(self, ns, b, **kw):
        if self.bucket is None:
            raise se(404)
        return Obj(data=[Obj(object="billing-keep.bin", upload_id=u, time_created="2026-10-16 06:00") for u in self.uploads],
                   has_next_page=False, next_page=None, headers={}, status=200, request=None)

    def list_multipart_upload_parts(self, ns, b, o, uid, **kw):
        return Obj(data=[Obj(part_number=n, etag=f"e{n}", size=sz) for n, sz in sorted(self.uploads[uid].items())],
                   has_next_page=False, next_page=None, headers={}, status=200, request=None)

    def create_multipart_upload(self, ns, b, det):
        self.calls.append(("create_mpu", det.object, det.storage_tier))
        self.uploads["up-new"] = {}
        return Obj(data=Obj(upload_id="up-new"))

    def upload_part(self, ns, b, o, uid, n, body, **kw):
        if self.fail_at == n:
            raise RuntimeError("network down")
        self.max_body = max(self.max_body, len(body))
        assert body.count(0) == len(body) and kw["content_length"] == len(body) and kw.get("content_md5")
        self.uploads[uid][n] = len(body)
        self.calls.append(("upload_part", n, len(body)))
        return Obj(headers={"etag": f"e{n}"})

    def commit_multipart_upload(self, ns, b, o, uid, det):
        parts = [p.part_num for p in det.parts_to_commit]
        self.calls.append(("commit", parts))
        self.obj_size = sum(self.uploads.pop(uid).values())

    def abort_multipart_upload(self, ns, b, o, uid):
        self.calls.append(("abort", uid))
        self.uploads.pop(uid, None)

    def delete_object(self, ns, b, o):
        self.calls.append(("delete_object", o))
        if self.obj_size is None:
            raise se(404)
        self.obj_size = None

    def list_objects(self, ns, b, **kw):
        return Obj(data=Obj(objects=[1] if self.obj_size is not None else []))

    def delete_bucket(self, ns, b):
        self.calls.append(("delete_bucket", b))
        self.bucket = None


def prov(fos):
    p = OCIProvider.__new__(OCIProvider)
    p.cred, p.compartment, p.cfg, p.proxy = {}, "ocid1.compartment.x", {"tenancy": "ocid1.tenancy.x", "region": "ap-osaka-1"}, None
    p.identity = Obj(list_region_subscriptions=lambda t: Obj(data=[Obj(region_name="ap-osaka-1", is_home_region=False),
                                                                    Obj(region_name="ap-tokyo-1", is_home_region=True)]))
    p._c = lambda cls, cfg=None: (p.__dict__.setdefault("_regions", []).append(cfg["region"]), fos)[1]
    p.BK_PART = 1024           # 测试里用 1 KiB 分片
    return p


# ================= 1. provider：上传 =================
fos = FakeOS()
p = prov(fos)
rep = []
r = p.billing_keep_upload(5000, None, None, None, lambda u, t, uid: rep.append((u, t, uid)))
ok("upload: home region used (not account default region)", set(p._regions) == {"ap-tokyo-1"} and r["region"] == "ap-tokyo-1")
ok("upload: bucket created Standard + private + auto-tiering disabled",
   ("create_bucket", "tricloud-billing-keep", "Standard", "NoPublicAccess", "Disabled") in fos.calls)
ok("upload: multipart in Standard tier", ("create_mpu", "billing-keep.bin", "Standard") in fos.calls)
ok("upload: 5 parts serial (4×1024 + 904), last part smaller",
   [c[1:] for c in fos.calls if c[0] == "upload_part"] == [(1, 1024), (2, 1024), (3, 1024), (4, 1024), (5, 904)])
ok("upload: commit with all parts in order, object size == total", ("commit", [1, 2, 3, 4, 5]) in fos.calls and r["size"] == 5000 and not r["existed"])
ok("upload: progress reported per part, ends at total", [x[0] for x in rep] == [1024, 2048, 3072, 4096, 5000] and rep[-1][2] == "up-new")
ok("upload: part body never larger than part size", fos.max_body == 1024)
ok("upload: real part size 64 MiB (memory bound)", OCIProvider.BK_PART == 64 * 1024 * 1024)

fos = FakeOS(bucket=Obj(storage_tier="Standard", public_access_type="NoPublicAccess", auto_tiering="Disabled"), obj_size=11 * 1024 ** 3)
r = prov(fos).billing_keep_upload(5000)
ok("upload: existing object -> existed, nothing uploaded", r["existed"] and r["size"] == 11 * 1024 ** 3
   and not any(c[0] in ("upload_part", "create_mpu", "create_bucket") for c in fos.calls))

fos = FakeOS(bucket=Obj(storage_tier="Archive", public_access_type="NoPublicAccess", auto_tiering=None))
try:
    prov(fos).billing_keep_upload(5000)
    ok("upload: non-Standard bucket refused", False)
except RuntimeError as e:
    ok("upload: non-Standard bucket refused", "不是标准层" in str(e))

fos = FakeOS(bucket=Obj(storage_tier="Standard", public_access_type="NoPublicAccess", auto_tiering="InfrequentAccess"))
prov(fos).billing_keep_upload(2048)
ok("upload: reused bucket with auto-tiering gets it disabled", ("update_bucket", "Disabled") in fos.calls)

# 续传：上次 upload 已有 1、2 片；另一个残留的 upload 被中止
fos = FakeOS(bucket=Obj(storage_tier="Standard", public_access_type="NoPublicAccess", auto_tiering="Disabled"),
             uploads={"up-old": {1: 1024, 2: 1024}, "up-stray": {1: 1024}})
rep = []
r = prov(fos).billing_keep_upload(9999, {"upload_id": "up-old", "total": 4000}, None, None, lambda u, t, uid: rep.append((u, uid)))
ok("resume: only missing parts uploaded, total from resume", [c[1] for c in fos.calls if c[0] == "upload_part"] == [3, 4] and r["size"] == 4000)
ok("resume: no new multipart created, stray upload aborted", not any(c[0] == "create_mpu" for c in fos.calls) and ("abort", "up-stray") in fos.calls
   and ("abort", "up-old") not in fos.calls)
ok("resume: progress counts already-uploaded parts", rep[0] == (3072, "up-old") and rep[-1][0] == 4000)

fos = FakeOS(bucket=Obj(storage_tier="Standard", public_access_type="NoPublicAccess", auto_tiering="Disabled"), uploads={"up-x": {1: 1024}})
prov(fos).billing_keep_upload(2048, {"upload_id": "gone", "total": 2048})
ok("resume: unknown upload id -> fresh upload, stale one aborted", ("abort", "up-x") in fos.calls and ("create_mpu", "billing-keep.bin", "Standard") in fos.calls)

# 停止：checkpoint 抛异常 → 不中止，已传分片保留可续传
fos = FakeOS()
n = {"i": 0}


def cp(m):
    n["i"] += 1
    if n["i"] == 3:
        raise tasks.TaskStopped()
try:
    prov(fos).billing_keep_upload(5000, None, None, cp)
except tasks.TaskStopped:
    pass
ok("stop: parts kept for resume, no abort, no commit", fos.uploads.get("up-new") == {1: 1024, 2: 1024}
   and not any(c[0] in ("abort", "commit") for c in fos.calls))

fos = FakeOS()
fos.fail_at = 2
with mock.patch("time.sleep", lambda s: None):
    try:
        prov(fos).billing_keep_upload(5000)
        ok("failure: part error raised after retries, upload kept", False)
    except RuntimeError:
        ok("failure: part error raised after retries, upload kept", fos.uploads.get("up-new") == {1: 1024})

# ================= 2. provider：状态 / 删除 =================
fos = FakeOS()
st = prov(fos).billing_keep_status()
ok("status: no bucket -> not exists, read-only", not st["bucket_exists"] and not st["exists"] and st["bucket"] == "tricloud-billing-keep"
   and not any(c[0] in ("create_bucket", "create_mpu") for c in fos.calls))
fos = FakeOS(bucket=Obj(storage_tier="Standard", public_access_type="NoPublicAccess", auto_tiering="Disabled"), obj_size=123, uploads={"u1": {}})
st = prov(fos).billing_keep_status()
ok("status: size + pending uploads", st["exists"] and st["size"] == 123 and st["pending_uploads"][0]["upload_id"] == "u1" and st["storage_tier"] == "Standard")
r = prov(fos).billing_keep_delete()
ok("delete: aborts uploads, deletes object then empty bucket", r["deleted"] and r["aborted"] == 1 and r["bucket_deleted"]
   and [c[0] for c in fos.calls if c[0] in ("abort", "delete_object", "delete_bucket")] == ["abort", "delete_object", "delete_bucket"])
fos = FakeOS()
r = prov(fos).billing_keep_delete()
ok("delete: no bucket -> ok, nothing deleted", r["ok"] and not r["deleted"] and not any(c[0].startswith("delete") for c in fos.calls))
src = open(os.path.join(ROOT, "app", "providers", "oci_more.py"), encoding="utf-8").read()
seg = src[src.index("def billing_keep_delete"):src.index("# ================= 20.")]
ok("delete: only touches the fixed billing-keep bucket", "self.BK_BUCKET" in seg and "bucket," not in seg.replace("self.BK_BUCKET", ""))
ok("no temp file / disk writes in upload", "tempfile" not in src[src.index("BK_BUCKET ="):src.index("# ================= 20.")]
   and "open(" not in src[src.index("BK_BUCKET ="):src.index("# ================= 20.")])


# ================= 3. 路由 =================
class FP:
    def __init__(self):
        self.calls, self.exists = [], False

    def billing_keep_status(self):
        self.calls.append("status")
        return {"region": "ap-tokyo-1", "bucket": "tricloud-billing-keep", "object": "billing-keep.bin", "exists": self.exists,
                "size": 11811160064 if self.exists else 0, "pending_uploads": [{"upload_id": "up-1"}]}

    def billing_keep_delete(self):
        self.calls.append("delete")
        return {"ok": True, "deleted": True}

    def account_type(self):
        self.calls.append("account_type")
        return {"label": "未知", "plan_type": None, "error": "查询订阅失败"}


mock.patch.object(OCIProvider, "__init__", lambda self, cred, region=None: setattr(self, "cred", cred)).start()


def set_plan(acc, plan):
    core.ex("UPDATE accounts SET acct_type=? WHERE id=?", (json.dumps({"plan_type": plan}) if plan else None, acc))


with TestClient(main.app) as c:
    c.post("/api/login", json={"password": "devpassword123"})
    with mock.patch.object(OCIProvider, "test", return_value={"ok": True}):
        oid = c.post("/api/accounts", json={"provider": "oci", "name": "payg", "cred": {
            "user": "ocid1.user.oc1..fakeuser123456", "tenancy": "ocid1.tenancy.oc1..faketen654321", "fingerprint": "aa:bb",
            "key_content": "-----BEGIN PRIVATE KEY-----\nFAKE\n-----END PRIVATE KEY-----\n", "region": "ap-tokyo-1"}}).json()["id"]
    fp = FP()
    U = f"/api/accounts/{oid}/oci/billing-keep"
    with mock.patch.object(services, "provider", lambda acc_id, region=None: fp):
        set_plan(oid, "FREE_TIER")
        j = c.get(U).json()
        ok("route free: GET not eligible + hint, no OCI call", j["eligible"] is False and j["plan"] == "free" and "免费号 20GB 内不收费，无需操作" in j["hint"] and not fp.calls)
        r = c.post(U, json={"confirm": True})
        ok("route free: POST 400 with clear hint", r.status_code == 400 and "免费号 20GB 内不收费，无需操作" in r.json()["detail"])
        set_plan(oid, None)
        r = c.post(U, json={"confirm": True})
        ok("route unknown plan: queries account type once, then refuses", r.status_code == 400 and "PAYG" in r.json()["detail"] and fp.calls == ["account_type"])
        set_plan(oid, "PAYG")
        ok("route: size_gb range 10.5–20 enforced", c.post(U, json={"size_gb": 10, "confirm": True}).status_code == 400
           and c.post(U, json={"size_gb": 25, "confirm": True}).status_code == 400 and c.post(U, json={"size_gb": "x", "confirm": True}).status_code == 400)
        ok("route: needs confirm", c.post(U, json={}).status_code == 400 and not core.q("SELECT id FROM tasks WHERE type='billing_keep'"))
        j = c.get(U).json()
        ok("route PAYG: GET status + note + defaults", j["eligible"] and j["plan"] == "paid" and j["default_gb"] == 11 and "$0.02–0.03" in j["note"]
           and "出网" in j["note"] and j["region"] == "ap-tokyo-1" and j["task"] is None)
        r = c.post(U, json={"confirm": True})
        t = core.q("SELECT * FROM tasks WHERE id=?", (r.json().get("task_id"),), one=True)
        ok("route PAYG: default 11 GiB -> background task", t and t["type"] == "billing_keep" and json.loads(t["params"])["size_bytes"] == 11 * 1024 ** 3
           and json.loads(t["params"])["resume"] is None)
        r2 = c.post(U, json={"confirm": True, "size_gb": 12})
        ok("route: running task -> same task id, no duplicate", r2.json().get("task_id") == t["id"] and r2.json().get("running")
           and len(core.q("SELECT id FROM tasks WHERE type='billing_keep'")) == 1)
        ok("route: GET shows running task progress", c.get(U).json()["task"]["status"] == "running")
        ok("route: DELETE needs confirm; refused while uploading", c.delete(U).status_code == 400 and c.delete(U + "?confirm=true").status_code == 409)
        tasks._update(t["id"], status="failed", message="network down", result={"uploaded": 3 * 1024 ** 3, "total": 11 * 1024 ** 3, "upload_id": "up-1"})
        r = c.post(U, json={"confirm": True, "size_gb": 15})
        p2 = json.loads(core.q("SELECT params FROM tasks WHERE id=?", (r.json()["task_id"],), one=True)["params"])
        ok("route: failed task with pending upload -> resume (keeps original total)", r.json()["resumed"] and p2["resume"] == {"upload_id": "up-1", "total": 11 * 1024 ** 3}
           and p2["size_bytes"] == 11 * 1024 ** 3 and r.json()["resumed_from"] == 3 * 1024 ** 3)
        tasks._update(r.json()["task_id"], status="done", message="ok", result={"size": 1})
        fp.exists = True
        r = c.post(U, json={"confirm": True})
        ok("route: object already exists -> size returned, no new task", r.json().get("existed") and r.json()["size"] == 11811160064
           and len(core.q("SELECT id FROM tasks WHERE type='billing_keep'")) == 2)
        ok("route: DELETE with confirm calls provider", c.delete(U + "?confirm=true").json()["deleted"] and fp.calls[-1] == "delete")
        from app.providers.aws_provider import AWSProvider
        with mock.patch.object(AWSProvider, "__init__", lambda self, cred, region=None: setattr(self, "cred", cred)), \
                mock.patch.object(AWSProvider, "test", return_value={"ok": True}):
            aws = c.post("/api/accounts", json={"provider": "aws", "name": "a", "cred": {"access_key": "AKIAFAKEFAKE1234", "secret_key": "s", "region": "us-east-1"}})
        ok("route: OCI only", aws.status_code == 200 and c.get(f"/api/accounts/{aws.json()['id']}/oci/billing-keep").status_code == 400)

        def boom():
            raise se(500)
        fp.billing_keep_status = boom
        ok("route: OCI ServiceError -> 400 (not 500)", c.post(U, json={"confirm": True}).status_code == 400)


# ================= 4. 后台任务 =================
class TP:
    def billing_keep_upload(self, total, resume, progress, checkpoint, report):
        progress("准备 Bucket…")
        for u in range(1, 4):
            checkpoint("分片")
            report(u * total // 3, total, "up-9")
            self.mid = json.loads(core.q("SELECT result FROM tasks WHERE id=?", (tid,), one=True)["result"])
        return {"ok": True, "existed": False, "size": total, "region": "ap-tokyo-1"}


tp = TP()
tid = tasks.create_task("billing_keep", oid, {"name": "保号账单", "size_bytes": 3 * 1024 ** 3, "resume": None})
with mock.patch.object(services, "provider", lambda acc_id, region=None: tp):
    asyncio.run(tasks._run_once(core.q("SELECT * FROM tasks WHERE id=?", (tid,), one=True)))
t = core.q("SELECT * FROM tasks WHERE id=?", (tid,), one=True)
res = json.loads(t["result"])
ok("task: progress (uploaded/total/upload_id) stored in result while running", tp.mid["upload_id"] == "up-9" and tp.mid["total"] == 3 * 1024 ** 3)
ok("task: done with object size in result", t["status"] == "done" and res["size"] == 3 * 1024 ** 3 and res["done"] and "3.00 GiB" in t["message"])
logs = " ".join(x["msg"] for x in tasks.get_logs(tid))
ok("task: logs progress milestones", "100%" in logs and "保号账单" in logs)
ok("task: registered + named", "billing_keep" in tasks.ONCE_HANDLERS and tasks.TYPE_NAME["billing_keep"] == "保号账单")
tid2 = tasks.create_task("billing_keep", oid, {"name": "保号账单", "size_bytes": 1, "resume": None})
ok("task: not auto-resumed on restart (interrupted, user re-starts = resume)", tasks.recover_on_startup()["interrupted"] >= 1
   and core.q("SELECT status FROM tasks WHERE id=?", (tid2,), one=True)["status"] == "interrupted")
ok("route constants: 10.5–20, default 11", (oci_routes.BK_MIN_GB, oci_routes.BK_MAX_GB, oci_routes.BK_DEFAULT_GB) == (10.5, 20, 11))

# ================= 5. Web / demo 静态检查 =================
web = open(os.path.join(ROOT, "web", "js", "oci.js"), encoding="utf-8").read()
corejs = open(os.path.join(ROOT, "web", "js", "core.js"), encoding="utf-8").read()
mockjs = open(os.path.join(ROOT, "demo", "mock.js"), encoding="utf-8").read()
demo = open(os.path.join(ROOT, "demo", "index.html"), encoding="utf-8").read()
ok("web: billing-keep card on object storage page with confirm + delete", "billingKeepCard(acc, $(\"#bkCard\", box))" in web and "confirmBox(BK_TITLE" in web
   and "/oci/billing-keep?confirm=true" in web and "<progress" in web)
ok("demo: mock covers /oci/billing-keep and demo rebuilt", "/oci\\/billing-keep$/" in mockjs and "billingKeepCard" in demo and "billing-keep" in demo)
ok("web: modal closes on backdrop only when press also started on backdrop", "downOnBg" in corejs and 'addEventListener("mousedown", markDown)' in corejs
   and "if (e.target === bg && downOnBg) close(null)" in corejs and "bg.onclick = (e) => { if (e.target === bg) close(null); };" not in corejs)

print(f"\n{sum(x[1] for x in R)}/{len(R)} passed")
sys.exit(0 if all(x[1] for x in R) else 1)
