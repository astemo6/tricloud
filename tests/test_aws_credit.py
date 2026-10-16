"""build 20：AWS 新号 Free Tier Credit（freetier 查询 + 一键完成 5 个活动 + 清理残留）。
全部用假的 boto3 客户端，不连接任何真实 AWS、不创建任何资源。"""
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

from botocore.exceptions import ClientError
from fastapi.testclient import TestClient

from app import core, main, services, tasks, telegram
from app.providers import aws_credit as AC
from app.providers.aws_provider import AWSProvider
from app.routers import aws_credit as RC

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
CLOCK = [1_000_000.0]
AC._now = lambda: CLOCK[0]
AC._sleep = lambda s: CLOCK.__setitem__(0, CLOCK[0] + s)
SENT = []


async def fake_send(msg, *a, **kw):
    SENT.append(msg)
telegram.send = fake_send


def CE(code, msg="x", op="Op"):
    return ClientError({"Error": {"Code": code, "Message": msg}}, op)


CALLS = []


def rec(svc, region, op, **kw):
    CALLS.append((svc, region, op, kw))


def calls(svc=None, op=None):
    return [c for c in CALLS if (svc is None or c[0] == svc) and (op is None or c[2] == op)]


class FT:
    """freetier。MODE: ok / denied / na / acts_denied"""
    MODE = "ok"

    def __init__(self, rg):
        self.rg = rg

    def get_account_plan_state(self):
        rec("freetier", self.rg, "get_account_plan_state")
        if FT.MODE == "denied":
            raise CE("AccessDeniedException", "User is not authorized to perform: freetier:GetAccountPlanState")
        if FT.MODE == "na":
            raise CE("ResourceNotFoundException", "Account plan not found")
        import datetime as dt
        return {"accountId": "123456789012", "accountPlanType": "FREE", "accountPlanStatus": "ACTIVE",
                "accountPlanRemainingCredits": {"amount": 118.42, "unit": "USD"},
                "accountPlanExpirationDate": dt.datetime(2027, 4, 1, 0, 0, tzinfo=dt.timezone.utc)}

    def list_account_activities(self, **kw):
        rec("freetier", self.rg, "list_account_activities", **kw)
        if FT.MODE == "acts_denied":
            raise CE("AccessDeniedException")
        if not kw.get("nextToken"):
            return {"activities": [
                {"activityId": "act-ec2-001", "title": "使用 Amazon EC2 启动实例", "status": "COMPLETED", "reward": {"credit": {"amount": 20, "unit": "USD"}}},
                {"activityId": "act-br-002", "title": "在 Amazon Bedrock 演练场中使用基础模型", "status": "NOT_STARTED", "reward": {"credit": {"amount": 20, "unit": "USD"}}},
                {"activityId": "act-bg-003", "title": "使用 AWS Budgets 设置成本预算", "status": "IN_PROGRESS", "reward": {"credit": {"amount": 20, "unit": "USD"}}},
            ], "nextToken": "p2"}
        return {"activities": [
            {"activityId": "act-lm-004", "title": "使用 AWS Lambda 创建 Web 应用", "status": "NOT_STARTED", "reward": {"credit": {"amount": 20, "unit": "USD"}}},
            {"activityId": "act-rds-005", "title": "创建 Amazon RDS 数据库", "status": "EXPIRING", "reward": {"credit": {"amount": 20, "unit": "USD"}}},
            {"activityId": "act-x-006", "title": "某个新活动", "status": "NOT_STARTED", "reward": {"credit": {"amount": 5, "unit": "USD"}}},
        ]}

    def get_account_activity(self, activityId, languageCode):
        rec("freetier", self.rg, "get_account_activity", activityId=activityId, languageCode=languageCode)
        import datetime as dt
        if activityId == "act-ec2-001":
            return {"activityId": activityId, "status": "COMPLETED", "completedAt": dt.datetime(2026, 10, 1, 8, 0, tzinfo=dt.timezone.utc),
                    "estimatedTimeToCompleteInMinutes": 10, "instructionsUrl": "https://example.invalid/ec2"}
        if activityId == "act-rds-005":
            raise CE("ThrottlingException")
        return {"activityId": activityId, "estimatedTimeToCompleteInMinutes": 15}


class OldFT:
    def __init__(self, rg):
        pass


class STS:
    def __init__(self, rg):
        pass

    def get_caller_identity(self):
        return {"Account": "123456789012"}


