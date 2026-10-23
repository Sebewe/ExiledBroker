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
    leagues = lpk.complete_leagues(con)
    assert leagues == LEAGUES
    rows = lpk.build(con, leagues)
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
    lpk.build(con, lpk.complete_leagues(con))
    steady = next(p for p in lpk.launch_board(con)[0]["picks"] if p["name"] == "Steady")
    assert steady["growth"] > 1.5  # ×4 newest outweighs ×0.25 oldest
    assert steady["rose"] == 4 and steady["worst"] == pytest.approx(0.25)


def test_a_running_league_is_not_a_reference_until_its_fortnight_ends(con):
    con.execute("DELETE FROM price_observation WHERE league_id = 'L5' AND day_offset >= 12")
    assert lpk.complete_leagues(con) == LEAGUES[1:]


def test_live_prices_only_from_recent_hours(con):
    lpk.build(con, lpk.complete_leagues(con))
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
