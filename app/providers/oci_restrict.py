"""build 30：OCI「一键切换受限 API」。

用当前全权限 API Key（只在本流程内使用）在租户根区间创建：组 + 策略 + 用户（名字带 TriCloud 前缀与随机后缀），
给新用户上传一把内存里生成的 RSA 2048 公钥，反复用新 Key 自检（实例 / VCN / 对象存储 / Usage API 可用，IAM 用户列表不可读），
全部通过后才由调用方替换面板里保存的凭证。任一步失败：用全权限 Key 尽力删除本次创建的 Key / 成员关系 / 用户 / 策略 / 组，
面板里的旧凭证保持不变。**绝不删除、也不撤销 OCI 云端原来的 API Key。**

策略语句集中在 POLICY_RULES（docs/api-credentials.md 有逐条说明，按 OCI 官方 policy reference 核对）。
"""
import datetime as dt
import hashlib
import importlib
import re
import secrets
import time


class _LazyOCI:
    """oci SDK 很大：路由模块只读策略常量时不导入（test_structure 要求 import app.main 不加载云 SDK），真正调用时才导入。"""

    def __getattr__(self, name):
        return getattr(importlib.import_module("oci"), name)


oci = _LazyOCI()

PREFIX = "TriCloud"
DESCRIPTION = "Created by TriCloud panel (restricted API, one-click switch)"
WAIT_SECONDS = 600       # 新 Key / 新策略生效最多等 10 分钟
RETRY_INTERVAL = 20      # 每轮自检间隔

# (动词, 资源类型, 用途)。只给面板代码实际调用到的接口所需权限；IAM 类（用户 / 组 / 策略 / 域 / 动态组）一律不给。
# 资源类型名按 OCI 官方文档核对：
#   Core（instance-family / volume-family / virtual-network-family / instance-agent-*）https://docs.oracle.com/en-us/iaas/Content/Identity/Reference/corepolicyreference.htm
#   object-family https://docs.oracle.com/en-us/iaas/Content/Identity/Reference/objectstoragepolicyreference.htm
#   network-load-balancers https://docs.oracle.com/en-us/iaas/Content/Identity/policyreference/nlbpolicyreference.htm
#   metrics https://docs.oracle.com/en-us/iaas/Content/Identity/Reference/monitoringpolicyreference.htm
#   resource-availability https://docs.oracle.com/en-us/iaas/Content/General/service-limits/overview.htm
#   usage-report https://docs.oracle.com/en-us/iaas/Content/Billing/Concepts/costanalysisoverview.htm
#   accountmanagement-family（osp-gateway 订阅，只读）https://docs.oracle.com/en-us/iaas/Content/Billing/Concepts/billingtoolsoverview.htm
#   organizations-subscription（Tenant Manager 订阅，只读）https://docs.oracle.com/en-us/iaas/Content/Identity/policyreference/organizationsreference.htm
#   compartments / tenancies（IAM 只读 inspect）https://docs.oracle.com/en-us/iaas/Content/Identity/Reference/iampolicyreference.htm
POLICY_RULES = (
    ("manage", "instance-family", "实例：列表 / 创建 / 抢机 / 开关机 / 改名 / 改配置 / 重装 / 删除、镜像、挂卷"),
    ("manage", "volume-family", "引导卷 / 块存储卷：查看、扩容、改性能、创建 / 挂载 / 删除"),
    ("manage", "virtual-network-family", "网络：VCN / 子网 / 安全列表 / 安全组 / 公网 IP（换 IP、预留 IP）/ IPv6 / 路由表 / 网关"),
    ("manage", "object-family", "对象存储：Bucket / 对象 / 保号账单分片上传 / 预认证下载链接"),
    ("manage", "network-load-balancers", "免费 AMD 下行 500Mbps（网络负载均衡器）"),
    ("read", "instance-agent-plugins", "读取 Oracle Cloud Agent 插件状态（Run Command 是否可用）"),
    ("use", "instance-agent-command-family", "扩容后扩展根分区（Run Command 固定脚本）"),
    ("read", "metrics", "实例流量统计（Monitoring，只读）"),
    ("read", "resource-availability", "配额 / 免费额度剩余（Limits，只读）"),
    ("read", "usage-report", "本月账单（Usage API，只读）"),
    ("read", "accountmanagement-family", "账号类型 / 开户时间（osp-gateway 订阅，只读）"),
    ("read", "organizations-subscription", "账号类型兜底（Tenant Manager 订阅，只读）"),
    ("inspect", "compartments", "子区间列表（对象存储扫描等，只读）"),
    ("inspect", "tenancies", "租户信息 / 区域订阅列表（只读；不能订阅新区域）"),
)