class EC2:
    OFFER = ["t3.micro", "t2.micro"]
    DRY = "DryRunOperation"
    STATES = {}
    RUN_FAIL = None

    def __init__(self, rg):
        self.rg = rg

    def describe_instance_type_offerings(self, **kw):
        rec("ec2", self.rg, "offerings", **kw)
        return {"InstanceTypeOfferings": [{"InstanceType": t} for t in EC2.OFFER]}

    def describe_images(self, **kw):
        return {"Images": [{"ImageId": "ami-old", "CreationDate": "2025"}, {"ImageId": "ami-new", "CreationDate": "2026"}]}

    def run_instances(self, **kw):
        rec("ec2", self.rg, "run_instances", **kw)
        if kw.get("DryRun"):
            raise CE(EC2.DRY, "Request would have succeeded" if EC2.DRY == "DryRunOperation" else
                     "You are not authorized to perform this operation. User: x is not authorized to perform: ec2:RunInstances")
        if EC2.RUN_FAIL:
            raise CE(EC2.RUN_FAIL)
        EC2.STATES["i-0abc"] = ["pending", "running"]
        return {"Instances": [{"InstanceId": "i-0abc"}]}

    def describe_instances(self, InstanceIds=None, Filters=None):
        rec("ec2", self.rg, "describe_instances", InstanceIds=InstanceIds, Filters=Filters)
        if Filters:
            return {"Reservations": [{"Instances": [{"InstanceId": "i-left1"}, {"InstanceId": "i-left2"}]}]}
        seq = EC2.STATES.get(InstanceIds[0], ["terminated"])
        st = seq.pop(0) if len(seq) > 1 else seq[0]
        return {"Reservations": [{"Instances": [{"InstanceId": InstanceIds[0], "State": {"Name": st}}]}]}

    def terminate_instances(self, InstanceIds):
        rec("ec2", self.rg, "terminate_instances", InstanceIds=InstanceIds)
        for i in InstanceIds:
            EC2.STATES[i] = ["shutting-down", "terminated"]


class SSM:
    def __init__(self, rg):
        self.rg = rg

    def get_parameter(self, Name):
        rec("ssm", self.rg, "get_parameter", Name=Name)
        return {"Parameter": {"Value": "ami-0al2023"}}


class Budgets:
    EXIST = False
    DENY = False

    def __init__(self, rg):
        self.rg = rg

    def describe_budgets(self, **kw):
        rec("budgets", self.rg, "describe_budgets", **kw)
        if Budgets.DENY:
            raise CE("AccessDeniedException", "not authorized to perform: budgets:ViewBudget")
        return {"Budgets": []}

    def create_budget(self, **kw):
        rec("budgets", self.rg, "create_budget", **kw)
        if Budgets.EXIST:
            raise CE("DuplicateRecordException")

    def delete_budget(self, **kw):
        rec("budgets", self.rg, "delete_budget", **kw)


class Lambda:
    ROLE_NOT_READY = 2

    def __init__(self, rg):
        self.rg = rg

    def list_functions(self, **kw):
        return {"Functions": []}

    def delete_function_url_config(self, **kw):
        rec("lambda", self.rg, "delete_function_url_config", **kw)
        if not LSTATE.get("fn"):
            raise CE("ResourceNotFoundException")

    def delete_function(self, **kw):
        rec("lambda", self.rg, "delete_function", **kw)
        if not LSTATE.get("fn"):
            raise CE("ResourceNotFoundException")
        LSTATE["fn"] = False

    def create_function(self, **kw):
        rec("lambda", self.rg, "create_function", **kw)
        if Lambda.ROLE_NOT_READY > 0:
            Lambda.ROLE_NOT_READY -= 1
            raise CE("InvalidParameterValueException", "The role defined for the function cannot be assumed by Lambda.")
        LSTATE["fn"] = True

    def get_function(self, **kw):
        return {"Configuration": {"State": "Active"}}

    def create_function_url_config(self, **kw):
        rec("lambda", self.rg, "create_function_url_config", **kw)
        return {"FunctionUrl": "https://abc.lambda-url.ap-northeast-1.on.aws/"}

    def add_permission(self, **kw):
        rec("lambda", self.rg, "add_permission", **kw)


LSTATE = {}


class IAM:
    def __init__(self, rg):
        pass

    def get_role(self, RoleName):
        if LSTATE.get("role"):
            return {"Role": {"Arn": "arn:aws:iam::123456789012:role/" + RoleName}}
        raise CE("NoSuchEntity")

    def create_role(self, **kw):
        rec("iam", None, "create_role", **kw)
        LSTATE["role"] = True
        return {"Role": {"Arn": "arn:aws:iam::123456789012:role/" + kw["RoleName"]}}

    def list_attached_role_policies(self, RoleName):
        if not LSTATE.get("role"):
            raise CE("NoSuchEntity")
        return {"AttachedPolicies": []}

    def list_role_policies(self, RoleName):
        return {"PolicyNames": []}

    def delete_role(self, RoleName):
        rec("iam", None, "delete_role", RoleName=RoleName)
        LSTATE["role"] = False


class RDS:
    SEQ = []
    LEFT = []

    def __init__(self, rg):
        self.rg = rg

    def describe_orderable_db_instance_options(self, **kw):
        rec("rds", self.rg, "orderable", **kw)
        return {"OrderableDBInstanceOptions": [{"StorageType": "gp2"}] if kw["DBInstanceClass"] == "db.t4g.micro" else []}

    def describe_db_instances(self, DBInstanceIdentifier=None, MaxRecords=None):
        if DBInstanceIdentifier is None:
            return {"DBInstances": RDS.LEFT}
        st = RDS.SEQ.pop(0) if len(RDS.SEQ) > 1 else (RDS.SEQ[0] if RDS.SEQ else "deleted")
        if st == "deleted":
            raise CE("DBInstanceNotFound")
        return {"DBInstances": [{"DBInstanceStatus": st}]}

    def create_db_instance(self, **kw):
        rec("rds", self.rg, "create_db_instance", **kw)

    def delete_db_instance(self, **kw):
        rec("rds", self.rg, "delete_db_instance", **kw)
        RDS.SEQ = ["deleting", "deleted"]


