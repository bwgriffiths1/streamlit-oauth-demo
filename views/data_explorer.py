import streamlit as st
import pandas as pd

st.title("Data Explorer")

DATASETS = {
    "Sales": pd.DataFrame(
        {
            "Date": ["2025-01-15", "2025-02-10", "2025-03-05", "2025-03-22", "2025-04-01"],
            "Product": ["Widget A", "Widget B", "Widget A", "Widget C", "Widget B"],
            "Quantity": [150, 230, 180, 95, 310],
            "Unit Price ($)": [12.50, 8.75, 12.50, 45.00, 8.75],
            "Total ($)": [1875.00, 2012.50, 2250.00, 4275.00, 2712.50],
        }
    ),
    "Inventory": pd.DataFrame(
        {
            "SKU": ["SKU-001", "SKU-002", "SKU-003", "SKU-004", "SKU-005"],
            "Product": ["Widget A", "Widget B", "Widget C", "Gadget X", "Gadget Y"],
            "In Stock": [420, 1150, 67, 890, 230],
            "Reorder Point": [100, 200, 50, 150, 100],
            "Warehouse": ["East", "West", "East", "Central", "West"],
        }
    ),
    "Customers": pd.DataFrame(
        {
            "Customer ID": ["C-1001", "C-1002", "C-1003", "C-1004", "C-1005"],
            "Name": ["Acme Corp", "Globex Inc", "Initech", "Umbrella Co", "Stark Industries"],
            "Region": ["Northeast", "West", "Midwest", "South", "West"],
            "Lifetime Value ($)": [24500, 18200, 31000, 12800, 56700],
            "Status": ["Active", "Active", "Churned", "Active", "Active"],
        }
    ),
}

dataset_name = st.selectbox("Select a dataset", list(DATASETS.keys()))
df = DATASETS[dataset_name]

st.subheader(f"{dataset_name} ({len(df)} rows)")
st.dataframe(df, use_container_width=True)

# Download as CSV
csv = df.to_csv(index=False)
st.download_button(
    label="Download as CSV",
    data=csv,
    file_name=f"{dataset_name.lower()}.csv",
    mime="text/csv",
)