# 绝不允许出现在策略里的资源类型（任何动词都不行）
FORBIDDEN_RESOURCES = ("users", "groups", "policies", "domains", "identity-domains", "dynamic-groups", "all-resources",
                       "authentication-policies", "identity-providers", "network-sources", "tag-namespaces", "credentials",
                       "api-keys", "auth-tokens", "customer-secret-keys", "smtp-credentials")
# 账单 / 订阅类资源只能 read / inspect
BILLING_RESOURCES = ("usage-report", "usage-reports", "usage-budgets", "accountmanagement-family", "organizations-subscription",
                     "organizations-family", "subscription", "invoices", "billing-schedules", "subscribed-services", "rate-cards")
_STMT_RE = re.compile(r"^Allow group (?P<g>[A-Za-z0-9_\-]+) to (?P<verb>inspect|read|use|manage) (?P<res>[a-z0-9\-]+) in tenancy$")


class RestrictError(RuntimeError):
    """给用户看的友好错误（不含凭证）。kind：precheck / create / verify / stopped / error。"""

    def __init__(self, msg, kind="error", cleanup=None):
        super().__init__(msg)
        self.kind = kind
        self.cleanup = cleanup or []


def policy_statements(group_name):
    return [f"Allow group {group_name} to {v} {r} in tenancy" for v, r, _ in POLICY_RULES]


def check_statements(stmts):
    """返回问题列表（空 = 安全）：不认识的语句格式、禁用资源、账单类非只读、in tenancy 以外的范围。"""
    bad = []
    for s in stmts:
        m = _STMT_RE.match(s)
        if not m:
            bad.append(f"格式不符：{s}")
            continue
        res, verb = m.group("res"), m.group("verb")
        if res in FORBIDDEN_RESOURCES:
            bad.append(f"禁止的资源类型：{s}")
        if res in BILLING_RESOURCES and verb not in ("inspect", "read"):
            bad.append(f"账单 / 订阅只能只读：{s}")
    return bad


def names(suffix=None):
    sfx = suffix or secrets.token_hex(3)
    return {"suffix": sfx, "group": f"{PREFIX}-Restricted-{sfx}", "policy": f"{PREFIX}-Restricted-{sfx}",
            "user": f"{PREFIX}-API-{sfx}"}


# ---------------- 密钥 ----------------
def gen_keypair():
    """内存里生成 RSA 2048：返回 (私钥 PEM, 公钥 PEM, 指纹)。私钥不落盘、不加口令（与面板现有存储一致，Fernet 加密入库）。"""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    k = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    priv = k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
    pub_obj = k.public_key()
    pub = pub_obj.public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    return priv, pub, fingerprint_of(pub_obj)


def fingerprint_of(public_key):
    """OCI API Key 指纹 = 公钥 DER（SubjectPublicKeyInfo）的 MD5，冒号分隔小写十六进制。"""
    from cryptography.hazmat.primitives import serialization
    if isinstance(public_key, str):
        public_key = serialization.load_pem_public_key(public_key.encode())
    der = public_key.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    h = hashlib.md5(der).hexdigest()   # noqa: S324 —— OCI 规定的指纹算法，不用于安全校验
    return ":".join(h[i:i + 2] for i in range(0, 32, 2))


# ---------------- 客户端（测试里替换 _client）----------------
def _client(cls, cfg, proxy=None):
    c = cls(cfg)
    if proxy:
        c.base_client.session.proxies = {"http": proxy, "https": proxy}
    return c


def _status(e):
    return getattr(e, "status", None)


def _short(e):
    return str(getattr(e, "message", None) or getattr(e, "code", None) or e)[:200]


def full_config(cred, region=None):
    cfg = {"user": cred["user"], "tenancy": cred["tenancy"], "fingerprint": cred["fingerprint"],
           "key_content": cred["key_content"], "region": region or cred.get("region")}
    if cred.get("pass_phrase"):
        cfg["pass_phrase"] = cred["pass_phrase"]
    return cfg