class BR:
    MODE = "ok"

    def __init__(self, rg):
        self.rg = rg

    def converse(self, **kw):
        rec("bedrock-runtime", self.rg, "converse", **kw)
        if BR.MODE == "denied":
            raise CE("AccessDeniedException", "You don't have access to the model with the specified model ID.")
        if BR.MODE == "fallback" and kw["modelId"] == "amazon.nova-micro-v1:0":
            raise CE("ValidationException", "Invocation of model ID with on-demand throughput isn't supported.")
        return {"output": {"message": {"content": [{"text": "Amazon Bedrock 是一项托管的生成式 AI 服务。"}]}},
                "usage": {"inputTokens": 12, "outputTokens": 20}}


SVC = {"freetier": FT, "sts": STS, "ec2": EC2, "ssm": SSM, "budgets": Budgets, "lambda": Lambda, "iam": IAM, "rds": RDS,
       "bedrock-runtime": BR}


class Session:
    def client(self, svc, region_name=None, config=None):
        return SVC[svc](region_name)


def fake(region="ap-northeast-1"):
    p = AWSProvider({"access_key": "AKIAFAKE", "secret_key": "fake", "region": "ap-northeast-1"}, region)
    p.session = Session()
    return p


LOGS = []


def ctx(stop_on=None):
    def step(m):
        LOGS.append(("step", m))
        if stop_on and stop_on in m:
            raise tasks.TaskStopped()
    return AC._Ctx(log=lambda m, lv="info": LOGS.append((lv, m)), step=step, note=lambda m: LOGS.append(("note", m)))


# ================= 1. freetier 查询 =================
s = fake().credit_state()
ok("state: plan type/status/remaining/expires", s["plan"] == {"account_id": "123456789012", "type": "FREE", "status": "ACTIVE", "remaining": 118.42,
                                                               "unit": "USD", "expires": "2027-04-01T00:00:00+00:00"})
ok("state: freetier client is us-east-1", {c[1] for c in calls("freetier")} == {"us-east-1"})
la = calls("freetier", "list_account_activities")
ok("state: ListAccountActivities languageCode=zh-CN + pagination", len(la) == 2 and all(c[3]["languageCode"] == "zh-CN" for c in la) and la[1][3]["nextToken"] == "p2")
keys = [a["key"] for a in s["activities"]]
ok("state: activities mapped by title (ec2/bedrock/budgets/lambda/rds + unknown None)", keys == ["ec2", "bedrock", "budgets", "lambda", "rds", None])
e = s["activities"][0]
ok("state: GetAccountActivity detail merged (completed_at / est / url / reward)", e["completed_at"].startswith("2026-10-01") and e["est_minutes"] == 10
   and e["reward"] == 20 and e["instructions_url"].startswith("https://"))
ok("state: one GetAccountActivity failure doesn't break the list", s["activities"][4]["status"] == "EXPIRING" and s["activities"][4]["completed_at"] is None)
ok("match_key: english titles too", AC.match_key({"title": "Launch an instance using Amazon EC2"}) == "ec2"
   and AC.match_key({"title": "Use a foundational model in the Amazon Bedrock playground"}) == "bedrock"
   and AC.match_key({"title": "Set up a cost budget using AWS Budgets"}) == "budgets"
   and AC.match_key({"title": "Create a web app using AWS Lambda"}) == "lambda" and AC.match_key({"title": "Create an Amazon RDS database"}) == "rds")

FT.MODE = "denied"
try:
    fake().credit_state()
    ok("state denied raises", False)
except core.AwsCreditError as x:
    ok("state denied: kind=denied, lists 3 freetier read permissions", x.kind == "denied" and all(p in str(x) for p in AC.FREETIER_PERMS))
FT.MODE = "na"
try:
    fake().credit_state()
    ok("state n/a raises", False)
except core.AwsCreditError as x:
    ok("state not applicable: kind=not_applicable, friendly", x.kind == "not_applicable" and "新免费计划" in str(x))
FT.MODE = "acts_denied"
s2 = fake().credit_state()
ok("state: plan ok but activities denied -> partial", s2["plan"]["type"] == "FREE" and s2["activities"] == [] and s2["activities_denied"])
FT.MODE = "ok"
SVC["freetier"] = OldFT
try:
    fake().credit_state()
    ok("old botocore raises", False)
except core.AwsCreditError as x:
    ok("state: botocore without freetier ops -> unsupported (upgrade hint)", x.kind == "unsupported" and "boto3" in str(x))
SVC["freetier"] = FT
ok("fetch_state wraps errors to state=...", RC.fetch_state(fake())["state"] == "ok")
FT.MODE = "denied"
fs = RC.fetch_state(fake())
ok("fetch_state denied: state=denied + permissions list", fs["state"] == "denied" and fs["permissions"] == AC.FREETIER_PERMS)
FT.MODE = "ok"

