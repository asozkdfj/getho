"""Betman paper-betting research, stage A: price import, event mapping and
purchasability (docs/qa/2026-10-20-betman-profit-simulator-development-spec.md)."""

import json
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from edge_api.betman_rules import BY_KEY, RULES_VERSION
from edge_api.db.models import (
    BetmanAlias,
    BetmanEventMapping,
    BetmanImport,
    BetmanOddsSnapshot,
    Fixture,
)
from edge_api.services import betman
from edge_api.services.betman import EventKey
from edge_ingestion.betman import BetmanImportError, parse, store

HEADER = (
    "product,round_id,event_number,league,country,home,away,kickoff_at,sale_close_at,"
    "sale_status,single_allowed,odds_home,odds_draw,odds_away,observed_at"
)


def _upcoming(s, now, n=2):
    """Upcoming mock fixtures of one league (distinct kickoffs)."""
    fixtures = s.scalars(
        select(Fixture)
        .where(Fixture.kickoff_at > now + timedelta(hours=6), Fixture.status == "scheduled")
        .order_by(Fixture.kickoff_at, Fixture.id)
    ).all()
    league = fixtures[0].league_id
    return [f for f in fixtures if f.league_id == league][:n]


def _row(f, event, *, rnd="2026-81", league="EPL", home="홈", away="원정", **kw):
    close = kw.get("sale_close_at", (f.kickoff_at - timedelta(minutes=10)).isoformat())
    values = {
        "product": "proto",
        "round_id": rnd,
        "event_number": event,
        "league": league,
        "country": "잉글랜드",
        "home": home,
        "away": away,
        "kickoff_at": kw.get("kickoff_at", f.kickoff_at.isoformat()),
        "sale_close_at": close,
        "sale_status": kw.get("sale_status", "on_sale"),
        "single_allowed": kw.get("single_allowed", ""),
        "odds_home": kw.get("odds_home", "2.10"),
        "odds_draw": kw.get("odds_draw", "3.20"),
        "odds_away": kw.get("odds_away", "3.05"),
        "observed_at": kw.get("observed_at", ""),
    }
    return ",".join(str(values[c]) for c in HEADER.split(","))


def _csv(*rows):
    return "\n".join([HEADER, *rows]) + "\n"


def _load(s, now, csv_text, **kw):
    rows = parse(csv_text, "csv", now=now, **kw)
    return store(s, "mock", csv_text.encode(), rows, source_mode="file", filename="r.csv")


def _mapping(s, event, rnd="2026-81"):
    return betman.latest_mappings(s, [EventKey("proto", rnd, event)]).get(
        EventKey("proto", rnd, event)
    )


# ------------------------------------------------------------------ parsing
@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"odds_home": "1.00"}, "above 1"),
        ({"odds_home": "-2"}, "above 1"),
        ({"odds_home": "NaN"}, "not finite"),
        ({"odds_home": "2.105"}, "two decimals"),
        ({"odds_home": "", "odds_draw": "", "odds_away": ""}, "no odds"),
        ({"kickoff_at": "2026-10-24T21:00:00"}, "no UTC offset"),
        ({"sale_status": "open"}, "sale_status"),
        ({"single_allowed": "maybe"}, "single_allowed"),
    ],
)
def test_invalid_rows_reject_the_whole_file(session_factory, seeded, now, change, message):
    with session_factory() as s:
        f = _upcoming(s, now)[0]
        text_ = _csv(_row(f, 1), _row(f, 2, **change))
        with pytest.raises(BetmanImportError) as exc:
            parse(text_, "csv", now=now)
        assert any(e.startswith("row 2:") and message in e for e in exc.value.errors)
        assert s.scalar(select(func.count()).select_from(BetmanOddsSnapshot)) == 0


