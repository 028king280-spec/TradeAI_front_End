import os
import time
from playwright.sync_api import sync_playwright

artifact_dir = r"C:\Users\Sourav Verma\.gemini\antigravity\brain\a47b88ae-3d04-471a-a671-adebd0b6ad2f"
os.makedirs(artifact_dir, exist_ok=True)
chrome_path = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

def run_qa():
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=chrome_path, headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()

        # Enable console and network error logging
        page.on("console", lambda msg: print(f"[Browser Console] {msg.type}: {msg.text}") if msg.type in ("error", "warning") else None)

        print("\n=================== 1. NAVIGATING TO /sentiment ===================")
        page.goto("http://localhost:3000/sentiment", wait_until="networkidle")
        time.sleep(2)

        # Switch to Stock Calculator view
        stock_calc_tab = page.locator("button:has-text('Stock Calculator')").first
        if stock_calc_tab.is_visible():
            stock_calc_tab.click()
            time.sleep(1)
            print("Switched to Stock Calculator view tab.")

        search_input = page.locator("input[placeholder*='Search any stock']").first
        calc_btn = page.locator("button:has-text('Calculate Sentiment')").first

        # --- A. RELIANCE ---
        print("\n--- Testing RELIANCE ---")
        search_input.fill("RELIANCE")
        time.sleep(0.5)
        search_input.press("Enter")
        page.wait_for_selector("text=RELIANCE", timeout=15000)
        time.sleep(3)

        text_content = page.inner_text("body")
        has_price_1377 = "1,377.50" in text_content or "1377.50" in text_content
        has_eod_badge = "EOD" in text_content
        has_close_label = "Last Verified Close" in text_content
        has_session_date = "2026-11-20" in text_content
        has_source = "Angel One SmartAPI" in text_content

        print(f"RELIANCE ₹1,377.50 visible: {has_price_1377}")
        print(f"RELIANCE EOD badge visible: {has_eod_badge}")
        print(f"RELIANCE 'Last Verified Close' visible: {has_close_label}")
        print(f"RELIANCE Session 2026-11-20 visible: {has_session_date}")
        print(f"RELIANCE Source Angel One visible: {has_source}")

        path_rel = os.path.join(artifact_dir, "stock_sentiment_reliance.png")
        page.screenshot(path=path_rel, full_page=True)
        print(f"Saved: {path_rel}")

        # --- B. TCS ---
        print("\n--- Testing TCS ---")
        search_input.fill("TCS")
        time.sleep(0.5)
        search_input.press("Enter")
        time.sleep(3)

        text_tcs = page.inner_text("body")
        has_price_tcs = "2,376.20" in text_tcs or "2376.20" in text_tcs
        print(f"TCS ₹2,376.20 visible: {has_price_tcs}")

        path_tcs = os.path.join(artifact_dir, "stock_sentiment_tcs.png")
        page.screenshot(path=path_tcs, full_page=True)
        print(f"Saved: {path_tcs}")

        # --- C. HDFCBANK ---
        print("\n--- Testing HDFCBANK ---")
        search_input.fill("HDFCBANK")
        time.sleep(0.5)
        search_input.press("Enter")
        time.sleep(3)

        text_hdfc = page.inner_text("body")
        has_price_hdfc = "846.00" in text_hdfc
        print(f"HDFCBANK ₹846.00 visible: {has_price_hdfc}")

        path_hdfc = os.path.join(artifact_dir, "stock_sentiment_hdfcbank.png")
        page.screenshot(path=path_hdfc, full_page=True)
        print(f"Saved: {path_hdfc}")

        # --- D. TOP 10 NEWS SCANNER ---
        print("\n--- Testing Top 10 News Scanner ---")
        top_scanner_tab = page.locator("button:has-text('Top 10 News Scanner')").first
        if top_scanner_tab.is_visible():
            top_scanner_tab.click()
            time.sleep(2)
        path_scanner = os.path.join(artifact_dir, "intraday_news_scanner.png")
        page.screenshot(path=path_scanner, full_page=True)
        print(f"Saved: {path_scanner}")

        # --- E. STOCK DETAILS: RELIANCE ---
        print("\n--- Testing Stock Details (/stocks/RELIANCE) ---")
        page.goto("http://localhost:3000/stocks/RELIANCE", wait_until="networkidle")
        time.sleep(2)
        path_details = os.path.join(artifact_dir, "stock_details_reliance.png")
        page.screenshot(path=path_details, full_page=True)
        print(f"Saved: {path_details}")

        browser.close()
    print("\n=================== ALL BROWSER QA TESTS COMPLETED ===================")

if __name__ == "__main__":
    run_qa()
