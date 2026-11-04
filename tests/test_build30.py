"""build 30：OCI 一键切换受限 API。全部用假 OCI 客户端（不连接任何真实云、不做任何真实写操作）。
覆盖：策略内容（无禁用权限、账单只读）、密钥 / 指纹、成功路径、各失败点回滚、绝不删除云端原 Key、旧私钥从库里清掉、
TG 验证码（未绑定 / 过期 / 重用 / 输错次数 / 跨账号）、路由与 API Token 403、后台任务、中断后清理、Web / App / 文档静态检查。"""
import asyncio
import json
import os
import re
import sys
import tempfile

D = tempfile.mkdtemp()
os.environ.update(TRICLOUD_DATA=D, PANEL_PASSWORD="devpassword123")
for k in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy", "FERNET_KEY"):
    os.environ.pop(k, None)
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _l10n_src  # noqa: E402,F401
sys.path.insert(0, ROOT)

import oci  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import core, main, security, services, tasks, telegram, tg_verify  # noqa: E402
from app.providers import oci_restrict as R  # noqa: E402

core.init_db()
P = F = 0


def ok(name, cond):
    global P, F
    if cond:
        P += 1
    else:
        F += 1
        print("FAIL", name)


def rd(*p):
    return open(os.path.join(ROOT, *p), encoding="utf-8").read()


async def noop():
    await asyncio.sleep(3600)


for f in ("task_loop", "monitor_loop", "schedule_loop"):
    setattr(tasks, f, noop)
telegram.poll_loop = noop
SENT = []


async def fake_send(text, *a, **kw):
    SENT.append(text)
    return FAKE_TG["ok"]
FAKE_TG = {"bound": True, "ok": True}
telegram.send = fake_send
telegram.cfg = lambda: ("123:abc", "42") if FAKE_TG["bound"] else ("", "")


class Obj:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def se(status, msg="err", code=None):
    return oci.exceptions.ServiceError(status, code or ("NotAuthorizedOrNotFound" if status == 404 else "Err"), {}, msg)


OLD_PRIV, OLD_PUB, OLD_FP = R.gen_keypair()
OLD_USER = "ocid1.user.oc1..aaaaold"
TEN = "ocid1.tenancy.oc1..aaaatenant"


class World:
    def __init__(self, **kw):
        self.calls, self.deleted, self.violations = [], [], []
        self.fail = None             # 方法名：该方法抛 500
        self.non_default = False     # get_user 404（非 Default 域）
        self.no_iam = False          # list_groups 404（0 权号 / 已受限）
        self.need_email = False
        self.active_after = 0        # 新 Key 前 N 次自检 401（生效中）
        self.usage_fail = False      # 新 Key 读 Usage API 一直 404
        self.new_list_users = False  # 新 Key 仍能读 IAM 用户（策略失效）
        self.fp_mismatch = False
        self.new_checks = 0
        self.statements = None
        self.uploaded = {}
        self.__dict__.update(kw)


W = World()


def _is_old(cfg):
    return cfg.get("user") == OLD_USER


class FakeIdentity:
    def __init__(self, cfg):
        self.cfg = cfg

    def _c(self, name, *a):
        W.calls.append((name, "old" if _is_old(self.cfg) else "new") + a)
        if W.fail == name:
            raise se(500, f"boom {name}")

    def list_region_subscriptions(self, t):
        self._c("list_region_subscriptions")
        return Obj(data=[Obj(region_name="ap-osaka-1", is_home_region=False), Obj(region_name="ap-tokyo-1", is_home_region=True)])

    def get_user(self, uid):
        self._c("get_user", uid)
        if W.non_default:
            raise se(404)
        return Obj(data=Obj(name="admin", email="owner@example.com"))

    def list_groups(self, t, **kw):
        self._c("list_groups")
        if W.no_iam:
            raise se(404)
        return Obj(data=[])

    def list_policies(self, t, **kw):
        self._c("list_policies")
        return Obj(data=[])

    def create_group(self, d):
        self._c("create_group", d.name)
        return Obj(data=Obj(id="ocid1.group.oc1..g1", name=d.name))

    def create_policy(self, d):
        self._c("create_policy", d.name)
        W.statements = list(d.statements)
        W.policy_compartment = d.compartment_id
        return Obj(data=Obj(id="ocid1.policy.oc1..p1"))

    def create_user(self, d):
        self._c("create_user", d.name, d.email)
        if W.need_email and not d.email:
            raise se(400, "Email is required for users in this domain", "InvalidParameter")
        W.user_desc = d.description
        return Obj(data=Obj(id="ocid1.user.oc1..new1"))

    def update_user_capabilities(self, uid, d):
        self._c("update_user_capabilities", uid)
        W.caps = d
        return Obj(data=None)

    def add_user_to_group(self, d):
        self._c("add_user_to_group", d.user_id, d.group_id)
        return Obj(data=Obj(id="ocid1.groupmembership.oc1..m1"))

    def upload_api_key(self, uid, d):
        self._c("upload_api_key", uid)
        fp = R.fingerprint_of(d.key)
        W.uploaded[uid] = (d.key, fp)
        return Obj(data=Obj(fingerprint="00:" * 15 + "00" if W.fp_mismatch else fp))

    def _del(self, what, *ids):
        self._c("delete_" + what, *ids)
        if OLD_USER in ids or OLD_FP in ids:
            W.violations.append((what, ids))
        W.deleted.append((what,) + ids)

    def delete_api_key(self, uid, fp):
        self._del("api_key", uid, fp)

    def remove_user_from_group(self, mid):
        self._del("membership", mid)

    def delete_user(self, uid):
        self._del("user", uid)

    def delete_policy(self, pid):
        self._del("policy", pid)

    def delete_group(self, gid):
        self._del("group", gid)

    def list_users(self, t, **kw):
        self._c("list_users")
        if _is_old(self.cfg) or W.new_list_users:
            return Obj(data=[])
        raise se(404)

    def list_domains(self, t, **kw):
        self._c("list_domains")
        raise se(404)


