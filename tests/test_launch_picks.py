from datetime import datetime, timedelta

import pytest

from exiledbroker.normalize.exchange_loader import SOURCE as HOURLY
from exiledbroker.services import launch_picks as lpk
from exiledbroker.storage import db

LEAGUES = ["L5", "L4", "L3", "L2", "L1"]  # newest first
DIVINE_CHAOS = 100.0
# One hour in each window and the sale (day offsets), plus the last day (a complete
# fortnight).
HOURS = {"day1": 0.5, "days2_4": 2.5, "days5_10": 6.5, "sell": 12.5}


def _item(con, item_id: str, name: str) -> None:
    con.execute(
        "INSERT INTO item (id, game, canonical_name, category) VALUES (?, 'poe1', ?, 'currency')",
        [item_id, name],
    )
    con.execute(
        "INSERT INTO tracked_item (item_id, group_id, group_label, sort_order)"
        " VALUES (?, 'currency', 'Currency', 1)",
        [item_id],
    )


def _price(con, league: str, item_id: str, day_offset: float, divine: float, per_day_div: float):
    """One hour; its volume makes `per_day_div` Divines traded a day in its window."""
    start = datetime(2026, 1, 1) + timedelta(days=30 * int(league[1:]))
    days = {0.5: 1, 2.5: 3, 6.5: 6, 12.5: 3, 13.5: 1}[day_offset]
    chaos = divine * DIVINE_CHAOS
    con.execute(
        "INSERT INTO price_observation (item_id, league_id, observed_at, day_offset, chaos_value,"
        " divine_value, source, volume, chaos_volume) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            item_id,
            league,
            start + timedelta(days=day_offset),
            day_offset,
            chaos,
            divine,
            HOURLY,
            per_day_div * days / divine,
            per_day_div * days * DIVINE_CHAOS,
        ],
    )


def _series(con, league, item_id, buy: float, sell: float, liquid: float = 100.0):
    for w, offset in HOURS.items():
        _price(con, league, item_id, offset, sell if w == "sell" else buy, liquid)


def _rebuild(con) -> dict[str, int]:
    """Reduce every complete league to its Launch history, then rank from it."""
    leagues = lpk.complete_leagues(con)
    for lg in leagues:
        lpk.capture(con, lg)
    return lpk.build(con, leagues)


@pytest.fixture
def con(tmp_path):
    with db.session(tmp_path / "t.duckdb") as c:
        db.init_schema(c)
        for i, name in enumerate(reversed(LEAGUES)):
            c.execute(
                "INSERT INTO league (id, game, name, start_at, kind) VALUES (?, 'poe1', ?, ?,"
                " 'challenge')",
                [name, name, datetime(2026, 1, 1) + timedelta(days=30 * (i + 1))],
            )
        items = {
            "currency:chaos-orb": "Chaos Orb",
            "currency:riser": "Riser",
            "currency:steady": "Steady",
            "currency:league-coin": "League Coin",
            "currency:pricey": "Pricey",
            "currency:thin": "Thin",
            "currency:faller": "Faller",
        }
        for item_id, name in items.items():
            _item(c, item_id, name)
        for lg in LEAGUES:
            # Chaos loses half its value against Divines by the sale.
            _series(c, lg, "currency:chaos-orb", 0.01, 0.005)
            _price(c, lg, "currency:chaos-orb", 13.5, 0.005, 100.0)
            _series(c, lg, "currency:riser", 0.1, 0.3)  # ×3 everywhere
            _series(c, lg, "currency:steady", 0.1, 0.15)  # ×1.5 everywhere
            _series(c, lg, "currency:pricey", 5.0, 15.0)  # ×3, but 5 div each
            _series(c, lg, "currency:thin", 0.1, 0.5, liquid=5.0)  # ×5, barely trades
            _series(c, lg, "currency:faller", 0.1, 0.05)  # halves
        _series(c, "L5", "currency:league-coin", 0.1, 2.0)  # ×20, one league only
        yield c


def test_ranks_affordable_carried_over_risers(con):
    assert lpk.complete_leagues(con) == LEAGUES
    rows = _rebuild(con)
    assert rows == {"launch_window": 3, "launch_pick": 6, "launch_pick_league": 30}

    board = lpk.launch_board(con)
    assert [w["window_id"] for w in board] == ["day1", "days2_4", "days5_10"]
    day1 = board[0]
    # League currency (one league), the 5-div item, the thin one and the faller drop out.
    assert [p["name"] for p in day1["picks"]] == ["Riser", "Steady"]
    riser = day1["picks"][0]
    assert riser["growth"] == pytest.approx(3.0) and riser["worst"] == pytest.approx(3.0)
    assert (riser["rose"], riser["traded"], riser["rank"]) == (5, 5, 1)
    assert [lg["league"] for lg in riser["leagues"]] == LEAGUES
    assert day1["chaos_growth"] == pytest.approx(0.5)
    assert day1["leagues"] == LEAGUES and day1["candidates"] == 2


