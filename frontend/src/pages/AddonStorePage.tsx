import { useEffect, useMemo, useState } from "react";
import "./addon-store.css";

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
  releases?: unknown;
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

function normalizeCatalogItem(item: RawCatalogItem, index: number): CatalogItem {
  const addonId = asString(item.id);
  const fallbackId = `unknown-${index + 1}`;
  const releases = Array.isArray(item.releases)
    ? (item.releases as Array<Record<string, unknown>>)
    : [];
  const latestRelease = releases[0] || {};
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
    releaseCount: releases.length,
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

  async function loadCatalog() {
    setLoading(true);
    setErr(null);
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
        throw new Error(`install_http_${res.status}: ${text}`);
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
        item.publisherId || "",
        ...(item.categories || []),
      ]
        .join(" ")
        .toLowerCase();
      return haystack.includes(q);
    });
  }, [items, query]);

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
                <div className="store-meta">publisher: {item.publisherId || "unknown"}</div>
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
