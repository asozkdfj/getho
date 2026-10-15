"""edge_ml - pure probability/market math for EPL Edge Lab.

This package has NO database, HTTP or provider dependencies so it can be
unit-tested in isolation and later moved to its own service/repo.
"""

from edge_ml.core import MatchResult, Outcome, Probabilities1X2

__all__ = ["MatchResult", "Outcome", "Probabilities1X2"]
