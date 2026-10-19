"""Independent regression: repair a partially delivered team statistics response."""

from edge_ingestion.jobs import run_ingestion
from edge_ingestion.providers import MockProvider
from edge_ingestion.team_news import ingest_post_match


def test_second_team_statistics_are_retried(db_session, now):
    provider = MockProvider(now)
    run_ingestion(db_session, provider, now=now)
    original = provider.get_match_statistics

    def partial(ids):
        seen = set()
        result = []
        for row in original(ids):
            if row.fixture_provider_id not in seen:
                result.append(row)
                seen.add(row.fixture_provider_id)
        return result

    provider.get_match_statistics = partial
    appearances, first = ingest_post_match(db_session, provider, now=now, scope=None, limit=10000)
    assert appearances > 0 and first > 0
    provider.get_match_statistics = original
    _, repaired = ingest_post_match(db_session, provider, now=now, scope=None, limit=10000)
    assert repaired == first, (first, repaired)
