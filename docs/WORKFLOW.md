# GitHub collaboration workflow

Mac Claude implements changes on feature branches and opens PRs targeting main. GitHub Actions runs the existing CI and an independent Codex code review. Codex posts a QA report on the PR; Claude addresses findings in new commits. PC1 Codex can run deeper model experiments, recording reproducible results in PRs or issues. The user reviews the evidence and approves merges. ChatGPT on iPhone reads published GitHub PRs, commits, CI runs, and QA comments, but cannot see unpushed local work.

Setup: The repository owner must add the OPENAI_API_KEY Actions secret and configure main branch protection/rulesets. This automation does not install secrets, change protection, deploy, or merge automatically. The Codex review is advisory, not a formal GitHub approval. After merging the setup PR, open a small same-repository test PR and confirm that CI, Codex, and PR comment publishing work.

Model accuracy claims require matched baseline-versus-candidate walk-forward evaluation, frozen data and as-of timing, log loss, Brier score, calibration, confidence intervals, and an honest Today's Pick decision-time replay. No automatic model promotion.
