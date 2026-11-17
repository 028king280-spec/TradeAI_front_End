import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1440, "height": 900})
        await page.goto("http://localhost:3000/alerts", wait_until="domcontentloaded")
        await asyncio.sleep(1)
        await page.fill("#whatsapp-number", "+919876543210")
        await page.click('button:has-text("Add number")')
        await asyncio.sleep(1)
        await page.screenshot(path="reports/alerts_page_number_added.png", full_page=True)
        print("Number added and screenshot saved successfully!")
        await browser.close()

asyncio.run(main())

