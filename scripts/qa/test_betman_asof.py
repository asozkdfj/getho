from datetime import timedelta

from conftest import set_test_wall_clock
from edge_api.services import betman
from tests.integration.test_betman import _mapped_price


def test_late_mapping_rejection_does_not_change_past_report(session_factory, seeded, now):
    with session_factory() as s:
        _, key = _mapped_price(s, now, observed_at=now.isoformat())
        at = now + timedelta(minutes=1)
        before = betman.status_report(s, at)
        assert before['selections']['purchasable'] == 3
        set_test_wall_clock(s, now + timedelta(hours=1))
        betman.manual_reject(s, key, 'later correction')
        after = betman.status_report(s, at)
        assert after == before
