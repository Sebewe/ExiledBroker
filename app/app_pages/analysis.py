import altair as alt
import polars as pl
import streamlit as st
from common import (
    UNIT_SUFFIX,
    analysis_leagues,
    cross_market_item,
    cross_market_per_league,
    database_ready,
    group_curves,
    launch_curves,
    tracked_items,
    turn_ins_across,
    unique_moves,
)

from exiledbroker.analysis import launch_patterns as lp
from exiledbroker.services import cross_market as xm

st.title("Analysis", icon=":material/insights:")
st.caption(
    "Patterns across recent challenge leagues. The economy shifts league to league, so "
    "recent leagues count more (set the half-life below), and the currency exchange "
    "(Settlers onward) is treated as a break from earlier leagues."
)

if not database_ready():
    st.info("Run `scripts/ingest.sh all` to load the history.", title="No data yet")
    st.stop()

available = analysis_leagues()
TOOLS = ["Unique moves", "Launch curves", "Group timing", "Card turn-ins", "Cross-market"]
with st.container(horizontal=True, vertical_alignment="bottom"):
    tool = st.segmented_control("Tool", TOOLS, default=TOOLS[0], required=True)
    half_life = st.number_input(
        "Recency half-life (leagues)",
        min_value=0.5,
        max_value=10.0,
        value=2.0,
        step=0.5,
        width=220,
        help="A league this many leagues older than the newest counts half as much.",
    )

hourly_tool = tool != "Unique moves"
pool = available["hourly"] if hourly_tool else available["daily"]
if not pool:
    source = "hourly exchange" if hourly_tool else "daily"
    st.info(
        f"No challenge league has {source} data loaded yet. Run `scripts/ingest.sh all`; "
        "these tools fill in as leagues load.",
        title="Waiting for data",
        icon=":material/hourglass_top:",
    )
    st.stop()

default = pool if hourly_tool else pool[:6]
leagues = st.pills(
    "Leagues (newest first)",
    pool,
    selection_mode="multi",
    default=default,
    key=f"leagues-{'hourly' if hourly_tool else 'daily'}",
)
if not leagues:
    st.caption("Pick at least one league.")
    st.stop()
leagues = [name for name in pool if name in leagues]  # keep newest-first order
weights = lp.recency_weights(leagues, half_life)
st.caption("Weights: " + " · ".join(f"{name} {w:.2f}" for name, w in weights.items()))


def weighted(df: pl.DataFrame, value: str, by: list[str]) -> pl.DataFrame:
    """Recency-weighted mean of `value` across leagues."""
    w = df.with_columns(weight=pl.col("league").replace_strict(weights, default=0.0))
    return w.group_by(by).agg(
        ((pl.col(value) * pl.col("weight")).sum() / pl.col("weight").sum()).alias(value)
    )


