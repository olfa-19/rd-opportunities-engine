import os
import json
import time
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
    print(f"[*] Waiting for file downloads to complete in: {download_dir}")
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
        print("[!] Warning: Some downloads may not have finished before timeout.")
    else:
        print("[+] All files downloaded successfully.")

def scrape_iris_opportunity(driver, base_download_dir):
    opportunity_data = {}
    
    try:
        print("[*] Checking detail page structure...")
        time.sleep(3)
        
        # Switch into iframe if content resides inside one
        iframes = driver.find_elements(By.TAG_NAME, "iframe")
        for iframe in iframes:
            try:
                driver.switch_to.frame(iframe)
                if len(driver.find_elements(By.XPATH, "//*[contains(text(), '소관부처') or contains(text(), '공고번호') or contains(text(), '공고명')]")) > 0:
                    print("[*] Detail data found inside an iframe.")
                    break 
                driver.switch_to.default_content()
            except:
                driver.switch_to.default_content()

        print("[*] Waiting for the opportunity data to load...")
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.XPATH, "//*[contains(text(), '소관부처') or contains(text(), '공고번호') or contains(text(), '공고명')]"))
        )
        
        print("[*] Extracting target metadata from main content area...")
        
        metadata_script = """
            var data = {};
            var container = document.querySelector('#contents, .contents, .sub_contents, .sub_content, main, form') || document.body;
            
            var titleEl = container.querySelector('h2, h3, .board_view_title, .view_tit, .tit');
            if (titleEl && !titleEl.innerText.includes("IRIS 소개")) {
                data['공고명 (Title)'] = titleEl.innerText.trim();
            }

            var rows = container.querySelectorAll('tr');
            rows.forEach(function(row) {
                var ths = row.querySelectorAll('th');
                var tds = row.querySelectorAll('td');
                
                if (ths.length > 0 && ths.length === tds.length) {
                    for (var i = 0; i < ths.length; i++) {
                        var key = ths[i].innerText.trim();
                        var val = tds[i].innerText.trim();
                        if (key && key.length < 50 && val) data[key] = val;
                    }
                } 
                else if (ths.length === 1 && tds.length > 0) {
                    var key = ths[0].innerText.trim();
                    var val = tds[0].innerText.trim();
                    if (key && key.length < 50 && val) data[key] = val;
                }
            });
            return data;
        """
        extracted_data = driver.execute_script(metadata_script)
        
        if extracted_data and len(extracted_data.keys()) > 0:
            opportunity_data.update(extracted_data)
        else:
            print("[!] Warning: JavaScript extractor found no structured data. Falling back to page source parse.")
            opportunity_data["raw_text"] = driver.find_element(By.TAG_NAME, "body").text[:2000]

        # Dynamic Folder Creation
        folder_identifier = opportunity_data.get("공고번호") or opportunity_data.get("공고명 (Title)") or f"IRIS_Opp_{int(time.time())}"
        clean_folder_name = "".join([c for c in folder_identifier if c.isalnum() or c in (' ', '_', '-')]).rstrip().replace(" ", "_")
        
        specific_opp_dir = os.path.join(base_download_dir, clean_folder_name[:60])
        
        if not os.path.exists(specific_opp_dir):
            os.makedirs(specific_opp_dir)
            print(f"[*] Created opportunity folder: {specific_opp_dir}")
            
        driver.execute_cdp_cmd('Page.setDownloadBehavior', {
            'behavior': 'allow',
            'downloadPath': specific_opp_dir
        })

        # Save metadata.json
        json_filename = os.path.join(specific_opp_dir, "metadata.json")
        with open(json_filename, 'w', encoding='utf-8') as f:
            json.dump(opportunity_data, f, ensure_ascii=False, indent=4)
        print(f"[+] Metadata successfully saved to: {json_filename}")

        # Download Attachments
        print("[*] Searching for attachments...")
        attachments = []
        
        file_links = driver.find_elements(By.XPATH, "//a[contains(translate(text(), 'PDFHWX', 'pdfhwx'), '.pdf') or contains(translate(text(), 'PDFHWX', 'pdfhwx'), '.hwp') or contains(translate(text(), 'ZIP', 'zip'), '.zip')]")
        
        if not file_links:
            file_links = driver.find_elements(By.XPATH, "//a[contains(@href, 'download') or contains(@class, 'file') or contains(@onclick, 'file')]")

        for link in file_links:
            file_name = link.text.strip()
            if file_name and len(file_name) > 3:
                attachments.append({"file_name": file_name})
                print(f"    -> Downloading: {file_name}")
                driver.execute_script("arguments[0].click();", link)
                time.sleep(1.5) 
                
        wait_for_downloads(specific_opp_dir)

    except Exception as e:
        print(f"[!] Error during scraping: {e}")

