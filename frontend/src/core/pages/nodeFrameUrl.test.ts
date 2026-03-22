import { describe, expect, it } from "vitest";
import { nodeUiFrameSrc } from "./nodeFrameUrl";

describe("nodeUiFrameSrc", () => {
  it("returns empty string for empty hostname", () => {
    expect(nodeUiFrameSrc("   ", "   ")).toBe("");
  });

  it("prefers the provided absolute endpoint url", () => {
    expect(nodeUiFrameSrc("https://node.example.test/ui/", "node.local")).toBe("https://node.example.test/ui");
  });

  it("adds the browser protocol for bare hostnames when no endpoint is provided", () => {
    expect(nodeUiFrameSrc("", "node.local")).toBe("http://node.local");
  });

  it("returns empty string for invalid non-absolute endpoints", () => {
    expect(nodeUiFrameSrc("/ui", "node.local")).toBe("");
  });
});
