"""Independent as-of regression for result corrections in shot history."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np

from edge_api.services import shadow_v2


def test_later_score_correction_does_not_change_past_features(monkeypatch):
    at = datetime(2026, 10, 20, tzinfo=UTC)
    fixtures = [
        SimpleNamespace(
            id=i,
            league_id=1,
            home_team_id=1,
            away_team_id=2,
            kickoff_at=at - timedelta(days=i + 1),
            home_score=1,
            away_score=0,
            updated_at=at - timedelta(days=1),
        )
        for i in range(6)
    ]
    stats = [
        SimpleNamespace(fixture_id=f.id, team_id=t, shots_on_target=4)
        for f in fixtures
        for t in (1, 2)
    ]
    session = MagicMock()
    session.scalars.return_value.all.return_value = fixtures
    monkeypatch.setattr(shadow_v2.queries, "latest_statistics", lambda *a, **k: stats)
    before = shadow_v2.shot_histories(session, "mock", {1}, at)[1].features(
        "1", at, "sot_and_finishing"
    )
    fixtures[0].home_score = 0
    fixtures[0].away_score = 1
    fixtures[0].updated_at = at + timedelta(hours=1)
    after = shadow_v2.shot_histories(session, "mock", {1}, at)[1].features(
        "1", at, "sot_and_finishing"
    )
    np.testing.assert_allclose(after, before)
