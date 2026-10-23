import type { FixtureSummary } from "@edge/contracts";
import { isValidElement, type ReactNode } from "react";
import { beforeEach, expect, it, vi } from "vitest";
import { TEST_LEAGUE } from "@/lib/testing";
import { MatchPicker } from "./MatchPicker";

// Component event-handler harness; not a DOM, browser or accessibility test.
const state = vi.hoisted(() => ({ values: [] as unknown[], cursor: 0 }));
vi.mock("react", async (original) => ({
  ...(await original<typeof import("react")>()),
  useMemo: (fn: () => unknown) => fn(),
  useState: (initial: unknown) => {
    const i = state.cursor++;
    if (!(i in state.values)) state.values[i] = typeof initial === "function" ? initial() : initial;
    return [state.values[i], (next: unknown) => {
      state.values[i] = typeof next === "function" ? next(state.values[i]) : next;
    }];
  },
}));

function nodes(root: ReactNode): Array<{ type: unknown; props: Record<string, unknown> }> {
  if (Array.isArray(root)) return root.flatMap(nodes);
  if (!isValidElement<Record<string, unknown>>(root)) return [];
  return [root, ...nodes(root.props.children as ReactNode)];
}
const fixtures = [{
  id: 1, league: TEST_LEAGUE, kickoff_at: "2026-10-23T12:00:00Z", status: "scheduled",
  home_team: { id: 1, name: "Arsenal", short_name: "ARS" },
  away_team: { id: 2, name: "Chelsea", short_name: "CHE" },
}] as FixtureSummary[];
function render(onChange = vi.fn()) {
  state.cursor = 0;
  return nodes(MatchPicker({ fixtures, tz: "Asia/Seoul", value: null, onChange }));
}
beforeEach(() => { state.values = []; });

it("search opens matching league even if it was collapsed before search", () => {
  let tree = render();
  const header = tree.find(n => "aria-expanded" in n.props)!;
  expect(header.props["aria-expanded"]).toBe(true);
  (header.props.onClick as () => void)();
  tree = render();
  expect(tree.find(n => "aria-expanded" in n.props)!.props["aria-expanded"]).toBe(false);
  const search = tree.find(n => n.props.type === "search")!.props.onChange as
    (e: {target: {value: string}}) => void;
  search({target:{value:"Arsenal"}});
  tree = render();
  expect(tree.find(n => "aria-expanded" in n.props)!.props["aria-expanded"]).toBe(true);
});

it("away button preserves the fixture id and outcome", () => {
  const choose = vi.fn();
  const tree = render(choose);
  const group = tree.find(n => n.props["aria-label"] === "Arsenal 대 Chelsea 선택")!;
  const buttons = nodes(group.props.children as ReactNode).filter(n => n.type === "button");
  (buttons[2]!.props.onClick as () => void)();
  expect(choose).toHaveBeenCalledWith({ fixtureId: 1, selection: "AWAY" });
});
