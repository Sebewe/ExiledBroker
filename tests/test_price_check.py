"""Price check (docs/price-check.md, workstreams B and C): past leagues' paths
(services/price_paths.py), the page's two documents (services/price_check.py) and
their endpoints, on the real-data replay (Mirage's first 30 hours) and synthetic paths."""

import math
from datetime import datetime

import polars as pl
import pytest

from exiledbroker.analysis import price_outlook as po
from exiledbroker.services import price_check, price_paths
from exiledbroker.storage import db
from test_api import LEAGUE, client, update  # noqa: F401
from test_currency_exchange import FakeExchange
from test_live_pipeline import LAUNCH, PAGES, settings  # noqa: F401
from test_performance import _add_past_leagues
from test_price_outlook import _league


@pytest.fixture
def loaded(settings):  # noqa: F811
    update(settings, FakeExchange(PAGES, now=LAUNCH), 30)
    return settings


# --- Past leagues' paths ---------------------------------------------------------------


def _rows(leagues: dict[str, float]) -> pl.DataFrame:
    """Synthetic leagues where item x falls by `drop` a day in Divines, y stays flat."""
    out = []
    for name, drop in leagues.items():
        prices, clock = _league(
            name,
            {
                "x": ("currency", lambda h, d=drop: 100.0 * math.exp(-d * h / 24)),
                "y": ("currency", lambda h: 10.0),
            },
        )
        out.append(po.hourly_rows(prices, clock))
    return pl.concat(out)


def test_served_paths_are_the_medians_of_each_leagues_own_path():
    rows = _rows({"A": 0.1, "B": 0.2, "C": 0.6})
    per_league = pl.concat(
        [
            price_paths.league_paths(rows.filter(league=lg)).with_columns(league=pl.lit(lg))
            for lg in ("A", "B", "C")
        ]
    )
    got = price_paths.medians(per_league)
    want, _ = po.build(rows)  # the research's paths, from the rows themselves
    want = want.pivot(on="horizon", index=["item_id", "bin"], values=["path", "leagues"])
    joined = got.join(want, on=["item_id", "bin"])
    assert joined.height == got.height == want.height
    assert (joined["h24"] - joined["path_h24"]).abs().max() < 1e-5
    assert (joined["h24_leagues"] == joined["leagues_h24"]).all()
    x = got.filter(item_id="x", bin=4)
    assert x["h24"][0] == pytest.approx(-0.2, abs=1e-4) and x["h24_leagues"][0] == 3
    assert x["d3"][0] == pytest.approx(-0.6, abs=1e-4)
    # One league is no path: under MIN_LEAGUES nothing is kept.
    one = price_paths.medians(per_league.filter(league="A"))
    assert one.is_empty()


def test_capture_rebuild_and_fit_on_the_database(loaded, monkeypatch):
    """Mirage and a copy of it (identical paths), captured, rebuilt and fitted. The
    replay's 30 hours hold no 24-hour forward change (it needs 36), so the horizons
    are shortened to 6 and 12 hours here."""
    monkeypatch.setattr(po, "HORIZONS", {"h24": 6, "d3": 12})
    _add_past_leagues(loaded, 1)
    with db.session(loaded.db_path) as con:
        rows = pl.concat([price_paths.capture(con, lg) for lg in ("Past1", LEAGUE)])
        assert price_paths.captured(con) == ["Past1", LEAGUE]
        n = price_paths.rebuild(con)
        paths = db.frame(con, "SELECT * FROM price_path")
        mirage = db.frame(con, "SELECT * FROM price_path_league WHERE league = ?", [LEAGUE])
        assert price_paths.fit(con, rows, ["Past1", LEAGUE]) > 0
        consts = db.frame(con, "SELECT * FROM price_path_constant")
    assert n == paths.height > 0 and (paths["h24_leagues"].drop_nulls() == 2).all()
    # Two identical leagues: the median is each league's own path.
    own = mirage.filter(pl.col("h24") != "[]")["h24"][0]
    item = mirage.filter(pl.col("h24") != "[]")["item_id"][0]
    first = next(i for i, v in enumerate(pl.Series([own]).str.json_decode()[0]) if v is not None)
    got = paths.filter(item_id=item, bin=first)["h24"][0]
    assert got == pytest.approx(pl.Series([own]).str.json_decode()[0][first])
    assert set(consts["phase"]) == {"days 0-2"} and (consts["leagues"] == f"Past1,{LEAGUE}").all()


def test_refresh_waits_for_the_fortnight_and_captures_once(loaded, monkeypatch):
    with db.session(loaded.db_path) as con:
        assert price_paths.refresh(con, LEAGUE) is None  # 30 hours in: not over
        monkeypatch.setattr(price_paths.launch_picks, "_fortnight_over", lambda c, lg: True)
        assert price_paths.refresh(con, LEAGUE) == LEAGUE
        assert price_paths.captured(con) == [LEAGUE]  # no 24-hour change yet: a marker
        assert price_paths.rebuild(con) == 0
        assert price_paths.refresh(con, LEAGUE) is None  # already captured
        assert price_paths.refresh(con, None) is None


# --- The outlook ------------------------------------------------------------------------

CONSTS = {
    (phase, thick, h): {"weight": 1.0, "low": -0.1, "high": 0.1}
    for phase, _, _ in po.PHASES
    for thick in (False, True)
    for h in po.HORIZONS
}


