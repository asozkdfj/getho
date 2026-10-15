"""Promoted teams start at relegation level instead of league average (v0.2.0)."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from edge_ml.core import MatchResult
from edge_ml.model import PoissonEloModel

S1_START = datetime(2025, 8, 16, 14, tzinfo=UTC)
S2_START = datetime(2026, 8, 15, 14, tzinfo=UTC)
# strength index: higher = better. X, Y, Z are weak and get relegated after S1.
S1_TEAMS = {"A": 3, "B": 2, "C": 2, "D": 1, "E": 1, "X": -2, "Y": -2, "Z": -3}
PROMOTED = ("P", "Q", "R")
S2_TEAMS = {**{t: v for t, v in S1_TEAMS.items() if t not in "XYZ"}, **dict.fromkeys(PROMOTED, 0)}


def _score(home: int, away: int) -> tuple[int, int]:
    diff = home - away
    return (max(0, 1 + diff // 2 + (diff > 0)), max(0, 1 - diff // 2 - (diff > 0)))


def _season(teams: dict[str, int], start: datetime, label: str, rounds: int) -> list[MatchResult]:
    names = sorted(teams)
    out, day = [], 0
    for _ in range(rounds):
        for h in names:
            for a in names:
                if h != a:
                    hg, ag = _score(teams[h], teams[a])
                    out.append(MatchResult(h, a, hg, ag, start + timedelta(hours=day), label))
                    day += 1
    return out


S1 = _season(S1_TEAMS, S1_START, "2025-26", rounds=1)
# only a few current-season matches, promoted teams draw each other
S2 = [
    MatchResult("P", "Q", 1, 1, S2_START, "2026-27"),
    MatchResult("R", "A", 0, 2, S2_START + timedelta(hours=1), "2026-27"),
    MatchResult("B", "C", 1, 0, S2_START + timedelta(hours=2), "2026-27"),
]
AS_OF = S2_START + timedelta(days=3)


def _fit(matches):
    return PoissonEloModel().fit(matches, as_of=AS_OF)


def _no_season(matches):
    return [replace(m, season=None) for m in matches]


def test_promoted_team_starts_near_relegation_level_not_average():
    with_prior = _fit(S1 + S2)
    without = _fit(_no_season(S1 + S2))
    assert with_prior.newcomers == frozenset(PROMOTED)

    weak_elo = sorted(with_prior.elo.rating(t) for t in "XYZ")
    assert with_prior.elo.rating("P") < 1500 - 40
    assert with_prior.elo.rating("P") == pytest.approx(sum(weak_elo) / 3, abs=25)
    assert without.elo.rating("P") == pytest.approx(1500, abs=5)

    s = with_prior.strengths
    assert (
        s.attack["P"] / s.defence["P"]
        < without.strengths.attack["P"] / without.strengths.defence["P"]
    )


def test_established_team_is_clear_favourite_against_promoted_side():
    with_prior = _fit(S1 + S2).predict("D", "P")
    without = _fit(_no_season(S1 + S2)).predict("D", "P")
    assert with_prior.probabilities.home > without.probabilities.home + 0.05
    assert with_prior.features["prior_away"] == "promoted_relegation_level"
    assert with_prior.features["prior_home"] == "data"


def test_unseen_team_gets_relegation_level_prior():
    model = _fit(S1 + S2)
    out = model.predict("D", "NEWTEAM")
    assert out.features["prior_away"] == "unseen_relegation_level"
    assert model.elo.rating("NEWTEAM") < 1500 - 40
    plain = _fit(_no_season(S1 + S2)).predict("D", "NEWTEAM")
    assert plain.features["prior_away"] == "league_average"
    assert out.probabilities.home > plain.probabilities.home


def test_promoted_team_before_first_match_of_season():
    # season start: no current-season match yet, promoted teams are unseen
    model = PoissonEloModel().fit(S1, as_of=S2_START - timedelta(days=1))
    assert len({m.season for m in S1}) == 1  # single season -> no newcomer logic
    assert model.predict("D", "P").features["prior_away"] == "league_average"

    two_seasons = _season(S1_TEAMS, S1_START - timedelta(days=365), "2024-25", 1) + S1
    model = PoissonEloModel().fit(two_seasons, as_of=S2_START - timedelta(days=1))
    assert model.predict("D", "P").features["prior_away"] == "unseen_relegation_level"


def test_same_teams_every_season_matches_seasonless_fit():
    # no promotion/relegation -> identical ratings for every known team
    s2_same = _season(S1_TEAMS, S2_START, "2026-27", rounds=1)[:10]
    a = _fit(S1 + s2_same)
    b = _fit(_no_season(S1 + s2_same))
    assert a.newcomers == frozenset()
    assert a.elo.ratings == pytest.approx(b.elo.ratings)
    assert a.strengths.attack == pytest.approx(b.strengths.attack)
    assert a.predict("A", "Z").probabilities == b.predict("A", "Z").probabilities


def test_probabilities_still_sum_to_one():
    model = _fit(S1 + S2)
    for home, away in [("P", "Q"), ("A", "R"), ("NEW1", "NEW2")]:
        assert sum(model.predict(home, away).probabilities.as_tuple()) == pytest.approx(1.0)
