import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { applyTheme, nextTheme, readTheme, subscribeTheme, THEME_KEY, THEME_SCRIPT } from "./theme";

/** Minimal window/document stand-ins (the test environment is node). */
function fakeBrowser() {
  const attrs: Record<string, string> = {};
  const data: Record<string, string> = {};
  const handlers: Record<string, (e: { key: string | null }) => void> = {};
  const storage = {
    getItem: (k: string): string | null => data[k] ?? null,
    setItem: (k: string, v: string) => {
      data[k] = v;
    },
    removeItem: (k: string) => {
      delete data[k];
    },
  };
  const g = globalThis as Record<string, unknown>;
  g.document = {
    documentElement: {
      getAttribute: (k: string) => attrs[k] ?? null,
      setAttribute: (k: string, v: string) => {
        attrs[k] = v;
      },
      removeAttribute: (k: string) => {
        delete attrs[k];
      },
    },
  };
  g.window = {
    localStorage: storage,
    addEventListener: (name: string, fn: (e: { key: string | null }) => void) => {
      handlers[name] = fn;
    },
    removeEventListener: (name: string) => {
      delete handlers[name];
    },
  };
  return { attrs, data, handlers, storage };
}

describe("theme", () => {
  let browser: ReturnType<typeof fakeBrowser>;
  beforeEach(() => {
    browser = fakeBrowser();
  });
  afterEach(() => {
    delete (globalThis as Record<string, unknown>).window;
    delete (globalThis as Record<string, unknown>).document;
  });

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

  it("a change in another tab is applied to this page (THEME-1)", () => {
    let notified = 0;
    const unsubscribe = subscribeTheme(() => {
      notified += 1;
    });
    applyTheme("light");
    browser.data[THEME_KEY] = "dark"; // the other tab wrote this
    browser.handlers.storage!({ key: THEME_KEY });
    expect(readTheme()).toBe("dark");
    expect(browser.attrs["data-theme"]).toBe("dark");
    delete browser.data[THEME_KEY]; // back to system in the other tab
    browser.handlers.storage!({ key: THEME_KEY });
    expect(browser.attrs["data-theme"]).toBeUndefined();
    browser.handlers.storage!({ key: "something-else" });
    expect(notified).toBe(3); // applyTheme + two theme storage events
    unsubscribe();
    expect(browser.handlers.storage).toBeUndefined();
  });

  it("keeps cycling when storage is blocked (THEME-2)", () => {
    const blocked = () => {
      throw new Error("blocked");
    };
    browser.storage.getItem = blocked;
    browser.storage.setItem = blocked;
    browser.storage.removeItem = blocked;
    const seen = [];
    for (let i = 0; i < 3; i += 1) {
      applyTheme(nextTheme(readTheme()));
      seen.push(readTheme());
    }
    expect(seen).toEqual(["light", "dark", "system"]);
  });
});
