import { useEffect, useState } from "react";
import { NavLink } from "react-router-dom";
import { apiGet } from "../api/client";
import { loadAddons } from "../router/loadAddons";
import avatarUrl from "../../assets/avatar.png";
import "./sidebar.css";

type AddonInfo = {
  id: string;
  enabled?: boolean;
  show_sidebar?: boolean;
};

const coreItems = [
  { label: "Home", path: "/" },
  { label: "Store", path: "/store" },
  { label: "Addons", path: "/addons" },
  { label: "Settings", path: "/settings" },
  { label: "Settings / Jobs", path: "/settings/jobs" },
  { label: "Settings / Metrics", path: "/settings/metrics" },
  { label: "Settings / Statistics", path: "/settings/statistics" },
];

export default function Sidebar({ isAdmin }: { isAdmin: boolean }) {
  const [backendAddons, setBackendAddons] = useState<AddonInfo[]>([]);

  useEffect(() => {
    let alive = true;

    const load = () => {
      apiGet<AddonInfo[]>("/api/addons")
        .then((data) => {
          if (alive) setBackendAddons(data);
        })
        .catch(() => {
          if (alive) setBackendAddons([]);
        });
    };

    load();
    const id = setInterval(load, 5000);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);

  const backendMap = new Map(backendAddons.map((a) => [a.id, a]));
  const addonItems = loadAddons()
    .filter((mod) => {
      if (!isAdmin) return false;
      const meta = backendMap.get(mod.meta.id);
      if (!meta) return false;
      if (meta.enabled === false) return false;
      if (meta.show_sidebar === false) return false;
      return true;
    })
    .map((mod) => mod.navItem);

  const coreNavItems = isAdmin ? coreItems : [coreItems[0]];

  return (
    <aside className="sidebar">
      <div className="sidebar-avatar">
        <img
          src={avatarUrl}
          alt="Avatar"
          className="sidebar-avatar-img"
        />
      </div>
      <div className="sidebar-title">Navigation</div>
      <nav className="sidebar-nav">
        {coreNavItems.map((it) => (
          <NavLink
            key={it.path}
            to={it.path}
            className={({ isActive }) =>
              `sidebar-link${isActive ? " sidebar-link-active" : ""}`
            }
          >
            {it.label}
          </NavLink>
        ))}
        {isAdmin && addonItems.length > 0 && <div className="sidebar-divider" />}
        {isAdmin && addonItems.map((it) => (
          <NavLink
            key={it.path}
            to={it.path}
            className={({ isActive }) =>
              `sidebar-link${isActive ? " sidebar-link-active" : ""}`
            }
          >
            {it.label}
          </NavLink>
        ))}
      </nav>
      <div className="sidebar-footer">
        {isAdmin ? "Addon links appear after sync." : "Guest mode: only Home is available."}
      </div>
    </aside>
  );
}
