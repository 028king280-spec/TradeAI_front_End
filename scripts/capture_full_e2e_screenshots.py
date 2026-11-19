import asyncio
import os
from playwright.async_api import async_playwright

async def run_e2e():
    os.makedirs("reports/e2e", exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 1440, "height": 900})
        page = await context.new_page()

        routes = [
            ("dashboard_overview", "http://localhost:3000/"),
            ("options_nifty", "http://localhost:3000/options/nifty"),
            ("options_sensex", "http://localhost:3000/options/sensex"),
            ("option_chain", "http://localhost:3000/option-chain"),
            ("performance", "http://localhost:3000/performance"),
        ]

        for name, url in routes:
            print(f"Navigating to {url}...")
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=25000)
                await page.wait_for_timeout(3000)
                path = f"reports/e2e/{name}.png"
                await page.screenshot(path=path, full_page=False)
                print(f"Captured {path}")
            except Exception as e:
                print(f"Error capturing {name}: {e}")

        await browser.close()
        print("E2E screenshot capture completed.")

if __name__ == "__main__":
    asyncio.run(run_e2e())
