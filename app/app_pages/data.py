import streamlit as st
from common import calendar, database_ready, loads

st.title("Data", icon=":material/database:")

if not database_ready():
    st.info("Run `eb exchange sync -l Mirage` first.", title="No data yet")
    st.stop()

with st.container(border=True):
    st.subheader("What's loaded", icon=":material/inventory_2:")
    st.dataframe(
        loads(),
        hide_index=True,
        column_config={
            "league": "League",
            "source": st.column_config.TextColumn(
                "Source",
                help="ggg-exchange-hourly: hourly exchange trades. "
                "poe.ninja-dump: daily prices from poe.ninja.",
            ),
            "item_count": st.column_config.NumberColumn("Items", format="localized"),
            "row_count": st.column_config.NumberColumn("Price rows", format="localized"),
            "loaded_at": st.column_config.DatetimeColumn("Loaded (UTC)", format="YYYY-MM-DD HH:mm"),
        },
        alt="Loaded data sources per league",
    )

with st.container(border=True):
    st.subheader("Challenge leagues", icon=":material/calendar_month:")
    st.caption(
        "Only the main 3–4 month challenge leagues are tracked. Event and Ruthless leagues "
        "have far fewer players and markets unlike a normal league, so they're left out."
    )
    st.dataframe(
        calendar().drop("kind"),
        hide_index=True,
        column_config={
            "name": "League",
            "start_date": st.column_config.DateColumn("Start"),
            "end_date": st.column_config.DateColumn("End"),
            "length_days": st.column_config.NumberColumn("Days"),
            "price_rows": st.column_config.NumberColumn("Price rows", format="localized"),
        },
        alt="Challenge league calendar",
    )

with st.container(border=True):
    st.subheader("Refreshing the data", icon=":material/sync:")
    st.markdown(
        "Run these from the repo root. Each one can be stopped with Ctrl-C and re-run to "
        "resume; finished work is never fetched or rewritten again."
    )
    st.code(
        "scripts/ingest.sh                     # everything, unattended (logs in data/logs/)\n"
        "eb exchange sync -l Mirage            # one league's hourly history\n"
        "eb exchange status                    # what's on disk and loaded",
        language="bash",
    )
