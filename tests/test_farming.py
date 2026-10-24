"""The Farming page's services (services/farming.py) on a small made-up world: two
baskets, a live league filled hour by hour and three past leagues in the reduced
history. Every state the page must handle: before launch, one hour, no Divine rate yet,
no history, an item that never traded against Divines, no locally built report, after
the launch fortnight; and the same answers on Postgres."""

import json
import math
import os
from datetime import datetime, timedelta

import pytest

from exiledbroker.config import Settings
from exiledbroker.normalize.tracked import currency_item_id
from exiledbroker.services import farming
from exiledbroker.services import item_history as ih
from exiledbroker.storage import db

PG_URL = os.environ.get("EB_TEST_POSTGRES_URL")
LIVE = "Live"
LAUNCHED = datetime(2026, 7, 24, 22)
PAST = {"Past3": 120, "Past2": 240, "Past1": 360}  # newest first: days before LIVE
ALPHA = ["Alpha Ember", "Alpha Shard", "Alpha Stone"]
BETA = ["Beta Fossil", "Beta Glyph", "Beta Rune"]
SHARED = "Shared Orb"  # in both baskets
NO_DIVINE = "Alpha Stone"  # never trades against Divines
BASE = {name: 10.0 * (i + 1) for i, name in enumerate([*ALPHA, *BETA, SHARED])}
RATE = 100.0  # Chaos per Divine
# A third basket for what only past leagues traded: a legacy output and a followed card
# that never trade in the live league (so the hosted site's `item` table lacks them).
GAMMA = ["Gamma Bead", "Gamma Coin", "Gamma Pearl"]
RELIC = "Gamma Relic"  # a legacy output
CARD = "The Gamma"  # a followed divination card
GAMMA_BASE = {name: 5.0 * (i + 1) for i, name in enumerate(GAMMA)}
PAST_ONLY = {RELIC: 7.0, CARD: 9.0}


def ids(names: list[str]) -> list[str]:
    return [currency_item_id(n) for n in names]


@pytest.fixture
def settings(tmp_path):
    s = Settings(data_dir=tmp_path, mechanics_file=tmp_path / "mechanics.toml")
    s.mechanics_file.write_text(
        "\n".join(
            f'[[mechanic]]\nid = "{mid}"\nname = "{mid.title()}"\noutputs = {json.dumps(names)}\n'
            for mid, names in (("alpha", [*ALPHA, SHARED]), ("beta", [*BETA, SHARED]))
        )
    )
    return s


@pytest.fixture
def gamma_settings(settings):
    """`settings` plus Gamma: three outputs, a legacy one and the followed cards."""
    with settings.mechanics_file.open("a") as f:
        f.write(
            f'[[mechanic]]\nid = "gamma"\nname = "Gamma"\noutputs = {json.dumps(GAMMA)}\n'
            f'legacy = {json.dumps([RELIC])}\ngroups = ["divination"]\n'
        )
    return settings


def report_doc() -> dict:
    """A report as `eb farming build` stores it (values made up)."""
    flat = {"gain": 0.004, "gap": 0.008, "best": 22, "worst": 6, "null95": 0.01}

    def phase(n: int) -> dict:
        effect = flat | {"verdict": "small"}
        return {
            "days": 10 * n,
            "leagues": 3,
            "price": [0.001 * (h - 12) for h in range(24)],
            "price_divine_market": [None] * 24,
            "divine": [0.0] * 24,
            "volume": None if n == 1 else [1 / 24] * 24,
            "effect": effect,
            "effect_divine_market": effect,
            "divine_effect": effect,
            "stability": 0.4,
            "mechanics": {
                "alpha": {"items": 4, "stability": 0.9, "shown": True, "price": [0.01] * 24}
                | effect,
                "beta": {"items": 4, "stability": 0.1, "shown": False, "price": [0.0] * 24}
                | effect,
            },
        }

    return {
        "leagues": ["Past1", "Past2", "Past3", LIVE],
        "phases": [["d0_2", 0, 2], ["d2_7", 2, 7], ["d7_14", 7, 14], ["later", 14, None]],
        "hours": {"d0_2": phase(1), "d2_7": phase(2), "d7_14": phase(3), "later": phase(4)},
        "impact": farming.IMPACT,
    }


def chaos_price(name: str, hour: int) -> float:
    """Every item doubles in price after its first day; Beta's halve again on day 3."""
    p = (BASE | GAMMA_BASE)[name] * (2.0 if hour >= 24 else 1.0)
    return p / 2 if name in BETA and hour >= 72 else p


