"""Cross-rate triangles: loops through the exchange's item-to-item markets.

GGG's hourly pages hold every market a league traded, including pairs with neither
Chaos nor Divine (Exalted/Alchemy, an Omen/Exalted). The loader keeps only the Chaos and
Divine legs, so these markets were never looked at. A triangle starts and ends in a base
currency (Chaos or Divine):

    base -> A    buy A in the A/base market
    A -> B       trade A for B in the A/B market
    B -> base    sell B in the B/base market

All three in the same hour. Fair prices are each market's volume-weighted ratio; worst
prices buy A at the hour's highest ratio, pay the highest ratio for B and sell B at the
lowest, as the Chaos-Divine loops do (finding 2). Every A/B market gives two triangles,
one each way round.

Research tooling, read-only and local (`python -m exiledbroker.analysis.triangles`). It
reads the raw pages already on disk (or in `exchange_page`): no requests.
"""

from datetime import UTC

import polars as pl

from exiledbroker.normalize.tracked import CHAOS_METADATA, DIVINE_METADATA

BASES = {"chaos": CHAOS_METADATA, "divine": DIVINE_METADATA}
BUFFER = 0.02  # a loop pays only above this, for fees and rounding (finding 2's default)
# A loop is listed only if its cross market typically trades this much an hour, in the
# base: dust-priced pairs at whole-number ratios (2 Alchemy for an Exalt) show huge gaps
# on a few Chaos of trading.
MIN_VALUE = {"chaos": 100.0, "divine": 0.5}


def legs(markets: pl.DataFrame) -> pl.DataFrame:
    """Each traded market as two legs: x priced in ref (ref per x), with the hour's
    lowest and highest traded ratio and the units of x traded."""
    m = markets.filter((pl.col("volume_traded_a") > 0) & (pl.col("volume_traded_b") > 0))

    def side(x: str, ref: str) -> pl.DataFrame:
        lo = pl.col(f"lowest_ratio_{ref}") / pl.col(f"lowest_ratio_{x}")
        hi = pl.col(f"highest_ratio_{ref}") / pl.col(f"highest_ratio_{x}")
        return m.select(
            "hour",
            x=pl.col(x),
            ref=pl.col(ref),
            price=pl.col(f"volume_traded_{ref}") / pl.col(f"volume_traded_{x}"),
            lo=pl.min_horizontal(lo, hi),
            hi=pl.max_horizontal(lo, hi),
            x_vol=pl.col(f"volume_traded_{x}").cast(pl.Float64),
        )

    return pl.concat([side("b", "a"), side("a", "b")])


def triangles(markets: pl.DataFrame, base: str = CHAOS_METADATA) -> pl.DataFrame:
    """One row per hour and loop base -> A -> B -> base whose three legs all traded."""
    lg = legs(markets)
    bases = set(BASES.values())
    in_base = lg.filter((pl.col("ref") == base) & ~pl.col("x").is_in(list(bases)))
    cross = lg.filter(~pl.col("x").is_in(list(bases)) & ~pl.col("ref").is_in(list(bases)))
    buy = in_base.select("hour", a="x", p_a="price", hi_a="hi")
    sell = in_base.select("hour", b="x", p_b="price", lo_b="lo", b_vol_base="x_vol")
    return (
        cross.select("hour", a="ref", b="x", p_ab="price", hi_ab="hi", ab_vol="x_vol")
        .join(buy, on=["hour", "a"])
        .join(sell, on=["hour", "b"])
        .with_columns(
            gap=pl.col("p_b") / (pl.col("p_a") * pl.col("p_ab")) - 1,
            worst=pl.col("lo_b") / (pl.col("hi_a") * pl.col("hi_ab")) - 1,
            # What one hour's B traded through the cross market is worth in the base.
            ab_value=pl.col("ab_vol") * pl.col("p_b"),
        )
    )


def coverage(markets: pl.DataFrame) -> dict:
    """How much of the league's trading is in markets without Chaos or Divine."""
    bases = list(BASES.values())
    traded = markets.filter((pl.col("volume_traded_a") > 0) & (pl.col("volume_traded_b") > 0))
    cross = traded.filter(~pl.col("a").is_in(bases) & ~pl.col("b").is_in(bases))
    return {
        "market_hours": traded.height,
        "cross_market_hours": cross.height,
        "cross_markets": cross["market_id"].n_unique(),
    }