# ================= 2. EC2 =================
CALLS.clear()
LOGS.clear()
r = fake().credit_run("ec2", {"hold_minutes": 5}, ctx())
ri = [c for c in calls("ec2", "run_instances") if not c[3].get("DryRun")][0][3]
ok("ec2: DryRun precheck before launch", calls("ec2", "run_instances")[0][3].get("DryRun") is True)
ok("ec2: t3.micro preferred, AL2023 via SSM public parameter", ri["InstanceType"] == "t3.micro" and ri["ImageId"] == "ami-0al2023"
   and calls("ssm", "get_parameter")[0][3]["Name"] == AC.AL2023_PARAM)
ok("ec2: tagged tricloud-credit=1 (instance+volume), standard credits, shutdown=terminate, IMDSv2",
   all({"Key": "tricloud-credit", "Value": "1"} in ts["Tags"] for ts in ri["TagSpecifications"]) and len(ri["TagSpecifications"]) == 2
   and ri["CreditSpecification"] == {"CpuCredits": "standard"} and ri["InstanceInitiatedShutdownBehavior"] == "terminate"
   and ri["MetadataOptions"]["HttpTokens"] == "required" and "shutdown -h +30" in ri["UserData"])
ok("ec2: launched in account default region", calls("ec2", "run_instances")[-1][1] == "ap-northeast-1")
ok("ec2: terminated after hold", calls("ec2", "terminate_instances")[0][3]["InstanceIds"] == ["i-0abc"] and r["cleaned"] and r["held_minutes"] == 5)
ok("ec2: hold progress shown", any("保持 5 分钟后终止" in m for k, m in LOGS if k == "step"))
EC2.OFFER = ["t2.micro"]
p = fake()
ok("ec2: falls back to t2.micro when t3 not offered", p._ec2_pick()[0] == "t2.micro")
EC2.OFFER = []
try:
    fake().credit_run("ec2", {}, ctx())
    ok("ec2 no type", False)
except core.AwsCreditError as x:
    ok("ec2: no micro type in region -> friendly", "不提供" in str(x))
EC2.OFFER = ["t3.micro", "t2.micro"]
CALLS.clear()
try:
    fake().credit_run("ec2", {"hold_minutes": 5}, ctx(stop_on="保持"))
    ok("ec2 stop", False)
except tasks.TaskStopped:
    ok("ec2: stopping during hold still terminates the instance", calls("ec2", "terminate_instances") != [])
EC2.DRY = "UnauthorizedOperation"
try:
    fake().credit_precheck("ec2")
    ok("ec2 precheck denied", False)
except core.AwsCreditError as x:
    ok("ec2 precheck denied -> lists ec2:RunInstances, no traceback", x.kind == "denied" and "ec2:RunInstances" in str(x) and "Traceback" not in str(x))
EC2.DRY = "DryRunOperation"
EC2.RUN_FAIL = "VPCIdNotSpecified"
CALLS.clear()
try:
    fake().credit_run("ec2", {}, ctx())
    ok("ec2 no vpc", False)
except core.AwsCreditError as x:
    ok("ec2: no default VPC -> friendly Chinese error, nothing to terminate", "默认 VPC" in str(x) and not calls("ec2", "terminate_instances"))
EC2.RUN_FAIL = None

# ================= 3. Budgets =================
CALLS.clear()
r = fake().credit_run("budgets", {}, ctx())
cb = calls("budgets", "create_budget")[0]
ok("budgets: monthly COST $1 named tricloud-credit-budget, tagged, us-east-1",
   cb[3]["Budget"]["BudgetName"] == "tricloud-credit-budget" and cb[3]["Budget"]["BudgetLimit"] == {"Amount": "1", "Unit": "USD"}
   and cb[3]["Budget"]["TimeUnit"] == "MONTHLY" and cb[3]["Budget"]["BudgetType"] == "COST" and cb[3]["ResourceTags"] == [{"Key": "tricloud-credit", "Value": "1"}]
   and cb[1] == "us-east-1" and cb[3]["AccountId"] == "123456789012")
ok("budgets: kept by default (free)", r["kept"] and not calls("budgets", "delete_budget"))
Budgets.EXIST = True
r = fake().credit_run("budgets", {}, ctx())
ok("budgets: duplicate -> existed, treated as executed", r["existed"])
Budgets.EXIST = False
r = fake().credit_run("budgets", {"keep_budget": False}, ctx())
ok("budgets: keep_budget=false deletes after 1 min", not r["kept"] and calls("budgets", "delete_budget"))
Budgets.DENY = True
try:
    fake().credit_run("budgets", {}, ctx())
    ok("budgets denied", False)
except core.AwsCreditError as x:
    ok("budgets denied -> needs budgets:ModifyBudget", "budgets:ModifyBudget" in str(x))
Budgets.DENY = False

# ================= 4. Lambda =================
CALLS.clear()
LOGS.clear()
LSTATE.clear()
with mock.patch("httpx.get", return_value=mock.Mock(status_code=200, text="<h1>Hello from TriCloud</h1>")) as hg:
    r = fake().credit_run("lambda", {"keep_minutes": 10}, ctx())
