from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Request
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
      max-width: 90%;
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
    .status-banner {
      border: 1px solid #92400e;
      background: #451a03;
      color: #fde68a;
      border-radius: 10px;
      padding: 10px 12px;
      margin-bottom: 12px;
      display: none;
    }
    .status-banner.visible {
      display: block;
    }
    .tabs {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-bottom: 12px;
    }
    .tab {
      border: 1px solid var(--border);
      border-radius: 999px;
      background: #0b1220;
      color: var(--text);
      padding: 6px 12px;
      font-size: 13px;
    }
    .tab.active {
      border-color: var(--accent);
      background: #082f49;
    }
    .tab.locked {
      opacity: 0.45;
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
    .checks {
      display: grid;
      gap: 6px;
      margin-top: 8px;
    }
    .check {
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 8px 10px;
      font-size: 13px;
      display: flex;
      justify-content: space-between;
      gap: 8px;
    }
    .check.ready {
      border-color: #166534;
      color: #86efac;
    }
    .check.warning {
      border-color: #92400e;
      color: #fde68a;
    }
    .check.failed {
      border-color: #991b1b;
      color: #fecaca;
    }
    .section-body {
      margin-top: 8px;
    }
    .mode-local-only,
    .mode-external-only {
      display: none;
    }
    .mode-local .mode-local-only {
      display: flex;
    }
    .mode-external .mode-external-only {
      display: flex;
    }
    .list {
      margin: 0;
      padding-left: 18px;
      color: var(--muted);
      font-size: 13px;
      line-height: 1.5;
    }
    .table {
      width: 100%;
      border-collapse: collapse;
      margin-top: 8px;
      font-size: 13px;
    }
    .table th,
    .table td {
      border-bottom: 1px solid var(--border);
      text-align: left;
      padding: 8px 6px;
      vertical-align: top;
    }
    .mono {
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
      font-size: 12px;
      white-space: pre-wrap;
    }
    .runtime-actions {
      margin-bottom: 10px;
    }
    .pill {
      display: inline-block;
      border: 1px solid var(--border);
      border-radius: 999px;
      padding: 3px 10px;
      font-size: 12px;
      margin-right: 6px;
      margin-bottom: 6px;
    }
    .pill.ok { border-color: #166534; color: #86efac; }
    .pill.muted { border-color: #475569; color: #cbd5e1; }
    .pill.warn { border-color: #92400e; color: #fde68a; }
    .pill.bad { border-color: #991b1b; color: #fecaca; }
    .led {
      width: 10px;
      height: 10px;
      border-radius: 999px;
      display: inline-block;
      border: 1px solid #334155;
      background: #475569;
    }
    .led.ok {
      background: #22c55e;
      border-color: #166534;
      box-shadow: 0 0 0 2px rgba(34, 197, 94, 0.16);
    }
    .led.muted {
      background: #94a3b8;
      border-color: #475569;
    }
    .led.bad {
      background: #ef4444;
      border-color: #991b1b;
      box-shadow: 0 0 0 2px rgba(239, 68, 68, 0.16);
    }
    .led-cell {
      width: 28px;
      text-align: center;
    }
    .stats {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
      gap: 8px;
      margin: 10px 0;
    }
    .stat {
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 8px 10px;
      background: #0b1220;
    }
    .stat .k {
      display: block;
      font-size: 11px;
      color: var(--muted);
    }
    .stat .v {
      display: block;
      font-size: 18px;
      font-weight: 600;
    }
    .toolbar {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin: 8px 0;
      align-items: center;
    }
    .toolbar input,
    .toolbar select {
      min-width: 180px;
      max-width: 260px;
    }
    .empty {
      border: 1px dashed var(--border);
      border-radius: 10px;
      padding: 10px;
      color: var(--muted);
      font-size: 13px;
    }
    .badge {
      display: inline-block;
      border: 1px solid var(--border);
      border-radius: 999px;
      padding: 2px 8px;
      font-size: 11px;
      margin-left: 6px;
    }
    .badge.core {
      border-color: #0369a1;
      color: #7dd3fc;
      background: #082f49;
    }
    .group-title {
      margin: 12px 0 6px;
      font-size: 13px;
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }
    .tree {
      margin: 8px 0;
      padding-left: 18px;
    }
    .tree li {
      margin: 4px 0;
    }
    .tree summary {
      cursor: pointer;
    }
    .row-actions {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
    }
    .mini {
      padding: 4px 8px;
      font-size: 11px;
      border-radius: 6px;
    }
    .toolbar-spacer {
      flex: 1 1 auto;
    }
    .modal-backdrop {
      position: fixed;
      inset: 0;
      background: rgba(2, 6, 23, 0.75);
      display: flex;
      align-items: center;
      justify-content: center;
      z-index: 50;
      padding: 16px;
    }
    .modal-backdrop.hidden {
      display: none;
    }
    .modal {
      width: min(520px, 100%);
      border: 1px solid var(--border);
      border-radius: 12px;
      background: var(--card);
      padding: 14px;
    }
    .modal h3 {
      margin: 0 0 10px;
      font-size: 16px;
    }
    .modal-grid {
      display: grid;
      gap: 10px;
      grid-template-columns: 1fr;
    }
    .modal-actions {
      display: flex;
      gap: 8px;
      margin-top: 12px;
    }
  </style>
</head>
<body>
  <main class="page">
    <h1 class="title">Synthia MQTT Setup</h1>
    <p class="sub">Configure broker mode and connection settings for the embedded MQTT runtime.</p>
    <div id="setup-banner" class="status-banner"></div>

    <section class="card">
      <div class="tabs" id="tabs">
        <button class="tab" data-section="setup">Setup</button>
        <button class="tab" data-section="overview">Overview</button>
        <button class="tab" data-section="principals">Principals</button>
        <button class="tab" data-section="users">Generic Users</button>
        <button class="tab" data-section="runtime">Runtime</button>
        <button class="tab" data-section="topics">Topics</button>
        <button class="tab" data-section="audit">Audit</button>
        <button class="tab" data-section="noisy-clients">Noisy Clients</button>
      </div>
      <h2 id="section-title">Current Runtime Status</h2>
      <div id="runtime-status" class="status">Loading...</div>
      <div id="section-content" class="section-body"></div>
    </section>

    <section class="card" id="setup-card">
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
        <label class="mode-local-only">
          Runtime note
          <input value="Synthia will supervise local broker runtime." readonly />
        </label>
        <label class="mode-external-only">
          External note
          <input value="Synthia will connect to an existing broker." readonly />
        </label>
        <label>
          Port
          <input id="port" placeholder="1883" />
        </label>
        <label class="mode-external-only">
          Username (optional)
          <input id="username" />
        </label>
        <label class="mode-external-only">
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
      <div class="card" style="margin-top:12px;">
        <div class="settings-card-title">Preflight</div>
        <div id="preflight" class="checks"></div>
      </div>
      <div class="card" style="margin-top:12px;">
        <div class="settings-card-title">Reserved Topics and Bootstrap</div>
        <ul class="list">
          <li><code>synthia/#</code> is reserved for Synthia-managed traffic.</li>
          <li>Anonymous access is limited to bootstrap discovery flows only.</li>
          <li>Users, policies, and grants are configured after initial setup.</li>
        </ul>
      </div>
      <div class="row">
        <button id="apply" class="primary">Save and Initialize</button>
        <button id="apply-restart">Save + Restart MQTT</button>
        <button id="test-connection">Test Connection</button>
        <button id="refresh">Refresh status</button>
        <button id="retry" disabled>Retry Last Action</button>
        <button id="recheck">Re-check</button>
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
    const testConnectionBtn = document.getElementById("test-connection");
    const refreshBtn = document.getElementById("refresh");
    const retryBtn = document.getElementById("retry");
    const recheckBtn = document.getElementById("recheck");
    const setupBanner = document.getElementById("setup-banner");
    const tabs = document.getElementById("tabs");
    const sectionTitle = document.getElementById("section-title");
    const sectionContent = document.getElementById("section-content");
    const setupCard = document.getElementById("setup-card");
    const preflight = document.getElementById("preflight");
    const actionStatus = document.getElementById("action-status");
    const runtimeStatus = document.getElementById("runtime-status");
    const sections = ["setup", "overview", "principals", "users", "runtime", "topics", "audit", "noisy-clients"];
    const state = {
      currentSection: "overview",
      gateActive: false,
      setupSummary: null,
      statusPayload: null,
      lastAction: null,
      lastExternalTest: null,
      runtimeActionStatus: "",
      runtimeActionKind: "",
      debugSubscriptionId: null,
      debugPollHandle: null,
      autoRefreshHandle: null,
      autoRefreshInFlight: false,
      debugMessages: [],
      sectionCache: {},
      filters: {
        principals: { q: "", type: "", status: "" },
        users: { q: "", status: "" },
        topics: { q: "" },
        audit: { q: "", status: "", principal: "", action: "" },
        noisyClients: { q: "", state: "" },
      },
    };
    const AUTO_REFRESH_MS = 5000;

    function sectionFromPath() {
      const marker = "/api/addons/mqtt";
      const path = window.location.pathname || "";
      if (!path.startsWith(marker)) return "overview";
      const tail = path.slice(marker.length).replace(/^\\/+/, "");
      const first = tail.split("/", 1)[0].trim();
      return sections.includes(first) ? first : "overview";
    }

    function navigateTo(section, replace) {
      const normalized = sections.includes(section) ? section : "overview";
      const nextPath = normalized === "overview" ? "/api/addons/mqtt" : `/api/addons/mqtt/${normalized}`;
      const method = replace ? "replaceState" : "pushState";
      window.history[method]({}, "", nextPath);
      state.currentSection = normalized;
      renderRoute();
    }

    function setStatus(message, kind) {
      actionStatus.textContent = message || "";
      actionStatus.className = kind ? `status ${kind}` : "status";
    }

    function setBusy(busy) {
      applyBtn.disabled = busy;
      applyRestartBtn.disabled = busy;
      testConnectionBtn.disabled = busy;
      refreshBtn.disabled = busy;
      retryBtn.disabled = busy || !state.lastAction;
      recheckBtn.disabled = busy;
    }

    function escapeHtml(value) {
      return String(value || "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;");
    }

    function formatLocalTimestamp(value) {
      const raw = String(value || "").trim();
      if (!raw || raw === "-") return "-";
      const parsed = Date.parse(raw);
      if (!Number.isFinite(parsed)) return raw;
      return new Date(parsed).toLocaleString();
    }

    function formatMsgRate(value) {
      const num = Number(value);
      if (!Number.isFinite(num)) return "-";
      return `${num.toFixed(3)} msg/sec`;
    }

    function gateIsActive(summary) {
      const setup = summary && summary.setup ? summary.setup : {};
      return Boolean(setup.requires_setup) && !Boolean(setup.setup_complete);
    }

    function modeValue() {
      return mode.value === "external" ? "external" : "local";
    }

    function applyModeClass() {
      const selected = modeValue();
      const root = setupCard;
      root.classList.remove("mode-local", "mode-external");
      root.classList.add(selected === "external" ? "mode-external" : "mode-local");
      const external = selected === "external";
      username.disabled = !external;
      password.disabled = !external;
    }

    function buildPreflightChecks() {
      const checks = [];
      const hostValue = String(host.value || "").trim();
      const portValue = Number.parseInt(String(port.value || "").trim(), 10);
      const keepaliveValue = Number.parseInt(String(keepalive.value || "").trim(), 10);
      checks.push({
        label: "Host",
        status: hostValue ? "ready" : "failed",
        detail: hostValue ? hostValue : "Host is required",
      });
      checks.push({
        label: "Port",
        status: Number.isFinite(portValue) && portValue > 0 && portValue <= 65535 ? "ready" : "failed",
        detail: Number.isFinite(portValue) && portValue > 0 && portValue <= 65535 ? String(portValue) : "Expected 1-65535",
      });
      checks.push({
        label: "Keepalive",
        status: Number.isFinite(keepaliveValue) && keepaliveValue > 0 ? "ready" : "failed",
        detail: Number.isFinite(keepaliveValue) && keepaliveValue > 0 ? `${keepaliveValue}s` : "Must be a positive integer",
      });
      if (modeValue() === "external") {
        if (!state.lastExternalTest) {
          checks.push({ label: "Connection test", status: "warning", detail: "Run Test Connection" });
        } else if (state.lastExternalTest.ok) {
          checks.push({ label: "Connection test", status: "ready", detail: state.lastExternalTest.detail });
        } else {
          checks.push({ label: "Connection test", status: "failed", detail: state.lastExternalTest.detail });
        }
      } else {
        checks.push({ label: "Local runtime", status: "ready", detail: "Broker managed by Synthia runtime." });
      }
      return checks;
    }

    function renderPreflight() {
      const checks = buildPreflightChecks();
      preflight.innerHTML = checks
        .map((item) => {
          return `<div class="check ${item.status}"><strong>${escapeHtml(item.label)}</strong><span>${escapeHtml(item.detail)}</span></div>`;
        })
        .join("");
      return checks;
    }

    async function fetchJson(url, options) {
      const res = await fetch(url, Object.assign({ credentials: "include", cache: "no-store" }, options || {}));
      if (!res.ok) throw new Error(`${url}_http_${res.status}`);
      return res.json();
    }

    async function createUserFromModal() {
      const usernameNode = document.getElementById("create-user-username");
      const passwordNode = document.getElementById("create-user-password");
      const prefixNode = document.getElementById("create-user-prefix");
      const modeNode = document.getElementById("create-user-access-mode");
      const topicsNode = document.getElementById("create-user-allowed-topics");
      const publishTopicsNode = document.getElementById("create-user-allowed-publish-topics");
      const subscribeTopicsNode = document.getElementById("create-user-allowed-subscribe-topics");
      const statusNode = document.getElementById("create-user-status");
      if (!usernameNode || !passwordNode || !prefixNode || !modeNode || !topicsNode || !publishTopicsNode || !subscribeTopicsNode || !statusNode) return;
      const usernameValue = String(usernameNode.value || "").trim();
      const prefixValue = String(prefixNode.value || "").trim();
      const passwordValue = String(passwordNode.value || "").trim() || "generated";
      const accessMode = String(modeNode.value || "private").trim();
      const allowedTopics = String(topicsNode.value || "")
        .split(",")
        .map((item) => String(item || "").trim())
        .filter((item) => item.length > 0);
      const allowedPublishTopics = String(publishTopicsNode.value || "")
        .split(",")
        .map((item) => String(item || "").trim())
        .filter((item) => item.length > 0);
      const allowedSubscribeTopics = String(subscribeTopicsNode.value || "")
        .split(",")
        .map((item) => String(item || "").trim())
        .filter((item) => item.length > 0);
      statusNode.textContent = "Creating user...";
      statusNode.className = "status";
      try {
        const response = await fetch("/api/system/mqtt/users", {
          method: "POST",
          credentials: "include",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            username: usernameValue,
            password: passwordValue,
            topic_prefix: prefixValue,
            access_mode: accessMode,
            allowed_topics: allowedTopics,
            allowed_publish_topics: allowedPublishTopics,
            allowed_subscribe_topics: allowedSubscribeTopics,
          }),
        });
        const payload = await response.json();
        if (!response.ok || !payload.ok) {
          throw new Error(payload && payload.detail ? payload.detail : "create_user_failed");
        }
        const passwordOut = payload.password ? ` Password: ${payload.password}` : "";
        statusNode.textContent = `Created ${payload.username}.${passwordOut}`;
        statusNode.className = "status ok";
        await loadStatus();
      } catch (error) {
        statusNode.textContent = `Create failed: ${error && error.message ? error.message : String(error)}`;
        statusNode.className = "status error";
      }
    }

    async function exportGenericUsers() {
      setStatus("Exporting generic users...", "");
      try {
        const res = await fetch("/api/system/mqtt/users/export", { credentials: "include", cache: "no-store" });
        const payload = await res.json();
        if (!res.ok || !payload.ok) {
          throw new Error(payload && payload.detail ? payload.detail : "users_export_failed");
        }
        const items = Array.isArray(payload.items) ? payload.items : [];
        window.prompt("Copy users JSON", JSON.stringify(items, null, 2));
        setStatus(`Exported ${items.length} users.`, "ok");
      } catch (error) {
        setStatus(`Export failed: ${error && error.message ? error.message : String(error)}`, "error");
      }
    }

    async function importGenericUsers() {
      const raw = window.prompt("Paste users JSON array", "[]");
      if (!raw) return;
      let parsed = [];
      try {
        const decoded = JSON.parse(String(raw));
        if (!Array.isArray(decoded)) throw new Error("json_array_required");
        parsed = decoded;
      } catch (error) {
        setStatus(`Import failed: ${error && error.message ? error.message : "json_invalid"}`, "error");
        return;
      }
      setStatus("Importing generic users...", "");
      try {
        const res = await fetch("/api/system/mqtt/users/import", {
          method: "POST",
          credentials: "include",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ items: parsed }),
        });
        const payload = await res.json();
        if (!res.ok || !payload.ok) {
          throw new Error(payload && payload.detail ? payload.detail : "users_import_failed");
        }
        await loadStatus();
        setStatus(`Imported ${Number(payload.imported || 0)} users.`, "ok");
      } catch (error) {
        setStatus(`Import failed: ${error && error.message ? error.message : String(error)}`, "error");
      }
    }

    async function runGenericUserAction(action, principalId, topicPrefix, accessMode, allowedTopics, allowedPublishTopics, allowedSubscribeTopics) {
      const id = String(principalId || "").trim();
      if (!id) return;
      const normalized = String(action || "").trim().toLowerCase();
      let method = "POST";
      let url = "";
      let body = null;
      if (normalized === "revoke") {
        if (!window.confirm(`Revoke ${id}?`)) return;
        url = `/api/system/mqtt/generic-users/${encodeURIComponent(id)}/revoke`;
        body = { reason: "ui_revoke" };
      } else if (normalized === "disable") {
        if (!window.confirm(`Disable ${id}?`)) return;
        url = `/api/system/mqtt/principals/${encodeURIComponent(id)}/actions/probation`;
        body = { reason: "ui_disable" };
      } else if (normalized === "rotate") {
        url = `/api/system/mqtt/generic-users/${encodeURIComponent(id)}/rotate-credentials`;
      } else if (normalized === "edit") {
        const nextPrefix = window.prompt("Topic prefix", String(topicPrefix || ""));
        const nextMode = window.prompt("Access mode (private/custom/non_reserved/admin)", String(accessMode || "private"));
        if (!nextPrefix || !nextMode) return;
        let nextAllowed = [];
        let nextAllowedPublish = [];
        let nextAllowedSubscribe = [];
        if (String(nextMode).toLowerCase() === "custom") {
          const base = Array.isArray(allowedTopics) ? allowedTopics.join(",") : String(allowedTopics || "");
          const raw = window.prompt("Allowed topics (comma separated)", base);
          nextAllowed = String(raw || "")
            .split(",")
            .map((item) => String(item || "").trim())
            .filter((item) => item.length > 0);
          const publishBase = Array.isArray(allowedPublishTopics) ? allowedPublishTopics.join(",") : base;
          const rawPublish = window.prompt("Allowed publish topics (comma separated)", publishBase);
          nextAllowedPublish = String(rawPublish || "")
            .split(",")
            .map((item) => String(item || "").trim())
            .filter((item) => item.length > 0);
          const subscribeBase = Array.isArray(allowedSubscribeTopics) ? allowedSubscribeTopics.join(",") : base;
          const rawSubscribe = window.prompt("Allowed subscribe topics (comma separated)", subscribeBase);
          nextAllowedSubscribe = String(rawSubscribe || "")
            .split(",")
            .map((item) => String(item || "").trim())
            .filter((item) => item.length > 0);
        }
        url = `/api/system/mqtt/users/${encodeURIComponent(id)}`;
        method = "PATCH";
        body = {
          topic_prefix: nextPrefix,
          access_mode: nextMode,
          allowed_topics: nextAllowed,
          allowed_publish_topics: nextAllowedPublish,
          allowed_subscribe_topics: nextAllowedSubscribe,
        };
      } else if (normalized === "delete") {
        if (!window.confirm(`Delete ${id}?`)) return;
        url = `/api/system/mqtt/users/${encodeURIComponent(id)}`;
        method = "DELETE";
      } else {
        return;
      }
      setStatus(`Running ${normalized} for ${id}...`, "");
      try {
        const response = await fetch(url, {
          method,
          credentials: "include",
          headers: body ? { "Content-Type": "application/json" } : undefined,
          body: body ? JSON.stringify(body) : undefined,
        });
        const payload = await response.json();
        if (!response.ok || (payload && payload.ok === false)) {
          throw new Error(payload && payload.detail ? payload.detail : `${normalized}_failed`);
        }
        await loadStatus();
        setStatus(`${normalized} completed for ${id}.`, "ok");
      } catch (error) {
        setStatus(`${normalized} failed for ${id}: ${error && error.message ? error.message : String(error)}`, "error");
      }
    }

    async function runPrincipalAction(action, principalId) {
      const id = String(principalId || "").trim();
      const act = String(action || "").trim().toLowerCase();
      if (!id || !act) return;
      if (act === "revoke" && !window.confirm(`Revoke ${id}?`)) return;
      const reason = act === "probation" ? "ui_probation" : act === "revoke" ? "ui_revoke" : "ui_action";
      setStatus(`Running ${act} for ${id}...`, "");
      try {
        const response = await fetch(`/api/system/mqtt/principals/${encodeURIComponent(id)}/actions/${encodeURIComponent(act)}`, {
          method: "POST",
          credentials: "include",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ reason }),
        });
        const payload = await response.json();
        if (!response.ok || (payload && payload.ok === false)) {
          throw new Error(payload && payload.detail ? payload.detail : `${act}_failed`);
        }
        await loadStatus();
        setStatus(`${act} completed for ${id}.`, "ok");
      } catch (error) {
        setStatus(`${act} failed for ${id}: ${error && error.message ? error.message : String(error)}`, "error");
      }
    }

    async function runPrincipalInfoAction(action, principalId) {
      const id = String(principalId || "").trim();
      const act = String(action || "").trim().toLowerCase();
      if (!id || !act) return;
      let url = "";
      let label = "";
      if (act === "details") {
        url = `/api/system/mqtt/principals/${encodeURIComponent(id)}`;
        label = "principal";
      } else if (act === "permissions") {
        url = `/api/system/mqtt/principals/${encodeURIComponent(id)}/permissions`;
        label = "permissions";
      } else if (act === "last-seen") {
        url = `/api/system/mqtt/principals/${encodeURIComponent(id)}/last-seen`;
        label = "last_seen";
      } else {
        return;
      }
      setStatus(`Loading ${act} for ${id}...`, "");
      try {
        const response = await fetch(url, { credentials: "include" });
        const payload = await response.json();
        if (!response.ok || (payload && payload.ok === false)) {
          throw new Error(payload && payload.detail ? payload.detail : `${act}_failed`);
        }
        window.alert(JSON.stringify(payload[label] || payload, null, 2));
        setStatus(`${act} loaded for ${id}.`, "ok");
      } catch (error) {
        setStatus(`${act} failed for ${id}: ${error && error.message ? error.message : String(error)}`, "error");
      }
    }

    function setRuntimeActionStatus(message, kind) {
      state.runtimeActionStatus = message || "";
      state.runtimeActionKind = kind || "";
      const node = document.getElementById("runtime-action-status");
      if (!node) return;
      node.textContent = state.runtimeActionStatus;
      node.className = state.runtimeActionKind ? `status ${state.runtimeActionKind}` : "status";
    }

    function setRuntimeBusy(busy) {
      const nodes = sectionContent.querySelectorAll("[data-runtime-action]");
      nodes.forEach((node) => {
        node.disabled = busy;
      });
    }

    function runtimeActionEndpoint(action) {
      const normalized = String(action || "").trim().toLowerCase();
      if (normalized === "health") return { method: "GET", url: "/api/system/mqtt/runtime/health" };
      if (normalized === "init") return { method: "POST", url: "/api/system/mqtt/runtime/init" };
      if (normalized === "start") return { method: "POST", url: "/api/system/mqtt/runtime/start" };
      if (normalized === "stop") return { method: "POST", url: "/api/system/mqtt/runtime/stop" };
      if (normalized === "bootstrap") return { method: "POST", url: "/api/system/mqtt/bootstrap/publish" };
      if (normalized === "view-config") return { method: "GET", url: "/api/system/runtime/config" };
      return { method: "POST", url: "/api/system/mqtt/runtime/rebuild" };
    }

    function renderRuntimeDebugStream() {
      const node = document.getElementById("runtime-debug-stream");
      if (!node) return;
      if (!Array.isArray(state.debugMessages) || state.debugMessages.length === 0) {
        node.textContent = "No debug messages yet.";
        return;
      }
      const lines = state.debugMessages.slice(-80).map((item) => {
        const ts = String(item.timestamp || item.ts || "-");
        const topic = String(item.topic || "-");
        const source = String(item.source_principal || "unknown");
        const payloadPreview = String(item.payload_preview || item.payload || "");
        return `[${ts}] [${source}] ${topic} -> ${payloadPreview}`;
      });
      node.textContent = lines.join("\\n");
    }

    async function pollDebugMessages() {
      if (!state.debugSubscriptionId) return;
      try {
        const res = await fetch(`/api/system/debug/subscribe/${encodeURIComponent(state.debugSubscriptionId)}/messages?limit=80`, {
          cache: "no-store",
          credentials: "include",
        });
        const payload = await res.json();
        if (!res.ok || !payload.ok) {
          throw new Error(payload && payload.detail ? payload.detail : "debug_messages_failed");
        }
        state.debugMessages = Array.isArray(payload.items) ? payload.items : [];
        renderRuntimeDebugStream();
      } catch (error) {
        setStatus(`Debug stream stopped: ${error && error.message ? error.message : String(error)}`, "error");
        if (state.debugPollHandle) {
          clearInterval(state.debugPollHandle);
          state.debugPollHandle = null;
        }
      }
    }

    async function runDebugSubscribe() {
      const topicFilter = String(window.prompt("Topic filter", "synthia/#") || "").trim();
      if (!topicFilter) return;
      const qosRaw = String(window.prompt("QoS (0/1/2)", "0") || "0").trim();
      const qos = Number.parseInt(qosRaw, 10);
      if (!Number.isFinite(qos) || qos < 0 || qos > 2) {
        setStatus("Debug subscribe failed: qos_invalid", "error");
        return;
      }
      setStatus(`Starting debug subscribe on ${topicFilter}...`, "");
      try {
        const res = await fetch("/api/system/debug/subscribe", {
          method: "POST",
          credentials: "include",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ topic_filter: topicFilter, qos, timeout_s: 300 }),
        });
        const payload = await res.json();
        if (!res.ok || !payload.ok) {
          throw new Error(payload && payload.detail ? payload.detail : "debug_subscribe_failed");
        }
        state.debugSubscriptionId = String(payload.subscription_id || "");
        state.debugMessages = [];
        renderRuntimeDebugStream();
        if (state.debugPollHandle) clearInterval(state.debugPollHandle);
        await pollDebugMessages();
        state.debugPollHandle = setInterval(() => { void pollDebugMessages(); }, 2000);
        setStatus(`Debug subscribe active (${topicFilter}).`, "ok");
      } catch (error) {
        setStatus(`Debug subscribe failed: ${error && error.message ? error.message : String(error)}`, "error");
      }
    }

    async function runDebugUnsubscribe() {
      const id = String(state.debugSubscriptionId || "").trim();
      if (!id) return;
      setStatus("Stopping debug subscribe...", "");
      try {
        const res = await fetch("/api/system/debug/unsubscribe", {
          method: "POST",
          credentials: "include",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ subscription_id: id }),
        });
        const payload = await res.json();
        if (!res.ok || !payload.ok) {
          throw new Error(payload && payload.detail ? payload.detail : "debug_unsubscribe_failed");
        }
        if (state.debugPollHandle) {
          clearInterval(state.debugPollHandle);
          state.debugPollHandle = null;
        }
        state.debugSubscriptionId = null;
        state.debugMessages = [];
        renderRuntimeDebugStream();
        setStatus("Debug subscribe stopped.", "ok");
      } catch (error) {
        setStatus(`Debug unsubscribe failed: ${error && error.message ? error.message : String(error)}`, "error");
      }
    }

    async function runDebugPublish() {
      const topicNode = document.getElementById("debug-publish-topic");
      const payloadNode = document.getElementById("debug-publish-payload");
      const qosNode = document.getElementById("debug-publish-qos");
      const retainNode = document.getElementById("debug-publish-retain");
      if (!topicNode || !payloadNode || !qosNode || !retainNode) return;
      const topic = String(topicNode.value || "").trim();
      if (!topic) {
        setStatus("Debug publish failed: topic_required", "error");
        return;
      }
      let payload = String(payloadNode.value || "").trim();
      let parsedPayload = {};
      if (payload) {
        try {
          parsedPayload = JSON.parse(payload);
        } catch (error) {
          parsedPayload = { value: payload };
        }
      }
      const qos = Number.parseInt(String(qosNode.value || "0"), 10);
      const retain = Boolean(retainNode.checked);
      setStatus(`Publishing to ${topic}...`, "");
      try {
        const res = await fetch("/api/system/debug/publish", {
          method: "POST",
          credentials: "include",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            topic,
            payload: parsedPayload,
            qos: Number.isFinite(qos) ? qos : 0,
            retain,
          }),
        });
        const data = await res.json();
        if (!res.ok || !data.ok) {
          throw new Error(data && data.detail ? data.detail : "debug_publish_failed");
        }
        setStatus(`Published to ${topic} (qos=${data.qos}, retain=${data.retain ? "true" : "false"}).`, "ok");
      } catch (error) {
        setStatus(`Debug publish failed: ${error && error.message ? error.message : String(error)}`, "error");
      }
    }

    async function runRuntimeConfigView() {
      setStatus("Loading runtime config...", "");
      try {
        const res = await fetch("/api/system/runtime/config", { credentials: "include", cache: "no-store" });
        const payload = await res.json();
        if (!res.ok || !payload.ok) {
          throw new Error(payload && payload.detail ? payload.detail : "runtime_config_failed");
        }
        const files = payload && payload.files && typeof payload.files === "object" ? payload.files : {};
        const ordered = ["broker.conf", "acl_compiled.conf", "passwords.conf"];
        const lines = [];
        ordered.forEach((name) => {
          if (!Object.prototype.hasOwnProperty.call(files, name)) return;
          lines.push(`# ${name}`);
          lines.push(String(files[name] || ""));
          lines.push("");
        });
        if (lines.length === 0) {
          lines.push("No runtime config files available.");
        }
        const node = document.getElementById("runtime-debug-stream");
        if (node) node.textContent = lines.join("\\n");
        setStatus("Runtime config loaded.", "ok");
      } catch (error) {
        setStatus(`Runtime config failed: ${error && error.message ? error.message : String(error)}`, "error");
      }
    }

    async function runRuntimeNoisyAction(action, principalId) {
      const act = String(action || "").trim().toLowerCase();
      const id = String(principalId || "").trim();
      if (!act || !id) return;
      if ((act === "disconnect" || act === "block") && !window.confirm(`${act} ${id}?`)) return;
      setStatus(`Applying ${act} to ${id}...`, "");
      try {
        const res = await fetch(`/api/system/runtime/${encodeURIComponent(act)}`, {
          method: "POST",
          credentials: "include",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ principal_id: id, reason: `ui_${act}` }),
        });
        const payload = await res.json();
        if (!res.ok || !payload.ok) {
          throw new Error(payload && payload.detail ? payload.detail : `${act}_failed`);
        }
        await loadStatus();
        setStatus(`${act} applied to ${id}.`, "ok");
      } catch (error) {
        setStatus(`${act} failed for ${id}: ${error && error.message ? error.message : String(error)}`, "error");
      }
    }

    async function runRuntimeAction(action) {
      const endpoint = runtimeActionEndpoint(action);
      setRuntimeBusy(true);
      setStatus(`Running runtime action: ${action}...`, "");
      setRuntimeActionStatus("Running...", "");
      try {
        const options = { method: endpoint.method, credentials: "include" };
        if (String(action || "").toLowerCase() === "rebuild") {
          options.headers = { "Content-Type": "application/json" };
          options.body = JSON.stringify({ force: false });
        }
        let res = await fetch(endpoint.url, options);
        let payload = await res.json();
        if (String(action || "").toLowerCase() === "rebuild" && res.status === 409) {
          const detail = payload && payload.detail && typeof payload.detail === "object" ? payload.detail : {};
          const estimated = Number(detail.estimated_active_count || 0);
          const clientList = Array.isArray(detail.active_clients) ? detail.active_clients.join(", ") : "";
          const confirmed = window.confirm(
            `Active clients detected (${estimated}).${clientList ? `\\n${clientList}` : ""}\\nForce rebuild anyway?`
          );
          if (!confirmed) {
            setRuntimeActionStatus("Rebuild cancelled.", "warn");
            setStatus("Rebuild cancelled.", "warn");
            return;
          }
          res = await fetch(endpoint.url, {
            method: endpoint.method,
            credentials: "include",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ force: true }),
          });
          payload = await res.json();
        }
        if (!res.ok) throw new Error(payload && payload.detail ? JSON.stringify(payload.detail) : `${endpoint.url}_http_${res.status}`);
        await loadStatus();
        const runtime = payload && payload.runtime ? payload.runtime : {};
        const health = payload && payload.health ? payload.health : {};
        const healthy = action === "health" ? Boolean(runtime.healthy) : Boolean(payload.ok);
        const message = action === "health"
          ? (runtime.healthy ? "Runtime health is healthy." : `Runtime health is degraded: ${runtime.degraded_reason || "unknown"}.`)
          : `Runtime ${action} completed (state=${runtime.state || "unknown"}, connected=${health.connected ? "true" : "false"}).`;
        setRuntimeActionStatus(message, healthy ? "ok" : "error");
        setStatus(message, healthy ? "ok" : "error");
      } catch (error) {
        const message = `Runtime ${action} failed: ${error?.message || String(error)}`;
        setRuntimeActionStatus(message, "error");
        setStatus(message, "error");
      } finally {
        setRuntimeBusy(false);
      }
    }

    function renderGateBanner() {
      const coreStatus = state.setupSummary && state.setupSummary.core_principals ? state.setupSummary.core_principals : {};
      const missingCorePrincipals = Array.isArray(coreStatus.missing) ? coreStatus.missing : [];
      const messages = [];
      if (state.gateActive) {
        messages.push("Setup required: only the setup page is available until MQTT initialization completes.");
      }
      if (missingCorePrincipals.length > 0) {
        messages.push(`Core principal registration warning: missing ${missingCorePrincipals.join(", ")}.`);
      }
      if (messages.length === 0) {
        setupBanner.classList.remove("visible");
        setupBanner.textContent = "";
        return;
      }
      setupBanner.classList.add("visible");
      setupBanner.textContent = messages.join(" ");
    }

    function healthPill(text, tone) {
      return `<span class="pill ${escapeHtml(tone)}">${escapeHtml(text)}</span>`;
    }

    function renderStats(items) {
      return `<div class="stats">` + items.map((item) =>
        `<div class="stat"><span class="k">${escapeHtml(item.k)}</span><span class="v">${escapeHtml(item.v)}</span></div>`
      ).join("") + `</div>`;
    }

    function statusTone(value) {
      const v = String(value || "").toLowerCase();
      if (v.includes("ready") || v.includes("healthy") || v.includes("active") || v === "ok" || v === "normal") return "ok";
      if (v.includes("degraded") || v.includes("probation") || v.includes("watch") || v.includes("warn")) return "warn";
      return "bad";
    }

    function principalLedTone(item, runtimeConnected) {
      const status = String(item && item.status ? item.status : "").toLowerCase();
      const noisyState = String(item && item.noisy_state ? item.noisy_state : "").toLowerCase();
      if (status === "revoked" || status === "expired" || status === "error" || noisyState === "blocked") return "bad";
      if (runtimeConnected) return "ok";
      return "muted";
    }

    async function loadOverviewPayload() {
      const [principals, noisy, audit, runtimeHealth] = await Promise.all([
        fetchJson("/api/system/mqtt/principals"),
        fetchJson("/api/system/mqtt/noisy-clients"),
        fetchJson("/api/system/mqtt/audit?limit=20"),
        fetchJson("/api/system/runtime/health"),
      ]);
      return {
        principals: Array.isArray(principals.items) ? principals.items : [],
        noisy: Array.isArray(noisy.items) ? noisy.items : [],
        audit: Array.isArray(audit.items) ? audit.items : [],
        brokerMetrics: runtimeHealth && runtimeHealth.broker_metrics ? runtimeHealth.broker_metrics : {},
      };
    }

    function filteredPrincipals(items) {
      const q = String(state.filters.principals.q || "").trim().toLowerCase();
      const type = String(state.filters.principals.type || "").trim().toLowerCase();
      const status = String(state.filters.principals.status || "").trim().toLowerCase();
      return items.filter((item) => {
        const pid = String(item.principal_id || "").toLowerCase();
        const ptype = principalGroup(item);
        const pstatus = String(item.status || "").toLowerCase();
        if (q && !pid.includes(q)) return false;
        if (type && ptype !== type) return false;
        if (status && pstatus !== status) return false;
        return true;
      });
    }

    function principalGroup(item) {
      const raw = String(item.principal_type || item.type || "").toLowerCase();
      if (raw.includes("system")) return "system";
      if (raw.includes("addon")) return "addon";
      if (raw.includes("node")) return "node";
      if (raw.includes("generic")) return "generic";
      return "other";
    }

    function principalGroupLabel(group) {
      if (group === "system") return "System";
      if (group === "addon") return "Addon";
      if (group === "node") return "Node";
      if (group === "generic") return "Generic";
      return "Other";
    }

    function filteredUsers(items) {
      const q = String(state.filters.users.q || "").trim().toLowerCase();
      const status = String(state.filters.users.status || "").trim().toLowerCase();
      return items.filter((item) => {
        const name = String(item.username || item.logical_identity || item.principal_id || "").toLowerCase();
        const ustatus = String(item.status || "").toLowerCase();
        if (q && !name.includes(q)) return false;
        if (status && ustatus !== status) return false;
        return true;
      });
    }

    function filteredAudit(items) {
      const q = String(state.filters.audit.q || "").trim().toLowerCase();
      const status = String(state.filters.audit.status || "").trim().toLowerCase();
      const principal = String(state.filters.audit.principal || "").trim().toLowerCase();
      const actionType = String(state.filters.audit.action || "").trim().toLowerCase();
      return items.filter((item) => {
        const action = String(item.action || item.event_type || "").toLowerCase();
        const eventType = String(item.event_type || "").toLowerCase();
        const result = String(item.result || item.status || "").toLowerCase();
        const actor = String(item.actor_principal || "").toLowerCase();
        const target = String(item.target || "").toLowerCase();
        if (q && !action.includes(q) && !eventType.includes(q) && !actor.includes(q) && !target.includes(q)) return false;
        if (status && result !== status) return false;
        if (principal && !actor.includes(principal) && !target.includes(principal)) return false;
        if (actionType && !action.includes(actionType) && !eventType.includes(actionType)) return false;
        return true;
      });
    }

    function filteredNoisy(items) {
      const q = String(state.filters.noisyClients.q || "").trim().toLowerCase();
      const stateFilter = String(state.filters.noisyClients.state || "").trim().toLowerCase();
      return items.filter((item) => {
        const principal = String(item.principal_id || "").toLowerCase();
        const noisyState = String(item.noisy_state || item.status || "").toLowerCase();
        if (q && !principal.includes(q)) return false;
        if (stateFilter && noisyState !== stateFilter) return false;
        return true;
      });
    }

    function buildTopicTree(items) {
      const root = {};
      (Array.isArray(items) ? items : []).forEach((item) => {
        const topic = String(item && item.topic ? item.topic : "").trim();
        if (!topic) return;
        const parts = topic.split("/").filter((part) => part.length > 0);
        if (parts.length === 0) return;
        let cursor = root;
        parts.forEach((part) => {
          if (!cursor[part]) cursor[part] = {};
          cursor = cursor[part];
        });
      });
      return root;
    }

    function renderTopicTreeNode(name, node, prefix) {
      const path = prefix ? `${prefix}/${name}` : name;
      const children = Object.keys(node || {}).sort();
      if (children.length === 0) {
        return `<li><span class='mono'>${escapeHtml(path)}</span></li>`;
      }
      const childHtml = children.map((child) => renderTopicTreeNode(child, node[child], path)).join("");
      return `<li><details><summary class='mono'>${escapeHtml(path)}</summary><ul class='tree'>${childHtml}</ul></details></li>`;
    }

    function renderTopicTree(items) {
      const root = buildTopicTree(items);
      const keys = Object.keys(root).sort();
      if (keys.length === 0) return "<div class='empty'>No topics observed yet.</div>";
      const html = keys.map((key) => renderTopicTreeNode(key, root[key], "")).join("");
      return `<ul class='tree'>${html}</ul>`;
    }

    function createUserModalMarkup() {
      return (
        `<div id='create-user-modal' class='modal-backdrop hidden'>` +
        `<div class='modal'>` +
        `<h3>Create MQTT User</h3>` +
        `<div class='modal-grid'>` +
        `<label>Username<input id='create-user-username' placeholder='homeassistant' /></label>` +
        `<label>Password<input id='create-user-password' placeholder='generated' value='generated' /></label>` +
        `<label>Topic Prefix<input id='create-user-prefix' placeholder='external/homeassistant' /></label>` +
        `<label>Access Mode<select id='create-user-access-mode'><option value='private'>private</option><option value='custom'>custom</option><option value='non_reserved'>non_reserved</option><option value='admin'>admin</option></select></label>` +
        `<label>Allowed Topics (comma separated)<input id='create-user-allowed-topics' placeholder='external/homeassistant/sensors/#' /></label>` +
        `<label>Allowed Publish Topics (comma separated)<input id='create-user-allowed-publish-topics' placeholder='external/homeassistant/events/#' /></label>` +
        `<label>Allowed Subscribe Topics (comma separated)<input id='create-user-allowed-subscribe-topics' placeholder='synthia/runtime/#' /></label>` +
        `</div>` +
        `<div class='modal-actions'>` +
        `<button class='primary' data-ui-action='submit-add-user'>Create</button>` +
        `<button data-ui-action='close-add-user'>Cancel</button>` +
        `</div>` +
        `<div id='create-user-status' class='status'></div>` +
        `</div>` +
        `</div>`
      );
    }

    async function loadSectionPayload(section) {
      if (section === "principals" || section === "users") {
        const principals = await fetchJson("/api/system/mqtt/principals");
        const items = Array.isArray(principals.items) ? principals.items : [];
        if (section === "users") {
          return items.filter((item) => {
            const kind = String(item.principal_type || item.type || "").toLowerCase();
            const identity = String(item.logical_identity || "").toLowerCase();
            return kind.includes("generic") || identity.startsWith("generic:");
          });
        }
        return items;
      }
      if (section === "noisy-clients") {
        const noisy = await fetchJson("/api/system/mqtt/noisy-clients");
        return Array.isArray(noisy.items) ? noisy.items : [];
      }
      if (section === "topics") {
        const topics = await fetchJson("/api/system/runtime/topics?limit=1000");
        return Array.isArray(topics.items) ? topics.items : [];
      }
      if (section === "audit") {
        const params = new URLSearchParams();
        params.set("limit", "50");
        const principal = String(state.filters.audit.principal || "").trim();
        const action = String(state.filters.audit.action || "").trim();
        if (principal) params.set("principal", principal);
        if (action) params.set("action", action);
        const audit = await fetchJson(`/api/system/mqtt/audit?${params.toString()}`);
        return Array.isArray(audit.items) ? audit.items : [];
      }
      return null;
    }

    async function renderSectionBody() {
      const section = state.currentSection;
      if (section === "setup") {
        sectionTitle.textContent = "Setup";
        sectionContent.innerHTML = "<div class='status'>Use the setup form below to initialize MQTT.</div>";
        setupCard.style.display = "block";
        return;
      }

      setupCard.style.display = state.gateActive ? "block" : "none";

      if (section === "overview") {
        sectionTitle.textContent = "Overview";
        const setup = state.setupSummary && state.setupSummary.setup ? state.setupSummary.setup : {};
        const broker = state.setupSummary && state.setupSummary.broker ? state.setupSummary.broker : {};
        const effective = state.setupSummary && state.setupSummary.effective_status ? state.setupSummary.effective_status : {};
        let overview = state.sectionCache.overview;
        if (!overview) {
          overview = await loadOverviewPayload();
          state.sectionCache.overview = overview;
        }
        const principals = Array.isArray(overview.principals) ? overview.principals : [];
        const genericUsers = principals.filter((item) => String(item.principal_type || "").toLowerCase() === "generic_user");
        const noisy = Array.isArray(overview.noisy) ? overview.noisy : [];
        const blocked = noisy.filter((item) => String(item.noisy_state || "").toLowerCase() === "blocked");
        const auditItems = Array.isArray(overview.audit) ? overview.audit : [];
        const recentErrors = auditItems.filter((item) => {
          const status = String(item.result || item.status || "").toLowerCase();
          return status === "error" || status === "degraded" || status === "warn";
        });
        const brokerMetrics = overview && overview.brokerMetrics ? overview.brokerMetrics : {};
        const degraded = String(effective.status || "").toLowerCase() === "degraded";
        sectionContent.innerHTML =
          (degraded ? `<div class='status error'>MQTT is degraded: ${(effective.reasons || []).map((x) => escapeHtml(x)).join(", ") || "unknown reason"}</div>` : "") +
          `<div>${healthPill(`Authority ${setup.authority_ready ? "ready" : "degraded"}`, setup.authority_ready ? "ok" : "bad")}` +
          `${healthPill(`Runtime ${state.statusPayload && state.statusPayload.connected ? "connected" : "disconnected"}`, state.statusPayload && state.statusPayload.connected ? "ok" : "warn")}` +
          `${healthPill(`Bootstrap ${(state.setupSummary && state.setupSummary.bootstrap_publish && state.setupSummary.bootstrap_publish.published) ? "published" : "pending"}`, (state.setupSummary && state.setupSummary.bootstrap_publish && state.setupSummary.bootstrap_publish.published) ? "ok" : "warn")}` +
          `${healthPill(`Setup ${setup.setup_status || "unknown"}`, statusTone(setup.setup_status || "unknown"))}</div>` +
          renderStats([
            { k: "Total Principals", v: principals.length },
            { k: "Generic Users", v: genericUsers.length },
            { k: "Noisy", v: noisy.length },
            { k: "Blocked", v: blocked.length },
            { k: "Recent Audit", v: auditItems.length },
            { k: "Recent Errors", v: recentErrors.length },
            { k: "Connected Clients", v: brokerMetrics.connected_clients ?? "-" },
            { k: "Message Rate", v: formatMsgRate(brokerMetrics.message_rate) },
            { k: "Dropped Messages", v: brokerMetrics.dropped_messages ?? "-" },
            { k: "Retained Messages", v: brokerMetrics.retained_messages ?? "-" },
            { k: "Broker Uptime", v: brokerMetrics.broker_uptime || "-" },
          ]) +
          `<div class='mono'>` +
          `mode: ${escapeHtml(state.statusPayload && state.statusPayload.mode ? state.statusPayload.mode : "unknown")}\\n` +
          `endpoint: ${escapeHtml(state.statusPayload && state.statusPayload.host ? `${state.statusPayload.host}:${state.statusPayload.port || "-"}` : "not configured")}\\n` +
          `broker_mode: ${escapeHtml(broker.broker_mode || "unknown")}\\n` +
          `direct_mqtt_supported: ${escapeHtml(broker.direct_mqtt_supported ? "true" : "false")}\\n` +
          `recent_activity: ${escapeHtml(auditItems.slice(0, 3).map((x) => x.event_type || "-").join(", ") || "none")}` +
          `</div>`;
        return;
      }

      if (section === "runtime") {
        sectionTitle.textContent = "Runtime";
        const recon = state.setupSummary && state.setupSummary.reconciliation ? state.setupSummary.reconciliation : {};
        const bootstrap = state.setupSummary && state.setupSummary.bootstrap_publish ? state.setupSummary.bootstrap_publish : {};
        sectionContent.innerHTML =
          `<div class='row runtime-actions'>` +
          `<button data-runtime-action='init'>Init</button>` +
          `<button data-runtime-action='start'>Start</button>` +
          `<button data-runtime-action='stop'>Stop</button>` +
          `<button data-runtime-action='rebuild'>Rebuild</button>` +
          `<button data-runtime-action='bootstrap'>Publish Bootstrap</button>` +
          `<button data-runtime-action='health'>Check Health</button>` +
          `<button data-runtime-action='view-config'>View Runtime Config</button>` +
          `<button data-runtime-action='debug-subscribe'>Subscribe to Topic</button>` +
          `<button data-runtime-action='debug-unsubscribe' ${state.debugSubscriptionId ? "" : "disabled"}>Stop Subscription</button>` +
          `</div>` +
          `<div id='runtime-action-status' class='${state.runtimeActionKind ? "status " + state.runtimeActionKind : "status"}'>${escapeHtml(state.runtimeActionStatus || "")}</div>` +
          `<div class='mono'>` +
          `last_reconcile_status: ${escapeHtml(recon.last_reconcile_status || "unknown")}\\n` +
          `last_reconcile_reason: ${escapeHtml(recon.last_reconcile_reason || "-")}\\n` +
          `last_runtime_state: ${escapeHtml(recon.last_runtime_state || "unknown")}\\n` +
          `bootstrap_published: ${escapeHtml(bootstrap.published ? "true" : "false")}\\n` +
          `bootstrap_attempts: ${escapeHtml(bootstrap.attempts || 0)}\\n` +
          `bootstrap_last_error: ${escapeHtml(bootstrap.last_error || "none")}` +
          `</div>` +
          `<h4>Debug Publish</h4>` +
          `<div class='grid'>` +
          `<label>Topic<input id='debug-publish-topic' placeholder='external/test/event' /></label>` +
          `<label>Payload (JSON or plain text)<input id='debug-publish-payload' placeholder='{\"hello\":\"world\"}' /></label>` +
          `<label>QoS<select id='debug-publish-qos'><option value='0'>0</option><option value='1'>1</option><option value='2'>2</option></select></label>` +
          `<label>Retain<input id='debug-publish-retain' type='checkbox' /></label>` +
          `</div>` +
          `<div class='row'><button data-runtime-action='debug-publish'>Publish Message</button></div>` +
          `<h4>Live Message Monitor</h4>` +
          `<div id='runtime-debug-stream' class='mono'>No debug messages yet.</div>`;
        renderRuntimeDebugStream();
        return;
      }

      sectionTitle.textContent =
        section === "principals" ? "Principals" :
        section === "users" ? "Generic Users" :
        section === "topics" ? "Topic Explorer" :
        section === "audit" ? "Audit" : "Noisy Clients";
      sectionContent.innerHTML = "<div class='status'>Loading...</div>";
      try {
        const items = await loadSectionPayload(section);
        state.sectionCache[section] = items;
        if (!Array.isArray(items) || items.length === 0) {
          sectionContent.innerHTML = "<div class='empty'>No items.</div>";
          return;
        }
        let visible = items;
        let toolbar = "";
        if (section === "principals") {
          toolbar =
            `<div class='toolbar'>` +
            `<input data-filter='principals-q' placeholder='Search principal id' value='${escapeHtml(state.filters.principals.q)}' />` +
            `<select data-filter='principals-type'><option value='' ${state.filters.principals.type === "" ? "selected" : ""}>All types</option><option value='system' ${state.filters.principals.type === "system" ? "selected" : ""}>System</option><option value='addon' ${state.filters.principals.type === "addon" ? "selected" : ""}>Addon</option><option value='node' ${state.filters.principals.type === "node" ? "selected" : ""}>Node</option><option value='generic' ${state.filters.principals.type === "generic" ? "selected" : ""}>Generic</option></select>` +
            `<select data-filter='principals-status'><option value='' ${state.filters.principals.status === "" ? "selected" : ""}>All status</option><option value='pending' ${state.filters.principals.status === "pending" ? "selected" : ""}>Pending</option><option value='active' ${state.filters.principals.status === "active" ? "selected" : ""}>Active</option><option value='probation' ${state.filters.principals.status === "probation" ? "selected" : ""}>Probation</option><option value='revoked' ${state.filters.principals.status === "revoked" ? "selected" : ""}>Revoked</option><option value='expired' ${state.filters.principals.status === "expired" ? "selected" : ""}>Expired</option></select>` +
            `<span class='toolbar-spacer'></span>` +
            `<button class='mini primary' data-ui-action='open-add-user'>Add User</button>` +
            `</div>`;
          visible = filteredPrincipals(items);
        } else if (section === "users") {
          toolbar =
            `<div class='toolbar'>` +
            `<input data-filter='users-q' placeholder='Search username' value='${escapeHtml(state.filters.users.q)}' />` +
            `<select data-filter='users-status'><option value='' ${state.filters.users.status === "" ? "selected" : ""}>All status</option><option value='active' ${state.filters.users.status === "active" ? "selected" : ""}>Active</option><option value='probation' ${state.filters.users.status === "probation" ? "selected" : ""}>Probation</option><option value='revoked' ${state.filters.users.status === "revoked" ? "selected" : ""}>Revoked</option></select>` +
            `<span class='toolbar-spacer'></span>` +
            `<button class='mini' data-ui-action='export-users'>Export Users</button>` +
            `<button class='mini' data-ui-action='import-users'>Import Users</button>` +
            `<button class='mini primary' data-ui-action='open-add-user'>Add User</button>` +
            `</div>`;
          visible = filteredUsers(items);
        } else if (section === "audit") {
          toolbar =
            `<div class='toolbar'>` +
            `<input data-filter='audit-q' placeholder='Search action' value='${escapeHtml(state.filters.audit.q)}' />` +
            `<input data-filter='audit-principal' placeholder='Filter principal' value='${escapeHtml(state.filters.audit.principal)}' />` +
            `<input data-filter='audit-action' placeholder='Filter action type' value='${escapeHtml(state.filters.audit.action)}' />` +
            `<select data-filter='audit-status'><option value='' ${state.filters.audit.status === "" ? "selected" : ""}>All results</option><option value='ok' ${state.filters.audit.status === "ok" ? "selected" : ""}>Success</option><option value='error' ${state.filters.audit.status === "error" ? "selected" : ""}>Failure</option><option value='degraded' ${state.filters.audit.status === "degraded" ? "selected" : ""}>Degraded</option><option value='warn' ${state.filters.audit.status === "warn" ? "selected" : ""}>Warning</option></select>` +
            `</div>`;
          visible = filteredAudit(items);
        } else if (section === "topics") {
          toolbar =
            `<div class='toolbar'>` +
            `<input data-filter='topics-q' placeholder='Filter topic path' value='${escapeHtml(String(state.filters.topics && state.filters.topics.q || ""))}' />` +
            `</div>`;
          const topicQuery = String(state.filters.topics && state.filters.topics.q || "").trim().toLowerCase();
          visible = items.filter((item) => {
            const topic = String(item && item.topic ? item.topic : "").toLowerCase();
            return !topicQuery || topic.includes(topicQuery);
          });
        } else if (section === "noisy-clients") {
          toolbar =
            `<div class='toolbar'>` +
            `<input data-filter='noisy-q' placeholder='Search principal id' value='${escapeHtml(state.filters.noisyClients.q)}' />` +
            `<select data-filter='noisy-state'><option value='' ${state.filters.noisyClients.state === "" ? "selected" : ""}>All noisy states</option><option value='watch' ${state.filters.noisyClients.state === "watch" ? "selected" : ""}>Watch</option><option value='noisy' ${state.filters.noisyClients.state === "noisy" ? "selected" : ""}>Noisy</option><option value='blocked' ${state.filters.noisyClients.state === "blocked" ? "selected" : ""}>Blocked</option></select>` +
            `</div>`;
          visible = filteredNoisy(items);
        }
        if (!Array.isArray(visible) || visible.length === 0) {
          sectionContent.innerHTML = toolbar + "<div class='empty'>No matching records.</div>";
          return;
        }
        if (section === "principals") {
          const order = ["system", "addon", "node", "generic", "other"];
          const groups = {};
          visible.forEach((item) => {
            const key = principalGroup(item);
            if (!groups[key]) groups[key] = [];
            groups[key].push(item);
          });
          const chunks = order
            .filter((key) => Array.isArray(groups[key]) && groups[key].length > 0)
            .map((key) => {
              const rows = groups[key]
                .slice(0, 50)
                .map((item) => {
                  const principalId = escapeHtml(item.principal_id || item.id || "-");
                  const principalType = escapeHtml(String(item.principal_type || item.type || key));
                  const rawStatus = String(item.status || "-");
                  const runtimeConnection = item && item.runtime_connection ? item.runtime_connection : {};
                  const runtimeConnected = Boolean(runtimeConnection && runtimeConnection.connected);
                  const status = escapeHtml(rawStatus);
                  const ledTone = principalLedTone(item, runtimeConnected);
                  const ledHint = runtimeConnected ? "connected" : "disconnected";
                  const led = `<span class='led ${ledTone}' title='${escapeHtml(ledHint)}'></span>`;
                  const topicPrefix = escapeHtml(String(item.topic_prefix || "-"));
                  const accessMode = escapeHtml(String(item.access_mode || "private"));
                  const allowedTopics = escapeHtml(Array.isArray(item.allowed_topics) ? item.allowed_topics.join(",") : "");
                  const allowedPublishTopics = escapeHtml(
                    Array.isArray(item.allowed_publish_topics) ? item.allowed_publish_topics.join(",") : ""
                  );
                  const allowedSubscribeTopics = escapeHtml(
                    Array.isArray(item.allowed_subscribe_topics) ? item.allowed_subscribe_topics.join(",") : ""
                  );
                  const managed = String(item.managed_by || "").toLowerCase() === "core";
                  const managedBadge = managed ? `<span class='badge core'>Core Managed</span>` : "";
                  const updated = escapeHtml(formatLocalTimestamp(item.updated_at || item.ts || item.reason || "-"));
                  const systemLocked = key === "system";
                  const destructive = `<button class='mini' disabled title='System principals are Core-managed'>Revoke</button>` +
                    `<button class='mini' disabled title='System principals are Core-managed'>Delete</button>` +
                    `<button class='mini' disabled title='System principals are Core-managed'>Rotate Password</button>` +
                    `<button class='mini' disabled title='System principals are Core-managed'>Edit Policy</button>`;
                  const readonly = `<button class='mini' data-principal-info='details' data-principal-id='${principalId}'>Details</button>` +
                    `<button class='mini' data-principal-info='permissions' data-principal-id='${principalId}'>Permissions</button>` +
                    `<button class='mini' data-principal-info='last-seen' data-principal-id='${principalId}'>Last Seen</button>`;
                  const genericActions = key === "generic"
                    ? `<button class='mini' data-generic-action='revoke' data-principal-id='${principalId}'>Revoke</button>` +
                      `<button class='mini' data-generic-action='disable' data-principal-id='${principalId}'>Disable</button>` +
                      `<button class='mini' data-generic-action='rotate' data-principal-id='${principalId}'>Rotate Password</button>` +
                      `<button class='mini' data-generic-action='edit' data-principal-id='${principalId}' data-topic-prefix='${topicPrefix}' data-access-mode='${accessMode}' data-allowed-topics='${allowedTopics}' data-allowed-publish-topics='${allowedPublishTopics}' data-allowed-subscribe-topics='${allowedSubscribeTopics}'>Edit Policy</button>` +
                      `<button class='mini' data-generic-action='delete' data-principal-id='${principalId}'>Delete</button>`
                    : "";
                  const principalActions = key !== "generic" && !systemLocked
                    ? `<button class='mini' data-principal-action='activate' data-principal-id='${principalId}'>Activate</button>` +
                      `<button class='mini' data-principal-action='probation' data-principal-id='${principalId}'>Disable</button>` +
                      `<button class='mini' data-principal-action='revoke' data-principal-id='${principalId}'>Revoke</button>`
                    : "";
                  return `<tr><td class='led-cell'>${led}</td><td>${principalId}</td><td>${principalType}${managedBadge}</td><td>${status}</td><td>${topicPrefix}</td><td>${updated}</td><td><div class='row-actions'>${readonly}${systemLocked ? destructive : (key === "generic" ? genericActions : principalActions)}</div></td></tr>`;
                })
                .join("");
              return `<div class='group-title'>${escapeHtml(principalGroupLabel(key))}</div><table class='table'><thead><tr><th class='led-cell'>State</th><th>Principal</th><th>Type</th><th>Status</th><th>Topic Prefix</th><th>Updated</th><th>Actions</th></tr></thead><tbody>${rows}</tbody></table>`;
            })
            .join("");
          sectionContent.innerHTML = toolbar + chunks + createUserModalMarkup();
          return;
        }

        if (section === "noisy-clients") {
          const rows = visible
            .slice(0, 50)
            .map((item) => {
              const principalId = escapeHtml(item.principal_id || "-");
              const noisyState = escapeHtml(item.noisy_state || item.status || "-");
              const inputs = item && item.noisy_inputs ? item.noisy_inputs : {};
              const mps = escapeHtml(String(inputs.messages_per_second ?? "-"));
              const payloadSize = escapeHtml(String(inputs.payload_size ?? "-"));
              const topicCount = escapeHtml(String(inputs.topic_count ?? "-"));
              const updated = escapeHtml(item.noisy_updated_at || item.updated_at || "-");
              const actions =
                `<button class='mini' data-noisy-action='disconnect' data-principal-id='${principalId}'>Disconnect</button>` +
                `<button class='mini' data-noisy-action='block' data-principal-id='${principalId}'>Block</button>` +
                `<button class='mini' data-noisy-action='throttle' data-principal-id='${principalId}'>Throttle</button>`;
              return `<tr><td>${principalId}</td><td>${noisyState}</td><td>${mps}</td><td>${payloadSize}</td><td>${topicCount}</td><td>${updated}</td><td><div class='row-actions'>${actions}</div></td></tr>`;
            })
            .join("");
          sectionContent.innerHTML =
            toolbar +
            `<table class='table'><thead><tr><th>Principal</th><th>Noisy State</th><th>msg/s</th><th>Payload Size</th><th>Topic Count</th><th>Updated</th><th>Actions</th></tr></thead><tbody>${rows}</tbody></table>`;
          return;
        }

        if (section === "topics") {
          const rows = visible
            .slice(0, 1000)
            .map((item) => {
              const topic = escapeHtml(String(item.topic || "-"));
              const count = escapeHtml(String(item.message_count ?? "-"));
              const retained = escapeHtml(String(item.retained_seen ? "yes" : "no"));
              const lastSeen = escapeHtml(String(item.last_seen || "-"));
              return `<tr><td>${topic}</td><td>${count}</td><td>${retained}</td><td>${lastSeen}</td></tr>`;
            })
            .join("");
          sectionContent.innerHTML =
            toolbar +
            `<div class='group-title'>Hierarchy</div>` +
            renderTopicTree(visible) +
            `<div class='group-title'>Observed Topics</div>` +
            `<table class='table'><thead><tr><th>Topic</th><th>Messages</th><th>Retained</th><th>Last Seen</th></tr></thead><tbody>${rows}</tbody></table>`;
          return;
        }

        if (section === "audit") {
          const rows = visible
            .slice(0, 50)
            .map((item) => {
              const actor = escapeHtml(String(item.actor_principal || "-"));
              const action = escapeHtml(String(item.action || item.event_type || "-"));
              const target = escapeHtml(String(item.target || "-"));
              const result = escapeHtml(String(item.result || item.status || "-"));
              const timestamp = escapeHtml(formatLocalTimestamp(item.timestamp || item.created_at || "-"));
              return `<tr><td>${actor}</td><td>${action}</td><td>${target}</td><td>${result}</td><td>${timestamp}</td></tr>`;
            })
            .join("");
          sectionContent.innerHTML =
            toolbar +
            `<table class='table'><thead><tr><th>Actor</th><th>Action</th><th>Target</th><th>Result</th><th>Timestamp</th></tr></thead><tbody>${rows}</tbody></table>`;
          return;
        }

        if (section === "users") {
          const rows = visible
            .slice(0, 50)
            .map((item) => {
              const principalId = escapeHtml(String(item.principal_id || "-"));
              const username = escapeHtml(String(item.username || item.logical_identity || "-"));
              const status = escapeHtml(String(item.status || "-"));
              const runtimeTraffic = item && item.runtime_traffic ? item.runtime_traffic : {};
              const avgMsgRate = escapeHtml(formatMsgRate(runtimeTraffic.avg_messages_per_second));
              const updated = escapeHtml(formatLocalTimestamp(item.updated_at || item.ts || item.reason || "-"));
              const actions =
                `<button class='mini' data-generic-action='revoke' data-principal-id='${principalId}'>Revoke</button>` +
                `<button class='mini' data-generic-action='disable' data-principal-id='${principalId}'>Disable</button>` +
                `<button class='mini' data-generic-action='rotate' data-principal-id='${principalId}'>Rotate Password</button>`;
              return `<tr><td>${principalId}</td><td>${username}</td><td>${status}</td><td>${avgMsgRate}</td><td>${updated}</td><td><div class='row-actions'>${actions}</div></td></tr>`;
            })
            .join("");
          sectionContent.innerHTML =
            toolbar +
            `<table class='table'><thead><tr><th>Principal</th><th>Username</th><th>Status</th><th>Avg Rate</th><th>Updated</th><th>Actions</th></tr></thead><tbody>${rows}</tbody></table>` +
            createUserModalMarkup();
          return;
        }

        const rows = visible
          .slice(0, 50)
          .map((item) => {
            const a = escapeHtml(item.principal_id || item.id || "-");
            const b = escapeHtml(item.status || item.type || item.event_type || "-");
            const c = escapeHtml(item.updated_at || item.ts || item.reason || "-");
            return `<tr><td>${a}</td><td>${b}</td><td>${c}</td></tr>`;
          })
          .join("");
        sectionContent.innerHTML =
          toolbar +
          `<table class='table'><thead><tr><th>ID</th><th>Status/Type</th><th>Updated/Reason</th></tr></thead><tbody>${rows}</tbody></table>` +
          (section === "users" ? createUserModalMarkup() : "");
      } catch (error) {
        sectionContent.innerHTML = `<div class='status error'>Section load failed: ${escapeHtml(error && error.message ? error.message : String(error))}</div><button id='section-retry'>Retry section</button>`;
      }
    }

    async function renderRoute() {
      const active = sections.includes(state.currentSection) ? state.currentSection : "overview";
      if (state.gateActive && active !== "setup") {
        navigateTo("setup", true);
        return;
      }
      const desiredOrder = state.gateActive
        ? ["setup"]
        : ["overview", "principals", "users", "runtime", "topics", "audit", "noisy-clients", "setup"];
      const buttonBySection = {};
      tabs.querySelectorAll(".tab").forEach((node) => {
        const section = String(node.getAttribute("data-section") || "");
        if (section) buttonBySection[section] = node;
      });
      desiredOrder.forEach((section) => {
        const node = buttonBySection[section];
        if (node) tabs.appendChild(node);
      });
      const tabButtons = tabs.querySelectorAll(".tab");
      tabButtons.forEach((node) => {
        const section = node.getAttribute("data-section");
        const locked = state.gateActive && section !== "setup";
        node.style.display = state.gateActive && section !== "setup" ? "none" : "";
        node.classList.toggle("active", section === active);
        node.classList.toggle("locked", locked);
        node.disabled = locked;
      });
      await renderSectionBody();
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
      applyModeClass();
      renderPreflight();
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
      state.statusPayload = statusPayload;
      state.setupSummary = setupPayload;
      state.sectionCache = {};
      state.gateActive = gateIsActive(setupPayload);
      const connected = statusPayload.connected ? "connected" : "disconnected";
      const modeText = statusPayload.mode || "unknown";
      const endpoint = statusPayload.host ? `${statusPayload.host}:${statusPayload.port ?? "-"}` : "not configured";
      const setupState = setupPayload?.setup?.setup_status || "unknown";
      runtimeStatus.textContent = `MQTT ${connected} • mode ${modeText} • endpoint ${endpoint} • setup ${setupState}`;
      renderGateBanner();
      await renderRoute();
    }

    function shouldAutoRefresh() {
      if (document.hidden) return false;
      const active = document.activeElement;
      if (!active || !active.tagName) return true;
      const tag = String(active.tagName || "").toUpperCase();
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return false;
      return true;
    }

    async function autoRefreshTick() {
      if (state.autoRefreshInFlight) return;
      if (!shouldAutoRefresh()) return;
      state.autoRefreshInFlight = true;
      try {
        await loadStatus();
      } catch (_) {
        // Keep auto-refresh silent; manual actions surface errors.
      } finally {
        state.autoRefreshInFlight = false;
      }
    }

    function startAutoRefresh() {
      if (state.autoRefreshHandle) {
        clearInterval(state.autoRefreshHandle);
      }
      state.autoRefreshHandle = window.setInterval(() => {
        void autoRefreshTick();
      }, AUTO_REFRESH_MS);
    }

    async function applySettings(restartAfter) {
      setBusy(true);
      setStatus("Validating settings...", "");
      try {
        const checks = renderPreflight();
        if (checks.some((item) => item.status === "failed")) {
          throw new Error("preflight_failed");
        }
        const selectedMode = mode.value === "external" ? "external" : "local";
        const parsedPort = Number.parseInt(String(port.value || "").trim(), 10);
        const parsedKeepalive = Number.parseInt(String(keepalive.value || "").trim(), 10);
        if (!Number.isFinite(parsedPort) || parsedPort <= 0 || parsedPort > 65535) {
          throw new Error("invalid_port");
        }
        if (!Number.isFinite(parsedKeepalive) || parsedKeepalive <= 0) {
          throw new Error("invalid_keepalive");
        }
        setStatus("Initializing MQTT...", "");
        const applyRes = await fetch("/api/system/mqtt/setup/apply", {
          method: "POST",
          credentials: "include",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            mode: selectedMode,
            host: String(host.value || "").trim(),
            port: parsedPort,
            username: String(username.value || "").trim(),
            password: String(password.value || ""),
            tls_enabled: tls.value === "true",
            keepalive_s: parsedKeepalive,
            client_id: String(clientId.value || "").trim() || "synthia-core",
            initialize: true,
            restart_after: Boolean(restartAfter),
          }),
        });
        const applyPayload = await applyRes.json();
        if (!applyRes.ok) {
          throw new Error(applyPayload && applyPayload.detail ? applyPayload.detail : `mqtt_setup_apply_http_${applyRes.status}`);
        }
        if (!applyPayload.ok) {
          const setup = applyPayload && applyPayload.setup ? applyPayload.setup : {};
          const err = setup.setup_error || (applyPayload.external_probe && applyPayload.external_probe.detail) || "setup_apply_failed";
          throw new Error(String(err));
        }

        await Promise.all([loadStatus(), loadSettings()]);
        state.lastAction = { restartAfter };
        await loadSettings();
        setStatus(restartAfter ? "Initialization successful (runtime restart applied)." : "Initialization successful.", "ok");
        if (!state.gateActive && state.currentSection === "setup") {
          navigateTo("overview", true);
        }
      } catch (error) {
        setStatus(`Initialization failed: ${error?.message || String(error)}`, "error");
      } finally {
        setBusy(false);
      }
    }

    async function testExternalConnection() {
      setBusy(true);
      setStatus("Testing external connection...", "");
      try {
        const selectedMode = modeValue();
        if (selectedMode !== "external") {
          state.lastExternalTest = { ok: true, detail: "Local mode does not require external connection test." };
        } else {
          const probeRes = await fetch("/api/system/mqtt/setup/test-connection", {
            method: "POST",
            credentials: "include",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              host: String(host.value || "").trim(),
              port: Number.parseInt(String(port.value || "").trim(), 10),
            }),
          });
          const probePayload = await probeRes.json();
          if (!probeRes.ok) throw new Error(probePayload && probePayload.detail ? probePayload.detail : `mqtt_setup_test_http_${probeRes.status}`);
          const connected = Boolean(probePayload.ok);
          const result = String(probePayload.result || "unreachable");
          state.lastExternalTest = {
            ok: connected,
            detail: connected ? "External broker is reachable." : `External broker test failed (${result}).`,
          };
        }
        renderPreflight();
        setStatus(state.lastExternalTest.detail, state.lastExternalTest.ok ? "ok" : "error");
      } catch (error) {
        state.lastExternalTest = { ok: false, detail: error?.message || String(error) };
        renderPreflight();
        setStatus(`Test failed: ${state.lastExternalTest.detail}`, "error");
      } finally {
        setBusy(false);
      }
    }

    mode.addEventListener("change", () => {
      applyModeClass();
      state.lastExternalTest = null;
      renderPreflight();
    });
    [host, port, username, password, tls, keepalive, clientId].forEach((el) => {
      el.addEventListener("input", () => renderPreflight());
      el.addEventListener("change", () => renderPreflight());
    });
    tabs.addEventListener("click", (event) => {
      const btn = event.target.closest(".tab");
      if (!btn) return;
      const section = btn.getAttribute("data-section");
      if (!section) return;
      navigateTo(section, false);
    });
    sectionContent.addEventListener("click", (event) => {
      const btn = event.target.closest("[data-runtime-action]");
      if (!btn) return;
      const action = btn.getAttribute("data-runtime-action");
      if (!action) return;
      if (action === "debug-subscribe") {
        void runDebugSubscribe();
        return;
      }
      if (action === "debug-unsubscribe") {
        void runDebugUnsubscribe();
        return;
      }
      if (action === "debug-publish") {
        void runDebugPublish();
        return;
      }
      if (action === "view-config") {
        void runRuntimeConfigView();
        return;
      }
      void runRuntimeAction(action);
    });
    sectionContent.addEventListener("click", (event) => {
      const open = event.target.closest("[data-ui-action='open-add-user']");
      if (open) {
        const modal = document.getElementById("create-user-modal");
        if (modal) modal.classList.remove("hidden");
        return;
      }
      const close = event.target.closest("[data-ui-action='close-add-user']");
      if (close) {
        const modal = document.getElementById("create-user-modal");
        if (modal) modal.classList.add("hidden");
        return;
      }
      const submit = event.target.closest("[data-ui-action='submit-add-user']");
      if (submit) {
        void createUserFromModal();
        return;
      }
      const exportUsers = event.target.closest("[data-ui-action='export-users']");
      if (exportUsers) {
        void exportGenericUsers();
        return;
      }
      const importUsers = event.target.closest("[data-ui-action='import-users']");
      if (importUsers) {
        void importGenericUsers();
        return;
      }
      const genericAction = event.target.closest("[data-generic-action]");
      if (genericAction) {
        const action = genericAction.getAttribute("data-generic-action");
        const principalId = genericAction.getAttribute("data-principal-id");
        const topicPrefix = genericAction.getAttribute("data-topic-prefix");
        const accessMode = genericAction.getAttribute("data-access-mode");
        const allowedTopics = String(genericAction.getAttribute("data-allowed-topics") || "")
          .split(",")
          .map((item) => String(item || "").trim())
          .filter((item) => item.length > 0);
        const allowedPublishTopics = String(genericAction.getAttribute("data-allowed-publish-topics") || "")
          .split(",")
          .map((item) => String(item || "").trim())
          .filter((item) => item.length > 0);
        const allowedSubscribeTopics = String(genericAction.getAttribute("data-allowed-subscribe-topics") || "")
          .split(",")
          .map((item) => String(item || "").trim())
          .filter((item) => item.length > 0);
        if (action && principalId) void runGenericUserAction(action, principalId, topicPrefix, accessMode, allowedTopics, allowedPublishTopics, allowedSubscribeTopics);
        return;
      }
      const principalAction = event.target.closest("[data-principal-action]");
      if (principalAction) {
        const action = principalAction.getAttribute("data-principal-action");
        const principalId = principalAction.getAttribute("data-principal-id");
        if (action && principalId) void runPrincipalAction(action, principalId);
        return;
      }
      const noisyAction = event.target.closest("[data-noisy-action]");
      if (noisyAction) {
        const action = noisyAction.getAttribute("data-noisy-action");
        const principalId = noisyAction.getAttribute("data-principal-id");
        if (action && principalId) void runRuntimeNoisyAction(action, principalId);
        return;
      }
      const principalInfo = event.target.closest("[data-principal-info]");
      if (principalInfo) {
        const action = principalInfo.getAttribute("data-principal-info");
        const principalId = principalInfo.getAttribute("data-principal-id");
        if (action && principalId) void runPrincipalInfoAction(action, principalId);
      }
    });
    sectionContent.addEventListener("click", async (event) => {
      const retry = event.target.closest("#section-retry");
      if (!retry) return;
      await renderSectionBody();
    });
    sectionContent.addEventListener("input", (event) => {
      const node = event.target;
      if (!node || !node.getAttribute) return;
      const name = node.getAttribute("data-filter");
      if (!name) return;
      const value = String(node.value || "");
      if (name === "principals-q") state.filters.principals.q = value;
      if (name === "users-q") state.filters.users.q = value;
      if (name === "audit-q") state.filters.audit.q = value;
      if (name === "topics-q") {
        if (!state.filters.topics) state.filters.topics = { q: "" };
        state.filters.topics.q = value;
      }
      if (name === "audit-principal") state.filters.audit.principal = value;
      if (name === "audit-action") state.filters.audit.action = value;
      if (name === "noisy-q") state.filters.noisyClients.q = value;
      void renderSectionBody();
    });
    sectionContent.addEventListener("change", (event) => {
      const node = event.target;
      if (!node || !node.getAttribute) return;
      const name = node.getAttribute("data-filter");
      if (!name) return;
      const value = String(node.value || "");
      if (name === "principals-type") state.filters.principals.type = value;
      if (name === "principals-status") state.filters.principals.status = value;
      if (name === "users-status") state.filters.users.status = value;
      if (name === "audit-status") state.filters.audit.status = value;
      if (name === "noisy-state") state.filters.noisyClients.state = value;
      void renderSectionBody();
    });
    window.addEventListener("popstate", () => {
      state.currentSection = sectionFromPath();
      void renderRoute();
    });
    document.addEventListener("visibilitychange", () => {
      if (!document.hidden) {
        void autoRefreshTick();
      }
    });
    window.addEventListener("beforeunload", () => {
      if (state.autoRefreshHandle) {
        clearInterval(state.autoRefreshHandle);
        state.autoRefreshHandle = null;
      }
    });
    applyBtn.addEventListener("click", () => void applySettings(false));
    applyRestartBtn.addEventListener("click", () => void applySettings(true));
    testConnectionBtn.addEventListener("click", () => void testExternalConnection());
    refreshBtn.addEventListener("click", async () => {
      setStatus("", "");
      try {
        await loadStatus();
      } catch (error) {
        setStatus(`Refresh failed: ${error?.message || String(error)}`, "error");
      }
    });
    retryBtn.addEventListener("click", async () => {
      if (!state.lastAction) return;
      await applySettings(Boolean(state.lastAction.restartAfter));
    });
    recheckBtn.addEventListener("click", async () => {
      setStatus("", "");
      renderPreflight();
      try {
        await loadStatus();
      } catch (error) {
        setStatus(`Re-check failed: ${error?.message || String(error)}`, "error");
      }
    });

    (async () => {
      setBusy(true);
      try {
        state.currentSection = sectionFromPath();
        await Promise.all([loadSettings(), loadStatus()]);
        startAutoRefresh();
        renderPreflight();
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


@router.get("/topics")
async def addon_topics(request: Request, limit: int = 500, format: str | None = None) -> Any:
    # Keep /topics as a UI route by default, but allow JSON for API callers.
    wants_json = str(format or "").strip().lower() == "json" or (
        "application/json" in str(request.headers.get("accept") or "").lower()
    )
    if not wants_json:
        return HTMLResponse(addon_ui_root())
    manager = getattr(request.app.state, "mqtt_manager", None)
    topic_fn = getattr(manager, "topic_activity", None) if manager is not None else None
    if not callable(topic_fn):
        return {"ok": True, "items": []}
    payload = await topic_fn(limit=limit)
    if not isinstance(payload, dict):
        return {"ok": True, "items": []}
    return {"ok": bool(payload.get("ok", True)), "items": list(payload.get("items") or [])}


@router.get("/{path:path}", response_class=HTMLResponse)
def addon_ui_subroute(path: str) -> str:
    return addon_ui_root()


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