# --- Unique moves ------------------------------------------------------------------
if tool == "Unique moves":
    st.subheader("How uniques move over launch week", icon=":material/trending_down:")
    with st.container(horizontal=True, vertical_alignment="bottom"):
        base_day = st.number_input("From day", 1, 13, 2, width=140)
        end_day = st.number_input("To day", 2, 60, 14, width=140)
        high_only = st.toggle("High-confidence prices only", value=True)
    if end_day <= base_day:
        st.caption("The end day must be after the start day.")
        st.stop()
    moves = unique_moves(tuple(leagues), base_day, end_day, high_only)
    if moves.is_empty():
        st.info("No uniques have prices on both days in these leagues yet.", title="No data")
        st.stop()
    per = lp.by_tier(moves)
    pooled = weighted(per, "median_ratio", ["tier"]).join(
        weighted(per, "share_up", ["tier"]), on="tier"
    )
    order = [label for _, label in lp.TIERS]
    cols = st.columns(len(order))
    for col, tier in zip(cols, order, strict=True):
        row = pooled.filter(pl.col("tier") == tier)
        if row.is_empty():
            col.metric(tier, "–", border=True, height="stretch")
            continue
        r = row.row(0, named=True)
        col.metric(
            tier,
            f"{r['median_ratio']:.2f}×",
            delta=f"{r['median_ratio'] - 1:+.0%}",
            delta_description=f"{r['share_up']:.0%} of items rose",
            border=True,
            height="stretch",
            help=f"Recency-weighted median of each unique's day-{end_day} price ÷ "
            f"day-{base_day} price, in divines.",
        )
    left, right = st.columns([3, 2])
    with left, st.container(border=True, height="stretch"):
        st.markdown(f"**Median day {end_day} ÷ day {base_day} price (divines), per league**")
        chart = (
            alt.Chart(per)
            .mark_bar()
            .encode(
                alt.X("league:N", sort=leagues, title=None),
                alt.Y("median_ratio:Q", title="Median ratio (1 = unchanged)"),
                alt.Color("tier:N", sort=order, title=None, legend=alt.Legend(orient="bottom")),
                alt.XOffset("tier:N", sort=order),
                tooltip=[
                    "league",
                    "tier",
                    "items",
                    alt.Tooltip("median_ratio:Q", format=".2f"),
                    alt.Tooltip("share_up:Q", format=".0%"),
                ],
            )
            .properties(height=360)
        )
        rule = alt.Chart(pl.DataFrame({"y": [1.0]})).mark_rule(strokeDash=[4, 4]).encode(y="y:Q")
        st.altair_chart(chart + rule, alt="Unique price ratio by tier and league")
        st.caption(
            "Below the dashed line = cheaper at the end. 0.25 = worth a quarter of the start price."
        )
    with right, st.container(border=True, height="stretch"):
        st.markdown("**Per league**")
        st.dataframe(
            per.drop("start_at", "leagues"),
            hide_index=True,
            height=360,
            column_config={
                "tier": "Tier (day-start price)",
                "league": "League",
                "items": st.column_config.NumberColumn("Uniques"),
                "median_ratio": st.column_config.NumberColumn("Median ratio", format="%.2f×"),
                "share_up": st.column_config.NumberColumn("Rose", format="percent"),
            },
            alt="Unique moves per league and tier",
        )
    with st.container(border=True):
        st.markdown("**Individual uniques**")
        st.caption("Each unique's start and end price (divines), most-dropped first.")
        st.dataframe(
            moves.sort("ratio").select("league", "name", "tier", "base", "end", "ratio"),
            hide_index=True,
            height=320,
            column_config={
                "base": st.column_config.NumberColumn(f"Day {base_day} (div)", format="%.2f"),
                "end": st.column_config.NumberColumn(f"Day {end_day} (div)", format="%.2f"),
                "ratio": st.column_config.NumberColumn("Ratio", format="%.2f×"),
            },
            alt="Individual unique price moves",
        )

