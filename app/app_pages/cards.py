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

from exiledbroker.services.divination import DEFAULT_WEIGHTS, score_turn_ins

st.title("Card turn-ins", icon=":material/style:")
st.caption(
    "Divination cards that turn into currency (or another card), where both the card and "
    "its reward trade on the exchange. A positive margin means buying a full set, "
    "turning it in and selling the reward beat the set's price, before gold fees and the "
    "time it takes to buy a set. Only cards NeverSink's filter shows (FilterBlade) are "
    "followed. Prices are the typical (median) hour, so a few junk trades can't skew them."
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
fmt = price_format(unit)

priced = cards.filter(pl.col("reward_item_id").is_not_null())
summary = turn_ins(league, unit)

# --- Scoring ---------------------------------------------------------------------
with st.container(border=True):
    st.markdown("**Opportunity score**")
    st.caption(
        "Each factor is ranked among the priced cards (best = 1), then weighted. Set a "
        "weight to 0 to ignore a factor."
    )
    w_cols = st.columns(4)
    weights = {
        "margin": w_cols[0].slider("Margin %", 0.0, 10.0, DEFAULT_WEIGHTS["margin"], 0.5),
        "investment": w_cols[1].slider(
            "Investment",
            0.0,
            10.0,
            DEFAULT_WEIGHTS["investment"],
            0.5,
            help="What a full set costs.",
        ),
        "profitable_hours": w_cols[2].slider(
            "Profitable hours", 0.0, 10.0, DEFAULT_WEIGHTS["profitable_hours"], 0.5
        ),
        "volume": w_cols[3].slider(
            "Volume traded",
            0.0,
            10.0,
            DEFAULT_WEIGHTS["volume"],
            0.5,
            help="Full sets' worth of cards traded: how quickly you can buy a set.",
        ),
    }
    with st.container(horizontal=True, vertical_alignment="bottom"):
        prefer = st.segmented_control(
            "Investment scores better when",
            ["Cheaper", "Bigger"],
            default="Cheaper",
            required=True,
            help="Cheaper: less capital and quicker to fill. Bigger: more chaos per flip.",
        )
        top_n = st.number_input("Show top", 5, 200, 25, 5, width=140)
        min_score = st.slider("Minimum score", 0.0, 1.0, 0.0, 0.05, width=260)
        profitable_only = st.toggle("Only profitable in the typical hour", value=True)

scored = score_turn_ins(summary, weights, prefer_cheaper_sets=prefer == "Cheaper")

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
    f"{cards.height - priced.height:,} (uniques, gems, random rewards) need an expected value.",
)
c3.metric(
    "Profitable 90%+ of hours",
    f"{scored.filter(pl.col('profitable_share') >= 0.9).height:,}"
    if not scored.is_empty()
    else "–",
    border=True,
    height="stretch",
)
top = (
    scored.row(0, named=True) if not scored.is_empty() and scored["score"][0] is not None else None
)
c4.metric(
    "Top score",
    f"{top['score']:.2f}" if top else "–",
    help=top["name"] if top else "No overlapping trades yet, or every weight is 0.",
    border=True,
    height="stretch",
)

if scored.is_empty():
    st.info(
        f"No hour in {league} has trades for both a card and its reward yet. {SYNC_HINT}",
        title="No turn-in prices yet",
        icon=":material/hourglass_top:",
    )
    st.stop()
if top is None:
    st.caption("Give at least one factor a weight above 0.")
    st.stop()

shown = scored.filter(pl.col("score") >= min_score)
if profitable_only:
    shown = shown.filter(pl.col("margin") > 0)
shown = shown.head(int(top_n)).with_columns(
    reward=pl.format("{}× {}", pl.col("reward_quantity"), pl.col("reward_name"))
)
if shown.is_empty():
    st.caption("No cards pass these filters. Lower the minimum score or allow unprofitable cards.")
    st.stop()

