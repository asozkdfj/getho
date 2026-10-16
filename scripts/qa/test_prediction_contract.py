"""Regression checks for the exchange contract; synthetic data, not performance."""

import copy
import unittest

from check_prediction_contract import validate


def fixture():
    model = {
        "model_id": "test-only",
        "training_data_available_through": "2026-10-15T00:00:00+00:00",
        "prediction_available_at": "2026-10-16T00:00:00+00:00",
        "probabilities": [0.5, 0.3, 0.2],
    }
    return {
        "schema_version": 1,
        "fixture_id": "synthetic-1",
        "policy_id": "kst09-v1",
        "decision_at": "2026-10-16T09:00:00+09:00",
        "kickoff_at": "2026-10-16T20:00:00+09:00",
        "result_available_at": "2026-10-16T23:00:00+09:00",
        "outcome": 0,
        "baseline": copy.deepcopy(model),
        "candidate": copy.deepcopy(model),
        "features": [
            {
                "name": "rest_hours_difference",
                "value": 24,
                "missing": False,
                "source": "synthetic-schedule",
                "available_at": "2026-10-15T00:00:00+00:00",
            }
        ],
    }


class ContractTests(unittest.TestCase):
    def test_valid_cross_timezone_pair(self):
        self.assertEqual(validate([fixture()]), 1)

    def test_rejects_leaks_and_malformed_pairs(self):
        mutations = [
            lambda r: r.update(kickoff_at=r["decision_at"]),
            lambda r: r.update(decision_at="2026-10-16T09:00:00"),
            lambda r: r.update(result_available_at=r["decision_at"]),
            lambda r: r["candidate"].update(prediction_available_at=r["kickoff_at"]),
            lambda r: r["candidate"].update(training_data_available_through=r["kickoff_at"]),
            lambda r: r["candidate"].update(probabilities=[float("nan"), 0.3, 0.2]),
            lambda r: r["candidate"].update(probabilities=[0.9, 0.3, 0.2]),
            lambda r: r["features"][0].update(available_at=r["kickoff_at"]),
            lambda r: r["features"][0].update(missing=True),
            lambda r: r["features"][0].update(source=""),
            lambda r: r.pop("baseline"),
        ]
        for index, mutate in enumerate(mutations):
            with self.subTest(case=index):
                row = fixture()
                mutate(row)
                with self.assertRaises((ValueError, KeyError)):
                    validate([row])

    def test_empty_or_duplicate_sample(self):
        for rows in ([], [fixture(), fixture()]):
            with self.assertRaises(ValueError):
                validate(rows)

    def test_explicit_missing_feature(self):
        row = fixture()
        row["features"][0].update(value=None, missing=True, available_at=None)
        self.assertEqual(validate([row]), 1)


if __name__ == "__main__":
    unittest.main()