# --- Launch curves -------------------------------------------------------------------
elif tool == "Launch curves":
    st.subheader("One item's launch curve, league by league", icon=":material/show_chart:")
    items = tracked_items()
    if items.is_empty():
        st.info("No price mappings yet. Run `eb exchange sync`.", title="No items")
        st.stop()
    labels = {
        f"{r['name']} · {r['group_label']}": r["item_id"] for r in items.iter_rows(named=True)
    }
    names = list(labels)
    with st.container(horizontal=True, vertical_alignment="bottom"):
        pick = st.selectbox(
            "Item",
            names,
            index=names.index("Divine Orb · Currency") if "Divine Orb · Currency" in names else 0,
            width=360,
        )
        unit = st.segmented_control(
            "Price in",
            ["chaos", "divine"],
            default="chaos",
            required=True,
            format_func=str.capitalize,
        )
        bucket = st.segmented_control(
            "Resolution",
            [1, 3, 6, 12, 24],
            default=6,
            required=True,
            format_func=lambda h: f"{h}h",
        )
        relative = st.toggle("Relative to day 1", value=True)
    curves = launch_curves((labels[pick],), tuple(leagues), unit, bucket)
    if curves.is_empty():
        st.info(f"{pick.split(' · ')[0]} hasn't traded in these leagues yet.", title="No data")
        st.stop()
    thin = curves.filter(pl.col("baseline_hours") < 6)["league"].unique().to_list()
    if relative and thin:
        st.warning(
            f"Thin day-1 market in {', '.join(thin)}: the day-1 price rests on fewer than six "
            "traded hours, so relative values there are unreliable.",
            icon=":material/warning:",
        )
    y_col = "relative" if relative else "value"
    y_title = "Price ÷ day-1 price" if relative else f"Price ({UNIT_SUFFIX[unit]})"
    avg = lp.weighted_curve(curves, weights)
    turns = lp.turning_points(avg)
    c1, c2, c3 = st.columns(3)
    c1.metric("Leagues", f"{curves['league'].n_unique()}", border=True, height="stretch")
    c2.metric(
        "Weighted low",
        f"day {turns['low_day']:.2f}" if turns["low_day"] is not None else "–",
        delta=f"{turns['low']:.2f}× day 1" if turns["low"] is not None else None,
        delta_color="off",
        border=True,
        height="stretch",
    )
    c3.metric(
        "Weighted peak",
        f"day {turns['peak_day']:.2f}" if turns["peak_day"] is not None else "–",
        delta=f"{turns['peak']:.2f}× day 1" if turns["peak"] is not None else None,
        delta_color="off",
        border=True,
        height="stretch",
    )
    with st.container(border=True):
        x = alt.X("bucket_day:Q", title="Days since launch").scale(domain=[0, 14])
        y = alt.Y(f"{y_col}:Q", title=y_title).scale(zero=False)
        lines = (
            alt.Chart(curves.drop_nulls(y_col))
            .mark_line(strokeWidth=1.2)
            .encode(
                x,
                y,
                alt.Color("league:N", sort=leagues, title=None, legend=alt.Legend(orient="bottom")),
                tooltip=[
                    "league",
                    alt.Tooltip("bucket_day:Q", title="Day", format=".2f"),
                    alt.Tooltip(f"{y_col}:Q", title=y_title, format=",.4~f"),
                    alt.Tooltip("volume:Q", title="Units traded", format=",.0f"),
                ],
            )
        )
        chart = lines
        if relative and not avg.is_empty():
            chart = lines + alt.Chart(avg).mark_line(strokeWidth=3, color="#F1F5F9").encode(
                x,
                alt.Y("relative:Q").scale(zero=False),
                tooltip=[
                    alt.Tooltip("bucket_day:Q", title="Day", format=".2f"),
                    alt.Tooltip("relative:Q", title="Weighted", format=".2f"),
                ],
            )
        st.altair_chart(chart.properties(height=420), alt=f"Launch curves for {pick}")
        if relative:
            st.caption(
                "Thick line: recency-weighted average across the selected leagues. 2 = twice the day-1 price."
            )

