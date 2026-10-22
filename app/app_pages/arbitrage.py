import altair as alt
import polars as pl
import streamlit as st
from common import analysis_leagues, cross_market_item, cross_market_per_league, database_ready

from exiledbroker.analysis import launch_patterns as lp
from exiledbroker.services import cross_market as xm

st.title("Arbitrage trading", icon=":material/swap_horiz:")
st.caption(
    "Many items trade against both Chaos and Divines on the exchange, and the two markets "
    "don't always agree. Each hour, a loop through both markets is priced at the worst "
    "prices seen that hour on every leg (highest buy, lowest sell, worst Divine rate). "
    "These are hourly summaries, not an order book: a paying hour means trades happened "
    "at those prices, not that one player could have caught both sides. Treat the list "
    "as candidates to check live."
)

SYNC_HINT = "Run `scripts/ingest.sh exchange` (or `eb exchange sync`) to pull hourly data."

if not database_ready():
    st.info(SYNC_HINT, title="No data yet", icon=":material/database:")
    st.stop()

pool = analysis_leagues()["hourly"]
if not pool:
    st.info(SYNC_HINT, title="No hourly exchange data loaded", icon=":material/hourglass_top:")
    st.stop()

# --- Controls ----------------------------------------------------------------------
with st.container(border=True):
    with st.container(horizontal=True, vertical_alignment="bottom"):
        leagues = st.pills(
            "Leagues (newest first)",
            pool,
            selection_mode="multi",
            default=pool,
            key="arb-leagues",
        )
        half_life = st.number_input(
            "Recency half-life (leagues)",
            0.5,
            10.0,
            2.0,
            0.5,
            width=220,
            help="A league this many leagues older than the newest counts half as much.",
        )
    with st.container(horizontal=True, vertical_alignment="bottom"):
        direction = st.segmented_control(
            "Loop",
            list(xm.DIRECTIONS),
            default="chaos_first",
            required=True,
            format_func=xm.DIRECTIONS.get,
        )
        buffer_pct = st.number_input(
            "Fee buffer (%)",
            0.0,
            50.0,
            2.0,
            0.5,
            width=150,
            help="An hour only counts if the loop beats this, to cover gold fees and "
            "rounding to whole-number trade ratios.",
        )
        min_hours = st.number_input(
            "Min hours in both markets",
            1,
            336,
            24,
            6,
            width=200,
            help="Per league. Fewer hours = too thin to judge.",
        )
        min_price = st.number_input(
            "Min item price (c)",
            0.0,
            10000.0,
            1.0,
            0.5,
            width=170,
            help="Filters out dust-priced bulk items (e.g. Rogue's Markers at ~0.001c), "
            "where gaps say more about how they trade than about profit.",
        )
    st.markdown("**Score weights**")
    w_cols = st.columns(4)
    score_weights = {
        "edge": w_cols[0].slider(
            "Edge",
            0.0,
            10.0,
            xm.DEFAULT_WEIGHTS["edge"],
            0.5,
            help="Typical edge in the hours the loop paid.",
        ),
        "consistency": w_cols[1].slider(
            "Paying hours",
            0.0,
            10.0,
            xm.DEFAULT_WEIGHTS["consistency"],
            0.5,
            help="Recency-weighted share of hours the loop beat the buffer.",
        ),
        "worst_league": w_cols[2].slider(
            "Worst league",
            0.0,
            10.0,
            xm.DEFAULT_WEIGHTS["worst_league"],
            0.5,
            help="Share of paying hours in the weakest selected league (0 if the item is "
            "missing from one): rewards items that paid every league.",
        ),
        "volume": w_cols[3].slider(
            "Volume",
            0.0,
            10.0,
            xm.DEFAULT_WEIGHTS["volume"],
            0.5,
            help="Chaos value that traded in both markets.",
        ),
    }

if not leagues:
    st.caption("Pick at least one league.")
    st.stop()
leagues = [name for name in pool if name in leagues]  # newest first
recency = lp.recency_weights(leagues, half_life)

per = cross_market_per_league(tuple(leagues), direction, buffer_pct / 100, int(min_hours))
if per.is_empty():
    st.info(
        "No item traded in both markets often enough in these leagues yet.",
        title="No data",
        icon=":material/hourglass_top:",
    )
    st.stop()
summary = xm.across_leagues(per, leagues, recency).filter(pl.col("chaos_price") >= min_price)
scored = xm.score(summary, score_weights)

total_hours = int(per["hours"].sum())
paying_hours = float((per["share"] * per["hours"]).sum())
c1, c2, c3, c4 = st.columns(4)
c1.metric("Item-hours in both markets", f"{total_hours:,}", border=True, height="stretch")
c2.metric(
    "Hours the loop paid",
    f"{paying_hours / total_hours:.1%}",
    border=True,
    height="stretch",
    help=f"After the {buffer_pct:g}% buffer.",
)
steady = scored.filter(pl.col("worst_league_share") >= 0.25).height if not scored.is_empty() else 0
c3.metric("Paid ≥25% of hours in every league", f"{steady:,}", border=True, height="stretch")
top = (
    scored.row(0, named=True) if not scored.is_empty() and scored["score"][0] is not None else None
)
c4.metric(
    "Top score",
    f"{top['score']:.2f}" if top else "–",
    help=top["name"] if top else None,
    border=True,
    height="stretch",
)
if top is None:
    st.caption("No item passes these filters, or every weight is 0.")
    st.stop()