class FakeCompute:
    def __init__(self, cfg):
        self.cfg = cfg

    def list_instances(self, **kw):
        if not _is_old(self.cfg):
            W.new_checks += 1
            if W.new_checks <= W.active_after:
                raise se(401, "NotAuthenticated", "NotAuthenticated")
        return Obj(data=[])


class FakeVN:
    def __init__(self, cfg):
        pass

    def list_vcns(self, **kw):
        return Obj(data=[])


class FakeOS:
    def __init__(self, cfg):
        pass

    def get_namespace(self, **kw):
        return Obj(data="ns")

    def list_buckets(self, ns, comp, **kw):
        return Obj(data=[])


class FakeUsage:
    def __init__(self, cfg):
        pass

    def request_summarized_usages(self, d):
        if W.usage_fail:
            raise se(404)
        return Obj(data=Obj(items=[]))


CLIENTS = {oci.identity.IdentityClient: FakeIdentity, oci.core.ComputeClient: FakeCompute, oci.core.VirtualNetworkClient: FakeVN,
           oci.object_storage.ObjectStorageClient: FakeOS, oci.usage_api.UsageapiClient: FakeUsage}
SEEN_CFG = []


def fake_client(cls, cfg, proxy=None):
    SEEN_CFG.append(dict(cfg))
    return CLIENTS[cls](cfg)


R._client = fake_client
CLOCK = {"t": 0.0}
R._sleep = lambda s: CLOCK.__setitem__("t", CLOCK["t"] + s)
R._clock = lambda: CLOCK["t"]
CRED = {"user": OLD_USER, "tenancy": TEN, "fingerprint": OLD_FP, "key_content": OLD_PRIV, "region": "ap-osaka-1", "pass_phrase": "pp"}


def fresh(**kw):
    global W
    W = World(**kw)
    CLOCK["t"] = 0.0


# ================= 1. 策略内容 =================
stm = R.policy_statements("TriCloud-Restricted-abc123")
ok("policy: statements well-formed and safe", R.check_statements(stm) == [] and len(stm) == len(R.POLICY_RULES) >= 10)
low = " ".join(stm).lower()
for res in ("instance-family", "volume-family", "virtual-network-family", "object-family", "network-load-balancers", "usage-report",
            "metrics", "resource-availability", "accountmanagement-family", "organizations-subscription", "compartments", "tenancies",
            "instance-agent-plugins", "instance-agent-command-family"):
    ok("policy grants " + res, f" {res} in tenancy" in low)
for bad in ("users", "groups", "policies", "domains", "dynamic-groups", "all-resources", "identity-domains", "api-keys"):
    ok("policy never mentions " + bad, not re.search(rf"\b(inspect|read|use|manage) {re.escape(bad)}\b", low))
ok("policy: billing / subscription read-only", all(re.search(r"to (read|inspect) " + r, low) for r in ("usage-report", "accountmanagement-family", "organizations-subscription"))
   and not re.search(r"to (use|manage) (usage-report|accountmanagement-family|organizations-subscription)", low))
ok("policy: tenancies / compartments inspect only", "to inspect tenancies" in low and "to inspect compartments" in low)
ok("policy: no 'where' / 'any-user' / other groups", all(" where " not in s and "any-user" not in s and "TriCloud-Restricted-abc123" in s for s in stm))
ok("check_statements: rejects manage users", R.check_statements(["Allow group G to manage users in tenancy"]))
ok("check_statements: rejects all-resources", R.check_statements(["Allow group G to read all-resources in tenancy"]))
ok("check_statements: rejects billing write", R.check_statements(["Allow group G to manage accountmanagement-family in tenancy"]))
ok("check_statements: rejects dynamic-groups / domains / policies / groups", all(R.check_statements([f"Allow group G to inspect {x} in tenancy"]) for x in
                                                                                ("dynamic-groups", "domains", "policies", "groups")))
