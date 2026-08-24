import os
import json
import re
import asyncio
import argparse
from datetime import datetime
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup

# --- CONFIGURATION & CONSTANTS ---
BASE_DIR = os.path.join(os.getcwd(), "나라장터")
HISTORY_FILE = os.path.join(BASE_DIR, "scraped_ids.json")

TARGET_EXTENSIONS = ['.hwp', '.hwpx', '.pdf', '.docx', '.xlsx', '.zip', '.cell']
IGNORE_KEYWORDS = ["사기 공문", "사칭문자", "수요물자"]

BOT_BASE_URL = "https://www.g2b.go.kr/link/PNPE027_01/single/?bidPbancNo={}&bidPbancOrd={}"
PUBLIC_BASE_URL = "https://www.g2b.go.kr:8081/ep/invitation/publish/bidInfoDtl.do?bidno={}&bidseq={}"

# Limit concurrent page visits to 2 so G2B doesn't choke or block requests
CONCURRENCY_LIMIT = asyncio.Semaphore(2)

# --- STATE MANAGEMENT ---
def load_scraped_history() -> set:
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r") as f:
            return set(json.load(f))
    return set()

def save_scraped_history(history_set: set):
    with open(HISTORY_FILE, "w") as f:
        json.dump(list(history_set), f)

# --- UTILITIES ---
def sanitize_folder_name(name: str) -> str:
    sanitized = re.sub(r'[\/:*?"<>|]', '_', name)
    return sanitized.strip()[:100]

def parse_bid_info(raw_bid_no: str):
    if "-" in raw_bid_no:
        parts = raw_bid_no.split("-")
        return parts[0], parts[1].zfill(3)
    return raw_bid_no, "000"

# --- SCRAPING LOGIC ---
async def process_opportunity(context, item, index, total, history_set):
    async with CONCURRENCY_LIMIT:
        bid_no = item["bid_id"]
        title = item["title"]
        
        folder_name = sanitize_folder_name(f"[{bid_no}] {title}")
        opportunity_dir = os.path.join(BASE_DIR, folder_name)
        os.makedirs(opportunity_dir, exist_ok=True)
        
        print(f"\n[Task {index}/{total}] Processing {bid_no}...")
        
        base_no, ord_no = parse_bid_info(bid_no)
        bot_url = BOT_BASE_URL.format(base_no, ord_no)
        public_url = PUBLIC_BASE_URL.format(base_no, ord_no)
        
        item["url"] = public_url 
        page = await context.new_page()
        page.on("dialog", lambda dialog: asyncio.create_task(dialog.accept()))
        
        try:
            # Use 'domcontentloaded' with fallback delay instead of strict 'networkidle'
            await page.goto(bot_url, wait_until='domcontentloaded', timeout=45000)
            await page.wait_for_timeout(5000) 
            
            # 1. Extract Description
            try:
                detail_html = await page.content()
                detail_soup = BeautifulSoup(detail_html, "html.parser")
                for script in detail_soup(["script", "style"]):
                    script.extract()
                item["raw_text_description"] = detail_soup.get_text(separator="\n", strip=True)
            except Exception as e:
                item["raw_text_description"] = f"Extraction failed: {str(e)}"
                
            # 2. Extract Attachments
            print(f"    [Task {index}] Hunting for files...")
            downloaded_files = set()
            
            # Escaped backslash fix for Python string formatting regex
            ext_pattern = "|".join([ext.strip('.') for ext in TARGET_EXTENSIONS])
            selector_query = f"text=/\\.({ext_pattern})$/i"
            
            text_elements = await page.locator(selector_query).all()
            link_elements = await page.locator("a, button, span[onclick*='download']").all()
            all_elements = text_elements + link_elements
            
            for elem in all_elements:
                try:
                    if not await elem.is_visible():
                        continue
                        
                    text = (await elem.inner_text()).strip()
                    if not text or text in downloaded_files:
                        continue
                        
                    is_file = any(ext in text.lower() for ext in TARGET_EXTENSIONS) or "download" in (await elem.get_attribute("onclick") or "").lower()
                    
                    if is_file and not any(k in text for k in IGNORE_KEYWORDS):
                        try:
                            async with page.expect_download(timeout=10000) as download_info:
                                await elem.evaluate("""node => {
                                    node.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
                                    node.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
                                    node.click();
                                }""")
                            
                            download = await download_info.value
                            actual_filename = download.suggested_filename
                            
                            if not actual_filename:
                                actual_filename = text if any(ext in text.lower() for ext in TARGET_EXTENSIONS) else f"attachment_{len(downloaded_files)}.file"
                            
                            final_save_path = os.path.join(opportunity_dir, actual_filename)
                            await download.save_as(final_save_path)
                            
                            item["attachments"].append({"file_name": actual_filename, "url": public_url})
                            downloaded_files.add(text)
                            print(f"    [Task {index}] [+] Downloaded: {actual_filename}")
                        except Exception:
                            pass
                except Exception:
                    pass
                    
            history_set.add(bid_no)
            
        except Exception as e:
            print(f"    [Task {index}] [!] Error processing {bid_no}: {e}")
        finally:
            json_path = os.path.join(opportunity_dir, "metadata.json")
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(item, f, ensure_ascii=False, indent=2)
                
            await page.close()


