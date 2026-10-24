"""Hour of day (analysis/hours.py): price and volume profiles by UTC hour, per phase of
the league, on synthetic hours."""

import math
from datetime import datetime, timedelta

import polars as pl
import pytest

from exiledbroker.analysis import hours as hr
from exiledbroker.storage import db

H = timedelta(hours=1)
LAUNCH = datetime(2026, 3, 6, 20)


def _hours(
    league: str = "Mirage",
    items: int = 6,
    days: int = 14,
    amp: float = 0.03,
    peak: int = 20,
    trend: float = 0.0,
    divine_amp: float = 0.0,
    seed: int = 1,
) -> pl.DataFrame:
    """`hourly`-shaped rows: each item's log price follows `trend` a day plus a daily
    cosine of amplitude `amp` peaking at UTC hour `peak`, with a little noise; volume
    peaks at the same hour. The Divine's Chaos price has its own cycle (`divine_amp`,
    peaking 12 hours later)."""
    import random

    rnd = random.Random(seed)
    rows = []
    for k in range(days * 24):
        t = LAUNCH + k * H
        cyc = math.cos(2 * math.pi * (t.hour - peak) / 24)
        for i in range(items):
            lp = math.log(10 + i) + trend * k / 24 + amp * cyc + rnd.gauss(0, 0.0005)
            rows.append((f"currency:i{i}", t, k / 24, math.exp(lp), 1000 * (1.5 + cyc)))
        rows.append((hr.DIVINE, t, k / 24, 200 * math.exp(-divine_amp * cyc), None))
    return pl.DataFrame(
        rows, schema=["item_id", "observed_at", "day_offset", "p", "cv"], orient="row"
    ).with_columns(
        league=pl.lit(league),
        phase=hr.phase_of(pl.col("day_offset")),
        date=pl.col("observed_at").dt.date(),
        hour=pl.col("observed_at").dt.hour(),
    )


def _profile(px: pl.DataFrame, phase: str = "d7_14") -> list[float]:
    dev = hr.deviations(px).filter(pl.col("phase") == phase)
    return hr.profile(hr.daily_price(dev))["v"]


def test_daily_cycle_is_recovered_at_its_hour():
    v = _profile(_hours(amp=0.03, peak=20))
    assert max(range(24), key=v.__getitem__) == 20
    assert min(range(24), key=v.__getitem__) == 8
    assert v[20] == pytest.approx(0.03, abs=0.004)


def test_a_trend_alone_makes_no_hour_pattern():
    # Prices rising 10% a day: a UTC-day mean would make late hours look 5% dear; the
    # centred mean leaves nothing.
    v = _profile(_hours(amp=0.0, trend=0.10))
    assert max(abs(x) for x in v) < 0.003


def test_a_trend_doesnt_shift_the_cycle():
    v = _profile(_hours(amp=0.03, peak=20, trend=0.10))
    assert max(range(24), key=v.__getitem__) == 20


def test_illiquid_items_are_left_out():
    px = _hours(items=2)
    thin = px.filter(pl.col("item_id") == "currency:i1").with_columns(
        item_id=pl.lit("currency:thin"), cv=pl.lit(10.0)
    )
    dev = hr.deviations(pl.concat([px, thin]))
    assert "currency:thin" not in dev["item_id"].to_list()
    assert hr.DIVINE in dev["item_id"].to_list()  # the Divine has no volume, but counts


def test_volume_shares_sum_to_one_on_complete_days_only():
    px = _hours(days=3)
    daily = hr.daily_volume(px)
    per_day = daily.group_by("date").agg(pl.col("v").sum(), n=pl.len())
    assert (per_day["n"] == 24).all()
    assert per_day["v"].to_list() == pytest.approx([1.0] * per_day.height)
    # Launch at 20:00 and three days of hours: the first and last UTC days are partial.
    assert per_day.height == 2
    v = hr.profile(daily)["v"]
    assert max(range(24), key=v.__getitem__) == 20


def test_effect_needs_size_noise_floor_and_two_leagues():
    big = hr.profile(hr.daily_price(hr.deviations(_hours(amp=0.03))))
    e = hr.effect(big, leagues=2)
    assert e["verdict"] == "worth_it" and e["best"] == 20 and e["worst"] == 8
    assert e["gain"] == pytest.approx(0.03, abs=0.004)
    assert e["gap"] == pytest.approx(math.expm1(0.06), abs=0.008)
    assert hr.effect(big, leagues=1)["verdict"] == "small"
    tiny = hr.profile(hr.daily_price(hr.deviations(_hours(amp=0.004))))
    assert hr.effect(tiny, leagues=5)["verdict"] == "small"  # under SMALL


def test_effect_with_no_data_is_small():
    e = hr.effect(
        hr.profile(pl.DataFrame(schema=hr.daily_price(hr.deviations(_hours(days=2))).schema)),
        leagues=5,
    )
    assert e["verdict"] == "small" and e["gain"] is None