ok("check_statements: rejects compartment scope / free text", R.check_statements(["Allow group G to manage instance-family in compartment x"]) and
   R.check_statements(["Allow any-user to manage instance-family in tenancy"]))
nm = R.names()
ok("names: TriCloud prefix + 6 hex suffix", re.fullmatch(r"TriCloud-Restricted-[0-9a-f]{6}", nm["group"]) and nm["policy"] == nm["group"]
   and re.fullmatch(r"TriCloud-API-[0-9a-f]{6}", nm["user"]) and R.names()["suffix"] != nm["suffix"])
ok("description says created by TriCloud", "TriCloud" in R.DESCRIPTION)
# 每条语句在文档里都有
DOC = rd("docs", "api-credentials.md")
ok("docs: every statement documented (zh)", all(f"`{v} {r}`" in DOC for v, r, _ in R.POLICY_RULES) and "一键切换受限 API" in DOC)
ok("docs: english section + never granted list", "One-click restricted API" in DOC and "Never granted" in DOC and "不会被删除或撤销" in DOC)

# ================= 2. 密钥 =================
priv, pub, fp = R.gen_keypair()
from cryptography.hazmat.primitives import serialization  # noqa: E402
k = serialization.load_pem_private_key(priv.encode(), None)
ok("keypair: RSA 2048, PKCS8, unencrypted", k.key_size == 2048 and priv.startswith("-----BEGIN PRIVATE KEY-----"))
ok("keypair: fingerprint format", re.fullmatch(r"([0-9a-f]{2}:){15}[0-9a-f]{2}", fp) is not None)
ok("keypair: fingerprint = md5(DER pubkey)", fp == R.fingerprint_of(k.public_key()) == R.fingerprint_of(pub))
import hashlib  # noqa: E402
der = k.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
ok("keypair: fingerprint matches openssl-style md5", fp.replace(":", "") == hashlib.md5(der).hexdigest())
ok("keypair: random each time", R.gen_keypair()[2] != fp)

# ================= 3. 成功路径 =================
fresh(active_after=2)
LOG, CREATED, STEPS = [], [], []
r = R.run_switch(dict(CRED), lambda m, lv="info": LOG.append((lv, m)), STEPS.append, CREATED.append, suffix="abc123")
ok("success: returns new user + key", r["user"] == "ocid1.user.oc1..new1" and r["key_content"].startswith("-----BEGIN PRIVATE KEY-----")
   and r["key_content"] != OLD_PRIV and r["fingerprint"] != OLD_FP)
ok("success: fingerprint equals uploaded public key", W.uploaded["ocid1.user.oc1..new1"][1] == r["fingerprint"])
ok("success: home region used for IAM writes", any(c.get("region") == "ap-tokyo-1" and c.get("user") == OLD_USER for c in SEEN_CFG))
ok("success: policy in tenancy root", W.policy_compartment == TEN and W.statements == R.policy_statements("TriCloud-Restricted-abc123"))
ok("success: names with prefix", ("create_group", "old", "TriCloud-Restricted-abc123") in W.calls and
   ("create_user", "old", "TriCloud-API-abc123", None) in W.calls)
ok("success: user added to group", ("add_user_to_group", "old", "ocid1.user.oc1..new1", "ocid1.group.oc1..g1") in W.calls)
ok("success: user capabilities = api keys only", W.caps.can_use_api_keys is True and W.caps.can_use_console_password is False
   and W.caps.can_use_auth_tokens is False and W.caps.can_use_customer_secret_keys is False)
ok("success: retried until key active (2 x 401)", W.new_checks == 3 and CLOCK["t"] == 2 * R.RETRY_INTERVAL)
ok("success: IAM denial verified with new key", ("list_users", "new") in W.calls)
ok("success: nothing deleted", W.deleted == [] and W.violations == [])
ok("success: created ids reported progressively", CREATED[-1].get("key_fingerprint") == r["fingerprint"] and CREATED[0].get("group_id") and len(CREATED) == 5)
ok("success: steps cover stages", any(s.startswith("预检") for s in STEPS) and any(s.startswith("等待新 Key") for s in STEPS))
ok("success: log never contains private key", all("PRIVATE KEY" not in m for _, m in LOG))
ok("success: checks recorded", set(r["checks"]) == set(R.CHECKS))
ok("success: new cfg carries no passphrase", all("pass_phrase" not in c for c in SEEN_CFG if c.get("user") == "ocid1.user.oc1..new1"))

# need_email：用管理员邮箱的 + 别名重试
fresh(need_email=True)
r2 = R.run_switch(dict(CRED), suffix="eee111")
ok("email required: retried with plus alias", ("create_user", "old", "TriCloud-API-eee111", "owner+tricloud-api-eee111@example.com") in W.calls and r2["user"])


