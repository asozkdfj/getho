import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

// The fixture page is an async server component (it fetches from the API), so
// these guards check its source; the warning logic itself is unit-tested in
// lib/picks.test.ts (qualityWarnings).
const source = readFileSync(path.join(__dirname, "fixtures/[id]/page.tsx"), "utf8");

describe("fixture page shows failed data checks (QA-05)", () => {
  it("derives the warnings from the prediction's quality report and status", () => {
    expect(source).toMatch(/qualityWarnings\(prediction\?\.quality, fixture\.status\)/);
  });

  it("renders them in the summary", () => {
    expect(source).toMatch(/warnings\.length > 0 &&/);
    expect(source).toMatch(/\{warnings\.join\(", "\)\}/);
  });
});
