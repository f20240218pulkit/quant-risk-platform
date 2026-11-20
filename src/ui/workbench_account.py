"""Tie persistent records to the verified Streamlit identity."""
import os
from tempfile import TemporaryDirectory
from uuid import uuid4

import streamlit as st

from src.workbench.storage import Store, identity_key


def configure_identity():
    persistent = os.getenv("WORKBENCH_DB")
    if not persistent:
        return
    with st.sidebar:
        st.divider()
        if not st.user.get("is_logged_in", False):
            try:
                configured = "auth" in st.secrets
            except FileNotFoundError:
                configured = False
            if configured:
                st.button("Sign in for saved reviews", on_click=st.login)
            else:
                st.caption("Private workspace sign-in has not been configured.")
        else:
            st.button("Sign out", on_click=st.logout)


def workspace():
    path = os.getenv("WORKBENCH_DB")
    if path:
        if not st.user.get("is_logged_in", False):
            raise ValueError("Sign in to use the private workspace.")
        try:
            owner = identity_key(st.user.get("iss"), st.user.get("sub"), st.user.get("exp"))
        except ValueError as exc:
            raise ValueError(str(exc)) from exc
        return Store(path), owner, True
    if "workbench_storage" not in st.session_state:
        st.session_state["workbench_storage"] = TemporaryDirectory(prefix="workbench-")
        st.session_state["workbench_owner"] = uuid4().hex
    folder = st.session_state["workbench_storage"].name
    return Store(f"{folder}/review.sqlite3"), st.session_state["workbench_owner"], False