cr = calls("iam", "create_role")[0][3]
ok("lambda: role trusts lambda.amazonaws.com, tagged, no policy attached",
   json.loads(cr["AssumeRolePolicyDocument"])["Statement"][0]["Principal"] == {"Service": "lambda.amazonaws.com"} and cr["Tags"] == AC.TAGS
   and not calls("iam", "attach_role_policy"))
ok("lambda: create_function retried while role propagates", len(calls("lambda", "create_function")) == 3)
cfn = calls("lambda", "create_function")[-1][3]
ok("lambda: python runtime, 128MB, tagged, zip has handler", cfn["Runtime"].startswith("python3") and cfn["MemorySize"] == 128
   and cfn["Tags"] == {"tricloud-credit": "1"} and cfn["Code"]["ZipFile"][:2] == b"PK")
ok("lambda: function URL auth NONE + InvokeFunctionUrl + InvokeFunction(InvokedViaFunctionUrl)",
   calls("lambda", "create_function_url_config")[0][3]["AuthType"] == "NONE"
   and [c[3]["Action"] for c in calls("lambda", "add_permission")] == ["lambda:InvokeFunctionUrl", "lambda:InvokeFunction"]
   and calls("lambda", "add_permission")[1][3].get("InvokedViaFunctionUrl") is True)
ok("lambda: URL invoked once to verify", hg.call_count == 1 and r["verified"] is True)
ok("lambda: kept 10 min then function + url + role deleted", r["kept_minutes"] == 10 and calls("lambda", "delete_function")
   and calls("iam", "delete_role") and not LSTATE.get("fn") and not LSTATE.get("role"))
CALLS.clear()
LSTATE.clear()
Lambda.ROLE_NOT_READY = 0
with mock.patch("httpx.get", side_effect=RuntimeError("boom")):
    try:
        fake().credit_run("lambda", {"keep_minutes": 3}, ctx(stop_on="保留函数"))
        ok("lambda stop", False)
    except tasks.TaskStopped:
        ok("lambda: stop during keep still cleans function + role", not LSTATE.get("fn") and not LSTATE.get("role"))

# ================= 5. RDS =================
CALLS.clear()
LOGS.clear()
RDS.SEQ = ["creating", "creating", "backing-up", "available"]
r = fake().credit_run("rds", {}, ctx())
cd = calls("rds", "create_db_instance")[0][3]
ok("rds: db.t4g.micro MySQL 20GB gp2 single-AZ private, no backups, tagged",
   cd["DBInstanceClass"] == "db.t4g.micro" and cd["Engine"] == "mysql" and cd["AllocatedStorage"] == 20 and cd["StorageType"] == "gp2"
   and cd["MultiAZ"] is False and cd["PubliclyAccessible"] is False and cd["BackupRetentionPeriod"] == 0 and cd["DeletionProtection"] is False
   and {"Key": "tricloud-credit", "Value": "1"} in cd["Tags"] and cd["DBInstanceIdentifier"].startswith("tricloud-credit-db-"))
pw = cd["MasterUserPassword"]
ok("rds: random password strong, never logged / returned", len(pw) >= 20 and pw.isalnum() and pw not in json.dumps(LOGS, ensure_ascii=False)
   and pw not in json.dumps(r))
dd = calls("rds", "delete_db_instance")[0][3]
ok("rds: deleted after available (SkipFinalSnapshot, DeleteAutomatedBackups)", dd["SkipFinalSnapshot"] is True and dd["DeleteAutomatedBackups"] is True
   and r["cleaned"])
ok("rds: progress messages show status + waited time", any("RDS 创建中：creating" in m for k, m in LOGS if k == "step"))
ok("rds: extended support disabled (no surprise charges)", cd.get("EngineLifecycleSupport") == "open-source-rds-extended-support-disabled")
CALLS.clear()
RDS.SEQ = ["creating", "failed"]
try:
    fake().credit_run("rds", {}, ctx())
    ok("rds failed", False)
except core.AwsCreditError as x:
    ok("rds: failed status -> friendly error + still deleted", "available" in str(x) and calls("rds", "delete_db_instance"))
CALLS.clear()
RDS.SEQ = ["creating", "creating", "available"]
try:
    fake().credit_run("rds", {}, ctx(stop_on="RDS 创建中"))
    ok("rds stop", False)
except tasks.TaskStopped:
    ok("rds: stop while creating -> waits until deletable, then deletes", calls("rds", "delete_db_instance") != [])

# ================= 6. Bedrock =================
CALLS.clear()
r = fake().credit_run("bedrock", {}, ctx())
cv = calls("bedrock-runtime", "converse")[0]
ok("bedrock: Converse Nova Micro in us-east-1, small maxTokens", cv[1] == "us-east-1" and cv[3]["modelId"] == "amazon.nova-micro-v1:0"
   and cv[3]["inferenceConfig"]["maxTokens"] <= 100 and r["output_tokens"] == 20)
BR.MODE = "fallback"
r = fake().credit_run("bedrock", {}, ctx())
ok("bedrock: on-demand unsupported -> retries us. inference profile", r["model"] == "us.amazon.nova-micro-v1:0")
BR.MODE = "denied"
try:
    fake().credit_run("bedrock", {}, ctx())
    ok("bedrock denied", False)
