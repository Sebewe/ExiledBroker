"""Item recipes against the exchange: combines, vendor upgrades and rerolls.

Three kinds, curated in config/recipes.toml:

  combine  `count` of one item make one of another (20 shards an orb, 100 splinters a
           Breachstone). Priced each hour both items traded against Chaos, like a card
           turn-in: the cost is count x the input's price, the value the output's.
  tiers    a vendor turns `ratio` of a tier into one of the next (3 Screaming essences
           into a Shrieking one), expanded into combines for every name at both tiers.
  reroll   `count` of one item become a random other item of its pool (the scarab
           vendor, Harvest's change crafts). GGG doesn't publish the odds, so a reroll is
           valued at its floor, the cheapest other item the pool can roll that day, as
           for random card rewards (analysis/card_ev.py, finding 12): an input that costs
           less pays whatever rolls. Priced daily, since the floor needs most of the pool
           to have traded.

Fair prices are the hour's (or day's) average in the Chaos market. Harsh prices buy
the inputs at the hour's highest trade and sell the output at its lowest, in Chaos or,
when it traded there that hour, in Divines at the hour's worst rate.

Research tooling, read-only and local (`python -m exiledbroker.analysis.recipes`).
Reads the local database only: no requests.
"""

import tomllib
from itertools import pairwise
from pathlib import Path

import duckdb
import polars as pl

from exiledbroker.analysis.card_ev import MIN_COVERAGE, daily_prices
from exiledbroker.storage import db

CHAOS_ID = "currency:chaos-orb"  # priced at 1 by definition; has no exchange rows
DAYS = (0, 13)  # the launch fortnight


def load(path: Path) -> dict:
    with path.open("rb") as f:
        return tomllib.load(f)


def expand_tiers(names: set[str], tiers: dict) -> list[dict]:
    """Combines for every name that exists at a tier and the next one."""
    out = []
    for group, spec in tiers.items():
        pattern, ladder = spec["pattern"], spec["tiers"]
        kinds = {""} if "{kind}" not in pattern else _kinds(names, pattern, ladder)
        for kind in sorted(kinds):
            for lo, hi in pairwise(ladder):
                a = pattern.format(tier=lo, kind=kind)
                b = pattern.format(tier=hi, kind=kind)
                if a in names and b in names:
                    out.append({"input": a, "count": spec["ratio"], "output": b, "group": group})
    return out


def _kinds(names: set[str], pattern: str, ladder: list[str]) -> set[str]:
    """The {kind} values that appear in `names` at any tier of the ladder."""
    out = set()
    for tier in ladder:
        head, _, tail = pattern.format(tier=tier, kind="\0").partition("\0")
        out |= {
            n[len(head) : len(n) - len(tail)]
            for n in names
            if n.startswith(head) and n.endswith(tail) and len(n) > len(head) + len(tail)
        }
    return out


def item_ids(con: duckdb.DuckDBPyConnection) -> dict[str, str]:
    """{canonical name: item id} for currency-like items."""
    return {
        name: item_id
        for item_id, name in db.rows(
            con, "SELECT id, canonical_name FROM item WHERE id LIKE 'currency:%'"
        )
    }


def combines(con: duckdb.DuckDBPyConnection, config: dict) -> tuple[pl.DataFrame, list[str]]:
    """Every combine and expanded vendor upgrade whose items exist, and the names that
    don't (a misspelling, or an item that never traded)."""
    ids = item_ids(con)
    recipes = [{**c, "group": c.get("group", "combine")} for c in config.get("combine", [])]
    recipes += expand_tiers(set(ids), config.get("tiers", {}))
    rows, missing = [], []
    for r in recipes:
        gone = [n for n in (r["input"], r["output"]) if n not in ids]
        if gone:
            missing += gone
            continue
        rows.append(
            {
                "group": r["group"],
                "recipe": f"{r['count']} {r['input']} -> {r['output']}",
                "input_id": ids[r["input"]],
                "count": r["count"],
                "output_id": ids[r["output"]],
            }
        )
    schema = {
        "group": pl.Utf8,
        "recipe": pl.Utf8,
        "input_id": pl.Utf8,
        "count": pl.Int64,
        "output_id": pl.Utf8,
    }
    return pl.DataFrame(rows, schema=schema), sorted(set(missing))


