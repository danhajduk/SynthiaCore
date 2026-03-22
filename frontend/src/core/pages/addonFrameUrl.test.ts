import { describe, expect, it } from "vitest";
import { addonUiFrameSrc } from "./addonFrameUrl";

describe("addonUiFrameSrc", () => {
  it("uses provided backend base override", () => {
    expect(addonUiFrameSrc("mqtt", "http://10.0.0.100:9001/")).toBe("http://10.0.0.100:9001/ui/addons/mqtt");
  });

  it("encodes addon id", () => {
    expect(addonUiFrameSrc("hello world", "http://127.0.0.1:9001")).toBe("http://127.0.0.1:9001/ui/addons/hello%20world");
  });

  it("returns empty string for empty addon id", () => {
    expect(addonUiFrameSrc("   ", "http://127.0.0.1:9001")).toBe("");
  });

  it("defaults to the backend proxy origin when no override is provided", () => {
    expect(addonUiFrameSrc("mqtt")).toContain("/ui/addons/mqtt");
  });
});
