import pytest

from scripts.qa.analyze_xg_complementarity import CANDIDATE, REFERENCE, analyze


def test_switches_count_corrections_and_new_failures_separately():
    base = {'league': 'x', 'season': '2025-26', 'kickoff_at': '2025-08-01', 'away': 'b',
            'production': [0.6, 0.1, 0.3], REFERENCE: [0.6, 0.1, 0.3],
            'xg_and_finishing': [0.3, 0.1, 0.6], CANDIDATE: [0.3, 0.1, 0.6]}
    rows = [dict(base, home=str(i), outcome=y) for i, y in enumerate([0, 1, 2])]
    out = analyze(rows)['2025-26']
    assert out['changed_top_outcome'] == 3
    assert out['corrected_errors'] == out['introduced_errors'] == 1
    assert out['changed_but_both_wrong'] == 1
    assert sum(out['outcome_ll_contributions'].values()) == pytest.approx(0)
    with pytest.raises(ValueError, match='duplicate'):
        analyze(rows + rows)
