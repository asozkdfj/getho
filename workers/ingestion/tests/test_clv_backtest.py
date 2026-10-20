import gzip
import json
from datetime import UTC, date, datetime

import numpy as np
import pytest

from edge_ingestion import cli, clv_backtest
from edge_ingestion.clv_backtest import BookPrices, Joined

HEADER = (
    "Div,Date,Time,HomeTeam,AwayTeam,FTHG,FTAG,"
    "PSH,PSD,PSA,PSCH,PSCD,PSCA,AvgH,AvgD,AvgA,AvgCH,AvgCD,AvgCA"
)


def test_parse_odds_normalises_names_and_dates():
    text = "\n".join(
        [
            HEADER,
            "E0,05/10/2024,15:00,Nott'm Forest,Chelsea,1,1,"
            "3.1,3.4,2.4,2.9,3.4,2.6,3.0,3.3,2.4,2.8,3.3,2.6",
            "E0,06/10/24,16:30,Arsenal,Spurs,2,0,1.5,4.5,6.0,,,,1.5,4.4,6.0,1.45,4.6,6.5",
        ]
    )
    odds = clv_backtest.parse_odds(text, "en.1")
    forest = odds[("en.1", date(2024, 10, 5), "nottm forest", "chelsea")]
    assert forest["pinnacle"] == BookPrices((3.1, 3.4, 2.4), (2.9, 3.4, 2.6))
    arsenal = odds[("en.1", date(2024, 10, 6), "arsenal", "spurs")]
    assert arsenal["pinnacle"].close is None  # missing closing prices are unknown, not guessed
    assert arsenal["average"].close == (1.45, 4.6, 6.5)
    assert arsenal["bet365"] == BookPrices(None, None)  # columns absent


def test_slope_recovers_the_share_of_the_move():
    rng = np.random.default_rng(0)
    early = rng.dirichlet([4, 3, 3], size=400)
    model = rng.dirichlet([4, 3, 3], size=400)
    close = early + 0.4 * (model - early)
    weeks = np.arange(400) // 10
    out = clv_backtest.slope(model, early, close, weeks)
    assert out["beta"] == pytest.approx(0.4)
    lo, hi = out["beta_ci95_weekly"]
    assert lo <= 0.4 <= hi
    flat = clv_backtest.slope(model, early, early.copy(), weeks)
    assert flat["beta"] == pytest.approx(0.0)


def test_partial_slope_ignores_mean_reversion_of_noisy_early_prices():
    """A forecaster with no information (base rate + noise) gets a positive plain
    slope when early prices are noisy; the partial slope does not credit it."""
    rng = np.random.default_rng(2)
    n = 6000
    base = np.tile([0.45, 0.27, 0.28], (n, 1))
    truth = 0.6 * base + 0.4 * rng.dirichlet([4, 3, 3], size=n)
    noise = rng.normal(0, 0.04, size=(n, 3))
    noise -= noise.mean(axis=1, keepdims=True)  # keeps sums at 1
    early, close = truth + noise, truth
    junk = rng.normal(0, 0.04, size=(n, 3))
    model = base + junk - junk.mean(axis=1, keepdims=True)
    weeks = np.arange(n) // 30
    plain = clv_backtest.slope(model, early, close, weeks)["beta"]
    partial = clv_backtest.partial_slope(model, base, early, close, weeks)
    assert plain > 0.1
    assert abs(partial["b_model"]) < 0.05
    lo, hi = partial["b_model_ci95_weekly"]
    assert lo < 0 < hi
    assert partial["b_base"] > 0.1  # the move toward the average is attributed to it

    informed = early + 0.5 * (close - early)  # knows half of the correction
    good = clv_backtest.partial_slope(informed, base, early, close, weeks)
    assert good["b_model_ci95_weekly"][0] > 0


def test_flag_clv_values_early_price_at_the_close():
    model = np.array([[0.60, 0.20, 0.20]])
    early = np.array([[0.50, 0.25, 0.25]])
    early_raw = np.array([[2.0, 3.8, 3.8]])
    close = np.array([[0.55, 0.22, 0.23]])
    out = clv_backtest.flag_clv(model, early, early_raw, close, np.array([0]))
    by_t = {f["threshold"]: f for f in out}
    assert by_t[0.03]["flags"] == 1
    assert by_t[0.03]["mean_clv"] == pytest.approx(2.0 * 0.55 - 1)
    assert by_t[0.03]["share_positive"] == 1.0
    assert by_t[0.10]["flags"] == 1
    assert clv_backtest.flag_clv(model, model, early_raw, close, np.array([0]))[0]["flags"] == 0


