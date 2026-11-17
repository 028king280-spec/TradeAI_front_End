import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1440, "height": 900})
        await page.goto("http://localhost:3000/alerts", wait_until="domcontentloaded")
        await asyncio.sleep(1)
        await page.fill("#whatsapp-number", "9812345678")
        await page.click('button:has-text("Add number")')
        await asyncio.sleep(1)
        await page.screenshot(path="reports/alerts_indian_number_verified.png", full_page=True)
        print("Indian 10-digit number test completed successfully!")
        await browser.close()

asyncio.run(main())