# --- Group timing --------------------------------------------------------------------
elif tool == "Group timing":
    st.subheader("When each group bottoms out and peaks", icon=":material/schedule:")
    groups = {
        "Currency": "currency",
        "High-tier essences": "essence",
        "Scarabs": "scarab",
        "Divination cards": "divination",
    }
    with st.container(horizontal=True, vertical_alignment="bottom"):
        group = st.segmented_control("Group", list(groups), default="Currency", required=True)
        unit = st.segmented_control(
            "Price in",
            ["chaos", "divine"],
            default="divine",
            required=True,
            format_func=str.capitalize,
            key="group-unit",
            help="In divines, Divine's own rise doesn't lift everything else.",
        )
        bucket = st.segmented_control(
            "Resolution",
            [3, 6, 12, 24],
            default=6,
            required=True,
            format_func=lambda h: f"{h}h",
            key="group-bucket",
        )
    g = group_curves(groups[group], tuple(leagues), unit, bucket)
    if g.is_empty():
        st.info(
            f"No {group.lower()} have enough day-1 trading in these leagues yet.", title="No data"
        )
        st.stop()
    avg = lp.weighted_curve(g, weights)
    rows = []
    for name in leagues:
        t = lp.turning_points(g.filter(pl.col("league") == name))
        items = g.filter(pl.col("league") == name)["items"].max()
        rows.append({"league": name, "items": items, **t})
    rows.append({"league": "Weighted", "items": None, **lp.turning_points(avg)})
    left, right = st.columns([3, 2])
    with left, st.container(border=True, height="stretch"):
        st.markdown(f"**Median {group.lower()} price ÷ its day-1 price**")
        x = alt.X("bucket_day:Q", title="Days since launch").scale(domain=[0, 14])
        y = alt.Y("relative:Q", title="Median price ÷ day-1 price").scale(zero=False)
        chart = alt.Chart(g).mark_line(strokeWidth=1.2).encode(
            x,
            y,
            alt.Color("league:N", sort=leagues, title=None, legend=alt.Legend(orient="bottom")),
            tooltip=[
                "league",
                alt.Tooltip("bucket_day:Q", title="Day", format=".2f"),
                alt.Tooltip("relative:Q", format=".2f"),
                "items",
            ],
        ) + alt.Chart(avg).mark_line(strokeWidth=3, color="#F1F5F9").encode(
            x, alt.Y("relative:Q").scale(zero=False)
        )
        st.altair_chart(chart.properties(height=400), alt=f"{group} launch timing")
        st.caption(
            "Each item counts once (median), so a few expensive items can't dominate. "
            "Thick line: recency-weighted. 1 = the day-1 price."
        )
    with right, st.container(border=True, height="stretch"):
        st.markdown("**Low and peak, per league**")
        st.dataframe(
            pl.DataFrame(rows),
            hide_index=True,
            column_config={
                "league": "League",
                "items": st.column_config.NumberColumn("Items"),
                "low_day": st.column_config.NumberColumn("Low (day)", format="%.2f"),
                "low": st.column_config.NumberColumn("Low ×", format="%.2f"),
                "peak_day": st.column_config.NumberColumn("Peak (day)", format="%.2f"),
                "peak": st.column_config.NumberColumn("Peak ×", format="%.2f"),
            },
            alt="Group lows and peaks per league",
        )

# --- Card turn-ins across leagues ---------------------------------------------------
elif tool == "Card turn-ins":
    st.subheader("Which card turn-ins hold up league after league", icon=":material/style:")
    t = turn_ins_across(tuple(leagues), half_life)
    if t.is_empty():
        st.info("No card turn-ins are priced in these leagues yet.", title="No data")
        st.stop()
    min_leagues = st.slider(
        "Seen in at least this many leagues", 1, len(leagues), min(2, len(leagues)), width=320
    )
    t = t.filter(pl.col("leagues") >= min_leagues).with_columns(
        reward=pl.format("{}× {}", pl.col("reward_quantity"), pl.col("reward_name"))
    )
    st.caption(
        "Weighted across leagues by recency. Worst league: the lowest share of profitable "
        "hours in any one league, so a card that only worked once stands out."
    )
    st.dataframe(
        t.select(
            "name",
            "filter_tier",
            "stack_size",
            "reward",
            "leagues",
            "weighted_margin_pct",
            "weighted_profitable_share",
            "worst_league_share",
        ),
        hide_index=True,
        height=520,
        column_config={
            "name": st.column_config.TextColumn("Card", pinned=True),
            "filter_tier": "Tier",
            "stack_size": st.column_config.NumberColumn("Set"),
            "reward": "Reward",
            "leagues": st.column_config.NumberColumn("Leagues"),
            "weighted_margin_pct": st.column_config.NumberColumn("Margin %", format="percent"),
            "weighted_profitable_share": st.column_config.ProgressColumn(
                "Profitable hours", format="percent", min_value=0, max_value=1
            ),
            "worst_league_share": st.column_config.ProgressColumn(
                "Worst league", format="percent", min_value=0, max_value=1
            ),
        },
        alt="Card turn-ins across leagues",
    )


