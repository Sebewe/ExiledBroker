"""Hour of day: does it matter when a farmer sells? (finding 6 in docs/findings.md).
Research only, on the local database; `report` is what the sell helper's `hours` ships
(services/sell_helper.py, `eb farming build`), built locally from past leagues.

Price: each item-hour's log Chaos price minus the item's mean log price over the WINDOW
hours centred on it (at least MIN_WINDOW of them traded). A centred mean rather than the
UTC day's: in launch week prices trend hard within a day, and a calendar-day mean turns
any trend into a fake hour-of-day pattern. Deviations are pooled per league-day and hour
(median over a basket's items), then averaged over days. The same for the Divine market's
own prices (not Chaos price ÷ Divine rate: the two markets' daily cycles differ), and for
the Divine's Chaos price. Volume: each hour's share of the day's Chaos traded, on
complete UTC days. Intervals resample days (hours within a day move together); the noise
floor shuffles hours within each day (`null95`).

The effect fades as a league ages, so everything is per PHASE of the league. A basket's
own profile is shown only if it holds across leagues (`stability`); otherwise the pooled
one.

Baskets are `{mechanic id: [item_id]}`, from config/mechanics.toml (`farming_baskets`:
outputs plus legacy outputs, since this reads past leagues); the `PROVISIONAL` name rules
stand in when the file is missing.

    python -m exiledbroker.analysis.hours          # the tables in finding 6
"""

import math
import re
import warnings

import numpy as np
import polars as pl

from exiledbroker.analysis import backtest as bt
from exiledbroker.config import Settings, get_settings
from exiledbroker.normalize import mechanics as mechanics_config
from exiledbroker.storage import db

WINDOW = 25  # hours in the centred mean
MIN_WINDOW = 21  # traded hours it needs
MIN_TRADED = 0.8  # share of a segment's hours an item must trade in to count
MIN_CHAOS_H = 300.0  # and its median Chaos traded an hour
LAUNCH_DAYS = 14
# (name, first day, end day) of the league's phases.
PHASES = (("d0_2", 0, 2), ("d2_7", 2, 7), ("d7_14", 7, 14), ("later", 14, math.inf))
BOOT = 500
SHUFFLES = 500
# A best hour less than 1% over the day's average is "small": about one order step
# (1c on 100c) and well inside an hour's typical move. It must also clear the noise floor.
SMALL = 0.01
# A basket's profile is its own only if each league's agrees with the other leagues'
# (mean leave-one-league-out correlation) at least this well.
STABLE_R = 0.5
# A verdict of "worth_it" needs the pattern in at least this many leagues.
MIN_LEAGUES = 2
# Volume shares need this many days of league behind them: on launch day volume grows
# tenfold, and its share by hour is that growth, not the time of day.
VOLUME_FROM_DAY = 2
DIVINE = "divine"  # the Divine's Chaos price, carried as an item in the Chaos market

# Stand-ins for workstream A's baskets: regexes on the item's name. A mechanic's own
# scarabs and astrolabe count in it.
PROVISIONAL = {
    "Breach": r"^(Splinter of |Blessing of |.*Breachstone|Breach Scarab|Grasping Astrolabe)",
    "Delirium": r"(Delirium Orb|^Simulacrum|^Delirium Scarab|^Deceptive Astrolabe)",
    "Essence": r"(Essence of |^Essence Scarab)",
    "Harvest": r"(Lifeforce|^Harvest Scarab|^Crystallised |^Fruiting Astrolabe)",
    "Delve": r"( Fossil$| Resonator| Fossil \(|^Sulphite Scarab)",
    "Legion": r"^(Timeless .*(Emblem|Splinter)|Legion Scarab|.*Enshrouding Crystal|Timeless Astr)",
    "Blight": r"( Oil$|^Blight Scarab|^Fungal Astrolabe)",
    "Expedition": r"^(Exotic Coinage|Astragali|Burial Medallion|Scrap Metal|Expedition Scarab"
    r"|Runic Astrolabe)",
    "Ritual": r"^(Ritual Vessel|Ritual Scarab|An Audience With|Omen of |Nameless Astrolabe)",
    "Ultimatum": r"^(Inscribed Ultimatum|Ultimatum Scarab|Chaotic Astrolabe)",
    "Abyss": r"^(Abyss Scarab|Lightless Astrolabe)",
    "Eldritch altars": r"^(Lesser|Greater|Grand|Exceptional) Eldritch (Ichor|Ember)",
    "Divination": r"^(Stacked Deck|Divination Scarab)",  # plus every card, below
    "Kalguur": r"^(Runegraft of|Kalguuran Scarab)",
    "Ancestors": r"^Tattoo of ",
}