def _joined(season: str, pinnacle: bool) -> Joined:
    prices = BookPrices((2.0, 3.5, 4.0), (1.9, 3.6, 4.2))
    return Joined(
        "en.1",
        season,
        datetime(2024, 1, 1, tzinfo=UTC),
        0,
        (0.5, 0.3, 0.2),
        {
            "pinnacle": prices if pinnacle else BookPrices(prices.early, None),
            "average": prices,
            "bet365": prices,
        },
    )


def test_primary_book_falls_back_when_pinnacle_is_thin():
    rows = [_joined("2024-25", pinnacle=i < 7) for i in range(10)]
    assert clv_backtest.choose_book(rows)[0] == "average"  # 70% < 80%
    rows = [_joined("2024-25", pinnacle=i < 9) for i in range(10)]
    book, cov = clv_backtest.choose_book(rows)
    assert book == "pinnacle"
    assert cov["pinnacle"] == pytest.approx(0.9)


def test_cli_end_to_end_from_cached_files(tmp_path, capsys):
    """Joins stored predictions with cached odds files; no network, no DB."""
    rng = np.random.default_rng(1)
    preds, lines = [], {s: [HEADER] for s in clv_backtest.SEASONS}
    teams = [f"Team {i}" for i in range(6)]
    for s_i, season in enumerate(clv_backtest.SEASONS):
        year = 2019 + s_i
        for n in range(30):
            day = datetime(year, 9, 1 + n % 28, 14, 0, tzinfo=UTC)
            home, away = teams[n % 6], teams[(n + 1 + n // 6) % 6]
            if home == away:
                continue
            early = rng.dirichlet([4, 3, 3])
            model = rng.dirichlet([4, 3, 3])
            close = early + 0.3 * (model - early)
            preds.append(
                {
                    "league": "en.1",
                    "season": season,
                    "kickoff_at": day.isoformat(),
                    "home": home.casefold(),
                    "away": away.casefold(),
                    "outcome": int(rng.integers(0, 3)),
                    "production": model.round(6).tolist(),
                }
            )
            e = ",".join(f"{1 / p:.4f}" for p in early)
            c = ",".join(f"{1 / p:.4f}" for p in close)
            lines[season].append(f"E0,{day:%d/%m/%Y},15:00,{home},{away},1,0,{e},{c},{e},{c}")
    preds.append({**preds[0], "home": "nobody", "away": "noone"})  # no odds row
    cache = tmp_path / "cache"
    cache.mkdir()
    for season, rows in lines.items():
        (cache / f"football-data-{clv_backtest.season_code(season)}-E0.csv").write_text(
            "\n".join(rows) + "\n"
        )
    pred_path = tmp_path / "preds.jsonl.gz"
    with gzip.open(pred_path, "wt") as fh:
        fh.write("\n".join(json.dumps(p) for p in preds) + "\n")
    out = tmp_path / "clv.json"

    assert (
        cli.main(
            [
                "backtest-clv",
                "--predictions",
                str(pred_path),
                "--cache-dir",
                str(cache),
                "--out",
                str(out),
            ]
        )
        == 0
    )
    summary = json.loads(capsys.readouterr().out)
    assert summary["book"] == "pinnacle"
    assert summary["n_joined"] == summary["n_predictions"] - 1
    assert summary["n_analysed"] < summary["n_joined"]  # 2019-20 has no earlier base rate
    assert summary["follow_up"]["b_model"] == pytest.approx(0.3, abs=0.01)
    assert summary["follow_up"]["b_base"] == pytest.approx(0.0, abs=0.01)
    assert summary["reading"]["model_has_information_beyond_early_market"] is True
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["unmatched"] == {"en.1 2019-20": 1}
    assert report["reading"]["decision"] == "none (measurement only)"
    assert set(report["source"]["files_sha256"]) == {f"en.1 {s}" for s in clv_backtest.SEASONS}


def test_default_predictions_points_at_the_stored_report():
    path = clv_backtest.default_predictions()
    assert path.name == "backtest-market.predictions.jsonl.gz"
    assert path.exists()
