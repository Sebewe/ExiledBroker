"""Live view: what's best to arbitrage in a running league's latest published hours.

GGG publishes each exchange hour a few minutes after it ends, so "now" means the
newest loaded hour, roughly an hour behind real time. Everything here looks back
`lookback_hours` from that hour: the latest edge or margin says where things stand,
and the share of paying hours over the lookback says whether it's a pattern or a blip.

SQL here must stay Postgres-compatible: the hosted site's Postgres serves the same queries.
"""

from datetime import UTC, datetime, timedelta

import duckdb
import polars as pl

from exiledbroker.config import Settings
from exiledbroker.normalize.exchange_loader import SOURCE as HOURLY
from exiledbroker.services import cross_market, divination
from exiledbroker.services.scoring import rank_score
from exiledbroker.storage import db

DIVINE_ID = "currency:divine-orb"
LOOP_FACTORS = {
    "edge_now": ("last_edge", True),
    "consistency": ("paying_share", True),
    "volume": ("overlap_chaos", True),
    "freshness": ("hours_since", False),
}
LOOP_WEIGHTS = {"edge_now": 4.0, "consistency": 3.0, "volume": 3.0, "freshness": 2.0}
CARD_FACTORS = {
    "margin_now": ("last_margin_pct", True),
    "consistency": ("profitable_share", True),
    "volume": ("sets_traded", True),
    "freshness": ("hours_since", False),
}
CARD_WEIGHTS = {"margin_now": 4.0, "consistency": 3.0, "volume": 3.0, "freshness": 2.0}


def live_leagues(con: duckdb.DuckDBPyConnection) -> pl.DataFrame:
    """Leagues followed on the exchange, newest data first: name, latest hour (null
    until something has traded), hours loaded, and the latest Divine price in Chaos
    (the site converts prices to Divines with it, in the browser). A just-launched
    league is listed before its first trade, so the live view can say it's waiting
    rather than missing."""
    # Cheap enough to run every minute: the latest hour comes from the league/time
    # index and the hour count from exchange_hour_loaded, not from scanning prices.
    return db.frame(
        con,
        """
        SELECT name, latest_hour, hours, launched_at, divine_chaos FROM (
            SELECT l.name, l.launched_at,
                   (SELECT max(p.observed_at) FROM price_observation p
                    WHERE p.league_id = l.id AND p.source = ?) AS latest_hour,
                   (SELECT d.chaos_value FROM price_observation d
                    WHERE d.item_id = ? AND d.league_id = l.id AND d.source = ?
                    ORDER BY d.observed_at DESC LIMIT 1) AS divine_chaos,
                   (SELECT count(*) FROM exchange_hour_loaded h
                    WHERE h.league_id = l.id) AS hours,
                   l.exchange_tracked
            FROM league l WHERE l.kind = 'challenge'
        ) t
        WHERE exchange_tracked OR latest_hour IS NOT NULL
        ORDER BY coalesce(latest_hour, launched_at) DESC NULLS LAST
        """,
        [HOURLY, DIVINE_ID, HOURLY],
    )


# GGG publishes an hour a few minutes after it ends; the worker loads it ~6 minutes past.
FIRST_DATA_DELAY = timedelta(minutes=10)


def upcoming_league(settings: Settings, with_trades: set[str]) -> dict | None:
    """The announced next league (settings), until it has trades loaded (its name is in
    `with_trades`): when it starts and roughly when its first hour shows up here (the end
    of its first clock hour, plus the publishing delay). While it's set, a league that
    stopped trading has ended rather than stalled: the site says so (Freshness.tsx) and
    the pipeline's alert stays quiet (ingest/pipeline.py)."""
    name, start = settings.next_league, settings.next_league_start
    if not name or not start or name in with_trades:
        return None
    start = start.astimezone(UTC) if start.tzinfo else start.replace(tzinfo=UTC)
    first_hour_end = start.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    return {"name": name, "start_at": start, "first_data_at": first_hour_end + FIRST_DATA_DELAY}


def latest_hour(con: duckdb.DuckDBPyConnection, league: str) -> datetime | None:
    q = """
        SELECT max(p.observed_at) FROM price_observation p
        WHERE p.league_id = (SELECT id FROM league WHERE name = ?) AND p.source = ?
    """
    rows = db.rows(con, q, [league, HOURLY])
    return rows[0][0] if rows else None


