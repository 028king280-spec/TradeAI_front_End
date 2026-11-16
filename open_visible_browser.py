import time
import sys
from playwright.sync_api import sync_playwright

def run_visible_session():
    print("=== LAUNCHING VISIBLE CHROMIUM BROWSER WINDOW ===")
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            slow_mo=600,
            args=["--start-maximized"]
        )
        context = browser.new_context(no_viewport=True)
        page = context.new_page()

        print("[1/5] Navigating to AIVOLVE Dashboard (http://localhost:3000)...")
        page.goto("http://localhost:3000", wait_until="networkidle")
        page.wait_for_timeout(2000)

        # Demonstrate live dashboard interaction
        print("[2/5] Switching active index to BANK NIFTY...")
        bank_card = page.locator("text=BANK NIFTY").first
        if bank_card.is_visible():
            bank_card.click()
            page.wait_for_timeout(2000)

        print("[3/5] Switching back to NIFTY 50...")
        nifty_card = page.locator("text=NIFTY 50").first
        if nifty_card.is_visible():
            nifty_card.click()
            page.wait_for_timeout(2000)

        print("[4/5] Opening Paper Trading Cockpit (http://localhost:3000/paper-trading)...")
        page.goto("http://localhost:3000/paper-trading", wait_until="networkidle")
        page.wait_for_timeout(3000)

        print("[5/5] Returning to Main Dashboard (http://localhost:3000)...")
        page.goto("http://localhost:3000", wait_until="networkidle")
        
        print("=== BROWSER IS LIVE & RUNNING ON DESKTOP ===")
        print("Holding session open for live user observation...")
        # Keep open for 2 minutes for the user to interact
        time.sleep(120)
        browser.close()

if __name__ == "__main__":
    run_visible_session()