async def scrape_g2b_spa_full(keyword: str, headless: bool):
    os.makedirs(BASE_DIR, exist_ok=True)
    scraped_history = load_scraped_history()
    
    target_date_str = datetime.now().strftime("%Y/%m/%d")
    print(f"[*] Starting daily run for date: {target_date_str} with keyword: '{keyword}'")
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context(
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            viewport={'width': 1400, 'height': 900},
            accept_downloads=True
        )
        
        main_page = await context.new_page()
        
        print('[*] Navigating to G2B main portal...')
        await main_page.goto('https://www.g2b.go.kr/', wait_until='domcontentloaded')
        await main_page.wait_for_timeout(4000)
        await main_page.keyboard.press("Escape")
        
        await main_page.evaluate(f'''
            const searchInput = document.getElementById('mf_wfm_gnb_wfm_gnbBtm_inpGlobalSearch');
            if (searchInput) searchInput.value = '{keyword}';
            const searchBtn = document.getElementById('mf_wfm_gnb_wfm_gnbBtm_btnGlobalSearch');
            if (searchBtn) searchBtn.click();
        ''')
        
        print('[*] Waiting for search results to load...')
        await main_page.wait_for_timeout(8000)
        
        title_locators = await main_page.locator("label[id$='_bizNm']").all()
        bid_nos = await main_page.locator("label[id$='_bizNo']").all()
        agencies = await main_page.locator("label[id$='_dmstUntyGrpNm']").all()
        dates = await main_page.locator("label[id$='_pbancPstgDt']").all()
        
        opportunities = []
        for i in range(len(title_locators)):
            date_text = (await dates[i].inner_text()).strip() if i < len(dates) else ""
            item_date = date_text[:10]
            
            if item_date != target_date_str:
                print(f"[-] Reached older date ({item_date}). Stopping queue.")
                break
                
            bid_no = (await bid_nos[i].inner_text()).strip() if i < len(bid_nos) else f"UNKNOWN_{i}"
            
            if bid_no in scraped_history:
                print(f"[-] Skipping {bid_no} - Already scraped previously.")
                continue
                
            title_text = (await title_locators[i].inner_text()).strip()
            agency = (await agencies[i].inner_text()).strip() if i < len(agencies) else ""
            
            opportunities.append({
                "bid_id": bid_no,
                "title": title_text,
                "organization": agency,
                "posting_date": date_text,
                "url": "",
                "raw_text_description": "",
                "attachments": []
            })
        
        await main_page.close()
        
        if not opportunities:
            print("[*] No new opportunities found for today. Exiting.")
        else:
            print(f"\n[*] Found {len(opportunities)} NEW results for {target_date_str}. Dispatching workers (max 2 at a time)...")
            tasks = [
                process_opportunity(context, item, idx + 1, len(opportunities), scraped_history) 
                for idx, item in enumerate(opportunities)
            ]
            await asyncio.gather(*tasks)
            save_scraped_history(scraped_history)

        await browser.close()
        print("\n[+] Scraping Complete!")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="G2B Daily Scraper")
    parser.add_argument("--keyword", type=str, default="AI", help="Search keyword")
    parser.add_argument("--headless", action="store_true", help="Run browser in background")
    args = parser.parse_args()
    
    asyncio.run(scrape_g2b_spa_full(keyword=args.keyword, headless=args.headless))