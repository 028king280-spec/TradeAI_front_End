import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1440, "height": 900})
        await page.goto("http://localhost:3000/alerts", wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(2)
        await page.screenshot(path="reports/alerts_page_verified.png", full_page=True)
        print("Alerts page screenshot saved to reports/alerts_page_verified.png")
        await browser.close()

asyncio.run(main())

