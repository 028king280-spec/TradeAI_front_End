import time
import sys
from playwright.sync_api import sync_playwright

def run_visible_session():
    print("=" * 70)
    print("🚀 AIVOLVE v3.0 — LIVE VISIBLE BROWSER TESTING SESSION")
    print("   Graphite & Teal Workspace Redesign | Live Market Ingestion Active")
    print("=" * 70)

    with sync_playwright() as p:
        print("[LAUNCH] Starting Chromium in visible maximized window (headless=False)...")
        browser = p.chromium.launch(
            headless=False,
            slow_mo=700,
            args=["--start-maximized"]
        )
        context = browser.new_context(no_viewport=True)
        page = context.new_page()

        # Step 1: Main Dashboard
        print("\n[STEP 1/7] Loading Main Dashboard (http://localhost:3000)...")
        page.goto("http://localhost:3000", wait_until="domcontentloaded")
        page.wait_for_timeout(3000)

        # Step 2: Index Switching
        print("\n[STEP 2/7] Testing Index Card Switching...")
        for symbol in ["BANK NIFTY", "FINNIFTY", "NIFTY 50"]:
            print(f"  👉 Selecting Index: {symbol}...")
            card = page.locator(f"button:has-text('{symbol}')").first
            if card.is_visible():
                card.hover()
                page.wait_for_timeout(800)
                card.click()
                page.wait_for_timeout(1800)

        # Step 3: Workspace Tabs Switching
        print("\n[STEP 3/7] Testing Workspace Tabs Navigation...")
        tabs = ["Signals", "Structure", "Outlook", "Learning", "Paper trading", "Overview"]
        for tab_name in tabs:
            print(f"  👉 Switching Workspace Tab to: '{tab_name}'...")
            tab_btn = page.locator(f"button:has-text('{tab_name}')").first
            if tab_btn.is_visible():
                tab_btn.click()
                page.wait_for_timeout(1500)

        # Step 4: Candlestick Chart Timeframe & Indicators
        print("\n[STEP 4/7] Testing Chart Timeframes & Technical Overlays...")
        for tf in ["5m", "15m"]:
            tf_btn = page.locator(f"button:has-text('{tf}')").first
            if tf_btn.is_visible():
                print(f"  👉 Switching Timeframe: {tf}...")
                tf_btn.click()
                page.wait_for_timeout(1200)

        for ind in ["VWAP", "SMC Zones"]:
            ind_btn = page.locator(f"button:has-text('{ind}')").first
            if ind_btn.is_visible():
                print(f"  👉 Toggling Indicator Overlay: {ind}...")
                ind_btn.click()
                page.wait_for_timeout(1000)

        # Step 5: Option Chain Terminal
        print("\n[STEP 5/7] Opening Option Chain Terminal (http://localhost:3000/option-chain)...")
        page.goto("http://localhost:3000/option-chain", wait_until="domcontentloaded")
        page.wait_for_timeout(3000)

        # Step 6: Observer Diagnostics
        print("\n[STEP 6/7] Opening Observer Telemetry (http://localhost:3000/observer)...")
        page.goto("http://localhost:3000/observer", wait_until="domcontentloaded")
        page.wait_for_timeout(3000)

        # Step 7: Return to Home Workspace
        print("\n[STEP 7/7] Returning to Main Workspace (http://localhost:3000)...")
        page.goto("http://localhost:3000", wait_until="domcontentloaded")
        page.wait_for_timeout(2000)

        print("\n" + "=" * 70)
        print("✅ VISIBLE TESTING RUN COMPLETED SUCCESSFULLY!")
        print("   Holding browser window open for live user observation.")
        print("   Press Ctrl+C in terminal to close when done.")
        print("=" * 70)

        # Keep browser open for live observation
        try:
            time.sleep(300)  # 5 minutes live display
        except KeyboardInterrupt:
            print("\nClosing browser...")

        browser.close()

if __name__ == "__main__":
    run_visible_session()
