import os
import json
import re
import asyncio
import argparse
from datetime import datetime
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup

# --- CONFIGURATION & CONSTANTS ---
BASE_DIR = os.path.join(os.getcwd(), "기업마당")
HISTORY_FILE = os.path.join(BASE_DIR, "scraped_ids.json")

# Bizinfo Support Project List URL
BIZINFO_SEARCH_URL = "https://www.bizinfo.go.kr/web/lay1/bbs/S1T122C128/AS/74/list.do"

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

# --- SCRAPING LOGIC ---
async def process_bizinfo_opportunity(context, item, index, total, history_set):
    bid_id = item["bid_id"]
    title = item["title"]
    detail_url = item["url"]
    
    folder_name = sanitize_folder_name(f"[기업마당_{bid_id}] {title}")
    opportunity_dir = os.path.join(BASE_DIR, folder_name)
    os.makedirs(opportunity_dir, exist_ok=True)
    
    print(f"\n[Task {index}/{total}] Processing Bizinfo {bid_id} in background...")
    
    page = await context.new_page()
    page.on("dialog", lambda dialog: asyncio.create_task(dialog.accept()))
    
    try:
        await page.goto(detail_url, wait_until='networkidle')
        await page.wait_for_timeout(3000)
        
        # 1. Extract Description
        try:
            detail_html = await page.content()
            detail_soup = BeautifulSoup(detail_html, "html.parser")
            
            # Find the main content area (usually inside a specific div on Bizinfo)
            content_area = detail_soup.select_one(".view_cont") or detail_soup
            for script in content_area(["script", "style"]):
                script.extract()
            item["raw_text_description"] = content_area.get_text(separator="\n", strip=True)
        except Exception as e:
            item["raw_text_description"] = f"Extraction failed: {str(e)}"
            
        # 2. Extract Attachments (UPDATED FIX)
        print(f"    [Task {index}] Hunting for files...")
        downloaded_files = set() # Track by href instead of text to avoid "다운로드" duplicates
        
        # Target the exact URL pattern we found in the inspect tool
        file_links = await page.locator("a[href*='fileDown.do']").all()
        
        for elem in file_links:
            try:
                if not await elem.is_visible():
                    continue
                    
                href = await elem.get_attribute("href")
                if not href or href in downloaded_files:
                    continue
                    
                try:
                    async with page.expect_download(timeout=10000) as download_info:
                        # CRITICAL FIX: Remove target="_blank" to force download in the same tab
                        await elem.evaluate("node => node.removeAttribute('target')")
                        await elem.click(force=True)
                    
                    download = await download_info.value
                    
                    # Playwright gets the real filename from the server's headers
                    actual_filename = download.suggested_filename
                    
                    # Fallback: Extract from the 'title' attribute if the server fails to provide it
                    if not actual_filename:
                        title_attr = await elem.get_attribute("title") or ""
                        # Cleans up "첨부파일 ★「AI 기반...」 FAQ.pdf 다운로드"
                        actual_filename = title_attr.replace("첨부파일", "").replace("다운로드", "").strip() 
                        if not actual_filename:
                            actual_filename = f"bizinfo_attachment_{len(downloaded_files)}.file"
                            
                    actual_filename = sanitize_folder_name(actual_filename)
                    
                    final_save_path = os.path.join(opportunity_dir, actual_filename)
                    await download.save_as(final_save_path)
                    
                    item["attachments"].append({"file_name": actual_filename, "url": detail_url})
                    downloaded_files.add(href)
                    print(f"    [Task {index}] [+] Downloaded: {actual_filename}")
                except Exception as e:
                    print(f"    [Task {index}] [!] Failed to download file at {href}: {e}")
            except Exception:
                continue
                
        history_set.add(bid_id)
        
    except Exception as e:
        print(f"    [Task {index}] [!] Error processing {bid_id}: {e}")
    finally:
        json_path = os.path.join(opportunity_dir, "metadata.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(item, f, ensure_ascii=False, indent=2)
            
        await page.close()


async def scrape_bizinfo(keyword: str, headless: bool):
    os.makedirs(BASE_DIR, exist_ok=True)
    scraped_history = load_scraped_history()
    target_date_str = datetime.now().strftime("%Y-%m-%d") # Bizinfo format
    print(f"[*] Starting Bizinfo daily run for date: {target_date_str} with keyword: '{keyword}'")
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context(
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            viewport={'width': 1400, 'height': 900},
            accept_downloads=True
        )
        
        main_page = await context.new_page()
        print('[*] Navigating to Bizinfo support projects portal...')
        await main_page.goto(BIZINFO_SEARCH_URL, wait_until='networkidle')
        await main_page.wait_for_timeout(3000)
        
        # Inject search keyword into the main search bar and submit
        await main_page.evaluate(f'''
            const searchInput = document.querySelector('input[title*="검색"], input[name*="srch"]');
            if (searchInput) {{
                searchInput.value = '{keyword}';
                const form = searchInput.closest('form');
                if (form) form.submit();
            }}
        ''')
        
        print('[*] Waiting for search results...')
        await main_page.wait_for_timeout(5000)
        
        # Parse standard HTML table rows
        rows = await main_page.locator("table tbody tr").all()
        opportunities = []
        
        for i, row in enumerate(rows):
            try:
                columns = await row.locator("td").all()
                if len(columns) < 5: 
                    continue # Skip empty/malformed rows
                
                # Column mapping depends on current Bizinfo layout (usually: Org, Title, Status, Date)
                org_text = (await columns[1].inner_text()).strip()
                title_elem = columns[2].locator("a").first
                title_text = (await title_elem.inner_text()).strip()
                date_text = (await columns[-1].inner_text()).strip()
                
                # Bizinfo URLs are usually relative hrefs
                href = await title_elem.get_attribute("href")
                full_url = f"https://www.bizinfo.go.kr{href}" if href.startswith("/") else href
                
                # Extract an ID from the URL (usually a sequence number)
                bid_id_match = re.search(r'pblancId=([^&]+)', full_url)
                bid_id = bid_id_match.group(1) if bid_id_match else f"BIZ_{datetime.now().strftime('%Y%m%d')}_{i}"
                
                # Check history
                if bid_id in scraped_history:
                    print(f"[-] Skipping {bid_id} - Already scraped.")
                    continue
                    
                opportunities.append({
                    "bid_id": bid_id,
                    "title": title_text,
                    "organization": org_text,
                    "posting_date": date_text,
                    "url": full_url,
                    "raw_text_description": "",
                    "attachments": []
                })
            except Exception as e:
                continue
        
        await main_page.close()
        
        if not opportunities:
            print("[*] No new Bizinfo opportunities found. Exiting.")
        else:
            print(f"\n[*] Found {len(opportunities)} NEW Bizinfo results. Dispatching workers...")
            tasks = [
                process_bizinfo_opportunity(context, item, idx + 1, len(opportunities), scraped_history) 
                for idx, item in enumerate(opportunities)
            ]
            await asyncio.gather(*tasks)
            save_scraped_history(scraped_history)

        await browser.close()
        print("\n[+] Bizinfo Scraping Complete!")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Bizinfo Scraper Adapter")
    parser.add_argument("--keyword", type=str, default="AI", help="Search keyword")
    parser.add_argument("--headless", action="store_true", help="Run browser in background")
    args = parser.parse_args()
    
    asyncio.run(scrape_bizinfo(keyword=args.keyword, headless=args.headless))