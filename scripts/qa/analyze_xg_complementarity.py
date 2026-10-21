"""Explain frozen xG candidate differences; never fit or select a new candidate."""

import argparse
import gzip
import hashlib
import json
import math
from pathlib import Path

from scripts.qa.analyze_draw_discrimination import auc
from scripts.qa.analyze_paired_market import metrics, winner

REFERENCE = 'sot_and_finishing'
CANDIDATE = 'sot_finishing_plus_xg'
MODELS = ('production', REFERENCE, 'xg_and_finishing', CANDIDATE)


def analyze(rows):
    keys = [(r['league'], r['season'], r['kickoff_at'], r['home'], r['away']) for r in rows]
    if len(keys) != len(set(keys)):
        raise ValueError('duplicate fixture')
    for r in rows:
        if r['outcome'] not in (0, 1, 2):
            raise ValueError('invalid outcome')
        for model in MODELS:
            p = r[model]
            if len(p) != 3 or any(not math.isfinite(v) or not 0 <= v <= 1 for v in p):
                raise ValueError('invalid probability')
            if abs(sum(p) - 1) > 2e-6:
                raise ValueError('invalid probability sum')
    result = {}
    for season in ('2024-25', '2025-26'):
        selected = [r for r in rows if r['season'] == season]
        if not selected:
            continue
        changed = [r for r in selected if winner(r[REFERENCE]) != winner(r[CANDIDATE])]
        def correct(r, model):
            return winner(r[model]) == r['outcome']
        def delta(r):
            y = r['outcome']
            return math.log(max(r[REFERENCE][y], 1e-15)) - math.log(
                max(r[CANDIDATE][y], 1e-15)
            )
        result[season] = {
            'n': len(selected), 'metrics': {m: metrics(selected, m) for m in MODELS},
            'changed_top_outcome': len(changed),
            'corrected_errors': sum(correct(r, CANDIDATE) for r in changed),
            'introduced_errors': sum(correct(r, REFERENCE) for r in changed),
            'changed_but_both_wrong': sum(
                not correct(r, REFERENCE) and not correct(r, CANDIDATE) for r in changed
            ),
            'll_improved_games': sum(delta(r) < 0 for r in selected),
            'll_worsened_games': sum(delta(r) > 0 for r in selected),
            'outcome_ll_contributions': {
                str(y): sum(delta(r) for r in selected if r['outcome'] == y) / len(selected)
                for y in range(3)
            },
            'draw_auc': {
                m: auc([r[m][1] for r in selected], [r['outcome'] == 1 for r in selected])
                for m in MODELS
            },
            'changed_metrics': {m: metrics(changed, m) for m in (REFERENCE, CANDIDATE)},
        }
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('predictions', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    raw = args.predictions.read_bytes()
    result = {
        'status': 'DESCRIPTIVE_ONLY_NO_RETUNING_OR_PROMOTION',
        'segments': analyze([
            json.loads(line) for line in gzip.decompress(raw).decode().splitlines()
        ]),
        'predictions_sha256': hashlib.sha256(raw).hexdigest(),
        'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'limitations': [
            'Already explored periods; no new holdout, no candidate changes.',
            'No source CSV replay; xG availability uses kickoff+3h proxy.',
            'Outcome decomposition is retrospective, not a usable selection rule.',
            'No significance claims for subgroup counts or AUC differences.',
        ],
    }
    args.out.write_text(json.dumps(result, indent=2) + '\n', encoding='utf8', newline='\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