def baskets(con, rules: dict[str, str] = PROVISIONAL) -> dict[str, list[str]]:
    """{mechanic: item ids} from name rules; divination cards join Divination."""
    items = db.frame(
        con,
        """
        SELECT i.id AS item_id, i.canonical_name AS name,
               EXISTS (SELECT 1 FROM tracked_item t
                       WHERE t.item_id = i.id AND t.group_id = 'divination') AS card
        FROM item i WHERE i.id LIKE 'currency:%'
        """,
    )
    out = {}
    for mechanic, rule in rules.items():
        hit = items.filter(
            pl.col("name").map_elements(lambda n, r=rule: bool(re.search(r, n)), pl.Boolean)
            | (pl.col("card") & (mechanic == "Divination"))
        )
        out[mechanic] = sorted(hit["item_id"].to_list())
    return out


def farming_baskets(con, settings: Settings) -> dict[str, list[str]]:
    """{mechanic id: item ids} from config/mechanics.toml, outputs plus legacy outputs;
    the PROVISIONAL name rules if there's no file."""
    mechanics = mechanics_config.load_mechanics(settings)
    if not mechanics:
        return baskets(con)
    return {m.id: mechanics_config.output_ids(con, m, legacy=True) for m in mechanics}


def phase_of(day: pl.Expr) -> pl.Expr:
    expr = pl.lit(None, dtype=pl.String)
    for name, lo, hi in reversed(PHASES):
        expr = pl.when((day >= lo) & (day < hi)).then(pl.lit(name)).otherwise(expr)
    return expr


def hourly(con, league: str, market: str = "chaos") -> pl.DataFrame:
    """A league's hours in one market (`chaos` or `divine`): price in that market's
    currency, Chaos traded (`cv`) and phase. The Chaos market also carries the Divine's
    Chaos price as the item DIVINE, so its profile comes out the same way."""
    price, cv = {
        "chaos": ("chaos_price", "chaos_price * chaos_volume"),
        "divine": ("divine_price", "divine_price * divine_volume * divine_rate"),
    }[market]
    px = db.frame(
        con,
        f"""
        SELECT item_id, observed_at, day_offset, {price} AS p, {cv} AS cv
        FROM cross_market_hour
        WHERE league_id = (SELECT id FROM league WHERE name = ?) AND {price} > 0
        """,
        [league],
    )
    rate = (
        pl.DataFrame(schema=px.schema)
        if market != "chaos"
        else (
            bt._rate(con, league)
            .join(px.select("observed_at", "day_offset").unique(), on="observed_at")
            .select(
                item_id=pl.lit(DIVINE),
                observed_at="observed_at",
                day_offset="day_offset",
                p="rate",
                cv=pl.lit(None, dtype=pl.Float64),
            )
        ).cast(px.schema)
    )
    return pl.concat([px, rate]).with_columns(
        league=pl.lit(league),
        phase=phase_of(pl.col("day_offset")),
        date=pl.col("observed_at").dt.date(),
        hour=pl.col("observed_at").dt.hour(),
    )


