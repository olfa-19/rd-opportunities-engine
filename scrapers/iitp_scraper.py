import os
import json
import re
import asyncio
import argparse
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup

# --- CONFIGURATION ---
BASE_DIR = os.path.join(os.getcwd(), "IITP")
HISTORY_FILE = os.path.join(BASE_DIR, "scraped_ids.json")
LIST_URL = "https://www.iitp.kr/web/lay1/bbs/S1T12C38/A/8/list.do"
DETAIL_URL_TEMPLATE = "https://www.iitp.kr/web/lay1/bbs/S1T12C38/A/8/view.do?article_seq={}"

CONCURRENCY_LIMIT = asyncio.Semaphore(2)

def load_scraped_history() -> set:
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r") as f:
            return set(json.load(f))
    return set()

def save_scraped_history(history_set: set):
    with open(HISTORY_FILE, "w") as f:
        json.dump(list(history_set), f)

def sanitize_folder_name(name: str) -> str:
    return re.sub(r'[\/:*?"<>|]', '_', name).strip()[:100]

# --- SCRAPE DETAIL PAGE ---
async def process_opportunity(context, opp_id, index, total, history_set):
    async with CONCURRENCY_LIMIT:
        detail_url = DETAIL_URL_TEMPLATE.format(opp_id)
        print(f"\n[{index}/{total}] Inspecting IITP Article ID: {opp_id}...")
        
        page = await context.new_page()
        page.on("dialog", lambda dialog: asyncio.create_task(dialog.accept()))
        
        try:
            await page.goto(detail_url, wait_until='domcontentloaded', timeout=45000)
            await page.wait_for_timeout(2000)
            
            html_content = await page.content()
            soup = BeautifulSoup(html_content, "html.parser")
            
            # Extract Title (IITP usually puts this in a strong tag or a specific header area)
            title = ""
            title_tag = soup.find('strong', class_='tit') or soup.find('h3') or soup.title
            if title_tag:
                title = title_tag.get_text(strip=True).replace("IITP", "").strip(" -|")
            if not title:
                title = f"IITP_Opportunity_{opp_id}"
            
            folder_name = sanitize_folder_name(f"[IITP_{opp_id}] {title}")
            opp_dir = os.path.join(BASE_DIR, folder_name)
            os.makedirs(opp_dir, exist_ok=True)
            
            # Extract Text Description (Cleaning up scripts/styles)
            for s in soup(["script", "style", "nav", "footer"]):
                s.extract()
            description = soup.get_text(separator="\n", strip=True)
            
            # Extract Date (Looking for standard YYYY-MM-DD formats)
            date_match = re.search(r'등록일자\s*[:\s]*([0-9]{4}-[0-9]{2}-[0-9]{2})', description)
            posting_date = date_match.group(1).strip() if date_match else "Date Not Found"

            # DOWNLOAD ATTACHMENTS
            print(f"    [*] Hunting for files...")
            attachments = []
            
            # IITP often uses hrefs with 'download' or explicit file extensions, or buttons saying '다운로드'
            download_links = await page.locator("a[href*='download'], a:has-text('다운로드'), a:has-text('첨부')").all()
            
            # Backup: Check for links with file extensions in the text
            if not download_links:
                 download_links = await page.locator("a").all()

            for link in download_links:
                try:
                    if await link.is_visible():
                        link_text = (await link.inner_text()).strip().lower()
                        href_val = await link.get_attribute('href') or ""
                        
                        # Trigger download if it looks like a file link
                        if "download" in href_val or "다운로드" in link_text or any(ext in link_text for ext in ['.hwp', '.hwpx', '.pdf', '.docx', '.xlsx', '.zip']):
                            async with page.expect_download(timeout=15000) as download_info:
                                await link.click(force=True)
                            
                            download = await download_info.value
                            file_name = download.suggested_filename or "attachment_file"
                            save_path = os.path.join(opp_dir, file_name)
                            await download.save_as(save_path)
                            attachments.append({"file_name": file_name})
                            print(f"    [+] Saved file: {file_name}")
                except Exception:
                    pass
            
            # Save Metadata
            meta_data = {
                "bid_id": opp_id,
                "title": title,
                "organization": "IITP",
                "posting_date": posting_date,
                "url": detail_url,
                "raw_text_description": description[:4000],
                "attachments": attachments
            }
            with open(os.path.join(opp_dir, "metadata.json"), "w", encoding="utf-8") as f:
                json.dump(meta_data, f, ensure_ascii=False, indent=2)
            
            print(f"    [✓] Processed and saved IITP/{folder_name}")
            history_set.add(opp_id)
            
        except Exception as e:
            print(f"    [!] Error processing {opp_id}: {e}")
        finally:
            await page.close()

# --- MAIN ENGINE ---
async def scrape_iitp_daily(headless: bool, force_all: bool = False):
    os.makedirs(BASE_DIR, exist_ok=True)
    scraped_history = load_scraped_history()
    
    print("[*] Starting IITP Scraper Engine...")
    found_ids = set()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context(
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            viewport={'width': 1400, 'height': 900},
            accept_downloads=True
        )
        page = await context.new_page()

        print("[*] Navigating to IITP Announcements List...")
        await page.goto(LIST_URL, wait_until="domcontentloaded", timeout=60000)
        
        # Wait for the table/list to load
        await page.wait_for_timeout(3000)
        html = await page.content()
        soup = BeautifulSoup(html, "html.parser")
        
        # Look for anchor tags with the class "tit" and extract article_seq
        announcements = soup.find_all('a', class_='tit')
        
        for anchor in announcements:
            href = anchor.get('href', '')
            match = re.search(r'article_seq=(\d+)', href)
            if match:
                found_ids.add(match.group(1))

        await page.close()

        if not found_ids:
            print("[!] No opportunities found on the main page.")
            await browser.close()
            return
        
        sorted_ids = sorted(list(found_ids), reverse=True)
        print(f"\n[+] Successfully detected {len(sorted_ids)} IITP opportunity IDs!")
        
        target_ids = []
        for pid in sorted_ids:
            if pid in scraped_history and not force_all:
                continue
            target_ids.append(pid)
        
        if not target_ids:
            print("[*] No new IITP items to scrape. Exiting.")
            await browser.close()
            return

        if len(target_ids) > 5:
            print(f"[*] Limiting run to the top 5 newest opportunities for testing...")
            target_ids = target_ids[:5]
        
        print(f"[*] Dispatching scrapers for {len(target_ids)} IITP opportunities...")
        
        tasks = [
            process_opportunity(context, opp_id, idx + 1, len(target_ids), scraped_history) 
            for idx, opp_id in enumerate(target_ids)
        ]
        
        await asyncio.gather(*tasks)
        save_scraped_history(scraped_history)

        await browser.close()
        print("\n[+] IITP Scraping Complete! Check Streamlit.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="IITP Daily Scraper")
    parser.add_argument("--headless", action="store_true", help="Run browser in background")
    args = parser.parse_args()
    
    # Run with force_all=True for initial testing
    asyncio.run(scrape_iitp_daily(headless=False, force_all=True))