import { useEffect, useState } from "react";
import { NavLink } from "react-router-dom";
import { apiGet } from "../api/client";
import { loadAddons } from "../router/loadAddons";
import avatarUrl from "../../assets/avatar.png";

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
      const meta = backendMap.get(mod.meta.id);
      if (!meta) return false;
      if (meta.enabled === false) return false;
      if (meta.show_sidebar === false) return false;
      return true;
    })
    .map((mod) => mod.navItem);

  const items = [...coreItems, ...addonItems];

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
        {coreItems.map((it) => (
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
        <div className="sidebar-divider" />
        {addonItems.map((it) => (
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
        Addon links appear after sync.
      </div>
    </aside>
  );
}
