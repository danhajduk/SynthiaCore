import { useLocation, useRoutes } from "react-router-dom";
import { buildRoutes } from "./core/router/routes";
import Shell from "./core/layout/Shell";
import { AdminSessionProvider, useAdminSession } from "./core/auth/AdminSessionContext";
import { PlatformBrandingProvider } from "./core/branding";

function AppLayout() {
  const { ready, authenticated } = useAdminSession();
  const location = useLocation();
  const element = useRoutes(buildRoutes(authenticated, ready));
  const chromeless =
    location.pathname === "/onboarding/registrations/approve" ||
    location.pathname === "/onboarding/nodes/approve" ||
    location.pathname === "/proxy-login";
  return (
    <Shell isAdmin={authenticated} chromeless={chromeless}>
      {element}
    </Shell>
  );
}

export default function App() {
  return (
    <PlatformBrandingProvider>
      <AdminSessionProvider>
        <AppLayout />
      </AdminSessionProvider>
    </PlatformBrandingProvider>
  );
}