except core.AwsCreditError as x:
    ok("bedrock: no model access -> friendly hint (bedrock:InvokeModel / Nova Micro)", x.kind == "denied" and "bedrock:InvokeModel" in str(x) and "Nova Micro" in str(x))
BR.MODE = "ok"
ok("bedrock: UI note says playground may be required", "playground" in AC.ACT_INFO["bedrock"]["note"])

# ================= 7. 清理残留 =================
CALLS.clear()
LSTATE.update(fn=True, role=True)
RDS.LEFT = [{"DBInstanceIdentifier": "tricloud-credit-db-aa11", "DBInstanceStatus": "available"},
            {"DBInstanceIdentifier": "prod-db", "DBInstanceStatus": "available"}]
cl = fake().credit_cleanup(["ap-northeast-1"], include_budget=True)
types = sorted(d["type"] for d in cl["deleted"])
ok("cleanup: tagged EC2 + lambda + tricloud rds + role + budget", types == ["budget", "ec2", "ec2", "iam-role", "lambda", "rds"] and cl["ok"])
ok("cleanup: EC2 filter by tag tricloud-credit=1", calls("ec2", "describe_instances")[0][3]["Filters"][0] == {"Name": "tag:tricloud-credit", "Values": ["1"]})
ok("cleanup: never touches non-tricloud RDS", [c[3]["DBInstanceIdentifier"] for c in calls("rds", "delete_db_instance")] == ["tricloud-credit-db-aa11"])
RDS.LEFT = []
cl = fake().credit_cleanup(["ap-northeast-1"])
ok("cleanup: budget kept unless include_budget", not any(d["type"] == "budget" for d in cl["deleted"]))

# ================= 8. friendly =================
ok("friendly: OptInRequired / Throttling / unknown code", "尚未启用" in AC.friendly(CE("OptInRequired")) and "限流" in AC.friendly(CE("ThrottlingException"))
   and AC.friendly(CE("WeirdError", "boom")) == "WeirdError：boom")
ok("friendly: plain exception -> type + message, no traceback", AC.friendly(RuntimeError("x")) == "RuntimeError：x")

