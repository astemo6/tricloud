"""build 30：敏感操作的 Telegram 验证码（目前用于 OCI「切换受限 API」）。

- 通过已绑定的 Bot（设置里的 tg_token + tg_chat_id）发 6 位数字码；没绑定直接拒绝。
- 只在内存里存 sha256（不落库）；5 分钟有效、最多输错 5 次、验证成功立即作废（一次性）；同一用途 60 秒内只发一次。
- 用途 + 对象（如 restrict:3）各自独立，A 账号的码不能用在 B 账号上。
"""
import hashlib
import hmac
import secrets
import threading
import time

TTL = 300
MAX_TRIES = 5
RESEND_GAP = 60

_lock = threading.Lock()
_codes = {}   # key -> {"h": sha256, "exp": ts, "tries": n, "sent": ts}
_now = time.time   # 测试替换


class CodeError(ValueError):
    """kind：not_bound / too_soon / missing / expired / wrong / too_many / send_failed"""

    def __init__(self, kind, wait=0):
        super().__init__(kind)
        self.kind = kind
        self.wait = wait


def _h(code):
    return hashlib.sha256(str(code).encode()).hexdigest()


def bound():
    from . import telegram
    token, chat = telegram.cfg()
    return bool(token and chat)


def issue(key):
    """生成新码（覆盖旧码）。返回明文码，只交给发送函数，不返回给浏览器。"""
    now = _now()
    with _lock:
        old = _codes.get(key)
        if old and now - old["sent"] < RESEND_GAP:
            raise CodeError("too_soon", wait=int(RESEND_GAP - (now - old["sent"])) + 1)
        code = f"{secrets.randbelow(10 ** 6):06d}"
        _codes[key] = {"h": _h(code), "exp": now + TTL, "tries": 0, "sent": now}
        return code


def discard(key):
    with _lock:
        _codes.pop(key, None)


async def send(key, text_fn):
    """text_fn(code) -> 消息正文。发送失败时作废这次的码。"""
    from . import telegram
    if not bound():
        raise CodeError("not_bound")
    code = issue(key)
    ok = await telegram.send(text_fn(code))
    if not ok:
        discard(key)
        raise CodeError("send_failed")
    return {"sent": True, "ttl": TTL}


def verify(key, code):
    """校验并消费验证码；失败抛 CodeError。"""
    code = str(code or "").strip()
    now = _now()
    with _lock:
        rec = _codes.get(key)
        if not rec:
            raise CodeError("missing")
        if now > rec["exp"]:
            _codes.pop(key, None)
            raise CodeError("expired")
        if rec["tries"] >= MAX_TRIES:
            _codes.pop(key, None)
            raise CodeError("too_many")
        if not (len(code) == 6 and code.isdigit() and hmac.compare_digest(rec["h"], _h(code))):
            rec["tries"] += 1
            if rec["tries"] >= MAX_TRIES:
                _codes.pop(key, None)
                raise CodeError("too_many")
            raise CodeError("wrong")
        _codes.pop(key, None)   # 一次性
        return True
