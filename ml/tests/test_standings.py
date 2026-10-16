from datetime import UTC, datetime, timedelta

import pytest

from edge_ml.core import MatchResult
from edge_ml.standings import VARIANTS, Standings

DAY0 = datetime(2024, 8, 10, 14, 0, tzinfo=UTC)


def result(day: int, home: str, away: str, hg: int, ag: int) -> MatchResult:
    return MatchResult(home, away, hg, ag, DAY0 + timedelta(days=day), season="2024-25")


def double_round_robin(teams: list[str], strength: dict[str, int]) -> list[MatchResult]:
    """Every pair twice, one match day per round; the stronger side wins 1-0."""
    out, day = [], 0
    for i, h in enumerate(teams):
        for a in teams[i + 1 :]:
            for home, away in ((h, a), (a, h)):
                hg = int(strength[home] > strength[away])
                out.append(
                    result(day, home, away, hg, 1 - hg if strength[home] != strength[away] else 0)
                )
                day += 1
    return out


def test_table_uses_only_earlier_days():
    s = Standings([result(0, "A", "B", 2, 0), result(1, "B", "A", 1, 1)])
    first = s.stakes("A", "2024-25", DAY0)  # same day as A's win: not counted yet
    assert first.points == 0 and first.played == 0
    later = s.stakes("A", "2024-25", DAY0 + timedelta(days=1))
    assert later.points == 3 and later.played == 1 and later.position == 1


def test_ranking_tie_breaks_on_goal_difference():
    s = Standings([result(0, "A", "B", 3, 0), result(0, "C", "D", 1, 0)])
    ranked = [t for t, _ in s.table("2024-25", (DAY0 + timedelta(days=1)).date())]
    assert ranked[:2] == ["A", "C"]


def test_dead_rubber_and_pressure_late_in_the_season():
    teams = [f"T{i:02d}" for i in range(10)]  # T00 strongest ... T09 weakest
    strength = {t: 10 - i for i, t in enumerate(teams)}
    matches = double_round_robin(teams, strength)
    s = Standings(matches)
    end = matches[-1].kickoff_at + timedelta(days=1)
    mid = s.stakes("T06", "2024-25", end)  # 7th of 10: above the bottom 3, below 6th
    assert mid.remaining == 0 and mid.dead
    bottom = s.stakes("T09", "2024-25", end)
    assert not bottom.dead and bottom.pressure == pytest.approx(1.0)
    top = s.stakes("T00", "2024-25", end)
    assert not top.dead and top.pressure == 0.0


def test_nothing_is_dead_early_and_pressure_grows_with_the_season():
    teams = [f"T{i:02d}" for i in range(10)]
    matches = double_round_robin(teams, {t: 10 - i for i, t in enumerate(teams)})
    s = Standings(matches)
    early = s.stakes("T09", "2024-25", matches[20].kickoff_at)
    late = s.stakes("T09", "2024-25", matches[-1].kickoff_at)
    assert not early.dead and early.pressure < late.pressure


def test_variant_lengths():
    s = Standings([result(0, "A", "B", 1, 0), result(0, "C", "D", 1, 0)])
    st = s.stakes("A", "2024-25", DAY0 + timedelta(days=1))
    assert [len(fn(st)) for fn in VARIANTS.values()] == [1, 1, 2]