# ================= 9. 路由 + 后台任务 =================
FT.MODE = "ok"
with TestClient(main.app) as c:
    anon = TestClient(main.app)
    c.post("/api/login", json={"password": "devpassword123"})
    with mock.patch.object(AWSProvider, "test", return_value={"ok": True}):
        aid = c.post("/api/accounts", json={"provider": "aws", "name": "aws-new", "cred": {"access_key": "AKIAFAKE00000000", "secret_key": "fake",
                                                                                         "region": "ap-northeast-1"}}).json()["id"]
    PROV = {}

    def prov(acc_id, region=None):
        return PROV.setdefault((acc_id, region), fake(region or "ap-northeast-1"))

    with mock.patch.object(services, "provider", prov):
        ok("route: unauthenticated 401", anon.get(f"/api/accounts/{aid}/aws/credits").status_code == 401)
        CALLS.clear()
        j = c.get(f"/api/accounts/{aid}/aws/credits").json()
        ok("route credits: state ok + plan + 5 activities in fixed order", j["state"] == "ok" and j["plan"]["remaining"] == 118.42
           and [a["key"] for a in j["activities"]] == ["ec2", "budgets", "lambda", "rds", "bedrock"])
        a = {x["key"]: x for x in j["activities"]}
        ok("route credits: status text + reward + runnable", a["ec2"]["status_text"] == "已完成" and not a["ec2"]["runnable"]
           and a["budgets"]["status_text"] == "进行中" and a["rds"]["status_text"] == "即将过期" and a["bedrock"]["reward"] == 20)
        ok("route credits: unmatched AWS activity listed separately", [x["title"] for x in j["extra_activities"]] == ["某个新活动"])
        ok("route credits: notes say 等待 AWS 识别, not 已获得", any("等待 AWS 识别" in n and "不代表已获得奖励" in n for n in j["notes"]))
        ok("route credits: pending excludes completed", j["pending"] == ["budgets", "lambda", "rds", "bedrock"])
        n0 = len(calls("freetier", "get_account_plan_state"))
        j2 = c.get(f"/api/accounts/{aid}/aws/credits").json()
        ok("route credits: cached 5 min (no extra freetier call)", j2["cached"] and len(calls("freetier", "get_account_plan_state")) == n0)
        c.get(f"/api/accounts/{aid}/aws/credits?refresh=true")
        ok("route credits: refresh=true bypasses cache", len(calls("freetier", "get_account_plan_state")) == n0 + 1)
        FT.MODE = "denied"
        jd = c.get(f"/api/accounts/{aid}/aws/credits?refresh=true")
        ok("route credits denied: 200 + state denied + friendly message", jd.status_code == 200 and jd.json()["state"] == "denied"
           and "freetier:ListAccountActivities" in jd.json()["message"] and len(jd.json()["activities"]) == 5)
        FT.MODE = "na"
        jn = c.get(f"/api/accounts/{aid}/aws/credits?refresh=true").json()
        ok("route credits not applicable: friendly", jn["state"] == "not_applicable" and "新免费计划" in jn["message"])
        FT.MODE = "ok"
        c.get(f"/api/accounts/{aid}/aws/credits?refresh=true")

        r0 = c.post(f"/api/accounts/{aid}/aws/credits/activities/budgets/run", json={})
        ok("route run: confirm required (400)", r0.status_code == 400 and "确认" in r0.json()["detail"])
        ok("route run: unknown activity 400", c.post(f"/api/accounts/{aid}/aws/credits/activities/s3/run", json={"confirm": True}).status_code == 400)
        ok("route run: completed activity 400", c.post(f"/api/accounts/{aid}/aws/credits/activities/ec2/run", json={"confirm": True}).json()["detail"].endswith("已完成，无需再执行"))
        ok("route run: hold range validated", c.post(f"/api/accounts/{aid}/aws/credits/activities/lambda/run", json={"confirm": True, "keep_minutes": 999}).status_code == 400)
        Budgets.DENY = True
        rd = c.post(f"/api/accounts/{aid}/aws/credits/activities/budgets/run", json={"confirm": True})
        ok("route run: precheck denied -> friendly 400 (no traceback, no task)", rd.status_code == 400 and "budgets:ModifyBudget" in rd.json()["detail"]
           and "Traceback" not in rd.text and not RC._credit_tasks(aid))
        Budgets.DENY = False
        rr = c.post(f"/api/accounts/{aid}/aws/credits/activities/act-bg-003/run", json={"confirm": True})
        ok("route run: AWS activityId accepted -> task aws_credit", rr.status_code == 200 and rr.json()["activity"] == "budgets" and rr.json()["task_id"])
        tid = rr.json()["task_id"]
        t = core.q("SELECT * FROM tasks WHERE id=?", (tid,), one=True)
        ok("route run: task params (activities, region, defaults)", t["type"] == "aws_credit" and json.loads(t["params"])["activities"] == ["budgets"]
           and json.loads(t["params"])["region"] == "ap-northeast-1" and json.loads(t["params"])["hold_minutes"] == 5)
        ok("route run: second run while running -> 409", c.post(f"/api/accounts/{aid}/aws/credits/activities/lambda/run", json={"confirm": True}).status_code == 409)
        ok("route cleanup: blocked while running (409)", c.post(f"/api/accounts/{aid}/aws/credits/cleanup", json={"confirm": True}).status_code == 409)
        jr = c.get(f"/api/accounts/{aid}/aws/credits").json()
        ok("route credits: running_task + last_run on activity", jr["running_task"]["id"] == tid
           and {x["key"]: x for x in jr["activities"]}["budgets"]["last_run"]["status"] == "running")
        # 执行后台任务
        CALLS.clear()
        asyncio.run(tasks._run_once(core.q("SELECT * FROM tasks WHERE id=?", (tid,), one=True)))
        t = core.q("SELECT * FROM tasks WHERE id=?", (tid,), one=True)
        res = json.loads(t["result"])
        ok("task: done, message says 等待 AWS 识别 (not 已获得)", t["status"] == "done" and "等待 AWS 识别" in t["message"] and "已获得" not in t["message"])
        ok("task: step executed with result", res["steps"]["budgets"]["status"] == "executed" and res["steps"]["budgets"]["message"] == "已执行，等待 AWS 识别")
        ok("task: credits re-fetched after run (cache updated)", calls("freetier", "get_account_plan_state") and RC._CREDITS[aid][1]["state"] == "ok")
        logs = [x["msg"] for x in tasks.get_logs(tid)]
        ok("task: logs show AWS 当前状态 after refresh", any(m.startswith("AWS 当前状态：Budgets 成本预算 进行中") for m in logs))
        ok("task: telegram summary sent", any("新号 Credit 任务" in m for m in SENT))
        jr = c.get(f"/api/accounts/{aid}/aws/credits").json()
        lr = {x["key"]: x for x in jr["activities"]}["budgets"]["last_run"]
        ok("route credits: last_run executed after task", lr["status"] == "executed" and lr["task_id"] == tid and jr["running_task"] is None)

        # 一键全部
        ok("route run-all: confirm required", c.post(f"/api/accounts/{aid}/aws/credits/run-all", json={}).status_code == 400)
        EC2.DRY = "UnauthorizedOperation"
        ra = c.post(f"/api/accounts/{aid}/aws/credits/run-all", json={"confirm": True}).json()
        ok("route run-all: pending only, in order (ec2 completed skipped)", ra["activities"] == ["budgets", "lambda", "rds", "bedrock"] and ra["skipped"] == [])
        EC2.DRY = "DryRunOperation"
        tid2 = ra["task_id"]
        CALLS.clear()
        LSTATE.clear()
        Lambda.ROLE_NOT_READY = 0
        RDS.SEQ = ["creating", "available"]
        BR.MODE = "denied"
        with mock.patch("httpx.get", return_value=mock.Mock(status_code=200, text="ok")):
            asyncio.run(tasks._run_once(core.q("SELECT * FROM tasks WHERE id=?", (tid2,), one=True)))
        BR.MODE = "ok"
        t2 = core.q("SELECT * FROM tasks WHERE id=?", (tid2,), one=True)
        st2 = json.loads(t2["result"])["steps"]
        ok("task run-all: one failure doesn't stop others", [st2[k]["status"] for k in ("budgets", "lambda", "rds", "bedrock")]
           == ["executed", "executed", "executed", "failed"])
        ok("task run-all: failed -> friendly message, task failed 3/4", t2["status"] == "failed" and t2["message"].startswith("3/4 已执行")
           and "bedrock:InvokeModel" in t2["message"] and "Traceback" not in t2["message"])
        ok("task run-all: resources cleaned (lambda/role/rds)", not LSTATE.get("fn") and not LSTATE.get("role") and calls("rds", "delete_db_instance"))
        # run-all：权限检查失败的活动跳过
        RC._CREDITS.pop(aid, None)
        FT.MODE = "denied"
        Budgets.DENY = True
        ra2 = c.post(f"/api/accounts/{aid}/aws/credits/run-all", json={"confirm": True, "activities": ["budgets", "bedrock"]}).json()
        ok("route run-all: no freetier state -> runs requested, denied skipped", ra2["activities"] == ["bedrock"]
           and ra2["skipped"][0]["activity"] == "budgets")
        Budgets.DENY = False
        FT.MODE = "ok"
        tasks.stop_task(ra2["task_id"])
        t3 = core.q("SELECT * FROM tasks WHERE id=?", (ra2["task_id"],), one=True)
        ok("task: stop works", t3["status"] == "stopped")
        # 清理
        ok("route cleanup: confirm required", c.post(f"/api/accounts/{aid}/aws/credits/cleanup", json={}).status_code == 400)
        CALLS.clear()
        cl = c.post(f"/api/accounts/{aid}/aws/credits/cleanup", json={"confirm": True, "include_budget": True}).json()
        ok("route cleanup: returns deleted list incl. budget", any(d["type"] == "budget" for d in cl["deleted"]) and cl["regions"] == ["ap-northeast-1"])
        aud = [x["action"] for x in core.q("SELECT action FROM audit ORDER BY id")]
        ok("audit: run / run-all / cleanup recorded", "aws-credit-run" in aud and "aws-credit-run-all" in aud and "aws-credit-cleanup" in aud)
        ok("route: non-aws account 400", c.get("/api/accounts/99999/aws/credits").status_code == 404)
        # telegram /credits 段
        c.get(f"/api/accounts/{aid}/aws/credits?refresh=true")
        lines = telegram.aws_free_plan_lines()
        ok("telegram /credits: AWS free plan line from cache only", lines and "FREE 计划，剩余 $118.42" in lines[1] and "1/5 已完成" in lines[1])