def home_region(cfg, proxy=None):
    idc = _client(oci.identity.IdentityClient, cfg, proxy)
    subs = idc.list_region_subscriptions(cfg["tenancy"]).data
    return next((s.region_name for s in subs if s.is_home_region), cfg["region"])


def precheck(cfg, proxy=None, log=lambda m, lv="info": None):
    """只读预检：主区域、当前用户在 Default 域（IAM 用户接口能读到自己）、能读组 / 策略（有 IAM 管理权限的前提）。"""
    try:
        home = home_region(cfg, proxy)
    except oci.exceptions.ServiceError as e:
        raise RestrictError(f"读取区域订阅失败（{_short(e)}），当前 API 不可用或权限不足", "precheck")
    idh = _client(oci.identity.IdentityClient, dict(cfg, region=home), proxy)
    try:
        me = idh.get_user(cfg["user"]).data
    except oci.exceptions.ServiceError as e:
        raise RestrictError("当前 API 用户不在 Default 域，或没有 IAM 读权限（0 权号 / 已是受限 API），无法自动切换；"
                            f"请用 Default 域管理员的 API Key（{_short(e)}）", "precheck")
    try:
        idh.list_groups(cfg["tenancy"], limit=1)
        idh.list_policies(cfg["tenancy"], limit=1)
    except oci.exceptions.ServiceError as e:
        raise RestrictError(f"当前 API 没有 IAM 管理权限（读不到组 / 策略：{_short(e)}），无法创建受限用户", "precheck")
    log(f"预检通过：主区域 {home}，当前用户 {getattr(me, 'name', '-')}（Default 域）")
    return home, idh, getattr(me, "email", None)


def _plus_email(email, user_name):
    if not email or "@" not in email:
        return None
    local, dom = email.split("@", 1)
    return f"{local.split('+', 1)[0]}+{user_name.lower()}@{dom}"


# ---------------- 自检 ----------------
CHECKS = ("instances", "vcns", "object_storage", "usage_api", "iam_denied")


