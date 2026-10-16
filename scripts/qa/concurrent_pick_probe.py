"""Four-process pick publication on an already seeded, dedicated QA test DB."""

import multiprocessing as mp
import os
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from edge_api.config import Settings
from edge_api.db.models import DailyPick
from edge_api.db.session import make_engine
from edge_api.services.picks import publish_daily_pick

MOMENT = datetime(2026, 10, 16, 10, tzinfo=UTC)


def publish(url, barrier, queue):
    engine = make_engine(url)
    barrier.wait(timeout=30)
    with Session(engine) as session:
        pick = publish_daily_pick(session, Settings(data_provider="mock"), MOMENT)
        pick_id = pick.id
        session.commit()
    queue.put(pick_id)
    engine.dispose()


if __name__ == "__main__":
    url = os.environ["TEST_DATABASE_URL"]
    parsed = make_url(url)
    assert parsed.host == "127.0.0.1" and parsed.port == 15432 and parsed.database == "edge_test"
    engine = make_engine(url)
    with Session(engine) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(DailyPick)
                .where(DailyPick.pick_date == MOMENT.date(), DailyPick.provider == "mock")
            )
            == 0
        ), "Run against a freshly seeded dedicated QA DB"
    barrier, queue = mp.Barrier(4), mp.Queue()
    processes = [mp.Process(target=publish, args=(url, barrier, queue)) for _ in range(4)]
    for process in processes:
        process.start()
    ids = [queue.get(timeout=45) for _ in processes]
    for process in processes:
        process.join(timeout=10)
        assert process.exitcode == 0
    with Session(engine) as session:
        count = session.scalar(
            select(func.count())
            .select_from(DailyPick)
            .where(DailyPick.pick_date == MOMENT.date(), DailyPick.provider == "mock")
        )
    assert len(set(ids)) == count == 1
    print({"processes": 4, "returned_ids": ids, "rows": count, "status": "PASS"})
