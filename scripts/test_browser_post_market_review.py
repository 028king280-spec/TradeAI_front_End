"""
AIVOLVE Institutional Quantitative Trading Intelligence v3.0
Playwright Visible Browser Test (Headless=False, SlowMo=800) for Daily AI Trade Review UI.
"""

import os
import time
from playwright.sync_api import sync_playwright

ARTIFACT_DIR = r"C:\Users\Sourav Verma\.gemini\antigravity\brain\a47b88ae-3d04-471a-a671-adebd0b6ad2f"


def run_browser_verification():
    print("[BrowserTest] Launching headed Chromium browser with slow_mo=800ms...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, slow_mo=800)
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()

        print("[BrowserTest] Navigating to http://localhost:3000/paper-trading ...")
        page.goto("http://localhost:3000/paper-trading", wait_until="networkidle", timeout=30000)
        time.sleep(2)

        # Click on "Daily AI Trade Review" tab
        print("[BrowserTest] Clicking on 'Daily AI Trade Review' tab...")
        tab_btn = page.get_by_role("button", name="Daily AI Trade Review")
        if tab_btn.is_visible():
            tab_btn.click()
        else:
            page.locator("button:has-text('Daily AI Trade Review')").click()

        time.sleep(2)

        # Verify header is present
        print("[BrowserTest] Verifying review header and cards...")
        page.wait_for_selector("text=DAILY AI TRADE PROFIT/LOSS FORENSIC REVIEW", timeout=10000)

        # Capture Screenshot of the Daily Review Dashboard
        shot1_path = os.path.join(ARTIFACT_DIR, "daily_ai_trade_review_dashboard.png")
        page.screenshot(path=shot1_path, full_page=False)
        print(f"[BrowserTest] Saved dashboard screenshot to: {shot1_path}")

        # Click on the first "Why Won/Lost?" button
        print("[BrowserTest] Clicking 'Why Won/Lost?' on first trade...")
        why_btn = page.locator("button:has-text('Why Won/Lost?')").first
        if why_btn.is_visible():
            why_btn.click()
            time.sleep(2)

            # Wait for modal
            page.wait_for_selector("text=FORENSIC TRADE AUDIT", timeout=5000)
            shot2_path = os.path.join(ARTIFACT_DIR, "daily_ai_trade_forensic_modal.png")
            page.screenshot(path=shot2_path, full_page=False)
            print(f"[BrowserTest] Saved forensic modal screenshot to: {shot2_path}")

        time.sleep(3)
        browser.close()
        print("[BrowserTest] Test successfully completed!")


if __name__ == "__main__":
    run_browser_verification()
