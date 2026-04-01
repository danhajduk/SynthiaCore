import { describe, expect, it } from "vitest";

import { sanitizeNextPath } from "./nextPath";

describe("sanitizeNextPath", () => {
  it("keeps safe in-app paths", () => {
    expect(sanitizeNextPath("/nodes/proxy/node-1/google/gmail/callback?code=abc")).toBe(
      "/nodes/proxy/node-1/google/gmail/callback?code=abc",
    );
  });

  it("rejects absolute and protocol-relative targets", () => {
    expect(sanitizeNextPath("https://example.com")).toBe("/");
    expect(sanitizeNextPath("//example.com/path")).toBe("/");
    expect(sanitizeNextPath("\\\\example.com\\path")).toBe("/");
    expect(sanitizeNextPath("/\\evil")).toBe("/");
  });

  it("defaults empty values to root", () => {
    expect(sanitizeNextPath("")).toBe("/");
    expect(sanitizeNextPath(null)).toBe("/");
  });
});
