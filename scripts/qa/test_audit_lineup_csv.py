import csv
import hashlib
import io
from datetime import UTC, datetime, timedelta

import pytest

from scripts.qa.audit_lineup_csv import REQUIRED, audit


def fixture(fid, day=0):
    return [
        dict(
            league_id="39",
            season="2025-26",
            fixture_id=str(fid),
            kickoff_at=(datetime(2025, 8, 1, tzinfo=UTC) + timedelta(days=day)).isoformat(),
            home_id="1",
            away_id="2",
            home_goals="1",
            away_goals="0",
            team_id=str(team),
            player_id=str(team * 100 + p),
            started="1",
            minutes="90",
        )
        for team in (1, 2)
        for p in range(11)
    ]


def encode(rows):
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=sorted(REQUIRED), lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue().encode()


def test_counts_and_history_never_include_same_kickoff():
    rows = [row for i in range(4) for row in fixture(i, i)] + fixture(5, 3)
    raw = encode(rows)
    result = audit(raw, hashlib.sha256(raw).hexdigest())
    segment = result["segments"]["39|2025-26"]
    assert segment["full_xi"] == 5
    assert segment["full_xi_with_3_prior_sheets_proxy"] == 2
    assert segment["full_xi_with_10_prior_sheets_proxy"] == 0
    assert result["experiment_readiness"] == "INCONCLUSIVE"
    simultaneous = audit(encode([row for i in range(5) for row in fixture(i)]))
    assert simultaneous["segments"]["39|2025-26"]["full_xi_with_3_prior_sheets_proxy"] == 0


def test_duplicate_player_and_conflicting_fixture_are_rejected():
    rows = fixture(1)
    assert audit(encode(rows + rows))["structure_verdict"] == "FAIL"
    rows[-1]["home_goals"] = "2"
    assert audit(encode(rows))["errors"][0]["kinds"] == ["conflicting_fixture_metadata"]


def test_missing_details_preserved_and_hash_uses_actual_bytes():
    row = fixture(1)[0]
    for key in ("player_id", "team_id", "started", "minutes"):
        row[key] = ""
    raw = encode([row])
    result = audit(raw)
    assert result["structure_verdict"] == "PASS"
    assert result["segments"]["39|2025-26"]["no_player_details"] == 1
    assert not result["hash_verified_against_manifest"]
    assert (
        audit(raw.replace(b"\n", b"\r\n"), hashlib.sha256(raw).hexdigest())["structure_verdict"]
        == "FAIL"
    )


def test_empty_bad_columns_and_naive_timestamps():
    assert audit(encode([]))["structure_verdict"] == "FAIL"
    with pytest.raises(ValueError, match="columns"):
        audit(b"foo\n1\n")
    rows = fixture(1)
    for row in rows:
        row["kickoff_at"] = "2025-08-01T00:00:00"
    assert audit(encode(rows))["structure_verdict"] == "FAIL"
