"""`edge backtest-clv` - does the production model know something the early market does not?

Measurement only. Pre-registered protocol (committed before the first run; do not
edit after results - add a dated addendum instead):

Question  When the production model disagrees with the early market price, does
          the market move toward the model by kickoff? A model with information
          the early market lacks predicts the line move (closing line value,
          CLV); a model that only adds noise does not.
Model     The production model's walk-forward probabilities already stored by
          `edge backtest-market` (ml/reports/backtest-market.predictions.jsonl.gz:
          weekly refit, results enter training 3 h after kickoff). Nothing is
          refitted here, so the model cannot have seen this experiment's odds.
Odds      football-data.co.uk season CSVs (downloaded by this command, cached,
          SHA-256 per file in the report), 9 divisions E0 E1 D1 D2 SP1 I1 F1 N1
          P1, seasons 2019-20..2025-26. "Early" = the pre-closing columns, "close"
          = the closing columns of the same bookmaker. The exact capture times
          are not published in the files; closing must be sharper than early on
          outcomes (reported as a sanity check) or the columns are not what we
          assume. Prices are de-vigged proportionally (as the service does).
Books     Primary: Pinnacle (PSH/PSD/PSA -> PSCH/PSCD/PSCA). If Pinnacle has both
          prices for fewer than 80% of the matched follow-up matches, the
          primary becomes the market average (AvgH.. -> AvgCH..). Bet365 and the
          other book are reported alongside.
Join      (division, UK match date, home, away) after the same team-name
          normalisation as the market experiment; unmatched rows are counted.
Segments  validation 2020-21..2022-23, follow-up 2023-24..2025-26 (as before).
Primary   Line-move slope  beta = sum(x * y) / sum(x * x) over all matches and
          the three outcomes, x = model - early, y = close - early (fair
          probabilities). beta = 0: the market never moves toward the model;
          beta = 1: the close lands on the model. 95% CI: weekly cluster
          bootstrap (ISO weeks, 4,000 resamples).
Reading   "The model carries information the early market lacks" iff the
          follow-up beta > 0 with its CI lower bound > 0 AND the validation
          beta > 0. Otherwise: no detectable information beyond the early price.
Descriptive (not part of the reading)
          - log loss of model, early and close on the matched sample;
          - per league, season phase (first 42 days of a league season vs the
            rest) and disagreement size (max |x| bins): beta and log loss;
          - outcomes the service would mark "large gap" (model - early >= t,
            t in 0.03/0.05/0.10): mean CLV = early price x closing fair
            probability - 1 (the value of the early price judged by the close)
            and the share of positive CLV. The product never places bets.
Decision  None. No model, pick or product change follows from this report; a
          positive reading only justifies pre-registering step 2 (a model that
          adjusts the market price).
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import logging
import urllib.request
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np

import edge_ml
from edge_ingestion.history.club_match_data import DIVISIONS, UK, team_key
from edge_ml.market import devig
from edge_ml.metrics import log_loss_per_match

logger = logging.getLogger(__name__)

PREDICTIONS_NAME = "backtest-market.predictions.jsonl.gz"
URL = "https://www.football-data.co.uk/mmz4281/{code}/{division}.csv"
SEASONS = ["2019-20", "2020-21", "2021-22", "2022-23", "2023-24", "2024-25", "2025-26"]
VALIDATION = ["2020-21", "2021-22", "2022-23"]
FOLLOW_UP = ["2023-24", "2024-25", "2025-26"]
# (early columns, closing columns) per bookmaker
BOOKS: dict[str, tuple[tuple[str, str, str], tuple[str, str, str]]] = {
    "pinnacle": (("PSH", "PSD", "PSA"), ("PSCH", "PSCD", "PSCA")),
    "average": (("AvgH", "AvgD", "AvgA"), ("AvgCH", "AvgCD", "AvgCA")),
    "bet365": (("B365H", "B365D", "B365A"), ("B365CH", "B365CD", "B365CA")),
}
PRIMARY, FALLBACK = "pinnacle", "average"
MIN_PRIMARY_COVERAGE = 0.80
FLAG_THRESHOLDS = (0.03, 0.05, 0.10)
EARLY_PHASE = timedelta(days=42)
DISAGREEMENT_BINS = ((0.0, 0.03), (0.03, 0.06), (0.06, 0.10), (0.10, 1.01))
N_RESAMPLES, SEED = 4000, 20261019
FLOAT_TOLERANCE = 1e-9  # 0.60 - 0.50 is 0.0999... in floating point

Prices = tuple[float, float, float]
OddsKey = tuple[str, date, str, str]  # (league, UK date, home, away)


def default_predictions() -> Path:
    return Path(edge_ml.__file__).resolve().parents[1] / "reports" / PREDICTIONS_NAME


def add_arguments(p: argparse.ArgumentParser) -> None:
    p.add_argument("--predictions", type=Path, default=default_predictions())
    p.add_argument("--cache-dir", type=Path, default=Path(".cache/history"))
    p.add_argument("--out", type=Path, help="write the full JSON report here")


# ------------------------------------------------------------------ odds files
def season_code(season: str) -> str:
    """'2019-20' -> '1920' (football-data.co.uk's folder name)."""
    return season[2:4] + season[5:7]


def fetch(cache_dir: Path, season: str, division: str, timeout: float = 60.0) -> Path:
    path = cache_dir / f"football-data-{season_code(season)}-{division}.csv"
    if not path.exists():
        url = URL.format(code=season_code(season), division=division)
        logger.info("downloading %s", url)
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            data = resp.read()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return path


def _decode(raw: bytes) -> str:
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


def _match_date(value: str) -> date | None:
    for fmt in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(value.strip(), fmt).date()  # noqa: DTZ007 (date only)
        except ValueError:
            continue
    return None


def _prices(row: dict[str, str], cols: tuple[str, str, str]) -> Prices | None:
    try:
        prices = tuple(float(row[c]) for c in cols)
    except (KeyError, TypeError, ValueError):
        return None
    return prices if all(p > 1.0 for p in prices) else None  # type: ignore[return-value]


@dataclass(frozen=True, slots=True)
class BookPrices:
    early: Prices | None
    close: Prices | None


def parse_odds(text: str, league: str) -> dict[OddsKey, dict[str, BookPrices]]:
    out: dict[OddsKey, dict[str, BookPrices]] = {}
    for row in csv.DictReader(io.StringIO(text)):
        day = _match_date(row.get("Date") or "")
        if day is None or not row.get("HomeTeam") or not row.get("AwayTeam"):
            continue
        key = (league, day, team_key(row["HomeTeam"]), team_key(row["AwayTeam"]))
        out[key] = {
            book: BookPrices(_prices(row, early), _prices(row, close))
            for book, (early, close) in BOOKS.items()
        }
    return out


# ------------------------------------------------------------------ joining
@dataclass(frozen=True, slots=True)
class Joined:
    league: str
    season: str
    kickoff_at: datetime
    outcome: int
    model: Prices
    books: dict[str, BookPrices]


def load_predictions(path: Path) -> list[dict[str, Any]]:
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        return [json.loads(line) for line in fh]


def odds_key(pred: dict[str, Any]) -> OddsKey:
    kickoff = datetime.fromisoformat(pred["kickoff_at"])
    return (pred["league"], kickoff.astimezone(UK).date(), pred["home"], pred["away"])


def join(
    preds: list[dict[str, Any]], odds: dict[OddsKey, dict[str, BookPrices]]
) -> tuple[list[Joined], dict[str, int]]:
    rows: list[Joined] = []
    unmatched: Counter[str] = Counter()
    for p in preds:
        if p["season"] not in SEASONS:
            continue
        books = odds.get(odds_key(p))
        if books is None:
            unmatched[f"{p['league']} {p['season']}"] += 1
            continue
        rows.append(
            Joined(
                p["league"],
                p["season"],
                datetime.fromisoformat(p["kickoff_at"]),
                int(p["outcome"]),
                tuple(p["production"]),  # type: ignore[arg-type]
                books,
            )
        )
    return rows, dict(sorted(unmatched.items()))


def coverage(rows: list[Joined], book: str, seasons: list[str]) -> float | None:
    scope = [r for r in rows if r.season in seasons]
    if not scope:
        return None
    full = sum(1 for r in scope if r.books[book].early and r.books[book].close)
    return full / len(scope)


def choose_book(rows: list[Joined]) -> tuple[str, dict[str, float | None]]:
    cov = {book: coverage(rows, book, FOLLOW_UP) for book in BOOKS}
    primary_cov = cov[PRIMARY]
    book = PRIMARY if primary_cov is not None and primary_cov >= MIN_PRIMARY_COVERAGE else FALLBACK
    return book, cov


# ------------------------------------------------------------------ statistics
def _weeks(kickoffs: list[datetime]) -> np.ndarray:
    labels: dict[tuple[int, int], int] = {}
    return np.array(
        [labels.setdefault(tuple(k.isocalendar()[:2]), len(labels)) for k in kickoffs]  # type: ignore[arg-type]
    )


def slope(
    model: np.ndarray, early: np.ndarray, close: np.ndarray, weeks: np.ndarray
) -> dict[str, Any]:
    """Line-move slope (see protocol) with a weekly cluster bootstrap CI."""
    x, y = model - early, close - early
    sxy, sxx = (x * y).sum(axis=1), (x * x).sum(axis=1)
    if len(sxx) == 0 or sxx.sum() <= 0:
        return {"n_matches": len(sxx), "beta": None, "beta_ci95_weekly": [None, None]}
    w_xy, w_xx = np.bincount(weeks, weights=sxy), np.bincount(weeks, weights=sxx)
    present = np.flatnonzero(np.bincount(weeks) > 0)
    w_xy, w_xx = w_xy[present], w_xx[present]
    rng = np.random.default_rng(SEED)
    idx = rng.integers(0, len(present), size=(N_RESAMPLES, len(present)))
    den = w_xx[idx].sum(axis=1)
    betas = w_xy[idx].sum(axis=1) / np.where(den > 0, den, np.nan)
    lo, hi = np.nanquantile(betas, [0.025, 0.975])
    return {
        "n_matches": len(sxx),
        "weeks": len(present),
        "beta": float(sxy.sum() / sxx.sum()),
        "beta_ci95_weekly": [float(lo), float(hi)],
    }


def _mean_ci(values: np.ndarray, weeks: np.ndarray) -> list[float | None]:
    if len(values) == 0:
        return [None, None]
    _, ids = np.unique(weeks, return_inverse=True)
    sums, sizes = np.bincount(ids, weights=values), np.bincount(ids).astype(float)
    rng = np.random.default_rng(SEED)
    idx = rng.integers(0, len(sums), size=(N_RESAMPLES, len(sums)))
    means = sums[idx].sum(axis=1) / sizes[idx].sum(axis=1)
    return [float(np.quantile(means, 0.025)), float(np.quantile(means, 0.975))]


def flag_clv(
    model: np.ndarray,
    early: np.ndarray,
    early_raw: np.ndarray,
    close: np.ndarray,
    weeks: np.ndarray,
) -> list[dict[str, Any]]:
    out = []
    for t in FLAG_THRESHOLDS:
        i, k = np.nonzero(model - early >= t - FLOAT_TOLERANCE)
        clv = early_raw[i, k] * close[i, k] - 1.0
        out.append(
            {
                "threshold": t,
                "flags": len(clv),
                "mean_clv": float(clv.mean()) if len(clv) else None,
                "mean_clv_ci95_weekly": _mean_ci(clv, weeks[i]),
                "share_positive": float((clv > 0).mean()) if len(clv) else None,
            }
        )
    return out


@dataclass(slots=True)
class Arrays:
    rows: list[Joined]
    model: np.ndarray
    early: np.ndarray
    early_raw: np.ndarray
    close: np.ndarray
    y: np.ndarray
    weeks: np.ndarray

    @classmethod
    def build(cls, rows: list[Joined], book: str) -> Arrays:
        rows = [r for r in rows if r.books[book].early and r.books[book].close]
        early_raw = np.array([r.books[book].early for r in rows], dtype=float).reshape(-1, 3)
        return cls(
            rows,
            np.array([r.model for r in rows], dtype=float).reshape(-1, 3),
            np.array([devig(e) for e in early_raw], dtype=float).reshape(-1, 3),
            early_raw,
            np.array([devig(r.books[book].close) for r in rows], dtype=float).reshape(-1, 3),  # type: ignore[arg-type]
            np.array([r.outcome for r in rows], dtype=int),
            _weeks([r.kickoff_at for r in rows]),
        )

    def subset(self, mask: np.ndarray) -> Arrays:
        return Arrays(
            [r for r, k in zip(self.rows, mask, strict=True) if k],
            self.model[mask],
            self.early[mask],
            self.early_raw[mask],
            self.close[mask],
            self.y[mask],
            self.weeks[mask],
        )

    def section(self, *, flags: bool = True) -> dict[str, Any]:
        out: dict[str, Any] = {"n_matches": len(self.rows)}
        if not self.rows:
            return out
        ll = {
            name: float(log_loss_per_match(p, self.y).mean())
            for name, p in (("model", self.model), ("early", self.early), ("close", self.close))
        }
        out["log_loss"] = ll
        out["closing_sharper_than_early"] = ll["close"] < ll["early"]
        out["line_move"] = slope(self.model, self.early, self.close, self.weeks)
        if flags:
            out["large_gap_clv"] = flag_clv(
                self.model, self.early, self.early_raw, self.close, self.weeks
            )
        return out


def early_phase_mask(rows: list[Joined]) -> np.ndarray:
    starts: dict[tuple[str, str], datetime] = {}
    for r in rows:
        key = (r.league, r.season)
        starts[key] = min(starts.get(key, r.kickoff_at), r.kickoff_at)
    return np.array([r.kickoff_at < starts[(r.league, r.season)] + EARLY_PHASE for r in rows])


def reading(validation: dict[str, Any], follow_up: dict[str, Any]) -> dict[str, Any]:
    v, f = validation.get("line_move", {}), follow_up.get("line_move", {})
    checks = {
        "follow_up_beta>0": (f.get("beta") or 0) > 0,
        "follow_up_ci_lower>0": (f.get("beta_ci95_weekly") or [None])[0] is not None
        and f["beta_ci95_weekly"][0] > 0,
        "validation_beta>0": (v.get("beta") or 0) > 0,
    }
    return {
        "checks": checks,
        "model_has_information_beyond_early_market": all(checks.values()),
        "decision": "none (measurement only)",
    }


# ------------------------------------------------------------------ run
def run(args: argparse.Namespace) -> dict[str, Any]:
    preds = load_predictions(args.predictions)
    leagues = sorted({p["league"] for p in preds} & set(DIVISIONS))
    odds: dict[OddsKey, dict[str, BookPrices]] = {}
    files: dict[str, str] = {}
    for league in leagues:
        for season in SEASONS:
            path = fetch(args.cache_dir, season, DIVISIONS[league])
            raw = path.read_bytes()
            files[f"{league} {season}"] = hashlib.sha256(raw).hexdigest()
            odds.update(parse_odds(_decode(raw), league))
    rows, unmatched = join([p for p in preds if p["league"] in leagues], odds)
    book, cov = choose_book(rows)
    data = Arrays.build(rows, book)
    seasons = np.array([r.season for r in data.rows])
    validation = data.subset(np.isin(seasons, VALIDATION)).section()
    follow = data.subset(np.isin(seasons, FOLLOW_UP))
    follow_up = follow.section()

    f_leagues = np.array([r.league for r in follow.rows])
    phase = early_phase_mask(follow.rows)
    disagreement = np.abs(follow.model - follow.early).max(axis=1)
    by_size = {
        f"{lo:.2f}-{min(hi, 1.0):.2f}": follow.subset(
            (disagreement >= lo) & (disagreement < hi)
        ).section(flags=False)
        for lo, hi in DISAGREEMENT_BINS
    }
    other_books = {}
    for other in BOOKS:
        if other == book:
            continue
        alt = Arrays.build(rows, other)
        alt_seasons = np.array([r.season for r in alt.rows])
        other_books[other] = {
            "validation": alt.subset(np.isin(alt_seasons, VALIDATION)).section(flags=False),
            "follow_up": alt.subset(np.isin(alt_seasons, FOLLOW_UP)).section(flags=False),
        }

    return {
        "generated_at": datetime.now().astimezone().isoformat(),
        "experiment": "clv_line_move_v1",
        "protocol": __doc__,
        "predictions": {
            "file": args.predictions.name,
            "sha256": hashlib.sha256(args.predictions.read_bytes()).hexdigest(),
        },
        "source": {
            "url": URL,
            "attribution": "football-data.co.uk",
            "files_sha256": files,
        },
        "leagues": leagues,
        "n_predictions": sum(1 for p in preds if p["league"] in leagues and p["season"] in SEASONS),
        "n_joined": len(rows),
        "unmatched": unmatched,
        "coverage_follow_up": cov,
        "book": book,
        "n_with_book_prices": len(data.rows),
        "validation": validation,
        "follow_up": follow_up,
        "reading": reading(validation, follow_up),
        "descriptive": {
            "per_league_follow_up": {
                lg: follow.subset(f_leagues == lg).section(flags=False) for lg in leagues
            },
            "season_phase_follow_up": {
                "first_42_days": follow.subset(phase).section(flags=False),
                "rest": follow.subset(~phase).section(flags=False),
            },
            "disagreement_size_follow_up": by_size,
            "other_books": other_books,
        },
    }


def summary(report: dict[str, Any]) -> dict[str, Any]:
    """The few numbers worth pasting back into a chat."""

    def brief(section: dict[str, Any]) -> dict[str, Any]:
        move = section.get("line_move", {})
        return {
            "n": section.get("n_matches"),
            "log_loss": {k: round(v, 4) for k, v in section.get("log_loss", {}).items()},
            "beta": None if move.get("beta") is None else round(move["beta"], 3),
            "beta_ci95": [
                None if v is None else round(v, 3) for v in move.get("beta_ci95_weekly", [])
            ],
        }

    d = report["descriptive"]
    return {
        "book": report["book"],
        "coverage_follow_up": report["coverage_follow_up"],
        "n_predictions": report["n_predictions"],
        "n_joined": report["n_joined"],
        "n_with_book_prices": report["n_with_book_prices"],
        "validation": brief(report["validation"]),
        "follow_up": brief(report["follow_up"]),
        "reading": report["reading"],
        "large_gap_clv_follow_up": report["follow_up"].get("large_gap_clv"),
        "per_league_follow_up": {k: brief(v) for k, v in d["per_league_follow_up"].items()},
        "season_phase_follow_up": {k: brief(v) for k, v in d["season_phase_follow_up"].items()},
        "disagreement_size_follow_up": {
            k: brief(v) for k, v in d["disagreement_size_follow_up"].items()
        },
        "other_books_follow_up": {k: brief(v["follow_up"]) for k, v in d["other_books"].items()},
    }
