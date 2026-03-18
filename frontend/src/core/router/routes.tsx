import type { ReactElement } from "react";
import type { RouteObject } from "react-router-dom";
import { Navigate } from "react-router-dom";
import Home from "../pages/Home";
import Addons from "../pages/Addons";
import AddonFrame from "../pages/AddonFrame";
import NodeDetails from "../pages/NodeDetails";
import Settings from "../pages/Settings";
import SettingsJobs from "../pages/SettingsJobs";
import SettingsMetrics from "../pages/SettingsMetrics";
import SettingsStatistics from "../pages/SettingsStatistics";
import AddonStorePage from "../../pages/AddonStorePage";
import OnboardingNodeApproval from "../pages/OnboardingNodeApproval";
import { getAddonRoutes } from "./loadAddons";

export function buildRoutes(isAdmin: boolean, ready: boolean): RouteObject[] {
  const addonRoutes = getAddonRoutes();
  const protectedRoute = (element: ReactElement): ReactElement => {
    if (!ready) {
      return <div>Loading...</div>;
    }
    return isAdmin ? element : <Navigate to="/" replace />;
  };

  return [
    { path: "/", element: <Home /> },
    { path: "/store", element: protectedRoute(<AddonStorePage />) },
    { path: "/addons", element: protectedRoute(<Addons />) },
    { path: "/nodes/:nodeId", element: protectedRoute(<NodeDetails />) },
    { path: "/addons/:addonId/:section", element: protectedRoute(<AddonFrame />) },
    { path: "/addons/:addonId", element: protectedRoute(<AddonFrame />) },
    { path: "/onboarding/registrations/approve", element: <OnboardingNodeApproval /> },
    { path: "/onboarding/nodes/approve", element: <OnboardingNodeApproval /> },
    { path: "/settings", element: protectedRoute(<Settings />) },
    { path: "/settings/jobs", element: protectedRoute(<SettingsJobs />) },
    { path: "/settings/metrics", element: protectedRoute(<SettingsMetrics />) },
    { path: "/settings/statistics", element: protectedRoute(<SettingsStatistics />) },
    ...addonRoutes.map((route) => (
      route.element ? { ...route, element: protectedRoute(route.element as ReactElement) } : route
    )),
    { path: "*", element: <Navigate to="/" replace /> },
  ];
}
