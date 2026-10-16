"""Validate v1 paired forecast JSONL. Standard library only; no network access."""

import argparse
import json
import math
from datetime import datetime
from pathlib import Path


def timestamp(value):
    stamp = datetime.fromisoformat(value)
    if stamp.utcoffset() is None:
        raise ValueError("timestamps must include UTC offset")
    return stamp


def validate(rows):
    seen = set()
    if not rows:
        raise ValueError("empty evaluation sample")
    for row in rows:
        if row["schema_version"] != 1:
            raise ValueError("unsupported schema version")
        identity = (row["fixture_id"], row["policy_id"])
        if identity in seen:
            raise ValueError("duplicate fixture/policy")
        seen.add(identity)
        decision = timestamp(row["decision_at"])
        if timestamp(row["kickoff_at"]) <= decision:
            raise ValueError("fixture already started at decision")
        if timestamp(row["result_available_at"]) <= decision:
            raise ValueError("target result already known at decision")
        if type(row["outcome"]) is not int or row["outcome"] not in (0, 1, 2):
            raise ValueError("outcome must be 0=home, 1=draw, 2=away")
        for name in ("baseline", "candidate"):
            model = row[name]
            if not model["model_id"]:
                raise ValueError("model_id required")
            trained = timestamp(model["training_data_available_through"])
            generated = timestamp(model["prediction_available_at"])
            if not trained <= generated <= decision:
                raise ValueError("model data/prediction unavailable at decision")
            p = model["probabilities"]
            if (
                len(p) != 3
                or any(
                    type(x) not in (int, float) or not math.isfinite(x) or not 0 <= x <= 1
                    for x in p
                )
                or not math.isclose(sum(p), 1, abs_tol=1e-6)
            ):
                raise ValueError("invalid 1X2 probability vector")
        names = set()
        for feature in row["features"]:
            if not feature["name"] or feature["name"] in names:
                raise ValueError("empty/duplicate feature name")
            names.add(feature["name"])
            if not feature["source"]:
                raise ValueError("feature provenance required")
            if type(feature["missing"]) is not bool:
                raise ValueError("missing must be boolean")
            if feature["missing"] != (feature["value"] is None):
                raise ValueError("missing flag and value disagree")
            if feature["missing"]:
                if feature["available_at"] is not None:
                    raise ValueError("missing feature cannot have availability timestamp")
            elif timestamp(feature["available_at"]) > timestamp(
                row["candidate"]["prediction_available_at"]
            ):
                raise ValueError("feature unavailable when candidate was generated")
    return len(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    rows = [
        json.loads(line)
        for line in args.path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    try:
        count = validate(rows)
    except (KeyError, TypeError, ValueError) as error:
        raise SystemExit(f"FAIL: {error}") from error
    print(f"PASS: {count} paired rows; structural/timestamp checks only")


if __name__ == "__main__":
    main()
