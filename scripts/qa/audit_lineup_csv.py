"""Audit exported lineup bytes and structure, without evaluating model outcomes."""

import argparse
import csv
import hashlib
import io
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

REQUIRED = {
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
}
META = ("league_id", "season", "kickoff_at", "home_id", "away_id", "home_goals", "away_goals")
PLAYER = ("team_id", "player_id", "started", "minutes")


def audit(raw, expected_sha=None):
    digest = hashlib.sha256(raw).hexdigest()
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
    if not set(reader.fieldnames or []) >= REQUIRED:
        raise ValueError("missing required CSV columns")
    groups = defaultdict(list)
    errors = []
    if expected_sha is not None and digest != expected_sha.lower():
        errors.append({"kind": "sha256_mismatch"})
    for line, row in enumerate(reader, 2):
        if None in row or any(row.get(k) is None for k in REQUIRED):
            errors.append({"kind": "malformed_row", "line": line})
            continue
        if not row["fixture_id"]:
            errors.append({"kind": "missing_fixture_id", "line": line})
            continue
        groups[row["fixture_id"]].append(row)
    segments = defaultdict(Counter)
    timeline = []
    for fid, rows in groups.items():
        meta = rows[0]
        count = segments[f"{meta['league_id']}|{meta['season']}"]
        count["fixtures_present"] += 1
        bad = []
        if len({tuple(r[k] for k in META) for r in rows}) != 1:
            bad.append("conflicting_fixture_metadata")
        if any(not meta[k] for k in META) or meta["home_id"] == meta["away_id"]:
            bad.append("invalid_fixture_identity")
        try:
            at = datetime.fromisoformat(meta["kickoff_at"])
            if at.tzinfo is None:
                raise ValueError("naive timestamp")
            for k in ("home_goals", "away_goals"):
                if int(meta[k]) < 0:
                    raise ValueError("negative score")
        except ValueError:
            bad.append("invalid_time_or_score")
            at = None
        seen = set()
        starters = Counter()
        players = Counter()
        empty = 0
        for row in rows:
            if all(row[k] == "" for k in PLAYER):
                empty += 1
                continue
            if any(row[k] == "" for k in PLAYER):
                bad.append("partial_player_fields")
                continue
            team, pid = row["team_id"], row["player_id"]
            if pid in seen:
                bad.append("duplicate_player_in_fixture")
            seen.add(pid)
            if team not in (meta["home_id"], meta["away_id"]):
                bad.append("foreign_team")
            try:
                started, minutes = int(row["started"]), int(row["minutes"])
                if started not in (0, 1) or not 0 <= minutes <= 130:
                    raise ValueError("range")
            except ValueError:
                bad.append("invalid_player_values")
                continue
            players[team] += 1
            starters[team] += started
        if empty and (empty != 1 or len(rows) != 1):
            bad.append("duplicate_or_mixed_placeholder")
        if bad:
            count["invalid_fixtures"] += 1
            errors.append({"fixture_id": fid, "kinds": sorted(set(bad))})
            continue
        if empty:
            count["no_player_details"] += 1
        home, away = meta["home_id"], meta["away_id"]
        both = players[home] > 0 and players[away] > 0
        count["both_team_details"] += int(both)
        full = starters[home] == 11 and starters[away] == 11
        count["full_xi"] += int(full)
        count["incomplete_xi"] += int(not full)
        timeline.append((at, fid, meta["league_id"], meta["season"], home, away, full))
    # Same-kickoff fixtures are inspected before adding any of their sheets.
    # Earlier kickoff is a structural proxy, not proof of result/data availability.
    past = Counter()
    by_time = defaultdict(list)
    for row in timeline:
        by_time[row[0]].append(row)
    for at in sorted(by_time):
        for _, _, league, season, home, away, full in by_time[at]:
            if full:
                count = segments[f"{league}|{season}"]
                count["full_xi_with_3_prior_sheets_proxy"] += int(min(past[home], past[away]) >= 3)
                count["full_xi_with_10_prior_sheets_proxy"] += int(
                    min(past[home], past[away]) >= 10
                )
        for _, _, _, _, home, away, full in by_time[at]:
            if full:
                past[home] += 1
                past[away] += 1
    if not groups:
        errors.append({"kind": "empty_dataset"})
    return {
        "sha256": digest,
        "hash_verified_against_manifest": expected_sha is not None
        and digest == expected_sha.lower(),
        "structure_verdict": "FAIL" if errors else "PASS",
        "experiment_readiness": "INCONCLUSIVE",
        "fixtures_present": len(groups),
        "segments": dict(sorted(segments.items())),
        "errors": errors,
        "limitations": [
            "No official fixture inventory: missing entire fixtures/seasons cannot be certified.",
            "No announced_at/captured_at/created_at/decision_at: no temporal availability proof.",
            "Prior sheets use earlier kickoff across supplied leagues, not confirmed completion.",
            "One provider namespace per input; IDs from multiple providers must not be mixed.",
            "No model fitting, outcome performance analysis, or automatic adoption decision.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", type=Path)
    parser.add_argument("--expected-sha256")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.csv.read_bytes(), args.expected_sha256)
    args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(
        json.dumps(
            {
                k: result[k]
                for k in ("structure_verdict", "experiment_readiness", "fixtures_present")
            }
        )
    )
    return int(result["structure_verdict"] == "FAIL")


if __name__ == "__main__":
    raise SystemExit(main())