def hourly(con: duckdb.DuckDBPyConnection, league: str, ids: list[str], days=DAYS) -> pl.DataFrame:
    """Each item's Chaos-market hours: average, lowest and highest trade, units traded,
    and the best harsh sale (the Chaos low, or the Divine low at the hour's worst rate)."""
    schema = {
        "item_id": pl.Utf8,
        "observed_at": pl.Datetime,
        "day": pl.Int64,
        "price": pl.Float64,
        "low": pl.Float64,
        "high": pl.Float64,
        "sell_low": pl.Float64,
        "units": pl.Float64,
    }
    if not ids:
        return pl.DataFrame(schema=schema)
    marks = ", ".join("?" for _ in ids)
    out = db.frame(
        con,
        f"""
        SELECT item_id, observed_at, CAST(floor(day_offset) AS BIGINT) AS day,
               chaos_price AS price, chaos_low AS low, chaos_high AS high,
               greatest(chaos_low, coalesce(divine_low * divine_rate_low, chaos_low))
                   AS sell_low,
               chaos_volume AS units
        FROM cross_market_hour
        WHERE league_id = (SELECT id FROM league WHERE name = ?)
          AND item_id IN ({marks}) AND chaos_price > 0
          AND day_offset >= ? AND day_offset < ?
        """,
        [league, *ids, days[0], days[1] + 1],
    )
    return out if not out.is_empty() else pl.DataFrame(schema=schema)


def combine_hours(
    con: duckdb.DuckDBPyConnection, league: str, recipes: pl.DataFrame, days=DAYS
) -> pl.DataFrame:
    """Per recipe and hour both items traded: the cost, value and margin, fair and harsh."""
    ids = sorted((set(recipes["input_id"]) | set(recipes["output_id"])) - {CHAOS_ID})
    px = hourly(con, league, ids, days)
    if recipes.is_empty() or px.is_empty():
        return pl.DataFrame()
    inp = px.select(
        "observed_at",
        "day",
        input_id="item_id",
        in_price="price",
        in_high="high",
        in_units="units",
    )
    out = px.select(
        "observed_at",
        output_id="item_id",
        out_price="price",
        out_sell_low="sell_low",
        out_units="units",
    )
    # A Chaos Orb output is worth 1 in every hour the input traded.
    chaos = inp.select(
        "observed_at",
        output_id=pl.lit(CHAOS_ID),
        out_price=pl.lit(1.0),
        out_sell_low=pl.lit(1.0),
        out_units=pl.lit(None, pl.Float64),
    ).unique()
    out = pl.concat([out, chaos])
    return (
        recipes.join(inp, on="input_id")
        .join(out, on=["output_id", "observed_at"])
        .with_columns(
            cost=pl.col("count") * pl.col("in_price"),
            cost_harsh=pl.col("count") * pl.col("in_high"),
        )
        .with_columns(
            margin=pl.col("out_price") / pl.col("cost") - 1,
            harsh_margin=pl.col("out_sell_low") / pl.col("cost_harsh") - 1,
            profit=pl.col("out_price") - pl.col("cost"),
            sets_traded=pl.col("in_units") / pl.col("count"),
            league=pl.lit(league),
        )
    )


