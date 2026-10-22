"""`edge export-lineups` - past seasons' line-ups and player minutes to CSV files.

For the player-availability experiment (docs/experiments/player-availability-2026.md)
without touching the database: the production model fits on every finished
fixture stored for a league, so loading old seasons into ``fixtures`` would
change live predictions (ADR-038). This reads the provider only and writes one
CSV (standard output by default, like ``export-match-stats``):

    one row per player who played in a finished fixture (started = in the XI,
    minutes), with the fixture's league, season, kickoff, teams and score;
    a finished fixture whose details did not come back gets a single row with
    the player columns empty, so every result is kept (the experiment's
    production model trains on all finished matches, not only those with sheets)

Nothing missing is filled in. Requests: one per league season plus one per 20
finished fixtures. When the provider's daily budget runs low, details stop and
the summary says how many fixtures were left without them. Player names are not
written (ids are enough).
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
    "home_id",
    "away_id",
    "home_goals",
    "away_goals",
    "team_id",
    "player_id",
    "started",
    "minutes",
)


@dataclass
class LineupExport:
    rows: list[dict[str, Any]] = field(default_factory=list)
    per_season: dict[str, dict[str, int]] = field(default_factory=dict)

    def csv(self) -> str:
        out = io.StringIO()
        writer = csv.DictWriter(out, fieldnames=COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(self.rows)
        return out.getvalue()


def export_lineups(
    provider: FootballDataProvider, leagues: list[str], years: list[int]
) -> LineupExport:
    out = LineupExport()
    for league in leagues:
        for year in years:
            fixtures = sorted(
                (
                    f
                    for f in provider.get_season_fixtures(league, year)
                    if f.status == "finished"
                    and f.home_score is not None
                    and f.away_score is not None
                ),
                key=lambda f: (f.kickoff_at, f.provider_id),
            )
            apps = provider.get_appearances([f.provider_id for f in fixtures])
            by_fixture: dict[str, list[Any]] = {}
            for a in apps:
                by_fixture.setdefault(a.fixture_provider_id, []).append(a)
            counts = {"finished": len(fixtures), "with_sheets": 0, "full_xi": 0}
            for f in fixtures:
                rows = by_fixture.get(f.provider_id, [])
                teams = {f.home_team_provider_id, f.away_team_provider_id}
                starters = {
                    t: sum(a.started for a in rows if a.team_provider_id == t) for t in teams
                }
                sheets = all(any(a.team_provider_id == t for a in rows) for t in teams)
                counts["with_sheets"] += sheets
                counts["full_xi"] += sheets and all(n == 11 for n in starters.values())
                base = {
                    "league_id": league,
                    "season": f.season,
                    "fixture_id": f.provider_id,
                    "kickoff_at": f.kickoff_at.isoformat(),
                    "home_id": f.home_team_provider_id,
                    "away_id": f.away_team_provider_id,
                    "home_goals": f.home_score,
                    "away_goals": f.away_score,
                }
                players = [
                    {
                        **base,
                        "team_id": a.team_provider_id,
                        "player_id": a.player.provider_id,
                        "started": int(a.started),
                        "minutes": a.minutes,
                    }
                    for a in sorted(rows, key=lambda a: (a.team_provider_id, a.player.provider_id))
                    if a.team_provider_id in teams
                ]
                empty = {"team_id": "", "player_id": "", "started": "", "minutes": ""}
                out.rows.extend(players or [{**base, **empty}])
            out.per_season[f"{league} {year}"] = counts
    return out
