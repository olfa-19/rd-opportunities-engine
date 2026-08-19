import os
import json
import pandas as pd
import streamlit as st

# Configure Streamlit Page
st.set_page_config(page_title="R&D AI Engine - Procurement Feed", layout="wide")
st.title("🤖 Unified R&D Opportunities & Procurement Feed")

PROJECT_ROOT = os.getcwd()

# Define known scraper target folders to scan
SCRAPER_FOLDERS = ["나라장터", "IRIS", "기업마당"]

def extract_attachment_names(data):
    """Normalize file attachments across different JSON formats."""
    attachments = data.get("attachments") or data.get("첨부파일 (Attachments)") or []
    file_list = []
    
    if isinstance(attachments, list):
        for item in attachments:
            if isinstance(item, dict):
                file_list.append(item.get("file_name", "Attachment"))
            elif isinstance(item, str):
                file_list.append(item)
    return file_list

def normalize_metadata(source_name, folder_name, data):
    """Fallback field normalizer to map key variations to a unified schema."""
    
    # 1. ID / Announcement Number
    opp_id = (
        data.get("bid_id") or 
        data.get("공고번호") or 
        folder_name
    )
    
    # 2. Title
    title = (
        data.get("title") or 
        data.get("공고명 (Title)") or 
        data.get("공고명") or 
        folder_name
    )
    
    # 3. Organization / Ministry
    organization = (
        data.get("organization") or 
        data.get("소관부처") or 
        data.get("전문기관명") or 
        data.get("공고기관") or 
        data.get("발주기관") or 
        "N/A"
    )
    
    # 4. Dates
    date = (
        data.get("posting_date") or 
        data.get("공고기간") or 
        data.get("접수기간") or 
        data.get("등록일") or 
        "N/A"
    )
    
    # 5. URL
    url = data.get("url") or data.get("URL") or "https://iris.go.kr"
    
    # 6. Attachments
    file_names = extract_attachment_names(data)
    
    # 7. Description / Content
    desc = data.get("raw_text_description") or data.get("raw_text") or ""
    if not desc:
        # If no explicit raw text, compile key-value pairs into a clean markdown block
        desc_lines = [f"**{k}**: {v}" for k, v in data.items() if k not in ["attachments", "첨부파일 (Attachments)"]]
        desc = "\n\n".join(desc_lines)

    return {
        "Source": source_name,
        "ID": str(opp_id),
        "Title": str(title),
        "Organization": str(organization),
        "Date": str(date),
        "Files": len(file_names),
        "File List": ", ".join(file_names),
        "URL": url,
        "Description": desc
    }

# --- Data Loader ---
records = []

for folder_name in SCRAPER_FOLDERS:
    source_dir = os.path.join(PROJECT_ROOT, folder_name)
    
    if os.path.exists(source_dir):
        # Scan through every subfolder inside each target source directory
        for subfolder in os.listdir(source_dir):
            opp_path = os.path.join(source_dir, subfolder)
            meta_path = os.path.join(opp_path, "metadata.json")
            
            if os.path.isdir(opp_path) and os.path.exists(meta_path):
                try:
                    with open(meta_path, "r", encoding="utf-8") as f:
                        json_content = json.load(f)
                        parsed_record = normalize_metadata(folder_name, subfolder, json_content)
                        records.append(parsed_record)
                except Exception as e:
                    st.sidebar.warning(f"Failed loading {meta_path}: {e}")

df = pd.DataFrame(records)

# --- Dashboard Layout ---
if not df.empty:
    # 1. High-Level Metrics
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Opportunities", len(df))
    col2.metric("Total Attachments", df["Files"].sum())
    col3.metric("Organizations Tracked", df["Organization"].nunique())
    col4.metric("Active Sources", df["Source"].nunique())

    st.markdown("---")

    # 2. Filters & Controls
    filter_col1, filter_col2 = st.columns([1, 2])
    
    with filter_col1:
        selected_sources = st.multiselect(
            "📍 Filter by Source", 
            options=df["Source"].unique(), 
            default=df["Source"].unique()
        )
    
    with filter_col2:
        search_query = st.text_input("🔍 Search Keyword (Title, Org, or ID)", "")

    # Apply Filters
    filtered_df = df[df["Source"].isin(selected_sources)]
    
    if search_query:
        filtered_df = filtered_df[
            filtered_df["Title"].str.contains(search_query, case=False, na=False) |
            filtered_df["Organization"].str.contains(search_query, case=False, na=False) |
            filtered_df["ID"].str.contains(search_query, case=False, na=False) |
            filtered_df["Description"].str.contains(search_query, case=False, na=False)
        ]

    # 3. Unified Data Table
    st.subheader("📋 Scraped Opportunities Feed")
    st.dataframe(
        filtered_df[["Source", "Date", "ID", "Title", "Organization", "Files", "File List", "URL"]],
        column_config={
            "URL": st.column_config.LinkColumn("Web Link"),
            "Files": st.column_config.NumberColumn("Attachments", help="Count of downloaded files")
        },
        use_container_width=True,
        hide_index=True
    )

    st.markdown("---")

    # 4. Detail Inspector
    st.subheader("🧐 Detail Inspector")
    if not filtered_df.empty:
        # Create a dropdown label with Source and Title
        filtered_df["display_label"] = filtered_df["Source"] + " | " + filtered_df["ID"] + " - " + filtered_df["Title"]
        selected_label = st.selectbox("Select Opportunity to Read Details:", filtered_df["display_label"])
        
        if selected_label:
            selected_row = filtered_df[filtered_df["display_label"] == selected_label].iloc[0]
            
            st.markdown(f"### {selected_row['Title']}")
            st.caption(f"**Source:** {selected_row['Source']} | **ID:** {selected_row['ID']} | **Organization:** {selected_row['Organization']} | **Date:** {selected_row['Date']}")
            
            if selected_row["File List"]:
                st.info(f"📁 **Downloaded Files:** {selected_row['File List']}")
                
            st.markdown("#### Parsed Content / Metadata")
            st.markdown(selected_row["Description"])
    else:
        st.info("No records match your search criteria.")

else:
    st.warning("⚠️ No scraped data found. Ensure your scrapers save output inside '나라장터', 'IRIS', or '기업마당' folders.")