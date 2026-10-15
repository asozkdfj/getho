from __future__ import annotations

import subprocess
from functools import lru_cache

from edge_api.config import get_settings


@lru_cache
def resolve_git_sha() -> str:
    """GIT_SHA env (set by Docker/CI) -> local `git rev-parse` -> 'unknown'."""
    configured = get_settings().git_sha
    if configured:
        return configured[:40]
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short=12", "HEAD"],
            capture_output=True,
            text=True,
            timeout=2,
            check=True,
        )
        return out.stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"
