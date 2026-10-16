"""build 20：AWS 新账号 Free Tier Credit（混入 AWSProvider）。

- 查询：freetier GetAccountPlanState（计划类型 / 剩余 credit / 到期）+ ListAccountActivities（zh-CN）+ GetAccountActivity（完成时间等），
  freetier 端点固定 us-east-1，这三个接口都免费。
- 一键完成 5 个官方活动（https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/free-tier-plans-activities.html）：
  EC2 / Budgets / Lambda / RDS / Bedrock，以最低成本执行，用完自动清理；创建的资源都打标签 tricloud-credit=1。
- AWS 没有公开说明用 API 完成的操作是否计入活动，所以执行后只能说「已执行，等待 AWS 识别」，以 ListAccountActivities 的状态为准。

这里只依赖 botocore 的异常类型（在函数里按需取），boto3 由 aws_provider 懒加载。
"""
import concurrent.futures as cf
import io
import json
import secrets
import string
import time
import zipfile

from ..core import AwsCreditError

FT_REGION = "us-east-1"          # freetier / budgets / bedrock（Nova Micro）都用 us-east-1
TAG_KEY, TAG_VAL = "tricloud-credit", "1"
TAGS = [{"Key": TAG_KEY, "Value": TAG_VAL}]
BUDGET_NAME = "tricloud-credit-budget"
LAMBDA_FN = "tricloud-credit-web"
LAMBDA_ROLE = "tricloud-credit-lambda-role"
RDS_PREFIX = "tricloud-credit-db"
EC2_NAME = "tricloud-credit-ec2"
EC2_TYPES = ("t3.micro", "t2.micro")
RDS_CLASSES = ("db.t4g.micro", "db.t3.micro")
AL2023_PARAM = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64"
BEDROCK_MODELS = ("amazon.nova-micro-v1:0", "us.amazon.nova-micro-v1:0")
LAMBDA_RUNTIME = "python3.13"

ACT_KEYS = ("ec2", "budgets", "lambda", "rds", "bedrock")
ACT_INFO = {
    "ec2": {"label": "EC2 启动实例", "kw": ("ec2",),
            "plan": "在账号默认区域启动 1 台最小免费级实例（t3.micro / t2.micro，Amazon Linux 2023，默认 VPC，无密钥对），"
                    "运行约 5 分钟后终止（实例还设了 30 分钟自动关机终止兜底）。约 $0.001，从 credit 扣。",
            "perms": ["ec2:RunInstances", "ec2:DescribeInstances", "ec2:TerminateInstances", "ec2:CreateTags",
                      "ec2:DescribeInstanceTypeOfferings", "ssm:GetParameter（或 ec2:DescribeImages）"]},
    "budgets": {"label": "Budgets 成本预算", "kw": ("budget", "预算"),
                "plan": f"创建月度成本预算 {BUDGET_NAME}（$1，不加通知）。预算本身免费，默认保留；可在「清理残留」里一并删除。",
                "perms": ["budgets:ModifyBudget", "budgets:ViewBudget", "budgets:TagResource"]},
    "lambda": {"label": "Lambda 网页应用", "kw": ("lambda",),
               "plan": f"创建最小执行角色 {LAMBDA_ROLE}（不附加任何策略）+ Python 函数 {LAMBDA_FN} + 函数 URL（公开访问），"
                       "访问一次 URL 验证；保留 10 分钟后自动删除函数、URL 和角色（URL 是公开的，不长期保留）。几乎为 $0。",
               "perms": ["iam:CreateRole", "iam:GetRole", "iam:PassRole", "iam:TagRole", "iam:DeleteRole", "lambda:CreateFunction",
                         "lambda:GetFunction", "lambda:CreateFunctionUrlConfig", "lambda:AddPermission", "lambda:DeleteFunction",
                         "lambda:TagResource"]},
    "rds": {"label": "RDS 数据库", "kw": ("rds", "aurora"),
            "plan": "在账号默认区域创建最小 MySQL 实例（db.t4g.micro / db.t3.micro，20 GB gp2，单可用区，不开公网，不备份，随机密码不保存不显示），"
                    "可用后约 1 分钟删除（跳过最终快照、删除自动备份）。创建 + 删除约 15–30 分钟，约 $0.01，从 credit 扣。",
            "perms": ["rds:CreateDBInstance", "rds:DescribeDBInstances", "rds:DeleteDBInstance", "rds:AddTagsToResource",
                      "rds:DescribeOrderableDBInstanceOptions"]},
    "bedrock": {"label": "Bedrock 基础模型", "kw": ("bedrock",),
                "plan": "在 us-east-1 用 Converse 调用 Amazon Nova Micro 发一句话（几十个 token，不到 $0.0001）。",
                "note": "官方要求的是「在 Amazon Bedrock playground 里使用基础模型」，用 API 调用不一定会被计入；如长时间不更新，请到控制台 playground 手动发一句。",
                "perms": ["bedrock:InvokeModel（Converse 使用该权限）"]},
}
FREETIER_PERMS = ["freetier:GetAccountPlanState", "freetier:ListAccountActivities", "freetier:GetAccountActivity"]