# ================= 10. Web / demo / App 静态检查 =================
A = open(os.path.join(ROOT, "web", "js", "aws.js"), encoding="utf-8").read()
C = open(os.path.join(ROOT, "web", "js", "core.js"), encoding="utf-8").read()
I = open(os.path.join(ROOT, "web", "js", "instances.js"), encoding="utf-8").read()
M = open(os.path.join(ROOT, "demo", "mock.js"), encoding="utf-8").read()
AJ = open(os.path.join(ROOT, "android", "app", "src", "main", "java", "com", "tricloud", "app", "AccountActivity.java"), encoding="utf-8").read()
IS = open(os.path.join(ROOT, "ios", "TriCloud", "AwsCredit.swift"), encoding="utf-8").read()
IP = open(os.path.join(ROOT, "ios", "TriCloud", "AccountPage.swift"), encoding="utf-8").read()
ok("web: AWS tab 新号 Credit registered", '["credit", "新号 Credit"]' in C and "credit: tabAwsCredit" in I)
ok("web: card endpoints (credits / run / run-all / cleanup)", "/aws/credits" in A and "/aws/credits/activities/" in A and "/aws/credits/run-all" in A
   and "/aws/credits/cleanup" in A)
ok("web: honest wording 已执行，等待 AWS 识别", "已执行，等待 AWS 识别" in A and "已获得奖励" not in A)
ok("web: run-all double confirm mentions credit cost", A.count("confirmBox(") >= 3 and "从 credit 中扣" in A)
ok("demo mock: credits + run + cleanup", "/aws/credits" in M and "run-all" in M and "cleanup" in M)
ok("android: credit tab + endpoints", '{"credit", "新号 Credit"}' in AJ and "/aws/credits" in AJ and "已执行，等待 AWS 识别" in AJ)
ok("ios: credit tab + endpoints", '("credit", "新号 Credit")' in IP and "/aws/credits" in IS and "已执行，等待 AWS 识别" in IS)
bv = RC.build_view(aid, {"state": "ok", "plan": {"type": "PAID"}, "activities": [], "activities_denied": True,
                         "activities_error": "没有 freetier 读权限"})
ok("activities denied: banner note + 无权限读取 status (not AWS 未返回)",
   "无法读取活动状态" in bv["notes"][0] and all(a["status_text"] == "无权限读取" for a in bv["activities"]))
bv2 = RC.build_view(aid, {"state": "ok", "plan": {"type": "FREE"}, "activities": []})
ok("activities empty but readable: AWS 未返回", all(a["status_text"] == "AWS 未返回" for a in bv2["activities"]) and "无法读取" not in bv2["notes"][0])

print(f"\n{sum(x[1] for x in R)}/{len(R)} passed")
sys.exit(0 if all(x[1] for x in R) else 1)