def deviations(px: pl.DataFrame) -> pl.DataFrame:
    """Per liquid item-hour: `d`, log price minus the centred WINDOW-hour mean, with the
    league, phase, UTC `date` and `hour`. Liquid: traded in MIN_TRADED of its segment's
    hours (the launch fortnight, or the hours after it), with a median of at least
    MIN_CHAOS_H Chaos traded an hour; the Divine always counts."""
    out = []
    segment = pl.col("day_offset") < LAUNCH_DAYS
    for (_,), g in px.with_columns(seg=segment).group_by("seg"):
        hours = pl.datetime_range(
            g["observed_at"].min(), g["observed_at"].max(), "1h", eager=True
        ).alias("observed_at")
        n = g["observed_at"].n_unique()
        liquid = (
            g.group_by("item_id")
            .agg(share=pl.len() / n, chaos_h=pl.col("cv").median())
            .filter(
                (pl.col("share") >= MIN_TRADED)
                & ((pl.col("chaos_h") >= MIN_CHAOS_H) | (pl.col("item_id") == DIVINE))
            )
            .select("item_id")
        )
        grid = liquid.join(
            pl.DataFrame(hours).cast({"observed_at": g.schema["observed_at"]}), how="cross"
        )
        out.append(
            grid.join(g, on=["item_id", "observed_at"], how="left")
            .sort("item_id", "observed_at")
            .with_columns(
                m=pl.col("p")
                .log()
                .rolling_mean(WINDOW, min_samples=MIN_WINDOW, center=True)
                .over("item_id")
            )
            .with_columns(d=pl.col("p").log() - pl.col("m"))
            .filter(pl.col("d").is_not_null())
            .select("league", "phase", "item_id", "observed_at", "date", "hour", "d", "cv")
        )
    return pl.concat(out)


def _days(daily: pl.DataFrame, value: str) -> np.ndarray:
    """daily (league, date, hour, value) → a days × 24 matrix, NaN where missing."""
    wide = daily.pivot(on="hour", index=["league", "date"], values=value).sort("league", "date")
    return np.column_stack(
        [
            wide[str(h)].cast(pl.Float64).to_numpy()
            if str(h) in wide.columns
            else np.full(wide.height, np.nan)
            for h in range(24)
        ]
    )


def daily_price(dev: pl.DataFrame, items: list[str] | None = None) -> pl.DataFrame:
    """Median deviation over `items` (all but the Divine if None) per league-day and hour."""
    d = (
        dev.filter(pl.col("item_id") != DIVINE)
        if items is None
        else dev.filter(pl.col("item_id").is_in(items))
    )
    return d.group_by("league", "date", "hour").agg(v=pl.col("d").median())


def daily_volume(px: pl.DataFrame, items: list[str] | None = None) -> pl.DataFrame:
    """Each hour's share of the day's Chaos traded, on complete UTC days, from `hourly`'s
    rows (no detrending needed, so a league's first hours count too)."""
    d = px.filter(pl.col("item_id") != DIVINE)
    if items is not None:
        d = d.filter(pl.col("item_id").is_in(items))
    by_hour = d.group_by("league", "date", "hour").agg(cv=pl.col("cv").fill_null(0).sum())
    full = (
        by_hour.group_by("league", "date")
        .agg(n=pl.len(), tot=pl.col("cv").sum())
        .filter((pl.col("n") == 24) & (pl.col("tot") > 0))
    )
    return by_hour.join(full, on=["league", "date"]).select(
        "league", "date", "hour", v=pl.col("cv") / pl.col("tot")
    )