def test_time_and_identity_checks(session_factory, seeded, now):
    with session_factory() as s:
        f = _upcoming(s, now)[0]
        after = (f.kickoff_at + timedelta(minutes=1)).isoformat()
        future = (now + timedelta(minutes=5)).isoformat()
        cases = {
            "sale_close_at is after kickoff_at": _row(f, 1, sale_close_at=after),
            "observed_at is in the future": _row(f, 1, observed_at=future),
            "appears twice": _row(f, 1) + "\n" + _row(f, 1),
            "home and away are the same": _row(f, 1, home="같은팀", away="같은팀"),
        }
        for message, rows in cases.items():
            with pytest.raises(BetmanImportError) as exc:
                parse(_csv(rows), "csv", now=now)
            assert message in str(exc.value), message
        with pytest.raises(BetmanImportError, match="observed-now"):
            parse(_csv(_row(f, 1, observed_at=now.isoformat())), "csv", now=now, observed_now=True)


def test_times_without_offset_need_an_explicit_zone(session_factory, seeded, now):
    with session_factory() as s:
        f = _upcoming(s, now)[0]
        local = f.kickoff_at.astimezone(betman_tz()).replace(tzinfo=None)
        row = _row(
            f,
            1,
            kickoff_at=local.isoformat(),
            sale_close_at=(local - timedelta(minutes=10)).isoformat(),
        )
        (parsed,) = parse(_csv(row), "csv", now=now, assume_tz="Asia/Seoul")
        assert parsed.kickoff_at == f.kickoff_at


def betman_tz():
    from zoneinfo import ZoneInfo

    return ZoneInfo("Asia/Seoul")


def test_json_rows_are_accepted(session_factory, seeded, now):
    with session_factory() as s:
        f = _upcoming(s, now)[0]
        record = dict(zip(HEADER.split(","), _row(f, 7).split(","), strict=True))
        (parsed,) = parse(json.dumps([record]), "json", now=now)
        assert parsed.key == EventKey("proto", "2026-81", 7)
        assert parsed.odds == {
            "HOME": Decimal("2.10"),
            "DRAW": Decimal("3.20"),
            "AWAY": Decimal("3.05"),
        }


# ------------------------------------------------------------------ storing
def test_prices_are_stored_per_selection_with_their_evidence(session_factory, seeded, now):
    with session_factory() as s:
        f, g = _upcoming(s, now)
        seen = (now - timedelta(minutes=3)).isoformat()
        r = _load(s, now, _csv(_row(f, 1, observed_at=seen), _row(g, 2, home="A", away="B")))
        assert (r.events, r.snapshots, r.proxy_snapshots) == (2, 6, 3)
        rows = s.scalars(select(BetmanOddsSnapshot).order_by(BetmanOddsSnapshot.id)).all()
        assert {x.price_evidence for x in rows if x.event_number == 1} == {"observed"}
        assert {x.price_evidence for x in rows if x.event_number == 2} == {"historical_proxy"}
        assert all(x.rules_version == RULES_VERSION and x.raw_home for x in rows)
        assert s.scalar(select(BetmanImport.artifact_sha256)) is not None
        again = _load(s, now, _csv(_row(f, 1, observed_at=seen), _row(g, 2, home="A", away="B")))
        assert again.already_loaded and again.snapshots == 0
        assert s.scalar(select(func.count()).select_from(BetmanOddsSnapshot)) == 6


@pytest.mark.parametrize(
    "table", ["betman_imports", "betman_odds_snapshots", "betman_event_mappings", "betman_aliases"]
)
def test_betman_tables_are_append_only(session_factory, seeded, now, table):
    with session_factory() as s:
        f = _upcoming(s, now)[0]
        _load(s, now, _csv(_row(f, 1)))
        betman.manual_map(
            s,
            "mock",
            betman.event_info(s, EventKey("proto", "2026-81", 1)),
            f.id,
            learn_aliases=True,
        )
        s.commit()
        with pytest.raises(DBAPIError, match="append-only"):
            s.execute(text(f"DELETE FROM {table}"))
        s.rollback()


# ------------------------------------------------------------------ mapping
def test_names_alone_never_map_an_event(session_factory, seeded, now):
    """Even with our own team names, no confirmed alias -> unmatched with suggestions."""
    with session_factory() as s:
        f = _upcoming(s, now)[0]
        _load(
            s,
            now,
            _csv(_row(f, 1, league=f.league.name, home=f.home_team.name, away=f.away_team.name)),
        )
        m = _mapping(s, 1)
        assert (m.status, m.fixture_id, m.reason) == ("unmatched", None, "unknown_league_alias")
        top = m.candidates[0]
        assert top["suggestion"] and top["fixture_id"] == f.id and top["name_similarity"] == 1.0


