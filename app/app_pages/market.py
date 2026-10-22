import altair as alt
import polars as pl
import streamlit as st
from common import (
    UNIT_SUFFIX,
    database_ready,
    fmt_price,
    hourly,
    hourly_leagues,
    price_format,
    summary,
)

st.title("Launch market", icon=":material/candlestick_chart:")

SYNC_HINT = (
    "Run `scripts/ingest.sh exchange -l <league>` (or `eb exchange sync`) to pull new hours."
)

if not database_ready():
    st.info(SYNC_HINT, title="No data yet", icon=":material/database:")
    st.stop()

leagues = hourly_leagues()
if leagues.is_empty():
    st.info(SYNC_HINT, title="No leagues tracked on the exchange", icon=":material/database:")
    st.stop()

league = st.selectbox("League", leagues["name"].to_list(), width=220)
info = leagues.filter(pl.col("name") == league).row(0, named=True)

# A new league is registered before GGG publishes its first hour (each hour appears
# only once it has ended), so "no data yet" is a normal state, not an error.
if info["row_count"] == 0:
    expected = f" Expected launch: {info['start_at']:%Y-%m-%d}." if info["start_at"] else ""
    st.info(
        f"{league} is being tracked, but no hourly trades have been published yet. GGG "
        f"publishes each hour of exchange history after that hour ends.{expected} "
        f"{SYNC_HINT}",
        title="Waiting for the first hour of trades",
        icon=":material/hourglass_top:",
    )
    st.stop()

launch_hours = 14 * 24
# A live league loaded from its recent hours may not include its launch fortnight.
past_launch = info["launched_at"] and info["hours_covered"] > launch_hours
if past_launch and summary(league, ("currency",), "chaos").is_empty():
    st.info(
        f"The hours loaded for {league} are from after its first two weeks, so there's "
        "no launch window to show. The Live market page shows what's trading now; "
        f'`eb exchange sync -l "{league}"` loads its launch fortnight.',
        title="Past the launch window",
        icon=":material/schedule:",
    )
    st.stop()
hours = min(info["hours_covered"], launch_hours)
covered = f"{hours} hour{'s' if hours != 1 else ''}" if hours < 48 else f"{hours / 24:.0f} days"
st.caption(
    f"Hourly trades on the in-game currency exchange: {covered} since launch "
    f"({info['launched_at']:%Y-%m-%d %H:%M} UTC). Each hour's price is volume-weighted "
    "across Chaos and Divine markets."
)

# KPI cards: the core currencies, each in the unit it's normally quoted in. Chaos is
# left out: it's the unit everything else is priced in.
KPIS = [
    ("currency:divine-orb", "chaos"),
    ("currency:orb-of-alchemy", "chaos"),
    ("currency:mirror-of-kalandra", "divine"),
    ("currency:mirror-shard", "divine"),
]
core = {u: summary(league, ("currency",), u) for u in ("chaos", "divine")}
for col, (item_id, kpi_unit) in zip(st.columns(len(KPIS)), KPIS, strict=True):
    rows = core[kpi_unit].filter(pl.col("item_id") == item_id)
    r = rows.row(0, named=True) if not rows.is_empty() else None
    name = r["name"] if r else item_id.removeprefix("currency:").replace("-", " ").title()
    if r is None or r["latest"] is None:
        col.metric(name, "–", help="No trades yet.", border=True, height="stretch")
        continue
    has_change = r["days"] > 1 and r["change"] is not None
    col.metric(
        name,
        fmt_price(r["latest"], kpi_unit),
        delta=f"{r['change']:+.0%}" if has_change else None,
        delta_description="vs. day 1" if has_change else None,
        chart_data=r["trend"] if len(r["trend"]) > 1 else None,
        chart_type="line",
        border=True,
        height="stretch",
    )

st.space("small")
st.subheader("Price mappings", icon=":material/stacked_line_chart:")

GROUPS = {
    "Currency": ("currency",),
    "High-tier essences": ("essence",),
    "Scarabs": ("scarab",),
    "Divination cards": ("divination",),
}
with st.container(horizontal=True, vertical_alignment="bottom"):
    group = st.segmented_control("Group", list(GROUPS), default="Currency", required=True)
    unit = st.segmented_control(
        "Price in",
        ["chaos", "divine"],
        default="chaos",
        required=True,
        format_func=str.capitalize,
    )
sfx = UNIT_SUFFIX[unit]
table = summary(league, GROUPS[group], unit)
# An item priced in itself is a flat line at 1; leave it out of its own unit.
self_priced = {"chaos": "currency:chaos-orb", "divine": "currency:divine-orb"}[unit]
table = table.filter(pl.col("item_id") != self_priced)

