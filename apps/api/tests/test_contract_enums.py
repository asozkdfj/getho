"""Hand-written enums in packages/contracts must match the backend."""

import json
import re
from pathlib import Path

from edge_api.db.models import FixtureStatus
from edge_ml.combination import MAX_LEGS, MIN_LEGS
from edge_ml.core import Outcome

CONTRACTS = Path(__file__).resolve().parents[3] / "packages/contracts"
INDEX_TS = (CONTRACTS / "src/index.ts").read_text(encoding="utf-8")


def _ts_array(name: str) -> list[str]:
    match = re.search(rf"export const {name} = \[(.*?)\]", INDEX_TS, re.S)
    assert match, f"{name} not found in contracts"
    return re.findall(r'"([^"]+)"', match.group(1))


def test_fixture_statuses_match():
    assert _ts_array("FIXTURE_STATUSES") == [s.value for s in FixtureStatus]


def test_outcomes_match():
    assert _ts_array("OUTCOMES") == [o.value for o in Outcome]
    schema = json.loads((CONTRACTS / "openapi.json").read_text(encoding="utf-8"))
    assert schema["components"]["schemas"]["Outcome"]["enum"] == [o.value for o in Outcome]


def test_combination_limits_match():
    assert f"MIN_COMBINATION_LEGS = {MIN_LEGS};" in INDEX_TS
    assert f"MAX_COMBINATION_LEGS = {MAX_LEGS};" in INDEX_TS
