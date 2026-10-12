"""v1.4 批量添加账号：解析粘贴的多段 JSON 与 OCI config。

支持的写法（可以混在一起粘贴）：
1. JSON 对象，一段或多段（逐个排列、逗号分隔或放在数组里都行）：
   {"provider": "aws", "name": "东京", "cred": {"access_key": "...", "secret_key": "...", "region": "ap-northeast-1"}}
   也可以不写 cred，直接平铺：{"provider": "azure", "name": "学生", "tenant_id": "...", "client_id": "...", ...}
   不写 provider 时按字段推断（access_key → AWS，tenant_id → Azure，tenancy → OCI）。
   Azure CLI `az ad sp create-for-rbac` 的输出（appId / password / tenant）也能识别，需另加 subscription_id。
2. OCI config（~/.oci/config 格式），一个 [PROFILE] 一个账号，私钥 PEM 直接贴在该段后面：
   [东京]
   user=ocid1.user...
   fingerprint=aa:bb:...
   tenancy=ocid1.tenancy...
   region=ap-tokyo-1
   -----BEGIN PRIVATE KEY-----
   ...
   -----END PRIVATE KEY-----
"""
import json
import re

from .providers import greencloud_provider as gcp  # greencloud

SECTION = re.compile(r"^\s*\[([^\]\r\n\"{}]+)\]\s*$")
PEM = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S)
OCI_KEYS = {"user", "fingerprint", "tenancy", "region", "pass_phrase", "compartment", "home_region", "proxy", "name", "key_content"}
ALIASES = {
    "aws": {"aws_access_key_id": "access_key", "accesskeyid": "access_key", "access_key_id": "access_key",
            "aws_secret_access_key": "secret_key", "secretaccesskey": "secret_key", "secret_access_key": "secret_key"},
    "azure": {"appid": "client_id", "app_id": "client_id", "password": "client_secret", "tenant": "tenant_id",
              "subscription": "subscription_id", "subscriptionid": "subscription_id", "clientid": "client_id",
              "clientsecret": "client_secret", "tenantid": "tenant_id"},
    "oci": {"key": "key_content", "private_key": "key_content"},
}
META = {"provider", "name", "cred", "cloud", "type", "remark", "cloud_created_at"}


def guess_provider(d):
    keys = {str(k).lower() for k in d}
    if keys & gcp.JSON_KEYS:  # greencloud
        return gcp.PROVIDER_ID  # greencloud
    if keys & {"access_key", "aws_access_key_id", "accesskeyid", "access_key_id", "secret_key"}:
        return "aws"
    if keys & {"tenant_id", "client_id", "client_secret", "subscription_id", "appid", "tenant"}:
        return "azure"
    if keys & {"tenancy", "fingerprint", "key_content"}:
        return "oci"
    return None


def _norm(prov, cred):
    al = ALIASES.get(prov, {})
    out = {}
    for k, v in cred.items():
        k2 = al.get(str(k).lower().replace("-", "_"), str(k).lower()) if str(k).lower() not in ("key_content",) else "key_content"
        if v not in (None, ""):
            out[k2] = v.strip() if isinstance(v, str) and k2 != "key_content" else v
    return out


def from_json(obj, default_provider=None):
    if not isinstance(obj, dict):
        raise ValueError("不是 JSON 对象")
    prov = str(obj.get("provider") or obj.get("cloud") or obj.get("type") or "").lower() or None
    cred = obj.get("cred") if isinstance(obj.get("cred"), dict) else {k: v for k, v in obj.items() if k not in META}
    prov = gcp.ALIASES.get(prov, prov) if prov else prov  # greencloud
    prov = prov or guess_provider(cred) or default_provider
    if gcp.is_gc(prov):  # greencloud
        return gcp.from_json(obj, str(obj.get("name") or obj.get("remark") or "").strip(), cred)  # greencloud
    if prov not in ("oci", "aws", "azure"):
        raise ValueError("无法判断云厂商，请加上 \"provider\": \"oci\" / \"aws\" / \"azure\"")
    cred = _norm(prov, cred)
    name = str(obj.get("name") or obj.get("remark") or obj.get("displayName") or "").strip()
    return {"provider": prov, "name": name, "cred": cred, "cloud_created_at": obj.get("cloud_created_at")}


