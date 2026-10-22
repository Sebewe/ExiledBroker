import altair as alt
import polars as pl
import streamlit as st
from common import database_ready, fmt_price, hourly, hourly_leagues, price_format, summary

st.title("Launch market", icon=":material/candlestick_chart:")

if not database_ready():
    st.info(
        "Run `eb exchange sync -l Mirage` to fetch and load the hourly data.",
        title="No data yet",
        icon=":material/database:",
    )
    st.stop()

leagues = hourly_leagues()
if leagues.is_empty():
    st.info(
        "Run `eb exchange sync -l Mirage` to fetch and load the hourly data.",
        title="No hourly exchange data loaded",
        icon=":material/database:",
    )
    st.stop()

with st.container(horizontal=True, vertical_alignment="bottom"):
    league = st.selectbox("League", leagues["name"].to_list(), width=220)
    unit = st.segmented_control(
        "Price in",
        ["chaos", "divine"],
        default="chaos",
        required=True,
        format_func=str.capitalize,
    )

info = leagues.filter(pl.col("name") == league).row(0, named=True)
st.caption(
    f"Hourly trades on the in-game currency exchange for the first "
    f"{info['days_covered'] + 1 / 24:.0f} days after launch "
    f"({info['launched_at']:%Y-%m-%d %H:%M} UTC). Each hour's price is volume-weighted "
    "across Chaos and Divine markets."
)

# KPI cards: the core currencies, each in the unit it's normally quoted in.
KPIS = [
    ("currency:divine-orb", "chaos"),
    ("currency:chaos-orb", "divine"),
    ("currency:orb-of-alchemy", "chaos"),
    ("currency:mirror-of-kalandra", "divine"),
    ("currency:mirror-shard", "divine"),
]
core = {
    u: summary(league, ("chaos", "divine", "alchemy", "mirror"), u) for u in ("chaos", "divine")
}
with st.container(horizontal=True):
    for item_id, kpi_unit in KPIS:
        rows = core[kpi_unit].filter(pl.col("item_id") == item_id)
        if rows.is_empty():
            continue
        r = rows.row(0, named=True)
        st.metric(
            r["name"],
            fmt_price(r["latest"], kpi_unit),
            delta=f"{r['change']:+.0%}" if r["change"] is not None else None,
            delta_description="vs. day 1",
            chart_data=r["trend"],
            chart_type="line",
            border=True,
        )

st.space("small")
st.subheader("Price mappings", icon=":material/stacked_line_chart:")

GROUPS = {
    "Currency": ("chaos", "divine", "alchemy"),
    "Mirrors": ("mirror",),
    "High-tier essences": ("essence",),
    "Scarabs": ("scarab",),
}
group = st.segmented_control(
    "Group", list(GROUPS), default="Currency", required=True, label_visibility="collapsed"
)
table = summary(league, GROUPS[group], unit)
# An item priced in itself is a flat line at 1; leave it out of its own unit.
self_priced = {"chaos": "currency:chaos-orb", "divine": "currency:divine-orb"}[unit]
table = table.filter(pl.col("item_id") != self_priced)

if table.is_empty():
    st.caption("No trades for this group in the window.")
    st.stop()

left, right = st.columns([2, 3])
with left, st.container(border=True, height="stretch"):
    st.markdown("**Launch-window summary**")
    st.caption("Sorted by chaos-equivalent volume. Select rows to chart them.")
    fmt = price_format(unit)
    event = st.dataframe(
        table.select(
            "name",
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
        key=f"table-{group}-{unit}",
        column_config={
            "name": st.column_config.TextColumn("Item", pinned=True),
            "day_1": st.column_config.NumberColumn("Day 1", format=fmt),
            "day_3": st.column_config.NumberColumn("Day 3", format=fmt),
            "day_7": st.column_config.NumberColumn("Day 7", format=fmt),
            "day_14": st.column_config.NumberColumn("Day 14", format=fmt),
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
picked = table[picked_rows] if picked_rows else table.head(min(5, table.height))

with right, st.container(border=True, height="stretch"):
    with st.container(horizontal=True, vertical_alignment="center"):
        st.markdown("**Hourly price**")
        log_scale = st.toggle("Log scale", value=group != "Mirrors")
    if not picked_rows:
        st.caption("Showing the top items by volume.")
    series = hourly(league, tuple(picked["item_id"].to_list()), unit)
    y = alt.Y("value:Q", title=f"Price ({unit})").scale(
        type="log" if log_scale else "linear", zero=False
    )
    x = alt.X("day_offset:Q", title="Days since launch").scale(domain=[0, 14])
    tooltip = [
        alt.Tooltip("name:N", title="Item"),
        alt.Tooltip("observed_at:T", title="Hour (UTC)", format="%b %d %H:%M"),
        alt.Tooltip("value:Q", title="Price", format=",.4~f"),
        alt.Tooltip("low:Q", title="Low", format=",.4~f"),
        alt.Tooltip("high:Q", title="High", format=",.4~f"),
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
            .encode(
                x,
                alt.Y("low:Q").scale(type="log" if log_scale else "linear", zero=False),
                alt.Y2("high:Q"),
            )
        )
        chart = band + lines
        st.caption("Shaded band: lowest to highest traded price in each hour.")
    st.altair_chart(chart.properties(height=420), alt=f"Hourly {group.lower()} prices")
