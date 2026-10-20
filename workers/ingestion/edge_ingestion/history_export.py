"""`edge export-match-stats` - past seasons' post-match statistics to a CSV file.

For research on past seasons (e.g. an xG experiment) without touching the
database: the production model fits on every finished fixture stored for a
league, so loading old seasons into ``fixtures`` would change live predictions.
This reads the provider only and writes one row per finished fixture:

    league_id, season, fixture_id, kickoff_at, home, away, home_goals, away_goals,
    home_shots, away_shots, home_sot, away_sot, home_xg, away_xg

Missing values stay empty (never filled in). Requests: one per league season
plus one per 20 finished fixtures. When the provider's daily budget runs low,
details stop and the summary says how many fixtures were left without them.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from typing import Any

from edge_ingestion.providers.base import FootballDataProvider

COLUMNS = (
    "league_id",
    "season",
    "fixture_id",
    "kickoff_at",
    "home",
    "away",
    "home_goals",
    "away_goals",
    "home_shots",
    "away_shots",
    "home_sot",
    "away_sot",
    "home_xg",
    "away_xg",
)


@dataclass
class ExportResult:
    rows: list[dict[str, Any]] = field(default_factory=list)
    per_season: dict[str, dict[str, int]] = field(default_factory=dict)

    def csv(self) -> str:
        out = io.StringIO()
        writer = csv.DictWriter(out, fieldnames=COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(self.rows)
        return out.getvalue()


def _blank(value: Any) -> Any:
    return "" if value is None else value


def export_match_stats(
    provider: FootballDataProvider, leagues: list[str], years: list[int]
) -> ExportResult:
    result = ExportResult()
    for league in leagues:
        for year in years:
            fixtures = [
                f
                for f in provider.get_season_fixtures(league, year)
                if f.status == "finished" and f.home_score is not None and f.away_score is not None
            ]
            stats = provider.get_match_statistics([f.provider_id for f in fixtures])
            by_team = {(s.fixture_provider_id, s.team_provider_id): s for s in stats}
            counts = {"finished": len(fixtures), "with_statistics": 0, "with_xg": 0}
            for f in sorted(fixtures, key=lambda f: (f.kickoff_at, f.provider_id)):
                h = by_team.get((f.provider_id, f.home_team_provider_id))
                a = by_team.get((f.provider_id, f.away_team_provider_id))
                both = h is not None and a is not None
                counts["with_statistics"] += both
                counts["with_xg"] += (
                    both and h.expected_goals is not None and a.expected_goals is not None
                )
                result.rows.append(
                    {
                        "league_id": league,
                        "season": f.season,
                        "fixture_id": f.provider_id,
                        "kickoff_at": f.kickoff_at.isoformat(),
                        "home": f.home_team.name,
                        "away": f.away_team.name,
                        "home_goals": f.home_score,
                        "away_goals": f.away_score,
                        "home_shots": _blank(h.shots if h else None),
                        "away_shots": _blank(a.shots if a else None),
                        "home_sot": _blank(h.shots_on_target if h else None),
                        "away_sot": _blank(a.shots_on_target if a else None),
                        "home_xg": _blank(h.expected_goals if h else None),
                        "away_xg": _blank(a.expected_goals if a else None),
                    }
                )
            result.per_season[f"{league} {year}"] = counts
    return result
