import type { ReactElement } from "react";
import type { RouteObject } from "react-router-dom";
import { Navigate, useLocation } from "react-router-dom";
import Home from "../pages/Home";
import Addons from "../pages/Addons";
import AddonFrame from "../pages/AddonFrame";
import NodeDetails from "../pages/NodeDetails";
import NodeFrame from "../pages/NodeFrame";
import ProxyLogin from "../pages/ProxyLogin";
import Settings from "../pages/Settings";
import EdgeGateway from "../pages/EdgeGateway";
import SettingsMetrics from "../pages/SettingsMetrics";
import SettingsSupervisor from "../pages/SettingsSupervisor";
import SettingsScheduler from "../pages/SettingsScheduler";
import AddonStorePage from "../../pages/AddonStorePage";
import OnboardingNodeApproval from "../pages/OnboardingNodeApproval";
import { getAddonRoutes } from "./loadAddons";

function ProtectedRedirect() {
  const location = useLocation();
  const next = `${location.pathname}${location.search}${location.hash}`;
  return <Navigate to={`/?next=${encodeURIComponent(next)}`} replace />;
}

export function buildRoutes(isAdmin: boolean, ready: boolean): RouteObject[] {
  const addonRoutes = getAddonRoutes();
  const protectedRoute = (element: ReactElement): ReactElement => {
    if (!ready) {
      return <div>Loading...</div>;
    }
    return isAdmin ? element : <ProtectedRedirect />;
  };

  return [
    { path: "/", element: <Home /> },
    { path: "/proxy-login", element: <ProxyLogin /> },
    { path: "/store", element: protectedRoute(<AddonStorePage />) },
    { path: "/addons", element: protectedRoute(<Addons />) },
    { path: "/nodes/:nodeId/UI", element: protectedRoute(<NodeFrame />) },
    { path: "/nodes/:nodeId", element: protectedRoute(<NodeDetails />) },
    { path: "/addons/:addonId/:section", element: protectedRoute(<AddonFrame />) },
    { path: "/addons/:addonId", element: protectedRoute(<AddonFrame />) },
    { path: "/onboarding/registrations/approve", element: <OnboardingNodeApproval /> },
    { path: "/onboarding/nodes/approve", element: <OnboardingNodeApproval /> },
    { path: "/settings", element: protectedRoute(<Settings />) },
    { path: "/settings/edge", element: protectedRoute(<EdgeGateway />) },
    { path: "/settings/metrics", element: protectedRoute(<SettingsMetrics />) },
    { path: "/settings/supervisor", element: protectedRoute(<SettingsSupervisor />) },
    { path: "/settings/scheduler", element: protectedRoute(<SettingsScheduler />) },
    ...addonRoutes.map((route) => (
      route.element ? { ...route, element: protectedRoute(route.element as ReactElement) } : route
    )),
    { path: "*", element: <Navigate to="/" replace /> },
  ];
}
