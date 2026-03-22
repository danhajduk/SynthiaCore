import { describe, expect, it } from "vitest";
import { nodeUiFrameSrc } from "./nodeFrameUrl";

describe("nodeUiFrameSrc", () => {
  it("returns empty string for empty hostname", () => {
    expect(nodeUiFrameSrc("node-1", "   ", "   ")).toBe("");
  });

  it("uses the Core node proxy when an endpoint exists", () => {
    expect(nodeUiFrameSrc("node-1", "https://node.example.test/ui/", "node.local")).toContain("/nodes/node-1/ui/");
  });

  it("uses the Core node proxy when only a hostname exists", () => {
    expect(nodeUiFrameSrc("node-1", "", "node.local")).toContain("/nodes/node-1/ui/");
  });

  it("returns empty string for invalid non-absolute endpoints", () => {
    expect(nodeUiFrameSrc("node-1", "/ui", "node.local")).toBe("");
  });

  it("uses the same origin for tunneled or default-port deployments", () => {
    expect(
      nodeUiFrameSrc(
        "node-1",
        "https://node.example.test/ui/",
        "node.local",
        {
          origin: "https://a75d480287c33cab.hexe-ai.com",
          hostname: "a75d480287c33cab.hexe-ai.com",
          protocol: "https:",
          port: "",
        },
      ),
    ).toBe("https://a75d480287c33cab.hexe-ai.com/nodes/node-1/ui/");
  });

  it("keeps the backend port fallback for frontend dev servers", () => {
    expect(
      nodeUiFrameSrc(
        "node-1",
        "https://node.example.test/ui/",
        "node.local",
        {
          origin: "http://127.0.0.1:5173",
          hostname: "127.0.0.1",
          protocol: "http:",
          port: "5173",
        },
      ),
    ).toBe("http://127.0.0.1:9001/nodes/node-1/ui/");
  });
});
