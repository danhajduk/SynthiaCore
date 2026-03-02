import { useEffect, useMemo, useState } from "react";
import "./addon-store.css";
import { installActionItems, parseInstallFailure, type InstallErrorDetail } from "./addonStoreErrorUtils";

type InstalledInfo = {
  version?: string;
  installed_at?: string;
};

type RawCatalogItem = {
  id?: unknown;
  name?: unknown;
  description?: unknown;
  categories?: unknown;
  featured?: unknown;
  version?: unknown;
  published_at?: unknown;
  publisher_id?: unknown;
  publisher_display_name?: unknown;
  releases?: unknown;
  release_count?: unknown;
  channels?: unknown;
};

type CatalogItem = {
  id: string;
  addonId: string | null;
  name: string;
  description: string;
  categories: string[];
  featured: boolean;
  version: string;
  publishedAt: string | null;
  publisherId: string | null;
  publisherDisplayName: string | null;
  releaseCount: number;
};

type CatalogStatus = {
  status?: string;
  source_id?: string;
  last_success_at?: string | null;
  last_error_at?: string | null;
  last_error_message?: string | null;
};

type CatalogResponse = {
  ok: boolean;
  items: RawCatalogItem[];
  catalog_status?: CatalogStatus;
  installed?: Record<string, InstalledInfo>;
};

function formatTs(value?: string | null): string {
  if (!value) return "-";
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? value : d.toLocaleString();
}

function asString(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : null;
}

function asStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value
    .map((entry) => asString(entry))
    .filter((entry): entry is string => Boolean(entry));
}

function asReleaseArray(value: unknown): Array<Record<string, unknown>> {
  if (!Array.isArray(value)) return [];
  return value.filter((entry): entry is Record<string, unknown> => typeof entry === "object" && entry !== null);
}

function asNonNegativeInt(value: unknown): number | null {
  if (typeof value !== "number" || !Number.isFinite(value)) return null;
  return Math.max(0, Math.trunc(value));
}

function channelReleases(channels: unknown): Array<Record<string, unknown>> {
  if (!channels || typeof channels !== "object") return [];
  const obj = channels as Record<string, unknown>;
  const preferred = ["stable", "beta", "nightly"];
  const remaining = Object.keys(obj).filter((name) => !preferred.includes(name)).sort();
  const names = [...preferred, ...remaining];
  const out: Array<Record<string, unknown>> = [];

  for (const name of names) {
    const rawChannel = obj[name];
    if (Array.isArray(rawChannel)) {
      out.push(
        ...rawChannel.filter((entry): entry is Record<string, unknown> => typeof entry === "object" && entry !== null),
      );
      continue;
    }
    if (!rawChannel || typeof rawChannel !== "object") {
      continue;
    }
    const wrapped = (rawChannel as Record<string, unknown>).releases;
    if (Array.isArray(wrapped)) {
      out.push(
        ...wrapped.filter((entry): entry is Record<string, unknown> => typeof entry === "object" && entry !== null),
      );
      continue;
    }
    const maybeRelease = rawChannel as Record<string, unknown>;
    if (typeof maybeRelease.version === "string" && maybeRelease.version.trim()) {
      out.push(maybeRelease);
    }
  }

  return out;
}

function normalizeCatalogItem(item: RawCatalogItem, index: number): CatalogItem {
  const addonId = asString(item.id);
  const fallbackId = `unknown-${index + 1}`;
  const releases = asReleaseArray(item.releases);
  const releasesFromChannels = channelReleases(item.channels);
  const effectiveReleases = releases.length > 0 ? releases : releasesFromChannels;
  const releaseCount = asNonNegativeInt(item.release_count);
  const latestRelease = effectiveReleases[0] || {};
  const version =
    asString(item.version) ||
    asString(latestRelease.version) ||
    asString(latestRelease.tag_name) ||
    "unknown";

  return {
    id: addonId || fallbackId,
    addonId,
    name: asString(item.name) || addonId || fallbackId,
    description: asString(item.description) || "No description provided.",
    categories: asStringArray(item.categories),
    featured: Boolean(item.featured),
    version,
    publishedAt: asString(item.published_at),
    publisherId: asString(item.publisher_id),
    publisherDisplayName: asString(item.publisher_display_name),
    releaseCount: releaseCount ?? effectiveReleases.length,
  };
}