# ================= 4. 失败点回滚 =================
def run_fail(**kw):
    fresh(**kw)
    try:
        R.run_switch(dict(CRED), suffix="fff000", wait_seconds=60)
    except R.RestrictError as e:
        return e
    return None


e = run_fail(non_default=True)
ok("precheck non-default domain: refused, nothing created", e and e.kind == "precheck" and "Default" in str(e) and e.cleanup == []
   and not any(c[0].startswith("create_") for c in W.calls))
e = run_fail(no_iam=True)
ok("precheck no IAM rights: refused, nothing created", e and e.kind == "precheck" and "IAM" in str(e) and not any(c[0].startswith("create_") for c in W.calls))
ok("cleanup_text: nothing created", R.cleanup_text([]) == "本次没有创建云端资源")
EXPECT = {
    "create_group": [],
    "create_policy": ["group"],
    "create_user": ["policy", "group"],
    "add_user_to_group": ["user", "policy", "group"],
    "upload_api_key": ["user", "policy", "group", "membership"],
}
for meth, dels in EXPECT.items():
    e = run_fail(fail=meth)
    kinds = [d[0] for d in W.deleted]
    order = [k2 for k2 in ("api_key", "membership", "user", "policy", "group") if k2 in kinds]
    ok(f"rollback at {meth}: deletes exactly what was created", e is not None and sorted(kinds) == sorted(dels) and kinds == order)
    ok(f"rollback at {meth}: never touches original key/user", W.violations == [])
    ok(f"rollback at {meth}: cleanup recorded", all(okk for _, okk, _ in e.cleanup) and len(e.cleanup) == len(dels))
e = run_fail(usage_fail=True)
ok("verify timeout (Usage API denied): rolled back incl. new key", e and e.kind == "verify" and "Usage API" in str(e)
   and [d[0] for d in W.deleted] == ["api_key", "membership", "user", "policy", "group"] and W.violations == [])
ok("verify timeout: waited ~wait_seconds", 40 <= CLOCK["t"] <= 60)
e = run_fail(new_list_users=True)
ok("verify: new key can read IAM users -> abort + rollback", e and e.kind == "verify" and "IAM" in str(e) and len(W.deleted) == 5 and W.violations == [])
e = run_fail(fp_mismatch=True)
ok("fingerprint mismatch -> abort + rollback", e and "指纹" in str(e) and len(W.deleted) == 5)
# 清理本身失败：结果写明，需要手动删
fresh(usage_fail=True)
orig_dp = FakeIdentity.delete_policy
FakeIdentity.delete_policy = lambda self, pid: (_ for _ in ()).throw(se(500, "nope"))
try:
    R.run_switch(dict(CRED), suffix="fff001", wait_seconds=20)
    e = None
except R.RestrictError as ex:
    e = ex
FakeIdentity.delete_policy = orig_dp
ok("cleanup partial failure reported", e and not all(okk for _, okk, _ in e.cleanup) and "手动删除" in R.cleanup_text(e.cleanup))


# 停止任务：TaskStopped 也回滚并原样抛出
class Stop(Exception):
    pass


Stop.__name__ = "TaskStopped"
fresh()
n = {"i": 0}


def stop_at_user(m):
    if m.startswith("创建用户"):
        raise Stop()


try:
    R.run_switch(dict(CRED), step=stop_at_user, suffix="stp000")
    stopped = None
except Stop as ex:
    stopped = ex
ok("stop: rolled back and re-raised", stopped is not None and sorted(d[0] for d in W.deleted) == ["group", "policy"] and getattr(stopped, "cleanup", None))
src = rd("app", "providers", "oci_restrict.py")
ok("source: never deletes / deactivates original key", src.count("delete_api_key") == 1
   and 'idh.delete_api_key, created["user_id"], created["key_fingerprint"]' in src and "update_user_state" not in src and "deactivate" not in src)
ok("source: oci imported lazily", "\nimport oci\n" not in src)

# ================= 5. TG 验证码 =================
TV = {"t": 1000.0}
tg_verify._now = lambda: TV["t"]
FAKE_TG["bound"] = False
try:
    asyncio.run(tg_verify.send("k1", lambda c: c))
    ok("tg: unbound refused", False)
except tg_verify.CodeError as ex:
    ok("tg: unbound refused", ex.kind == "not_bound")
FAKE_TG["bound"] = True
SENT.clear()
asyncio.run(tg_verify.send("k1", lambda c: "code " + c))
code = re.search(r"\d{6}", SENT[-1]).group(0)
ok("tg: 6-digit code sent via bot", len(code) == 6 and code.isdigit())
ok("tg: code not stored in plaintext", code not in json.dumps({k: v["h"] for k, v in tg_verify._codes.items()}))
try:
    asyncio.run(tg_verify.send("k1", lambda c: c))
    ok("tg: resend throttled", False)
except tg_verify.CodeError as ex:
    ok("tg: resend throttled", ex.kind == "too_soon" and ex.wait > 0)