def build(
    con,
    hours: int,
    *,
    rate: bool = True,
    past: bool = True,
    report: bool = True,
    gamma: bool = False,
    hosted: bool = False,
) -> None:
    """The world on `con` (DuckDB or Postgres): the live league with `hours` loaded
    hours, the past leagues' history and the report. With `gamma`, also Gamma's items,
    and its legacy output and card in past leagues only; `hosted` stores `item` and
    `tracked_item` as `eb site seed` does, with only the items the live league traded."""
    live = BASE | (GAMMA_BASE if gamma else {})
    everything = live | (PAST_ONLY if gamma else {})
    db.init_schema(con)
    db.execute(
        con,
        "INSERT INTO league (id, game, name, start_at, launched_at, kind, exchange_tracked) "
        "VALUES ('poe1-live', 'poe1', ?, ?, ?, 'challenge', TRUE)",
        [LIVE, LAUNCHED - timedelta(hours=22), LAUNCHED],
    )
    for name in live if hosted else everything:
        db.execute(
            con,
            "INSERT INTO item (id, game, canonical_name, category) VALUES (?, 'poe1', ?, 'currency')",
            [currency_item_id(name), name],
        )
    if gamma:
        db.execute(
            con,
            "INSERT INTO divination_card (item_id, name, followed) VALUES (?, ?, TRUE)",
            [currency_item_id(CARD), CARD],
        )
        if not hosted:
            db.execute(
                con,
                "INSERT INTO tracked_item (item_id, group_id, group_label, sort_order) "
                "VALUES (?, 'divination', 'Divination cards', 4)",
                [currency_item_id(CARD)],
            )
    for h in range(hours):
        for name in live:
            p = chaos_price(name, h)
            divine = None if name == NO_DIVINE else p / RATE * 1.02
            db.execute(
                con,
                "INSERT INTO cross_market_hour (league_id, item_id, observed_at, day_offset, "
                "chaos_price, chaos_volume, divine_price, divine_volume, divine_rate) "
                "VALUES ('poe1-live', ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    currency_item_id(name),
                    LAUNCHED + timedelta(hours=h),
                    h / 24,
                    p,
                    10.0 + h % 3,
                    divine,
                    None if divine is None else 1.0,
                    RATE if rate else None,
                ],
            )
    if past:
        for league, before in PAST.items():
            start = LAUNCHED - timedelta(days=before)
            for name, base in everything.items():
                for day in range(14):
                    # Every past league's index is 1 + day, alike in each basket; the
                    # items only past leagues traded rise three times as fast.
                    p = base * (1 + (3 if name in PAST_ONLY else 1) * day)
                    db.execute(
                        con,
                        f"INSERT INTO {ih.HISTORY} ({', '.join(ih.COLUMNS)}) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        [league, start, currency_item_id(name), day, p, p / RATE]
                        + [p * 240, 24, 0.02, 24],
                    )
    if report:
        farming.store_report(con, report_doc())


def serve(tmp_path, settings, hours: int, **kw) -> dict:
    with db.session(settings.db_path) as con:
        build(con, hours, **kw)
    with db.session(settings.db_path, read_only=True) as con:
        return farming.farming(con, LIVE, settings)


def by_id(rows: list[dict]) -> dict[str, dict]:
    return {r["id"]: r for r in rows}


def test_before_launch_only_the_outlook(tmp_path, settings):
    doc = serve(tmp_path, settings, 0)
    assert doc["phase"] == "pre_launch"
    assert doc["latest_hour"] is None and doc["day_offset"] is None
    assert doc["mechanics"] == [] and doc["items"] == []
    outlook = by_id(doc["outlook"])
    assert set(outlook) == {"alpha", "beta"}
    alpha = outlook["alpha"]
    assert alpha["leagues"] == 3 and set(alpha["windows"]) == {"day1", "days2_4", "days5_10"}
    # Day 1's median price over days 12–14's: 1 / 13 in every league.
    assert alpha["windows"]["day1"]["premium"] == pytest.approx(1 / 13)
    assert alpha["windows"]["day1"]["worst"] == pytest.approx(1 / 13)
    assert doc["hours"]["phase"] == "d0_2"
    assert doc["impact"] == farming.IMPACT


