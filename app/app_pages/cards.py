import altair as alt
import polars as pl
import streamlit as st
from common import (
    UNIT_SUFFIX,
    card_turn_in_hourly,
    database_ready,
    fmt_price,
    followed_cards,
    hourly_leagues,
    price_format,
    turn_ins,
)

st.title("Card turn-ins", icon=":material/style:")
st.caption(
    "Divination cards that turn into currency (or another card), where both the card and "
    "its reward trade on the exchange. A positive margin means buying a full set, "
    "turning it in and selling the reward beat the set's price at that hour, before gold "
    "fees and the time it takes to buy a set. Only cards NeverSink's filter shows "
    "(FilterBlade) are followed."
)

SYNC_HINT = (
    "Run `scripts/ingest.sh exchange -l <league>` (or `eb exchange sync`) to pull new hours."
)

if not database_ready():
    st.info(SYNC_HINT, title="No data yet", icon=":material/database:")
    st.stop()

cards = followed_cards()
leagues = hourly_leagues()
if cards.is_empty() or leagues.is_empty():
    st.info(SYNC_HINT, title="No card data loaded", icon=":material/database:")
    st.stop()

with st.container(horizontal=True, vertical_alignment="bottom"):
    league = st.selectbox("League", leagues["name"].to_list(), width=220, key="cards-league")
    unit = st.segmented_control(
        "Price in",
        ["chaos", "divine"],
        default="chaos",
        required=True,
        format_func=str.capitalize,
        key="cards-unit",
    )
sfx = UNIT_SUFFIX[unit]

priced = cards.filter(pl.col("reward_item_id").is_not_null())
random_or_other = cards.height - priced.height
table = turn_ins(league, unit).filter(pl.col("hours") > 0)

c1, c2, c3, c4 = st.columns(4)
c1.metric(
    "Cards followed",
    f"{cards.height:,}",
    border=True,
    height="stretch",
    help="Shown by NeverSink's filter at the configured strictness.",
)
c2.metric(
    "Turn-ins priced",
    f"{priced.height:,}",
    border=True,
    height="stretch",
    help="Fixed currency or card rewards. The other "
    f"{random_or_other:,} (uniques, gems, random rewards) need an expected value.",
)
c3.metric(
    "Profitable 90%+ of hours",
    f"{table.filter(pl.col('profitable_share') >= 0.9).height:,}" if not table.is_empty() else "–",
    border=True,
    height="stretch",
)
best = table.row(0, named=True) if not table.is_empty() else None
c4.metric(
    "Best average margin",
    fmt_price(best["avg_margin"], unit) if best else "–",
    help=best["name"] if best else "No overlapping trades yet.",
    border=True,
    height="stretch",
)

if table.is_empty():
    st.info(
        f"No hour in {league} has trades for both a card and its reward yet. {SYNC_HINT}",
        title="No turn-in prices yet",
        icon=":material/hourglass_top:",
    )
    st.stop()

table = table.with_columns(
    reward=pl.format("{}× {}", pl.col("reward_quantity"), pl.col("reward_name"))
)
fmt = price_format(unit)
left, right = st.columns([3, 2])
with left, st.container(border=True, height="stretch"):
    st.markdown("**Turn-in margins**")
    st.caption(f"Averages over the hours both traded, in {unit} ({sfx}). Select a row to chart it.")
    event = st.dataframe(
        table.select(
            "name",
            "filter_tier",
            "stack_size",
            "reward",
            "avg_set_cost",
            "avg_reward_value",
            "avg_margin",
            "avg_margin_pct",
            "profitable_share",
            "cards_traded",
        ),
        hide_index=True,
        height=460,
        on_select="rerun",
        selection_mode="single-row",
        placeholder="–",
        key=f"turn-ins-{unit}",
        column_config={
            "name": st.column_config.TextColumn("Card", pinned=True),
            "filter_tier": st.column_config.TextColumn("Tier", help="NeverSink filter tier."),
            "stack_size": st.column_config.NumberColumn("Set", help="Cards in a full set."),
            "reward": st.column_config.TextColumn("Reward"),
            "avg_set_cost": st.column_config.NumberColumn(f"Set cost ({sfx})", format=fmt),
            "avg_reward_value": st.column_config.NumberColumn(f"Reward ({sfx})", format=fmt),
            "avg_margin": st.column_config.NumberColumn(f"Margin ({sfx})", format=fmt),
            "avg_margin_pct": st.column_config.NumberColumn("Margin %", format="percent"),
            "profitable_share": st.column_config.ProgressColumn(
                "Profitable hours",
                format="percent",
                min_value=0,
                max_value=1,
            ),
            "cards_traded": st.column_config.NumberColumn(
                "Cards traded", format="compact", help="Units of the card traded in the window."
            ),
        },
        alt="Divination card turn-in margins",
    )

row = table[event.selection.rows[0]] if event.selection.rows else table.head(1)
pick = row.row(0, named=True)
with right, st.container(border=True, height="stretch"):
    st.markdown(f"**{pick['name']}**: {pick['stack_size']} cards → {pick['reward']}")
    series = card_turn_in_hourly(league, pick["item_id"], unit).drop_nulls("margin")
    if series.is_empty():
        st.caption("No overlapping hourly trades to chart.")
        st.stop()
    long = series.unpivot(
        index=["day_offset", "observed_at"],
        on=["set_cost", "reward_value"],
        variable_name="series",
        value_name="value",
    ).with_columns(
        pl.col("series").replace({"set_cost": "Full set of cards", "reward_value": "Reward"})
    )
    x = alt.X("day_offset:Q", title="Days since launch").scale(domain=[0, 14])
    chart = (
        alt.Chart(long)
        .mark_line(strokeWidth=1.5)
        .encode(
            x,
            alt.Y("value:Q", title=f"Value ({sfx})").scale(zero=False),
            alt.Color("series:N", title=None, legend=alt.Legend(orient="bottom")),
            tooltip=[
                alt.Tooltip("observed_at:T", title="Hour (UTC)", format="%b %d %H:%M"),
                alt.Tooltip("series:N", title="Series"),
                alt.Tooltip("value:Q", title=f"Value ({sfx})", format=",.4~f"),
            ],
        )
        .properties(height=380)
    )
    st.altair_chart(chart, alt=f"{pick['name']} set cost versus reward value")
    st.caption(
        f"Profitable in {pick['profitable_share']:.0%} of {pick['hours']} hours; "
        f"average margin {fmt_price(pick['avg_margin'], unit)} "
        f"({pick['avg_margin_pct']:.1%} of the set cost)."
    )
