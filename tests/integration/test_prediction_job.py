"""Prediction snapshot guarantees: idempotency, append-only, required fields."""

from datetime import timedelta

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from edge_api.db.models import Fixture, ModelVersion, OddsSnapshot, Prediction
from edge_api.services.prediction_job import run_prediction_job
from edge_ingestion.jobs import run_ingestion, run_pipeline
from edge_ingestion.providers import MockProvider
from edge_ml.model import FEATURE_SET, MODEL_VERSION

BOOKMAKER = "mockbook"


def _predictions(session):
    return {
        p.id: (p.fixture_id, p.probability_home, p.market_odds_snapshot_id, p.input_data_as_of)
        for p in session.scalars(select(Prediction))
    }


def test_rerunning_prediction_job_creates_no_duplicates(db_session, seeded, now):
    assert seeded.predictions.created > 0
    before = _predictions(db_session)

    again = run_prediction_job(db_session, now=now, bookmaker=BOOKMAKER)
    db_session.commit()
    assert again.created == 0
    assert again.unchanged == seeded.predictions.created
    assert _predictions(db_session) == before
    assert db_session.scalar(select(func.count()).select_from(ModelVersion)) == 1


def test_full_pipeline_rerun_is_a_noop(session_factory, seeded, now):
    with session_factory() as s:
        res = run_pipeline(s, MockProvider(now), now=now, bookmaker=BOOKMAKER)
        s.commit()
    assert res.ingestion.odds_inserted == 0
    assert res.ingestion.fixtures_changed == 0
    assert res.predictions.created == 0


def test_new_odds_append_new_prediction_and_keep_history(db_session, seeded, now):
    before = _predictions(db_session)
    later = now + timedelta(hours=12)
    run_ingestion(db_session, MockProvider(later), now=later)
    res = run_prediction_job(db_session, now=later, bookmaker=BOOKMAKER)
    db_session.commit()

    after = _predictions(db_session)
    assert res.created > 0
    assert {k: after[k] for k in before} == before  # history is untouched
    assert len(after) == len(before) + res.created


def test_prediction_rows_have_required_audit_fields(db_session, seeded, now):
    rows = db_session.scalars(select(Prediction)).all()
    assert rows
    for p in rows:
        assert p.fixture_id and p.model_version_id and p.market_odds_snapshot_id
        assert p.created_at.utcoffset() == timedelta(0)
        assert p.input_data_as_of <= now
        assert p.probability_home + p.probability_draw + p.probability_away == pytest.approx(1)
        snap = db_session.get(OddsSnapshot, p.market_odds_snapshot_id)
        fixture = db_session.get(Fixture, p.fixture_id)
        assert snap.fixture_id == p.fixture_id
        assert snap.captured_at <= now < fixture.kickoff_at  # pre-match, no look-ahead
    mv = db_session.scalars(select(ModelVersion)).one()
    assert mv.version == MODEL_VERSION and mv.feature_set == FEATURE_SET
    assert mv.git_sha and mv.calibration == "identity"
    assert "poisson_weight" in mv.params


def test_no_predictions_for_started_or_finished_fixtures(db_session, seeded, now):
    started = db_session.scalar(
        select(func.count())
        .select_from(Prediction)
        .join(Fixture, Fixture.id == Prediction.fixture_id)
        .where(Fixture.kickoff_at <= now)
    )
    assert started == 0


@pytest.mark.parametrize("table", ["predictions", "odds_snapshots"])
@pytest.mark.parametrize("op", ["UPDATE {t} SET created_at = now()", "DELETE FROM {t}"])
def test_snapshot_tables_are_append_only(session_factory, seeded, table, op):
    with session_factory() as s, pytest.raises(DBAPIError, match="append-only"):
        s.execute(text(op.format(t=table)))


def test_db_rejects_probabilities_not_summing_to_one(session_factory, seeded):
    with session_factory() as s:
        p = s.scalars(select(Prediction).limit(1)).one()
        with pytest.raises(DBAPIError, match="probabilities_sum_to_one"):
            s.execute(
                text(
                    "INSERT INTO predictions (fixture_id, model_version_id, "
                    "market_odds_snapshot_id, input_data_as_of, probability_home, "
                    "probability_draw, probability_away, expected_goals_home, "
                    "expected_goals_away, features) VALUES (:f, :m, :o, now(), 0.5, 0.5, 0.5, "
                    "1, 1, '{}')"
                ),
                {"f": p.fixture_id, "m": p.model_version_id, "o": p.market_odds_snapshot_id},
            )