def test_one_hour_of_data(tmp_path, settings):
    doc = serve(tmp_path, settings, 1)
    assert doc["phase"] == "launch" and doc["day_offset"] == 0
    assert doc["latest_hour"] == (LAUNCHED).replace(tzinfo=doc["latest_hour"].tzinfo)
    alpha = by_id(doc["mechanics"])["alpha"]
    assert alpha["items"] == 4 and alpha["priced_items"] == 4
    assert alpha["index"] is None  # an item needs 6 hours on day 0 for a baseline
    assert alpha["change_24h"] is None and alpha["change_7d"] is None
    assert alpha["usual"] == pytest.approx(1.0)  # past leagues on day 0
    assert alpha["usual_low"] == pytest.approx(1.0) and alpha["usual_high"] == pytest.approx(1.0)
    assert alpha["liquidity"] is not None  # past leagues' days 1–3 before the league has 3
    assert alpha["chaos_volume_h"] == pytest.approx(sum(BASE[n] * 10 for n in [*ALPHA, SHARED]))
    item = {i["name"]: i for i in doc["items"]}["Alpha Ember"]
    assert item["chaos"]["price"] == BASE["Alpha Ember"]
    assert item["chaos"]["hours_traded"] == 1.0 and item["chaos"]["sigma_h"] is None


def test_index_usual_and_changes(tmp_path, settings):
    doc = serve(tmp_path, settings, 48)
    assert doc["phase"] == "launch" and math.floor(doc["day_offset"]) == 1
    alpha = by_id(doc["mechanics"])["alpha"]
    # Every item doubled after day 0: the index is 2 Divines on a 1 Divine base...
    assert alpha["index"] == pytest.approx(2.0)
    assert alpha["change_24h"] == pytest.approx(1.0)  # ...from 1 a day earlier
    assert alpha["change_7d"] is None  # the league is 2 days old
    assert alpha["usual"] == pytest.approx(2.0)  # past leagues on day 1: 1 + 1
    assert all(m["score"] is not None for m in doc["mechanics"])
    assert doc["hours"]["phase"] == "d0_2"
    assert list(doc["hours"]["mechanics"]) == ["alpha"]  # Beta's own profile isn't shown
    shared = {i["name"]: i for i in doc["items"]}[SHARED]
    assert shared["mechanics"] == ["alpha", "beta"]
    assert shared["divine"]["price"] == pytest.approx(BASE[SHARED] * 2 / RATE * 1.02)
    assert shared["divine"]["hours_traded"] == pytest.approx(1.0)
    assert shared["chaos"]["volume_h"] == pytest.approx(11.0)  # 10, 11, 12 in turn


def test_no_divine_rate_yet(tmp_path, settings):
    doc = serve(tmp_path, settings, 12, rate=False)
    assert doc["phase"] == "launch"
    assert all(m["index"] is None for m in doc["mechanics"])  # the index is in Divines
    assert all(i["chaos"]["price"] for i in doc["items"]) and len(doc["items"]) == 7


def test_a_single_league_has_no_history(tmp_path, settings):
    doc = serve(tmp_path, settings, 48, past=False)
    assert doc["outlook"] == []
    for m in doc["mechanics"]:
        assert m["usual"] is None and m["usual_low"] is None and m["liquidity"] is None
        assert m["index"] == pytest.approx(2.0)
    assert {m["score"] for m in doc["mechanics"]} == {None}  # no factor has values
    assert [m["id"] for m in doc["mechanics"]] == ["alpha", "beta"]


def test_an_item_never_traded_against_divines(tmp_path, settings):
    doc = serve(tmp_path, settings, 48)
    stone = {i["name"]: i for i in doc["items"]}[NO_DIVINE]
    assert stone["divine"] is None
    assert stone["chaos"]["price"] == BASE[NO_DIVINE] * 2


def test_no_report_built_yet(tmp_path, settings):
    doc = serve(tmp_path, settings, 30, report=False)
    assert doc["hours"] is None and doc["impact"] is None
    assert doc["mechanics"] and doc["outlook"]


def test_after_the_launch_fortnight(tmp_path, settings):
    doc = serve(tmp_path, settings, 15 * 24)
    assert doc["phase"] == "later" and doc["day_offset"] >= 14
    beta = by_id(doc["mechanics"])["beta"]
    assert beta["usual"] is None and beta["usual_low"] is None  # no usual after day 13
    # Beta's own drops are back at their day-0 price, the shared one still doubled.
    assert beta["index"] == pytest.approx(2**0.25) and beta["change_7d"] == pytest.approx(0.0)
    assert beta["liquidity"] is not None  # the league's own last 3 days now
    assert all(m["score"] is not None for m in doc["mechanics"])
    assert doc["hours"]["phase"] == "later" and doc["hours"]["volume"]


