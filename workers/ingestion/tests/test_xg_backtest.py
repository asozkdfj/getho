"""xG experiment plumbing: reading the export, joining it to football-data matches,
and the gate against the shot-based reference (no real xG here)."""

from datetime import UTC, datetime
from types import SimpleNamespace

import numpy as np

from edge_ingestion import xg_backtest as xb
from edge_ingestion.history_export import COLUMNS


def _csv(*rows):
    lines = [",".join(COLUMNS)]
    for r in rows:
        lines.append(",".join(str(r.get(c, "")) for c in COLUMNS))
    return "\n".join(lines) + "\n"


def _row(home, away, hg, ag, when, hxg="1.2", axg="0.8", league="39"):
    return {
        "league_id": league,
        "season": "2024-25",
        "fixture_id": "1",
        "kickoff_at": when,
        "home": home,
        "away": away,
        "home_goals": hg,
        "away_goals": ag,
        "home_xg": hxg,
        "away_xg": axg,
    }


def _match(home, away, hg, ag, when, season="2024-25"):
    return SimpleNamespace(
        result=SimpleNamespace(
            home=home,
            away=away,
            home_goals=hg,
            away_goals=ag,
            kickoff_at=datetime.fromisoformat(when),
            season=season,
        )
    )


def test_rows_without_both_xg_values_are_dropped():
    text = _csv(
        _row("Arsenal", "Chelsea", 2, 1, "2024-09-01T15:00:00+00:00"),
        _row("Leeds", "Hull", 0, 0, "2024-09-01T15:00:00+00:00", axg=""),
    )
    rows = xb.read_xg(text)
    assert len(rows["39"]) == 1 and rows["39"][0]["xg"] == (1.2, 0.8)


def test_join_needs_date_score_and_one_matching_name():
    rows = xb.read_xg(
        _csv(
            _row("Wolverhampton Wanderers", "Brighton", 1, 1, "2024-09-01T14:00:00+00:00"),
            _row("Manchester United", "Fulham", 1, 0, "2024-09-01T14:00:00+00:00"),
            _row("Arsenal", "Chelsea", 3, 0, "2024-09-02T19:00:00+00:00"),
        )
    )["39"]
    matches = [
        _match("Wolves", "Brighton", 1, 1, "2024-09-01T14:00:00+00:00"),  # one name matches
        _match("Man United", "Fulham", 1, 0, "2024-09-01T14:00:00+00:00"),
        _match("Arsenal", "Chelsea", 2, 0, "2024-09-02T19:00:00+00:00"),  # score differs
        _match("Everton", "Spurs", 1, 1, "2024-09-01T14:00:00+00:00"),  # names do not match
    ]
    joined, counts = xb.join(matches, rows)
    assert len(joined) == 2
    assert counts["2024-25"] == {"matches": 4, "joined": 2}


def test_each_xg_row_is_used_once():
    rows = xb.read_xg(_csv(_row("Arsenal", "Chelsea", 1, 0, "2024-09-01T14:00:00+00:00")))["39"]
    twice = [
        _match("Arsenal", "Chelsea", 1, 0, "2024-09-01T14:00:00+00:00"),
        _match("Arsenal", "Chelsea", 1, 0, "2024-09-01T18:00:00+00:00"),
    ]
    joined, _ = xb.join(twice, rows)
    assert len(joined) == 1


def test_uk_date_decides_the_day():
    # 23:30 UTC on 31 Aug is 00:30 on 1 Sep in London (summer time)
    rows = xb.read_xg(_csv(_row("Arsenal", "Chelsea", 1, 0, "2024-08-31T23:30:00+00:00")))["39"]
    joined, _ = xb.join([_match("Arsenal", "Chelsea", 1, 0, "2024-09-01T00:30:00+01:00")], rows)
    assert len(joined) == 1


def _ex(candidates, seasons, outcomes):
    rows = [
        SimpleNamespace(match=SimpleNamespace(result=SimpleNamespace(kickoff_at=t)))
        for t in [datetime(2025, 8, 1 + i % 28, tzinfo=UTC) for i in range(len(seasons))]
    ]
    return SimpleNamespace(
        candidates=candidates,
        seasons=np.array(seasons),
        outcomes=np.array(outcomes),
        rows=rows,
    )


def test_gate_compares_the_chosen_xg_variant_with_the_reference():
    n = 400
    y = np.zeros(n, dtype=int)
    ref = np.tile([0.5, 0.3, 0.2], (n, 1))
    good = np.tile([0.6, 0.25, 0.15], (n, 1))  # more mass on the outcome that happened
    worse = np.tile([0.4, 0.35, 0.25], (n, 1))
    ex = _ex(
        {xb.REFERENCE: ref, "xg_and_finishing": good, "sot_finishing_plus_xg": worse},
        ["2025-26"] * n,
        y,
    )
    validation = {
        xb.REFERENCE: {"log_loss": 0.70},
        "xg_and_finishing": {"log_loss": 0.69},
        "sot_finishing_plus_xg": {"log_loss": 0.71},
    }
    g = xb.gate_vs_reference(ex, validation)
    assert g["selected_on_validation"] == "xg_and_finishing"
    assert g["validation_gain_vs_reference"] == np.float64(0.70) - 0.69
    assert g["follow_up_gain_vs_reference"] > 0.1 and g["passes"] and g["reading"] == "passes"
    assert g["deployed"] is False