def _since(latest: datetime, lookback_hours: int) -> datetime:
    return latest - timedelta(hours=lookback_hours)


def live_loops(
    con: duckdb.DuckDBPyConnection,
    league: str,
    direction: str = "chaos_first",
    buffer: float = 0.02,
    lookback_hours: int = 6,
    min_price: float = 1.0,
    weights: dict[str, float] | None = None,
) -> pl.DataFrame:
    """Chaos/Divine loops in the latest hours, best first."""
    latest = latest_hour(con, league)
    if latest is None:
        return pl.DataFrame()
    hours = cross_market.hourly(
        con, [league], direction=direction, since=_since(latest, lookback_hours)
    )
    if hours.is_empty():
        return pl.DataFrame()
    last = hours.sort("observed_at").group_by("item_id").agg(pl.all().last().name.prefix("last_"))
    out = (
        hours.group_by("item_id", "name")
        .agg(
            pl.len().alias("hours"),
            (pl.col("edge") > buffer).mean().alias("paying_share"),
            pl.col("overlap_chaos").sum(),
        )
        .join(last, on="item_id")
        .select(
            "item_id",
            "name",
            "hours",
            "paying_share",
            "overlap_chaos",
            last_edge=pl.col("last_edge"),
            # Traded in both markets in the item's latest hour: the Chaos value, and the
            # items (GGG publishes units traded per hour, not the number of trades).
            hour_volume=pl.col("last_overlap_chaos"),
            hour_items=pl.col("last_overlap_chaos") / pl.col("last_chaos_price"),
            last_gap=pl.col("last_gap"),
            price=pl.col("last_chaos_price"),
            # The range traded in the Chaos market that hour: what the site shows,
            # since an hourly summary has no current price.
            price_low=pl.col("last_chaos_low"),
            price_high=pl.col("last_chaos_high"),
            last_hour=pl.col("last_observed_at"),
            hours_since=(pl.lit(latest) - pl.col("last_observed_at")).dt.total_hours(),
        )
        .filter(pl.col("price") >= min_price, pl.col("last_edge") > buffer)
    )
    return rank_score(out, LOOP_FACTORS, weights or LOOP_WEIGHTS)


def live_card_flips(
    con: duckdb.DuckDBPyConnection,
    league: str,
    lookback_hours: int = 6,
    unit: str = "chaos",
    weights: dict[str, float] | None = None,
) -> pl.DataFrame:
    """Card turn-ins in the latest hours, best first (only ones that paid last time)."""
    latest = latest_hour(con, league)
    if latest is None:
        return pl.DataFrame()
    hours = divination.hourly_turn_ins(con, league, unit=unit, since=_since(latest, lookback_hours))
    hours = hours.drop_nulls("margin")
    if hours.is_empty():
        return pl.DataFrame()
    cards = divination.followed_cards(con, hours["card"].unique().to_list()).select(
        "name", "item_id", "stack_size", "reward_quantity", "reward_name"
    )
    last = hours.sort("observed_at").group_by("card").agg(pl.all().last().name.prefix("last_"))
    out = (
        hours.group_by("card")
        .agg(
            pl.len().alias("hours"),
            (pl.col("margin") > 0).mean().alias("profitable_share"),
            pl.col("card_volume").sum().alias("cards_traded"),
        )
        .join(last, on="card")
        .join(cards, left_on="card", right_on="name")
        .select(
            pl.col("card").alias("name"),
            "item_id",
            "hours",
            "profitable_share",
            sets_traded=pl.col("cards_traded") / pl.col("stack_size"),
            set_cost=pl.col("last_set_cost"),
            reward_value=pl.col("last_reward_value"),
            last_margin=pl.col("last_margin"),
            last_margin_pct=pl.col("last_margin") / pl.col("last_set_cost"),
            reward=pl.format("{}× {}", pl.col("reward_quantity"), pl.col("reward_name")),
            stack_size="stack_size",
            last_hour=pl.col("last_observed_at"),
            hours_since=(pl.lit(latest) - pl.col("last_observed_at")).dt.total_hours(),
        )
        .filter(pl.col("last_margin") > 0)
    )
    return rank_score(out, CARD_FACTORS, weights or CARD_WEIGHTS)
