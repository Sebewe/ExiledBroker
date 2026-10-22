"""The services on Postgres, the hosted database: the schema must build there, every
service must give the same answer as on DuckDB, and the live pages' queries must be
able to use an index on the big tables rather than scanning them.

Runs only when EB_TEST_POSTGRES_URL points at a disposable database (CI starts one;
locally e.g. `docker run -e POSTGRES_PASSWORD=eb -p 55432:5432 postgres:17` and
EB_TEST_POSTGRES_URL=postgresql://postgres:eb@localhost:55432/postgres). The database
is wiped. Data: the replay fixture (Mirage's first 30 hours) loaded into DuckDB by the
real pipeline, then copied over."""

import os
from datetime import timedelta

import polars as pl
import pytest
from polars.testing import assert_frame_equal

from exiledbroker.analysis import launch_patterns as lp
from exiledbroker.config import Settings
from exiledbroker.ingest import currency_exchange as cx
from exiledbroker.ingest.live import sync_live
from exiledbroker.services import cross_market, divination, live, market, overview, prices
from exiledbroker.storage import db, site
from test_currency_exchange import FakeExchange, client_for
from test_live_pipeline import LAUNCH, PAGES, store_reference_data

PG_URL = os.environ.get("EB_TEST_POSTGRES_URL")
pytestmark = pytest.mark.skipif(not PG_URL, reason="EB_TEST_POSTGRES_URL is not set")
LEAGUE = "Mirage"
BIG_TABLES = {"price_observation", "cross_market_hour"}


@pytest.fixture(scope="module")
def engines(tmp_path_factory):
    import psycopg

    s = Settings(data_dir=tmp_path_factory.mktemp("pg"), request_min_interval=0)
    store_reference_data(s)
    server = FakeExchange(PAGES, now=LAUNCH + 30 * 3600)
    with client_for(s, server) as client:
        now = cx.from_ts(server.now) + timedelta(minutes=10)
        sync_live(client, s, LEAGUE, now=now, earliest=cx.from_ts(LAUNCH - 72 * 3600))

    pg = psycopg.connect(PG_URL, autocommit=True)
    pg.execute("DROP SCHEMA public CASCADE")
    pg.execute("CREATE SCHEMA public")
    duck = db.connect(s.db_path, read_only=True)
    # The same copy `eb site seed` makes; it also builds the schema on Postgres.
    site.seed(duck, pg, [LEAGUE])
    yield duck, pg
    duck.close()
    pg.close()


def _cases(duck) -> dict:
    """Every service and analysis query, with arguments that return data."""
    groups = market.tracked_groups(duck)["group_id"].to_list()
    items = db.rows(
        duck,
        "SELECT DISTINCT item_id FROM price_observation p JOIN tracked_item t USING (item_id)",
    )
    item_ids = sorted(i for (i,) in items)
    names = prices.item_names(duck, [LEAGUE])
    since = live.latest_hour(duck, LEAGUE) - timedelta(hours=6)
    leagues = [LEAGUE]
    weights = {LEAGUE: 1.0}
    return {
        "live.live_leagues": lambda c: live.live_leagues(c),
        "live.latest_hour": lambda c: live.latest_hour(c, LEAGUE),
        "live.live_loops": lambda c: live.live_loops(c, LEAGUE),
        "live.live_card_flips": lambda c: live.live_card_flips(c, LEAGUE),
        "divination.followed_cards": lambda c: divination.followed_cards(c),
        "divination.hourly_turn_ins": lambda c: divination.hourly_turn_ins(c, LEAGUE),
        "divination.hourly_turn_ins(since)": lambda c: divination.hourly_turn_ins(
            c, LEAGUE, since=since
        ),
        "divination.turn_in_summary": lambda c: divination.turn_in_summary(c, LEAGUE),
        "cross_market.hourly": lambda c: cross_market.hourly(c, leagues),
        "cross_market.hourly(since)": lambda c: cross_market.hourly(c, leagues, since=since),
        "cross_market.summarize": lambda c: cross_market.summarize(c, leagues, min_hours=1),
        "market.hourly_leagues": lambda c: market.hourly_leagues(c),
        "market.tracked_groups": lambda c: market.tracked_groups(c),
        "market.daily": lambda c: market.daily(c, LEAGUE, groups),
        "market.summary": lambda c: market.summary(c, LEAGUE, groups),
        "market.hourly": lambda c: market.hourly(c, LEAGUE, item_ids),
        "prices.item_names": lambda c: prices.item_names(c, leagues),
        "prices.item_curve": lambda c: prices.item_curve(c, leagues, names[0]),
        "overview.table_counts": lambda c: overview.table_counts(c),
        "overview.league_calendar": lambda c: overview.league_calendar(c),
        "overview.leagues_with_prices": lambda c: overview.leagues_with_prices(c),
        "lp.unique_moves": lambda c: lp.unique_moves(c),
        "lp.hourly_league_names": lambda c: lp.hourly_league_names(c),
        "lp.daily_league_names": lambda c: lp.daily_league_names(c),
        "lp.launch_curves": lambda c: lp.launch_curves(c, item_ids, leagues, bucket_hours=1),
        "lp.group_curves": lambda c: lp.group_curves(
            c, groups[0], leagues, bucket_hours=1, min_baseline_hours=1
        ),
        "lp.turn_ins_across_leagues": lambda c: lp.turn_ins_across_leagues(c, leagues, weights),
    }


def _normalized(df: pl.DataFrame) -> pl.DataFrame:
    """Same values, engine-neutral types: Postgres sums are NUMERIC and its integers
    come back as Python ints, so compare numbers as floats."""
    return df.with_columns(
        pl.col(c).cast(pl.Float64) for c, t in df.schema.items() if t.is_numeric() or t == pl.Null
    )


