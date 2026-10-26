"""What a divination card set with a random reward is worth (docs/findings.md 12).

A random reward ("5x Fossil") gives one of several items, with weights GGG doesn't
publish, so a set is valued three ways each day of a league, from the exchange's daily
median prices (`cross_market_hour`, Chaos market):

  floor   quantity x the cheapest item the reward can roll that day: a set that costs
          less pays whatever rolls, with no assumption about the weights
  median  quantity x the median item (every item equally likely)
  mean    quantity x the average item (every item equally likely: flatters, since the
          dear outcomes are usually the rare ones)

against the set's cost (stack size x the card's daily median price). The pools are
curated in config/card_rewards.toml. A day counts only when the card traded and at
least `MIN_COVERAGE` of its pool did, so a missing cheap item can't lift the floor. The
pool is what traded at all in that league: legacy ids and items not in the league's
game never count against the coverage.

Research tooling, read-only and local (`python -m exiledbroker.analysis.card_ev`).
"""

import tomllib
from pathlib import Path

import duckdb
import polars as pl

from exiledbroker.storage import db

MIN_COVERAGE = 0.8  # share of a pool's items that must have a price that day
ALL_CARDS = "*cards*"  # the pool token for "any divination card"


def load_pools(path: Path) -> dict[str, list[str]]:
    """{reward name: [LIKE patterns on item.canonical_name]} from config/card_rewards.toml."""
    with path.open("rb") as f:
        return {name: list(spec["like"]) for name, spec in tomllib.load(f)["pool"].items()}


def pool_items(con: duckdb.DuckDBPyConnection, pools: dict[str, list[str]]) -> pl.DataFrame:
    """One row per (reward name, item it can roll)."""
    frames = []
    for reward, patterns in pools.items():
        if patterns == [ALL_CARDS]:
            q = "SELECT item_id FROM divination_card"
            params: list = []
        else:
            where = " OR ".join("canonical_name LIKE ?" for _ in patterns)
            q = f"SELECT id AS item_id FROM item WHERE id LIKE 'currency:%' AND ({where})"
            params = patterns
        ids = [r[0] for r in db.rows(con, q, params)]
        frames.append(pl.DataFrame({"reward_name": [reward] * len(ids), "item_id": ids}))
    return (
        pl.concat(frames)
        if frames
        else pl.DataFrame(schema={"reward_name": pl.Utf8, "item_id": pl.Utf8})
    )


def random_cards(con: duckdb.DuckDBPyConnection, pools: dict[str, list[str]]) -> pl.DataFrame:
    """Followed cards whose reward is random and has a pool."""
    cards = db.frame(
        con,
        """
        SELECT item_id AS card_id, name AS card, stack_size, reward_name, reward_quantity
        FROM divination_card
        WHERE followed AND reward_fixed = false AND stack_size IS NOT NULL
        """,
    )
    return cards.filter(pl.col("reward_name").is_in(list(pools)))


def daily_prices(con: duckdb.DuckDBPyConnection, league: str, item_ids: list[str]) -> pl.DataFrame:
    """Each item's daily median Chaos price, and the medians of its hourly lows and highs
    (for harsh prices: buy at the high, sell at the low), and units traded."""
    if not item_ids:
        return pl.DataFrame(schema={"item_id": pl.Utf8, "day": pl.Int64, "price": pl.Float64})
    marks = ", ".join("?" for _ in item_ids)
    return db.frame(
        con,
        f"""
        SELECT item_id, CAST(floor(day_offset) AS BIGINT) AS day,
               percentile_cont(0.5) WITHIN GROUP (ORDER BY chaos_price) AS price,
               percentile_cont(0.5) WITHIN GROUP (ORDER BY chaos_low) AS low,
               percentile_cont(0.5) WITHIN GROUP (ORDER BY chaos_high) AS high,
               sum(chaos_volume) AS units
        FROM cross_market_hour
        WHERE league_id = (SELECT id FROM league WHERE name = ?)
          AND item_id IN ({marks}) AND chaos_price > 0
        GROUP BY item_id, CAST(floor(day_offset) AS BIGINT)
        """,
        [league, *item_ids],
    )