def test_confirmed_aliases_map_the_next_round_automatically(session_factory, seeded, now):
    with session_factory() as s:
        f = _upcoming(s, now)[0]
        _load(s, now, _csv(_row(f, 1)))
        info = betman.event_info(s, EventKey("proto", "2026-81", 1))
        m = betman.manual_map(s, "mock", info, f.id, learn_aliases=True)
        assert (m.status, m.method) == ("mapped", "manual")
        assert s.scalar(select(func.count()).select_from(BetmanAlias)) == 3
        # next round, same Betman names, same pairing -> automatic
        _load(s, now, _csv(_row(f, 4, rnd="2026-82")))
        auto = _mapping(s, 4, "2026-82")
        assert (auto.status, auto.method, auto.fixture_id) == ("mapped", "auto", f.id)


def test_reversed_home_and_away_is_rejected(session_factory, seeded, now):
    with session_factory() as s:
        f = _upcoming(s, now)[0]
        _load(s, now, _csv(_row(f, 1)))
        betman.manual_map(
            s,
            "mock",
            betman.event_info(s, EventKey("proto", "2026-81", 1)),
            f.id,
            learn_aliases=True,
        )
        _load(s, now, _csv(_row(f, 2, rnd="2026-82", home="원정", away="홈")))
        m = _mapping(s, 2, "2026-82")
        assert (m.status, m.reason, m.fixture_id) == ("rejected", "home_away_reversed", None)


def test_team_aliases_are_scoped_to_their_league(session_factory, seeded, now):
    with session_factory() as s:
        f = _upcoming(s, now)[0]
        _load(s, now, _csv(_row(f, 1)))
        betman.manual_map(
            s,
            "mock",
            betman.event_info(s, EventKey("proto", "2026-81", 1)),
            f.id,
            learn_aliases=True,
        )
        # same team names under another Betman league name: no league alias, no team alias there
        _load(s, now, _csv(_row(f, 2, rnd="2026-82", league="다른리그")))
        assert _mapping(s, 2, "2026-82").reason == "unknown_league_alias"


def test_a_moved_kickoff_is_not_matched_and_cannot_be_forced(session_factory, seeded, now):
    with session_factory() as s:
        f = _upcoming(s, now)[0]
        _load(s, now, _csv(_row(f, 1)))
        betman.manual_map(
            s,
            "mock",
            betman.event_info(s, EventKey("proto", "2026-81", 1)),
            f.id,
            learn_aliases=True,
        )
        moved = (f.kickoff_at + timedelta(days=1)).isoformat()
        _load(s, now, _csv(_row(f, 2, rnd="2026-82", kickoff_at=moved, sale_close_at="")))
        assert _mapping(s, 2, "2026-82").reason == "no_fixture_in_window"
        with pytest.raises(betman.MappingError, match="kickoff differs"):
            betman.manual_map(
                s, "mock", betman.event_info(s, EventKey("proto", "2026-82", 2)), f.id
            )


def test_one_fixture_cannot_be_two_events_of_a_round(session_factory, seeded, now):
    with session_factory() as s:
        f = _upcoming(s, now)[0]
        _load(s, now, _csv(_row(f, 1), _row(f, 2, home="홈2", away="원정2")))
        betman.manual_map(
            s,
            "mock",
            betman.event_info(s, EventKey("proto", "2026-81", 1)),
            f.id,
            learn_aliases=True,
        )
        with pytest.raises(betman.MappingError, match="already mapped to event 1"):
            betman.manual_map(
                s, "mock", betman.event_info(s, EventKey("proto", "2026-81", 2)), f.id
            )
        # an automatic run that finds the same fixture for another event is ambiguous
        _load(s, now, _csv(_row(f, 3, observed_at=now.isoformat())))
        m = _mapping(s, 3)
        assert (m.status, m.reason) == ("ambiguous", "fixture_mapped_to_event_1")
        # the same event number in another round is a different event
        _load(s, now, _csv(_row(f, 1, rnd="2026-82")))
        assert _mapping(s, 1, "2026-82").status == "mapped"


