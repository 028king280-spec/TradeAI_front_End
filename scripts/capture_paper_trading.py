import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1400, "height": 1100})
        page.on("console", lambda msg: print(f"PAGE LOG: {msg.text}"))
        await page.goto("http://localhost:3000", wait_until="domcontentloaded", timeout=20000)
        await page.wait_for_timeout(3000)
        
        # Click Paper trading tab
        tab = page.locator("button:has-text('Paper trading'), button:has-text('Paper Trading')").first
        if await tab.is_visible():
            await tab.click()
            await page.wait_for_timeout(3000)
            print("Clicked Paper trading tab")

        # Click Refresh Live CMP button to trigger sync
        refresh_btn = page.locator("button:has-text('Refresh Live CMP')").first
        if await refresh_btn.is_visible():
            await refresh_btn.click()
            await page.wait_for_timeout(3000)
            print("Clicked Refresh Live CMP button in UI")
        
        await page.screenshot(path="reports/paper_trading_position_verified.png", full_page=True)
        print("Paper trading page screenshot saved to reports/paper_trading_position_verified.png")
        print("Paper trading page screenshot saved to reports/paper_trading_position_verified.png")
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())