def summary(loops: pl.DataFrame, buffer: float = BUFFER) -> pl.DataFrame:
    """Per loop: hours with all three legs, the median fair gap, the share of hours that
    paid over the buffer at worst prices, and what the cross market traded an hour."""
    if loops.is_empty():
        return pl.DataFrame()
    return (
        loops.group_by("a", "b")
        .agg(
            hours=pl.len(),
            gap=pl.col("gap").median(),
            worst=pl.col("worst").median(),
            pays=(pl.col("worst") > buffer).mean(),
            ab_value=pl.col("ab_value").median(),
        )
        .sort("pays", "gap", descending=True)
    )


def named(df: pl.DataFrame, names: dict[str, str], cols=("a", "b")) -> pl.DataFrame:
    """Metadata ids replaced by item names (the id's last segment when RePoE lacks it)."""
    return df.with_columns(
        pl.col(c).map_elements(lambda m: names.get(m, m.rsplit("/", 1)[-1]), pl.Utf8) for c in cols
    )


def main() -> None:  # pragma: no cover - research entry point
    from exiledbroker.analysis.backtest import hourly_leagues
    from exiledbroker.config import get_settings
    from exiledbroker.ingest import currency_exchange as cx
    from exiledbroker.ingest.item_names import load_base_items
    from exiledbroker.normalize.exchange_loader import resolve_names
    from exiledbroker.storage import db

    settings = get_settings()
    with db.session(settings.db_path, read_only=True) as con:
        leagues = hourly_leagues(con)
        try:
            base_items = load_base_items(con)
        except LookupError:  # no RePoE names stored: ids are shown by their last segment
            base_items = {}
        hours = {
            lg: [
                cx.to_ts(h.replace(tzinfo=UTC))
                for (h,) in db.rows(
                    con,
                    """
                    SELECT e.hour FROM exchange_hour_loaded e JOIN league l ON l.id = e.league_id
                    WHERE l.name = ? AND e.hour < l.launched_at + INTERVAL 14 DAY
                    ORDER BY e.hour
                    """,
                    [lg],
                )
            ]
            for lg in leagues
        }
    per_league = []
    for lg in leagues:
        markets = pl.DataFrame(
            list(cx.market_rows(settings, lg, hours[lg])), schema=cx.MARKET_SCHEMA, strict=False
        )
        ids = sorted(set(markets["a"]) | set(markets["b"]))
        names = {mid: name for mid, _, name, _ in resolve_names(ids, base_items)}
        c = coverage(markets)
        print(
            f"{lg}: {len(hours[lg])} hours, {c['cross_markets']} item-to-item markets, "
            f"{c['cross_market_hours']:,} of {c['market_hours']:,} traded market-hours"
        )
        for base_name, base in BASES.items():
            loops = triangles(markets, base)
            s = summary(loops)
            if s.is_empty():
                continue
            share = (loops["worst"] > BUFFER).mean()
            print(
                f"  via {base_name}: {loops.height:,} loop-hours, {share:.1%} paid at worst "
                f"prices, median fair gap {loops['gap'].median():+.1%}"
            )
            per_league.append(
                named(s, names)
                .filter(pl.col("ab_value") >= MIN_VALUE[base_name])
                .with_columns(league=pl.lit(lg), base=pl.lit(base_name))
            )
    if not per_league:
        print("No triangles found.")
        return
    allp = pl.concat(per_league)
    with pl.Config(tbl_rows=60, tbl_cols=12, tbl_width_chars=220, fmt_str_lengths=50):
        print(
            f"\nLoops trading at least {MIN_VALUE['chaos']:.0f}c (or {MIN_VALUE['divine']} div) "
            "an hour that paid at worst prices "
            "in at least 25% of hours, per league:"
        )
        print(allp.filter(pl.col("pays") >= 0.25, pl.col("hours") >= 24).sort("league", "pays"))
        print("\nAcross leagues (loops with 24+ hours in a league):")
        print(
            allp.filter(pl.col("hours") >= 24)
            .group_by("base", "a", "b")
            .agg(
                leagues=pl.len(),
                worst_league_pays=pl.col("pays").min(),
                typical_pays=pl.col("pays").median(),
                gap=pl.col("gap").median(),
                ab_value=pl.col("ab_value").median(),
            )
            .sort("leagues", "worst_league_pays", descending=True)
            .head(40)
        )


if __name__ == "__main__":  # pragma: no cover
    main()
