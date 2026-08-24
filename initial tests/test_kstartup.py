import os
import json
import re
import asyncio
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup

BASE_DIR = os.path.join(os.getcwd(), "K-Startup")
DETAIL_URL_TEMPLATE = "https://www.k-startup.go.kr/web/contents/bizpbanc-ongoing.do?schM=view&pbancSn={}"

def sanitize_folder_name(name: str) -> str:
    sanitized = re.sub(r'[\/:*?"<>|]', '_', name)
    return sanitized.strip()[:100]

async def test_scrape_kstartup():
    os.makedirs(BASE_DIR, exist_ok=True)
    print("[*] Launching browser to test K-Startup scraping...")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            viewport={'width': 1400, 'height': 900},
            accept_downloads=True
        )
        page = await context.new_page()

        print("[*] Navigating to K-Startup announcements list...")
        await page.goto("https://www.k-startup.go.kr/web/contents/bizpbanc-ongoing.do", wait_until="domcontentloaded")
        
        print("[*] Waiting for card elements to render...")
        await page.wait_for_timeout(5000)

        # Scroll to trigger any lazy-rendered cards
        await page.evaluate("window.scrollTo(0, 500)")
        await page.wait_for_timeout(1000)

        # Retrieve full DOM HTML directly into Python
        html_content = await page.content()
        
        # Extract pbancSn opportunity IDs directly using Python regex
        raw_ids = re.findall(r'pbancSn[=:]\s*["\']?(\d+)', html_content)
        found_ids = list(dict.fromkeys(raw_ids))
        
        found_items = []
        soup = BeautifulSoup(html_content, "html.parser")

        # Map each extracted ID to its corresponding title on the page
        for pbanc_sn in found_ids:
            # Look for anchor/element associated with this ID
            element = soup.find(lambda tag: tag.has_attr('href') and f"pbancSn={pbanc_sn}" in tag['href']) or \
                      soup.find(lambda tag: tag.has_attr('onclick') and f"pbancSn={pbanc_sn}" in tag['onclick'])
            
            title = ""
            if element:
                title = element.get_text(strip=True)
            
            # Fallback title search inside parent card containers
            if not title or len(title) < 3:
                for card in soup.find_all(['div', 'li', 'a']):
                    card_str = str(card)
                    if f"pbancSn={pbanc_sn}" in card_str or pbanc_sn in card_str:
                        lines = [l.strip() for l in card.get_text(separator=" ", strip=True).split("  ") if len(l.strip()) > 10]
                        if lines:
                            title = lines[0]
                            break

            if not title:
                title = f"K-Startup Opportunity {pbanc_sn}"

            found_items.append({
                "id": pbanc_sn,
                "title": title,
                "url": DETAIL_URL_TEMPLATE.format(pbanc_sn)
            })

        print(f"\n[+] Extracted {len(found_items)} unique opportunities from K-Startup!\n")

        if not found_items:
            print("[!] No items matched. Saving HTML snapshot for debugging...")
            with open("debug_kstartup.html", "w", encoding="utf-8") as f:
                f.write(html_content)
            await browser.close()
            return

        # Display detected list
        for idx, item in enumerate(found_items[:5], 1):
            print(f"{idx}. ID: {item['id']} | Title: {item['title'][:60]}")

        print("\n[*] Starting detailed download & metadata processing for top items...\n")

        # Process top 3 items
        test_items = found_items[:3]
        for idx, item in enumerate(test_items, 1):
            opp_id = item["id"]
            title = item["title"]
            detail_url = item["url"]

            print(f"[{idx}/{len(test_items)}] Scraping Opportunity ID {opp_id}...")
            print(f"    Title: {title[:50]}")
            
            folder_name = sanitize_folder_name(f"[K-Startup_{opp_id}] {title}")
            opp_dir = os.path.join(BASE_DIR, folder_name)
            os.makedirs(opp_dir, exist_ok=True)

            detail_page = await context.new_page()
            detail_page.on("dialog", lambda dialog: asyncio.create_task(dialog.accept()))

            try:
                await detail_page.goto(detail_url, wait_until="domcontentloaded", timeout=45000)
                await detail_page.wait_for_timeout(3000)

                # Extract Full Text Content
                detail_html = await detail_page.content()
                detail_soup = BeautifulSoup(detail_html, "html.parser")
                for s in detail_soup(["script", "style"]):
                    s.extract()
                description = detail_soup.get_text(separator="\n", strip=True)

                # Extract Attachments
                attachments = []
                download_links = await detail_page.locator("a[href*='download'], a[href*='file'], a.btn_down, button[onclick*='file']").all()

                for d_link in download_links:
                    try:
                        if await d_link.is_visible():
                            file_text = (await d_link.inner_text()).strip() or "attachment"
                            if any(ext in file_text.lower() for ext in ['.hwp', '.hwpx', '.pdf', '.docx', '.xlsx', '.zip', '.ppt']):
                                async with detail_page.expect_download(timeout=10000) as download_info:
                                    await d_link.click()
                                download = await download_info.value
                                file_name = download.suggested_filename or file_text
                                save_path = os.path.join(opp_dir, file_name)
                                await download.save_as(save_path)
                                attachments.append({"file_name": file_name})
                                print(f"    [+] Saved file: {file_name}")
                    except Exception:
                        pass

                # Save metadata.json
                meta_data = {
                    "bid_id": opp_id,
                    "title": title,
                    "organization": "K-Startup",
                    "posting_date": "Page 1 Test",
                    "url": detail_url,
                    "raw_text_description": description[:4000],
                    "attachments": attachments
                }

                with open(os.path.join(opp_dir, "metadata.json"), "w", encoding="utf-8") as f:
                    json.dump(meta_data, f, ensure_ascii=False, indent=2)

                print(f"    [✓] Saved metadata.json in K-Startup/{folder_name}\n")

            except Exception as e:
                print(f"    [!] Error processing {opp_id}: {e}")
            finally:
                await detail_page.close()

        await browser.close()
        print("[+] Test completed successfully!")

if __name__ == "__main__":
    asyncio.run(test_scrape_kstartup())