def test_past_leagues_keep_what_only_they_traded(tmp_path, settings, gamma_settings):
    """A legacy output and a followed card that traded only in past leagues stay in
    Gamma's past curves on the hosted site too, whose `item` and `tracked_item` hold only
    the live league's items: the usual path and the outlook match the local page's."""
    local = serve(tmp_path, gamma_settings, 48, gamma=True)
    gamma_settings.db_path.unlink()
    hosted = serve(tmp_path, gamma_settings, 48, gamma=True, hosted=True)
    gamma = by_id(local["mechanics"])["gamma"]
    # Day 1 of past leagues: three outputs at 2, the relic and the card at 4.
    assert gamma["usual"] == pytest.approx((2**3 * 4**2) ** (1 / 5))
    assert by_id(local["outlook"])["gamma"]["windows"]["day1"]["premium"] != pytest.approx(
        by_id(local["outlook"])["alpha"]["windows"]["day1"]["premium"]
    )  # the relic and the card count in the outlook too
    # The basket counts the followed card the live league hasn't traded (yet).
    assert gamma["items"] == 4 and gamma["priced_items"] == 3
    _same(local, hosted)


def test_the_page_reads_small_results(tmp_path, settings):
    """No hourly rows reach Python: the live league comes back reduced to days and
    24-hour medians, however many hours are loaded."""
    with db.session(settings.db_path) as con:
        build(con, 15 * 24)
    with db.session(settings.db_path, read_only=True) as con, db.metered() as meter:
        farming.farming(con, LIVE, settings)
    live = [q for q in meter.queries if "cross_market_hour" in q.sql]
    assert live and sum(q.rows for q in live) <= 7 * (1 + 4 + 3 + 2) + 4, [
        (q.caller, q.rows) for q in live
    ]


def test_eb_farming_build_stores_the_report(tmp_path, monkeypatch):
    """`eb farming build` on the replay (Mirage's first 30 hours): the hour-of-day
    profiles for the phases it has, the phase bounds and finding 7's impact, which the
    page then serves for the league's phase."""
    from typer.testing import CliRunner

    from exiledbroker.cli import app
    from test_api import update
    from test_currency_exchange import FakeExchange
    from test_live_pipeline import LAUNCH, PAGES, store_reference_data

    monkeypatch.setenv("EB_DATA_DIR", str(tmp_path))
    s = Settings(data_dir=tmp_path, request_min_interval=0)
    store_reference_data(s)
    update(s, FakeExchange(PAGES, now=LAUNCH), 30)
    result = CliRunner().invoke(app, ["farming", "build"])
    assert result.exit_code == 0, result.output
    with db.session(s.db_path, read_only=True) as con:
        doc = farming.report(con)
        page = farming.farming(con, "Mirage", s)
    assert doc["impact"] == farming.IMPACT and doc["leagues"] == ["Mirage"]
    assert [p[0] for p in doc["phases"]] == ["d0_2", "d2_7", "d7_14", "later"]
    assert doc["phases"][-1][2] is None  # open-ended, not Infinity
    assert set(doc["hours"]) <= {"d0_2"}  # 30 hours: the first phase at most
    assert page["impact"] == farming.IMPACT
    assert page["hours"] is None or page["hours"]["phase"] == "d0_2"


def _same(a, b, path=""):
    if isinstance(a, dict):
        assert a.keys() == b.keys(), path
        for k in a:
            _same(a[k], b[k], f"{path}.{k}")
    elif isinstance(a, list):
        assert len(a) == len(b), path
        for i, (x, y) in enumerate(zip(a, b, strict=True)):
            _same(x, y, f"{path}[{i}]")
    elif isinstance(a, float):
        assert b == pytest.approx(a, rel=1e-9, abs=1e-12), path
    else:
        assert a == b, path


@pytest.mark.skipif(not PG_URL, reason="EB_TEST_POSTGRES_URL is not set")
@pytest.mark.parametrize("hours", [0, 1, 48, 15 * 24])
def test_postgres_gives_the_same_page(tmp_path, gamma_settings, hours):
    """The same page from a local database and from Postgres seeded as the hosted site
    is (`item` and `tracked_item` with the live league's items only)."""
    settings = gamma_settings
    import psycopg
    from psycopg.conninfo import conninfo_to_dict, make_conninfo

    with psycopg.connect(PG_URL, autocommit=True) as admin:
        admin.execute("DROP DATABASE IF EXISTS eb_farming_test")
        admin.execute("CREATE DATABASE eb_farming_test")
    url = make_conninfo(**(conninfo_to_dict(PG_URL) | {"dbname": "eb_farming_test"}))
    with db.session(settings.db_path) as con:
        build(con, hours, gamma=True)
    with psycopg.connect(url, autocommit=True) as pg:
        build(pg, hours, gamma=True, hosted=True)
    with db.session(settings.db_path, read_only=True) as con:
        expected = farming.farming(con, LIVE, settings)
    with psycopg.connect(url) as pg:
        got = farming.farming(pg, LIVE, settings)
    assert expected["mechanics"] or hours == 0
    _same(expected, got)
