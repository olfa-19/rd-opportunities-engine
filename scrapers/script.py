import os
import json
import re
import asyncio
import argparse
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup

# --- CONFIGURATION & STATE ---
BASE_DIR = os.path.join(os.getcwd(), "나라장터")
HISTORY_FILE = os.path.join(BASE_DIR, "scraped_ids.json")

def load_scraped_history():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r") as f:
            return set(json.load(f))
    return set()

def save_scraped_history(history_set):
    with open(HISTORY_FILE, "w") as f:
        json.dump(list(history_set), f)

def sanitize_folder_name(name: str) -> str:
    return re.sub(r'[\/:*?"<>|]', '_', name).strip()[:100]

# --- SCRAPING LOGIC ---
async def extract_item_details(page, item, folder_path, task_idx, total):
    print(f"    [Task {task_idx}/{total}] Waiting for detail view to load...")
    await page.wait_for_timeout(7000) # Give it plenty of time to render
    
    print(f"      [Task {task_idx}] Nuking popups and overlays from the DOM...")
    # NUCLEAR FIX 1: Physically delete anything that looks like a popup or backdrop overlay
    nuke_js = """
        document.querySelectorAll('[class*="pop"], [class*="modal"], [class*="dialog"], [class*="overlay"], [style*="z-index"]').forEach(el => {
            const z = window.getComputedStyle(el).zIndex;
            if (z !== 'auto' && parseInt(z) > 100) {
                el.remove();
            }
        });
    """
    try:
        await page.evaluate(nuke_js)
        for frame in page.frames:
            await frame.evaluate(nuke_js)
    except Exception:
        pass
        
    await page.wait_for_timeout(1000)

    # --- 3. EXTRACT TEXT ---
    item["raw_text_description"] = ""
    for frame in page.frames:
        try:
            html = await frame.content()
            soup = BeautifulSoup(html, "html.parser")
            text = soup.get_text(separator="\n", strip=True)
            if "공고일자" in text or "입찰" in text or "규격" in text:  
                item["raw_text_description"] += text + "\n"
        except Exception:
            continue
            
    # --- 4. EXTRACT FILES ---
    downloaded_files = set()
    ignore_keywords = ["사기 공문", "사칭문자", "수요물자", "조달청고시제", "신구조문대비"]
    
    for frame in page.frames:
        try:
            # Grab absolutely anything that has a file extension or download tag
            text_elements = await frame.locator(r"text=/\.(hwp|hwpx|pdf|docx|xlsx|zip|cell|ppt|pptx|xls|doc)/i").all()
            link_elements = await frame.locator("a, button, span[onclick*='download']").all()
            
            all_elements = text_elements + link_elements
            
            for elem in all_elements:
                try:
                    text = (await elem.inner_text()).strip()
                    if not text or text in downloaded_files: 
                        continue
                        
                    if any(k in text for k in ignore_keywords):
                        continue
                        
                    exts = ['.hwp', '.hwpx', '.pdf', '.docx', '.xlsx', '.zip', '.cell', '.ppt', '.pptx', '.xls', '.doc']
                    is_file = any(ext in text.lower() for ext in exts) or "download" in (await elem.get_attribute("onclick") or "").lower()
                    
                    if is_file:
                        print(f"      [Task {task_idx}] Found target file: '{text}' - Forcing download click...")
                        
                        try:
                            # NUCLEAR FIX 2: Bypassing strict visibility checks and scrolling forcefully
                            await elem.scroll_into_view_if_needed()
                            async with page.expect_download(timeout=10000) as download_info:
                                # First try native playwright force click
                                await elem.click(force=True, timeout=3000)
                            
                            download = await download_info.value
                            actual_filename = download.suggested_filename or text
                            actual_filename = sanitize_folder_name(actual_filename) 
                            
                            final_save_path = os.path.join(folder_path, actual_filename)
                            await download.save_as(final_save_path)
                            
                            item["attachments"].append({"file_name": actual_filename, "url": page.url})
                            downloaded_files.add(text)
                            print(f"      [Task {task_idx}] [+] Success: {actual_filename}")
                            
                        except Exception:
                            # Fallback: if native click fails, try injecting raw javascript mouse event
                            try:
                                async with page.expect_download(timeout=10000) as download_info:
                                    await elem.evaluate("node => { node.dispatchEvent(new MouseEvent('mousedown', { bubbles: true })); node.click(); }")
                                
                                download = await download_info.value
                                actual_filename = sanitize_folder_name(download.suggested_filename or text)
                                await download.save_as(os.path.join(folder_path, actual_filename))
                                
                                item["attachments"].append({"file_name": actual_filename, "url": page.url})
                                downloaded_files.add(text)
                                print(f"      [Task {task_idx}] [+] Success (JS Click): {actual_filename}")
                            except Exception:
                                downloaded_files.add(text) # Add to skip list so we don't loop on it
                                
                except Exception:
                    continue
        except Exception:
            continue

    if not downloaded_files:
        debug_img = os.path.join(folder_path, f"DEBUG_{item['bid_id']}.png")
        await page.screenshot(path=debug_img, full_page=True)
        print(f"      [Task {task_idx}] ⚠️ No files downloaded! Saved screenshot to look at: {debug_img}")

    with open(os.path.join(folder_path, "metadata.json"), "w", encoding="utf-8") as f:
        json.dump(item, f, ensure_ascii=False, indent=2)