_sleep = time.sleep                 # 测试里替换为假时钟
_now = time.time
WAIT_STEP = 5                       # 等待时每 5 秒检查一次「停止任务」


def _code(e):
    r = getattr(e, "response", None) or {}
    return (r.get("Error") or {}).get("Code") or ""


def _msg(e):
    r = getattr(e, "response", None) or {}
    return str((r.get("Error") or {}).get("Message") or e)[:240]


def is_denied(e):
    c = _code(e)
    return c.startswith("AccessDenied") or c in ("UnauthorizedOperation", "AuthorizationError", "UnauthorizedException",
                                                  "NotAuthorized", "AccessDeniedException")


def friendly(e, key=None):
    """把云厂商异常转成一句中文（不带异常栈）。"""
    if isinstance(e, AwsCreditError):
        return str(e)
    c = _code(e)
    info = ACT_INFO.get(key or "", {})
    if is_denied(e):
        perms = "、".join(info.get("perms") or []) or "对应服务的权限"
        return f"权限不足（{c}）：该 IAM 用户需要 {perms}"
    table = {
        "OptInRequired": "账号或该区域尚未启用（OptInRequired）：新账号可能还在验证，或该区域需先在「区域」页启用",
        "PendingVerification": "账号仍在验证中（PendingVerification），新账号通常要几分钟到几小时，稍后再试",
        "VPCIdNotSpecified": "该区域没有默认 VPC，无法用最省事的方式启动实例；请在 VPC 控制台创建默认 VPC 后再试",
        "MissingInput": "该区域没有默认 VPC / 子网，请在 VPC 控制台创建默认 VPC 后再试",
        "InstanceLimitExceeded": "实例数量配额不足（InstanceLimitExceeded）",
        "VcpuLimitExceeded": "vCPU 配额不足（VcpuLimitExceeded），新账号配额可能为 0，请到配额页申请",
        "InsufficientInstanceCapacity": "该区域暂时没有这个实例类型的容量，稍后再试",
        "Unsupported": "该区域 / 可用区不支持这个实例类型",
        "DBInstanceQuotaExceeded": "RDS 实例数量配额不足",
        "InsufficientDBInstanceCapacity": "该区域暂时没有这个 RDS 规格的容量，稍后再试",
        "StorageQuotaExceeded": "RDS 存储配额不足",
        "ThrottlingException": "请求太频繁被 AWS 限流，稍后再试",
        "Throttling": "请求太频繁被 AWS 限流，稍后再试",
        "TooManyRequestsException": "请求太频繁被 AWS 限流，稍后再试",
        "ServiceQuotaExceededException": "服务配额不足",
        "InvalidClientTokenId": "Access Key 无效或已删除",
        "SignatureDoesNotMatch": "Secret Key 不正确",
        "ExpiredToken": "凭证已过期",
    }
    if c in table:
        return table[c]
    if c:
        return f"{c}：{_msg(e)}"
    name = type(e).__name__
    if name in ("EndpointConnectionError", "ConnectTimeoutError", "ReadTimeoutError", "ConnectionClosedError"):
        return "连接 AWS 超时或失败，请检查网络 / 账号代理后重试"
    return f"{name}：{str(e)[:200]}"


class _Ctx:
    """活动执行上下文：log(消息, 级别) 写任务日志；step(消息) 是安全点（任务被停止时抛出 TaskStopped）；note(消息) 只更新进度。"""

    def __init__(self, log=None, step=None, note=None):
        self.log = log or (lambda m, lv="info": None)
        self.step = step or (lambda m: None)
        self.note = note or (lambda m: None)

    def sleep(self, seconds, msg=None):
        end = _now() + max(0, seconds)
        while True:
            left = end - _now()
            if left <= 0:
                return
            if msg:
                self.step(msg.format(left=int(left)))
            _sleep(min(WAIT_STEP, left))


def _wait(ctx, fn, ok, timeout, every=5, msg=None):
    """轮询 fn() 直到 ok(结果) 为真；超时返回最后一次结果（调用方决定是否算失败）。"""
    start = _now()
    last = None
    while True:
        last = fn()
        if ok(last):
            return last, True
        waited = _now() - start
        if waited >= timeout:
            return last, False
        if msg:
            ctx.step(msg(last, int(waited)))
        _sleep(every)


def _rds_password():
    alpha = string.ascii_letters + string.digits
    return "Tc" + "".join(secrets.choice(alpha) for _ in range(22))