for kind, val in (("wrong", "000000" if code != "000000" else "111111"), ("wrong", "abc")):
    try:
        tg_verify.verify("k1", val)
        ok("tg: wrong rejected", False)
    except tg_verify.CodeError as ex:
        ok("tg: wrong rejected", ex.kind == kind)
try:
    tg_verify.verify("other", code)
    ok("tg: scoped per key", False)
except tg_verify.CodeError as ex:
    ok("tg: scoped per key", ex.kind == "missing")
ok("tg: correct code accepted", tg_verify.verify("k1", code) is True)
try:
    tg_verify.verify("k1", code)
    ok("tg: single use", False)
except tg_verify.CodeError as ex:
    ok("tg: single use", ex.kind == "missing")
TV["t"] += 100
asyncio.run(tg_verify.send("k2", lambda c: "code " + c))
c2 = re.search(r"\d{6}", SENT[-1]).group(0)
TV["t"] += tg_verify.TTL + 1
try:
    tg_verify.verify("k2", c2)
    ok("tg: expired", False)
except tg_verify.CodeError as ex:
    ok("tg: expired", ex.kind == "expired")
asyncio.run(tg_verify.send("k3", lambda c: "code " + c))
c3 = re.search(r"\d{6}", SENT[-1]).group(0)
kinds = []
for _ in range(tg_verify.MAX_TRIES):
    try:
        tg_verify.verify("k3", "999999" if c3 != "999999" else "888888")
    except tg_verify.CodeError as ex:
        kinds.append(ex.kind)
ok("tg: too many attempts voids code", kinds[-1] == "too_many" and kinds[:-1] == ["wrong"] * (tg_verify.MAX_TRIES - 1))
try:
    tg_verify.verify("k3", c3)
    ok("tg: voided code unusable", False)
except tg_verify.CodeError as ex:
    ok("tg: voided code unusable", ex.kind == "missing")
FAKE_TG["ok"] = False
TV["t"] += 1000
try:
    asyncio.run(tg_verify.send("k4", lambda c: c))
    ok("tg: send failure discards code", False)
except tg_verify.CodeError as ex:
    ok("tg: send failure discards code", ex.kind == "send_failed" and "k4" not in tg_verify._codes)
FAKE_TG["ok"] = True
ok("tg: ttl 5 min, 5 tries", tg_verify.TTL == 300 and tg_verify.MAX_TRIES == 5)

# ================= 6. 路由 + 后台任务 =================
cl = TestClient(main.app)
cl.__enter__()
lr = cl.post("/api/login", json={"password": "devpassword123"})
ok("login", lr.status_code == 200)
ACC = core.ex("INSERT INTO accounts(provider,name,region,cred_enc,created) VALUES(?,?,?,?,?)",
              ("oci", "东京主号", "ap-osaka-1", core.encrypt(dict(CRED)), 1))
AWS = core.ex("INSERT INTO accounts(provider,name,region,cred_enc,created) VALUES(?,?,?,?,?)",
              ("aws", "aws1", "us-east-1", core.encrypt({"access_key": "AKIAX", "secret_key": "s", "region": "us-east-1"}), 1))
s = cl.get(f"/api/accounts/{ACC}/oci/restrict").json()
ok("route: status", s["restricted"] is None and s["tg_bound"] is True and s["task"] is None and len(s["statements"]) == len(R.POLICY_RULES)
   and s["wait_minutes"] == 10 and s["code_ttl"] == 300)
ok("route: AWS refused (OCI only)", cl.get(f"/api/accounts/{AWS}/oci/restrict").status_code == 400
   and cl.post(f"/api/accounts/{AWS}/oci/restrict/code").status_code == 400)
