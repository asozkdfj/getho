import logging

from edge_api.config import Settings
from edge_api.logging_setup import RedactingFormatter, redact


def test_secrets_are_not_exposed_in_repr():
    s = Settings(
        database_url="postgresql+psycopg://edge:supersecret@db:5432/edge",
        football_data_api_key="key-123",
    )
    text = repr(s) + str(s.model_dump())
    assert "supersecret" not in text
    assert "key-123" not in text
    assert s.database_url.get_secret_value().endswith("@db:5432/edge")


def test_empty_api_key_is_none_and_cors_is_split():
    s = Settings(football_data_api_key="", cors_origins="http://a.com, http://b.com")
    assert s.football_data_api_key is None
    assert s.cors_origins == ["http://a.com", "http://b.com"]


def test_settings_parse_comma_separated_cors_from_env(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:3000,https://edge.example")
    assert Settings().cors_origins == ["http://localhost:3000", "https://edge.example"]


def test_redact_connection_urls_and_keys():
    assert redact("postgresql://edge:pw@db/edge") == "postgresql://edge:***@db/edge"
    assert redact("GET /x?api_key=abc&x=1") == "GET /x?api_key=***&x=1"


def test_formatter_redacts_log_records():
    record = logging.LogRecord(
        "t", logging.INFO, __file__, 1, "url=%s", ("redis://u:pw@r:6379",), None
    )
    assert "pw" not in RedactingFormatter("%(message)s").format(record)
