import os
import json
import re
import asyncio
import argparse
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup

# --- CONFIGURATION ---
BASE_DIR = os.path.join(os.getcwd(), "K-Startup")
HISTORY_FILE = os.path.join(BASE_DIR, "scraped_ids.json")
DETAIL_URL_TEMPLATE = "https://www.k-startup.go.kr/web/contents/bizpbanc-ongoing.do?schM=view&pbancSn={}"

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
        print(f"\n[{index}/{total}] Inspecting Opportunity ID: {opp_id}...")
        
        page = await context.new_page()
        page.on("dialog", lambda dialog: asyncio.create_task(dialog.accept()))
        
        try:
            await page.goto(detail_url, wait_until='domcontentloaded', timeout=45000)
            await page.wait_for_timeout(3000)
            
            # 1. SCROLL TO BOTTOM TO REVEAL ATTACHMENTS
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(2000)

            html_content = await page.content()
            soup = BeautifulSoup(html_content, "html.parser")
            
            # Extract Title
            title_tag = soup.select_one('.board_view_tit, .view_tit, h2.title, h3.title')
            if title_tag:
                title = title_tag.get_text(strip=True)
            else:
                title = soup.title.get_text(strip=True) if soup.title else f"Opportunity_{opp_id}"
            
            title = title.replace("K-Startup", "").replace("사업공고", "").strip(" -|")
            
            folder_name = sanitize_folder_name(f"[K-Startup_{opp_id}] {title}")
            opp_dir = os.path.join(BASE_DIR, folder_name)
            os.makedirs(opp_dir, exist_ok=True)
            
            # Extract Text Description
            for s in soup(["script", "style"]):
                s.extract()
            description = soup.get_text(separator="\n", strip=True)
            
            # Extract Organization & Posting Date
            org_match = re.search(r'(소관부처|주관기관|전문기관)\s*[:\s]\s*([^\n]+)', description)
            org = org_match.group(2).strip() if org_match else "K-Startup"

            date_match = re.search(r'(공고기간|접수기간|등록일)\s*[:\s]\s*([0-9\.\-\~\s]+)', description)
            posting_date = date_match.group(2).strip() if date_match else "See Details"

            # 2. DOWNLOAD ATTACHMENTS
            print(f"    [*] Hunting for files at bottom of page...")
            attachments = []
            
            # Target all '다운로드' buttons (excluding '바로보기' preview buttons)
            download_btns = await page.locator("a:has-text('다운로드'), button:has-text('다운로드')").all()

            for btn in download_btns:
                try:
                    btn_text = (await btn.inner_text()).strip()
                    # Skip '일괄 다운로드' if we are doing individual files, or process individual buttons
                    if "다운로드" in btn_text and "일괄" not in btn_text:
                        if await btn.is_visible():
                            async with page.expect_download(timeout=15000) as download_info:
                                await btn.click(force=True)
                            download = await download_info.value
                            file_name = download.suggested_filename
                            save_path = os.path.join(opp_dir, file_name)
                            await download.save_as(save_path)
                            attachments.append({"file_name": file_name})
                            print(f"    [+] Saved file: {file_name}")
                except Exception as e:
                    pass
            
            # Save Metadata
            meta_data = {
                "bid_id": opp_id,
                "title": title,
                "organization": org,
                "posting_date": posting_date,
                "url": detail_url,
                "raw_text_description": description[:4000],
                "attachments": attachments
            }
            with open(os.path.join(opp_dir, "metadata.json"), "w", encoding="utf-8") as f:
                json.dump(meta_data, f, ensure_ascii=False, indent=2)
            
            print(f"    [✓] Processed and saved K-Startup/{folder_name}")
            history_set.add(opp_id)
            
        except Exception as e:
            print(f"    [!] Error processing {opp_id}: {e}")
        finally:
            await page.close()

# --- MAIN ENGINE ---
async def scrape_kstartup_daily(headless: bool, force_all: bool = False):
    os.makedirs(BASE_DIR, exist_ok=True)
    scraped_history = load_scraped_history()
    
    print("[*] Starting K-Startup Scraper Engine...")
    found_ids = set()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context(
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            viewport={'width': 1400, 'height': 900},
            accept_downloads=True
        )
        page = await context.new_page()

        print("[*] Navigating to K-Startup...")
        await page.goto("https://www.k-startup.go.kr/web/contents/bizpbanc-ongoing.do", wait_until="networkidle", timeout=60000)
        
        await page.wait_for_timeout(5000)
        
        html = await page.content()
        
        matches = re.findall(r'go_view\([\'"]?(\d+)[\'"]?\)', html)
        for m in matches:
            found_ids.add(m)

        await page.close()

        if not found_ids:
            print("[!] No opportunities found. Check your connection.")
            await browser.close()
            return
        
        sorted_ids = sorted(list(found_ids), reverse=True)
        print(f"\n[+] Successfully detected {len(sorted_ids)} opportunity IDs!")
        
        target_ids = []
        for pid in sorted_ids:
            if pid in scraped_history and not force_all:
                continue
            target_ids.append(pid)
        
        if not target_ids:
            print("[*] No new items to scrape. Exiting.")
            await browser.close()
            return

        if len(target_ids) > 5:
            print(f"[*] Limiting run to the top 5 newest opportunities...")
            target_ids = target_ids[:5]
        
        print(f"[*] Dispatching scrapers for {len(target_ids)} opportunities...")
        
        tasks = [
            process_opportunity(context, opp_id, idx + 1, len(target_ids), scraped_history) 
            for idx, opp_id in enumerate(target_ids)
        ]
        
        await asyncio.gather(*tasks)
        save_scraped_history(scraped_history)

        await browser.close()
        print("\n[+] Scraping Complete! Check Streamlit.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="K-Startup Daily Scraper")
    parser.add_argument("--headless", action="store_true", help="Run browser in background")
    args = parser.parse_args()
    
    asyncio.run(scrape_kstartup_daily(headless=False, force_all=True))