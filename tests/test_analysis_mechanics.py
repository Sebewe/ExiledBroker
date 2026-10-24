from datetime import datetime, timedelta

import polars as pl
import pytest

from exiledbroker.analysis import mechanics as m
from exiledbroker.storage import db

LEAGUES = ["New", "Mid", "Old"]  # newest first
BKS: m.Baskets = {
    "breach": ("Breach", ["a", "b", "c"]),
    "essence": ("Essence", ["d", "e", "f"]),
    "tiny": ("Tiny", ["g", "h"]),  # under MIN_ITEMS
}


def rows(league: str, item: str, prices: dict[int, float], **kw) -> list[dict]:
    """One item's days: a Chaos price (Divines at 100c), traded every hour by default."""
    return [
        {
            "league": league,
            "item_id": item,
            "day": day,
            "chaos": p,
            "divine": p / 100,
            "chaos_volume": kw.get("cv", 2400.0),
            "hours": kw.get("hours", 24),
            "absret": kw.get("absret", 0.01),
            "day_hours": 24,
        }
        for day, p in prices.items()
    ]


def frame(rs: list[dict]) -> pl.DataFrame:
    return pl.DataFrame(rs, schema=m.ITEM_DAY_SCHEMA)


def league_days(league: str, breach: float, essence: float) -> list[dict]:
    """Breach's items grow by `breach` a day, Essence's by `essence`, over days 0–13."""
    out = []
    for item in "abc":
        out += rows(league, item, {d: 10 * breach**d for d in range(14)})
    for item in "def":
        out += rows(league, item, {d: 5 * essence**d for d in range(14)})
    for item in "gh":
        out += rows(league, item, {d: 1.0 for d in range(14)})
    return out


def test_item_days_reduces_a_leagues_hours(tmp_path):
    con = db.connect(tmp_path / "x.duckdb")
    db.init_schema(con)
    start = datetime(2026, 3, 6)
    db.execute(
        con,
        "INSERT INTO league (id, game, name, start_at, kind) VALUES ('m', 'poe1', 'Mirage', ?, 'challenge')",
        [start],
    )
    for i in ("x", "y"):
        db.execute(
            con,
            "INSERT INTO item (id, game, canonical_name, category) VALUES (?, 'poe1', ?, 'currency')",
            [i, i],
        )
    # x: 4 hours on day 0 at 1, 2, 4, 8c (rate 100c), one hour on day 1; y trades once.
    for h, p in enumerate([1.0, 2.0, 4.0, 8.0]):
        db.execute(
            con,
            "INSERT INTO cross_market_hour (league_id, item_id, observed_at, day_offset, chaos_price, chaos_volume, divine_rate) VALUES ('m', 'x', ?, ?, ?, 10, 100)",
            [start + timedelta(hours=h), h / 24, p],
        )
    db.execute(
        con,
        "INSERT INTO cross_market_hour (league_id, item_id, observed_at, day_offset, chaos_price, chaos_volume) VALUES ('m', 'x', ?, 1.0, 8, 1), ('m', 'y', ?, 0.25, 3, 1)",
        [start + timedelta(hours=24), start + timedelta(hours=6)],
    )
    d = m.item_days(con, "Mirage", ["x", "y"]).sort("item_id", "day")
    x0 = d.row(0, named=True)
    assert x0 | {"chaos": pytest.approx(3.0), "divine": pytest.approx(0.03)} == {
        "league": "Mirage",
        "item_id": "x",
        "day": 0,
        "chaos": pytest.approx(3.0),  # median of 1, 2, 4, 8
        "divine": pytest.approx(0.03),
        "chaos_volume": 150.0,
        "hours": 4,
        "absret": pytest.approx(0.6931, abs=1e-4),  # each hour doubles: |ln 2|
        "day_hours": 5,  # hours with any trade that day (x's 4 and y's 1)
    }
    x1 = d.row(1, named=True)
    assert (x1["day"], x1["hours"], x1["divine"], x1["day_hours"]) == (
        1,
        1,
        None,
        1,
    )  # no rate that hour
    assert m.item_days(con, "Mirage", []).is_empty()