# --- Ranked table (full width) -----------------------------------------------------
st.subheader("Ranked loops", icon=":material/leaderboard:")
st.caption("Money first. Select a row to see its charts at the bottom of the page.")
event = st.dataframe(
    scored.select(
        "name",
        "score",
        "chaos_price",
        "weighted_edge",
        "capacity_chaos",
        "overlap_chaos",
        "weighted_share",
        "worst_league_share",
        "median_gap",
        "leagues",
    ),
    hide_index=True,
    height=520,
    on_select="rerun",
    selection_mode="single-row",
    placeholder="–",
    key=f"arb-table-{direction}",
    column_config={
        "name": st.column_config.TextColumn("Item", pinned=True, width="medium"),
        "score": st.column_config.ProgressColumn("Score", format="%.2f", min_value=0, max_value=1),
        "chaos_price": st.column_config.NumberColumn(
            "Price (c)", format="%.2f", help="Typical Chaos price of one item."
        ),
        "weighted_edge": st.column_config.NumberColumn(
            "Edge",
            format="percent",
            help="Typical worst-price edge in the hours the loop paid.",
        ),
        "capacity_chaos": st.column_config.NumberColumn(
            "Profit, upper bound (c)",
            format="compact",
            help="Edge × volume in paying hours, summed over the selected leagues. An upper "
            "bound: assumes you could have taken all of it.",
        ),
        "overlap_chaos": st.column_config.NumberColumn(
            "Volume (c)", format="compact", help="Chaos value traded in both markets."
        ),
        "weighted_share": st.column_config.ProgressColumn(
            "Paying hours", format="percent", min_value=0, max_value=1
        ),
        "worst_league_share": st.column_config.ProgressColumn(
            "Worst league", format="percent", min_value=0, max_value=1
        ),
        "median_gap": st.column_config.NumberColumn(
            "Typical gap",
            format="percent",
            help="Median of (price via Divines ÷ Chaos price − 1), at average prices.",
        ),
        "leagues": st.column_config.NumberColumn("Leagues"),
    },
    alt="Arbitrage loops ranked by score",
)

# --- Charts for the selected item (bottom) -----------------------------------------
pick = (scored[event.selection.rows[0]] if event.selection.rows else scored.head(1)).row(
    0, named=True
)
item_hours = cross_market_item(tuple(leagues), pick["item_id"], direction)
present = [name for name in leagues if name in item_hours["league"].unique().to_list()]
st.subheader(f"{pick['name']} in each market", icon=":material/show_chart:")
if not present:
    st.caption("No cross-market hours to chart for this item.")
    st.stop()
detail_league = st.segmented_control(
    "League", present, default=present[0], required=True, key="arb-league"
)
one = item_hours.filter(pl.col("league") == detail_league)
x = alt.X("day_offset:Q", title="Days since launch").scale(domain=[0, 14])
prices = one.unpivot(
    index=["day_offset", "observed_at"],
    on=["chaos_price", "via_divines"],
    variable_name="series",
    value_name="value",
).with_columns(
    pl.col("series").replace(
        {"chaos_price": "Bought with Chaos", "via_divines": "Sold for Divines (in chaos)"}
    )
)
left, right = st.columns(2)
with left, st.container(border=True, height="stretch"):
    st.markdown("**Price in each market**")
    st.altair_chart(
        alt.Chart(prices)
        .mark_line(strokeWidth=1.2)
        .encode(
            x,
            alt.Y("value:Q", title="Price (c)").scale(zero=False),
            alt.Color("series:N", title=None, legend=alt.Legend(orient="bottom")),
            tooltip=[
                alt.Tooltip("observed_at:T", title="Hour (UTC)", format="%b %d %H:%M"),
                "series",
                alt.Tooltip("value:Q", title="Price (c)", format=",.4~f"),
            ],
        )
        .properties(height=300),
        alt=f"{pick['name']} price in each market",
    )
with right, st.container(border=True, height="stretch"):
    st.markdown("**Loop edge per hour**")
    bars = (
        alt.Chart(one)
        .mark_bar()
        .encode(
            x,
            alt.Y("edge:Q", title="Worst-price edge", axis=alt.Axis(format="%")),
            color=alt.condition(
                alt.datum.edge > buffer_pct / 100, alt.value("#34D399"), alt.value("#F87171")
            ),
            tooltip=[
                alt.Tooltip("observed_at:T", title="Hour (UTC)", format="%b %d %H:%M"),
                alt.Tooltip("edge:Q", title="Edge", format=".1%"),
                alt.Tooltip("overlap_chaos:Q", title="Volume (c)", format=",.0f"),
            ],
        )
    )
    rule = (
        alt.Chart(pl.DataFrame({"y": [buffer_pct / 100]}))
        .mark_rule(strokeDash=[4, 4])
        .encode(y="y:Q")
    )
    st.altair_chart((bars + rule).properties(height=300), alt=f"{pick['name']} loop edge")
    st.caption("Green hours beat the fee buffer (dashed line).")
