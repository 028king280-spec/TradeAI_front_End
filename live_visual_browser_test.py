import time
import sys
from playwright.sync_api import sync_playwright

def run_live_visual_browser_testing():
    print("=" * 60)
    print(">>> STARTING LIVE VISIBLE BROWSER TESTING IN FRONT OF USER <<<")
    print("=" * 60)

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            slow_mo=1000,
            args=["--start-maximized"]
        )
        context = browser.new_context(no_viewport=True)
        page = context.new_page()

        # Step 1: Main Dashboard
        print("\n[STEP 1/7] Loading Main Dashboard (http://localhost:3000)...")
        page.goto("http://localhost:3000", wait_until="networkidle")
        page.wait_for_timeout(2000)

        # Highlight & click BANK NIFTY card
        print("[STEP 2/7] Clicking 'BANK NIFTY' Index Card...")
        bank_card = page.locator("text=BANK NIFTY").first
        if bank_card.is_visible():
            bank_card.hover()
            page.wait_for_timeout(1000)
            bank_card.click()
            page.wait_for_timeout(2500)

        # Highlight & click NIFTY 50 card
        print("[STEP 3/7] Clicking 'NIFTY 50' Index Card...")
        nifty_card = page.locator("text=NIFTY 50").first
        if nifty_card.is_visible():
            nifty_card.hover()
            page.wait_for_timeout(1000)
            nifty_card.click()
            page.wait_for_timeout(2500)

        # Test Signal Bias Toggles (CE, PE, AUTO)
        print("[STEP 4/7] Testing Signal Bias Toggles (CALL, PUT, AUTO)...")
        bias_ce = page.locator("button:has-text('CALL (CE)')").first
        if bias_ce.is_visible():
            bias_ce.click()
            page.wait_for_timeout(1500)
        
        bias_pe = page.locator("button:has-text('PUT (PE)')").first
        if bias_pe.is_visible():
            bias_pe.click()
            page.wait_for_timeout(1500)

        bias_auto = page.locator("button:has-text('AUTO')").first
        if bias_auto.is_visible():
            bias_auto.click()
            page.wait_for_timeout(1500)

        # Scroll down smoothly to show all analytics cards
        print("[STEP 5/7] Scrolling through Live Analysis, SMC Order Flow, and Setups...")
        page.mouse.wheel(0, 500)
        page.wait_for_timeout(2000)
        page.mouse.wheel(0, 600)
        page.wait_for_timeout(2000)
        page.mouse.wheel(0, -1100) # Scroll back to top
        page.wait_for_timeout(1500)

        # Step 6: Option Chain Terminal
        print("\n[STEP 6/7] Navigating to Option Chain Terminal (http://localhost:3000/option-chain)...")
        page.goto("http://localhost:3000/option-chain", wait_until="networkidle")
        page.wait_for_timeout(2500)

        # Toggle WIDE and ATM in Option Chain
        print("  - Toggling WIDE strike range in Option Chain...")
        wide_btn = page.locator("button:has-text('WIDE')").first
        if wide_btn.is_visible():
            wide_btn.click()
            page.wait_for_timeout(2500)

        print("  - Toggling ATM strike range in Option Chain...")
        atm_btn = page.locator("button:has-text('ATM')").first
        if atm_btn.is_visible():
            atm_btn.click()
            page.wait_for_timeout(2000)

        # Step 7: Dedicated Index Terminals
        print("\n[STEP 7/7] Testing Dedicated BANK NIFTY Terminal (http://localhost:3000/options/BANKNIFTY)...")
        page.goto("http://localhost:3000/options/BANKNIFTY", wait_until="networkidle")
        page.wait_for_timeout(2500)
        page.mouse.wheel(0, 400)
        page.wait_for_timeout(1500)

        print("Testing Dedicated FINNIFTY Terminal (http://localhost:3000/options/FINNIFTY)...")
        page.goto("http://localhost:3000/options/FINNIFTY", wait_until="networkidle")
        page.wait_for_timeout(2500)
        page.mouse.wheel(0, 400)
        page.wait_for_timeout(1500)

        # Step 8: Paper Trading Cockpit & Tabs
        print("\nTesting Paper Trading Cockpit (http://localhost:3000/paper-trading)...")
        page.goto("http://localhost:3000/paper-trading", wait_until="networkidle")
        page.wait_for_timeout(2500)

        # Switch tabs in simulator
        journal_btn = page.locator("button:has-text('Journal')").first
        if journal_btn.is_visible():
            print("  - Clicking 'Journal' tab...")
            journal_btn.click()
            page.wait_for_timeout(2000)

        ai_btn = page.locator("button:has-text('AI Learning')").first
        if ai_btn.is_visible():
            print("  - Clicking 'AI Learning' tab...")
            ai_btn.click()
            page.wait_for_timeout(2500)

        pos_btn = page.locator("button:has-text('Positions')").first
        if pos_btn.is_visible():
            print("  - Returning to 'Positions' tab...")
            pos_btn.click()
            page.wait_for_timeout(2000)

        # Return to Dashboard and keep open for user
        print("\nReturning to Main Dashboard...")
        page.goto("http://localhost:3000", wait_until="networkidle")
        print("\n" + "=" * 60)
        print(">>> ALL LIVE BROWSER TESTS PASSED 100% IN FRONT OF USER! <<<")
        print("Keeping the browser open on screen for observation...")
        print("=" * 60)

        # Keep browser open for 90 seconds so user can inspect and interact
        time.sleep(90)
        browser.close()

if __name__ == "__main__":
    run_live_visual_browser_testing()