# --- Ranked table (full width) -----------------------------------------------------
st.subheader("Ranked turn-ins", icon=":material/leaderboard:")
st.caption(
    f"Typical hour, in {unit} ({sfx}). Money first; what the card gives comes last. "
    "Select a row to see its chart at the bottom of the page."
)
event = st.dataframe(
    shown.select(
        "name",
        "score",
        "set_cost",
        "reward_value",
        "margin",
        "margin_pct",
        "sets_traded",
        "profitable_share",
        "reward",
        "stack_size",
    ),
    hide_index=True,
    height=520,
    on_select="rerun",
    selection_mode="single-row",
    placeholder="–",
    key=f"turn-ins-{unit}",
    column_config={
        "name": st.column_config.TextColumn("Card", pinned=True, width="medium"),
        "score": st.column_config.ProgressColumn("Score", format="%.2f", min_value=0, max_value=1),
        "set_cost": st.column_config.NumberColumn(
            f"Set cost ({sfx})", format=fmt, help="What a full set of cards costs."
        ),
        "reward_value": st.column_config.NumberColumn(
            f"Reward ({sfx})", format=fmt, help="What the turn-in reward sells for."
        ),
        "margin": st.column_config.NumberColumn(f"Margin ({sfx})", format=fmt),
        "margin_pct": st.column_config.NumberColumn("Margin %", format="percent"),
        "sets_traded": st.column_config.NumberColumn(
            "Sets traded", format="compact", help="Full sets' worth of cards traded."
        ),
        "profitable_share": st.column_config.ProgressColumn(
            "Profitable hours",
            format="percent",
            min_value=0,
            max_value=1,
        ),
        "reward": st.column_config.TextColumn("Gives"),
        "stack_size": st.column_config.NumberColumn("Set size", help="Cards in a full set."),
    },
    alt="Divination card turn-ins ranked by score",
)

# --- Charts (bottom) ---------------------------------------------------------------
pick = (shown[event.selection.rows[0]] if event.selection.rows else shown.head(1)).row(
    0, named=True
)
st.subheader("Charts", icon=":material/show_chart:")
left, right = st.columns(2)
with left, st.container(border=True, height="stretch"):
    with st.container(horizontal=True, vertical_alignment="center"):
        st.markdown("**Opportunity map**")
        map_log = st.toggle(
            "Log scale",
            value=False,
            key="map-log",
            help="Spreads out cheap sets when set costs range from fractions of a chaos to "
            "thousands.",
        )
    st.caption(
        f"Top {shown.height} by score. Right = bigger investment, up = bigger margin, "
        "bubble size = sets traded, colour = score."
    )
    chart = (
        alt.Chart(shown.filter(pl.col("set_cost") > 0, pl.col("margin_pct") > -1))
        .mark_circle(opacity=0.8, stroke="#0F172A", strokeWidth=0.5)
        .encode(
            alt.X("set_cost:Q", title=f"Set cost ({sfx})").scale(
                type="log" if map_log else "linear"
            ),
            alt.Y("margin_pct:Q", title="Margin % (typical hour)", axis=alt.Axis(format="%")),
            alt.Size("sets_traded:Q", title="Sets traded", scale=alt.Scale(type="sqrt")),
            alt.Color("score:Q", title="Score", scale=alt.Scale(scheme="goldorange")),
            tooltip=[
                alt.Tooltip("name:N", title="Card"),
                alt.Tooltip("reward:N", title="Gives"),
                alt.Tooltip("set_cost:Q", title=f"Set cost ({sfx})", format=",.4~f"),
                alt.Tooltip("margin_pct:Q", title="Margin", format=".1%"),
                alt.Tooltip("profitable_share:Q", title="Profitable hours", format=".0%"),
                alt.Tooltip("sets_traded:Q", title="Sets traded", format=",.0f"),
                alt.Tooltip("score:Q", title="Score", format=".2f"),
            ],
        )
        .properties(height=380)
    )
    st.altair_chart(chart, alt="Card turn-in opportunity map")

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
    detail = (
        alt.Chart(long.filter(pl.col("value") > 0))
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
    st.altair_chart(detail, alt=f"{pick['name']} set cost versus reward value")
    st.caption(
        f"Profitable in {pick['profitable_share']:.0%} of {pick['hours']} hours; typical "
        f"margin {fmt_price(pick['margin'], unit) if pick['margin'] > 0 else 'negative'} "
        f"({pick['margin_pct']:.1%} of the set cost)."
    )
