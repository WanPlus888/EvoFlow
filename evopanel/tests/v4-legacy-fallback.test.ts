import { describe, expect, it } from "vitest";
import { shouldRenderLegacyRows } from "../src/react/v4/V4StreamRowsBridge";

describe("V4 legacy rendering fallback", () => {
  it("keeps legacy rows visible while V4 is connecting", () => {
    expect(shouldRenderLegacyRows("connecting", false)).toBe(true);
  });

  it("keeps legacy rows visible when V4 is disabled", () => {
    expect(shouldRenderLegacyRows("disabled", false)).toBe(true);
    expect(shouldRenderLegacyRows("no-thread", false)).toBe(true);
  });

  it("keeps legacy rows visible on home surface", () => {
    expect(shouldRenderLegacyRows("ready", true)).toBe(true);
  });

  it("hands off only after a real V4 snapshot is ready", () => {
    expect(shouldRenderLegacyRows("ready", false)).toBe(false);
  });
});
