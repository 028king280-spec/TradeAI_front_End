import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1400, "height": 1100})
        await page.goto("http://localhost:3000", wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(2000)
        
        # Click Paper trading tab
        tab = page.locator("button:has-text('Paper trading'), button:has-text('Paper Trading')").first
        if await tab.is_visible():
            await tab.click()
            await page.wait_for_timeout(2000)
            print("Clicked Paper trading tab")
        
        await page.screenshot(path="reports/paper_trading_position_verified.png", full_page=True)
        print("Paper trading page screenshot saved to reports/paper_trading_position_verified.png")
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
