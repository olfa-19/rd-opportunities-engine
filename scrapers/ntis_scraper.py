import os
import json
import time
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

def setup_driver(base_download_dir):
    options = webdriver.ChromeOptions()
    prefs = {
        "download.default_directory": base_download_dir,
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "safebrowsing.enabled": True,
        "plugins.always_open_pdf_externally": True,
        "profile.default_content_setting_values.automatic_downloads": 1 
    }
    options.add_experimental_option("prefs", prefs)
    return webdriver.Chrome(options=options)

def wait_for_downloads(download_dir, timeout=60):
    print(f"[*] Waiting for file downloads in: {download_dir}")
    seconds = 0
    dl_wait = True
    while dl_wait and seconds < timeout:
        time.sleep(1)
        dl_wait = False
        for fname in os.listdir(download_dir):
            if fname.endswith('.crdownload') or fname.endswith('.tmp'):
                dl_wait = True
        seconds += 1
    if seconds >= timeout:
        print("[!] Warning: Downloads timed out.")
    else:
        print("[+] All files downloaded successfully.")

def scrape_ntis_opportunity(driver, base_download_dir, opp_id, opp_title):
    opportunity_data = {
        "bid_id": opp_id,
        "공고명 (Title)": opp_title
    }
    
    try:
        print(f"[*] Extracting details for ID {opp_id}...")
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.XPATH, "//*[contains(text(), '부처명') or contains(text(), '공고기관') or contains(text(), '마감일')]"))
        )
        time.sleep(1.5)
        
        # JS Metadata Extractor for Grid/DL/Table structures
        metadata_script = """
            var data = {};
            
            var dts = document.querySelectorAll('dt');
            var dds = document.querySelectorAll('dd');
            if (dts.length > 0 && dts.length === dds.length) {
                for (var i = 0; i < dts.length; i++) {
                    var k = dts[i].innerText.trim();
                    var v = dds[i].innerText.trim();
                    if (k && v) data[k] = v;
                }
            }

            var allElems = document.querySelectorAll('div, li, span, p');
            allElems.forEach(function(el) {
                if (el.children.length <= 2) {
                    var txt = el.innerText.trim();
                    if (txt.includes(':') && txt.length < 80 && !txt.includes('\\n')) {
                        var parts = txt.split(':');
                        if (parts.length === 2) {
                            var key = parts[0].trim();
                            var val = parts[1].trim();
                            if (key && val && key.length < 30) {
                                data[key] = val;
                            }
                        }
                    }
                }
            });

            var rows = document.querySelectorAll('tr');
            rows.forEach(function(row) {
                var ths = row.querySelectorAll('th');
                var tds = row.querySelectorAll('td');
                if (ths.length > 0 && ths.length === tds.length) {
                    for (var i = 0; i < ths.length; i++) {
                        var k = ths[i].innerText.trim();
                        var v = tds[i].innerText.trim();
                        if (k && v) data[k] = v;
                    }
                }
            });

            return data;
        """
        extracted_data = driver.execute_script(metadata_script)
        if extracted_data:
            opportunity_data.update(extracted_data)

        # Dynamic subfolder creation
        clean_folder_name = "".join([c for c in opp_title if c.isalnum() or c in (' ', '_', '-')]).rstrip().replace(" ", "_")
        folder_name = f"{opp_id}_{clean_folder_name}"[:60]
        specific_opp_dir = os.path.join(base_download_dir, folder_name)
        
        if not os.path.exists(specific_opp_dir):
            os.makedirs(specific_opp_dir)
            
        driver.execute_cdp_cmd('Page.setDownloadBehavior', {
            'behavior': 'allow',
            'downloadPath': specific_opp_dir
        })

        # Download attachment files
        print("    [*] Searching for attachment files...")
        attachments = []
        file_links = driver.find_elements(
            By.XPATH, 
            "//a[contains(@href, 'down') or contains(@href, 'file') or contains(@onclick, 'down') or contains(@onclick, 'file') or contains(translate(text(), 'PDFHWX', 'pdfhwx'), '.pdf') or contains(translate(text(), 'PDFHWX', 'pdfhwx'), '.hwp') or contains(translate(text(), 'ZIP', 'zip'), '.zip')]"
        )

        for link in file_links:
            file_name = link.text.strip()
            if file_name and len(file_name) > 3:
                attachments.append({"file_name": file_name})
                print(f"        -> Downloading: {file_name}")
                driver.execute_script("arguments[0].click();", link)
                time.sleep(1.5) 
                
        wait_for_downloads(specific_opp_dir)

        # Save metadata.json
        opportunity_data["attachments"] = attachments
        opportunity_data["url"] = driver.current_url
        
        json_filename = os.path.join(specific_opp_dir, "metadata.json")
        with open(json_filename, 'w', encoding='utf-8') as f:
            json.dump(opportunity_data, f, ensure_ascii=False, indent=4)
        print(f"    [+] Saved metadata to: {json_filename}\n")

    except Exception as e:
        print(f"[!] Error scraping opportunity ID {opp_id}: {e}\n")