def daily_values(
    con: duckdb.DuckDBPyConnection, league: str, pools: dict[str, list[str]]
) -> pl.DataFrame:
    """Per card and day: the set's cost, its floor / median / mean value, and the margins
    (value / cost - 1). Only days the card traded and its pool was covered."""
    cards = random_cards(con, pools)
    items = pool_items(con, pools)
    ids = sorted(set(cards["card_id"]) | set(items["item_id"]))
    px = daily_prices(con, league, ids)
    if cards.is_empty() or px.is_empty():
        return pl.DataFrame()
    # The pool as it exists in this league: items that traded on at least one day.
    size = (
        items.join(px.select("item_id").unique(), on="item_id")
        .group_by("reward_name")
        .agg(pool_size=pl.len())
    )
    outcome = (
        items.join(px, on="item_id")
        .group_by("reward_name", "day")
        .agg(
            lo=pl.col("price").min(),
            mid=pl.col("price").median(),
            lo_harsh=pl.col("low").min(),
            mid_harsh=pl.col("low").median(),
            avg=pl.col("price").mean(),
            priced=pl.len(),
            cheapest=pl.col("item_id").sort_by("price").first(),
        )
        .join(size, on="reward_name")
        .filter(pl.col("priced") >= MIN_COVERAGE * pl.col("pool_size"))
    )
    card_px = px.select(
        card_id="item_id", day="day", card_price="price", card_high="high", card_units="units"
    )
    return (
        cards.join(card_px, on="card_id")
        .join(outcome, on=["reward_name", "day"])
        .with_columns(
            cost=pl.col("stack_size") * pl.col("card_price"),
            cost_harsh=pl.col("stack_size") * pl.col("card_high"),
        )
        .with_columns(
            floor=pl.col("reward_quantity") * pl.col("lo"),
            median=pl.col("reward_quantity") * pl.col("mid"),
            mean=pl.col("reward_quantity") * pl.col("avg"),
            harsh_floor_margin=pl.col("reward_quantity") * pl.col("lo_harsh") / pl.col("cost_harsh")
            - 1,
            harsh_median_margin=pl.col("reward_quantity")
            * pl.col("mid_harsh")
            / pl.col("cost_harsh")
            - 1,
        )
        .with_columns(
            (pl.col(v) / pl.col("cost") - 1).alias(f"{v}_margin")
            for v in ("floor", "median", "mean")
        )
        .with_columns(
            floor_profit=pl.col("floor") - pl.col("cost"),
            median_profit=pl.col("median") - pl.col("cost"),
            league=pl.lit(league),
        )
        .sort("card", "day")
    )


def summary(values: pl.DataFrame, days: tuple[int, int] = (0, 13)) -> pl.DataFrame:
    """Per league and card over a window of days: how many days were priced, the median
    margin at the floor / median / mean, the share of days the floor paid, the typical
    set cost and the cards traded a day."""
    if values.is_empty():
        return values
    w = values.filter(pl.col("day").is_between(*days))
    return (
        w.group_by("league", "card", "reward_name", "stack_size", "reward_quantity")
        .agg(
            days=pl.len(),
            cost=pl.col("cost").median(),
            floor_margin=pl.col("floor_margin").median(),
            median_margin=pl.col("median_margin").median(),
            mean_margin=pl.col("mean_margin").median(),
            floor_pays=(pl.col("floor_margin") > 0).mean(),
            floor_profit=pl.col("floor_profit").median(),
            median_profit=pl.col("median_profit").median(),
            harsh_floor=pl.col("harsh_floor_margin").median(),
            harsh_median=pl.col("harsh_median_margin").median(),
            cards_a_day=pl.col("card_units").median(),
        )
        .sort("league", "floor_margin", descending=[False, True])
    )


def main() -> None:  # pragma: no cover - research entry point
    from exiledbroker.config import get_settings

    settings = get_settings()
    pools = load_pools(Path(settings.mechanics_file).parent / "card_rewards.toml")
    with db.session(settings.db_path, read_only=True) as con:
        leagues = [
            r[0]
            for r in db.rows(
                con,
                "SELECT DISTINCT l.name FROM cross_market_hour x JOIN league l ON l.id = x.league_id",
            )
        ]
        out = pl.concat([daily_values(con, lg, pools) for lg in leagues], how="diagonal_relaxed")
    with pl.Config(tbl_rows=200, tbl_cols=20, tbl_width_chars=200):
        cols = [
            "league",
            "card",
            "days",
            "cost",
            "floor_margin",
            "floor_pays",
            "floor_profit",
            "median_margin",
            "median_profit",
            "harsh_floor",
            "harsh_median",
            "cards_a_day",
        ]
        print(summary(out).select(cols))
        later = summary(out, days=(14, 10_000))
        if not later.is_empty():
            print("After day 13:")
            print(later.select(cols))


if __name__ == "__main__":  # pragma: no cover
    main()
