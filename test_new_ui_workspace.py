"""
AIVOLVE v3.0 - NEW GRAPHITE & TEAL UI WORKSPACE TEST SUITE
Tests the newly merged UI redesign across core routes and viewports,
inspects console logs, and saves screenshot evidence.
"""

import os
import sys
import time
from playwright.sync_api import sync_playwright

OUTPUT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "reports", "ui_redesign_test"))
os.makedirs(OUTPUT_DIR, exist_ok=True)

ROUTES = [
    ("/", "01_home_graphite_teal_workspace.png"),
    ("/design-preview", "02_design_preview_reference.png"),
    ("/options/NIFTY", "03_options_nifty_terminal.png"),
    ("/option-chain", "04_option_chain_table.png"),
    ("/paper-trading", "05_paper_trading_cockpit.png"),
    ("/observer", "06_observer_diagnostics.png"),
    ("/sentiment", "07_sentiment_panel.png"),
    ("/ai-insights", "08_ai_insights.png"),
]

VIEWPORTS = [
    {"name": "desktop_1920x1080", "width": 1920, "height": 1080},
    {"name": "laptop_1366x768", "width": 1366, "height": 768},
    {"name": "mobile_390x844", "width": 390, "height": 844},
]

def run_ui_tests():
    print("=" * 80)
    print("🎨 AIVOLVE v3.0 — NEW UI WORKSPACE REDESIGN TEST")
    print(f"Target URL: http://localhost:3000")
    print(f"Screenshots Output: {OUTPUT_DIR}")
    print("=" * 80)

    console_errors = []
    page_results = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1920, "height": 1080})
        page = context.new_page()

        def handle_console(msg):
            if msg.type in ["error"]:
                text = msg.text
                # Filter out known non-fatal dev warnings
                if "favicon" not in text.lower():
                    console_errors.append(f"[{page.url}] {text}")

        page.on("console", handle_console)

        # 1. Test All Core Routes
        print("\n[PHASE 1] Testing Core Routes on Desktop (1920x1080)...")
        for route, filename in ROUTES:
            url = f"http://localhost:3000{route}"
            print(f"  👉 Visiting {route}...", end="", flush=True)
            try:
                resp = page.goto(url, wait_until="domcontentloaded", timeout=10000)
                status = resp.status if resp else "NO_RESP"
                time.sleep(1.5) # allow hydration and layout to settle
                screenshot_path = os.path.join(OUTPUT_DIR, filename)
                page.screenshot(path=screenshot_path, full_page=False)
                
                # Check for key element
                has_nav = page.locator("nav, [class*='Sidebar'], [class*='AppShell']").count() > 0
                result = "PASS" if status == 200 and has_nav else f"WARN({status})"
                page_results.append({"route": route, "status": status, "result": result, "screenshot": filename})
                print(f" [{result}] HTTP {status} (Saved: {filename})")
            except Exception as e:
                print(f" [FAIL] Error: {e}")
                page_results.append({"route": route, "status": "ERROR", "result": "FAIL", "error": str(e)})

        # 2. Test Responsive Viewports on Home Page
        print("\n[PHASE 2] Testing Responsive Viewports on Home Page...")
        for vp in VIEWPORTS:
            vp_name = vp["name"]
            page.set_viewport_size({"width": vp["width"], "height": vp["height"]})
            page.goto("http://localhost:3000/", wait_until="domcontentloaded", timeout=10000)
            time.sleep(1.5)
            filename = f"responsive_home_{vp_name}.png"
            page.screenshot(path=os.path.join(OUTPUT_DIR, filename), full_page=False)
            print(f"  📱 Viewport {vp_name} ({vp['width']}x{vp['height']}): Captured {filename}")

        # 3. Test Interactive Workspace Elements
        print("\n[PHASE 3] Testing Interactive Elements (Tabs, Filters, Search)...")
        page.set_viewport_size({"width": 1920, "height": 1080})
        page.goto("http://localhost:3000/", wait_until="networkidle", timeout=15000)
        
        # Test tab switching if tabs exist
        tabs = page.locator("[role='tab'], button:has-text('Signals'), button:has-text('Structure'), button:has-text('Overview')")
        tab_count = tabs.count()
        print(f"  Found {tab_count} workspace tabs.")
        if tab_count > 0:
            for i in range(min(tab_count, 4)):
                tab_text = tabs.nth(i).inner_text().strip().split("\n")[0]
                try:
                    tabs.nth(i).click(timeout=3000)
                    time.sleep(0.5)
                    print(f"    ✅ Clicked tab: '{tab_text}'")
                except Exception as ex:
                    print(f"    ⚠️ Tab click failed for '{tab_text}': {ex}")

        # Capture interactive state
        interactive_screen = os.path.join(OUTPUT_DIR, "09_interactive_workspace_tabs.png")
        page.screenshot(path=interactive_screen)
        print(f"  Saved interactive tabs state: 09_interactive_workspace_tabs.png")

        browser.close()

    print("\n" + "=" * 80)
    print("📊 UI REDESIGN TEST SUMMARY")
    print("=" * 80)
    passed = sum(1 for r in page_results if r.get("result") == "PASS")
    total = len(page_results)
    print(f"Pages Tested : {total}")
    print(f"Passed       : {passed} / {total}")
    print(f"Console Errs : {len(console_errors)}")
    if console_errors:
        print("Console Error Samples:")
        for err in console_errors[:5]:
            print(f"  ❌ {err}")
    print(f"Screenshots  : {len(os.listdir(OUTPUT_DIR))} files in {OUTPUT_DIR}")
    print("=" * 80)

if __name__ == "__main__":
    run_ui_tests()