def verify_new_key(new_cfg, compartment, proxy=None):
    """用新 Key 做一轮自检。返回 (全部通过, {检查名: (ok, 说明)})。IAM 拒绝只在前面都通过（Key 已生效）后才判断。"""
    res = {}
    try:
        cc = _client(oci.core.ComputeClient, new_cfg, proxy)
        cc.list_instances(compartment_id=compartment, limit=1)
        res["instances"] = (True, "")
        vn = _client(oci.core.VirtualNetworkClient, new_cfg, proxy)
        vn.list_vcns(compartment_id=compartment, limit=1)
        res["vcns"] = (True, "")
        osc = _client(oci.object_storage.ObjectStorageClient, new_cfg, proxy)
        ns = osc.get_namespace(compartment_id=new_cfg["tenancy"]).data
        osc.list_buckets(ns, compartment, limit=1)
        res["object_storage"] = (True, "")
    except oci.exceptions.ServiceError as e:
        k = next(c for c in CHECKS if c not in res)
        res[k] = (False, f"{_status(e)} {_short(e)}")
        return False, res
    home = new_cfg.get("_home") or new_cfg["region"]
    cfg_home = {k: v for k, v in new_cfg.items() if k != "_home"}
    try:
        ua = _client(oci.usage_api.UsageapiClient, dict(cfg_home, region=home), proxy)
        now = dt.datetime.now(dt.timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        ua.request_summarized_usages(oci.usage_api.models.RequestSummarizedUsagesDetails(
            tenant_id=new_cfg["tenancy"], time_usage_started=now - dt.timedelta(days=1), time_usage_ended=now,
            granularity="DAILY", query_type="COST"))
        res["usage_api"] = (True, "")
    except oci.exceptions.ServiceError as e:
        res["usage_api"] = (False, f"{_status(e)} {_short(e)}")
        return False, res
    idn = _client(oci.identity.IdentityClient, dict(cfg_home, region=home), proxy)
    try:
        idn.list_users(new_cfg["tenancy"], limit=1)
        res["iam_denied"] = (False, "新 Key 仍能读取 IAM 用户列表")
        return False, res
    except oci.exceptions.ServiceError as e:
        if _status(e) not in (401, 403, 404):
            res["iam_denied"] = (False, f"{_status(e)} {_short(e)}")
            return False, res
    try:
        idn.list_domains(new_cfg["tenancy"], limit=1)
        res["iam_denied"] = (True, "IAM 用户不可读（身份域列表可读，但没有管理权限）")
    except oci.exceptions.ServiceError:
        res["iam_denied"] = (True, "IAM 用户 / 身份域都不可读")
    return True, res


CHECK_LABEL = {"instances": "实例列表", "vcns": "VCN 列表", "object_storage": "对象存储", "usage_api": "Usage API 账单",
               "iam_denied": "IAM 已禁止"}


def _fmt_checks(res):
    return "；".join(f"{CHECK_LABEL[k]} {'✓' if ok else '✗ ' + why}" + (f"（{why}）" if ok and why else "")
                    for k, (ok, why) in res.items())


# ---------------- 清理（失败回滚，用全权限 Key）----------------
def cleanup(idh, created, log=lambda m, lv="info": None):
    """尽力删除本次创建的资源（顺序：API Key → 组成员 → 用户 → 策略 → 组）。返回 [(资源, ok, 说明)]。
    只删 created 里记录的 OCID；原来的 API Key / 用户从不出现在 created 里，所以不可能被删。"""
    out = []

    def one(label, fn, *a):
        try:
            fn(*a)
            out.append((label, True, ""))
            log(f"已删除 {label}")
        except Exception as e:   # noqa: BLE001
            if _status(e) == 404:
                out.append((label, True, "已不存在"))
            else:
                out.append((label, False, _short(e)))
                log(f"删除 {label} 失败：{_short(e)}", "warn")
    if created.get("user_id") and created.get("key_fingerprint"):
        one("新 API Key", idh.delete_api_key, created["user_id"], created["key_fingerprint"])
    if created.get("membership_id"):
        one("组成员关系", idh.remove_user_from_group, created["membership_id"])
    if created.get("user_id"):
        one("用户 " + created.get("user_name", ""), idh.delete_user, created["user_id"])
    if created.get("policy_id"):
        one("策略 " + created.get("policy_name", ""), idh.delete_policy, created["policy_id"])
    if created.get("group_id"):
        one("组 " + created.get("group_name", ""), idh.delete_group, created["group_id"])
    return out


def cleanup_text(res):
    if not res:
        return "本次没有创建云端资源"
    bad = [f"{l}（{w}）" for l, ok, w in res if not ok]
    if not bad:
        return "已清理本次创建的 " + "、".join(l for l, _, _ in res)
    return "部分清理失败，请到 OCI 控制台手动删除：" + "、".join(bad)


# ---------------- 主流程 ----------------
_sleep = time.sleep
_clock = time.monotonic


def run_switch(cred, log=lambda m, lv="info": None, step=lambda m: None, on_created=lambda c: None,
               wait_seconds=None, interval=None, sleep=None, clock=None, suffix=None):
    """cred：账号当前（全权限）运行时凭证（proxy 已合成）。成功返回新凭证字段 + 创建的资源信息；失败抛 RestrictError（已回滚）。
    step(msg)：进度 / 安全点（任务被停止时抛异常，同样会回滚）。on_created(created)：每创建一个资源回调一次（写进任务结果，便于中断后清理）。"""
    wait_seconds = WAIT_SECONDS if wait_seconds is None else wait_seconds
    interval = RETRY_INTERVAL if interval is None else interval
    sleep, clock = sleep or _sleep, clock or _clock   # 测试要同时替换 _sleep 和 _clock（只换一个会忙等）
    proxy = cred.get("proxy")
    cfg = full_config(cred)
    compartment = cred.get("compartment") or cred["tenancy"]
    step("预检：主区域、Default 域、IAM 权限…")
    home, idh, my_email = precheck(cfg, proxy, log)
    nm = names(suffix)
    stmts = policy_statements(nm["group"])
    bad = check_statements(stmts)
    if bad:   # 代码里的策略被改坏时兜底，绝不创建
        raise RestrictError("内置策略校验失败：" + "；".join(bad), "precheck")
    created = {"home_region": home, "group_name": nm["group"], "policy_name": nm["policy"], "user_name": nm["user"]}
    M = oci.identity.models
    tenancy = cfg["tenancy"]
    try:
        step(f"创建组 {nm['group']}…")
        g = idh.create_group(M.CreateGroupDetails(compartment_id=tenancy, name=nm["group"], description=DESCRIPTION)).data
        created["group_id"] = g.id
        on_created(dict(created))
        log(f"已创建组 {nm['group']}")
        step(f"创建策略 {nm['policy']}（租户根区间，{len(stmts)} 条语句）…")
        p = idh.create_policy(M.CreatePolicyDetails(compartment_id=tenancy, name=nm["policy"], description=DESCRIPTION,
                                                    statements=stmts)).data
        created["policy_id"] = p.id
        on_created(dict(created))
        log(f"已创建策略 {nm['policy']}")
        step(f"创建用户 {nm['user']}…")
        try:
            u = idh.create_user(M.CreateUserDetails(compartment_id=tenancy, name=nm["user"], description=DESCRIPTION)).data
        except oci.exceptions.ServiceError as e:
            alt = _plus_email(my_email, nm["user"])
            if _status(e) == 400 and "mail" in str(getattr(e, "message", "")).lower() and alt:
                log("该租户创建用户需要邮箱，使用当前管理员邮箱的 + 别名")
                u = idh.create_user(M.CreateUserDetails(compartment_id=tenancy, name=nm["user"], description=DESCRIPTION,
                                                        email=alt)).data
            else:
                raise
        created["user_id"] = u.id
        on_created(dict(created))
        log(f"已创建用户 {nm['user']}")
        try:   # 只允许 API Key：不能控制台登录、不能建 Auth Token / SMTP / 客户密钥（失败不影响主流程）
            idh.update_user_capabilities(u.id, M.UpdateUserCapabilitiesDetails(
                can_use_console_password=False, can_use_api_keys=True, can_use_auth_tokens=False, can_use_smtp_credentials=False,
                can_use_db_credentials=False, can_use_customer_secret_keys=False, can_use_o_auth2_client_credentials=False))
        except Exception as e:   # noqa: BLE001
            log(f"限制用户能力失败（不影响使用）：{_short(e)}", "warn")
        step("把用户加入组…")
        m = idh.add_user_to_group(M.AddUserToGroupDetails(user_id=u.id, group_id=g.id)).data
        created["membership_id"] = m.id
        on_created(dict(created))
        step("生成 RSA 2048 密钥并上传公钥…")
        priv, pub, fp = gen_keypair()
        k = idh.upload_api_key(u.id, M.CreateApiKeyDetails(key=pub)).data
        created["key_fingerprint"] = getattr(k, "fingerprint", None) or fp
        on_created(dict(created))
        if created["key_fingerprint"] != fp:
            raise RestrictError(f"OCI 返回的指纹 {created['key_fingerprint']} 与本地计算的 {fp} 不一致", "create")
        log(f"已上传新 API Key（指纹 {fp}）")
        new_cfg = {"user": u.id, "tenancy": tenancy, "fingerprint": fp, "key_content": priv, "region": cfg["region"], "_home": home}
        deadline = clock() + wait_seconds
        n = 0
        while True:
            n += 1
            step(f"等待新 Key 与策略生效，第 {n} 次自检…")
            ok, res = verify_new_key(new_cfg, compartment, proxy)
            if ok:
                log("自检通过：" + _fmt_checks(res), "ok")
                break
            if res.get("iam_denied") == (False, "新 Key 仍能读取 IAM 用户列表"):
                raise RestrictError("新 Key 仍能读取 IAM 用户列表，权限没有按预期受限，已放弃切换", "verify")
            log(f"第 {n} 次自检未通过：{_fmt_checks(res)}")
            if clock() + interval > deadline:
                raise RestrictError(f"等待约 {wait_seconds // 60} 分钟后新 Key 仍未通过自检（{_fmt_checks(res)}），已放弃切换", "verify")
            sleep(interval)
        return {"user": u.id, "fingerprint": fp, "key_content": priv, "home_region": home, "created": created,
                "statements": stmts, "checks": {k: v[1] for k, v in res.items()}}
    except BaseException as e:
        log(f"切换失败，开始回滚本次创建的资源（不会动原 API Key）：{_short(e)}", "warn")
        cl = cleanup(idh, created, log)
        if isinstance(e, RestrictError):
            e.cleanup = cl
            raise
        if isinstance(e, oci.exceptions.ServiceError):
            raise RestrictError(f"OCI 返回错误（{_status(e)} {_short(e)}）", "create", cl) from None
        if isinstance(e, Exception) and type(e).__name__ != "TaskStopped":
            raise RestrictError(_short(e), "error", cl) from None
        e.cleanup = cl   # TaskStopped / KeyboardInterrupt：原样抛出，调用方读取清理结果
        raise