def _lambda_zip():
    code = ("import json\n\n"
            "def lambda_handler(event, context):\n"
            "    return {'statusCode': 200, 'headers': {'Content-Type': 'text/html; charset=utf-8'},\n"
            "            'body': '<h1>Hello from TriCloud</h1><p>AWS Free Tier credit activity</p>'}\n")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("lambda_function.py", code)
    return buf.getvalue()


def match_key(act):
    """AWS 活动 → 我们的活动 key（按 activityId / 标题里的服务名匹配）。"""
    s = (str(act.get("activityId") or act.get("activity_id") or "") + " " + str(act.get("title") or "")).lower()
    for k in ("bedrock", "budgets", "lambda", "rds", "ec2"):      # bedrock 先于 ec2（标题里可能同时提到实例）
        if any(w in s for w in ACT_INFO[k]["kw"]):
            return k
    return None


def _iso(v):
    if v in (None, ""):
        return None
    try:
        return v.isoformat()
    except AttributeError:
        return str(v)


class AWSCredit:
    # ---------------- 查询 ----------------
    def _ft(self):
        ft = self.c("freetier", FT_REGION)
        if not hasattr(ft, "get_account_plan_state") or not hasattr(ft, "list_account_activities"):
            raise AwsCreditError("面板的 boto3 / botocore 版本过旧，不含 freetier GetAccountPlanState / ListAccountActivities，请升级后重建镜像",
                                 kind="unsupported")
        return ft

    def credit_state(self):
        """返回 {plan, activities}；无权限 / 不适用时抛 AwsCreditError(kind=denied / not_applicable)。"""
        ft = self._ft()
        try:
            ps = ft.get_account_plan_state()
        except Exception as e:
            raise self._ft_err(e)
        if not ps.get("accountPlanType") and not ps.get("accountPlanStatus"):
            raise AwsCreditError("该账号不适用新免费计划（AWS 未返回计划信息）", kind="not_applicable")
        rc = ps.get("accountPlanRemainingCredits") or {}
        plan = {"account_id": ps.get("accountId"), "type": ps.get("accountPlanType"), "status": ps.get("accountPlanStatus"),
                "remaining": rc.get("amount"), "unit": rc.get("unit") or "USD", "expires": _iso(ps.get("accountPlanExpirationDate"))}
        acts, tok = [], None
        try:
            for _ in range(10):
                kw = {"languageCode": "zh-CN", "maxResults": 20}
                if tok:
                    kw["nextToken"] = tok
                r = ft.list_account_activities(**kw)
                acts += r.get("activities") or []
                tok = r.get("nextToken")
                if not tok:
                    break
        except Exception as e:
            err = self._ft_err(e)
            if err.kind == "denied":
                return {"plan": plan, "activities": [], "activities_error": str(err), "activities_denied": True}
            raise err

        def detail(a):
            try:
                return ft.get_account_activity(activityId=a["activityId"], languageCode="zh-CN")
            except Exception:
                return {}
        with cf.ThreadPoolExecutor(max_workers=5) as ex:
            details = list(ex.map(detail, acts))
        out = []
        for a, d in zip(acts, details):
            cr = ((d.get("reward") or a.get("reward") or {}).get("credit") or {})
            out.append({"activity_id": a.get("activityId"), "title": d.get("title") or a.get("title"), "status": d.get("status") or a.get("status"),
                        "reward": cr.get("amount"), "unit": cr.get("unit") or "USD", "description": d.get("description"),
                        "instructions_url": d.get("instructionsUrl"), "est_minutes": d.get("estimatedTimeToCompleteInMinutes"),
                        "started_at": _iso(d.get("startedAt")), "completed_at": _iso(d.get("completedAt")),
                        "expires_at": _iso(d.get("expiresAt")), "key": match_key(a)})
        return {"plan": plan, "activities": out}

    @staticmethod
    def _ft_err(e):
        if isinstance(e, AwsCreditError):
            return e
        c = _code(e)
        if is_denied(e):
            return AwsCreditError("没有 freetier 读权限：请给该 IAM 用户添加只读权限 " + " / ".join(FREETIER_PERMS), kind="denied")
        if c in ("ResourceNotFoundException", "ValidationException", "NotFoundException") or "not applicable" in _msg(e).lower() \
                or "not eligible" in _msg(e).lower():
            return AwsCreditError("该账号不适用新免费计划 Credit 活动（AWS 返回：" + _msg(e)[:120] + "）。"
                                  "只有 2025-07-15 之后注册、使用新免费计划的账号才有这些活动", kind="not_applicable")
        return AwsCreditError("查询 Free Tier 状态失败：" + friendly(e), kind="error")

    # ---------------- 执行前权限检查（只读 / DryRun，免费） ----------------
    def credit_precheck(self, key):
        """确认账号有该活动需要的权限；缺权限抛 AwsCreditError（文案带所需权限）。返回检查说明。"""
        from botocore.exceptions import ClientError
        try:
            if key == "ec2":
                itype, ami = self._ec2_pick()
                try:
                    self.c("ec2").run_instances(ImageId=ami, InstanceType=itype, MinCount=1, MaxCount=1, DryRun=True)
                except ClientError as e:
                    if _code(e) != "DryRunOperation":
                        raise
                return f"DryRun 通过（{itype} · {ami}）"
            if key == "budgets":
                self.c("budgets", FT_REGION).describe_budgets(AccountId=self._account_id(), MaxResults=1)
                return "可读取预算"
            if key == "lambda":
                self.c("lambda").list_functions(MaxItems=1)
                try:
                    self.c("iam").get_role(RoleName=LAMBDA_ROLE)
                except ClientError as e:
                    if _code(e) != "NoSuchEntity":
                        raise
                return "可访问 Lambda 与 IAM"
            if key == "rds":
                self.c("rds").describe_db_instances(MaxRecords=20)
                self._rds_class()
                return "可访问 RDS"
            if key == "bedrock":
                return "Bedrock 无免费的预检接口，执行时直接调用"
        except AwsCreditError:
            raise
        except Exception as e:
            raise AwsCreditError(friendly(e, key), kind="denied" if is_denied(e) else "error")
        raise AwsCreditError(f"未知活动：{key}", kind="error")

    def _account_id(self):
        if not getattr(self, "_acct_id", None):
            self._acct_id = self.c("sts").get_caller_identity()["Account"]
        return self._acct_id

    # ---------------- 执行 ----------------
    def credit_run(self, key, opts=None, ctx=None):
        """执行一个活动（同步，后台任务里在线程中调用）。返回结果 dict；失败抛 AwsCreditError（友好文案）。
        停止任务（TaskStopped）原样抛出，但 finally 里仍会清理已创建的资源。"""
        opts = opts or {}
        ctx = ctx or _Ctx()
        fn = {"ec2": self._run_ec2, "budgets": self._run_budgets, "lambda": self._run_lambda,
              "rds": self._run_rds, "bedrock": self._run_bedrock}.get(key)
        if not fn:
            raise AwsCreditError(f"未知活动：{key}")
        ctx.step(f"检查权限：{ACT_INFO[key]['label']}…")
        ctx.log("权限检查：" + self.credit_precheck(key))
        try:
            return fn(opts, ctx)
        except AwsCreditError:
            raise
        except Exception as e:
            if type(e).__name__ == "TaskStopped":
                raise
            raise AwsCreditError(friendly(e, key), kind="denied" if is_denied(e) else "error")

    # ---- EC2 ----
    def _ec2_pick(self):
        if getattr(self, "_ec2_choice", None):
            return self._ec2_choice
        ec2 = self.c("ec2")
        offered = {o["InstanceType"] for o in ec2.describe_instance_type_offerings(
            LocationType="region", Filters=[{"Name": "instance-type", "Values": list(EC2_TYPES)}]).get("InstanceTypeOfferings", [])}
        itype = next((t for t in EC2_TYPES if t in offered), None)
        if not itype:
            raise AwsCreditError(f"该区域（{self.region}）不提供 {' / '.join(EC2_TYPES)}，请把账号默认区域换成常见区域后再试")
        try:
            ami = self.c("ssm").get_parameter(Name=AL2023_PARAM)["Parameter"]["Value"]
        except Exception:
            imgs = ec2.describe_images(Owners=["amazon"], Filters=[{"Name": "name", "Values": ["al2023-ami-2023*-kernel-*-x86_64"]},
                                                                   {"Name": "state", "Values": ["available"]}]).get("Images", [])
            if not imgs:
                raise AwsCreditError("找不到 Amazon Linux 2023 镜像（SSM 公开参数与 DescribeImages 都失败）")
            ami = max(imgs, key=lambda i: i.get("CreationDate", ""))["ImageId"]
        self._ec2_choice = (itype, ami)
        return self._ec2_choice

    def _ec2_state(self, iid):
        try:
            r = self.c("ec2").describe_instances(InstanceIds=[iid])["Reservations"]
            return r[0]["Instances"][0]["State"]["Name"] if r else "terminated"
        except Exception as e:
            if _code(e) == "InvalidInstanceID.NotFound":
                return "pending"
            raise

    def _run_ec2(self, opts, ctx):
        hold = max(0, min(60, int(opts.get("hold_minutes", 5))))
        itype, ami = self._ec2_pick()
        ec2 = self.c("ec2")
        iid = None
        try:
            ctx.step(f"启动 {itype}（{self.region}）…")
            safety = hold + 25
            r = ec2.run_instances(
                ImageId=ami, InstanceType=itype, MinCount=1, MaxCount=1, InstanceInitiatedShutdownBehavior="terminate",
                UserData=f"#!/bin/bash\nshutdown -h +{safety}\n", MetadataOptions={"HttpTokens": "required"},
                CreditSpecification={"CpuCredits": "standard"},
                TagSpecifications=[{"ResourceType": "instance", "Tags": TAGS + [{"Key": "Name", "Value": EC2_NAME}]},
                                   {"ResourceType": "volume", "Tags": TAGS + [{"Key": "Name", "Value": EC2_NAME}]}])
            iid = r["Instances"][0]["InstanceId"]
            ctx.log(f"已启动 {iid}（{itype} · {ami}），实例内设了 {safety} 分钟后自动关机终止兜底", "ok")
            st, ok = _wait(ctx, lambda: self._ec2_state(iid), lambda s: s == "running", 600, 5,
                           lambda s, w: f"等待实例运行：{s}（{w} 秒）")
            if not ok:
                raise AwsCreditError(f"实例 10 分钟内没有进入 running（当前 {st}），已终止")
            ctx.log("实例已运行", "ok")
            if hold:
                ctx.sleep(hold * 60, "实例运行中，保持 " + str(hold) + " 分钟后终止（剩余 {left} 秒）…")
        finally:
            if iid:
                try:
                    ec2.terminate_instances(InstanceIds=[iid])
                    ctx.log(f"已终止 {iid}")
                    _wait(ctx, lambda: self._ec2_state(iid), lambda s: s == "terminated", 300, 10)
                except Exception as e:
                    ctx.log(f"终止 {iid} 失败：{friendly(e, 'ec2')}（可用「清理残留资源」再试）", "error")
        return {"instance_id": iid, "instance_type": itype, "image_id": ami, "region": self.region, "held_minutes": hold, "cleaned": True}

    # ---- Budgets ----
    def _run_budgets(self, opts, ctx):
        bg = self.c("budgets", FT_REGION)
        aid = self._account_id()
        amount = str(opts.get("budget_amount") or "1")
        ctx.step(f"创建月度成本预算 {BUDGET_NAME}（${amount}）…")
        kw = dict(AccountId=aid, Budget={"BudgetName": BUDGET_NAME, "BudgetLimit": {"Amount": amount, "Unit": "USD"},
                                         "TimeUnit": "MONTHLY", "BudgetType": "COST"})
        existed = False
        try:
            try:
                bg.create_budget(ResourceTags=[{"Key": TAG_KEY, "Value": TAG_VAL}], **kw)
            except Exception as e:      # 没有 budgets:TagResource 时不带标签再建一次（预算按固定名称清理）
                if not is_denied(e):
                    raise
                ctx.log("没有 budgets:TagResource 权限，改为不带标签创建", "warn")
                bg.create_budget(**kw)
            ctx.log(f"已创建预算 {BUDGET_NAME}", "ok")
        except Exception as e:
            if _code(e) != "DuplicateRecordException":
                raise
            existed = True
            ctx.log(f"预算 {BUDGET_NAME} 已存在（之前创建过），视为已执行", "ok")
        kept = opts.get("keep_budget", True) not in (False, "false", 0, "0")
        if not kept:
            ctx.sleep(60, "预算保留 1 分钟后删除（剩余 {left} 秒）…")
            bg.delete_budget(AccountId=aid, BudgetName=BUDGET_NAME)
            ctx.log("已删除预算")
        return {"budget": BUDGET_NAME, "amount": amount, "existed": existed, "kept": kept}

    # ---- Lambda ----
    def _lambda_cleanup(self, ctx, region=None):
        lm, iam, out = self.c("lambda", region), self.c("iam"), []
        for fn in (lambda: lm.delete_function_url_config(FunctionName=LAMBDA_FN), lambda: lm.delete_function(FunctionName=LAMBDA_FN)):
            try:
                fn()
                out.append("lambda")
            except Exception as e:
                if _code(e) != "ResourceNotFoundException":
                    raise
        if out:
            ctx.log(f"已删除函数 {LAMBDA_FN}（{region or self.region}）")
        if self._delete_role(iam):
            ctx.log(f"已删除角色 {LAMBDA_ROLE}")
            out.append("role")
        return out

    @staticmethod
    def _delete_role(iam):
        try:
            for p in iam.list_attached_role_policies(RoleName=LAMBDA_ROLE).get("AttachedPolicies", []):
                iam.detach_role_policy(RoleName=LAMBDA_ROLE, PolicyArn=p["PolicyArn"])
            for n in iam.list_role_policies(RoleName=LAMBDA_ROLE).get("PolicyNames", []):
                iam.delete_role_policy(RoleName=LAMBDA_ROLE, PolicyName=n)
            iam.delete_role(RoleName=LAMBDA_ROLE)
            return True
        except Exception as e:
            if _code(e) == "NoSuchEntity":
                return False
            raise

    def _run_lambda(self, opts, ctx):
        keep = max(0, min(60, int(opts.get("keep_minutes", 10))))
        lm, iam = self.c("lambda"), self.c("iam")
        created = False
        url = None
        verified = None
        try:
            self._lambda_cleanup(ctx)       # 上次中断的残留先清掉
            ctx.step(f"创建执行角色 {LAMBDA_ROLE}（不附加策略）…")
            trust = {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Principal": {"Service": "lambda.amazonaws.com"},
                                                              "Action": "sts:AssumeRole"}]}
            role = iam.create_role(RoleName=LAMBDA_ROLE, AssumeRolePolicyDocument=json.dumps(trust), Tags=TAGS,
                                   Description="TriCloud free tier credit activity (auto deleted)")["Role"]["Arn"]
            created = True
            ctx.step(f"创建函数 {LAMBDA_FN}（{LAMBDA_RUNTIME}，128 MB）…")
            zipb = _lambda_zip()
            for i in range(12):            # 新建的角色要几秒到几十秒才能被 Lambda 使用
                try:
                    lm.create_function(FunctionName=LAMBDA_FN, Runtime=LAMBDA_RUNTIME, Role=role, Handler="lambda_function.lambda_handler",
                                       Code={"ZipFile": zipb}, MemorySize=128, Timeout=5, Tags={TAG_KEY: TAG_VAL},
                                       Description="TriCloud free tier credit activity (auto deleted)")
                    break
                except Exception as e:
                    if _code(e) == "InvalidParameterValueException" and "role" in _msg(e).lower() and i < 11:
                        ctx.step("等待新角色生效…")
                        _sleep(5)
                        continue
                    raise
            _wait(ctx, lambda: lm.get_function(FunctionName=LAMBDA_FN)["Configuration"].get("State"),
                  lambda s: s == "Active", 120, 3, lambda s, w: f"等待函数就绪：{s}…")
            ctx.step("创建函数 URL（公开访问）…")
            url = lm.create_function_url_config(FunctionName=LAMBDA_FN, AuthType="NONE")["FunctionUrl"]
            lm.add_permission(FunctionName=LAMBDA_FN, StatementId="tricloud-url", Action="lambda:InvokeFunctionUrl",
                              Principal="*", FunctionUrlAuthType="NONE")
            try:     # 2025-10 起新的函数 URL 还需要 lambda:InvokeFunction（InvokedViaFunctionUrl）
                lm.add_permission(FunctionName=LAMBDA_FN, StatementId="tricloud-url-invoke", Action="lambda:InvokeFunction",
                                  Principal="*", InvokedViaFunctionUrl=True)
            except Exception as e:
                if is_denied(e):
                    raise
                ctx.log("跳过 InvokeFunction 授权：" + friendly(e, "lambda"), "warn")
            ctx.log(f"函数 URL：{url}", "ok")
            verified = self._lambda_probe(url, ctx)
            if keep:
                ctx.sleep(keep * 60, "保留函数 " + str(keep) + " 分钟后自动删除（剩余 {left} 秒）…")
        finally:
            if created:
                try:
                    self._lambda_cleanup(ctx)
                except Exception as e:
                    ctx.log(f"清理 Lambda 失败：{friendly(e, 'lambda')}（可用「清理残留资源」再试）", "error")
        return {"function": LAMBDA_FN, "url": url, "verified": verified, "kept_minutes": keep, "region": self.region, "cleaned": True}

    def _lambda_probe(self, url, ctx):
        import httpx
        proxy = (getattr(self, "cred", None) or {}).get("proxy")
        for i in range(6):
            try:
                r = httpx.get(url, timeout=15, **({"proxy": proxy} if proxy else {}))
                if r.status_code == 200:
                    ctx.log(f"访问函数 URL 成功（HTTP 200）：{r.text[:60]}", "ok")
                    return True
                ctx.log(f"访问函数 URL：HTTP {r.status_code}（权限生效可能要几秒）", "warn")
            except Exception as e:
                ctx.log(f"访问函数 URL 失败：{type(e).__name__}", "warn")
            if i < 5:
                ctx.step("等待函数 URL 生效…")
                _sleep(5)
        ctx.log("函数 URL 未能验证成功（不影响函数已创建），继续", "warn")
        return False

    # ---- RDS ----
    def _rds_class(self):
        rds = self.c("rds")
        for cls in RDS_CLASSES:
            opts = rds.describe_orderable_db_instance_options(Engine="mysql", DBInstanceClass=cls, MaxRecords=20).get("OrderableDBInstanceOptions", [])
            if opts:
                return cls
        raise AwsCreditError(f"该区域（{self.region}）没有 {' / '.join(RDS_CLASSES)} 的 MySQL 规格")

    def _rds_status(self, ident):
        try:
            return self.c("rds").describe_db_instances(DBInstanceIdentifier=ident)["DBInstances"][0]["DBInstanceStatus"]
        except Exception as e:
            if _code(e) == "DBInstanceNotFound":
                return "deleted"
            raise

    def _rds_delete(self, ident, ctx, wait_ready=True):
        rds = self.c("rds")
        if wait_ready:     # 创建中的实例不能删除：等它可用 / 失败
            _wait(ctx, lambda: self._rds_status(ident), lambda s: s in ("available", "failed", "deleted", "deleting", "storage-full",
                                                                         "incompatible-parameters", "stopped"), 3600, 30)
        st = self._rds_status(ident)
        if st in ("deleted", "deleting"):
            return st
        rds.delete_db_instance(DBInstanceIdentifier=ident, SkipFinalSnapshot=True, DeleteAutomatedBackups=True)
        ctx.log(f"已提交删除 {ident}（跳过最终快照、删除自动备份）")
        return "deleting"

    def _run_rds(self, opts, ctx):
        hold = max(0, min(30, int(opts.get("rds_hold_minutes", 1))))
        cls = self._rds_class()
        rds = self.c("rds")
        ident = f"{RDS_PREFIX}-{secrets.token_hex(3)}"
        created = deleted = False
        t0 = time.time()
        try:
            ctx.step(f"创建 RDS {ident}（MySQL · {cls} · 20 GB gp2 · 单可用区 · 不公网）…")
            kw = dict(DBInstanceIdentifier=ident, DBInstanceClass=cls, Engine="mysql", MasterUsername="tcadmin",
                      MasterUserPassword=_rds_password(), AllocatedStorage=20, StorageType="gp2", MultiAZ=False,
                      PubliclyAccessible=False, BackupRetentionPeriod=0, DeletionProtection=False, AutoMinorVersionUpgrade=True,
                      CopyTagsToSnapshot=False, Tags=TAGS + [{"Key": "Name", "Value": ident}])
            try:
                rds.create_db_instance(EngineLifecycleSupport="open-source-rds-extended-support-disabled", **kw)
            except Exception as e:
                if _code(e) not in ("InvalidParameterCombination", "InvalidParameterValue") or "Lifecycle" not in _msg(e):
                    raise
                rds.create_db_instance(**kw)
            created = True
            ctx.log(f"已提交创建 {ident}（随机密码只在创建请求里使用，不保存、不显示）", "ok")
            st, ok = _wait(ctx, lambda: self._rds_status(ident), lambda s: s in ("available", "failed", "deleted"), 45 * 60, 30,
                           lambda s, w: f"RDS 创建中：{s}（已等待 {w // 60} 分 {w % 60} 秒，通常 5–15 分钟）")
            if st != "available":
                raise AwsCreditError(f"RDS 实例没有变为 available（当前 {st}），已删除")
            ctx.log(f"RDS 已可用（用时 {int(time.time() - t0) // 60} 分钟）", "ok")
            if hold:
                ctx.sleep(hold * 60, "RDS 已可用，保持 " + str(hold) + " 分钟后删除（剩余 {left} 秒）…")
            self._rds_delete(ident, ctx, wait_ready=False)
            deleted = True
            st, ok = _wait(ctx, lambda: self._rds_status(ident), lambda s: s == "deleted", 30 * 60, 30,
                           lambda s, w: f"RDS 删除中：{s}（已等待 {w // 60} 分钟）")
            ctx.log("RDS 已删除" if ok else "RDS 仍在删除中（AWS 后台会继续删除）", "ok" if ok else "warn")
        finally:
            if created and not deleted:
                try:
                    ctx.log("清理：删除 RDS（创建中的实例要等它可用才能删除，可能需要十几分钟）…", "warn")
                    self._rds_delete(ident, _Ctx(log=ctx.log, note=ctx.note), wait_ready=True)
                except Exception as e:
                    ctx.log(f"删除 RDS {ident} 失败：{friendly(e, 'rds')}（可用「清理残留资源」再试）", "error")
        return {"db_instance": ident, "class": cls, "engine": "mysql", "region": self.region, "minutes": int(time.time() - t0) // 60,
                "cleaned": True}

    # ---- Bedrock ----
    def _run_bedrock(self, opts, ctx):
        br = self.c("bedrock-runtime", FT_REGION)
        last = None
        for mid in BEDROCK_MODELS:
            ctx.step(f"调用 Bedrock {mid}（us-east-1）…")
            try:
                r = br.converse(modelId=mid, messages=[{"role": "user", "content": [{"text": "你好，请用一句话介绍 Amazon Bedrock。"}]}],
                                inferenceConfig={"maxTokens": 64, "temperature": 0.2})
            except Exception as e:
                last = e
                c = _code(e)
                if is_denied(e):
                    raise AwsCreditError("没有 Bedrock 调用权限或模型访问权限：请给 IAM 用户添加 bedrock:InvokeModel，"
                                         "并在 Bedrock 控制台确认 Amazon Nova Micro 可用（us-east-1）", kind="denied")
                if c in ("ValidationException", "ResourceNotFoundException") and mid != BEDROCK_MODELS[-1]:
                    ctx.log(f"{mid} 不可用（{c}），换跨区域推理配置再试", "warn")
                    continue
                if c in ("ResourceNotFoundException", "ValidationException"):
                    raise AwsCreditError(f"Amazon Nova Micro 在该账号不可用（{c}：{_msg(e)[:120]}），请到 Bedrock 控制台检查模型访问")
                raise
            text = "".join(x.get("text", "") for x in (((r.get("output") or {}).get("message") or {}).get("content") or []))
            u = r.get("usage") or {}
            ctx.log(f"模型回复：{text[:120]}", "ok")
            return {"model": mid, "reply": text[:300], "input_tokens": u.get("inputTokens"), "output_tokens": u.get("outputTokens")}
        raise AwsCreditError(friendly(last, "bedrock"))

    # ---------------- 清理残留 ----------------
    def credit_cleanup(self, regions=None, include_budget=False):
        """删除所有带 tricloud-credit=1 标签 / 固定名称的残留：EC2 实例、Lambda 函数与角色、RDS 实例，可选预算。"""
        regions = [r for r in dict.fromkeys(regions or [self.region]) if r]
        deleted, errors = [], []
        for rg in regions:
            try:
                ec2 = self.c("ec2", rg)
                ids = [i["InstanceId"] for res in ec2.describe_instances(Filters=[
                    {"Name": f"tag:{TAG_KEY}", "Values": [TAG_VAL]},
                    {"Name": "instance-state-name", "Values": ["pending", "running", "stopping", "stopped"]}]).get("Reservations", [])
                    for i in res.get("Instances", [])]
                if ids:
                    ec2.terminate_instances(InstanceIds=ids)
                    deleted += [{"type": "ec2", "id": x, "region": rg} for x in ids]
            except Exception as e:
                errors.append({"type": "ec2", "region": rg, "error": friendly(e, "ec2")})
            try:
                lm = self.c("lambda", rg)
                n = 0
                for fn in (lambda: lm.delete_function_url_config(FunctionName=LAMBDA_FN), lambda: lm.delete_function(FunctionName=LAMBDA_FN)):
                    try:
                        fn()
                        n += 1
                    except Exception as e:
                        if _code(e) != "ResourceNotFoundException":
                            raise
                if n:
                    deleted.append({"type": "lambda", "id": LAMBDA_FN, "region": rg})
            except Exception as e:
                errors.append({"type": "lambda", "region": rg, "error": friendly(e, "lambda")})
            try:
                rds = self.c("rds", rg)
                for d in rds.describe_db_instances(MaxRecords=100).get("DBInstances", []):
                    ident = d["DBInstanceIdentifier"]
                    if not ident.startswith(RDS_PREFIX) or d.get("DBInstanceStatus") == "deleting":
                        continue
                    try:
                        rds.delete_db_instance(DBInstanceIdentifier=ident, SkipFinalSnapshot=True, DeleteAutomatedBackups=True)
                        deleted.append({"type": "rds", "id": ident, "region": rg})
                    except Exception as e:
                        msg = "实例还在创建中，等它可用后再点一次清理" if _code(e) == "InvalidDBInstanceState" else friendly(e, "rds")
                        errors.append({"type": "rds", "id": ident, "region": rg, "error": msg})
            except Exception as e:
                errors.append({"type": "rds", "region": rg, "error": friendly(e, "rds")})
        try:
            if self._delete_role(self.c("iam")):
                deleted.append({"type": "iam-role", "id": LAMBDA_ROLE})
        except Exception as e:
            errors.append({"type": "iam-role", "error": friendly(e, "lambda")})
        if include_budget:
            try:
                self.c("budgets", FT_REGION).delete_budget(AccountId=self._account_id(), BudgetName=BUDGET_NAME)
                deleted.append({"type": "budget", "id": BUDGET_NAME})
            except Exception as e:
                if _code(e) != "NotFoundException":
                    errors.append({"type": "budget", "error": friendly(e, "budgets")})
        return {"ok": not errors, "deleted": deleted, "errors": errors, "regions": regions}
