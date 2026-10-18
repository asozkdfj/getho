"""shadow-v1 candidate definitions (frozen with the protocol)."""

import numpy as np
import pytest

from edge_ml.market import devig
from edge_ml.shadow import BLEND_WEIGHT, DESCRIPTIVE, PRIMARY, candidates


def test_candidates_follow_their_fixed_definitions():
    prod, odds = [0.5, 0.3, 0.2], [1.8, 3.6, 5.0]
    c = candidates(prod, odds)
    assert set(c) == {*PRIMARY, *DESCRIPTIVE}
    assert c["production"] == pytest.approx(prod)
    assert c["market"] == pytest.approx(devig(odds))
    expected = BLEND_WEIGHT * np.array(prod) + (1 - BLEND_WEIGHT) * np.array(devig(odds))
    assert c["blend_w0.25"] == pytest.approx(expected.tolist())
    for probs in c.values():
        assert sum(probs) == pytest.approx(1) and min(probs) > 0


def test_calibrated_candidate_keeps_the_top_outcome_and_raises_a_favourite():
    c = candidates([0.7, 0.2, 0.1], [1.5, 4.0, 6.0])
    cal = c["production_calibrated_v1"]
    assert int(np.argmax(cal)) == 0 and cal[0] > 0.7  # frozen map b > 1


@pytest.mark.parametrize(
    ("prod", "odds"),
    [
        ([0.5, 0.3, 0.3], [2.0, 3.0, 4.0]),
        ([0.5, 0.5, 0.0], [2.0, 3.0, 4.0]),
        ([0.5, 0.3], [2, 3, 4]),
    ],
)
def test_invalid_inputs_are_refused(prod, odds):
    with pytest.raises(ValueError):
        candidates(prod, odds)
