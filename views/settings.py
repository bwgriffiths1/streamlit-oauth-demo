import streamlit as st

st.title("Settings")

# --- User profile info ---
st.subheader("Your Profile")

col1, col2 = st.columns(2)
with col1:
    st.markdown("**Name**")
    st.info(st.user.get("name", "Not available"))

with col2:
    st.markdown("**Email**")
    st.info(st.user.get("email", "Not available"))

st.divider()

# --- App preferences (placeholder) ---
st.subheader("Preferences")
st.toggle("Dark mode", value=False, disabled=True, help="Coming soon")
st.selectbox("Default page", ["Dashboard", "Data Explorer"], disabled=True, help="Coming soon")

st.divider()

st.caption("Preferences are placeholders for demonstration purposes.")
