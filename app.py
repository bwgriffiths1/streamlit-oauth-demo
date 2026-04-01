import streamlit as st

st.set_page_config(
    page_title="Demo App",
    page_icon=":material/lock:",
    layout="wide",
)

# --- Landing page (unauthenticated) ---
if not st.user.is_logged_in:
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.title("Welcome to the Demo App")
        st.markdown(
            "This is a multi-page demo application secured with Google authentication. "
            "Log in with your Google account to access the dashboard, data explorer, "
            "and settings."
        )
        st.divider()
        if st.button("Log in with Google", type="primary", width="stretch"):
            st.login()
    st.stop()

# --- Authenticated: sidebar + navigation ---
user_name = st.user.get("name", "User")
user_email = st.user.get("email", "")

with st.sidebar:
    st.markdown(f"**{user_name}**")
    if user_email:
        st.caption(user_email)
    st.divider()
    if st.button("Log out", width="stretch"):
        st.logout()

pg = st.navigation(
    [
        st.Page("views/dashboard.py", title="Dashboard", icon=":material/dashboard:"),
        st.Page("views/data_explorer.py", title="Data Explorer", icon=":material/search:"),
        st.Page("views/settings.py", title="Settings", icon=":material/settings:"),
    ]
)
pg.run()
