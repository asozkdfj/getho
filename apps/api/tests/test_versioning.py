"""Build identification: commit placeholders and the source fingerprint."""

from pathlib import Path

import pytest

from edge_api import versioning
from edge_api.config import get_settings


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    versioning.resolve_git_sha.cache_clear()
    yield
    versioning.resolve_git_sha.cache_clear()
    get_settings.cache_clear()


def _sha_with(monkeypatch, value):
    monkeypatch.setenv("GIT_SHA", value)
    get_settings.cache_clear()
    versioning.resolve_git_sha.cache_clear()
    return versioning.resolve_git_sha()


def test_a_configured_commit_is_recorded(monkeypatch):
    assert _sha_with(monkeypatch, "0123456789ab") == "0123456789ab"


@pytest.mark.parametrize("placeholder", ["local", "unknown", "LOCAL", " "])
def test_placeholders_are_never_recorded_as_a_commit(monkeypatch, placeholder):
    """Codex readiness audit: stored model versions said git_sha = "local"."""
    monkeypatch.setattr(versioning, "_git_checkout_sha", lambda: "unknown")
    assert _sha_with(monkeypatch, placeholder) == "unknown"


def test_placeholder_falls_back_to_the_checkout(monkeypatch):
    monkeypatch.setattr(versioning, "_git_checkout_sha", lambda: "abc123def456-dirty")
    assert _sha_with(monkeypatch, "local") == "abc123def456-dirty"


def _tree(tmp_path: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return tmp_path


def test_fingerprint_follows_the_source_and_nothing_else(tmp_path):
    root = _tree(tmp_path / "a", {"__init__.py": "", "model.py": "X = 1\n"})
    base = versioning.fingerprint({"pkg": root})
    assert versioning.fingerprint({"pkg": root}) == base  # deterministic
    (root / "__pycache__").mkdir()
    (root / "__pycache__" / "model.cpython-312.py").write_text("junk")
    (root / "notes.txt").write_text("not code")
    assert versioning.fingerprint({"pkg": root}) == base  # caches and non-code ignored
    (root / "model.py").write_text("X = 2\n")
    assert versioning.fingerprint({"pkg": root}) != base  # any code change shows
    copy = _tree(tmp_path / "b", {"__init__.py": "", "model.py": "X = 2\n"})
    assert versioning.fingerprint({"pkg": copy}) == versioning.fingerprint({"pkg": root})


def test_a_missing_package_changes_the_fingerprint(tmp_path):
    root = _tree(tmp_path, {"__init__.py": ""})
    assert versioning.fingerprint({"pkg": root, "other": None}) != versioning.fingerprint(
        {"pkg": root}
    )


def test_installed_code_fingerprint_is_a_sha256():
    value = versioning.code_fingerprint()
    assert len(value) == 64 and int(value, 16) >= 0
    assert versioning.build_info()["code_fingerprint"] == value