def test_two_candidate_fixtures_are_ambiguous(session_factory, seeded, now):
    with session_factory() as s:
        f = _upcoming(s, now)[0]
        _load(s, now, _csv(_row(f, 1)))
        betman.manual_map(
            s,
            "mock",
            betman.event_info(s, EventKey("proto", "2026-81", 1)),
            f.id,
            learn_aliases=True,
        )
        twin = Fixture(
            provider="mock",
            provider_id="twin-1",
            league_id=f.league_id,
            season=f.season,
            kickoff_at=f.kickoff_at + timedelta(hours=1),
            home_team_id=f.home_team_id,
            away_team_id=f.away_team_id,
            status="scheduled",
        )
        s.add(twin)
        s.flush()
        _load(s, now, _csv(_row(f, 5, rnd="2026-82")))
        m = _mapping(s, 5, "2026-82")
        assert (m.status, m.reason) == ("ambiguous", "several_fixtures")
        assert {c["fixture_id"] for c in m.candidates} == {f.id, twin.id}


def test_a_manual_decision_is_not_overwritten_by_automatic_runs(session_factory, seeded, now):
    with session_factory() as s:
        f = _upcoming(s, now)[0]
        _load(s, now, _csv(_row(f, 1)))
        betman.manual_reject(s, EventKey("proto", "2026-81", 1), "not a league match")
        info = betman.event_info(s, EventKey("proto", "2026-81", 1))
        statuses = betman.auto_map(s, "mock", [info])
        assert statuses[info.key] == "rejected"
        assert _mapping(s, 1).method == "manual"
        # unchanged automatic decisions are not stored again
        betman.auto_map(s, "mock", [info])
        assert s.scalar(select(func.count()).select_from(BetmanEventMapping)) == 2


# ------------------------------------------------------------------ purchasability
def _mapped_price(s, now, **kw):
    f = _upcoming(s, now)[0]
    _load(s, now, _csv(_row(f, 1, **kw)))
    key = EventKey("proto", "2026-81", 1)
    betman.manual_map(s, "mock", betman.event_info(s, key), f.id, learn_aliases=True)
    return f, key


def test_only_an_observed_price_stored_before_the_decision_counts(session_factory, seeded, now):
    from conftest import set_test_wall_clock

    with session_factory() as s:
        f, key = _mapped_price(s, now, observed_at=(now - timedelta(minutes=1)).isoformat())
        report = betman.status_report(s, now + timedelta(minutes=1))
        assert report["selections"] == {"purchasable": 3, "blocked": 0}
        home = report["events"][0]["selections"]["HOME"]
        assert home["purchasable"] and home["break_even_probability"] == round(1 / 2.10, 4)
        # seen on Betman before the decision but stored after it
        set_test_wall_clock(s, now + timedelta(hours=1))
        late = _csv(
            _row(f, 1, odds_home="2.40", observed_at=(now - timedelta(minutes=1)).isoformat())
        )
        rows = parse(late, "csv", now=now + timedelta(hours=1))
        store(s, "mock", late.encode(), rows, source_mode="file", filename="late.csv")
        at = now + timedelta(minutes=30)
        price = betman.latest_prices(s, at)[(key, "HOME")]
        assert price.decimal_odds == Decimal("2.10")  # the later row is not visible yet
        newer = betman.latest_prices(s, now + timedelta(hours=2))[(key, "HOME")]
        assert newer.decimal_odds == Decimal("2.40")
        mapping = betman.latest_mappings(s, [key])[key]
        assert "stored_after_decision" in betman.purchase_blockers(newer, mapping, at)


