(() => {
  "use strict";

  const REFRESH_MS = 5000;
  const tokenInput = document.querySelector("#api-token");
  const notice = document.querySelector("#notice");
  const statusText = document.querySelector("#service-status");
  const statusDetail = document.querySelector("#service-detail");

  tokenInput.value = sessionStorage.getItem("duqu_api_token") || "";
  tokenInput.addEventListener("change", () => {
    sessionStorage.setItem("duqu_api_token", tokenInput.value.trim());
    refresh();
  });
  document.querySelector("#refresh-button").addEventListener("click", refresh);

  const escapeHtml = (value) => String(value ?? "")
    .replaceAll("&", "&amp;").replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;").replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");

  const apiHeaders = () => {
    const token = tokenInput.value.trim();
    return token ? { Authorization: `Bearer ${token}` } : {};
  };

  async function getJson(path) {
    const response = await fetch(path, { headers: apiHeaders(), cache: "no-store" });
    if (!response.ok) throw new Error(response.status === 401 ? "API 需要有效的 Token" : `API 请求失败 (${response.status})`);
    return response.json();
  }

  function formatUptime(seconds) {
    const value = Math.max(0, Math.floor(Number(seconds) || 0));
    const days = Math.floor(value / 86400);
    const hours = Math.floor((value % 86400) / 3600);
    const minutes = Math.floor((value % 3600) / 60);
    return days ? `${days} 天 ${hours} 小时` : `${hours} 小时 ${minutes} 分钟`;
  }

  function formatTime(timestamp) {
    if (!timestamp) return "—";
    const date = new Date(Number(timestamp) * 1000);
    return Number.isNaN(date.getTime()) ? "—" : date.toLocaleString();
  }

  function statusClass(status) {
    const normalized = String(status || "unknown").toLowerCase();
    const allowed = new Set(["online", "collecting", "error", "offline", "disabled"]);
    return `status-pill status-${allowed.has(normalized) ? normalized : "unknown"}`;
  }

  function renderDevices(devices) {
    const table = document.querySelector("#device-table");
    if (!devices.length) {
      table.innerHTML = '<tr><td colspan="6" class="empty">暂无设备状态</td></tr>';
      return;
    }
    table.innerHTML = devices.map((device) => {
      const name = device.name ? `${escapeHtml(device.name)} <span class="muted">(${escapeHtml(device.device_id)})</span>` : escapeHtml(device.device_id);
      const runtime = escapeHtml(device.runtime_status || "unknown");
      const mqtt = escapeHtml(device.mqtt_state || "unknown");
      return `<tr><td>${name}</td><td><span class="${statusClass(runtime)}">${runtime}</span></td>` +
        `<td>${mqtt}</td><td>${Number(device.comm_success_rate || 0).toFixed(1)}%</td>` +
        `<td>${Number(device.upload_success_rate || 0).toFixed(1)}%</td>` +
        `<td>${formatTime(device.last_comm_time)}</td></tr>`;
    }).join("");
  }

  function renderCache(cache) {
    const list = document.querySelector("#cache-list");
    const entries = Object.entries(cache || {});
    if (!entries.length) { list.innerHTML = '<p class="empty">暂无缓存记录</p>'; return; }
    list.innerHTML = entries.map(([device, item]) => `<div class="cache-item">` +
      `<span class="cache-device">${escapeHtml(device)}</span><span class="cache-stats">` +
      `<span>待补传 <strong>${Number(item.pending || 0)}</strong></span>` +
      `<span>死信 <strong>${Number(item.dead_letter || 0)}</strong></span></span></div>`).join("");
  }

  function render(payload) {
    statusText.textContent = payload.status === "ready" ? "运行正常" : "在线";
    statusDetail.textContent = `运行 ${formatUptime(payload.uptime_seconds)}`;
    document.querySelector("#device-count").textContent = payload.devices ?? "—";
    document.querySelector("#pending-count").textContent = payload.cache_pending ?? "—";
    document.querySelector("#dead-letter-count").textContent = payload.cache_dead_letter ?? "—";
    document.querySelector("#last-updated").textContent = `更新于 ${new Date().toLocaleTimeString()}`;
    renderDevices(payload.device_status || []);
    renderCache(payload.cache_status || {});
  }

  async function refresh() {
    notice.textContent = "";
    try {
      render(await getJson("/api/v1/status"));
    } catch (error) {
      statusText.textContent = "无法读取";
      statusDetail.textContent = "请检查网关和 Token";
      notice.textContent = error.message;
    }
  }

  refresh();
  window.setInterval(refresh, REFRESH_MS);
})();
