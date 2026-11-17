import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1400, "height": 1200})
        await page.goto("http://localhost:3000", wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(3000)
        
        # Click Outlook tab
        outlook_btn = page.locator("button:has-text('Outlook')").first
        if await outlook_btn.is_visible():
            await outlook_btn.click()
            await page.wait_for_timeout(2000)
            print("Clicked Outlook tab")
        
        card = page.locator("text=NEXT-SESSION OPTIONS RECOMMENDATION").first
        if await card.is_visible():
            container = card.locator("xpath=ancestor::div[contains(@class, 'rounded-2xl')]").first
            await container.scroll_into_view_if_needed()
            await page.wait_for_timeout(1000)
            await container.screenshot(path="reports/next_session_pricing_verified.png")
            print("Card container screenshot saved to reports/next_session_pricing_verified.png")
        else:
            await page.screenshot(path="reports/next_session_pricing_verified.png", full_page=True)
            print("Full page screenshot saved")
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
