import type { RouteObject } from "react-router-dom";
import Home from "../pages/Home";
import Addons from "../pages/Addons";
import Settings from "../pages/Settings";
import SettingsJobs from "../pages/SettingsJobs";
import SettingsMetrics from "../pages/SettingsMetrics";
import SettingsStatistics from "../pages/SettingsStatistics";
import { getAddonRoutes } from "./loadAddons";

export function buildRoutes(): RouteObject[] {
  const addonRoutes = getAddonRoutes();

  return [
    { path: "/", element: <Home /> },
    { path: "/addons", element: <Addons /> },
    { path: "/settings", element: <Settings /> },
    { path: "/settings/jobs", element: <SettingsJobs /> },
    { path: "/settings/metrics", element: <SettingsMetrics /> },
    { path: "/settings/statistics", element: <SettingsStatistics /> },
    ...addonRoutes,
    { path: "*", element: <div>404</div> },
  ];
}
