import { describe, expect, it } from "vitest";

import { nextTheme, THEME_KEY, THEME_SCRIPT } from "./theme";

describe("theme", () => {
  it("cycles system -> light -> dark -> system", () => {
    expect(nextTheme("system")).toBe("light");
    expect(nextTheme("light")).toBe("dark");
    expect(nextTheme("dark")).toBe("system");
  });

  it("the pre-paint script only accepts light or dark from storage", () => {
    expect(THEME_SCRIPT).toContain(THEME_KEY);
    expect(THEME_SCRIPT).toContain('t==="light"||t==="dark"');
    expect(THEME_SCRIPT).toContain("try{");
  });
});