def profile(daily: pl.DataFrame, seed: int = 6) -> dict:
    """Mean of `v` per UTC hour over days, with a 90% interval from resampling days and
    `null95`, the best hour's value that 95% of hour-shuffled days stay under."""
    m = _days(daily, "v")
    if not len(m):
        return {
            "v": [math.nan] * 24,
            "lo": [math.nan] * 24,
            "hi": [math.nan] * 24,
            "days": 0,
            "null95": math.nan,
        }
    # Hours no day has (a league's first hours) stay NaN; nanmean warns about them.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        rng = np.random.default_rng(seed)
        mean = np.nanmean(m, axis=0)
        reps = np.stack(
            [np.nanmean(m[rng.integers(0, len(m), len(m))], axis=0) for _ in range(BOOT)]
        )
        lo, hi = np.nanpercentile(reps, [5, 95], axis=0)
        shuffled = [
            np.nanmax(np.nanmean(np.array([rng.permutation(r) for r in m]), axis=0))
            for _ in range(SHUFFLES)
        ]
    return {
        "v": mean.tolist(),
        "lo": lo.tolist(),
        "hi": hi.tolist(),
        "days": len(m),
        "null95": float(np.percentile(shuffled, 95)),
    }


def effect(p: dict, leagues: int) -> dict:
    """What timing is worth, from a price profile: the best hour over the day's average
    (`gain`) and over the worst hour (`gap`), as fractions of the price, and the noise
    floor (`null95`, same units). `small` unless the gain is at least SMALL, above the
    noise floor, and from at least MIN_LEAGUES leagues."""
    v = np.array(p["v"])
    if np.isnan(v).all():
        return {
            "gain": None,
            "gap": None,
            "best": None,
            "worst": None,
            "null95": None,
            "verdict": "small",
        }
    best, worst = int(np.nanargmax(v)), int(np.nanargmin(v))
    gain = math.expm1(v[best])
    worth = gain >= SMALL and v[best] > p["null95"] and leagues >= MIN_LEAGUES
    return {
        "gain": round(gain, 5),
        "gap": round(math.expm1(v[best] - v[worst]), 5),
        "best": best,
        "worst": worst,
        "null95": round(math.expm1(p["null95"]), 5),
        "verdict": "worth_it" if worth else "small",
    }


def stability(dev: pl.DataFrame, items: list[str] | None = None) -> float:
    """Mean over leagues of the correlation between that league's price profile and the
    other leagues' pooled (NaN with fewer than two leagues)."""
    leagues = dev["league"].unique().to_list()
    rs = []
    for lg in leagues:
        one = daily_price(dev.filter(pl.col("league") == lg), items)
        rest = daily_price(dev.filter(pl.col("league") != lg), items)
        if one.height < 20 or rest.height < 20:
            continue
        with warnings.catch_warnings():  # hours no day has stay NaN
            warnings.simplefilter("ignore", RuntimeWarning)
            a, b = np.nanmean(_days(one, "v"), axis=0), np.nanmean(_days(rest, "v"), axis=0)
        ok = ~np.isnan(a) & ~np.isnan(b)
        if ok.sum() >= 12:
            rs.append(float(np.corrcoef(a[ok], b[ok])[0, 1]))
    return float(np.mean(rs)) if rs else math.nan


def item_vs_pooled(dev: pl.DataFrame, target: str) -> dict:
    """Out of league, do items' own profiles from the other leagues predict `target`'s
    item profiles better than the pooled profile, or than nothing (all zeros)? Mean
    squared error per hour (in log points squared) of each forecast."""
    items = dev.filter(pl.col("item_id") != DIVINE)
    t, rest = items.filter(pl.col("league") == target), items.filter(pl.col("league") != target)
    pooled = np.nanmean(_days(daily_price(rest), "v"), axis=0)

    def per_item(d):
        return (
            d.group_by("item_id", "hour")
            .agg(v=pl.col("d").mean())
            .pivot(on="hour", index="item_id", values="v")
        )

    j = per_item(t).join(per_item(rest), on="item_id", suffix="_r")
    cols = [str(h) for h in range(24)]
    if not all(c in j.columns and c + "_r" in j.columns for c in cols):
        return {"items": 0}
    a = j.select(cols).to_numpy()
    b = j.select([c + "_r" for c in cols]).to_numpy()
    ok = ~np.isnan(a).any(axis=1) & ~np.isnan(b).any(axis=1)
    a, b = a[ok], b[ok]
    return {
        "items": len(a),
        "own": float(np.mean((a - b) ** 2)),
        "pooled": float(np.mean((a - pooled) ** 2)),
        "zero": float(np.mean(a**2)),
    }