def test_stability_across_leagues():
    same = pl.concat([hr.deviations(_hours(lg, seed=s)) for lg, s in (("A", 1), ("B", 2))])
    assert hr.stability(same) > 0.9
    opposite = pl.concat(
        [hr.deviations(_hours("A", peak=20)), hr.deviations(_hours("B", peak=8, seed=3))]
    )
    assert hr.stability(opposite) < -0.9
    assert math.isnan(hr.stability(hr.deviations(_hours("A"))))


def test_report_per_phase():
    a, b = _hours("A", divine_amp=0.02), _hours("B", seed=2, divine_amp=0.02)
    px = pl.concat([a, b])
    dev = pl.concat([hr.deviations(a), hr.deviations(b)])
    # The Divine market: the same items, priced in Divines, with no cycle of their own.
    dev_div = dev.filter(pl.col("item_id") != hr.DIVINE).with_columns(d=pl.lit(0.0))
    rep = hr.report(
        px,
        dev,
        dev_div,
        {"Essence": ["currency:i0", "currency:i1", "currency:i2"], "Tiny": ["currency:i0"]},
    )
    assert list(rep) == ["d0_2", "d2_7", "d7_14"]  # no "later" hours
    r = rep["d7_14"]
    assert r["leagues"] == 2 and r["days"] == 16 and len(r["price"]) == 24
    assert r["effect"]["verdict"] == "worth_it" and r["effect"]["best"] == 20
    assert r["price"][20] == pytest.approx(0.03, abs=0.004)
    # The Divine is dearest 12 hours away from the items' peak.
    assert r["divine_effect"]["best"] == 8 and r["divine_effect"]["verdict"] == "worth_it"
    assert r["effect_divine_market"]["verdict"] == "small"
    assert sum(r["volume"]) == pytest.approx(1.0, abs=1e-3)
    assert rep["d0_2"]["volume"] is None  # launch-day growth, not the time of day
    assert r["mechanics"]["Essence"]["shown"] and r["mechanics"]["Essence"]["items"] == 3
    assert "Tiny" not in r["mechanics"]  # under 3 items


def test_baskets_from_name_rules(tmp_path):
    con = db.connect(tmp_path / "t.duckdb")
    db.init_schema(con)
    names = {
        "currency:splinter-of-xoph": "Splinter of Xoph",
        "currency:essence-of-horror": "Essence of Horror",
        "currency:essence-scarab": "Essence Scarab",
        "currency:the-doctor": "The Doctor",
        "currency:chaos-orb": "Chaos Orb",
    }
    for iid, name in names.items():
        con.execute(
            "INSERT INTO item (id, game, canonical_name, category) VALUES (?, 'poe1', ?, "
            "'Currency')",
            [iid, name],
        )
    con.execute(
        "INSERT INTO tracked_item (item_id, group_id, group_label, sort_order) "
        "VALUES ('currency:the-doctor', 'divination', 'Divination cards', 1)"
    )
    b = hr.baskets(con)
    assert b["Breach"] == ["currency:splinter-of-xoph"]
    assert b["Essence"] == ["currency:essence-of-horror", "currency:essence-scarab"]
    assert b["Divination"] == ["currency:the-doctor"]
    assert not any("currency:chaos-orb" in ids for ids in b.values())
    con.close()


def test_recent_vs_past_forecasts_days_7_to_14():
    # League A cycles 3% all fortnight; B cycles 3% too: earlier leagues and B's own
    # days 4–7 both forecast B's days 7–14 well, far better than no pattern.
    dev = pl.concat([hr.deviations(_hours("A")), hr.deviations(_hours("B", seed=2))])
    assert hr.recent_vs_past(dev, ["A", "B"], "A") is None  # nothing earlier
    r = hr.recent_vs_past(dev, ["A", "B"], "B")
    assert r["past"] < r["zero"] / 20 and r["recent"] < r["zero"] / 20


def test_farming_baskets_from_the_config(tmp_path):
    from exiledbroker.config import Settings

    con = db.connect(tmp_path / "t.duckdb")
    db.init_schema(con)
    for iid, name in (
        ("currency:essence-of-horror", "Essence of Horror"),
        ("currency:remnant-of-corruption", "Remnant of Corruption"),
    ):
        con.execute(
            "INSERT INTO item (id, game, canonical_name, category) VALUES (?, 'poe1', ?, "
            "'Currency')",
            [iid, name],
        )
    toml = tmp_path / "mechanics.toml"
    toml.write_text(
        '[[mechanic]]\nid = "essence"\nname = "Essence"\n'
        'outputs = ["Essence of Horror"]\nlegacy = ["Remnant of Corruption"]\n'
    )
    got = hr.farming_baskets(con, Settings(data_dir=tmp_path, mechanics_file=toml))
    # Legacy outputs count: this reads past leagues.
    assert got == {"essence": ["currency:essence-of-horror", "currency:remnant-of-corruption"]}
    # No file: the provisional name rules.
    none = Settings(data_dir=tmp_path, mechanics_file=tmp_path / "missing.toml")
    assert hr.farming_baskets(con, none)["Essence"] == ["currency:essence-of-horror"]
    con.close()
