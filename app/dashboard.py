"""Local Streamlit demo. Run with: streamlit run app/dashboard.py"""

import streamlit as st

from exiledbroker.config import get_settings
from exiledbroker.services import overview
from exiledbroker.storage import db

settings = get_settings()
st.set_page_config(page_title="ExiledBroker", layout="wide")
st.title("ExiledBroker")
st.caption(f"Game: {settings.default_game} · Database: {settings.db_path}")

if not settings.db_path.exists():
    st.warning("No database yet. Run `eb init-db` first.")
    st.stop()

with db.session(read_only=True) as con:
    counts = overview.table_counts(con)

st.subheader("Loaded data")
cols = st.columns(len(counts))
for col, (table, n) in zip(cols, counts.items()):
    col.metric(table, f"{n:,}")