def from_oci_config(text):
    """一段 OCI config 文本 → 若干账号。没有 [PROFILE] 头时整段当作一个账号。"""
    out, cur = [], None
    pems = PEM.findall(text)
    # 先把 PEM 换成占位符，便于逐行解析，同时记录它属于哪个 profile
    holder = text
    for i, p in enumerate(pems):
        holder = holder.replace(p, f"\n__PEM_{i}__\n", 1)
    for line in holder.splitlines():
        s = line.strip()
        if not s or s.startswith("#") or s.startswith(";"):
            continue
        m = SECTION.match(s)
        if m:
            cur = {"name": m.group(1).strip(), "cred": {}}
            out.append(cur)
            continue
        if cur is None:
            cur = {"name": "", "cred": {}}
            out.append(cur)
        pm = re.fullmatch(r"__PEM_(\d+)__", s)
        if pm:
            cur["cred"]["key_content"] = pems[int(pm.group(1))].strip() + "\n"
            continue
        if "=" in s:
            k, v = s.split("=", 1)
            k = k.strip().lower()
            if k == "key_file":
                cur["key_file"] = v.strip()
            elif k in OCI_KEYS:
                if k == "name":
                    cur["name"] = v.strip()
                else:
                    cur["cred"][k] = v.strip()
    res = []
    for c in out:
        item = {"provider": "oci", "name": c["name"] if c["name"] and c["name"].upper() != "DEFAULT" else "", "cred": c["cred"]}
        if not c["cred"].get("key_content") and c.get("key_file"):
            item["error"] = f"key_file={c['key_file']} 在面板服务器上读不到，请把私钥 PEM 直接贴在该段后面"
        res.append(item)
    return res


def _is_json_start(text, i):
    if text[i] == "{":
        return True
    if text[i] == "[":
        line_end = text.find("\n", i)
        line = text[i: line_end if line_end >= 0 else len(text)]
        return not SECTION.match(line)
    return False


def _next_start(text, i):
    """JSON 解析失败后，从下一行起找下一个 JSON 对象或 [PROFILE] 段的开头继续解析。"""
    pos = text.find("\n", i)
    while pos >= 0:
        line_start = pos + 1
        nl = text.find("\n", line_start)
        line = text[line_start: nl if nl >= 0 else len(text)]
        if line.startswith("{") or SECTION.match(line):
            return line_start
        pos = nl
    return len(text)


OTHER_SIGNS = re.compile(r"AKIA|ASIA|access.?key|secret|tenant|client|subscription|租户|订阅|应用程序|客户端", re.I)


def _parse_text(seg):
    """非 JSON 文本：标准 OCI config 走原解析，其余（控制台复制、环境变量、CSV…）走自动识别。"""
    gc = gcp.sniff(seg)  # greencloud
    if gc:  # greencloud
        return gc  # greencloud
    looks_cfg = re.search(r"^\s*(user|tenancy|fingerprint)\s*=\s*\S", seg, re.M) and not OTHER_SIGNS.search(PEM.sub("", seg))
    if looks_cfg:
        return from_oci_config(seg)
    got = sniff(seg)
    if not got and re.search(r"^\s*\[", seg, re.M):
        return from_oci_config(seg)
    return got


