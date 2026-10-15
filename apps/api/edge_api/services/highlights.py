"""'Matches to watch': where the model and the market disagree the most.

This is an analysis view, not a pick list: one outcome per upcoming fixture
(the one the model rates highest relative to the market), filtered by a
minimum gap, sorted by gap, with caveats explaining when the model is likely
to be unreliable.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from edge_api.db.models import Fixture, FixtureStatus, OddsSnapshot, Prediction
from edge_api.schemas import FixtureSummaryOut, HighlightCaveat, HighlightOut
from edge_api.services.analysis import analyse_outcomes
from edge_ml.core import Outcome

# A gap this large usually means the market knows something the model doesn't
# (injuries, transfers, rotation), so we flag it rather than celebrate it.
LARGE_GAP = 0.10
NEWCOMER_PRIORS = {"promoted_relegation_level", "unseen_relegation_level"}


def caveats_for(prediction: Prediction, edge: float) -> list[HighlightCaveat]:
    features = prediction.features or {}
    out: list[HighlightCaveat] = []
    if features.get("prior_home") in NEWCOMER_PRIORS:
        out.append("promoted_home")
    if features.get("prior_away") in NEWCOMER_PRIORS:
        out.append("promoted_away")
    if edge >= LARGE_GAP:
        out.append("large_gap")
    return out


def build_highlights(
    fixtures: Sequence[Fixture],
    predictions: dict[int, Prediction],
    summaries: dict[int, FixtureSummaryOut],
    *,
    now: datetime,
    min_edge: float,
    threshold: float,
    limit: int,
) -> list[HighlightOut]:
    items: list[HighlightOut] = []
    for fixture in fixtures:
        prediction = predictions.get(fixture.id)
        if (
            prediction is None
            or fixture.status != FixtureStatus.SCHEDULED.value
            or fixture.kickoff_at <= now
        ):
            continue
        snapshot: OddsSnapshot = prediction.odds_snapshot
        best = max(analyse_outcomes(prediction, snapshot, threshold), key=lambda r: r.edge)
        if best.edge < min_edge:
            continue
        items.append(
            HighlightOut(
                fixture=summaries[fixture.id],
                outcome=Outcome(best.outcome),
                model_probability=best.model_probability,
                fair_probability=best.fair_probability,
                edge=best.edge,
                decimal_odds=best.decimal_odds,
                expected_value=best.expected_value,
                caveats=caveats_for(prediction, best.edge),
            )
        )
    items.sort(key=lambda h: (-h.edge, h.fixture.kickoff_at, h.fixture.id))
    return items[:limit]