async def process_single_opportunity(context, item, folder_path, task_idx, total, history_set):
    await asyncio.sleep(task_idx * 2)
    page = await context.new_page()
    page.on("dialog", lambda dialog: asyncio.create_task(dialog.accept()))
    
    try:
        await page.goto("https://www.g2b.go.kr/", wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(3000)
        await page.keyboard.press("Escape")
        
        await page.evaluate(f'''
            const searchInput = document.getElementById('mf_wfm_gnb_wfm_gnbBtm_inpGlobalSearch');
            if (searchInput) searchInput.value = '{item["bid_id"]}';
            const searchBtn = document.getElementById('mf_wfm_gnb_wfm_gnbBtm_btnGlobalSearch');
            if (searchBtn) searchBtn.click();
        ''')
        
        await page.wait_for_timeout(6000)
        
        # NUCLEAR FIX 3: Click the exact text label, not the surrounding cell padding
        title_label = page.locator("label[id$='_bizNm']").first
        await title_label.wait_for(state="visible", timeout=15000)
        await title_label.click(force=True)
        
        await extract_item_details(page, item, folder_path, task_idx, total)
        history_set.add(item["bid_id"])
        
    except Exception as e:
        print(f"    [Task {task_idx}] Error processing {item['bid_id']}: {e}")
    finally:
        await page.close()

async def run_scraper(keyword: str, max_results: int, headless: bool):
    os.makedirs(BASE_DIR, exist_ok=True)
    scraped_history = load_scraped_history()
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context(accept_downloads=True)
        main_page = await context.new_page()
        
        print(f'[*] Searching for "{keyword}"...')
        await main_page.goto('https://www.g2b.go.kr/', wait_until='domcontentloaded', timeout=60000)
        await main_page.wait_for_timeout(3000)
        
        await main_page.evaluate(f'''
            const searchInput = document.getElementById('mf_wfm_gnb_wfm_gnbBtm_inpGlobalSearch');
            if (searchInput) searchInput.value = '{keyword}';
            document.getElementById('mf_wfm_gnb_wfm_gnbBtm_btnGlobalSearch').click();
        ''')
        await main_page.wait_for_timeout(8000)
        
        title_locators = await main_page.locator("label[id$='_bizNm']").all()
        bid_nos = await main_page.locator("label[id$='_bizNo']").all()
        agencies = await main_page.locator("label[id$='_dmstUntyGrpNm']").all()
        dates = await main_page.locator("label[id$='_pbancPstgDt']").all()
        
        items_to_process = []
        for i in range(min(len(title_locators), max_results)):
            bid_no = (await bid_nos[i].inner_text()).strip()
            
            if bid_no in scraped_history:
                print(f"[-] Skipping {bid_no} (Already scraped)")
                continue
                
            title_text = (await title_locators[i].inner_text()).strip()
            folder_name = sanitize_folder_name(f"[{bid_no}] {title_text}")
            opportunity_dir = os.path.join(BASE_DIR, folder_name)
            os.makedirs(opportunity_dir, exist_ok=True)
            
            items_to_process.append({
                "item": {
                    "bid_id": bid_no,
                    "title": title_text,
                    "organization": (await agencies[i].inner_text()).strip(),
                    "posting_date": (await dates[i].inner_text()).strip(),
                    "url": "https://www.g2b.go.kr/",
                    "raw_text_description": "",
                    "attachments": []
                },
                "folder": opportunity_dir
            })
            
        await main_page.close()
        
        if items_to_process:
            print(f"[*] Found {len(items_to_process)} NEW items. Dispatching workers...")
            tasks = [process_single_opportunity(context, data["item"], data["folder"], idx+1, len(items_to_process), scraped_history) 
                     for idx, data in enumerate(items_to_process)]
            await asyncio.gather(*tasks)
            save_scraped_history(scraped_history)
        else:
            print("[*] No new items found.")
            
        await browser.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="G2B Scraper")
    parser.add_argument("--keyword", type=str, default="AI", help="Search keyword")
    parser.add_argument("--limit", type=int, default=5, help="Max results to check")
    parser.add_argument("--headless", action="store_true", help="Run in background")
    args = parser.parse_args()
    
    asyncio.run(run_scraper(args.keyword, args.limit, args.headless))