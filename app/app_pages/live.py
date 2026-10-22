from datetime import UTC, datetime, timedelta

import polars as pl
import streamlit as st
from common import UNIT_SUFFIX, database_ready, live_cards, live_leagues, live_loops, price_format

from exiledbroker.services import cross_market as xm

st.title("Live market", icon=":material/bolt:")
st.caption(
    "What's best to arbitrage right now in a running league. GGG publishes each hour of "
    "exchange trades a few minutes after it ends, so ‘now’ is the latest published "
    "hour, about an hour behind real time. Keep it updated with `scripts/ingest.sh live` "
    "(or `eb live watch`)."
)

HINT = "Start the live feed with `scripts/ingest.sh live` (or `eb live watch`)."

if not database_ready():
    st.info(HINT, title="No data yet", icon=":material/database:")
    st.stop()
leagues = live_leagues()
if leagues.is_empty():
    st.info(HINT, title="No live data yet", icon=":material/hourglass_top:")
    st.stop()

with st.container(horizontal=True, vertical_alignment="bottom"):
    league = st.selectbox("League", leagues["name"].to_list(), width=220, key="live-league")
    auto = st.toggle(
        "Live updates",
        value=True,
        help="Re-read the data every minute. New hours appear as the live feed loads them.",
    )


@st.fragment(run_every="1m" if auto else None)
def live_view() -> None:
    info = live_leagues().filter(pl.col("name") == league)
    if info.is_empty():
        st.info(HINT, title="No live data yet", icon=":material/hourglass_top:")
        return
    latest = info["latest_hour"][0]
    if latest is None:
        launched = info["launched_at"][0]
        if launched is None:
            st.info(
                f"{league} is registered but hasn't appeared on the exchange yet. Its first "
                "trades show up here about an hour after launch, as GGG publishes each hour.",
                title="Waiting for launch",
                icon=":material/hourglass_top:",
            )
        else:
            st.info(
                f"{league} launched at {launched:%b %d, %H:00} UTC, but nothing has traded on "
                "the exchange in its published hours yet. Trades show up here as GGG "
                "publishes each hour.",
                title="Waiting for the first trades",
                icon=":material/hourglass_top:",
            )
        return
    now = datetime.now(UTC).replace(tzinfo=None)
    published_at = latest + timedelta(hours=1)  # the hour's trades are complete at its end
    age_min = max(0, int((now - published_at).total_seconds() // 60))
    next_due = published_at + timedelta(hours=1, minutes=6)
    status = (
        f"Latest published hour: **{latest:%b %d, %H:00}–{published_at:%H:00} UTC** "
        f"({age_min // 60}h {age_min % 60}m ago). "
    )
    if age_min > 75:
        st.warning(
            status + f"That's older than expected, so the live feed may not be running. {HINT}",
            icon=":material/sync_problem:",
        )
    else:
        st.success(
            status + f"Next hour expected around {next_due:%H:%M} UTC.",
            icon=":material/check_circle:",
        )

    with st.container(border=True), st.container(horizontal=True, vertical_alignment="bottom"):
        lookback = st.segmented_control(
            "Look back",
            [1, 3, 6, 12, 24],
            default=6,
            required=True,
            format_func=lambda h: f"{h}h",
            key="live-lookback",
            help="How many recent hours to judge consistency and volume over.",
        )
        direction = st.segmented_control(
            "Loop",
            list(xm.DIRECTIONS),
            default="chaos_first",
            required=True,
            format_func=xm.DIRECTIONS.get,
            key="live-direction",
        )
        buffer_pct = st.number_input(
            "Fee buffer (%)",
            0.0,
            50.0,
            2.0,
            0.5,
            width=150,
            key="live-buffer",
            help="A loop only counts if it beats this, to cover gold fees and rounding.",
        )
        min_price = st.number_input(
            "Min item price (c)",
            0.0,
            10000.0,
            1.0,
            0.5,
            width=170,
            key="live-price",
            help="Filters out dust-priced bulk items.",
        )
        unit = st.segmented_control(
            "Cards priced in",
            ["chaos", "divine"],
            default="chaos",
            required=True,
            format_func=str.capitalize,
            key="live-unit",
        )
    sfx = UNIT_SUFFIX[unit]

    loops = live_loops(league, latest, direction, buffer_pct / 100, lookback, min_price)
    cards = live_cards(league, latest, lookback, unit)
    c1, c2, c3 = st.columns(3)
    c1.metric(
        "Loops paying in their latest hour",
        f"{loops.height:,}",
        border=True,
        height="stretch",
        help=f"Beat the {buffer_pct:g}% buffer, priced ≥{min_price:g}c.",
    )
    c2.metric(
        "Card flips paying in their latest hour", f"{cards.height:,}", border=True, height="stretch"
    )
    c3.metric("Hours loaded", f"{info['hours'][0]:,}", border=True, height="stretch")

    st.subheader("Best loops right now", icon=":material/swap_horiz:")
    st.caption(
        "Chaos ↔ Divine: edge at the worst prices of the item's latest hour, then how "
        f"often it paid over the last {lookback}h. Hourly summaries, not an order book: "
        "check the live exchange before trading."
    )
    if loops.is_empty():
        st.caption("Nothing beat the buffer in the latest hours.")
    else:
        st.dataframe(
            loops.select(
                "name",
                "score",
                "price",
                "last_edge",
                "overlap_chaos",
                "paying_share",
                "hours_since",
                "last_gap",
            ),
            hide_index=True,
            height=380,
            placeholder="–",
            column_config={
                "name": st.column_config.TextColumn("Item", pinned=True, width="medium"),
                "score": st.column_config.ProgressColumn(
                    "Score", format="%.2f", min_value=0, max_value=1
                ),
                "price": st.column_config.NumberColumn("Price (c)", format="%.2f"),
                "last_edge": st.column_config.NumberColumn(
                    "Edge now", format="percent", help="Worst-price loop edge, latest hour."
                ),
                "overlap_chaos": st.column_config.NumberColumn(
                    "Volume (c)",
                    format="compact",
                    help=f"Chaos value traded in both markets over the last {lookback}h.",
                ),
                "paying_share": st.column_config.ProgressColumn(
                    f"Paid ({lookback}h)", format="percent", min_value=0, max_value=1
                ),
                "hours_since": st.column_config.NumberColumn(
                    "Hours ago", format="%d", help="0 = traded in the latest hour."
                ),
                "last_gap": st.column_config.NumberColumn(
                    "Gap now",
                    format="percent",
                    help="Price via Divines vs Chaos price, at average prices.",
                ),
            },
            alt="Best Chaos-Divine loops right now",
        )

    st.subheader("Best card flips right now", icon=":material/style:")
    st.caption(
        "Buy a full set, turn it in, sell the reward: margin in the card's latest hour, then "
        f"how often it paid over the last {lookback}h."
    )
    if cards.is_empty():
        st.caption("No card flip paid in the latest hours.")
    else:
        fmt = price_format(unit)
        st.dataframe(
            cards.select(
                "name",
                "score",
                "set_cost",
                "reward_value",
                "last_margin",
                "last_margin_pct",
                "sets_traded",
                "profitable_share",
                "hours_since",
                "reward",
            ),
            hide_index=True,
            height=380,
            placeholder="–",
            column_config={
                "name": st.column_config.TextColumn("Card", pinned=True, width="medium"),
                "score": st.column_config.ProgressColumn(
                    "Score", format="%.2f", min_value=0, max_value=1
                ),
                "set_cost": st.column_config.NumberColumn(f"Set cost ({sfx})", format=fmt),
                "reward_value": st.column_config.NumberColumn(f"Reward ({sfx})", format=fmt),
                "last_margin": st.column_config.NumberColumn(f"Margin ({sfx})", format=fmt),
                "last_margin_pct": st.column_config.NumberColumn("Margin %", format="percent"),
                "sets_traded": st.column_config.NumberColumn(
                    f"Sets traded ({lookback}h)", format="compact"
                ),
                "profitable_share": st.column_config.ProgressColumn(
                    f"Paid ({lookback}h)", format="percent", min_value=0, max_value=1
                ),
                "hours_since": st.column_config.NumberColumn("Hours ago", format="%d"),
                "reward": st.column_config.TextColumn("Gives"),
            },
            alt="Best card flips right now",
        )


live_view()