def test_a_horizon_says_which_state_it_is_in():
    def look(day, path=-0.2, thick=True, priced=True, last=25):
        return price_check.horizon("h24", day, thick, priced, path, 3, CONSTS, last)

    sell = look(1.0)
    assert sell["verdict"] == "sell" and sell["state"] == "judged" and sell["leagues"] == 3
    assert sell["typical"] == pytest.approx(math.expm1(-0.2))
    assert sell["low"] == pytest.approx(math.expm1(-0.3))
    assert sell["high"] == pytest.approx(math.expm1(-0.1))
    assert look(1.0, path=0.2, thick=True)["verdict"] == "none"  # no thick hold on days 0–2
    assert look(1.0, path=0.2, thick=False)["verdict"] == "hold"
    assert look(1.0, path=-0.02)["verdict"] == "none"  # under the threshold, with a band
    assert look(1.0, path=-0.02)["low"] is not None
    assert look(1.0, priced=False)["verdict"] == "none"  # no price now: no call
    assert look(9.0, path=-0.5, thick=False)["verdict"] == "none"  # thin after day 7
    for later in (14.0, 30.0, 13.5):  # past day 13, or past the last bin with a path
        h = look(later)
        assert h["state"] == "later" and h["verdict"] == "none" and h["low"] is None
    assert look(13.0, last=25)["state"] == "later"  # bin 26 > 25
    missing = look(1.0, path=None)
    assert missing["state"] == "no_history" and missing["typical"] is None


# --- The endpoints ----------------------------------------------------------------------


def _synthetic_paths(s, path: float) -> None:
    """Every listed item's path at the replay's bin, and the constants (as if built)."""
    with db.session(s.db_path) as con:
        ids = [r[0] for r in db.rows(con, "SELECT DISTINCT item_id FROM cross_market_hour")]
        for bin_ in range(30):
            for i in ids:
                con.execute(
                    "INSERT INTO price_path VALUES (?, ?, ?, 3, ?, 3)", [i, bin_, path, path]
                )
        for (phase, thick, h), c in CONSTS.items():
            con.execute(
                "INSERT INTO price_path_constant VALUES (?, ?, ?, ?, ?, ?, 'A,B,C', ?)",
                [phase, thick, h, c["weight"], c["low"], c["high"], datetime(2026, 10, 25)],
            )


def test_the_list_and_an_item_without_paths(client, loaded):  # noqa: F811
    doc = client.get(f"/api/price-check/{LEAGUE}").json()
    assert doc["league"] == LEAGUE and doc["latest_hour"].endswith("Z")
    assert 1 < doc["day_offset"] < 1.5
    assert doc["items"] and doc["movers_mode"] == "moves"
    assert [x["name"] for x in doc["items"]] == sorted(x["name"] for x in doc["items"])
    listed = {x["item_id"]: x for x in doc["items"]}
    assert set(doc["movers"]) <= set(listed) and len(doc["movers"]) <= price_check.MOVERS
    assert all(listed[i]["change_24h"] is not None for i in doc["movers"])
    assert all(x["verdict_24h"] == "none" for x in doc["items"])
    moves = [abs(listed[i]["change_24h"]) for i in doc["movers"]]
    assert moves == sorted(moves, reverse=True)

    item_id = doc["movers"][0]
    item = client.get(f"/api/price-check/{LEAGUE}/{item_id}").json()
    assert item["item_id"] == item_id and item["name"] == listed[item_id]["name"]
    assert item["series"] and item["series"][0][0].endswith("Z")
    assert len(item["series"]) <= 30 and all(len(p) == 3 for p in item["series"])
    assert item["outlook"]["unit"] == "divine"
    for h in ("h24", "d3"):  # nothing built: no history to judge by
        assert item["outlook"][h]["state"] == "no_history"
        assert item["outlook"][h]["verdict"] == "none" and item["outlook"][h]["low"] is None
    assert item["stack"]["chaos"]["volume_h"] > 0
    assert item["launch_premium"] is None and item["hours"] is None


def test_unknown_items_and_leagues_are_404(client, loaded):  # noqa: F811
    assert client.get("/api/price-check/Nowhere").status_code == 404
    assert client.get(f"/api/price-check/Nowhere/{'currency:orb-of-alchemy'}").status_code == 404
    for item in ("currency:nope", "currency:chaos-orb", "ninja:12345"):
        r = client.get(f"/api/price-check/{LEAGUE}/{item}")
        assert r.status_code == 404, item


def test_calls_from_past_leagues_paths(client, loaded):  # noqa: F811
    _synthetic_paths(loaded, -0.2)
    doc = client.get(f"/api/price-check/{LEAGUE}").json()
    assert doc["movers_mode"] == "calls" and doc["movers"]
    listed = {x["item_id"]: x for x in doc["items"]}
    assert all(listed[i]["verdict_24h"] == "sell" for i in doc["movers"])
    item = client.get(f"/api/price-check/{LEAGUE}/{doc['movers'][0]}").json()
    h24 = item["outlook"]["h24"]
    assert h24["state"] == "judged" and h24["verdict"] == "sell" and h24["leagues"] == 3
    assert h24["low"] < h24["typical"] < h24["high"]


def test_no_call_falls_back_to_the_biggest_moves(client, loaded):  # noqa: F811
    _synthetic_paths(loaded, -0.01)  # every path under the thresholds
    doc = client.get(f"/api/price-check/{LEAGUE}").json()
    assert doc["movers_mode"] == "moves" and doc["movers"]
