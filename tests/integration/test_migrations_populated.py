"""Downgrades on databases that already hold data (Codex QA, populated rollback)."""

from sqlalchemy import select, text

from edge_api.db.models import ModelVersion


def _cfg():
    from alembic.config import Config

    from conftest import ROOT, TEST_DATABASE_URL

    cfg = Config(str(ROOT / "apps/api/alembic.ini"))
    cfg.attributes["url"] = TEST_DATABASE_URL
    return cfg


def test_fingerprint_downgrade_keeps_rows_that_differ_only_by_fingerprint(session_factory):
    from alembic import command

    from conftest import _install_test_clock

    with session_factory() as s:
        for fp in ("a" * 64, "b" * 64):
            s.execute(
                text(
                    "INSERT INTO model_versions (name, version, git_sha, feature_set, "
                    "code_fingerprint, calibration, params) VALUES "
                    "('probe', '0.2.0', 'unknown', 'qa', :fp, 'identity', '{}')"
                ),
                {"fp": fp},
            )
        s.commit()
        engine = s.get_bind()
    cfg = _cfg()
    try:
        command.downgrade(cfg, "0005")  # used to fail on the old four-column key
        with engine.connect() as conn:
            shas = (
                conn.execute(
                    text("SELECT git_sha FROM model_versions WHERE name = 'probe' ORDER BY id")
                )
                .scalars()
                .all()
            )
        assert shas == ["unknown", "unknown+bbbbbbbbbbbb"]
    finally:
        command.upgrade(cfg, "head")
        _install_test_clock(engine)
    with session_factory() as s:
        assert len(s.scalars(select(ModelVersion).where(ModelVersion.name == "probe")).all()) == 2
