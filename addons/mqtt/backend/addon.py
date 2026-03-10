from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from app.addons.models import AddonMeta, BackendAddon

router = APIRouter()
_config: dict[str, Any] = {}


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@router.get("", response_class=HTMLResponse)
def addon_ui_root() -> str:
    return """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Synthia MQTT Setup</title>
  <style>
    :root {
      color-scheme: light dark;
      --bg: #0f172a;
      --card: #111827;
      --border: #334155;
      --text: #e5e7eb;
      --muted: #94a3b8;
      --accent: #0ea5e9;
      --danger: #ef4444;
      --ok: #22c55e;
    }
    body {
      margin: 0;
      font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
      background: var(--bg);
      color: var(--text);
    }
    .page {
      max-width: 980px;
      margin: 0 auto;
      padding: 20px;
    }
    .title {
      margin: 0 0 8px 0;
      font-size: 24px;
    }
    .sub {
      margin: 0 0 16px 0;
      color: var(--muted);
    }
    .card {
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 16px;
      margin-bottom: 14px;
    }
    .grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 12px;
    }
    label {
      display: flex;
      flex-direction: column;
      gap: 6px;
      font-size: 13px;
      color: var(--muted);
    }
    input, select {
      border: 1px solid var(--border);
      border-radius: 8px;
      background: #0b1220;
      color: var(--text);
      padding: 10px 12px;
      font-size: 14px;
    }
    .row {
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      margin-top: 14px;
    }
    button {
      border: 1px solid var(--border);
      border-radius: 8px;
      background: #0b1220;
      color: var(--text);
      padding: 10px 12px;
      cursor: pointer;
    }
    button.primary {
      border-color: #0369a1;
      background: #0c4a6e;
    }
    button:disabled {
      opacity: 0.5;
      cursor: not-allowed;
    }
    .status {
      font-size: 13px;
      color: var(--muted);
      margin-top: 8px;
    }
    .status.error {
      color: var(--danger);
    }
    .status.ok {
      color: var(--ok);
    }
    .mono {
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
      font-size: 12px;
      white-space: pre-wrap;
    }
  </style>
</head>
<body>
  <main class="page">
    <h1 class="title">Synthia MQTT Setup</h1>
    <p class="sub">Configure broker mode and connection settings for the embedded MQTT runtime.</p>

    <section class="card">
      <h2>Current Runtime Status</h2>
      <div id="runtime-status" class="status">Loading...</div>
      <div id="runtime-debug" class="mono"></div>
    </section>

    <section class="card">
      <h2>MQTT Setup</h2>
      <div class="grid">
        <label>
          Mode
          <select id="mode">
            <option value="local">Local broker</option>
            <option value="external">External broker</option>
          </select>
        </label>
        <label>
          Host
          <input id="host" placeholder="127.0.0.1" />
        </label>
        <label>
          Port
          <input id="port" placeholder="1883" />
        </label>
        <label>
          Username (optional)
          <input id="username" />
        </label>
        <label>
          Password (optional)
          <input id="password" type="password" />
        </label>
        <label>
          TLS enabled
          <select id="tls">
            <option value="false">Disabled</option>
            <option value="true">Enabled</option>
          </select>
        </label>
        <label>
          Keepalive (seconds)
          <input id="keepalive" placeholder="30" />
        </label>
        <label>
          Client ID
          <input id="client_id" placeholder="synthia-core" />
        </label>
      </div>
      <div class="row">
        <button id="apply" class="primary">Apply MQTT settings</button>
        <button id="apply-restart">Apply and restart MQTT</button>
        <button id="refresh">Refresh status</button>
      </div>
      <div id="action-status" class="status"></div>
    </section>
  </main>

  <script>
    const mode = document.getElementById("mode");
    const host = document.getElementById("host");
    const port = document.getElementById("port");
    const username = document.getElementById("username");
    const password = document.getElementById("password");
    const tls = document.getElementById("tls");
    const keepalive = document.getElementById("keepalive");
    const clientId = document.getElementById("client_id");
    const applyBtn = document.getElementById("apply");
    const applyRestartBtn = document.getElementById("apply-restart");
    const refreshBtn = document.getElementById("refresh");
    const actionStatus = document.getElementById("action-status");
    const runtimeStatus = document.getElementById("runtime-status");
    const runtimeDebug = document.getElementById("runtime-debug");

    function setStatus(message, kind) {
      actionStatus.textContent = message || "";
      actionStatus.className = kind ? `status ${kind}` : "status";
    }

    function setBusy(busy) {
      applyBtn.disabled = busy;
      applyRestartBtn.disabled = busy;
      refreshBtn.disabled = busy;
    }

    async function loadSettings() {
      const res = await fetch("/api/system/settings", { credentials: "include" });
      if (!res.ok) throw new Error(`settings_http_${res.status}`);
      const payload = await res.json();
      if (!payload.ok || !payload.settings) throw new Error(payload.error || "settings_unavailable");
      const settings = payload.settings;
      const selectedMode = String(settings["mqtt.mode"] || "local").toLowerCase() === "external" ? "external" : "local";
      mode.value = selectedMode;
      host.value = String(settings[`mqtt.${selectedMode}.host`] || (selectedMode === "local" ? "127.0.0.1" : ""));
      port.value = String(settings[`mqtt.${selectedMode}.port`] ?? 1883);
      username.value = String(settings[`mqtt.${selectedMode}.username`] || "");
      password.value = String(settings[`mqtt.${selectedMode}.password`] || "");
      tls.value = Boolean(settings[`mqtt.${selectedMode}.tls_enabled`]) ? "true" : "false";
      keepalive.value = String(settings["mqtt.keepalive_s"] ?? 30);
      clientId.value = String(settings["mqtt.client_id"] || "synthia-core");
    }

    async function loadStatus() {
      const [statusRes, setupRes] = await Promise.all([
        fetch("/api/system/mqtt/status", { cache: "no-store", credentials: "include" }),
        fetch("/api/system/mqtt/setup-summary", { cache: "no-store", credentials: "include" }),
      ]);
      if (!statusRes.ok) throw new Error(`mqtt_status_http_${statusRes.status}`);
      if (!setupRes.ok) throw new Error(`mqtt_setup_http_${setupRes.status}`);
      const statusPayload = await statusRes.json();
      const setupPayload = await setupRes.json();
      const connected = statusPayload.connected ? "connected" : "disconnected";
      const modeText = statusPayload.mode || "unknown";
      const endpoint = statusPayload.host ? `${statusPayload.host}:${statusPayload.port ?? "-"}` : "not configured";
      const setupState = setupPayload?.setup?.setup_status || "unknown";
      runtimeStatus.textContent = `MQTT ${connected} • mode ${modeText} • endpoint ${endpoint} • setup ${setupState}`;
      runtimeDebug.textContent = JSON.stringify(setupPayload, null, 2);
    }

    async function putSetting(key, value) {
      const res = await fetch(`/api/system/settings/${encodeURIComponent(key)}`, {
        method: "PUT",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ value }),
      });
      if (!res.ok) throw new Error(`settings_put_http_${res.status}`);
    }

    async function applySettings(restartAfter) {
      setBusy(true);
      setStatus("Applying settings...", "");
      try {
        const selectedMode = mode.value === "external" ? "external" : "local";
        const parsedPort = Number.parseInt(String(port.value || "").trim(), 10);
        const parsedKeepalive = Number.parseInt(String(keepalive.value || "").trim(), 10);
        if (!Number.isFinite(parsedPort) || parsedPort <= 0 || parsedPort > 65535) {
          throw new Error("invalid_port");
        }
        if (!Number.isFinite(parsedKeepalive) || parsedKeepalive <= 0) {
          throw new Error("invalid_keepalive");
        }

        await putSetting("mqtt.mode", selectedMode);
        await putSetting(`mqtt.${selectedMode}.host`, String(host.value || "").trim());
        await putSetting(`mqtt.${selectedMode}.port`, parsedPort);
        await putSetting(`mqtt.${selectedMode}.username`, String(username.value || "").trim());
        await putSetting(`mqtt.${selectedMode}.password`, String(password.value || ""));
        await putSetting(`mqtt.${selectedMode}.tls_enabled`, tls.value === "true");
        await putSetting("mqtt.keepalive_s", parsedKeepalive);
        await putSetting("mqtt.client_id", String(clientId.value || "").trim() || "synthia-core");

        if (restartAfter) {
          const restartRes = await fetch("/api/system/mqtt/restart", { method: "POST", credentials: "include" });
          if (!restartRes.ok) throw new Error(`mqtt_restart_http_${restartRes.status}`);
        }

        await loadStatus();
        await loadSettings();
        setStatus(restartAfter ? "Settings applied and MQTT restarted." : "Settings applied.", "ok");
      } catch (error) {
        setStatus(`Apply failed: ${error?.message || String(error)}`, "error");
      } finally {
        setBusy(false);
      }
    }

    mode.addEventListener("change", async () => {
      try {
        await loadSettings();
      } catch {
        // ignore; main status handles failures
      }
    });
    applyBtn.addEventListener("click", () => void applySettings(false));
    applyRestartBtn.addEventListener("click", () => void applySettings(true));
    refreshBtn.addEventListener("click", async () => {
      setStatus("", "");
      try {
        await loadStatus();
      } catch (error) {
        setStatus(`Refresh failed: ${error?.message || String(error)}`, "error");
      }
    });

    (async () => {
      setBusy(true);
      try {
        await Promise.all([loadSettings(), loadStatus()]);
        setStatus("Ready.", "ok");
      } catch (error) {
        setStatus(`Load failed: ${error?.message || String(error)}`, "error");
      } finally {
        setBusy(false);
      }
    })();
  </script>
</body>
</html>
"""


