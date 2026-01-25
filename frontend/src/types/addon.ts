import type { RouteObject } from "react-router-dom";

export type AddonMeta = {
  id: string;
  name: string;
  basePath: string;
};

export type AddonNavItem = {
  label: string;
  path: string;
  icon?: string;
};

export type FrontendAddonModule = {
  meta: AddonMeta;
  routes: RouteObject[];
  navItem: AddonNavItem;
};
