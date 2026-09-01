import os
import json
import pandas as pd
import streamlit as st
import datetime

# --- Team Bridge Styling & Config ---
st.set_page_config(page_title="Team Bridge - R&D Feed", layout="wide", page_icon="🌉")
st.title("🌉 Team Bridge: R&D & Procurement Engine")
st.markdown("Unified dashboard for tracking and managing localized R&D opportunities.")
st.markdown("---")

PROJECT_ROOT = os.getcwd()
SCRAPER_FOLDERS = ["나라장터", "IRIS", "기업마당", "NTIS", "K-Startup", "IITP"]

def extract_attachment_names(data):
    """Extract attachment names from metadata."""
    attachments = data.get("attachments") or data.get("첨부파일 (Attachments)") or []
    file_list = []
    
    if isinstance(attachments, list):
        for item in attachments:
            if isinstance(item, dict):
                file_list.append(item.get("file_name", "Attachment"))
            elif isinstance(item, str):
                file_list.append(item)
    return file_list

def normalize_metadata(source_name, folder_path, data, meta_path):
    """Normalize metadata fields, prioritizing JSON date fields before file timestamps."""
    folder_name = os.path.basename(folder_path)
    opp_id = data.get("bid_id") or data.get("공고번호") or folder_name
    title = data.get("title") or data.get("공고명 (Title)") or data.get("공고명") or folder_name
    organization = (
        data.get("organization") or 
        data.get("소관부처") or 
        data.get("전문기관명") or 
        data.get("공고기관") or 
        data.get("발주기관") or 
        "N/A"
    )
    
    # 1. Look for explicit date keys inside metadata.json
    raw_date = (
        data.get("scraped_at") or 
        data.get("collected_at") or 
        data.get("posting_date") or 
        data.get("공고기간") or 
        data.get("접수기간") or 
        data.get("등록일")
    )
    
    # 2. Fallback to file timestamp if no date is found in JSON
    if raw_date and str(raw_date).strip():
        date = str(raw_date).strip()
    else:
        file_timestamp = os.path.getmtime(meta_path)
        date = datetime.datetime.fromtimestamp(file_timestamp).strftime('%Y-%m-%d')
    
    file_names = extract_attachment_names(data)
    files_str = ", ".join(file_names) if file_names else "No downloadable files"
    
    desc = (
        f"**Source Platform:** {source_name}\n\n"
        f"**Opportunity ID:** {opp_id}\n\n"
        f"**Project Name:** {title}\n\n"
        f"**Organization:** {organization}\n\n"
        f"**Date:** {date}\n\n"
        f"**Available Files:** {files_str}"
    )

    return {
        "Source": source_name,
        "ID": str(opp_id),
        "Title": str(title),
        "Organization": str(organization),
        "Date": str(date),
        "Files": len(file_names),
        "File List": ", ".join(file_names),
        "Folder Path": folder_path, 
        "Description": desc
    }

# --- Data Loader ---
records = []

for source_folder in SCRAPER_FOLDERS:
    source_dir = os.path.join(PROJECT_ROOT, source_folder)
    
    if os.path.exists(source_dir):
        for root, dirs, files in os.walk(source_dir):
            if "metadata.json" in files:
                meta_path = os.path.join(root, "metadata.json")
                try:
                    with open(meta_path, "r", encoding="utf-8") as f:
                        json_content = json.load(f)
                        parsed = normalize_metadata(source_folder, root, json_content, meta_path)
                        records.append(parsed)
                except Exception as e:
                    st.sidebar.warning(f"Error loading {meta_path}: {e}")

df = pd.DataFrame(records)

# --- Dashboard Layout ---
if not df.empty:
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Opportunities", len(df))
    col2.metric("Total Attachments", df["Files"].sum())
    col3.metric("Organizations Tracked", df["Organization"].nunique())
    col4.metric("Active Sources", df["Source"].nunique())

    st.markdown("---")

    filter_col1, filter_col2 = st.columns([1, 2])
    
    with filter_col1:
        selected_sources = st.multiselect(
            "📍 Filter by Platform Source", 
            options=df["Source"].unique(), 
            default=df["Source"].unique()
        )
    
    with filter_col2:
        search_query = st.text_input("🔍 Search Keyword (Title, Org, or ID)", "")

    filtered_df = df[df["Source"].isin(selected_sources)]
    
    if search_query:
        filtered_df = filtered_df[
            filtered_df["Title"].str.contains(search_query, case=False, na=False) |
            filtered_df["Organization"].str.contains(search_query, case=False, na=False) |
            filtered_df["ID"].str.contains(search_query, case=False, na=False)
        ]

    st.subheader("📋 Scraped Opportunities Feed")
    st.dataframe(
        filtered_df[["Source", "Date", "ID", "Title", "Organization", "Files", "File List"]],
        column_config={
            "Files": st.column_config.NumberColumn("Attachments", help="Count of downloaded files")
        },
        use_container_width=True,
        hide_index=True
    )

    st.markdown("---")

    # --- Detail & Download Inspector ---
    st.subheader("🧐 Detail Inspector & File Downloader")
    if not filtered_df.empty:
        filtered_df["display_label"] = filtered_df["Source"] + " | " + filtered_df["ID"] + " - " + filtered_df["Title"]
        selected_label = st.selectbox("Select Opportunity to Inspect & Download Files:", filtered_df["display_label"])
        
        if selected_label:
            selected_row = filtered_df[filtered_df["display_label"] == selected_label].iloc[0]
            
            st.markdown(f"### {selected_row['Title']}")
            st.info(selected_row["Description"])
            
            # --- FILE DOWNLOAD SECTION ---
            folder_path = selected_row["Folder Path"]
            if os.path.exists(folder_path):
                downloadable_files = [
                    f for f in os.listdir(folder_path) 
                    if f != "metadata.json" and not f.startswith(".")
                ]
                
                if downloadable_files:
                    st.markdown("#### 📁 Download Attachments")
                    file_cols = st.columns(min(len(downloadable_files), 3))
                    
                    for idx, file_name in enumerate(downloadable_files):
                        full_file_path = os.path.join(folder_path, file_name)
                        col_target = file_cols[idx % 3]
                        
                        with open(full_file_path, "rb") as fp:
                            col_target.download_button(
                                label=f"📄 {file_name}",
                                data=fp.read(),
                                file_name=file_name,
                                mime="application/octet-stream",
                                key=f"dl_{selected_row['ID']}_{idx}"
                            )
                else:
                    st.info("No physical attachment files found in this opportunity directory.")
    else:
        st.info("No records match your search criteria.")

else:
    st.warning("⚠️ No scraped data found.")