@router.get("/api/addon/meta")
def addon_meta() -> dict[str, Any]:
    return {
        "id": "mqtt",
        "name": "Synthia MQTT",
        "version": "0.1.0",
        "description": "Platform-managed embedded MQTT infrastructure addon",
    }


@router.get("/api/addon/health")
def addon_health() -> dict[str, Any]:
    return {
        "status": "ok",
        "mode": "embedded_platform",
        "platform_managed": True,
        "checked_at": _utcnow_iso(),
    }


@router.get("/api/addon/capabilities")
def addon_capabilities() -> dict[str, Any]:
    return {
        "capabilities": [
            "mqtt.broker_runtime",
            "mqtt.authority",
            "mqtt.bootstrap",
        ],
        "platform_managed": True,
    }


@router.get("/api/addon/config/effective")
def addon_effective_config() -> dict[str, Any]:
    return {
        "platform_managed": True,
        "config": dict(_config),
    }


@router.post("/api/addon/config")
def addon_config_update(body: dict[str, Any]) -> dict[str, Any]:
    if isinstance(body, dict):
        _config.update(body)
    return {
        "ok": True,
        "platform_managed": True,
        "updated_at": _utcnow_iso(),
        "config": dict(_config),
    }


addon = BackendAddon(
    meta=AddonMeta(
        id="mqtt",
        name="Synthia MQTT",
        version="0.1.0",
        description="Platform-managed embedded MQTT infrastructure addon.",
        show_sidebar=False,
        platform_managed=True,
        capabilities=["mqtt.broker_runtime", "mqtt.authority", "mqtt.bootstrap"],
    ),
    router=router,
)
