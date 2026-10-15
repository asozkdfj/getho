import pytest

from edge_ml.poisson import probabilities_from_expected_goals
from edge_ml.simulation import replay_match, simulate_match


def test_simulated_frequencies_converge_to_the_model():
    s = simulate_match(1.6, 1.1, runs=200_000, seed=7)
    exact = probabilities_from_expected_goals(1.6, 1.1)
    for sim, ex in zip(s.outcome_share.as_tuple(), exact.as_tuple(), strict=True):
        assert sim == pytest.approx(ex, abs=4 * s.standard_error)
    assert s.mean_goals[0] == pytest.approx(1.6, abs=0.02)
    assert sum(share for _, share in s.total_goals) == pytest.approx(1.0)
    top = s.top_scores[0]
    assert top.share == pytest.approx(top.exact, abs=0.01)


def test_simulation_is_reproducible_and_seed_dependent():
    assert simulate_match(1.4, 1.2, runs=5000, seed=1) == simulate_match(
        1.4, 1.2, runs=5000, seed=1
    )
    assert simulate_match(1.4, 1.2, runs=5000, seed=1) != simulate_match(
        1.4, 1.2, runs=5000, seed=2
    )
    with pytest.raises(ValueError):
        simulate_match(1.4, 1.2, runs=0)


def test_derived_markets_are_consistent():
    s = simulate_match(1.5, 1.0, runs=20_000, seed=3)
    assert s.over["1.5"] >= s.over["2.5"] >= s.over["3.5"]
    assert s.both_teams_score <= min(1 - s.home_clean_sheet, 1 - s.away_clean_sheet) + 1e-9
    assert s.standard_error < 0.005


def test_replay_goal_minutes():
    for seed in range(20):
        r = replay_match(1.5, 1.2, seed=seed)
        assert len(r.goals) == r.home_goals + r.away_goals
        assert sum(g.side == "home" for g in r.goals) == r.home_goals
        assert all(1 <= g.minute <= 90 for g in r.goals)
        assert [g.minute for g in r.goals] == sorted(g.minute for g in r.goals)
