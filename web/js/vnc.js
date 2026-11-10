// VNC 控制台（VirtFusion）：后端开启并返回 wss 地址 + 密码，前端用内置
// noVNC（web/vendor/novnc，v1.5.0）直连面板的 websocket 端点，在弹窗里显示画面。
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
        rfb = new RFB(scr, info.url, { credentials: { password: info.password } });
        rfb.scaleViewport = true;
        rfb.background = "#000";
        rfb.addEventListener("connect", () => { if (stat.isConnected) stat.textContent = t("vnc.connected"); });
        rfb.addEventListener("disconnect", () => { if (stat.isConnected) stat.textContent = t("vnc.disconnected"); });
        rfb.addEventListener("credentialsrequired", () => rfb.sendCredentials({ password: info.password }));
        rfb.addEventListener("securityfailure", () => { if (stat.isConnected) stat.textContent = t("vnc.failed", { msg: "security" }); });
      } catch (e) {
        if (stat.isConnected) stat.textContent = t("vnc.failed", { msg: e.message });
      }
    });
}