def prepare_main_page(driver):
    """Utility to navigate to IRIS main page and clear popups/frames."""
    driver.get("https://iris.go.kr/main.do")
    time.sleep(3) 
    
    driver.execute_script("""
        var elements = document.querySelectorAll('[class*="pop"], [id*="pop"], .layer, .modal');
        for (var i = 0; i < elements.length; i++) {
            elements[i].style.display = 'none';
        }
    """)
    
    iframes = driver.find_elements(By.TAG_NAME, "iframe")
    for iframe in iframes:
        try:
            driver.switch_to.frame(iframe)
            if "접수중" in driver.page_source:
                print("[*] Target data found inside an iframe! Switched context.")
                break
            driver.switch_to.default_content()
        except:
            driver.switch_to.default_content()
            
    driver.execute_script("window.scrollTo(0, 800);")
    time.sleep(2)

# --- Execution Block ---
if __name__ == "__main__":
    PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    BASE_DOWNLOAD_DIR = os.path.join(PROJECT_ROOT, "IRIS")
    
    if not os.path.exists(BASE_DOWNLOAD_DIR):
        os.makedirs(BASE_DOWNLOAD_DIR)

    print("[*] Starting IRIS Scraper...")
    driver = setup_driver(BASE_DOWNLOAD_DIR)
    
    try:
        print("[*] Navigating to IRIS main dashboard...")
        prepare_main_page(driver)
        original_window = driver.current_window_handle

        # Count total '접수중' badges on the main page
        total_badges = driver.execute_script("""
            var xpath = "//*[normalize-space(text())='접수중']";
            var elements = document.evaluate(xpath, document, null, XPathResult.ORDERED_NODE_SNAPSHOT_TYPE, null);
            return elements.snapshotLength;
        """)

        print(f"[*] Total '접수중' badges found on dashboard: {total_badges}")

        if total_badges == 0:
            print("[!] No '접수중' badges located.")
        
        # Loop through each opportunity badge
        for item_index in range(total_badges):
            print(f"\n--- Processing Opportunity {item_index + 1} of {total_badges} ---")
            
            # Reset context back to main page for iterations after the first
            if item_index > 0:
                # Close any extra detail tabs if open
                while len(driver.window_handles) > 1:
                    driver.switch_to.window(driver.window_handles[-1])
                    driver.close()
                driver.switch_to.window(original_window)
                prepare_main_page(driver)

            # Click badge by target index
            click_result = driver.execute_script(f"""
                var targetIdx = {item_index};
                var xpath = "//*[normalize-space(text())='접수중']";
                var elements = document.evaluate(xpath, document, null, XPathResult.ORDERED_NODE_SNAPSHOT_TYPE, null);
                
                if (targetIdx >= elements.snapshotLength) return 'INDEX_OUT_OF_BOUNDS';
                
                var badge = elements.snapshotItem(targetIdx);
                var row = badge.closest('tr, li');
                
                if (!row) {{
                    row = badge.parentElement;
                    while (row && row.tagName !== 'BODY') {{
                        if (row.querySelectorAll('a').length > 0) break;
                        row = row.parentElement;
                    }}
                }}
                
                if (row) {{
                    var links = row.querySelectorAll('a');
                    for (var j = 0; j < links.length; j++) {{
                        if (links[j].innerText.trim().length > 10) {{
                            links[j].click();
                            return 'CLICKED_A_TAG';
                        }}
                    }}
                    if (row.hasAttribute('onclick')) {{
                        row.click();
                        return 'CLICKED_ROW_ITSELF';
                    }}
                }}
                return 'FOUND_BADGE_BUT_NO_CLICKABLE_LINK';
            """)

            print(f"[*] JS Click Result for Index {item_index}: {click_result}")

            if click_result in ['CLICKED_A_TAG', 'CLICKED_ROW_ITSELF']:
                time.sleep(4) 
                
                # Switch to new tab if opened
                if len(driver.window_handles) > 1:
                    for window_handle in driver.window_handles:
                        if window_handle != original_window:
                            driver.switch_to.window(window_handle)
                            break
                
                WebDriverWait(driver, 15).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "body"))
                )
                time.sleep(2) 
                
                scrape_iris_opportunity(driver, BASE_DOWNLOAD_DIR)
            else:
                print(f"[!] Could not trigger click for badge index {item_index}")

    except Exception as e:
        print(f"[!] Critical Error: {e}")
        
    finally:
        print("[*] Closing browser...")
        driver.quit()
        print("[+] Process finished.")