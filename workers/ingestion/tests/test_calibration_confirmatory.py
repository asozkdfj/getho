import json
import re
from datetime import date, timedelta
from pathlib import Path

import numpy as np

from edge_ingestion import calibration_confirmatory as cc
from edge_ingestion import cli
from edge_ingestion.history.football_data import season_code

REPO = Path(__file__).resolve().parents[3]
TEAMS = ["Alpha", "Beta", "Gamma", "Delta"]


def _season_csv(season: str, start: date, drop_last: bool = False) -> str:
    rng = np.random.default_rng(int(season[:4]))
    pairs = [(h, a) for h in TEAMS for a in TEAMS if h != a]
    lines = ["Div,Date,Time,HomeTeam,AwayTeam,FTHG,FTAG"]
    for i, (home, away) in enumerate(pairs[:-1] if drop_last else pairs):
        day = start + timedelta(days=7 * i)
        hg, ag = rng.poisson(1.5), rng.poisson(1.1)
        lines.append(f"E0,{day:%d/%m/%Y},15:00,{home},{away},{hg},{ag}")
    return "\n".join(lines) + "\n"


def _cache(tmp_path: Path, target: str, target_start: date, drop_last: bool = False) -> Path:
    cache = tmp_path / "cache"
    cache.mkdir()
    for season in cc.seasons_from(cc.FIRST, target):
        start = target_start if season == target else date(int(season[:4]), 8, 10)
        text = _season_csv(season, start, drop_last=drop_last and season == target)
        (cache / f"football-data-{season_code(season)}-E0.csv").write_text(text)
    return cache


def _run(cache: Path, season: str, capsys, out: Path) -> dict:
    assert (
        cli.main(
            [
                "score-calibration-confirmatory",
                "--season",
                season,
                "--cache-dir",
                str(cache),
                "--out",
                str(out),
            ]
        )
        == 0
    )
    return json.loads(capsys.readouterr().out)


def test_frozen_map_matches_the_report_and_the_protocol():
    report = json.loads((REPO / "ml/reports/backtest-calibration.json").read_text())
    frozen = report["frozen_map_for_confirmation"]
    assert (frozen["a"], frozen["b"]) == (cc.FROZEN_A, cc.FROZEN_B)
    assert report["standard_gate"]["validation_gain"] == cc.EXPLORATORY_VALIDATION_GAIN
    doc = (REPO / cc.PROTOCOL).read_text()
    assert re.search(rf"a = {cc.FROZEN_A:.6f}, b = {cc.FROZEN_B:.6f}", doc)
    assert "2026-10-19 00:00 UTC" in doc and "2,500" in doc


def test_season_completeness_is_a_full_double_round_robin():
    full = [(h, a) for h in TEAMS for a in TEAMS if h != a]
    assert cc.season_complete(full)["complete"] is True
    assert cc.season_complete(full[:-1])["complete"] is False
    assert cc.season_complete([])["complete"] is False


def test_no_metric_is_reported_before_the_season_is_complete(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(cc, "LEAGUES", ("en.1",))
    cache = _cache(tmp_path, "2026-27", date(2026, 10, 20), drop_last=True)
    out = tmp_path / "report.json"
    summary = _run(cache, "2026-27", capsys, out)
    assert summary["status"] == "not_scored"
    assert summary["completeness"]["en.1"] == {
        "teams": 4,
        "played": 11,
        "expected": 12,
        "complete": False,
    }
    text = out.read_text()
    for leak in ("log_loss", "brier", "hit_rate", "decision", "metrics"):
        assert leak not in text


def test_complete_season_is_scored_inside_the_window(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(cc, "LEAGUES", ("en.1",))
    # first two matches kick off before 2026-10-19 and must not be scored
    cache = _cache(tmp_path, "2026-27", date(2026, 10, 5))
    out = tmp_path / "report.json"
    summary = _run(cache, "2026-27", capsys, out)
    assert summary["status"] == "scored"
    decision = summary["decision"]
    assert decision["n_matches"] == 10
    assert decision["conclusion"] == "undecidable"  # < 2,500
    assert decision["standard_gate"]["checks"]["validation_gain>=0.001"] is False
    assert decision["standard_gate"]["passed"] is False
    assert set(decision["calibration_criteria"]["checks"]) == {"C1", "C2", "C3"}
    assert decision["deployed"] is False
    report = json.loads(out.read_text())
    assert report["mode"] == "confirmatory"
    assert report["data"]["en.1"]["files"][-1]["season"] == "2026-27"
    assert len(report["data"]["en.1"]["files"][-1]["sha256"]) == 64


def test_past_season_is_a_labelled_rehearsal(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(cc, "LEAGUES", ("en.1",))
    cache = _cache(tmp_path, "2025-26", date(2025, 8, 10))
    summary = _run(cache, "2025-26", capsys, tmp_path / "r.json")
    assert summary["mode"] == "rehearsal"
    assert summary["status"] == "rehearsal_scored"
    assert summary["decision"]["n_matches"] == 12  # whole season


def test_a_different_production_model_blocks_scoring(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(cc, "LEAGUES", ("en.1",))
    monkeypatch.setattr(cc, "MODEL_VERSION", "0.3.0")
    cache = _cache(tmp_path, "2026-27", date(2026, 10, 20))
    summary = _run(cache, "2026-27", capsys, tmp_path / "r.json")
    assert summary["status"] == "blocked"
    assert "decision" not in summary


def test_frozen_calibrator_keeps_rows_normalised_and_the_top_on_top():
    probs = np.array([[0.62, 0.22, 0.16], [0.35, 0.33, 0.32], [0.2, 0.25, 0.55]])
    cal = cc.frozen_calibrator().calibrate_matrix(probs)
    assert np.allclose(cal.sum(axis=1), 1.0)
    assert (cal.argmax(axis=1) == probs.argmax(axis=1)).all()
    assert cal[0, 0] > probs[0, 0]  # b > 1 lifts a clear favourite
