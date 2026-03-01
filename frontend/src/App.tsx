import { useRoutes } from "react-router-dom";
import { buildRoutes } from "./core/router/routes";
import Shell from "./core/layout/Shell";
import { AdminSessionProvider, useAdminSession } from "./core/auth/AdminSessionContext";

function AppLayout() {
  const { ready, authenticated } = useAdminSession();
  const element = useRoutes(buildRoutes(authenticated, ready));
  return <Shell isAdmin={authenticated}>{element}</Shell>;
}

export default function App() {
  return (
    <AdminSessionProvider>
      <AppLayout />
    </AdminSessionProvider>
  );
}
