"""Run against PR #10 via PYTHONPATH; synthetic contract counterexamples."""

import numpy as np
import pytest

from edge_ml.calibration import TopOutcomeCalibrator


def test_logistic_map_is_nondecreasing_even_on_inverse_signal():
    cal = TopOutcomeCalibrator("logistic").fit_arrays(
        [0.4, 0.5, 0.6, 0.7, 0.8] * 20, [1, 1, 0, 0, 0] * 20
    )
    mapped = cal.map_top(np.array([0.4, 0.8]))
    assert mapped[0] <= mapped[1], (cal.params, mapped.tolist())


def test_isotonic_pools_equal_probability_observations():
    cal = TopOutcomeCalibrator("isotonic").fit_arrays([0.6, 0.6], [0, 1])
    assert float(cal.map_top(0.6)) == pytest.approx(0.5)
