"""测试辅助：把已国际化的源码还原成中文文案再做字符串断言。

i18n 之后 Web 源码里是 t("key") / 标签数组里的 "key"，Android 里是 getString(R.string.sNNNN)，
原来按中文文案写的静态断言改用这里读源码：把这些引用替换成 zh 目录里的原文（带引号）。
"""
import html, json, os, re, subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_WEB = None
_AND = None


def _web_zh():
    global _WEB
    if _WEB is None:
        js = ("import(process.argv[1]).then(m => process.stdout.write(JSON.stringify(m.STR.zh)))")
        out = subprocess.run(["node", "--input-type=module", "-e", js, "file://" + os.path.join(ROOT, "web", "js", "i18n.js")],
                             capture_output=True, text=True, check=True).stdout
        _WEB = json.loads(out)
    return _WEB


def _and_zh():
    global _AND
    if _AND is None:
        x = open(os.path.join(ROOT, "android", "app", "src", "main", "res", "values", "strings.xml"), encoding="utf-8").read()
        _AND = {}
        for k, v in re.findall(r'<string name="([^"]+)"[^>]*>(.*?)</string>', x, re.S):
            v = html.unescape(v).replace("\\n", "\n").replace("\\'", "'").replace('\\"', '"')
            _AND[k] = v
    return _AND


def web(text):
    zh = _web_zh()
    q = lambda k: json.dumps(zh[k], ensure_ascii=False)
    # 模板字符串里的 ${t("key")} 还原成原文本身（不带引号）
    text = re.sub(r'\$\{t\(\s*"([\w.]+)"\s*\)\}', lambda m: zh[m.group(1)] if m.group(1) in zh else m.group(0), text)
    text = re.sub(r'\bt\(\s*"([\w.]+)"\s*(?:,[^()]*?)?\)', lambda m: q(m.group(1)) if m.group(1) in zh else m.group(0), text)
    text = re.sub(r'"([A-Za-z][\w]*\.[\w.]+)"', lambda m: q(m.group(1)) if m.group(1) in zh else m.group(0), text)
    return text


def android(text):
    zh = _and_zh()
    q = lambda k: json.dumps(zh[k], ensure_ascii=False)
    text = re.sub(r'(?:getString|L10n\.s)\(R\.string\.(\w+)\s*(?:,[^()]*?)?\)', lambda m: q(m.group(1)) if m.group(1) in zh else m.group(0), text)
    return re.sub(r'R\.string\.(\w+)', lambda m: q(m.group(1)) if m.group(1) in zh else m.group(0), text)


def read(path):
    s = open(path, encoding="utf-8").read()
    if path.endswith(".js") and os.sep + "web" + os.sep in path:
        return web(s)
    if path.endswith(".java"):
        return android(s)
    return s