def combine_summary(hours: pl.DataFrame, buffer: float = 0.02) -> pl.DataFrame:
    """Per league and recipe: hours priced, median margin, share of hours over the
    buffer at fair and harsh prices, profit a craft, and how many sets' worth of the
    input and outputs traded in a typical hour."""
    if hours.is_empty():
        return hours
    return (
        hours.group_by("league", "group", "recipe")
        .agg(
            hours=pl.len(),
            cost=pl.col("cost").median(),
            margin=pl.col("margin").median(),
            pays=(pl.col("margin") > buffer).mean(),
            harsh=pl.col("harsh_margin").median(),
            harsh_pays=(pl.col("harsh_margin") > buffer).mean(),
            profit=pl.col("profit").median(),
            sets_an_hour=pl.col("sets_traded").median(),
            outputs_an_hour=pl.col("out_units").median(),
        )
        .sort("league", "margin", descending=[False, True])
    )


# --- Rerolls -------------------------------------------------------------------------


def pool_ids(con: duckdb.DuckDBPyConnection, spec: dict) -> list[str]:
    where = " OR ".join("canonical_name LIKE ?" for _ in spec["like"])
    q = f"SELECT id FROM item WHERE id LIKE 'currency:%' AND ({where})"
    return sorted(r[0] for r in db.rows(con, q, list(spec["like"])))


def lifeforce_id(con: duckdb.DuckDBPyConnection, name: str | None) -> str | None:
    """The lifeforce's item id, with either spelling of Crystallised."""
    if not name:
        return None
    hit = db.rows(
        con,
        "SELECT id FROM item WHERE canonical_name LIKE ? ORDER BY id",
        [name.replace("Crystallised", "Crystalli_ed")],
    )
    return hit[0][0] if hit else None


def reroll_days(
    con: duckdb.DuckDBPyConnection, league: str, name: str, spec: dict, days=DAYS
) -> pl.DataFrame:
    """Per input item and day: `count` of it against the floor of the rest of its pool.

    A day counts only when at least MIN_COVERAGE of the pool (as it traded in this
    league) has a price, so a missing cheap item can't lift the floor."""
    ids = pool_ids(con, spec)
    lf = lifeforce_id(con, spec.get("lifeforce"))
    px = daily_prices(con, league, ids + ([lf] if lf else []))
    if px.is_empty():
        return pl.DataFrame()
    px = px.filter(pl.col("day").is_between(*days))
    pool = px.filter(pl.col("item_id").is_in(ids))
    size = pool["item_id"].n_unique()
    # The two cheapest items each day, so each input's floor leaves itself out.
    ranked = pool.sort("price").group_by("day", maintain_order=True)
    cheap = ranked.agg(
        n=pl.len(),
        id1=pl.col("item_id").first(),
        p1=pl.col("price").first(),
        p2=pl.col("price").get(1, null_on_oob=True),
    )
    cheap_low = (
        pool.sort("low")
        .group_by("day", maintain_order=True)
        .agg(
            lid1=pl.col("item_id").first(),
            l1=pl.col("low").first(),
            l2=pl.col("low").get(1, null_on_oob=True),
        )
    )
    out = (
        pool.join(cheap, on="day")
        .join(cheap_low, on="day")
        .filter(pl.col("n") >= MIN_COVERAGE * size)
        .with_columns(
            floor=pl.when(pl.col("item_id") == pl.col("id1"))
            .then(pl.col("p2"))
            .otherwise(pl.col("p1")),
            floor_low=pl.when(pl.col("item_id") == pl.col("lid1"))
            .then(pl.col("l2"))
            .otherwise(pl.col("l1")),
        )
        .filter(pl.col("floor").is_not_null())
        .with_columns(
            cost=spec["count"] * pl.col("price"),
            cost_harsh=spec["count"] * pl.col("high"),
        )
        .with_columns(
            margin=pl.col("floor") / pl.col("cost") - 1,
            harsh_margin=pl.col("floor_low") / pl.col("cost_harsh") - 1,
            gain=pl.col("floor") - pl.col("cost"),
            league=pl.lit(league),
            reroll=pl.lit(name),
        )
    )
    if lf:
        lfp = px.filter(pl.col("item_id") == lf).select("day", lifeforce_price="price")
        out = out.join(lfp, on="day", how="left").with_columns(
            lifeforce_units=pl.col("gain") / pl.col("lifeforce_price")
        )
    names = dict(db.rows(con, "SELECT id, canonical_name FROM item WHERE id LIKE 'currency:%'"))
    return out.with_columns(
        input=pl.col("item_id").replace_strict(names, default=pl.col("item_id"))
    )


