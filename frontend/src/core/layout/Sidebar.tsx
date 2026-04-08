import { useEffect, useState } from "react";
import { NavLink } from "react-router-dom";
import { apiGet } from "../api/client";
import { usePlatformBranding } from "../branding";
import { loadAddons } from "../router/loadAddons";
import avatarUrl from "../../assets/avatar.png";
import "./sidebar.css";

type AddonInfo = {
  id: string;
  enabled?: boolean;
  show_sidebar?: boolean;
};

type NavItem = {
  label: string;
  path: string;
};

type NavSection = {
  title: string;
  items: NavItem[];
};

const homeItems: NavItem[] = [{ label: "Home", path: "/" }];
const addonItemsCore: NavItem[] = [
  { label: "Addons", path: "/addons" },
];
const storeItems: NavItem[] = [{ label: "Store", path: "/store" }];
const systemItems: NavItem[] = [
  { label: "Settings", path: "/settings" },
  { label: "Supervisor", path: "/settings/supervisor" },
  { label: "Edge Gateway", path: "/settings/edge" },
  { label: "Scheduler Jobs", path: "/settings/jobs" },
  { label: "System Metrics", path: "/settings/metrics" },
  { label: "Job Statistics", path: "/settings/statistics" },
];

export default function Sidebar({ isAdmin }: { isAdmin: boolean }) {
  const branding = usePlatformBranding();
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
  const dynamicAddonItems = loadAddons()
    .filter((mod) => {
      if (!isAdmin) return false;
      const meta = backendMap.get(mod.meta.id);
      if (!meta) return false;
      if (meta.enabled === false) return false;
      if (meta.show_sidebar === false) return false;
      return true;
    })
    .map((mod) => mod.navItem);

  const sections: NavSection[] = isAdmin
    ? [
        { title: "Home", items: homeItems },
        { title: branding.addonsName, items: addonItemsCore.map((item) => ({ ...item, label: `${branding.addonsName} & ${branding.nodesName}` })) },
        { title: "Store", items: storeItems },
        { title: "System", items: systemItems },
        { title: `${branding.addonsName} UIs`, items: dynamicAddonItems },
      ].filter((section) => section.items.length > 0)
    : [{ title: "Home", items: homeItems }];

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
        {sections.map((section) => (
          <div key={section.title} className="sidebar-section">
            <div className="sidebar-section-title">{section.title}</div>
            <div className="sidebar-section-items">
              {section.items.map((it) => (
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
            </div>
          </div>
        ))}
      </nav>
      <div className="sidebar-footer">
        {isAdmin ? "Admin mode enabled." : `Guest mode: Home only. Sign in for ${branding.addonsName}, Store, and System routes.`}
      </div>
    </aside>
  );
}
