"""ExiledBroker local demo. Run from the repo root: streamlit run app/dashboard.py"""

from pathlib import Path

import streamlit as st

REPO_URL = "https://github.com/Sebewe/ExiledBroker"
STATIC = Path(__file__).parent / "static"

st.set_page_config(
    page_title="ExiledBroker",
    page_icon=":material/candlestick_chart:",
    layout="wide",
)

# Project name at the top of the left bar (and a compact mark when it's collapsed).
st.logo(str(STATIC / "logo.svg"), size="large", link=REPO_URL, icon_image=str(STATIC / "icon.svg"))

page = st.navigation(
    [
        st.Page("app_pages/live.py", title="Live market", icon=":material/bolt:", default=True),
        st.Page("app_pages/market.py", title="Launch market", icon=":material/candlestick_chart:"),
        st.Page("app_pages/cards.py", title="Card turn-ins", icon=":material/style:"),
        st.Page("app_pages/arbitrage.py", title="Arbitrage trading", icon=":material/swap_horiz:"),
        st.Page("app_pages/analysis.py", title="Analysis", icon=":material/insights:"),
        st.Page("app_pages/data.py", title="Data", icon=":material/database:"),
    ]
)

with st.sidebar:
    st.caption(
        "Hourly prices from Grinding Gear Games' public currency exchange history; "
        "daily history from [poe.ninja](https://poe.ninja) "
        "([CC BY-SA](https://creativecommons.org/licenses/by-sa/3.0/)). "
        "Not affiliated with or endorsed by Grinding Gear Games or poe.ninja."
    )
    st.link_button("ExiledBroker on GitHub", REPO_URL, icon=":material/code:", width="stretch")

page.run()
