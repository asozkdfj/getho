import pytest

from edge_ml.experiments import get_param, set_param
from edge_ml.model import ModelParams
from edge_ml.promotion import PromotionPolicy, decide


def _report(diff, lo, hi, brier=-0.001, ece_c=0.02, ece_p=0.02, n=1000):
    return {
        "n_matches": n,
        "models": {
            "production": {"ece": ece_p},
            "candidate": {
                "ece": ece_c,
                "vs_reference": {
                    "reference": "production",
                    "log_loss": {"mean_diff": diff, "ci_low": lo, "ci_high": hi},
                    "brier": {"mean_diff": brier, "ci_low": 0, "ci_high": 0},
                },
            },
        },
    }


def test_promotes_clear_improvement():
    d = decide(_report(-0.004, -0.007, -0.001))
    assert d.promote and d.reasons == ["all promotion checks passed"]


def test_promotes_material_gain_even_if_ci_touches_zero():
    assert decide(_report(-0.003, -0.006, 0.0005)).promote


def test_rejects_noise_level_gain():
    d = decide(_report(-0.0002, -0.0016, 0.0012))
    assert not d.promote and "too small" in d.reasons[0]


@pytest.mark.parametrize(
    ("kwargs", "fragment"),
    [
        ({"brier": 0.001}, "Brier"),
        ({"ece_c": 0.05}, "calibration"),
        ({"n": 100}, "too few"),
    ],
)
def test_rejects_on_other_checks(kwargs, fragment):
    d = decide(_report(-0.004, -0.007, -0.001, **kwargs))
    assert not d.promote and any(fragment in r for r in d.reasons)


def test_rejects_wrong_reference_or_missing_models():
    r = _report(-0.004, -0.007, -0.001)
    r["models"]["candidate"]["vs_reference"]["reference"] = "base_rate"
    assert not decide(r).promote
    assert not decide({"n_matches": 1, "models": {}}).promote


def test_policy_is_configurable():
    assert decide(
        _report(-0.0015, -0.003, 0.001), policy=PromotionPolicy(min_log_loss_gain=0.001)
    ).promote


def test_set_and_get_nested_params():
    p = set_param(ModelParams(), "elo.k_factor", 30.0)
    assert get_param(p, "elo.k_factor") == 30.0 and ModelParams().elo.k_factor == 20.0
    assert get_param(set_param(p, "poisson_weight", 0.4), "poisson_weight") == 0.4