ok("route: start without code -> 400", cl.post(f"/api/accounts/{ACC}/oci/restrict", json={"confirm": True}).status_code == 400)
SENT.clear()
TV["t"] += 1000
rc = cl.post(f"/api/accounts/{ACC}/oci/restrict/code")
ok("route: code sent", rc.status_code == 200 and rc.json()["sent"] and "东京主号" in SENT[-1] and "code" not in rc.json())
code = re.search(r"<code>(\d{6})</code>", SENT[-1]).group(1)
ok("route: resend 429", cl.post(f"/api/accounts/{ACC}/oci/restrict/code").status_code == 429)
ok("route: needs confirm", cl.post(f"/api/accounts/{ACC}/oci/restrict", json={"code": code}).status_code == 400)
ok("route: wrong code", cl.post(f"/api/accounts/{ACC}/oci/restrict", json={"code": "000001" if code != "000001" else "000002", "confirm": True}).status_code == 400)
tok = security.new_api_token("t", "full")
H = {"Authorization": "Bearer " + tok}
nc = TestClient(main.app)
ok("token: GET status 403", nc.get(f"/api/accounts/{ACC}/oci/restrict", headers=H).status_code == 403)
ok("token: send code 403", nc.post(f"/api/accounts/{ACC}/oci/restrict/code", headers=H).status_code == 403)
ok("token: start 403", nc.post(f"/api/accounts/{ACC}/oci/restrict", headers=H, json={"code": code, "confirm": True}).status_code == 403)
ok("token: other endpoints still work", nc.get("/api/accounts", headers=H).status_code == 200)
fresh()
rs = cl.post(f"/api/accounts/{ACC}/oci/restrict", json={"code": code, "confirm": True})
ok("route: task created", rs.status_code == 200 and rs.json()["task_id"] > 0)
TID = rs.json()["task_id"]
ok("route: code single use", cl.post(f"/api/accounts/{ACC}/oci/restrict", json={"code": code, "confirm": True}).status_code in (400, 409))
ok("route: second start while running -> 409", cl.post(f"/api/accounts/{ACC}/oci/restrict", json={"code": "123456", "confirm": True}).status_code == 409)
ok("audit: start recorded", core.q("SELECT 1 FROM audit WHERE action='oci-restrict-start'", one=True))
row = core.q("SELECT params FROM tasks WHERE id=?", (TID,), one=True)
ok("task params hold no secrets", "PRIVATE" not in row["params"] and code not in row["params"])
services.provider(ACC)   # 旧 provider 缓存（替换后必须丢弃）
SENT.clear()
asyncio.run(tasks._run_once(core.q("SELECT * FROM tasks WHERE id=?", (TID,), one=True)))
t = core.q("SELECT * FROM tasks WHERE id=?", (TID,), one=True)
res = json.loads(t["result"])
ok("task: done", t["status"] == "done" and "受限 API" in t["message"] and "不会删除或撤销" in t["message"])
ok("task: progress stage done", res["stage"] == "done" and res["step"] == res["steps"] == tasks.RESTRICT_STEPS)
acc = core.get_account(ACC, with_cred=True)
ok("task: credentials replaced", acc["cred"]["user"] == "ocid1.user.oc1..new1" and acc["cred"]["fingerprint"] != OLD_FP
   and acc["cred"]["key_content"] != OLD_PRIV and acc["cred"]["key_content"].startswith("-----BEGIN PRIVATE KEY-----"))
ok("task: tenancy / region / home kept, passphrase dropped", acc["cred"]["tenancy"] == TEN and acc["cred"]["region"] == "ap-osaka-1"
   and acc["cred"]["home_region"] == "ap-tokyo-1" and "pass_phrase" not in acc["cred"])
info = json.loads(acc["restricted_api"])
ok("task: restricted flag stored without secrets", info["user_name"].startswith("TriCloud-API-") and "PRIVATE" not in acc["restricted_api"]
   and info["fingerprint"] == acc["cred"]["fingerprint"])
ok("task: provider cache dropped", not any(k[0] == ACC for k in services._cache))
# 旧私钥不在库里任何地方（明文 / 各行密文解密后）
db_bytes = open(core.DB_PATH, "rb").read()
old_body = OLD_PRIV.split("\n")[1]
ok("old key: not in db file plaintext", old_body.encode() not in db_bytes)
leak = False
for row in core.q("SELECT cred_enc FROM accounts"):
    if OLD_PRIV in json.dumps(core.decrypt(row["cred_enc"])):
        leak = True
for row in core.q("SELECT params, result, message FROM tasks") + core.q("SELECT msg AS params, '' AS result, '' AS message FROM task_logs") + core.q("SELECT detail AS params, '' AS result, '' AS message FROM audit"):
    if any(old_body in str(v) or "PRIVATE KEY" in str(v) for v in row.values()):
        leak = True
ok("old key: not in any decrypted cred / task / log / audit", not leak)
ok("old key: no temp files written", not [f for f in os.listdir(D) if f.endswith((".pem", ".key")) and f != "fernet.key"])
ok("never deleted original key in cloud", W.violations == [] and W.deleted == [])
ok("TG: success pushed", any("受限 API" in x for x in SENT))
ok("audit: switch recorded", core.q("SELECT 1 FROM audit WHERE action='oci-restrict'", one=True))
lst = {a["id"]: a for a in cl.get("/api/accounts").json()}
ok("accounts list: restricted badge field", lst[ACC]["restricted"] is True and lst[AWS]["restricted"] is False)
ok("route: status shows restricted", cl.get(f"/api/accounts/{ACC}/oci/restrict").json()["restricted"]["group_name"].startswith("TriCloud-Restricted-"))
ok("route: already restricted -> code refused", cl.post(f"/api/accounts/{ACC}/oci/restrict/code").status_code == 400)
ok("route: already restricted -> start refused", cl.post(f"/api/accounts/{ACC}/oci/restrict", json={"code": "123456", "confirm": True}).status_code == 400)
ok("restricted: region subscribe friendly 400", cl.post(f"/api/accounts/{ACC}/oci/region-subscriptions", json={"confirm": True, "region_key": "NRT"}).status_code == 400)
ok("TG account text shows restricted", "受限 API" in telegram._acc_text(core.get_account(ACC)) and "受限" not in telegram._acc_text(core.get_account(AWS)))
# 重复执行任务：直接拒绝
tid2 = tasks.create_task("oci_restrict", ACC, {"name": "x"})
asyncio.run(tasks._run_once(core.q("SELECT * FROM tasks WHERE id=?", (tid2,), one=True)))
ok("task: not run twice", core.q("SELECT status, message FROM tasks WHERE id=?", (tid2,), one=True)["status"] == "failed")
# 手动换回全权限 Key → 受限标记去掉
from app.routers import accounts as acc_routes  # noqa: E402
_orig_test = services.PROVIDERS["oci"].test
services.PROVIDERS["oci"].test = lambda self: {"ok": True}
acc_routes._apply_cred_patch(ACC, {"user": OLD_USER, "fingerprint": OLD_FP, "key_content": OLD_PRIV})
services.PROVIDERS["oci"].test = _orig_test
ok("manual key change clears restricted flag", core.get_account(ACC)["restricted_api"] is None)

