import asyncio
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup

async def scrape_g2b_spa():
    async with async_playwright() as p:
        # Launching browser
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            viewport={'width': 1400, 'height': 900}
        )
        page = await context.new_page()
        
        print('[*] Navigating to G2B main portal...')
        await page.goto('https://www.g2b.go.kr/', wait_until='networkidle')
        
        print('[*] Waiting 4 seconds for page to initialize...')
        await page.wait_for_timeout(4000)
        
        print('[*] Injecting keyword "AI" directly via JavaScript...')
        await page.evaluate('''
            const searchInput = document.getElementById('mf_wfm_gnb_wfm_gnbBtm_inpGlobalSearch');
            if (searchInput) {
                searchInput.value = 'AI';
            }
        ''')
        
        print('[*] Triggering search click directly via JavaScript...')
        await page.evaluate('''
            const searchBtn = document.getElementById('mf_wfm_gnb_wfm_gnbBtm_btnGlobalSearch');
            if (searchBtn) {
                searchBtn.click();
            }
        ''')
        
        print('[*] Waiting 10 seconds for results to load...')
        await page.wait_for_timeout(10000)
        
        print('[*] Extracting and parsing data...')
        html = await page.content()
        soup = BeautifulSoup(html, 'html.parser')
        
        # Use CSS selectors to find elements whose IDs end with the specific data tags
        titles = soup.select("label[id$='_bizNm']")
        bid_nos = soup.select("label[id$='_bizNo']")
        agencies = soup.select("label[id$='_dmstUntyGrpNm']") # Demand Agency
        dates = soup.select("label[id$='_pbancPstgDt']")      # Posting Date
        
        print("\n" + "="*60)
        print(" G2B SEARCH RESULTS: 'AI'")
        print("="*60)
        
        # Loop through the extracted lists and print them
        for i in range(len(titles)):
            title = titles[i].text.strip()
            # Safely grab the corresponding data, default to "N/A" if missing
            bid_no = bid_nos[i].text.strip() if i < len(bid_nos) else "N/A"
            agency = agencies[i].text.strip() if i < len(agencies) else "N/A"
            date = dates[i].text.strip() if i < len(dates) else "N/A"
            
            print(f"Bid Number : {bid_no}")
            print(f"Title      : {title}")
            print(f"Agency     : {agency}")
            print(f"Date       : {date}")
            print("-" * 60)
            
        print('[+] Scraping Complete!')
        await browser.close()

if __name__ == "__main__":
    asyncio.run(scrape_g2b_spa())