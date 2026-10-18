"""Read-only 09:00 KST comparison audit; not a production quality-gate replay.

Set QA_DATABASE_URL; never place credentials in output. A repeatable-read,
read-only transaction reads existing records without API calls or DB writes.
"""

import argparse
import hashlib
import json
import math
import os
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from sqlalchemy import create_engine, text


def valid_probabilities(p):
    return (
        len(p) == 3 and all(math.isfinite(v) and 0 <= v <= 1 for v in p) and abs(sum(p) - 1) < 1e-6
    )


def available(created_at, captured_at, decision):
    return created_at <= decision and captured_at <= decision


def metrics(rows, field):
    n = len(rows)
    if not n:
        return None
    return {
        "n": n,
        "log_loss": sum(-math.log(max(r[field][r["outcome"]], 1e-15)) for r in rows) / n,
        "brier": sum(
            sum((v - (i == r["outcome"])) ** 2 for i, v in enumerate(r[field])) for r in rows
        )
        / n,
        "accuracy": sum(max((0, 2, 1), key=lambda i: r[field][i]) == r["outcome"] for r in rows)
        / n,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument(
        "--end", type=date.fromisoformat, required=True, help="exclusive UTC midnight / KST 09:00"
    )
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--max-age-hours", type=float, default=72)
    args = parser.parse_args()
    if args.end <= args.start or args.max_age_hours <= 0:
        parser.error("require end > start and positive max-age-hours")
    engine = create_engine(os.environ["QA_DATABASE_URL"])
    now = datetime.now(UTC)
    params = {
        "start": datetime.combine(args.start, datetime.min.time(), UTC),
        "end": datetime.combine(args.end, datetime.min.time(), UTC),
        "now": now,
    }
    with (
        engine.connect().execution_options(isolation_level="REPEATABLE READ") as conn,
        conn.begin(),
    ):
        conn.execute(text("SET TRANSACTION READ ONLY"))
        conn.execute(text("SET LOCAL statement_timeout = '60s'"))
        # 09:00 KST == 00:00 UTC. Current fixture rows are NOT historical schedule snapshots.
        rows = (
            conn.execute(
                text("""
            WITH scope AS (
                SELECT f.*,
                    date_trunc('day', f.kickoff_at AT TIME ZONE 'UTC')
                    AT TIME ZONE 'UTC' AS decision
                FROM fixtures f WHERE f.provider='api_football'
                  AND f.kickoff_at >= :start AND f.kickoff_at < :end
            )
            SELECT f.id, f.league_id, f.status, f.kickoff_at, f.decision,
                f.home_score, f.away_score,
                p.id AS prediction_id, p.created_at AS prediction_created,
                p.input_data_as_of, p.probability_home, p.probability_draw, p.probability_away,
                p.market_odds_snapshot_id, mv.version, mv.git_sha, mv.calibration,
                o.id AS odds_id, o.bookmaker, o.captured_at AS odds_captured,
                o.created_at AS odds_created,
                o.odds_home, o.odds_draw, o.odds_away,
                po.captured_at AS input_odds_captured, po.created_at AS input_odds_created,
                (SELECT count(DISTINCT n.team_id) FROM team_news_snapshots n
                  WHERE n.fixture_id=f.id AND n.provider='api_football' AND n.kind='absences'
                    AND n.created_at<=f.decision
                    AND n.captured_at<=f.decision) AS absence_teams,
                (SELECT count(DISTINCT n.team_id) FROM team_news_snapshots n
                  WHERE n.fixture_id=f.id AND n.provider='api_football' AND n.kind='lineup'
                    AND n.created_at<=f.decision AND n.captured_at<=f.decision) AS lineup_teams
            FROM scope f
            LEFT JOIN LATERAL (
                SELECT pr.* FROM predictions pr
                JOIN model_versions v ON v.id=pr.model_version_id
                WHERE pr.fixture_id=f.id AND pr.created_at<=f.decision
                  AND pr.input_data_as_of<=f.decision AND v.version='0.2.0'
                  AND v.calibration='identity'
                ORDER BY pr.created_at DESC,pr.id DESC LIMIT 1
            ) p ON true
            LEFT JOIN model_versions mv ON mv.id=p.model_version_id
            LEFT JOIN odds_snapshots po ON po.id=p.market_odds_snapshot_id
            LEFT JOIN LATERAL (
                SELECT os.* FROM odds_snapshots os WHERE os.fixture_id=f.id
                  AND os.provider='api_football' AND os.market='1X2'
                  AND os.bookmaker=po.bookmaker
                  AND os.created_at<=f.decision AND os.captured_at<=f.decision
                ORDER BY os.captured_at DESC, os.id DESC LIMIT 1
            ) o ON true
            WHERE f.decision<=:now ORDER BY f.kickoff_at,f.id
        """),
                params,
            )
            .mappings()
            .all()
        )
        coverage = (
            conn.execute(
                text("""
            SELECT 'news_' || kind AS kind, count(*) AS rows,
                count(DISTINCT fixture_id) AS fixtures,
                min(created_at) AS first_stored, max(created_at) AS last_stored
            FROM team_news_snapshots WHERE provider='api_football' GROUP BY kind
            UNION ALL
            SELECT 'player_minutes',count(*),count(DISTINCT fixture_id),
                min(created_at),max(created_at)
            FROM player_appearances WHERE provider='api_football'
        """)
            )
            .mappings()
            .all()
        )
    manifest = []
    for row in rows:
        r = dict(row)
        reasons = []
        if r["kickoff_at"] <= r["decision"]:
            reasons.append("already_started_at_decision")
        if r["prediction_id"] is None:
            reasons.append("no_stored_prediction_available_at_decision")
        if r["odds_id"] is None:
            reasons.append("no_same_bookmaker_odds_available_at_decision")
        if r["prediction_id"] is not None:
            p = [r["probability_home"], r["probability_draw"], r["probability_away"]]
            if not valid_probabilities(p):
                reasons.append("invalid_model_probabilities")
            if not available(r["input_odds_created"], r["input_odds_captured"], r["decision"]):
                reasons.append("prediction_used_unavailable_odds")
            for field in ("prediction_created", "input_odds_captured"):
                if r["decision"] - r[field] > timedelta(hours=args.max_age_hours):
                    reasons.append("stale_" + field)
            r["production"] = p
        if r["odds_id"] is not None:
            odds = [float(r[k]) for k in ("odds_home", "odds_draw", "odds_away")]
            if not all(math.isfinite(v) and v > 1 for v in odds):
                reasons.append("invalid_odds")
            else:
                inv = [1 / v for v in odds]
                r["market"] = [v / sum(inv) for v in inv]
            if r["decision"] - r["odds_captured"] > timedelta(hours=args.max_age_hours):
                reasons.append("stale_market_odds")
        r["exclusions"] = reasons
        r["pair_eligible"] = not reasons
        r["outcome"] = None
        if (
            r["status"] == "finished"
            and r["home_score"] is not None
            and r["away_score"] is not None
        ):
            r["outcome"] = (
                0
                if r["home_score"] > r["away_score"]
                else 1
                if r["home_score"] == r["away_score"]
                else 2
            )
        if r["pair_eligible"]:
            r["blend_25"] = [
                0.25 * p + 0.75 * m for p, m in zip(r["production"], r["market"], strict=True)
            ]
        manifest.append(r)
    evaluated = [r for r in manifest if r["pair_eligible"] and r["outcome"] is not None]
    manifest_path = args.out.with_suffix(".jsonl")
    payload = "".join(json.dumps(r, default=str, ensure_ascii=False) + "\n" for r in manifest)
    manifest_path.write_text(payload, encoding="utf-8", newline="\n")
    report = {
        "generated_at": now.isoformat(),
        "start": str(args.start),
        "end_exclusive": str(args.end),
        "decision": "09:00 Asia/Seoul",
        "max_age_hours": args.max_age_hours,
        "fixtures": len(manifest),
        "pair_eligible": sum(r["pair_eligible"] for r in manifest),
        "settled_pairs": len(evaluated),
        "evaluated_by_league": dict(Counter(str(r["league_id"]) for r in evaluated)),
        "evaluated_by_decision": dict(Counter(str(r["decision"]) for r in evaluated)),
        "evaluated_model_identities": sorted(
            {str((r["version"], r["git_sha"], r["calibration"])) for r in evaluated}
        ),
        "exclusions_nonexclusive": dict(Counter(x for r in manifest for x in r["exclusions"])),
        "metrics_descriptive_only": {
            k: metrics(evaluated, k) for k in ("production", "market", "blend_25")
        },
        "stored_feature_coverage": [dict(r) for r in coverage],
        "scope_absence_both_teams_at_decision": sum(r["absence_teams"] == 2 for r in manifest),
        "scope_lineup_both_teams_at_decision": sum(r["lineup_teams"] == 2 for r in manifest),
        "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "limitations": [
            "Current fixture schedule/status, not a historical candidate-universe replay",
            "Training-result availability and historical quality gates not certified",
            "No API calls; stored coverage only; missing means not observed, not healthy player",
            "No promotion decision or significance claim from this observational audit",
        ],
    }
    args.out.write_text(
        json.dumps(report, default=str, ensure_ascii=False, indent=2),
        encoding="utf-8",
        newline="\n",
    )
    print(json.dumps(report, default=str, ensure_ascii=False))


if __name__ == "__main__":
    main()