def test_every_service_gives_the_same_answer_on_postgres(engines):
    duck, pg = engines
    cases = _cases(duck)
    with_data = 0
    for name, run in cases.items():
        expected, got = run(duck), run(pg)
        if isinstance(expected, pl.DataFrame):
            assert expected.columns == got.columns, name
            with_data += expected.height > 0
            if expected.height == 0 and got.height == 0:
                continue
            (
                assert_frame_equal(
                    _normalized(expected),
                    _normalized(got),
                    check_row_order=False,
                    check_dtypes=False,
                    rel_tol=1e-9,
                    abs_tol=1e-9,
                ),
                name,
            )
        else:
            assert expected == got, name
    assert with_data >= 15  # the comparison isn't vacuous


# The queries behind the live pages run every hour for every visitor's cache miss.
LIVE_QUERIES = [
    "live.live_leagues",
    "live.latest_hour",
    "live.live_loops",
    "live.live_card_flips",
    "divination.hourly_turn_ins(since)",
    "cross_market.hourly(since)",
]


def _scans(plan: dict) -> list[dict]:
    out = [plan] if plan.get("Relation Name") in BIG_TABLES else []
    for child in plan.get("Plans", []):
        out += _scans(child)
    return out


def _index_lookups(node: dict) -> list[tuple[str, str]]:
    """(index, condition) pairs a scan uses: its own, or for a bitmap scan those of
    the bitmap index scans under it. A sequential scan has none."""
    if node["Node Type"] in ("Index Scan", "Index Only Scan", "Bitmap Index Scan"):
        return [(node["Index Name"], node.get("Index Cond", ""))]
    return [pair for child in node.get("Plans", []) for pair in _index_lookups(child)]


def _leading_columns(pg) -> dict[str, str]:
    return dict(
        db.rows(
            pg,
            """
            SELECT c.relname, a.attname FROM pg_index i
            JOIN pg_class c ON c.oid = i.indexrelid
            JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = i.indkey[0]
            """,
        )
    )


@pytest.mark.parametrize("name", LIVE_QUERIES)
def test_live_queries_can_use_an_index(engines, name):
    """With sequential scans disabled, every read of a big table must be an index
    lookup on the index's leading column; a condition on a later column still reads
    the whole index. On this small fixture Postgres would rightly choose to scan; at
    hosted size the right index has to exist."""
    duck, pg = engines
    run = _cases(duck)[name]
    with db.metered() as meter:
        run(pg)
    assert meter.queries
    leading = _leading_columns(pg)
    pg.execute("SET enable_seqscan = off")
    try:
        for q in meter.queries:
            [(plan,)] = db.rows(pg, "EXPLAIN (FORMAT JSON) " + q.sql, q.params)
            for node in _scans(plan[0]["Plan"]):
                lookups = _index_lookups(node)
                assert lookups, (name, node["Node Type"], q.sql)
                for index, cond in lookups:
                    assert leading[index] in cond, (name, index, cond, q.sql)
    finally:
        pg.execute("SET enable_seqscan = on")


# The site's tables, ordered so rows compare engine-neutrally.
WORKER_TABLES = {
    "price_observation": "item_id, observed_at",
    "cross_market_hour": "item_id, observed_at",
    "exchange_hour_loaded": "hour",
    "tracked_item": "item_id, group_id",
    "divination_card": "item_id",
}


def _contents(con, table: str, order: str) -> pl.DataFrame:
    return _normalized(db.frame(con, f"SELECT * FROM {table} ORDER BY {order}"))


def test_live_worker_writes_postgres_like_duckdb(engines, tmp_path):
    """The hosted worker: `sync_live` with EB_DATABASE_URL set loads hour by hour into
    Postgres (DuckDB attached to it). The tables must end up as the DuckDB pipeline's."""
    import psycopg
    from psycopg.conninfo import conninfo_to_dict, make_conninfo

    duck, _ = engines
    with psycopg.connect(PG_URL, autocommit=True) as admin:
        admin.execute("DROP DATABASE IF EXISTS eb_worker_test")
        admin.execute("CREATE DATABASE eb_worker_test")
    url = make_conninfo(**(conninfo_to_dict(PG_URL) | {"dbname": "eb_worker_test"}))
    s = Settings(data_dir=tmp_path, request_min_interval=0, database_url=url)
    store_reference_data(s)  # local file: the reference rows the worker would have
    with db.session(s.db_path, read_only=True) as local, psycopg.connect(url) as pg:
        db.init_schema(pg)
        for key, content, source in db.rows(
            local, "SELECT key, content, source_url FROM reference_data"
        ):
            pg.execute(
                "INSERT INTO reference_data (key, fetched_at, content, source_url, checked_at) "
                "VALUES (%s, now(), %s, %s, now())",
                [key, content, source],
            )
    server = FakeExchange(PAGES, now=LAUNCH)
    for hours_in in (1, 2, 3, 6, 12, 24, 30):
        server.now = LAUNCH + hours_in * 3600
        now = cx.from_ts(server.now) + timedelta(minutes=10)
        with client_for(s, server) as client:
            status = sync_live(client, s, LEAGUE, now=now, earliest=cx.from_ts(LAUNCH - 72 * 3600))
        assert status.state == "updated", status

    with psycopg.connect(url) as pg:
        for table, order in WORKER_TABLES.items():
            (
                assert_frame_equal(
                    _contents(duck, table, order),
                    _contents(pg, table, order),
                    check_dtypes=False,
                    rel_tol=1e-9,
                    abs_tol=1e-9,
                ),
                table,
            )
        runs = db.rows(pg, "SELECT state, requests FROM ingest_run ORDER BY started_at")
    assert [r[0] for r in runs] == ["updated"] * 7
