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
    .pill.warn { border-color: #92400e; color: #fde68a; }
    .pill.bad { border-color: #991b1b; color: #fecaca; }
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
    const sections = ["setup", "overview", "principals", "users", "runtime", "audit", "noisy-clients"];
    const state = {
      currentSection: "overview",
      gateActive: false,
      setupSummary: null,
      statusPayload: null,
      lastAction: null,
      lastExternalTest: null,
      runtimeActionStatus: "",
      runtimeActionKind: "",
      sectionCache: {},
      filters: {
        principals: { q: "", type: "", status: "" },
        users: { q: "", status: "" },
        audit: { q: "", status: "" },
        noisyClients: { q: "", state: "" },
      },
    };

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
      return { method: "POST", url: "/api/system/mqtt/runtime/rebuild" };
    }

    async function runRuntimeAction(action) {
      const endpoint = runtimeActionEndpoint(action);
      setRuntimeBusy(true);
      setStatus(`Running runtime action: ${action}...`, "");
      setRuntimeActionStatus("Running...", "");
      try {
        const res = await fetch(endpoint.url, { method: endpoint.method, credentials: "include" });
        const payload = await res.json();
        if (!res.ok) throw new Error(payload && payload.detail ? payload.detail : `${endpoint.url}_http_${res.status}`);
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
      if (!state.gateActive) {
        setupBanner.classList.remove("visible");
        setupBanner.textContent = "";
        return;
      }
      setupBanner.classList.add("visible");
      setupBanner.textContent =
        "Setup required: only the setup page is available until MQTT initialization completes.";
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

    async function loadOverviewPayload() {
      const [principals, noisy, audit] = await Promise.all([
        fetchJson("/api/system/mqtt/principals"),
        fetchJson("/api/system/mqtt/noisy-clients"),
        fetchJson("/api/system/mqtt/audit?limit=20"),
      ]);
      return {
        principals: Array.isArray(principals.items) ? principals.items : [],
        noisy: Array.isArray(noisy.items) ? noisy.items : [],
        audit: Array.isArray(audit.items) ? audit.items : [],
      };
    }

    function filteredPrincipals(items) {
      const q = String(state.filters.principals.q || "").trim().toLowerCase();
      const type = String(state.filters.principals.type || "").trim().toLowerCase();
      const status = String(state.filters.principals.status || "").trim().toLowerCase();
      return items.filter((item) => {
        const pid = String(item.principal_id || "").toLowerCase();
        const ptype = String(item.principal_type || item.type || "").toLowerCase();
        const pstatus = String(item.status || "").toLowerCase();
        if (q && !pid.includes(q)) return false;
        if (type && ptype !== type) return false;
        if (status && pstatus !== status) return false;
        return true;
      });
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
      return items.filter((item) => {
        const action = String(item.event_type || "").toLowerCase();
        const result = String(item.status || "").toLowerCase();
        if (q && !action.includes(q)) return false;
        if (status && result !== status) return false;
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
      if (section === "audit") {
        const audit = await fetchJson("/api/system/mqtt/audit?limit=50");
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
        const degraded = String(effective.status || "").toLowerCase() === "degraded";
        sectionContent.innerHTML =
          (degraded ? `<div class='status error'>MQTT is degraded: ${(effective.reasons || []).map((x) => escapeHtml(x)).join(", ") || "unknown reason"}</div>` : "") +
          `<div>${healthPill(`Authority ${setup.authority_ready ? "ready" : "degraded"}`, setup.authority_ready ? "ok" : "bad")}` +
          `${healthPill(`Runtime ${state.statusPayload && state.statusPayload.connected ? "connected" : "disconnected"}`, state.statusPayload && state.statusPayload.connected ? "ok" : "warn")}` +
          `${healthPill(`Bootstrap ${(state.setupSummary && state.setupSummary.bootstrap_publish && state.setupSummary.bootstrap_publish.published) ? "published" : "pending"}`, (state.setupSummary && state.setupSummary.bootstrap_publish && state.setupSummary.bootstrap_publish.published) ? "ok" : "warn")}` +
          `${healthPill(`Setup ${setup.setup_status || "unknown"}`, statusTone(setup.setup_status || "unknown"))}</div>` +
          renderStats([
            { k: "Principals", v: principals.length },
            { k: "Generic Users", v: genericUsers.length },
            { k: "Noisy", v: noisy.length },
            { k: "Blocked", v: blocked.length },
            { k: "Recent Audit", v: auditItems.length },
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
          `<button data-runtime-action='health'>Check Health</button>` +
          `</div>` +
          `<div id='runtime-action-status' class='${state.runtimeActionKind ? "status " + state.runtimeActionKind : "status"}'>${escapeHtml(state.runtimeActionStatus || "")}</div>` +
          `<div class='mono'>` +
          `last_reconcile_status: ${escapeHtml(recon.last_reconcile_status || "unknown")}\\n` +
          `last_reconcile_reason: ${escapeHtml(recon.last_reconcile_reason || "-")}\\n` +
          `last_runtime_state: ${escapeHtml(recon.last_runtime_state || "unknown")}\\n` +
          `bootstrap_published: ${escapeHtml(bootstrap.published ? "true" : "false")}\\n` +
          `bootstrap_attempts: ${escapeHtml(bootstrap.attempts || 0)}\\n` +
          `bootstrap_last_error: ${escapeHtml(bootstrap.last_error || "none")}` +
          `</div>`;
        return;
      }

      sectionTitle.textContent =
        section === "principals" ? "Principals" : section === "users" ? "Generic Users" : section === "audit" ? "Audit" : "Noisy Clients";
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
            `<select data-filter='principals-type'><option value='' ${state.filters.principals.type === "" ? "selected" : ""}>All types</option><option value='synthia_addon' ${state.filters.principals.type === "synthia_addon" ? "selected" : ""}>Addon</option><option value='synthia_node' ${state.filters.principals.type === "synthia_node" ? "selected" : ""}>Node</option></select>` +
            `<select data-filter='principals-status'><option value='' ${state.filters.principals.status === "" ? "selected" : ""}>All status</option><option value='pending' ${state.filters.principals.status === "pending" ? "selected" : ""}>Pending</option><option value='active' ${state.filters.principals.status === "active" ? "selected" : ""}>Active</option><option value='probation' ${state.filters.principals.status === "probation" ? "selected" : ""}>Probation</option><option value='revoked' ${state.filters.principals.status === "revoked" ? "selected" : ""}>Revoked</option><option value='expired' ${state.filters.principals.status === "expired" ? "selected" : ""}>Expired</option></select>` +
            `</div>`;
          visible = filteredPrincipals(items);
        } else if (section === "users") {
          toolbar =
            `<div class='toolbar'>` +
            `<input data-filter='users-q' placeholder='Search username' value='${escapeHtml(state.filters.users.q)}' />` +
            `<select data-filter='users-status'><option value='' ${state.filters.users.status === "" ? "selected" : ""}>All status</option><option value='active' ${state.filters.users.status === "active" ? "selected" : ""}>Active</option><option value='probation' ${state.filters.users.status === "probation" ? "selected" : ""}>Probation</option><option value='revoked' ${state.filters.users.status === "revoked" ? "selected" : ""}>Revoked</option></select>` +
            `</div>`;
          visible = filteredUsers(items);
        } else if (section === "audit") {
          toolbar =
            `<div class='toolbar'>` +
            `<input data-filter='audit-q' placeholder='Search action' value='${escapeHtml(state.filters.audit.q)}' />` +
            `<select data-filter='audit-status'><option value='' ${state.filters.audit.status === "" ? "selected" : ""}>All results</option><option value='ok' ${state.filters.audit.status === "ok" ? "selected" : ""}>Success</option><option value='error' ${state.filters.audit.status === "error" ? "selected" : ""}>Failure</option><option value='degraded' ${state.filters.audit.status === "degraded" ? "selected" : ""}>Degraded</option><option value='warn' ${state.filters.audit.status === "warn" ? "selected" : ""}>Warning</option></select>` +
            `</div>`;
          visible = filteredAudit(items);
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
          `<table class='table'><thead><tr><th>ID</th><th>Status/Type</th><th>Updated/Reason</th></tr></thead><tbody>${rows}</tbody></table>`;
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
      void runRuntimeAction(action);
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