def parse(text, default_provider=None):
    """返回 [{"provider", "name", "cred"} 或 {"error"}]，顺序与粘贴顺序一致。错误信息里不回显凭证内容。"""
    text = (text or "").replace("\r\n", "\n")
    dec = json.JSONDecoder()
    items, i, n = [], 0, len(text)
    while i < n:
        while i < n and text[i] in " \t\n,;":
            i += 1
        if i >= n:
            break
        if _is_json_start(text, i):
            try:
                obj, j = dec.raw_decode(text, i)
            except json.JSONDecodeError as e:
                end = _next_start(text, i)
                items.append({"error": f"JSON 解析失败：{e.msg}（第 {text.count(chr(10), 0, e.pos) + 1} 行）"})
                i = end
                continue
            for o in (obj if isinstance(obj, list) else [obj]):
                try:
                    items.append(from_json(o, default_provider))
                except ValueError as e:
                    items.append({"error": str(e), "name": str(o.get("name") or "") if isinstance(o, dict) else ""})
            i = j
            continue
        # 非 JSON：取到下一个 JSON 起点之前，作为 OCI config 解析
        j = i
        while j < n:
            nl = text.find("\n", j)
            if nl < 0:
                j = n
                break
            j = nl + 1
            k = j
            while k < n and text[k] in " \t":
                k += 1
            if k < n and _is_json_start(text, k):
                j = k
                break
        seg = text[i:j]
        if seg.strip():
            parsed = _parse_text(seg)
            if parsed:
                items += parsed
            else:
                items.append({"error": "无法识别的内容（没有找到任何云账号凭证）"})
        i = j
    return items


# ---------------- v1.6：从随手复制的一堆内容里自动识别 ----------------
# 控制台复制的「标签: 值」/「标签」换行「值」、环境变量（export AWS_ACCESS_KEY_ID=...）、
# AWS 下载的 accessKeys.csv / credentials.csv、Azure 门户「应用注册」页、OCI 配置预览，混着贴也行。

def _lk(s):
    return re.sub(r"[\s_\-\.()（）/:：\"'`*$]", "", s.lower()).replace("export", "", 1) if s else ""


LABELS = {}
for _p, _k, _names in [
    ("aws", "access_key", "accesskeyid accesskey awsaccesskeyid awsaccesskey ak 访问密钥id 访问密钥 访问key accesskeyidak"),
    ("aws", "secret_key", "secretaccesskey secretkey awssecretaccesskey awssecretkey sk 秘密访问密钥 私有访问密钥 secretaccesskeysk 私密访问密钥"),
    ("azure", "tenant_id", "tenantid tenant 租户id 目录id 目录租户id 租户 directoryid directorytenantid azuretenantid armtenantid"),
    ("azure", "client_id", "clientid appid applicationid 应用程序id 应用程序客户端id 客户端id 应用id applicationclientid azureclientid armclientid"),
    ("azure", "client_secret", "clientsecret clientsecretvalue secretvalue 客户端密码 客户端密码值 客户端机密 机密值 azureclientsecret armclientsecret"),
    ("azure", "subscription_id", "subscriptionid subscription 订阅id 订阅 azuresubscriptionid armsubscriptionid"),
    ("oci", "user", "user userocid userid 用户ocid 用户"),
    ("oci", "tenancy", "tenancy tenancyocid tenancyid 租户ocid 租赁ocid"),
    ("oci", "fingerprint", "fingerprint 指纹 apikey指纹 密钥指纹"),
    ("oci", "pass_phrase", "passphrase 私钥密码"),
    ("oci", "compartment", "compartment compartmentid compartmentocid 区间 区间ocid"),
    ("oci", "home_region", "homeregion 主区域"),
    ("oci", "key_file", "keyfile"),
    (None, "region", "region 区域 地域 默认区域 defaultregion awsdefaultregion awsregion ociregion 区域标识符"),
    (None, "secret", "secret 密钥值 值 value password 密码"),
    (None, "name", "name 名称 备注 备注名 备注名称 账号名 账号名称 账户名 remark alias profile 账号 账户"),
]:
    for _n in _names.split():
        LABELS[_n] = (_p, _k)

