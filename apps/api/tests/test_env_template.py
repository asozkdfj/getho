"""Guards for .env.example (it is copied verbatim to .env by developers)."""

import re
from pathlib import Path

from edge_api.config import Settings

TEMPLATE = Path(__file__).resolve().parents[3] / ".env.example"
LINES = [ln for ln in TEMPLATE.read_text().splitlines() if ln and not ln.startswith("#")]


def test_no_inline_comments():
    # docker compose reads `KEY=   # note` as the literal value "# note".
    offenders = [ln for ln in LINES if re.search(r"\s#", ln)]
    assert offenders == []


def test_template_values_are_valid_settings(monkeypatch):
    for line in LINES:
        key, _, value = line.partition("=")
        monkeypatch.setenv(key, value)
    settings = Settings(_env_file=None)
    assert settings.data_provider == "mock"
    assert settings.api_football_leagues == "all" and settings.odds_lookahead_days is None
    assert settings.api_football_key is None