def test_index_is_the_baskets_geometric_mean_over_day_0():
    days = frame(
        rows("L", "a", {0: 10, 1: 20})
        + rows("L", "b", {0: 10, 1: 5})
        + rows("L", "c", {0: 10, 1: 40})
        + rows("L", "d", {0: 10, 1: 99}, hours=3)  # too few day-0 hours for a baseline
        + rows("L", "g", {0: 1, 1: 2})
    )
    ix = m.index(days, BKS).sort("mechanic", "day")
    breach = ix.filter(mechanic="breach", day=1).row(0, named=True)
    assert breach["index"] == pytest.approx((2 * 0.5 * 4) ** (1 / 3))
    assert breach["items"] == 3
    assert ix.filter(mechanic="tiny")["index"].to_list() == [None, None]  # 1 item
    assert ix.filter(mechanic="essence").is_empty()


def test_usual_weights_recent_leagues_and_needs_two():
    days = frame(
        league_days("New", 1.0, 1.0) + league_days("Mid", 1.1, 1.0) + league_days("Old", 1.2, 1.0)
    )
    ix = m.index(days, BKS)
    u = m.usual(ix, ["Mid", "Old"]).filter(mechanic="breach", day=1).row(0, named=True)
    w_old = 0.5 ** (1 / m.HALF_LIFE)
    assert u["usual"] == pytest.approx(1.1 ** (1 / (1 + w_old)) * 1.2 ** (w_old / (1 + w_old)))
    assert (u["low"], u["high"], u["leagues"]) == (pytest.approx(1.1), pytest.approx(1.2), 2)
    assert m.usual(ix, ["Old"]).is_empty()  # one past league isn't a usual


def test_walk_forward_usual_on_leagues_that_repeat():
    days = frame(
        league_days("New", 1.1, 0.9) + league_days("Mid", 1.1, 0.9) + league_days("Old", 1.1, 0.9)
    )
    wf = m.walk_forward_usual(m.index(days, BKS), LEAGUES)
    assert set(wf["target"]) == {"New"}  # the only league with two before it
    assert wf["err_weighted"].abs().max() == pytest.approx(0, abs=1e-9)
    assert wf["in_minmax"].all()
    assert wf["err_pooled"].abs().max() > 0.1  # the two mechanics differ: pooling loses that
    # Matched baskets give the same here (every league has the same items).
    same = m.walk_forward_usual(m.index(days, BKS), LEAGUES, days=days, bks=BKS)
    assert same["err_weighted"].abs().max() == pytest.approx(0, abs=1e-9)


def test_persistence_of_a_lasting_lead():
    # In New, Breach runs 50% over its usual all fortnight; Essence and four others don't.
    extra = {f"m{i}": (f"M{i}", [f"m{i}{j}" for j in range(3)]) for i in range(5)}
    bks = BKS | extra

    def league(name: str, lead: float, tilt: float) -> list[dict]:
        out = []
        for i in range(5):
            for j in range(3):
                out += rows(
                    name, f"m{i}{j}", {d: (1 + tilt * i / 10) if d else 1.0 for d in range(14)}
                )
        for item in "abc":
            out += rows(name, item, {d: 10 * (lead if d else 1) * 1.05**d for d in range(14)})
        for item in "def":
            out += rows(name, item, {d: 5.0 for d in range(14)})
        return out

    days = frame(league("New", 1.5, 1.0) + league("Mid", 1.0, 0.0) + league("Old", 1.0, 0.0))
    p = m.persistence(m.index(days, bks), LEAGUES)
    assert p.height > 0 and p["rho"].min() > 0.9