def recent_vs_past(dev: pl.DataFrame, leagues: list[str], target: str) -> dict | None:
    """Where should the live league's profile come from? Days 7–14 of `target` (pooled,
    Chaos market) against two forecasts made before them: its own days 4–7 (the live
    league's recent days) and earlier leagues' days 7–14. Mean squared error per hour
    (log points squared), and that of forecasting no pattern (`zero`)."""
    items = dev.filter((pl.col("item_id") != DIVINE) & (pl.col("league") == target))
    hourly_day = items.with_columns(
        day=(pl.col("observed_at") - pl.col("observed_at").min()).dt.total_hours() / 24
    )

    def prof(d: pl.DataFrame) -> np.ndarray:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            return np.nanmean(_days(daily_price(d), "v"), axis=0)

    actual = prof(items.filter(pl.col("phase") == "d7_14"))
    recent = prof(hourly_day.filter(pl.col("phase") == "d2_7").filter(pl.col("day") >= 3))
    past = leagues[: leagues.index(target)]
    if not past:
        return None
    before = prof(
        dev.filter(
            pl.col("league").is_in(past)
            & (pl.col("phase") == "d7_14")
            & (pl.col("item_id") != DIVINE)
        )
    )
    return {
        "recent": float(np.nanmean((actual - recent) ** 2)),
        "past": float(np.nanmean((actual - before) ** 2)),
        "zero": float(np.nanmean(actual**2)),
    }


def _fractions(v: list[float]) -> list[float | None]:
    return [None if math.isnan(x) else round(math.expm1(x), 5) for x in v]


def phase_report(
    px: pl.DataFrame,
    dev: pl.DataFrame,
    dev_div: pl.DataFrame,
    bks: dict[str, list[str]],
    first_day: float,
) -> dict:
    """One phase's constants (see `report`); every frame already limited to the phase."""
    n = dev["league"].n_unique()
    chaos = profile(daily_price(dev))
    div_market = profile(daily_price(dev_div))
    rate = profile(daily_price(dev, [DIVINE]))
    vol = profile(daily_volume(px)) if first_day >= VOLUME_FROM_DAY else None
    mechanics = {}
    for mech, ids in bks.items():
        present = dev.filter(pl.col("item_id").is_in(ids))["item_id"].n_unique()
        if present < 3:
            continue
        p = profile(daily_price(dev, ids))
        r = stability(dev, ids)
        e = effect(p, n)
        mechanics[mech] = {
            "items": present,
            "stability": None if math.isnan(r) else round(r, 2),
            "shown": e["verdict"] == "worth_it" and r >= STABLE_R,
            "price": _fractions(p["v"]),
            **e,
        }
    r = stability(dev)
    return {
        "days": chaos["days"],
        "leagues": n,
        "price": _fractions(chaos["v"]),
        "price_divine_market": _fractions(div_market["v"]),
        "divine": _fractions(rate["v"]),
        "volume": None if vol is None else [round(x, 5) for x in vol["v"]],
        "effect": effect(chaos, n),
        "effect_divine_market": effect(div_market, n),
        "divine_effect": effect(rate, n),
        "stability": None if math.isnan(r) else round(r, 2),
        "mechanics": mechanics,
    }


