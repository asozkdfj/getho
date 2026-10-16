import { describe, expect, it } from "vitest";

import { isActivePath } from "./nav";

describe("active menu item", () => {
  it("treats fixture pages as part of the match list", () => {
    expect(isActivePath("/", "/")).toBe(true);
    expect(isActivePath("/fixtures/12", "/")).toBe(true);
    expect(isActivePath("/leagues", "/")).toBe(false);
  });

  it("matches a section and its sub-pages only", () => {
    expect(isActivePath("/leagues/3", "/leagues")).toBe(true);
    expect(isActivePath("/picks", "/picks")).toBe(true);
    expect(isActivePath("/picksx", "/picks")).toBe(false);
  });
});