R_AKIA = re.compile(r"\b((?:AKIA|ASIA)[A-Z0-9]{16})\b")
R_SECRET40 = re.compile(r"(?<![A-Za-z0-9/+=])([A-Za-z0-9/+]{40})(?![A-Za-z0-9/+=])")
R_OCID = re.compile(r"\b(ocid1\.(user|tenancy|compartment)\.[a-z0-9]+\.[a-z0-9\-]*\.[a-z0-9]+)\b")
R_FP = re.compile(r"\b((?:[0-9a-f]{2}:){15}[0-9a-f]{2})\b")
R_REGION = re.compile(r"\b((?:us|eu|ap|sa|ca|me|af|il|mx|uk|jp|kr|in|sg|au|br|de|fr|ch|se|it|es|nl|cn)-(?:gov-)?[a-z]+-\d)\b")
R_AZSECRET = re.compile(r"(?<![A-Za-z0-9_.~\-])([A-Za-z0-9_.\-]*~[A-Za-z0-9_.~\-]{20,})(?![A-Za-z0-9_.~\-])")
R_GUID = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")
R_KV = re.compile(r"""^\s*(?:export\s+|set\s+|\$env:)?["'`]?([^:=：\n]{1,40}?)["'`]?\s*[:=：]\s*(.*?)\s*,?\s*$""", re.I)
PROV_WORDS = {"aws": "aws", "amazon": "aws", "亚马逊": "aws", "amazonwebservices": "aws", "azure": "azure", "微软": "azure",
              "microsoftazure": "azure", "oci": "oci", "oracle": "oci", "oraclecloud": "oci", "甲骨文": "oci"}
REQ = {"oci": ("user", "tenancy", "fingerprint", "key_content", "region"),
       "aws": ("access_key", "secret_key"),
       "azure": ("tenant_id", "client_id", "client_secret", "subscription_id")}


def _clean_val(v):
    v = v.strip().strip(",;").strip().strip("\"'`").strip()
    return v


def _label(s):
    k = _lk(s)
    return LABELS.get(k)


