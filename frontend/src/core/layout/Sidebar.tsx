import { NavLink } from "react-router-dom";
import { getNavItems } from "../router/loadAddons";

const coreItems = [
  { label: "Home", path: "/" },
  { label: "Addons", path: "/addons" },
  { label: "Settings", path: "/settings" },
];

export default function Sidebar() {
  const addonItems = getNavItems();

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