def run_ntis_scraper(target_date=None, force_all=False):
    """
    target_date: Format 'YYYY.MM.DD' or 'YYYY-MM-DD'. If None, defaults to today's date.
    force_all: If True, ignores date filter and scrapes all items on page 1 (useful for testing).
    """
    PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    BASE_DOWNLOAD_DIR = os.path.join(PROJECT_ROOT, "NTIS")
    
    if not os.path.exists(BASE_DOWNLOAD_DIR):
        os.makedirs(BASE_DOWNLOAD_DIR)

    today_dot = datetime.now().strftime("%Y.%m.%d")
    today_dash = datetime.now().strftime("%Y-%m-%d")
    
    if not target_date and not force_all:
        print(f"[*] Target Date set to today: {today_dot}")
    elif target_date:
        print(f"[*] Target Date specified: {target_date}")
    else:
        print("[*] Running in FORCE_ALL mode (scraping all visible page 1 items).")

    driver = setup_driver(BASE_DOWNLOAD_DIR)
    
    try:
        url = "https://www.ntis.go.kr/rndgate/eg/un/ra/mng.do"
        driver.get(url)
        print("[*] Navigated to NTIS dashboard.")
        
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.XPATH, "//a[contains(@onclick, 'fn_view')]"))
        )
        time.sleep(2)

        # Collect list of opportunities from table
        announcement_links = driver.find_elements(By.XPATH, "//a[contains(@onclick, 'fn_view')]")
        print(f"[*] Found {len(announcement_links)} items on the page.")

        candidates = []
        for link in announcement_links:
            title = link.get_attribute("title") or link.text.strip()
            onclick_text = link.get_attribute("onclick") or ""
            opp_id = "".join([c for c in onclick_text if c.isdigit()])
            
            # Find closest table row text to check publication/posting date
            try:
                parent_row = link.find_element(By.XPATH, "./ancestor::tr")
                row_text = parent_row.text
            except Exception:
                row_text = ""

            candidates.append({
                "id": opp_id,
                "title": title,
                "row_text": row_text
            })

        # Filter candidates by date
        to_process = []
        for item in candidates:
            if force_all:
                to_process.append(item)
            elif target_date:
                if target_date in item["row_text"]:
                    to_process.append(item)
            else:
                # Default check against today's date formats
                if today_dot in item["row_text"] or today_dash in item["row_text"]:
                    to_process.append(item)

        print(f"[*] {len(to_process)} opportunities match date criteria.")

        if not to_process:
            print("[!] No new opportunities found for the specified date.")
            return

        # Loop through matched items
        for idx, item in enumerate(to_process, start=1):
            print(f"\n--- Processing ({idx}/{len(to_process)}): {item['title']} (ID: {item['id']}) ---")
            
            # Navigate back to list if not on first iteration
            if driver.current_url != url:
                driver.get(url)
                WebDriverWait(driver, 15).until(
                    EC.presence_of_element_located((By.XPATH, "//a[contains(@onclick, 'fn_view')]"))
                )
                time.sleep(1.5)

            # Trigger JS view function for specific ID
            driver.execute_script(f"fn_view('{item['id']}');")
            scrape_ntis_opportunity(driver, BASE_DOWNLOAD_DIR, item['id'], item['title'])

    except Exception as e:
        print(f"[!] Critical Error in main loop: {e}")
    finally:
        print("[*] Closing browser...")
        driver.quit()
        print("[+] Process finished.")

if __name__ == "__main__":
    # Standard run (filters by today's date automatically):
    run_ntis_scraper()

    # NOTE: To test past announcements (e.g., from 2026.08.21), replace above with:
    # run_ntis_scraper(target_date="2026.08.21")
    
    # Or to force scrape everything on page 1 regardless of date:
    # run_ntis_scraper(force_all=True)