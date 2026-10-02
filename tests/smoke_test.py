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
        assert all(p["supports_billing"] for p in provs), provs
        aws_meta = [p for p in provs if p["id"] == "aws"][0]
        assert aws_meta["supports_lightsail"] and aws_meta["supports_cloudfront"], aws_meta
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


        # 13. 设置 API：TG 配置读写
        s = c.get("/api/settings").json()
        assert s["tg_bot_token_set"] is False and s["tg_bot_running"] is False, s
        r = c.put("/api/settings", json={"tg_bot_token": "", "tg_chat_id": "12345"})
        assert r.status_code == 200, r.text
        s = c.get("/api/settings").json()
        assert s["tg_chat_id"] == "12345", s
        print("13. 设置 API OK", flush=True)

        # 14. TG 推送：mock send_message，验证任务结束触发通知
        from unittest.mock import patch as _patch
        sent = []
        from app import tg as _tg
        with _patch("app.tg.get_tg_config", return_value=("tok", "123")), \
             _patch("app.tg.send_message", side_effect=lambda t, parse_mode="HTML": sent.append(t) or True):
            _tg.notify_job_finished({"title": "测试任务", "status": "success", "result": "ok"})
            assert sent and "测试任务" in sent[0], sent
        # 未配置 token 时静默跳过
        with _patch("app.tg.send_message", side_effect=lambda t, parse_mode="HTML": sent.append(t) or True):
            _tg.notify_job_finished({"title": "x", "status": "success", "result": ""})
            assert len(sent) == 1, sent
        print("14. TG 通知钩子 OK", flush=True)

        # 15. jobs._run_job 完成后自动走通知（mock urllib 层）
        with _patch("app.tg.get_tg_config", return_value=("tok", "123")), \
             _patch("urllib.request.urlopen") as _url:
            _url.return_value.__enter__.return_value.status = 200
            jidn = jobs.submit("test", "oci", None, "通知测试", lambda ctx: "done")
            for _ in range(50):
                jn = db.job_get(jidn)
                if jn["status"] not in ("queued", "running"):
                    break
                time.sleep(0.2)
            assert jn["status"] == "success", jn
            assert _url.called, "任务完成未触发 TG 推送"
        print("15. 任务完成自动推送 OK", flush=True)

        # 16. 账单接口：三家 mock get_billing
        fake_bill = {"currency": "USD", "period": "2026-10-01 ~ 2026-10-02",
                     "total": 12.5, "services": [{"name": "Compute", "cost": 12.5}],
                     "note": "test"}
        for pid in ("oci", "aws", "azure"):
            aid = [a["id"] for a in accs if a["provider"] == pid][0]
            with patch.object(get_provider(pid), "get_billing", return_value=fake_bill):
                b = c.get(f"/api/accounts/{aid}/billing").json()
                assert b["total"] == 12.5 and b["services"][0]["name"] == "Compute", (pid, b)
        print("16. 三家账单接口 OK", flush=True)

        # 17. Lightsail：列表 + 操作
        fake_ls = [{"name": "ls-1", "state": "running", "bundle": "nano_2_0",
                    "blueprint": "ubuntu_22_04", "public_ip": "3.3.3.3",
                    "private_ip": "192.168.1.2", "ipv6": "", "region": "us-east-1",
                    "zone": "us-east-1a", "created": "2026-01-01"}]
        with patch.object(get_provider("aws"), "list_lightsail", return_value=fake_ls) as m:
            lst = c.get(f"/api/accounts/{aws_id}/lightsail?region=").json()
            assert lst[0]["name"] == "ls-1" and lst[0]["state"] == "running", lst
            m.assert_called_once()
        with patch.object(get_provider("aws"), "lightsail_action",
                          return_value="Lightsail 实例 ls-1 已停止") as m:
            r = c.post(f"/api/accounts/{aws_id}/lightsail/action",
                       json={"name": "ls-1", "action": "stop", "region": "us-east-1"})
            assert r.status_code == 200 and "已停止" in r.json()["message"], r.text
            m.assert_called_once_with({"dummy": "x"}, "ls-1", "stop", "us-east-1")
        # 非法操作被拒绝
        r = c.post(f"/api/accounts/{aws_id}/lightsail/action",
                   json={"name": "ls-1", "action": "nonsense", "region": "us-east-1"})
        assert r.status_code == 400, r.text
        # 非 AWS 账号拒绝
        r = c.get(f"/api/accounts/{oci_id}/lightsail")
        assert r.status_code == 400, r.text
        print("17. Lightsail 接口 OK", flush=True)

        # 18. CloudFront：列表 + 刷新 + 启用停用
        fake_cf = [{"id": "E123", "domain": "d123.cloudfront.net", "status": "Deployed",
                    "enabled": True, "comment": "", "aliases": ["cdn.example.com"],
                    "origins": ["origin.example.com"], "price_class": "100"}]
        with patch.object(get_provider("aws"), "list_cloudfront", return_value=fake_cf):
            lst = c.get(f"/api/accounts/{aws_id}/cloudfront").json()
            assert lst[0]["id"] == "E123" and lst[0]["enabled"] is True, lst
        with patch.object(get_provider("aws"), "cloudfront_invalidate",
                          return_value="缓存刷新已提交") as m:
            r = c.post(f"/api/accounts/{aws_id}/cloudfront/invalidate",
                       json={"distribution_id": "E123", "paths": ["/*"]})
            assert r.status_code == 200, r.text
            m.assert_called_once_with({"dummy": "x"}, "E123", ["/*"])
        with patch.object(get_provider("aws"), "cloudfront_toggle",
                          return_value="已停用") as m:
            r = c.post(f"/api/accounts/{aws_id}/cloudfront/toggle",
                       json={"distribution_id": "E123", "enabled": False})
            assert r.status_code == 200, r.text
            m.assert_called_once_with({"dummy": "x"}, "E123", False)
        r = c.get(f"/api/accounts/{oci_id}/cloudfront")
        assert r.status_code == 400, r.text
        print("18. CloudFront 接口 OK", flush=True)

        # 19. 配额/订阅接口
        fake_q = {"groups": [{"title": "计算", "items": [{"name": "x", "detail": "可用1"}]}],
                  "note": "n"}
        with patch.object(get_provider("oci"), "get_quotas", return_value=fake_q):
            q = c.get(f"/api/accounts/{oci_id}/quotas").json()
            assert q["groups"][0]["title"] == "计算", q
        fake_s = {"items": [{"name": "租户名", "detail": "t"}], "note": ""}
        with patch.object(get_provider("oci"), "get_subscription", return_value=fake_s):
            s = c.get(f"/api/accounts/{oci_id}/subscription").json()
            assert s["items"][0]["detail"] == "t", s
        r = c.get(f"/api/accounts/{aws_id}/subscription")
        assert r.status_code == 400, r.text
        print("19. 配额/订阅接口 OK", flush=True)

        # 20. 一键测活
        with patch.object(get_provider("oci"), "test", return_value=None), \
             patch.object(get_provider("aws"), "test",
                          side_effect=RuntimeError("bad key")):
            lst = c.post("/api/accounts/test-all?provider=oci").json()
            assert len(lst) == 2 and lst[0]["ok"] is True, lst
            lst = c.post("/api/accounts/test-all?provider=aws").json()
            assert lst[0]["ok"] is False and "bad key" in lst[0]["message"], lst
        print("20. 一键测活 OK", flush=True)

        # 21. 监控设置读写
        m0 = c.get(f"/api/accounts/{oci_id}/monitor").json()
        assert m0 == {"monitor_alert": False, "monitor_restart": False}, m0
        r = c.put(f"/api/accounts/{oci_id}/monitor",
                  json={"monitor_alert": True, "monitor_restart": False})
        assert r.status_code == 200, r.text
        m1 = c.get(f"/api/accounts/{oci_id}/monitor").json()
        assert m1["monitor_alert"] is True and m1["monitor_restart"] is False, m1
        print("21. 监控设置 OK", flush=True)

        # 22. 设置扩展字段（每日报告/监控间隔）
        s = c.get("/api/settings").json()
        assert s["daily_report"] is False and s["daily_report_hour"] == 9 \
            and s["monitor_interval_min"] == 5, s
        r = c.put("/api/settings", json={"tg_bot_token": "", "tg_chat_id": "",
                                         "daily_report": True, "daily_report_hour": 8,
                                         "monitor_interval_min": 10})
        assert r.status_code == 200, r.text
        s = c.get("/api/settings").json()
        assert s["daily_report"] is True and s["daily_report_hour"] == 8 \
            and s["monitor_interval_min"] == 10, s
        print("22. 设置扩展 OK", flush=True)

        # 23. 新操作走任务（改名/扩容/开端口参数透传）
        with patch.object(get_provider("oci"), "instance_action",
                          return_value="ok") as m:
            r = c.post(f"/api/accounts/{oci_id}/action",
                       json={"instance": fake_inst.__dict__, "action": "rename",
                             "params": {"new_name": "web2"}})
            assert r.status_code == 200, r.text
            job_id = r.json()["job_id"]
            for _ in range(50):
                j = c.get(f"/api/jobs/{job_id}").json()
                if j["status"] not in ("queued", "running"):
                    break
                time.sleep(0.2)
            assert j["status"] == "success", j
            _, _, action, ctx = m.call_args[0]
            assert action == "rename" and ctx.params == {"new_name": "web2"}, \
                m.call_args
        print("23. 新操作参数透传 OK", flush=True)

        # 24. monitor 模块：状态变化告警 + 每日报告（mock）
        from app import monitor as _mon
        from unittest.mock import patch as _p2
        sent2 = []
        _mon._last_status.clear()
        inst_a = InstanceInfo(id="i-1", name="a", status="running")
        inst_b = InstanceInfo(id="i-1", name="a", status="stopped")
        with _p2("app.tg.send_message",
                 side_effect=lambda t, parse_mode="HTML": sent2.append(t) or True), \
             _p2.object(get_provider("oci"), "list_instances",
                        side_effect=[[inst_a], [inst_b]]), \
             _p2("app.tasks.submit_action", return_value="jid") as _sa:
            accs_mon = db.account_list()
            # 开启账号1的告警+自启
            db.account_set_monitor(accs_mon[0]["id"], True, True)
            _mon._check_once()   # 第一次：建立基线，无告警
            assert sent2 == [], sent2
            _mon._check_once()   # 第二次：running->stopped，告警+自启
            assert any("告警" in t for t in sent2), sent2
            assert _sa.called, "异常停止未触发自动重启"
            db.account_set_monitor(accs_mon[0]["id"], False, False)
        print("24. 监控告警/自启 OK", flush=True)

        print("\n全部冒烟测试通过", flush=True)


main()
