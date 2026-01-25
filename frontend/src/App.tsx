import { useRoutes } from "react-router-dom";
import { buildRoutes } from "./core/router/routes";
import Shell from "./core/layout/Shell";

export default function App() {
  const element = useRoutes(buildRoutes());
  return <Shell>{element}</Shell>;
}
