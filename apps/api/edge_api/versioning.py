"""Which code produced a prediction or a pick.

Two identifiers, recorded together:

- ``resolve_git_sha()``: the commit, from GIT_SHA (Docker/CI build arg) or a local
  git checkout (``-dirty`` when it has uncommitted changes). Placeholders such
  as "local" are treated as unknown, never as a commit.
- ``code_fingerprint()``: SHA-256 over the source of the Python packages that
  build predictions and picks. It needs no git, so it identifies the exact code
  even when the build was not given its commit; ``edge code-fingerprint`` prints
  it for any checkout, so a fingerprint can be matched back to a commit.
"""

from __future__ import annotations

import hashlib
import importlib.util
import subprocess
from functools import lru_cache
from pathlib import Path

from edge_api.config import get_settings

UNKNOWN = "unknown"
PLACEHOLDERS = {"", "local", UNKNOWN}
PACKAGES = ("edge_ml", "edge_api", "edge_ingestion")


@lru_cache
def resolve_git_sha() -> str:
    """GIT_SHA env (set by Docker/CI) -> local `git rev-parse` -> 'unknown'."""
    configured = (get_settings().git_sha or "").strip()
    if configured.lower() not in PLACEHOLDERS:
        return configured[:40]
    return _git_checkout_sha()


def _git(*args: str) -> str:
    out = subprocess.run(["git", *args], capture_output=True, text=True, timeout=2, check=True)
    return out.stdout.strip()


def _git_checkout_sha() -> str:
    try:
        sha = _git("rev-parse", "--short=12", "HEAD")
        dirty = bool(_git("status", "--porcelain", "--untracked-files=no"))
    except (OSError, subprocess.SubprocessError):
        return UNKNOWN
    if not sha:
        return UNKNOWN
    return f"{sha}-dirty" if dirty else sha


def _package_root(name: str) -> Path | None:
    spec = importlib.util.find_spec(name)
    if spec is None or not spec.submodule_search_locations:
        return None
    return Path(next(iter(spec.submodule_search_locations)))


@lru_cache
def code_fingerprint() -> str:
    return fingerprint({name: _package_root(name) for name in PACKAGES})


def fingerprint(roots: dict[str, Path | None]) -> str:
    """SHA-256 of (package/relative path, bytes) for every .py file of the
    packages, in sorted order. Packages that are not installed are named as
    missing, so a partial install never looks like the full code."""
    h = hashlib.sha256()
    for name, root in roots.items():
        if root is None:
            h.update(f"{name}:missing\0".encode())
            continue
        for path in sorted(root.rglob("*.py"), key=lambda p: p.relative_to(root).as_posix()):
            if "__pycache__" in path.parts:
                continue
            h.update(f"{name}/{path.relative_to(root).as_posix()}\0".encode())
            h.update(path.read_bytes())
            h.update(b"\0")
    return h.hexdigest()


def build_info() -> dict[str, str]:
    return {"git_sha": resolve_git_sha(), "code_fingerprint": code_fingerprint()}
