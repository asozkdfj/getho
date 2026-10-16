import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

interface Rule {
  selector: string;
  media: string | null;
  body: string;
  offset: number;
}

/** Flat list of rules with the @media they sit in (enough for this stylesheet). */
function rules(css: string): Rule[] {
  const out: Rule[] = [];
  const stripped = css.replace(/\/\*[\s\S]*?\*\//g, (c) => " ".repeat(c.length));
  const re = /([^{}]+)\{/g;
  const stack: string[] = [];
  let i = 0;
  while (i < stripped.length) {
    re.lastIndex = i;
    const open = re.exec(stripped);
    const close = stripped.indexOf("}", i);
    if (close !== -1 && (!open || close < open.index + open[0].length - 1)) {
      stack.pop();
      i = close + 1;
      continue;
    }
    if (!open) break;
    const selector = open[1]!.trim();
    const start = open.index + open[0].length;
    if (selector.startsWith("@")) {
      stack.push(selector);
      i = start;
      continue;
    }
    const end = stripped.indexOf("}", start);
    out.push({
      selector,
      media: stack.at(-1) ?? null,
      body: stripped.slice(start, end),
      offset: open.index,
    });
    i = end + 1;
  }
  return out;
}

const css = readFileSync(path.join(__dirname, "globals.css"), "utf8");

describe("mobile overrides come after the base rules (QA-08)", () => {
  // Same specificity: the later declaration wins, a media query does not help.
  for (const selector of [".pick-prob-value", ".pick-outcome"]) {
    it(selector, () => {
      const all = rules(css).filter((r) => r.selector === selector && /font-size/.test(r.body));
      const base = all.filter((r) => r.media === null);
      const mobile = all.filter((r) => r.media?.includes("max-width: 520px"));
      expect(base).toHaveLength(1);
      expect(mobile).toHaveLength(1);
      expect(mobile[0]!.offset).toBeGreaterThan(base[0]!.offset);
    });
  }
});
