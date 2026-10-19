"""Exercise migration 0006 rollback with two legitimate fingerprint identities.

Only the named disposable QA database on port 15432 is accepted. Never production.
"""

import json
import os
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError

url = os.environ["QA_DATABASE_URL"]
parsed = make_url(url)
assert parsed.database == "edge_test_pr5_guard" and parsed.port == 15432
root = Path(os.environ["QA_TARGET_ROOT"])
cfg = Config(str(root / "apps/api/alembic.ini"))
cfg.attributes["url"] = url
command.upgrade(cfg, "head")
engine = create_engine(url)
with engine.begin() as conn:
    for fingerprint in ("a" * 64, "b" * 64):
        conn.execute(
            text("""
            INSERT INTO model_versions
                (name, version, git_sha, feature_set, code_fingerprint, calibration, params)
            VALUES ('qa-downgrade-probe', '0.2.0', 'unknown', 'qa', :fp, 'identity', '{}')
            ON CONFLICT DO NOTHING
        """),
            {"fp": fingerprint},
        )
try:
    command.downgrade(cfg, "0005")
except IntegrityError as exc:
    print(
        json.dumps(
            {
                "downgrade": "FAIL",
                "error_type": type(exc.orig).__name__,
                "constraint": "uq_model_versions_identity",
                "reason": "two different fingerprints share the old four-column key",
            }
        )
    )
else:
    print(json.dumps({"downgrade": "PASS"}))