if table.is_empty():
    st.info(
        f"Nothing in {group.lower()} has traded yet in {league}. {SYNC_HINT}",
        title="No trades yet",
        icon=":material/hourglass_top:",
    )
    st.stop()

left, right = st.columns([2, 3])
with left, st.container(border=True, height="stretch"):
    st.markdown("**Launch-window summary**")
    st.caption(
        f"Prices in {unit} ({sfx}), sorted by average price over the window "
        "(volume-weighted). Select rows to chart them."
    )
    fmt = price_format(unit)
    event = st.dataframe(
        table.select(
            "name",
            "average",
            "day_1",
            "day_3",
            "day_7",
            "day_14",
            "change",
            "peak_day",
            "trend",
            "chaos_volume",
        ),
        hide_index=True,
        height=460,
        on_select="rerun",
        selection_mode="multi-row",
        placeholder="–",
        key=f"table-{group}-{unit}",
        column_config={
            "name": st.column_config.TextColumn("Item", pinned=True),
            "average": st.column_config.NumberColumn(
                f"Avg price ({sfx})",
                format=fmt,
                help="Volume-weighted average price over the whole window.",
            ),
            "day_1": st.column_config.NumberColumn(f"Day 1 ({sfx})", format=fmt),
            "day_3": st.column_config.NumberColumn(f"Day 3 ({sfx})", format=fmt),
            "day_7": st.column_config.NumberColumn(f"Day 7 ({sfx})", format=fmt),
            "day_14": st.column_config.NumberColumn(f"Day 14 ({sfx})", format=fmt),
            "change": st.column_config.NumberColumn(
                "Day 1 → latest", format="percent", help="Change from day 1 to the last day."
            ),
            "peak_day": st.column_config.NumberColumn("Peak day", format="%d"),
            "trend": st.column_config.LineChartColumn("Daily trend"),
            "chaos_volume": st.column_config.NumberColumn(
                "Volume (c)", format="compact", help="Chaos-equivalent traded in the window."
            ),
        },
        alt=f"{group} launch-window price summary",
    )

picked_rows = event.selection.rows
# Without a selection, chart the five most-traded items (not Chaos itself, which is
# the pricing unit and would flatten everything else).
picked = (
    table[picked_rows]
    if picked_rows
    else table.filter(pl.col("item_id") != "currency:chaos-orb")
    .sort("chaos_volume", descending=True)
    .head(5)
)

with right, st.container(border=True, height="stretch"):
    with st.container(horizontal=True, vertical_alignment="center"):
        st.markdown("**Hourly price**")
        log_scale = st.toggle(
            "Log scale",
            value=False,
            help="Useful when comparing items with very different prices.",
        )
    if not picked_rows:
        st.caption("Showing the five most-traded items. Select rows in the table to change.")
    series = hourly(league, tuple(picked["item_id"].to_list()), unit)
    # Hours without a price in this unit (e.g. before the first Divine trade) can't be
    # plotted, and the optional log scale can't show zero.
    series = series.filter(pl.col("value").is_not_null() & (pl.col("value") > 0))
    if series.is_empty():
        st.caption("No hourly trades to chart yet.")
        st.stop()
    scale = "log" if log_scale else "linear"
    x = alt.X("day_offset:Q", title="Days since launch").scale(domain=[0, 14])
    y = alt.Y("value:Q", title=f"Price ({sfx})").scale(type=scale, zero=False)
    tooltip = [
        alt.Tooltip("name:N", title="Item"),
        alt.Tooltip("observed_at:T", title="Hour (UTC)", format="%b %d %H:%M"),
        alt.Tooltip("value:Q", title=f"Price ({sfx})", format=",.4~f"),
        alt.Tooltip("low:Q", title=f"Low ({sfx})", format=",.4~f"),
        alt.Tooltip("high:Q", title=f"High ({sfx})", format=",.4~f"),
        alt.Tooltip("volume:Q", title="Units traded", format=",.0f"),
    ]
    lines = (
        alt.Chart(series)
        .mark_line(strokeWidth=1.5)
        .encode(
            x,
            y,
            alt.Color("name:N", title=None, legend=alt.Legend(orient="bottom")),
            tooltip=tooltip,
        )
    )
    chart = lines
    if picked.height == 1:
        band = (
            alt.Chart(series)
            .mark_area(opacity=0.2)
            .encode(x, alt.Y("low:Q").scale(type=scale, zero=False), alt.Y2("high:Q"))
        )
        chart = band + lines
        st.caption("Shaded band: lowest to highest traded price in each hour.")
    st.altair_chart(chart.properties(height=420), alt=f"Hourly {group.lower()} prices")
