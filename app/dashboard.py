"""Local Streamlit demo. Run with: streamlit run app/dashboard.py"""

import streamlit as st

from exiledbroker.config import get_settings
from exiledbroker.services import overview, prices
from exiledbroker.storage import db

CREDIT = (
    "Economy data from [poe.ninja](https://poe.ninja) "
    "([CC BY-SA](https://creativecommons.org/licenses/by-sa/3.0/)). "
    "Not affiliated with or endorsed by Grinding Gear Games or poe.ninja."
)

settings = get_settings()
st.set_page_config(page_title="ExiledBroker", layout="wide")
st.title("ExiledBroker")
st.caption(f"Game: {settings.default_game} · Database: {settings.db_path}")
st.sidebar.caption(CREDIT)

if not settings.db_path.exists():
    st.warning("No database yet. Run `eb dumps sync` (or `eb init-db`) first.")
    st.stop()

with db.session(read_only=True) as con:
    counts = overview.table_counts(con)
    calendar = overview.league_calendar(con)
    priced_leagues = overview.leagues_with_prices(con)

st.subheader("Loaded data")
cols = st.columns(len(counts))
for col, (table, n) in zip(cols, counts.items(), strict=True):
    col.metric(table, f"{n:,}")

st.subheader("League calendar")
st.dataframe(calendar, hide_index=True, width="stretch")

st.subheader("League-start price curve")
if not priced_leagues:
    st.info("No price data loaded yet. Run `eb dumps sync`.")
    st.stop()

left, mid, right = st.columns([1, 2, 1])
league = left.selectbox("League", priced_leagues)
with db.session(read_only=True) as con:
    names = prices.item_names(con, league)
default = names.index("Mageblood") if "Mageblood" in names else 0
item = mid.selectbox("Item", names, index=default)
max_day = right.slider("Days since league start", 7, 60, 21)

with db.session(read_only=True) as con:
    curve = prices.item_curve(con, league, item, max_day)

if curve.is_empty():
    st.info("No rows for that item in this window.")
else:
    wide = curve.pivot(on="series", index="day_offset", values="chaos_value").sort("day_offset")
    st.line_chart(wide, x="day_offset", y_label="chaos", x_label="day")
    st.caption("Daily values. Day 0 and 'Low' confidence points are thin and noisy.")
