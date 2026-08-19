import os
import json
import pandas as pd

BASE_DIR = os.path.join(os.getcwd(), "나라장터")
OUTPUT_EXCEL = os.path.join(BASE_DIR, "G2B_Scraped_Opportunities_Summary.xlsx")

def build_excel_summary():
    if not os.path.exists(BASE_DIR):
        print(f"[!] Directory '{BASE_DIR}' does not exist.")
        return

    records = []

    # Iterate through all scraped item folders
    for item_folder in os.listdir(BASE_DIR):
        folder_path = os.path.join(BASE_DIR, item_folder)
        meta_path = os.path.join(folder_path, "metadata.json")

        if os.path.isdir(folder_path) and os.path.exists(meta_path):
            try:
                with open(meta_path, "r", encoding="utf-8") as f:
                    data = json.load(f)

                attachments = data.get("attachments", [])
                file_details = []
                file_types = set()

                for att in attachments:
                    fname = att.get("file_name", "")
                    if fname:
                        # Extract file extension (e.g., .hwp, .pdf)
                        _, ext = os.path.splitext(fname)
                        ext_clean = ext.replace(".", "").upper() if ext else "UNKNOWN"
                        
                        file_types.add(ext_clean)
                        file_details.append(f"{fname} ({ext_clean})")

                # Truncate description for Excel cell readability
                raw_desc = data.get("raw_text_description", "").strip()
                desc_preview = (raw_desc[:300].replace("\n", " ") + "...") if len(raw_desc) > 300 else raw_desc.replace("\n", " ")

                records.append({
                    "Bid ID": data.get("bid_id", ""),
                    "Title": data.get("title", ""),
                    "Organization": data.get("organization", ""),
                    "Posting Date": data.get("posting_date", ""),
                    "Total Files Scraped": len(attachments),
                    "File Types": ", ".join(sorted(file_types)) if file_types else "None",
                    "Scraped Files List": "\n".join(file_details) if file_details else "None",
                    "Public URL": data.get("url", ""),
                    "Description Preview": desc_preview,
                    "Local Folder Path": folder_path
                })
            except Exception as e:
                print(f"[!] Error parsing {meta_path}: {e}")

    if not records:
        print("[!] No valid metadata.json files found to export.")
        return

    # Create DataFrame and sort by posting date / bid ID
    df = pd.DataFrame(records)
    df.sort_values(by=["Posting Date", "Bid ID"], ascending=[False, False], inplace=True)

    # Write to Excel with auto-adjusted column width formatting
    with pd.ExcelWriter(OUTPUT_EXCEL, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Scraped Opportunities")
        
        # Access openpyxl worksheet to format column widths
        worksheet = writer.sheets["Scraped Opportunities"]
        for col in worksheet.columns:
            max_len = max(len(str(cell.value or '')) for cell in col)
            col_letter = col[0].column_letter
            # Set reasonable width boundaries
            worksheet.column_dimensions[col_letter].width = min(max(max_len + 3, 12), 50)

    print(f"\n[+] Report successfully generated!\n[+] Saved to: {OUTPUT_EXCEL}")

if __name__ == "__main__":
    build_excel_summary()