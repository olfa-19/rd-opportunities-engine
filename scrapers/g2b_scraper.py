import os
import json
import re
import asyncio
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup

# Base directory for saving opportunities
BASE_DIR = os.path.join(os.getcwd(), "나라장터")

def sanitize_folder_name(name: str) -> str:
    """Removes invalid filesystem characters for folder/file creation."""
    sanitized = re.sub(r'[\/:*?"<>|]', '_', name)
    return sanitized.strip()[:100]

def parse_bid_info(raw_bid_no: str):
    """Extracts base bid number and order number."""
    if "-" in raw_bid_no:
        parts = raw_bid_no.split("-")
        return parts[0], parts[1].zfill(3)
    return raw_bid_no, "000"

async def process_opportunity(context, item, index, total):
    bid_no = item["bid_id"]
    title = item["title"]
    
    folder_name = sanitize_folder_name(f"[{bid_no}] {title}")
    opportunity_dir = os.path.join(BASE_DIR, folder_name)
    os.makedirs(opportunity_dir, exist_ok=True)
    
    print(f"\n[Task {index}/{total}] Starting processing for {bid_no} in background tab...")
    
    base_no, ord_no = parse_bid_info(bid_no)
    
    # Internal bot URL for direct DOM access
    bot_url = f"https://www.g2b.go.kr/link/PNPE027_01/single/?bidPbancNo={base_no}&bidPbancOrd={ord_no}"
    # Standard public URL for human reference in metadata
    public_url = f"https://www.g2b.go.kr:8081/ep/invitation/publish/bidInfoDtl.do?bidno={base_no}&bidseq={ord_no}"
    item["url"] = public_url 
    
    page = await context.new_page()
    
    # Automatically accept any native browser alert popups that ask "Do you want to download?"
    page.on("dialog", lambda dialog: asyncio.create_task(dialog.accept()))
    
    try:
        await page.goto(bot_url, wait_until='networkidle')
        await page.wait_for_timeout(6000) 
        
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
        
        # Method A: Find elements whose exact text ends with a file extension (WebSquare Grids)
        text_elements = await page.locator("text=/\.(hwp|hwpx|pdf|docx|xlsx|zip|cell)$/i").all()
        
        # Method B: Find standard download buttons as a fallback
        link_elements = await page.locator("a, button, span[onclick*='download']").all()
        
        all_elements = text_elements + link_elements
        
        for elem in all_elements:
            try:
                # Ensure the element is visible and not hidden behind a modal
                if not await elem.is_visible():
                    continue
                    
                text = (await elem.inner_text()).strip()
                if not text or text in downloaded_files:
                    continue
                    
                exts = ['.hwp', '.hwpx', '.pdf', '.docx', '.xlsx', '.zip', '.cell']
                
                # Check if it's a file by extension or contains download logic
                is_file = any(ext in text.lower() for ext in exts) or "download" in (await elem.get_attribute("onclick") or "").lower()
                
                if is_file and not any(k in text for k in ["사기 공문", "사칭문자", "수요물자"]):
                    try:
                        async with page.expect_download(timeout=8000) as download_info:
                            # Send strict mouse events to bypass WebSquare's custom click listeners
                            await elem.evaluate("""node => {
                                node.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
                                node.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
                                node.click();
                            }""")
                        
                        download = await download_info.value
                        actual_filename = download.suggested_filename
                        
                        if not actual_filename:
                            actual_filename = text if any(ext in text.lower() for ext in exts) else f"attachment_{len(downloaded_files)}.file"
                        
                        final_save_path = os.path.join(opportunity_dir, actual_filename)
                        await download.save_as(final_save_path)
                        
                        item["attachments"].append({
                            "file_name": actual_filename,
                            "url": public_url
                        })
                        downloaded_files.add(text)
                        print(f"    [Task {index}] [+] Downloaded attachment: {actual_filename}")
                    except Exception:
                        # Timeout means it wasn't a real download trigger, silently move to next
                        pass
            except Exception:
                pass
                
    finally:
        json_path = os.path.join(opportunity_dir, "metadata.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(item, f, ensure_ascii=False, indent=2)
        print(f"    [Task {index}] [+] Saved metadata.json")
        
        await page.close()


async def scrape_g2b_spa_full(keyword: str = "AI", max_results: int = 3):
    os.makedirs(BASE_DIR, exist_ok=True)
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            viewport={'width': 1400, 'height': 900},
            accept_downloads=True
        )
        
        main_page = await context.new_page()
        
        print('[*] Navigating to G2B main portal...')
        await main_page.goto('https://www.g2b.go.kr/', wait_until='networkidle')
        await main_page.wait_for_timeout(4000)
        
        await main_page.keyboard.press("Escape")
        await main_page.wait_for_timeout(500)
        
        print(f'[*] Injecting keyword "{keyword}"...')
        await main_page.evaluate(f'''
            const searchInput = document.getElementById('mf_wfm_gnb_wfm_gnbBtm_inpGlobalSearch');
            if (searchInput) searchInput.value = '{keyword}';
        ''')
        
        print('[*] Triggering search...')
        await main_page.evaluate('''
            const searchBtn = document.getElementById('mf_wfm_gnb_wfm_gnbBtm_btnGlobalSearch');
            if (searchBtn) searchBtn.click();
        ''')
        
        print('[*] Waiting for search results to load...')
        await main_page.wait_for_timeout(10000)
        
        title_locators = await main_page.locator("label[id$='_bizNm']").all()
        bid_nos = await main_page.locator("label[id$='_bizNo']").all()
        agencies = await main_page.locator("label[id$='_dmstUntyGrpNm']").all()
        dates = await main_page.locator("label[id$='_pbancPstgDt']").all()
        
        valid_count = min(len(title_locators), max_results)
        print(f"\n[*] Found results. Queueing top {valid_count} opportunities...")
        
        opportunities = []
        for i in range(valid_count):
            title_text = (await title_locators[i].inner_text()).strip()
            bid_no = (await bid_nos[i].inner_text()).strip() if i < len(bid_nos) else f"UNKNOWN_{i}"
            agency = (await agencies[i].inner_text()).strip() if i < len(agencies) else ""
            date = (await dates[i].inner_text()).strip() if i < len(dates) else ""
            
            opportunities.append({
                "bid_id": bid_no,
                "title": title_text,
                "organization": agency,
                "posting_date": date,
                "url": "",
                "raw_text_description": "",
                "attachments": []
            })
        
        await main_page.close()
        
        tasks = [
            process_opportunity(context, item, idx + 1, valid_count) 
            for idx, item in enumerate(opportunities)
        ]
        
        await asyncio.gather(*tasks)

        await browser.close()
        print(f"\n[+] Scraping Complete! Successfully processed {valid_count} opportunities concurrently.")

if __name__ == "__main__":
    asyncio.run(scrape_g2b_spa_full(keyword="AI", max_results=3))