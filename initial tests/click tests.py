import asyncio
from playwright.async_api import async_playwright

async def debug_g2b_click():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()

        # Monitor if ANY new tab or internal navigation happens
        context.on("page", lambda new_page: print(f"\n[EVENT] A new tab opened! URL: {new_page.url}"))
        page.on("framenavigated", lambda frame: print(f"\n[EVENT] Navigation happened: {frame.url}") if frame == page.main_frame else None)

        print("[*] Navigating to G2B...")
        await page.goto("https://www.g2b.go.kr/", wait_until="networkidle")
        await page.wait_for_timeout(3000)
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(500)

        print("[*] Searching for 'AI'...")
        await page.evaluate('''
            const searchInput = document.getElementById('mf_wfm_gnb_wfm_gnbBtm_inpGlobalSearch');
            if (searchInput) searchInput.value = 'AI';
            const searchBtn = document.getElementById('mf_wfm_gnb_wfm_gnbBtm_btnGlobalSearch');
            if (searchBtn) searchBtn.click();
        ''')

        print("[*] Waiting for results to load...")
        await page.wait_for_timeout(8000)

        # Get the first result's label
        title_label = page.locator("label[id$='_bizNm']").first
        
        try:
            await title_label.wait_for(state="visible", timeout=10000)
            
            # 1. Print the HTML structure of the row
            html = await title_label.evaluate("node => node.closest('tr') ? node.closest('tr').outerHTML : node.closest('td').outerHTML")
            print("\n========== ROW HTML ==========")
            print(html)
            print("==============================\n")
            
            # 2. Try an aggressive bounding-box click on the parent cell
            print("[*] Attempting native browser click on the parent cell...")
            parent_cell = title_label.locator("..")
            await parent_cell.click(force=True)
            
        except Exception as e:
            print(f"Error finding the element: {e}")

        print("[*] Waiting 5 seconds to observe browser behavior...")
        await page.wait_for_timeout(5000)

        await browser.close()
        print("[*] Debug complete.")

if __name__ == "__main__":
    asyncio.run(debug_g2b_click())