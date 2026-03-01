import { useEffect, useMemo, useState } from "react";
import "./addon-store.css";

type InstalledInfo = {
  version?: string;
  installed_at?: string;
};

type CatalogItem = {
  id: string;
  name?: string;
  description?: string;
  categories?: string[];
  featured?: boolean;
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
  items: CatalogItem[];
  catalog_status?: CatalogStatus;
  installed?: Record<string, InstalledInfo>;
};

function formatTs(value?: string | null): string {
  if (!value) return "-";
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? value : d.toLocaleString();
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
      setItems(Array.isArray(payload.items) ? payload.items : []);
      setCatalogStatus(payload.catalog_status || {});
      setInstalled(payload.installed || {});
    } catch (e: any) {
      setErr(e?.message ?? String(e));
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
    } catch (e: any) {
      setErr(e?.message ?? String(e));
    } finally {
      setRefreshing(false);
    }
  }

  async function installAddon(addonId: string) {
    setBusyInstall(addonId);
    setErr(null);
    setInstalled((prev) => ({
      ...prev,
      [addonId]: {
        ...(prev[addonId] || {}),
        installed_at: new Date().toISOString(),
      },
    }));
    try {
      const res = await fetch("/api/store/install", {
        method: "POST",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ source_id: "official", addon_id: addonId }),
      });
      if (!res.ok) {
        const text = await res.text();
        throw new Error(`install_http_${res.status}: ${text}`);
      }
      const payload = await res.json();
      setInstalled((prev) => ({
        ...prev,
        [addonId]: {
          version: payload?.version || prev[addonId]?.version,
          installed_at: new Date().toISOString(),
        },
      }));
    } catch (e: any) {
      setErr(e?.message ?? String(e));
      await loadCatalog();
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
        item.name || "",
        item.description || "",
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
            const info = installed[item.id] || {};
            const isBusy = busyInstall === item.id;
            return (
              <div className="store-card" key={item.id}>
                <div className="store-card-head">
                  <div className="store-addon-name">{item.name || item.id}</div>
                  <div className="store-addon-id">{item.id}</div>
                </div>
                {item.description && <div className="store-desc">{item.description}</div>}
                {Array.isArray(item.categories) && item.categories.length > 0 && (
                  <div className="store-meta">categories: {item.categories.join(", ")}</div>
                )}
                <div className="store-meta">installed version: {info.version || "not installed"}</div>
                <div className="store-meta">installed at: {formatTs(info.installed_at)}</div>
                <div className="store-row">
                  <button
                    className="store-btn"
                    disabled={isBusy}
                    onClick={() => installAddon(item.id)}
                  >
                    {isBusy ? "Installing..." : "Install"}
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
