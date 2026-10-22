"""ExiledBroker local demo. Run from the repo root: streamlit run app/dashboard.py"""

import streamlit as st

st.set_page_config(
    page_title="ExiledBroker",
    page_icon=":material/candlestick_chart:",
    layout="wide",
)

page = st.navigation(
    [
        st.Page(
            "app_pages/market.py",
            title="Launch market",
            icon=":material/candlestick_chart:",
            default=True,
        ),
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

page.run()