def report(
    px: pl.DataFrame, dev: pl.DataFrame, dev_div: pl.DataFrame, bks: dict[str, list[str]]
) -> dict:
    """The sell helper's hour-of-day constants, per phase, from past leagues: price
    profiles (fractions over the 24-hour average, by UTC hour) in the Chaos market, in the
    Divine market, and the Divine's own Chaos price; the share of the day's Chaos traded
    each hour; each price profile's effect; and every basket's profile, `shown` when it
    holds across leagues (otherwise the page uses the pooled one). `px` is `hourly`'s
    Chaos market, `dev` its deviations, `dev_div` the Divine market's deviations. A phase
    with no data is left out."""
    out = {}
    for name, first_day, _ in PHASES:
        ph = dev.filter(pl.col("phase") == name)
        if ph.is_empty():
            continue
        out[name] = phase_report(
            px.filter(pl.col("phase") == name),
            ph,
            dev_div.filter(pl.col("phase") == name),
            bks,
            first_day,
        )
    return out


def _row(v: list, scale: float = 100.0) -> str:
    return " ".join("  n/a" if x is None else f"{x * scale:+5.1f}" for x in v)


def _effect(e: dict) -> str:
    return (
        f"gain {e['gain']:+.2%} null {e['null95']:.2%} best {e['best']:02d} "
        f"worst {e['worst']:02d} {e['verdict']}"
    )


def main() -> None:
    settings = get_settings()
    con = db.connect(settings.db_path, read_only=True)
    leagues = bt.hourly_leagues(con)
    px = pl.concat([hourly(con, lg) for lg in leagues])
    dev = pl.concat([deviations(px.filter(pl.col("league") == lg)) for lg in leagues])
    dev_div = pl.concat([deviations(hourly(con, lg, "divine")) for lg in leagues])
    rep = report(px, dev, dev_div, farming_baskets(con, settings))
    print("UTC hour:                     " + " ".join(f"{h:5d}" for h in range(24)))
    for name, r in rep.items():
        print(
            f"\n== {name}: {r['leagues']} leagues, {r['days']} days, stability {r['stability']} =="
        )
        ph = dev.filter(pl.col("phase") == name)
        for lg in leagues:
            one = ph.filter(pl.col("league") == lg)
            if not one.is_empty():
                p = profile(daily_price(one))
                print(
                    f"{lg[:12]:12s} Chaos market   {_row(_fractions(p['v']))}  "
                    f"{_effect(effect(p, MIN_LEAGUES))}"
                )  # this league's own floor
        print(f"{'all':12s} Chaos market   {_row(r['price'])}  {_effect(r['effect'])}")
        print(
            f"{'all':12s} Divine market  {_row(r['price_divine_market'])}  "
            f"{_effect(r['effect_divine_market'])}"
        )
        print(f"{'all':12s} Divine rate    {_row(r['divine'])}  {_effect(r['divine_effect'])}")
        if r["volume"]:
            print(f"{'all':12s} volume share   {_row(r['volume'])}")
        for mech, m in r["mechanics"].items():
            print(
                f"  {mech[:15]:15s} n={m['items']:3d} {_effect(m)} "
                f"stability {m['stability']} {'SHOWN' if m['shown'] else ''}"
            )
    print("\nDays 7–14 forecast from the league's days 4–7 or from earlier leagues (MSE ×1e4):")
    for lg in leagues:
        r = recent_vs_past(dev, leagues, lg)
        if r:
            print(
                f"{lg:12s} recent {r['recent'] * 1e4:.2f} past {r['past'] * 1e4:.2f} "
                f"zero {r['zero'] * 1e4:.2f}"
            )
    print("\nOwn item profiles vs pooled, out of league (launch fortnight; MSE, log pts² ×1e4):")
    launch = dev.filter(pl.col("phase") != "later")
    for lg in leagues:
        r = item_vs_pooled(launch, lg)
        if r["items"]:
            print(
                f"{lg:12s} items {r['items']}: own {r['own'] * 1e4:.1f} "
                f"pooled {r['pooled'] * 1e4:.1f} zero {r['zero'] * 1e4:.1f}"
            )


if __name__ == "__main__":
    main()
