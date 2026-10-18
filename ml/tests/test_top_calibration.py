import numpy as np
import pytest

from edge_ml.calibration import TopOutcomeCalibrator, _pav
from edge_ml.core import Outcome, Probabilities1X2


def test_pav_is_monotone_and_pools_violations():
    xs, ys = _pav([0.1, 0.2, 0.3, 0.4], [0, 1, 0, 1])
    assert ys == sorted(ys)
    assert xs == [0.1, 0.25, 0.4] and ys == [0.0, 0.5, 1.0]


@pytest.mark.parametrize("method", ["logistic", "isotonic"])
def test_learns_that_favourites_win_more_often(method):
    rng = np.random.default_rng(0)
    top = rng.uniform(0.35, 0.85, 20_000)
    truth = np.clip(top + np.where(top > 0.6, 0.05, 0.0), 0, 1)  # favourites under-stated
    hit = rng.random(len(top)) < truth
    cal = TopOutcomeCalibrator(method).fit_arrays(top, hit)
    assert cal.map_top(0.75) > 0.77  # raised towards ~0.80
    assert abs(cal.map_top(0.45) - 0.45) < 0.03  # mid range left about where it was


@pytest.mark.parametrize("method", ["logistic", "isotonic"])
def test_rows_stay_valid_and_keep_the_top_outcome(method):
    rng = np.random.default_rng(1)
    pm = rng.dirichlet([2, 1.5, 1.8], 2000)
    hit = rng.random(2000) < pm.max(1) + 0.1
    cal = TopOutcomeCalibrator(method).fit_arrays(pm.max(1), hit)
    qm = cal.calibrate_matrix(pm)
    assert np.allclose(qm.sum(1), 1) and (qm > 0).all()
    assert (qm.argmax(1) == pm.argmax(1)).all()  # never changes the most likely outcome
    # the two other outcomes keep their ratio
    for p, q in zip(pm[:50], qm[:50], strict=True):
        k = int(p.argmax())
        a, b = (i for i in range(3) if i != k)
        assert q[a] / q[b] == pytest.approx(p[a] / p[b])


def test_identity_when_already_calibrated_and_object_api():
    rng = np.random.default_rng(2)
    top = rng.uniform(0.35, 0.85, 30_000)
    hit = rng.random(len(top)) < top
    cal = TopOutcomeCalibrator("logistic").fit_arrays(top, hit)
    assert cal.map_top(0.7) == pytest.approx(0.7, abs=0.015)
    p = Probabilities1X2(0.6, 0.25, 0.15)
    cal2 = TopOutcomeCalibrator("logistic").fit([p] * 10, [Outcome.HOME] * 7 + [Outcome.AWAY] * 3)
    assert cal2.calibrate(p).home == pytest.approx(0.7, abs=0.02)
    assert cal2.name == "top-logistic"
    with pytest.raises(ValueError):
        TopOutcomeCalibrator("magic")
