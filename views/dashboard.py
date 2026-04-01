import streamlit as st
import pandas as pd
import random

st.title("Dashboard")
st.markdown(f"Hello, **{st.user.get('name', 'User')}**! Here's your overview.")

# --- KPI metrics ---
col1, col2, col3, col4 = st.columns(4)
col1.metric("Total Users", "1,284", "+12%")
col2.metric("Active Sessions", "342", "+5%")
col3.metric("Revenue", "$48,230", "+8.2%")
col4.metric("Conversion Rate", "3.6%", "-0.4%")

st.divider()

# --- Charts ---
left, right = st.columns(2)

with left:
    st.subheader("Monthly Trend")
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    trend_data = pd.DataFrame(
        {"Month": months, "Users": [800, 920, 1010, 980, 1100, 1150, 1200, 1180, 1250, 1300, 1280, 1284]},
    ).set_index("Month")
    st.line_chart(trend_data)

with right:
    st.subheader("Revenue by Category")
    categories = ["Electronics", "Clothing", "Food", "Services", "Other"]
    revenue = [random.randint(5000, 15000) for _ in categories]
    cat_data = pd.DataFrame({"Category": categories, "Revenue ($)": revenue}).set_index("Category")
    st.bar_chart(cat_data)
