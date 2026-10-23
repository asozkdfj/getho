# Claude development role

Use the latest main as the baseline for a new feature branch. Develop features and model candidates on a separate claude/ branch, not directly on main. Open a pull request with a change summary, tests actually run, risk assessment, and model impact. Address CI and independent Codex QA findings in subsequent PR commits. Do not claim better predictive accuracy without matched, leakage-free walk-forward evaluation. Do not automatically merge or deploy; the user makes the final decision.