def test_premiums_and_the_walk_forward_outlook():
    # Every league: Breach's drops are dear at launch (×3 the settled price), Essence's
    # cheap (×0.5), the others flat; the ranking repeats, so the forecast is perfect.
    extra = {f"m{i}": (f"M{i}", [f"m{i}{j}" for j in range(3)]) for i in range(3)}
    bks = BKS | extra

    def league(name: str) -> list[dict]:
        out = []
        for item in "abc":
            out += rows(name, item, {d: (30 if d < 4 else 10) for d in range(14)})
        for item in "def":
            out += rows(name, item, {d: (5 if d < 4 else 10) for d in range(14)})
        for i in range(3):
            for j in range(3):
                out += rows(name, f"m{i}{j}", {d: (10 + i if d < 1 else 10) for d in range(14)})
        return out

    days = frame(league("New") + league("Mid") + league("Old"))
    pr = m.premiums(days, bks)
    day1 = pr.filter(window="day1").sort("mechanic")
    assert dict(zip(day1["mechanic"], day1["premium"], strict=True))["breach"] == pytest.approx(3)
    assert dict(zip(day1["mechanic"], day1["premium"], strict=True))["essence"] == pytest.approx(
        0.5
    )
    assert "tiny" not in set(pr["mechanic"])  # its items have no settled price… and too few
    o = m.outlook(pr, LEAGUES).filter(mechanic="breach", window="days2_4").row(0, named=True)
    assert (o["premium"], o["worst"], o["leagues"]) == (pytest.approx(3), pytest.approx(3), 3)
    wf = m.walk_forward_outlook(pr, LEAGUES)
    first = wf.filter(window="day1").row(0, named=True)
    assert first["target"] == "New" and first["rho"] == pytest.approx(1) and first["top3"] == 3
    assert first["chance"] == pytest.approx(9 / 5)


def test_liquidity_counts_quiet_items_and_scores_easy_to_sell():
    days = frame(
        # Breach: deep, steady and always traded.
        rows("L", "a", {d: 10 for d in range(5)}, cv=24000.0, absret=0.01)
        + rows("L", "b", {d: 10 for d in range(5)}, cv=24000.0, absret=0.01)
        + rows("L", "c", {d: 10 for d in range(5)}, cv=24000.0, absret=0.01)
        # Essence: thin and jumpy; f traded only on day 0, so it counts as quiet later.
        + rows("L", "d", {d: 5 for d in range(5)}, cv=240.0, hours=6, absret=0.2)
        + rows("L", "e", {d: 5 for d in range(5)}, cv=240.0, hours=6, absret=0.2)
        + rows("L", "f", {0: 5}, cv=240.0, hours=6, absret=0.2)
    )
    liq = m.liquidity(days, BKS, 1, 4).sort("mechanic")
    b, e = liq.row(0, named=True), liq.row(1, named=True)
    assert b["traded"] == 1.0 and b["item_cv_h"] == 1000.0 and b["basket_cv_h"] == 3000.0
    assert b["amihud"] == pytest.approx(0.01 / 1000)
    assert e["traded"] == pytest.approx((0.25 + 0.25 + 0) / 3)
    assert e["items"] == 3
    ranked = m.easy_to_sell(liq)
    assert ranked["mechanic"].to_list() == ["breach", "essence"]
    assert ranked["liquidity"].to_list() == [1.0, 0.5]


def test_score_and_windows():
    df = pl.DataFrame(
        {
            "mechanic": ["a", "b", "c"],
            "vs_usual": [1.3, 0.8, 1.0],
            "premium": [None, None, None],  # past day 10: the outlook drops out
            "liquidity": [0.2, 1.0, 0.6],
        }
    )
    assert m.score(df)["mechanic"].to_list() == ["a", "c", "b"]
    assert [m.window_at(d) for d in (None, 0, 1, 3, 4, 9, 10)] == [
        None,
        "day1",
        "days2_4",
        "days2_4",
        "days5_10",
        "days5_10",
        None,
    ]
