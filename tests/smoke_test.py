"""TriCloud 本地冒烟测试（无真实网络调用，全部 mock/本地逻辑）。"""
import os
import sys
import tempfile
import time
from unittest.mock import patch

tmp = tempfile.mkdtemp()
os.environ["DATA_DIR"] = tmp
os.environ["PANEL_PASSWORD"] = "test123456"
sys.path.insert(0, os.path.expanduser("~/workspace/tricloud"))

from fastapi.testclient import TestClient
from app.main import app


def main():
    with TestClient(app, raise_server_exceptions=False) as c:
        r = c.get("/api/providers")
        assert r.status_code == 401, r.status_code
        print("1. 未登录拦截 OK", flush=True)

        assert c.post("/api/login", json={"password": "wrong"}).status_code == 403
        print("2. 错误密码拒绝 OK", flush=True)

        assert c.post("/api/login", json={"password": "test123456"}).status_code == 200
        print("3. 登录 OK", flush=True)

        provs = c.get("/api/providers").json()
        assert [p["id"] for p in provs] == ["oci", "aws", "azure"]
        assert provs[0]["supports_snatch"] is True and len(provs[0]["fields"]) == 7
        print("4. providers 元信息 OK", flush=True)

        # 5. 账号创建：mock 掉 provider.test（本地只验证流程，真实连通性由用户在面板里测）
        from app import db
        from app.providers import get_provider
        for pid in ("oci", "aws", "azure"):
            with patch.object(get_provider(pid), "test", return_value=None):
                r = c.post("/api/accounts", json={
                    "provider": pid, "name": f"{pid}-test",
                    "creds": {"dummy": "x"}})
                assert r.status_code == 200, (pid, r.status_code, r.text)
        accs = c.get("/api/accounts").json()
        assert len(accs) == 3, accs
        print("5. 账号增查 OK", flush=True)

        # 5b. provider.test 抛异常时 API 返回 400 而不是 500
        with patch.object(get_provider("oci"), "test", side_effect=RuntimeError("auth failed")):
            r = c.post("/api/accounts", json={
                "provider": "oci", "name": "bad", "creds": {}})
            assert r.status_code == 400 and "auth failed" in r.json()["detail"], r.text
        print("   凭证校验失败优雅返回 400 OK", flush=True)

        # 6. 实例列表：mock list_instances
        from app.providers.base import InstanceInfo
        fake_inst = InstanceInfo(id="i-123", name="web-1", status="running",
                                 status_text="RUNNING", shape="VM.Standard.E2.1.Micro",
                                 cpu="1", memory="1", public_ip="1.2.3.4",
                                 private_ip="10.0.0.5", region="ap-tokyo-1")
        oci_id = [a["id"] for a in accs if a["provider"] == "oci"][0]
        with patch.object(get_provider("oci"), "list_instances", return_value=[fake_inst]):
            lst = c.get(f"/api/accounts/{oci_id}/instances").json()
            assert lst[0]["public_ip"] == "1.2.3.4" and lst[0]["status"] == "running", lst
        print("6. 实例列表 OK", flush=True)

        # 7. 实例操作走后台任务：mock instance_action
        with patch.object(get_provider("oci"), "instance_action", return_value="实例已重启") as m:
            r = c.post(f"/api/accounts/{oci_id}/action",
                       json={"instance": fake_inst.__dict__, "action": "restart", "params": {}})
            assert r.status_code == 200, r.text
            job_id = r.json()["job_id"]
            for _ in range(50):
                j = c.get(f"/api/jobs/{job_id}").json()
                if j["status"] not in ("queued", "running"):
                    break
                time.sleep(0.2)
            assert j["status"] == "success" and j["result"] == "实例已重启", j
            m.assert_called_once()
        print("7. 实例操作任务 OK", flush=True)

        # 7b. 不支持的操作被拒绝
        r = c.post(f"/api/accounts/{oci_id}/action",
                   json={"instance": fake_inst.__dict__, "action": "nonsense", "params": {}})
        assert r.status_code == 400, r.text
        print("   非法操作拒绝 OK", flush=True)

        # 8. 创建实例走后台任务：mock create_instance
        with patch.object(get_provider("oci"), "create_instance",
                          return_value="实例创建成功") as m:
            r = c.post(f"/api/accounts/{oci_id}/create", json={"shape": "VM.Standard.E2.1.Micro"})
            assert r.status_code == 200, r.text
            job_id = r.json()["job_id"]
            for _ in range(50):
                j = c.get(f"/api/jobs/{job_id}").json()
                if j["status"] not in ("queued", "running"):
                    break
                time.sleep(0.2)
            assert j["status"] == "success", j
        print("8. 创建实例任务 OK", flush=True)

        # 8b. 抢机：OCI 支持，AWS 不支持
        with patch.object(get_provider("oci"), "snatch_instance", return_value="抢机成功"):
            r = c.post(f"/api/accounts/{oci_id}/snatch", json={"shape": "VM.Standard.A1.Flex"})
            assert r.status_code == 200, r.text
        aws_id = [a["id"] for a in accs if a["provider"] == "aws"][0]
        r = c.post(f"/api/accounts/{aws_id}/snatch", json={})
        assert r.status_code == 400, r.text
        print("   抢机路由 OK", flush=True)

        # 9. 任务停止
        from app import jobs
        def _long(ctx):
            for _ in range(100):
                if ctx.should_stop():
                    return "stopped-early"
                time.sleep(0.05)
            return "finished"
        jid3 = jobs.submit("test", "oci", None, "长任务", _long)
        time.sleep(0.5)
        assert jobs.request_stop(jid3) is True
        for _ in range(50):
            j3 = db.job_get(jid3)
            if j3["status"] not in ("queued", "running", "stop_requested"):
                break
            time.sleep(0.2)
        assert j3["status"] == "stopped", j3
        print("9. 任务停止 OK", flush=True)

        # 10. 任务列表/删除
        lst = c.get("/api/jobs?limit=10").json()
        assert len(lst) >= 3
        assert c.delete(f"/api/jobs/{jid3}").status_code == 200
        print("10. 任务 API OK", flush=True)

        # 11. 改密码
        r = c.post("/api/change-password",
                   json={"old_password": "test123456", "new_password": "newpass99"})
        assert r.status_code == 200, r.text
        c.post("/api/logout")
        assert c.post("/api/login", json={"password": "newpass99"}).status_code == 200
        print("11. 改密码 OK", flush=True)

        # 12. 凭证加密存储，无明文落盘
        from app.crypto import encrypt_secret, decrypt_secret
        assert decrypt_secret(encrypt_secret('{"a": 1}')) == '{"a": 1}'
        aid = db.account_create("oci", "enc-test", {"k": "v secret"})
        assert db.account_get(aid)["creds"] == {"k": "v secret"}
        raw = open(os.path.join(tmp, "tricloud.db"), "rb").read()
        assert b"v secret" not in raw, "凭证明文落盘！"
        print("12. 凭证加密存储 OK", flush=True)

        print("\n全部冒烟测试通过", flush=True)


main()