def test_recency_weights_the_newest_league_most(con):
    # In the newest league Steady jumped; in the oldest it fell just as far.
    con.execute(
        "UPDATE price_observation SET divine_value = 0.4 WHERE item_id = 'currency:steady'"
        " AND league_id = 'L5' AND day_offset = 12.5"
    )
    con.execute(
        "UPDATE price_observation SET divine_value = 0.025 WHERE item_id ="
        " 'currency:steady' AND league_id = 'L1' AND day_offset = 12.5"
    )
    _rebuild(con)
    steady = next(p for p in lpk.launch_board(con)[0]["picks"] if p["name"] == "Steady")
    assert steady["growth"] > 1.5  # ×4 newest outweighs ×0.25 oldest
    assert steady["rose"] == 4 and steady["worst"] == pytest.approx(0.25)


def test_a_running_league_is_not_a_reference_until_its_fortnight_ends(con):
    con.execute("DELETE FROM price_observation WHERE league_id = 'L5' AND day_offset >= 12")
    assert lpk.complete_leagues(con) == LEAGUES[1:]


def test_live_prices_only_from_recent_hours(con):
    _rebuild(con)
    # The newest league's latest hour is its day-14 Chaos row; Riser last traded on
    # day 12.5, more than LIVE_HOURS before it.
    picks = lpk.launch_board(con)[0]["picks"]
    assert {p["name"]: p["live_divine"] for p in picks} == {"Riser": None, "Steady": None}
    _price(con, "L5", "currency:riser", 13.5, 0.31, 100.0)
    riser = lpk.launch_board(con)[0]["picks"][0]
    assert riser["live_divine"] == pytest.approx(0.31)


def test_an_empty_database_has_no_board(con):
    con.execute("DELETE FROM price_observation")
    assert lpk.complete_leagues(con) == []
    assert lpk.build(con, []) == dict.fromkeys(lpk.TABLES, 0)
    assert lpk.launch_board(con) == []


def test_the_history_is_small_and_ranks_the_same(con):
    """Each league is reduced to one row per item and window; ranking from it gives
    what ranking straight from the hourly rows did (the expectations above)."""
    assert lpk.capture(con, "L5") == 7 * 4  # 7 items (League Coin included) × 4 windows
    assert lpk.capture(con, "L5") == 7 * 4  # replaced, not added to
    assert db.scalar(con, "SELECT count(*) FROM launch_history") == 28
    for lg in LEAGUES[1:]:
        lpk.capture(con, lg)
    con.execute("DELETE FROM price_observation")  # the hourly history isn't needed now
    lpk.build(con)
    assert [p["name"] for p in lpk.launch_board(con)[0]["picks"]] == ["Riser", "Steady"]


def test_refresh_captures_once_and_rebuilds_when_the_references_change(con):
    assert lpk.refresh(con) == LEAGUES
    assert lpk.refresh(con) is None  # nothing new
    # A new league (L6) runs: not a reference while in its fortnight, even once it has
    # reached the sale days, until they're over.
    con.execute(
        "INSERT INTO league (id, game, name, start_at, kind) VALUES ('L6', 'poe1', 'L6', ?,"
        " 'challenge')",
        [datetime(2026, 1, 1) + timedelta(days=180)],
    )
    for item in ("currency:chaos-orb", "currency:riser", "currency:steady"):
        _series(con, "L6", item, 0.1, 0.2)
    _price(con, "L6", "currency:chaos-orb", 13.5, 0.005, 100.0)
    assert lpk.refresh(con, live="L6") is None
    assert "L6" not in lpk.captured_leagues(con)
    con.execute(
        "INSERT INTO price_observation (item_id, league_id, observed_at, day_offset, chaos_value,"
        " divine_value, source, volume, chaos_volume) VALUES ('currency:chaos-orb', 'L6', ?,"
        " 14.5, 1, 0.005, ?, 1, 1)",
        [datetime(2026, 7, 15), HOURLY],
    )
    assert lpk.refresh(con, live="L6") == ["L6", *LEAGUES[:4]]  # the oldest drops out
    assert lpk.windows(con)["leagues"][0] == "L6,L5,L4,L3,L2"