# 失败任务：旧凭证不变 + 回滚 + TG
ACC2 = core.ex("INSERT INTO accounts(provider,name,region,cred_enc,created) VALUES(?,?,?,?,?)",
               ("oci", "首尔", "ap-osaka-1", core.encrypt(dict(CRED)), 1))
before = core.q("SELECT cred_enc FROM accounts WHERE id=?", (ACC2,), one=True)["cred_enc"]
fresh(fail="upload_api_key")
SENT.clear()
tid3 = tasks.create_task("oci_restrict", ACC2, {"name": "首尔"})
asyncio.run(tasks._run_once(core.q("SELECT * FROM tasks WHERE id=?", (tid3,), one=True)))
t3 = core.q("SELECT * FROM tasks WHERE id=?", (tid3,), one=True)
ok("failed task: status failed + cleanup in message", t3["status"] == "failed" and "已清理" in t3["message"] and "面板凭证未改动" in t3["message"])
ok("failed task: credentials untouched", core.q("SELECT cred_enc, restricted_api FROM accounts WHERE id=?", (ACC2,), one=True) == {"cred_enc": before, "restricted_api": None})
ok("failed task: rollback done, original untouched", len(W.deleted) == 4 and W.violations == [])
ok("failed task: TG pushed", any("失败" in x for x in SENT))
ok("failed task: result marks cleaned", json.loads(t3["result"])["cleaned"] is True)

# 中断任务（服务重启）留下的资源：下一次执行先清理
ACC3 = core.ex("INSERT INTO accounts(provider,name,region,cred_enc,created) VALUES(?,?,?,?,?)",
               ("oci", "大阪", "ap-osaka-1", core.encrypt(dict(CRED)), 1))
old_t = tasks.create_task("oci_restrict", ACC3, {"name": "大阪"})
tasks._update(old_t, status="interrupted", result={"stage": "user", "created": {"home_region": "ap-tokyo-1", "group_id": "ocid1.group.oc1..old",
                                                                                 "group_name": "TriCloud-Restricted-old", "policy_id": "ocid1.policy.oc1..old"}})
fresh()
tid4 = tasks.create_task("oci_restrict", ACC3, {"name": "大阪"})
asyncio.run(tasks._run_once(core.q("SELECT * FROM tasks WHERE id=?", (tid4,), one=True)))
ok("interrupted leftovers cleaned first", ("policy", "ocid1.policy.oc1..old") in W.deleted and ("group", "ocid1.group.oc1..old") in W.deleted)
ok("interrupted task marked cleaned", json.loads(core.q("SELECT result FROM tasks WHERE id=?", (old_t,), one=True)["result"])["cleaned"] is True)
ok("then switch succeeded", core.q("SELECT status FROM tasks WHERE id=?", (tid4,), one=True)["status"] == "done")

# 停止任务：回滚，凭证不变
ACC4 = core.ex("INSERT INTO accounts(provider,name,region,cred_enc,created) VALUES(?,?,?,?,?)",
               ("oci", "孟买", "ap-osaka-1", core.encrypt(dict(CRED)), 1))
before4 = core.q("SELECT cred_enc FROM accounts WHERE id=?", (ACC4,), one=True)["cred_enc"]
fresh(active_after=99)
tid5 = tasks.create_task("oci_restrict", ACC4, {"name": "孟买"})
_orig_sleep = R._sleep


def stop_then_sleep(sec):
    tasks.stop_task(tid5)
    _orig_sleep(sec)


R._sleep = stop_then_sleep
asyncio.run(tasks._run_once(core.q("SELECT * FROM tasks WHERE id=?", (tid5,), one=True)))
R._sleep = _orig_sleep
t5 = core.q("SELECT * FROM tasks WHERE id=?", (tid5,), one=True)
ok("stopped task: status stopped, rolled back", t5["status"] == "stopped" and len(W.deleted) == 5 and W.violations == [])
ok("stopped task: credentials untouched", core.q("SELECT cred_enc FROM accounts WHERE id=?", (ACC4,), one=True)["cred_enc"] == before4)
ok("stopped task: result notes cleanup", json.loads(t5["result"])["stage"] == "stopped")

