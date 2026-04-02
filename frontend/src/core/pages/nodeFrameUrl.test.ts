import { describe, expect, it } from "vitest";
import { nodeUiFrameSrc } from "./nodeFrameUrl";

describe("nodeUiFrameSrc", () => {
  it("returns empty string for empty hostname", () => {
    expect(nodeUiFrameSrc("node-1", "   ", "   ")).toBe("");
  });

  it("uses the Core node proxy when an endpoint exists", () => {
    expect(nodeUiFrameSrc("node-1", "https://node.example.test/ui/", "node.local")).toContain("/nodes/proxy/ui/node-1/");
  });

  it("uses the Core node proxy when only a hostname exists", () => {
    expect(nodeUiFrameSrc("node-1", "", "node.local")).toContain("/nodes/proxy/ui/node-1/");
  });

  it("returns empty string for invalid non-absolute endpoints", () => {
    expect(nodeUiFrameSrc("node-1", "/ui", "node.local")).toBe("");
  });

  it("uses the same origin for managed public tunnel hostnames", () => {
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
    ).toBe("https://a75d480287c33cab.hexe-ai.com/nodes/proxy/ui/node-1/");
  });

  it("keeps the backend port fallback for LAN/default-port access", () => {
    expect(
      nodeUiFrameSrc(
        "node-1",
        "https://node.example.test/ui/",
        "node.local",
        {
          origin: "http://10.0.0.100",
          hostname: "10.0.0.100",
          protocol: "http:",
          port: "",
        },
      ),
    ).toBe("http://10.0.0.100:9001/nodes/proxy/ui/node-1/");
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
    ).toBe("http://127.0.0.1:9001/nodes/proxy/ui/node-1/");
  });
});