def test_blockers_name_every_reason(session_factory, seeded, now):
    with session_factory() as s:
        f, key = _mapped_price(s, now, sale_status="suspended")
        price = betman.latest_prices(s, now)[(key, "HOME")]
        mapping = betman.latest_mappings(s, [key])[key]
        assert betman.purchase_blockers(price, mapping, now) == [
            "historical_proxy",
            "sale_suspended",
        ]
        after_close = f.kickoff_at - timedelta(minutes=5)
        assert "after_sale_close" in betman.purchase_blockers(price, mapping, after_close)
        assert "after_kickoff" in betman.purchase_blockers(price, mapping, f.kickoff_at)
        assert "not_mapped" in betman.purchase_blockers(price, None, now)


def test_prices_without_a_sale_close_time_are_not_purchasable(session_factory, seeded, now):
    with session_factory() as s:
        _, key = _mapped_price(s, now, sale_close_at="", observed_at=now.isoformat())
        price = betman.latest_prices(s, now)[(key, "DRAW")]
        mapping = betman.latest_mappings(s, [key])[key]
        assert betman.purchase_blockers(price, mapping, now) == ["sale_close_unknown"]


def test_unverified_rules_are_reported_not_assumed(session_factory, seeded, now):
    assert BY_KEY["sale_close"].status == "unverified"
    assert BY_KEY["tax"].status == "unverified"
    assert BY_KEY["fixed_odds_at_purchase"].status == "confirmed"
    with session_factory() as s:
        report = betman.status_report(s, now)
        assert report["rule_warnings"][0] == "rules_unverified"
        assert "sale_close" in report["rule_warnings"]
        assert "nothing is bought" in report["note"]


# ------------------------------------------------------------------ CLI
def test_cli_import_status_and_map(session_factory, seeded, now, tmp_path, capsys, monkeypatch):
    from contextlib import contextmanager

    from edge_api.config import Settings
    from edge_ingestion import betman_cli, cli

    @contextmanager
    def scope():
        with session_factory() as s:
            yield s
            s.commit()

    monkeypatch.setattr(betman_cli, "session_scope", scope)
    monkeypatch.setattr(betman_cli, "get_settings", lambda: Settings(data_provider="mock"))
    monkeypatch.setattr(betman_cli, "utcnow", lambda: now)
    with session_factory() as s:
        f = _upcoming(s, now)[0]
    path = tmp_path / "round.csv"
    path.write_text(_csv(_row(f, 1)), encoding="utf-8")

    assert cli.main(["betman-import", "--file", str(path), "--observed-now"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["stored"] and out["snapshots"] == 3 and out["mapping"] == {"unmatched": 1}

    args = ["betman-map", "--product", "proto", "--round", "2026-81", "--event", "1"]
    assert cli.main([*args, "--fixture", str(f.id), "--learn-aliases"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "mapped"

    assert cli.main(["betman-status", "--round", "2026-81", "--at", now.isoformat()]) == 0
    status = json.loads(capsys.readouterr().out)
    (event,) = status["events"]
    assert event["mapping"]["fixture_id"] == f.id
    assert all(sel["purchasable"] for sel in event["selections"].values())

    bad = tmp_path / "bad.csv"
    bad.write_text(_csv(_row(f, 2, odds_home="0.9")), encoding="utf-8")
    assert cli.main(["betman-import", "--file", str(bad)]) == 2
    assert json.loads(capsys.readouterr().out)["stored"] is False

    assert cli.main(["betman-rules"]) == 0
    assert json.loads(capsys.readouterr().out)["version"] == RULES_VERSION


def test_rules_document_matches_the_code():
    from pathlib import Path

    from edge_api.betman_rules import RULES

    doc = (Path(__file__).resolve().parents[2] / "docs/betman/RULES.md").read_text(
        encoding="utf-8"
    )
    assert RULES_VERSION in doc
    for r in RULES:
        line = next(ln for ln in doc.splitlines() if f"`{r.key}`" in ln)
        assert ("**확인**" in line) == (r.status == "confirmed"), r.key


def test_example_file_parses(now):
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "docs/betman/example-round.csv"
    rows = parse(path.read_text(encoding="utf-8"), "csv", now=now)
    assert [r.key.event_number for r in rows] == [1, 2]
    assert all(r.observed_at is None for r in rows)  # a template, never observed prices