export default function AddonStorePage() {
  const [items, setItems] = useState<CatalogItem[]>([]);
  const [installed, setInstalled] = useState<Record<string, InstalledInfo>>({});
  const [catalogStatus, setCatalogStatus] = useState<CatalogStatus>({});
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [busyInstall, setBusyInstall] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [installErrorDetail, setInstallErrorDetail] = useState<InstallErrorDetail | null>(null);

  async function loadCatalog() {
    setLoading(true);
    setErr(null);
    setInstallErrorDetail(null);
    try {
      const res = await fetch("/api/store/catalog?source_id=official");
      if (!res.ok) throw new Error(`catalog_http_${res.status}`);
      const payload = (await res.json()) as CatalogResponse;
      const normalized = Array.isArray(payload.items)
        ? payload.items.map((item, index) => normalizeCatalogItem(item || {}, index))
        : [];
      setItems(normalized);
      setCatalogStatus(payload.catalog_status || {});
      setInstalled(payload.installed || {});
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadCatalog();
  }, []);

  async function refreshCatalog() {
    setRefreshing(true);
    setErr(null);
    setInstallErrorDetail(null);
    try {
      const res = await fetch("/api/store/sources/official/refresh", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
      });
      if (!res.ok) {
        const text = await res.text();
        throw new Error(`refresh_http_${res.status}: ${text}`);
      }
      await loadCatalog();
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setRefreshing(false);
    }
  }

  async function installAddon(item: CatalogItem) {
    if (!item.addonId) {
      setErr("install_unavailable_missing_addon_id");
      return;
    }

    setBusyInstall(item.id);
    setErr(null);
    setInstallErrorDetail(null);
    try {
      const res = await fetch("/api/store/install", {
        method: "POST",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ source_id: "official", addon_id: item.addonId }),
      });
      if (!res.ok) {
        const text = await res.text();
        const parsed = parseInstallFailure(res.status, text);
        setInstallErrorDetail(parsed.detail);
        throw new Error(parsed.message);
      }
      await loadCatalog();
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusyInstall(null);
    }
  }

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return items;
    return items.filter((item) => {
      const haystack = [
        item.id,
        item.name,
        item.description,
        item.publisherDisplayName || "",
        item.publisherId || "",
        ...(item.categories || []),
      ]
        .join(" ")
        .toLowerCase();
      return haystack.includes(q);
    });
  }, [items, query]);

  const installActions = useMemo(() => installActionItems(installErrorDetail), [installErrorDetail]);

  return (
    <div className="store-page">
      <div className="store-head">
        <h1 className="store-title">Addon Store</h1>
        <div className="store-actions">
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search addons"
            className="store-search"
          />
          <button onClick={refreshCatalog} disabled={refreshing || loading} className="store-btn">
            {refreshing ? "Refreshing..." : "Refresh"}
          </button>
        </div>
      </div>

      <div className="store-status-card">
        <div className="store-status-line">
          <strong>Status:</strong> {catalogStatus.status || "unknown"}
        </div>
        <div className="store-status-line">
          <strong>Source:</strong> {catalogStatus.source_id || "official"}
        </div>
        <div className="store-status-line">
          <strong>Last success:</strong> {formatTs(catalogStatus.last_success_at)}
        </div>
        <div className="store-status-line">
          <strong>Last error:</strong> {formatTs(catalogStatus.last_error_at)}
        </div>
        {!!catalogStatus.last_error_message && (
          <div className="store-error-inline">{catalogStatus.last_error_message}</div>
        )}
      </div>

      {err && <div className="store-error-inline">{err}</div>}
      {installActions.length > 0 && (
        <div className="store-error-actions">
          <div className="store-error-actions-title">Recommended actions</div>
          {installActions.map((action) => (
            <div className="store-error-action-card" key={action}>
              {action}
            </div>
          ))}
        </div>
      )}
      {installErrorDetail && (
        <details className="store-diag">
          <summary>Install diagnostics</summary>
          <div className="store-diag-line">
            <strong>error:</strong> {installErrorDetail.error || installErrorDetail.code || "unknown"}
          </div>
          {installErrorDetail.remediation_path && (
            <div className="store-diag-line">
              <strong>remediation_path:</strong> {installErrorDetail.remediation_path}
            </div>
          )}
          {installErrorDetail.catalog_release_package_profile && (
            <div className="store-diag-line">
              <strong>catalog_release_package_profile:</strong> {installErrorDetail.catalog_release_package_profile}
            </div>
          )}
          {installErrorDetail.layout_hint && (
            <div className="store-diag-line">
              <strong>layout_hint:</strong> {installErrorDetail.layout_hint}
            </div>
          )}
          {installErrorDetail.catalog_release_version && (
            <div className="store-diag-line">
              <strong>catalog_release_version:</strong> {installErrorDetail.catalog_release_version}
            </div>
          )}
          {installErrorDetail.source_id && (
            <div className="store-diag-line">
              <strong>source_id:</strong> {installErrorDetail.source_id}
            </div>
          )}
          {installErrorDetail.artifact_url && (
            <div className="store-diag-line">
              <strong>artifact_url:</strong> {installErrorDetail.artifact_url}
            </div>
          )}
          {installErrorDetail.hint && (
            <div className="store-diag-line">
              <strong>hint:</strong> {installErrorDetail.hint}
            </div>
          )}
        </details>
      )}

      {loading ? (
        <div className="store-empty">Loading catalog...</div>
      ) : filtered.length === 0 ? (
        <div className="store-empty">No addons found.</div>
      ) : (
        <div className="store-grid">
          {filtered.map((item) => {
            const info = item.addonId ? installed[item.addonId] || {} : {};
            const isBusy = busyInstall === item.id;
            const installable = Boolean(item.addonId);
            return (
              <div className="store-card" key={item.id}>
                <div className="store-card-head">
                  <div className="store-addon-name">{item.name}</div>
                  <div className="store-addon-id">{item.id}</div>
                </div>
                <div className="store-desc">{item.description}</div>
                {item.categories.length > 0 && (
                  <div className="store-meta">categories: {item.categories.join(", ")}</div>
                )}
                <div className="store-meta">current version: {item.version}</div>
                <div className="store-meta">installed version: {info.version || "not installed"}</div>
                <div className="store-meta">installed at: {formatTs(info.installed_at)}</div>
                <div className="store-meta">published at: {formatTs(item.publishedAt)}</div>
                <div className="store-meta">
                  publisher:{" "}
                  {item.publisherDisplayName
                    ? item.publisherDisplayName
                    : item.publisherId || "unknown"}
                </div>
                <div className="store-meta">releases: {item.releaseCount}</div>
                {item.featured && <div className="store-meta">featured: yes</div>}
                <div className="store-row">
                  <button
                    className="store-btn"
                    disabled={isBusy || !installable}
                    onClick={() => installAddon(item)}
                  >
                    {isBusy ? "Installing..." : installable ? "Install" : "Install unavailable"}
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
