import type { RouteObject } from "react-router-dom";
import Home from "../pages/Home";
import Addons from "../pages/Addons";
import Settings from "../pages/Settings";
import { getAddonRoutes } from "./loadAddons";

export function buildRoutes(): RouteObject[] {
  const addonRoutes = getAddonRoutes();

  return [
    { path: "/", element: <Home /> },
    { path: "/addons", element: <Addons /> },
    { path: "/settings", element: <Settings /> },
    ...addonRoutes,
    { path: "*", element: <div>404</div> },
  ];
}