def sniff(text):
    """把随手复制的内容识别成若干账号：[{"provider", "name", "cred"} 或带 "error"]。识别不到返回 []。"""
    text = (text or "").replace("\r\n", "\n")
    pems = PEM.findall(text)
    for i, p in enumerate(pems):
        text = text.replace(p, f"\n__PEM_{i}__\n", 1)
    facts = []          # (prov|None, key, value)
    pending_label = None
    csv_cols = None
    queue = text.split("\n")
    while queue:
        line = queue.pop(0).strip()
        if not line or line.startswith("#") or line.startswith("//"):
            continue
        pm = re.fullmatch(r"__PEM_(\d+)__", line)
        if pm:
            facts.append(("oci", "key_content", pems[int(pm.group(1))].strip() + "\n"))
            pending_label = None
            continue
        sm = SECTION.match(line)
        if sm:
            facts.append((None, "name", sm.group(1).strip()))
            pending_label = None
            continue
        low = line.lower()
        # AWS 下载的 CSV：表头含 Access key ID / Secret access key
        if "access key id" in low and "secret access key" in low and "," in line:
            cols = [_lk(c) for c in line.split(",")]
            csv_cols = {k: cols.index(c) for k, c in (("access_key", "accesskeyid"), ("secret_key", "secretaccesskey"), ("name", "username")) if c in cols}
            continue
        if csv_cols and line.count(",") >= 1:
            cells = [c.strip().strip('"') for c in line.split(",")]
            if len(cells) > max(csv_cols.values()) and R_AKIA.search(cells[csv_cols.get("access_key", 0)] or ""):
                if "name" in csv_cols and cells[csv_cols["name"]]:
                    facts.append((None, "name", cells[csv_cols["name"]]))
                facts.append(("aws", "access_key", cells[csv_cols["access_key"]]))
                if "secret_key" in csv_cols:
                    facts.append(("aws", "secret_key", cells[csv_cols["secret_key"]]))
                continue
        # 单独一行的标签（门户复制常见：标签一行、值下一行）
        bare_line = line.strip()
        if bare_line.endswith("=") and _label(bare_line.rstrip("=").strip()):
            # 环境变量留空（AZURE_CLIENT_ID=）：当作没给，不能被当成账号名
            pending_label = None
            continue
        lab = _label(line.rstrip(":：").strip())
        if lab:
            pending_label = lab
            continue
        kv = R_KV.match(line)
        if kv and kv.group(2) and not re.match(r"^https?$", kv.group(1).strip(), re.I):
            lab = _label(kv.group(1))
            if lab:
                v = _clean_val(kv.group(2))
                if lab[1] != "name" and " " in v.strip():
                    # 一行里有多对「标签: 值」（如 AK: xxx  SK: yyy）：值取第一段，其余放回队列
                    first, rest = v.split(None, 1)
                    if R_KV.match(rest) and _label(R_KV.match(rest).group(1)):
                        queue.insert(0, rest)
                        v = _clean_val(first)
                if v:
                    facts.append((lab[0], lab[1], v))
                pending_label = None
                continue
        if pending_label:
            facts.append((pending_label[0], pending_label[1], _clean_val(line)))
            pending_label = None
            continue
        # 无标签：按值的形状识别
        found = False
        for m in R_AKIA.finditer(line):
            pre = line[:m.start()].strip(" :：-|,\t")
            if pre and len(pre) <= 20 and not R_SECRET40.search(pre):
                facts.append((None, "name", pre))
            facts.append(("aws", "access_key", m.group(1)))
            found = True
            rest = line[:m.start()] + " " + line[m.end():]
            sm2 = R_SECRET40.search(rest)
            if sm2:
                facts.append(("aws", "secret_key", sm2.group(1)))
        for m in R_OCID.finditer(line):
            facts.append(("oci", m.group(2), m.group(1)))
            found = True
        for m in R_FP.finditer(line):
            facts.append(("oci", "fingerprint", m.group(1)))
            found = True
        if found:
            continue
        rm = R_REGION.fullmatch(line)
        if rm:
            facts.append((None, "region", rm.group(1)))
            continue
        if R_SECRET40.fullmatch(line) and facts and facts[-1][:2] == ("aws", "access_key"):
            facts.append(("aws", "secret_key", line))
            continue
        if R_AZSECRET.fullmatch(line):
            facts.append((None, "secret", line))
            continue
        w = _lk(line)
        if w in PROV_WORDS:
            facts.append((PROV_WORDS[w], "_hint", ""))
            continue
        if len(line) <= 30 and not R_GUID.search(line) and "://" not in line and not re.search(r"[A-Za-z0-9+/]{24,}", line):
            facts.append((None, "_bare", line))

    accounts = []
    cur = None

    def new(prov=None):
        nonlocal cur
        cur = {"prov": prov, "cred": {}, "name": "", "bare": ""}
        accounts.append(cur)

    def complete(a):
        return a["prov"] and all(a["cred"].get(k) for k in REQ[a["prov"]])

    new()
    for prov, key, val in facts:
        if key == "_bare":
            if not cur["cred"] and not cur["name"]:
                cur["bare"] = val
            elif complete(cur):
                new()
                cur["bare"] = val
            continue
        if key == "_hint":
            if cur["cred"] and cur["prov"] and cur["prov"] != prov:
                new(prov)
            elif not cur["prov"]:
                cur["prov"] = prov
            continue
        if key == "name":
            if cur["cred"] and (cur["name"] or complete(cur)):
                new()
            elif cur["name"] and not cur["cred"]:
                pass
            cur["name"] = val
            continue
        if key == "secret":
            if cur["prov"] == "aws" or (not cur["prov"] and cur["cred"].get("access_key")):
                prov, key = "aws", "secret_key"
            else:
                prov, key = "azure", "client_secret"
        if key == "region" or (prov == "oci" and key == "home_region"):
            if cur["cred"].get(key) and complete(cur):
                new(cur["prov"])
            cur["cred"][key] = val
            continue
        if cur["prov"] and prov != cur["prov"] and cur["cred"] and any(k not in ("region",) for k in cur["cred"]):
            new(prov)
        elif cur["cred"].get(key):
            new(prov)
        cur["prov"] = cur["prov"] or prov
        cur["cred"][key] = val

    res = []
    for a in accounts:
        if not a["prov"]:
            continue
        cred = {k: v for k, v in a["cred"].items()}
        if not any(k in cred for k in REQ[a["prov"]]):
            continue
        name = a["name"] or a["bare"]
        if name.upper() == "DEFAULT":
            name = ""
        item = {"provider": a["prov"], "name": name, "cred": cred}
        if a["prov"] == "aws":
            cred.setdefault("region", "us-east-1")
        kf = cred.pop("key_file", None)
        if a["prov"] == "oci" and not cred.get("key_content") and kf:
            item["error"] = f"key_file={kf} 在面板服务器上读不到，请把私钥 PEM 直接贴在该段后面"
        res.append(item)
    return res
