"""Portfolio Workbench Streamlit navigation."""
from pathlib import Path

import streamlit as st

from src.ui.workbench_account import configure_identity
from src.ui.workbench_pages import broker_page, currency_page, research_page, saved_page

st.set_page_config(page_title="Portfolio Workbench", page_icon="◈", layout="wide")
configure_identity()
review_path = Path(__file__).parent / "src" / "ui" / "workbench.py"
st.navigation([
    st.Page(str(review_path), title="Portfolio review", icon=":material/analytics:", default=True),
    st.Page(research_page, title="Strategy research", icon=":material/science:", url_path="research"),
    st.Page(saved_page, title="Saved reviews & alerts", icon=":material/notifications:", url_path="workspace"),
    st.Page(currency_page, title="AUD and USD analysis", icon=":material/currency_exchange:", url_path="currency"),
    st.Page(broker_page, title="Broker import", icon=":material/account_balance:", url_path="broker"),
]).run()
