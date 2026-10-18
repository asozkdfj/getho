"""Calibration experiment on synthetic predictions (a code check, not evidence)."""

import gzip
import json
from argparse import Namespace
from datetime import UTC, datetime, timedelta

import numpy as np

from edge_ingestion import calibration_backtest as cb


def _write(path, n_per_season=2500, bias=0.06):
    rng = np.random.default_rng(0)
    seasons = ["2019-20", "2020-21", "2021-22", "2022-23", "2023-24", "2024-25", "2025-26"]
    t0 = datetime(2019, 8, 1, 14, tzinfo=UTC)
    rows = []
    for s_i, season in enumerate(seasons):
        for j in range(n_per_season):
            p = rng.dirichlet([3, 2, 2.5])
            truth = p.copy()
            k = int(p.argmax())
            if p[k] > 0.6:  # favourites under-stated, like the real data
                truth[k] = min(p[k] + bias, 0.97)
                others = [i for i in range(3) if i != k]
                truth[others] = p[others] * (1 - truth[k]) / p[others].sum()
            y = int(rng.choice(3, p=truth / truth.sum()))
            kickoff = t0 + timedelta(days=365 * s_i + j * 300 / n_per_season)
            rows.append(
                {
                    "league": "xx.1" if j % 2 else "yy.1",
                    "season": season,
                    "kickoff_at": kickoff.isoformat(),
                    "outcome": y,
                    "production": p.round(6).tolist(),
                }
            )
    with gzip.open(path, "wt") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")


def test_experiment_runs_and_reports_all_gates(tmp_path):
    path = tmp_path / "pred.jsonl.gz"
    _write(path)
    report = cb.run(Namespace(predictions=path, out=tmp_path / "out.json"))
    assert report["chosen"] in cb.METHODS
    gate = report["gate"]
    assert {"g1_validation_gain", "g3_strong_tier_gap", "g4_rest_gap", "passed"} <= set(gate)
    # the synthetic favourites are under-stated: calibration shrinks that gap
    assert gate["g3_strong_tier_gap"] < gate["g3_strong_tier_gap_production"]
    strong = [
        b for b in report["descriptive"]["bands_follow_up"]["production"] if b["band"][0] >= 0.6
    ]
    assert sum(b["n"] for b in strong) < report["follow_up"]["n_matches"]  # follow-up only
    assert json.loads((tmp_path / "out.json").read_text())["experiment"].startswith("top_outcome")


def test_walk_forward_never_uses_the_target_season():
    probs = np.array([[0.7, 0.2, 0.1]] * 6)
    y = np.array([0, 0, 0, 1, 1, 1])
    seasons = np.array(["a", "a", "a", "b", "b", "b"])
    out = cb.walk_forward("isotonic", probs, y, seasons)
    assert np.allclose(out[:3], probs[:3])  # first season untouched
    # season b is mapped with season a only (all home wins) -> home raised, not lowered
    assert out[3, 0] > 0.7


def test_report_carries_manifest_history_and_breakdowns(tmp_path):
    """Codex QA M1: the exploratory result is reproducible and point-in-time."""
    path = tmp_path / "pred.jsonl.gz"
    _write(path, n_per_season=600)
    report = cb.run(Namespace(predictions=path, out=None))
    assert report["status"] == "exploratory"
    manifest = report["manifest"]
    assert manifest["protocol_commit"] == cb.PROTOCOL_COMMIT
    assert manifest["rows"] == 7 * 600 and manifest["excluded"]["rows"] == 600
    assert manifest["evaluated_rows"] == 6 * 600
    for method, history in report["parameter_history"].items():
        assert [h["season"] for h in history] == [
            "2020-21",
            "2021-22",
            "2022-23",
            "2023-24",
            "2024-25",
            "2025-26",
        ]
        for h in history:
            assert h["available_at"] <= h["decision_at"]
            assert h["season"] not in h["trained_on"]
            if method == "logistic":
                assert h["b"] >= 0
    assert set(report["by_season"]) == set(cb.VALIDATION + cb.FOLLOW_UP)
    assert set(report["by_league_follow_up"]) == {"xx.1", "yy.1"}
    assert (
        sum(v["n"] for v in report["by_league_follow_up"].values())
        == (report["follow_up"]["n_matches"])
    )
    std = report["standard_gate"]
    assert std["passed"] == (
        std["validation_gain"] >= 0.001
        and std["follow_up_gain"] >= 0.002
        and std["follow_up_ci95_weekly"][1] < 0
    )
    assert report["frozen_map_for_confirmation"]["n_train"] == manifest["rows"]
