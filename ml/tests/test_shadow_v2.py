from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from edge_ml import shadow_v2
from edge_ml.core import MatchResult
from edge_ml.model import PoissonEloModel

DOC = Path(__file__).resolve().parents[2] / "docs/experiments/shadow-v2-2026.md"


def test_protocol_constants_match_the_document():
    doc = DOC.read_text()
    assert "2026-11-02 ~ 2027-03-28" in doc and "**1,500**" in doc
    assert shadow_v2.EVALUATION_START.isoformat() == "2026-11-02"
    assert shadow_v2.EVALUATION_END.isoformat() == "2027-03-28"
    assert shadow_v2.MIN_SETTLED == 1500 and shadow_v2.MIN_GAIN == 0.002
    for v in (*shadow_v2.OWN, *shadow_v2.OPPONENT):
        assert f"{v:.4f}".replace("-", "−") in doc


def test_neutral_features_reproduce_the_production_forecast():
    t0 = datetime(2025, 8, 1, tzinfo=UTC)
    teams = ["a", "b", "c", "d"]
    history = [
        MatchResult(h, a, (i + j) % 3, (i * j) % 2, t0 + timedelta(days=3 * (4 * i + j)), "2025-26")
        for i, h in enumerate(teams)
        for j, a in enumerate(teams)
        if h != a
    ]
    model = PoissonEloModel().fit(history, t0 + timedelta(days=120))
    out = model.predict("a", "b")
    neutral = shadow_v2.shot_adjusted(
        out.expected_goals_home, out.expected_goals_away, [0] * 4, [0] * 4
    )
    assert neutral == pytest.approx(list(out.probabilities.as_tuple()), abs=1e-12)


def test_more_shots_on_target_for_the_home_side_raise_its_chance():
    base = shadow_v2.shot_adjusted(1.4, 1.1, [0] * 4, [0] * 4)
    shooting = shadow_v2.shot_adjusted(1.4, 1.1, [0.3, 0, 0, 0], [0] * 4)
    lucky = shadow_v2.shot_adjusted(1.4, 1.1, [0, 0, 0.3, 0], [0] * 4)  # scored above its shots
    assert shooting[0] > base[0]
    assert lucky[0] < base[0]


def test_candidates_reject_a_broken_production_vector():
    with pytest.raises(ValueError):
        shadow_v2.candidates((0.5, 0.5, 0.5), (2.0, 3.0, 4.0), (1.2, 1.0), [0] * 4, [0] * 4)