# ================= 7. 结构 / 前端 / App / i18n 静态检查 =================
ok("registry: oci_restrict handler + type name", "oci_restrict" in tasks.ONCE_HANDLERS and tasks.TYPE_NAME["oci_restrict"] == "切换受限 API")
ok("main: token rule covers restrict paths", main.RESTRICT_RE.match(f"/api/accounts/{ACC}/oci/restrict") and main.RESTRICT_RE.match("/api/accounts/1/oci/restrict/code")
   and not main.RESTRICT_RE.match("/api/accounts/1/oci/restricted-foo"))
from app import i18n  # noqa: E402
keys = [k for k in i18n.MESSAGES["zh"] if "rapi" in k]
ok("backend i18n zh/en for every rapi key", len(keys) >= 12 and all(k in i18n.MESSAGES["en"] for k in keys))
WJ = rd("web", "js", "accounts.js") + rd("web", "js", "instances.js")
ok("web: button + badge + dialog", "data-rapi" in WJ and "restrictDialog" in WJ and "restrictedTag" in WJ and "/oci/restrict/code" in WJ and "rapiNote" in WJ)
I = rd("web", "js", "i18n.js")
rk = sorted(set(re.findall(r'"(rapi\.[A-Za-z]+)"', I)))
ok("web i18n: rapi keys in zh and en", len(rk) >= 25 and all(I.count(f'"{k}"') == 2 for k in rk))
used = set(re.findall(r't\("(rapi\.[A-Za-z]+)"', WJ))
ok("web i18n: every used key defined", used and used <= set(rk))
ok("web: strong confirm wording", "不会删除或撤销" in I and "NOT deleted or revoked" in I and "不能再管理 IAM" in I and "可以关闭窗口" in I)
zh = rd("android", "app", "src", "main", "res", "values", "strings.xml")
en = rd("android", "app", "src", "main", "res", "values-en", "strings.xml")
az, ae = set(re.findall(r'<string name="(rapi_\w+)"', zh)), set(re.findall(r'<string name="(rapi_\w+)"', en))
A = rd("android", "app", "src", "main", "java", "com", "tricloud", "app", "AccountsActivity.java") + rd("android", "app", "src", "main", "java", "com", "tricloud", "app", "TasksActivity.java")
ok("android: rapi strings zh == en", az == ae and len(az) >= 20)
ok("android: every rapi string used", all("R.string." + k in A for k in az))
J = "android/app/src/main/java/com/tricloud/app/"
AJ = "".join(rd(*(J + f).split("/")) for f in os.listdir(os.path.join(ROOT, J)) if f.endswith(".java"))
ok("android: no static Chinese constants", not re.search(r"static[^(\n]*=[^\n]*[\u4e00-\u9fff]", AJ))
ok("android: flow uses code endpoint + confirm", "/oci/restrict/code" in A and 'put("confirm", true)' in A and "restrictFlow" in A)
S = rd("ios", "TriCloud", "RestrictApi.swift")
IE = rd("ios", "TriCloud", "en.lproj", "Localizable.strings")
IZ = rd("ios", "TriCloud", "zh-Hans.lproj", "Localizable.strings")
lits = set(re.findall(r'L\("([^"]+)"\)', S)) | {"发送 Telegram 验证码", "输入 Telegram 验证码", "开始切换", "我已自己保存好原来的全权限 API Key", "Telegram 验证码（6 位数字）",
                                                "已发送到 Telegram，5 分钟内有效，只能用一次。", "受限 API", "🔒 受限", "切换受限 API"}
ok("ios: every literal localized zh+en", all(f'"{x}" = ' in IE and f'"{x}" = ' in IZ for x in lits))
ok("ios: wired into account management", "restrictFlow(acc)" in rd("ios", "TriCloud", "MainPage.swift") and "oci_restrict" in rd("ios", "TriCloud", "TasksPage.swift"))
ok("ios: flow uses code endpoint + confirm", "/oci/restrict/code" in S and '"confirm": true' in S)
_vc = int(re.search(r"versionCode (\d+)", rd("android", "app", "build.gradle")).group(1))
ok("version >= 30 and Android == iOS", _vc >= 30 and f'CURRENT_PROJECT_VERSION: "{_vc}"' in rd("ios", "project.yml"))
ok("docs build 30", "build 30" in rd("CHANGELOG.md") and "build 30" in rd(".github", "release-notes.md") and "build 30" in rd("docs", "FEATURES.md"))
DM = rd("demo", "mock.js")
ok("demo mock: restrict routes", "route30" in DM and "/oci\\/restrict" in DM)

cl.__exit__(None, None, None)
print(f"{P}/{P+F} passed")
sys.exit(1 if F else 0)
