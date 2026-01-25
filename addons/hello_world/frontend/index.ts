import type { RouteObject } from "react-router-dom";
import HelloWorldPage from "./HelloWorldPage";

export const meta = {
  id: "hello_world",
  name: "Hello World",
  basePath: "/addons/hello_world",
};

export const routes: RouteObject[] = [
  { path: meta.basePath, element: <HelloWorldPage /> },
];

export const navItem = {
  label: "Hello World",
  path: meta.basePath,
  icon: "Sparkles",
};
