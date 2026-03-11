import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { Cpu } from "lucide-react";

import { HOME_STATUS_TILE_TITLES, StatusMini } from "./Home";

describe("home status tiles", () => {
  it("renders icon + label contract for status mini tile", () => {
    const html = renderToStaticMarkup(<StatusMini title="Core" icon={Cpu} tone="ok" />);
    expect(html).toContain("home-mini-icon");
    expect(html).toContain("home-mini-title");
    expect(html).toContain("Core");
  });

  it("exposes expected tile labels including AI Node", () => {
    expect(Array.from(HOME_STATUS_TILE_TITLES)).toEqual([
      "Core",
      "Supervisor",
      "MQTT",
      "Scheduler",
      "Workers",
      "Addons",
      "Network",
      "Internet",
      "AI Node",
    ]);
  });
});
