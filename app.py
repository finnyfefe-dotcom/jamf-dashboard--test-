import streamlit as st
import pandas as pd
import datetime
import matplotlib.pyplot as plt

# --- Optional: Set page config for wider layout ---
st.set_page_config(layout="wide")

# --- Inject custom CSS to reduce padding and stretch content ---
st.markdown("""
    <style>
        .block-container {
            padding-top: 3rem;
            padding-bottom: 1rem;
            padding-left: 2rem;
            padding-right: 2rem;
            max-width: 100%;
        }
    </style>
    """, unsafe_allow_html=True)


# --- File Upload ---
# Allow uploading one or more CSV files and concatenate them
with st.expander("📦 Upload CSVs"):
    uploaded_files = st.file_uploader("Upload one or more Jamf inventory CSVs", type="csv", accept_multiple_files=True)

# Read and concatenate uploaded files into a single DataFrame
df = None
if uploaded_files:
    dfs = []
    for f in uploaded_files:
        try:
            d = pd.read_csv(f)
            dfs.append(d)
        except Exception as e:
            st.error(f"Failed to read {getattr(f, 'name', 'file')}: {e}")
    if dfs:
        df = pd.concat(dfs, ignore_index=True)

    # --- Data Enrichment ---
    if "Computer Name" in df.columns:
        df["Department"] = df["Computer Name"].str.extract(r"^(PRO|SEM|STU|DCE|SOE)")
    if "Last Inventory Update" in df.columns:
        df["Last Inventory Update"] = pd.to_datetime(df["Last Inventory Update"], errors="coerce")
        df["Days Since Update"] = (datetime.datetime.now() - df["Last Inventory Update"]).dt.days
        df["Check-In Status"] = df["Days Since Update"].apply(
            lambda x: "Checked in (<30 days)" if x < 30 else "Not checked in (30+ days)"
        )

    # --- Warranty Prep ---
    if "Warranty Expiration" in df.columns:
        df["Warranty Expiration"] = pd.to_datetime(df["Warranty Expiration"], errors="coerce")
        df["Days Until Expiration"] = (df["Warranty Expiration"] - pd.Timestamp.now()).dt.days
        df["Warranty Status"] = df["Days Until Expiration"].apply(
            lambda x: "Expired" if pd.notna(x) and x < 0
            else ("Expiring Soon (<90 days)" if pd.notna(x) and x <= 90 else "Valid")
        )

    # --- Page Navigation ---
    page = st.sidebar.radio("Navigate to:", ["Inventory", "Warranty"])

    # --- Inventory Page ---
    if page == "Inventory":
        st.title("Inventory Dashboard")

        # Layout: Filters | Chart | Results
        col_filters, col_chart, col_results = st.columns([2, 3, 3])

        # Filters
        with col_filters:
            st.write("### Filters")
            search_term = st.text_input("Search by Name, Serial, or User")

            departments = df["Department"].dropna().unique() if "Department" in df.columns else []
            selected_dept = st.selectbox(
                "Filter by Department",
                options=(["All"] + sorted(departments.tolist())) if len(departments) > 0 else ["All"],
                key="inv_dept"
            )

            managed = df["Managed"].dropna().unique() if "Managed" in df.columns else []
            managed_options = ["All"] + sorted(managed.tolist()) + ["Unmanaged"]
            selected_managed = st.selectbox("Filter by Managed Status", options=managed_options, key="inv_managed")

            selected_os = st.selectbox(
                "Filter by Operating System",
                options=(["All"] + sorted(df["Operating System"].dropna().unique().tolist())) if "Operating System" in df.columns else ["All"],
                key="inv_os"
            )

        # Apply filters
        results = df.copy()
        if selected_dept != "All":
            results = results[results["Department"] == selected_dept]
        if selected_managed != "All" and "Managed" in results.columns:
            if selected_managed == "Unmanaged":
                results = results[results["Managed"].isna() | (results["Managed"] == "Unmanaged")]
            else:
                results = results[results["Managed"] == selected_managed]
        if search_term:
            results = results[results.apply(lambda row: search_term.lower() in str(row).lower(), axis=1)]
        if selected_os != "All" and "Operating System" in results.columns:
            results = results[results["Operating System"] == selected_os]

        # Chart
        checkin_counts = results["Check-In Status"].value_counts() if "Check-In Status" in results.columns else pd.Series(dtype=int)
        with col_chart:
            st.write("### Inventory Check-In Status")
            if not checkin_counts.empty:
                fig, ax = plt.subplots(figsize=(6, 4))
                ax.bar(checkin_counts.index.astype(str), checkin_counts.values, color=["green", "red"])
                ax.set_ylabel("Number of Devices")
                ax.set_title("Last Inventory Update Status")
                st.pyplot(fig)
            st.write("### Check-In Status Details")
            st.write(f"✅ Checked In: {int(checkin_counts.get('Checked in (<30 days)', 0))}")
            st.write(f"❌ Not Checked In: {int(checkin_counts.get('Not checked in (30+ days)', 0))}")

        # Results + Export
        with col_results:
            st.write("### Filtered Results")

            # Columns to display (only include those present)
            display_cols = [c for c in [
                "Computer Name",
                "Serial Number",
                "Username",
                "Operating System",
                "Last Inventory Update",
                "Managed"
            ] if c in results.columns]

            # Determine stale devices (not checked in >= 30 days)
            if "Days Since Update" in results.columns:
                stale_mask = results["Days Since Update"] >= 30
            elif "Check-In Status" in results.columns:
                stale_mask = results["Check-In Status"] == "Not checked in (30+ days)"
            else:
                stale_mask = pd.Series(False, index=results.index)

            # Row highlighter for Styler: red background for stale rows
            def highlight_stale(row):
                is_stale = False
                try:
                    is_stale = bool(stale_mask.loc[row.name])
                except Exception:
                    is_stale = False
                if is_stale:
                    return ["background-color: #ffd6d6; color: #900;"] * len(row)
                return [""] * len(row)

            if display_cols:
                styled = results[display_cols].style.apply(highlight_stale, axis=1)
                st.dataframe(styled)
            else:
                st.write("No columns available to display.")

            # Export (collapsible)
            with st.expander("📦 Export Results"):
                csv = results.to_csv(index=False).encode("utf-8")
                st.download_button(
                    label="Download filtered results as CSV",
                    data=csv,
                    file_name="jamf_filtered_inventory.csv",
                    mime="text/csv",
                )

    # --- Warranty Page ---
    elif page == "Warranty":
        st.title("Warranty Dashboard")

        # Layout: Filters | Chart | Table
        col_filters, col_chart, col_table = st.columns([2, 3, 3])

        # Filters
        with col_filters:
            st.write("### Warranty Filters")
            dept_options = sorted(df["Department"].dropna().unique().tolist()) if "Department" in df.columns else []
            selected_dept_w = st.selectbox(
                "Filter by Department",
                options=(["All"] + dept_options) if dept_options else ["All"],
                key="warr_dept"
            )

        # Apply filter
        if selected_dept_w != "All" and "Department" in df.columns:
            w_df = df[df["Department"] == selected_dept_w].copy()
        else:
            w_df = df.copy()


        # Chart + Summary
        with col_chart:
            st.subheader("Warranty Status Overview")
            status_counts = w_df["Warranty Status"].value_counts() if "Warranty Status" in w_df.columns else pd.Series(dtype=int)
            if not status_counts.empty:
                color_map = {"Valid": "green", "Expired": "red", "Expiring Soon (<90 days)": "orange"}
                colors = [color_map.get(label, "gray") for label in status_counts.index.astype(str)]
                fig, ax = plt.subplots(figsize=(6, 4))
                ax.bar(status_counts.index.astype(str), status_counts.values, color=colors)
                ax.set_ylabel("Number of Devices")
                ax.set_title("Warranty Status Distribution")
                st.pyplot(fig)
            st.write("### Summary")
            st.write(f"❌ Expired: {int(status_counts.get('Expired', 0))}")
            st.write(f"⚠️ Expiring Soon: {int(status_counts.get('Expiring Soon (<90 days)', 0))}")
            st.write(f"✅ Valid: {int(status_counts.get('Valid', 0))}")

        # Expired Devices Table
        with col_table:
            st.subheader("Expired Devices")
            expired = w_df[w_df["Warranty Status"] == "Expired"].copy() if "Warranty Status" in w_df.columns else pd.DataFrame()
            display_cols = [c for c in ["Computer Name", "Username", "Department", "Warranty Expiration", "Days Until Expiration"] if c in expired.columns]
            if expired.empty or not display_cols:
                st.write("No expired devices found.")
            else:
                expired["Warranty Expiration"] = pd.to_datetime(expired["Warranty Expiration"], errors="coerce")
                st.dataframe(expired[display_cols])

else:
    st.info("Please upload your Jamf inventory CSV to begin.")
