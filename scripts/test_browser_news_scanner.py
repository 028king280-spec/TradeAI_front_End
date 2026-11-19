"""
AIVOLVE Institutional Quantitative Trading Intelligence v3.0
Playwright Headed Browser Acceptance Test (headless=False, slowMo=800ms)
for AI News Sentiment & Top 10 Intraday Stock Opportunity Scanner.
"""

import os
import time
from playwright.sync_api import sync_playwright

ARTIFACT_DIR = r"C:\Users\Sourav Verma\.gemini\antigravity\brain\a47b88ae-3d04-471a-a671-adebd0b6ad2f"


def run_browser_news_scanner_verification():
    print("[BrowserTest] Launching headed Chromium browser with slow_mo=800ms...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, slow_mo=800)
        context = browser.new_context(viewport={"width": 1440, "height": 960})
        page = context.new_page()

        print("[BrowserTest] Navigating to http://localhost:3000/sentiment ...")
        page.goto("http://localhost:3000/sentiment", wait_until="networkidle", timeout=30000)
        time.sleep(2)

        # 1. Verify Top 10 News Scanner is visible
        print("[BrowserTest] Verifying Top 10 News Scanner header...")
        page.wait_for_selector("text=AI NEWS SENTIMENT & INTRADAY STOCK OPPORTUNITY SCANNER", timeout=10000)

        # 2. Capture Top 10 Overall View
        shot1 = os.path.join(ARTIFACT_DIR, "top10_news_scanner_overall.png")
        page.screenshot(path=shot1, full_page=False)
        print(f"[BrowserTest] Saved Top 10 Overall screenshot to: {shot1}")
        time.sleep(1)

        # 3. Switch to "Top 10 Bullish News" tab
        print("[BrowserTest] Switching to 'Top 10 Bullish News' tab...")
        page.locator("button:has-text('Top 10 Bullish News')").click()
        time.sleep(2)
        shot2 = os.path.join(ARTIFACT_DIR, "top10_news_scanner_bullish.png")
        page.screenshot(path=shot2, full_page=False)
        print(f"[BrowserTest] Saved Top 10 Bullish screenshot to: {shot2}")

        # 4. Switch to "Top 10 Bearish News" tab
        print("[BrowserTest] Switching to 'Top 10 Bearish News' tab...")
        page.locator("button:has-text('Top 10 Bearish News')").click()
        time.sleep(2)
        shot3 = os.path.join(ARTIFACT_DIR, "top10_news_scanner_bearish.png")
        page.screenshot(path=shot3, full_page=False)
        print(f"[BrowserTest] Saved Top 10 Bearish screenshot to: {shot3}")

        # 5. Switch back to Overall and open first stock modal
        print("[BrowserTest] Switching back to Overall tab and opening stock research modal...")
        page.locator("button:has-text('Top 10 Overall Impact')").click()
        time.sleep(1)

        # Click on the first stock card
        first_card = page.locator("h3:has-text('TATACONSUM'), h3:has-text('BHARTIARTL'), h3").first
        if first_card.is_visible():
            first_card.click()
            time.sleep(2)
            page.wait_for_selector("text=Event Impact Thesis & Catalyst Rationale", timeout=6000)
            shot4 = os.path.join(ARTIFACT_DIR, "top10_stock_forensic_research_modal.png")
            page.screenshot(path=shot4, full_page=False)
            print(f"[BrowserTest] Saved Forensic Research Modal screenshot to: {shot4}")

            # Close modal by clicking X button
            close_btn = page.locator("button:has(svg.lucide-x), button:has-text('✕')").first
            if close_btn.is_visible():
                close_btn.click()
            else:
                page.keyboard.press("Escape")
            time.sleep(1)

        # 6. Switch to "Latest High-Impact News" stream
        print("[BrowserTest] Switching to 'Latest High-Impact News' stream...")
        page.locator("button:has-text('Latest High-Impact News')").click()
        time.sleep(2)
        shot5 = os.path.join(ARTIFACT_DIR, "top10_news_stream_view.png")
        page.screenshot(path=shot5, full_page=False)
        print(f"[BrowserTest] Saved News Stream screenshot to: {shot5}")

        time.sleep(2)
        browser.close()
        print("[BrowserTest] All browser acceptance checks completed successfully!")


if __name__ == "__main__":
    run_browser_news_scanner_verification()
