import altair as alt
import polars as pl
import streamlit as st
from common import (
    UNIT_SUFFIX,
    analysis_leagues,
    database_ready,
    group_curves,
    launch_curves,
    tracked_items,
    turn_ins_across,
    unique_moves,
)

from exiledbroker.analysis import launch_patterns as lp

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
TOOLS = ["Unique moves", "Launch curves", "Group timing", "Card turn-ins"]
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
else:
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