# --- Cross-market (Chaos vs Divine) ------------------------------------------------
else:
    st.subheader("Same item, two markets: Chaos vs Divine", icon=":material/swap_horiz:")
    st.caption(
        "Many items trade against both Chaos and Divines. Each hour, a loop through both "
        "markets is priced at the worst prices seen that hour on every leg (highest buy, "
        "lowest sell, worst Divine rate). These are hourly summaries, not an order book: "
        "a paying hour means trades happened at those prices, not that one player could "
        "have caught both sides. Treat the list as candidates to check live."
    )
    with st.container(border=True):
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
                help="Filters out dust-priced bulk items (e.g. Rogue's Markers at "
                "~0.001c), where gaps say more about how they trade than about profit.",
            )
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
                help="Share of paying hours in the weakest selected league (0 if the "
                "item is missing from one): rewards items that paid every league.",
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

    per = cross_market_per_league(tuple(leagues), direction, buffer_pct / 100, int(min_hours))
    if per.is_empty():
        st.info(
            "No item traded in both markets often enough in these leagues yet.",
            title="No data",
            icon=":material/hourglass_top:",
        )
        st.stop()
    summary = xm.across_leagues(per, leagues, weights)  # recency weights, set above
    summary = summary.filter(pl.col("chaos_price") >= min_price)
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
    steady = (
        scored.filter(pl.col("worst_league_share") >= 0.25).height if not scored.is_empty() else 0
    )
    c3.metric("Paid ≥25% of hours in every league", f"{steady:,}", border=True, height="stretch")
    top = (
        scored.row(0, named=True)
        if not scored.is_empty() and scored["score"][0] is not None
        else None
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

    left, right = st.columns([3, 2])
    with left, st.container(border=True, height="stretch"):
        st.markdown("**Ranked loops**")
        st.caption("Select a row to chart it.")
        event = st.dataframe(
            scored.select(
                "name",
                "score",
                "leagues",
                "weighted_share",
                "worst_league_share",
                "weighted_edge",
                "median_gap",
                "chaos_price",
                "overlap_chaos",
                "capacity_chaos",
            ),
            hide_index=True,
            height=480,
            on_select="rerun",
            selection_mode="single-row",
            placeholder="–",
            key=f"cross-{direction}",
            column_config={
                "name": st.column_config.TextColumn("Item", pinned=True),
                "score": st.column_config.ProgressColumn(
                    "Score", format="%.2f", min_value=0, max_value=1
                ),
                "leagues": st.column_config.NumberColumn("Leagues"),
                "weighted_share": st.column_config.ProgressColumn(
                    "Paying hours", format="percent", min_value=0, max_value=1
                ),
                "worst_league_share": st.column_config.ProgressColumn(
                    "Worst league", format="percent", min_value=0, max_value=1
                ),
                "weighted_edge": st.column_config.NumberColumn(
                    "Edge when paying",
                    format="percent",
                    help="Typical worst-price edge in the hours the loop paid.",
                ),
                "median_gap": st.column_config.NumberColumn(
                    "Typical gap",
                    format="percent",
                    help="Median of (price via Divines ÷ Chaos price − 1), at average prices.",
                ),
                "chaos_price": st.column_config.NumberColumn("Price (c)", format="%.2f"),
                "overlap_chaos": st.column_config.NumberColumn(
                    "Volume (c)", format="compact", help="Chaos value traded in both markets."
                ),
                "capacity_chaos": st.column_config.NumberColumn(
                    "Upper-bound profit (c)",
                    format="compact",
                    help="Edge × volume in paying hours, summed. An upper bound: assumes "
                    "you could have taken all of it.",
                ),
            },
            alt="Cross-market loops ranked by score",
        )
    pick = (scored[event.selection.rows[0]] if event.selection.rows else scored.head(1)).row(
        0, named=True
    )
    item_hours = cross_market_item(tuple(leagues), pick["item_id"], direction)
    with right, st.container(border=True, height="stretch"):
        st.markdown(f"**{pick['name']}**")
        present = [name for name in leagues if name in item_hours["league"].unique().to_list()]
        detail_league = st.segmented_control(
            "League", present, default=present[0], required=True, key="cross-league"
        )
        one = item_hours.filter(pl.col("league") == detail_league)
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
        x = alt.X("day_offset:Q", title="Days since launch").scale(domain=[0, 14])
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
            .properties(height=220),
            alt=f"{pick['name']} price in each market",
        )
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
        st.altair_chart(
            (bars + rule).properties(height=200), alt=f"{pick['name']} loop edge per hour"
        )
        st.caption("Green hours beat the fee buffer (dashed line).")
