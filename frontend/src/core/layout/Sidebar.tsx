import { useEffect, useState } from "react";
import { NavLink } from "react-router-dom";
import { apiGet } from "../api/client";
import { loadAddons } from "../router/loadAddons";

type AddonInfo = {
  id: string;
  enabled?: boolean;
  show_sidebar?: boolean;
};

const coreItems = [
  { label: "Home", path: "/" },
  { label: "Addons", path: "/addons" },
  { label: "Settings", path: "/settings" },
];

export default function Sidebar() {
  const [backendAddons, setBackendAddons] = useState<AddonInfo[]>([]);

  useEffect(() => {
    apiGet<AddonInfo[]>("/api/addons")
      .then(setBackendAddons)
      .catch(() => setBackendAddons([]));
  }, []);

  const backendMap = new Map(backendAddons.map((a) => [a.id, a]));
  const addonItems = loadAddons()
    .filter((mod) => {
      const meta = backendMap.get(mod.meta.id);
      if (!meta) return false;
      if (meta.enabled === false) return false;
      if (meta.show_sidebar === false) return false;
      return true;
    })
    .map((mod) => mod.navItem);

  const items = [...coreItems, ...addonItems];

  return (
    <aside
      style={{
        borderRight: "1px solid rgba(255,255,255,0.08)",
        padding: 12,
        background: "linear-gradient(180deg, rgba(50,50,70,0.35), rgba(10,10,20,0.35))",
      }}
    >
      <div style={{ fontWeight: 800, marginBottom: 12 }}>Navigation</div>
      <nav style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        {items.map((it) => (
          <NavLink
            key={it.path}
            to={it.path}
            style={({ isActive }) => ({
              padding: "10px 12px",
              borderRadius: 10,
              textDecoration: "none",
              color: "white",
              background: isActive ? "rgba(255,255,255,0.12)" : "transparent",
            })}
          >
            {it.label}
          </NavLink>
        ))}
      </nav>
      <div style={{ marginTop: 16, fontSize: 12, opacity: 0.7 }}>
        Addon links appear after sync.
      </div>
    </aside>
  );
}
