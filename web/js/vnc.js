// VNC 控制台（VirtFusion）：后端开启 VNC 并返回密码，前端用内置 noVNC
// （web/vendor/novnc，v1.5.0）连面板后端的 websocket 中继（/vnc-ws），
// 由服务端经账号代理转发到绿云的 wss 端点——浏览器直连绿云 wss 会被断开。
// 弹窗关闭后轮询检测元素已脱离文档，自动断开连接，避免残留会话。
import { api, modal, rq } from "./core.js";
import { t } from "./i18n.js";

export async function openVnc(acc, inst) {
  let rfb = null, timer = null;
  modal(t("vnc.title", { name: inst.name }), `<div id="vncScr" style="height:68vh;background:#000;border-radius:8px;overflow:hidden"></div>
    <p class="muted" id="vncStat" style="margin-top:8px">${t("vnc.connecting")}</p>`,
    null, t("common.close"), false, async (bg) => {
      const scr = bg.querySelector("#vncScr"), stat = bg.querySelector("#vncStat");
      const cleanup = () => {
        if (timer) { clearInterval(timer); timer = null; }
        if (rfb) { try { rfb.disconnect(); } catch (_) { /* ignore */ } rfb = null; }
      };
      timer = setInterval(() => { if (!scr.isConnected) cleanup(); }, 800);
      try {
        const info = await api(`/accounts/${acc.id}/instances/vnc?instance_id=${encodeURIComponent(inst.id)}&${rq(acc)}`);
        if (!scr.isConnected) return;
        const RFB = (await import("../vendor/novnc/core/rfb.js")).default;
        // 经面板后端中继（/vnc-ws）：浏览器直连绿云 wss 在部分网络下会被中断，中继后浏览器只连面板域名
        const wsUrl = `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/api/accounts/${acc.id}/instances/vnc-ws?instance_id=${encodeURIComponent(inst.id)}&${rq(acc)}`;
        rfb = new RFB(scr, wsUrl, { credentials: { password: info.password } });
        rfb.scaleViewport = true;
        rfb.background = "#000";
        rfb.addEventListener("connect", () => { if (stat.isConnected) stat.textContent = t("vnc.connected"); });
        rfb.addEventListener("disconnect", (e) => { if (stat.isConnected) stat.textContent = t("vnc.disconnected") + ((e.detail && e.detail.reason) ? `（${e.detail.reason}）` : ""); });
        rfb.addEventListener("credentialsrequired", () => rfb.sendCredentials({ password: info.password }));
        rfb.addEventListener("securityfailure", () => { if (stat.isConnected) stat.textContent = t("vnc.failed", { msg: "security" }); });
      } catch (e) {
        if (stat.isConnected) stat.textContent = t("vnc.failed", { msg: e.message });
      }
    });
}