def reroll_summary(values: pl.DataFrame) -> pl.DataFrame:
    """Per league, reroll and input: days priced, median margin at the floor, share of
    days it paid, at harsh prices, the gain a reroll and units traded a day (plus, for
    Harvest, the lifeforce the gain would pay for)."""
    if values.is_empty():
        return values
    aggs = [
        pl.len().alias("days"),
        pl.col("cost").median(),
        pl.col("margin").median(),
        (pl.col("margin") > 0).mean().alias("pays"),
        pl.col("harsh_margin").median().alias("harsh"),
        pl.col("gain").median(),
        pl.col("units").median().alias("units_a_day"),
    ]
    if "lifeforce_units" in values.columns:
        aggs.append(pl.col("lifeforce_units").median())
    return (
        values.group_by("league", "reroll", "input")
        .agg(aggs)
        .sort("league", "reroll", "margin", descending=[False, False, True])
    )


def across_leagues(summary: pl.DataFrame, key: str, value: str = "margin") -> pl.DataFrame:
    """Per item: the leagues it was priced in, how many it paid in (median above 0), and
    its worst and median league."""
    if summary.is_empty():
        return summary
    return (
        summary.group_by(key)
        .agg(
            leagues=pl.len(),
            paid_in=(pl.col(value) > 0).sum(),
            worst=pl.col(value).min(),
            typical=pl.col(value).median(),
            worst_harsh=pl.col("harsh").min(),
        )
        .sort("worst", descending=True)
    )


def _concat(frames: list[pl.DataFrame]) -> pl.DataFrame:
    frames = [f for f in frames if not f.is_empty()]
    return pl.concat(frames, how="diagonal_relaxed") if frames else pl.DataFrame()


def main() -> None:  # pragma: no cover - research entry point
    from exiledbroker.analysis.backtest import hourly_leagues
    from exiledbroker.config import get_settings

    settings = get_settings()
    config = load(Path(settings.mechanics_file).parent / "recipes.toml")
    with db.session(settings.db_path, read_only=True) as con:
        leagues = hourly_leagues(con)
        recipes, missing = combines(con, config)
        hours = _concat([combine_hours(con, lg, recipes) for lg in leagues])
        rerolls = [
            reroll_days(con, lg, name, spec)
            for lg in leagues
            for name, spec in config.get("reroll", {}).items()
        ]
    rv = _concat(rerolls)
    with pl.Config(tbl_rows=400, tbl_cols=20, tbl_width_chars=220, fmt_str_lengths=60):
        print(f"Leagues: {', '.join(leagues)}; days {DAYS[0]}-{DAYS[1]}")
        if missing:
            print(f"Not in the item table (skipped): {', '.join(missing)}")
        cs = combine_summary(hours)
        print("\nCombines and vendor upgrades, per league:")
        print(cs)
        print("\nCombines across leagues (by the worst league's median margin):")
        print(across_leagues(cs, "recipe"))
        rs = reroll_summary(rv)
        for name in config.get("reroll", {}):
            part = rs.filter(reroll=name) if "reroll" in rs.columns else rs
            if part.is_empty():
                print(f"\n{name}: nothing priced")
                continue
            print(f"\n{name}, across leagues (best 30):")
            print(across_leagues(part, "input").head(30))
            if "lifeforce_units" in part.columns:
                print(f"{name}, per league (best 10 each):")
                print(part.group_by("league").head(10))


if __name__ == "__main__":  # pragma: no cover
    main()
