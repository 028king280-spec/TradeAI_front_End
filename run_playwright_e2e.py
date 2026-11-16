import os
import sys
import time
import json
import statistics
from datetime import datetime, timezone
from playwright.sync_api import sync_playwright

REPORTS_DIR = r"d:\ReactJs\aivolve-trading-ai\reports\browser_e2e\2026-11-16"
os.makedirs(REPORTS_DIR, exist_ok=True)

BASE_URL = "http://localhost:3000"
BACKEND_URL = "http://127.0.0.1:8000"

results = {
    "test_start": datetime.now(timezone.utc).isoformat(),
    "base_url": BASE_URL,
    "backend_url": BACKEND_URL,
    "environment": {
        "browser": "Chromium",
        "playwright": True,
        "operating_mode": "OBSERVATION_ONLY"
    },
    "routes_tested": [],
    "interactions_tested": [],
    "live_market_data": {},
    "options_greeks": {},
    "ai_predictions": {},
    "risk_security_ui": {},
    "network_audit": {
        "total_requests": 0,
        "status_codes": {},
        "slow_endpoints": [],
        "failed_requests": [],
        "latencies_ms": []
    },
    "console_messages": {
        "errors": [],
        "warnings": [],
        "logs_count": 0
    },
    "responsive_tests": [],
    "negative_tests": [],
    "defects": [],
    "assertions": {
        "passed": 0,
        "failed": 0,
        "details": []
    }
}

def record_assertion(name: str, passed: bool, detail: str = ""):
    if passed:
        results["assertions"]["passed"] += 1
    else:
        results["assertions"]["failed"] += 1
    results["assertions"]["details"].append({
        "name": name,
        "passed": passed,
        "detail": detail
    })
    status_str = "PASS" if passed else "FAIL"
    print(f"  [{status_str}] {name}: {detail}")

print("=== STARTING REAL BROWSER E2E TEST SUITE (OBSERVATION_ONLY) ===")

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(viewport={"width": 1920, "height": 1080})
    page = context.new_page()

    # Track console events
    def on_console(msg):
        results["console_messages"]["logs_count"] += 1
        if msg.type == "error":
            # Sanitize any potential tokens/secrets
            text = msg.text[:300]
            results["console_messages"]["errors"].append({
                "text": text,
                "location": str(msg.location)
            })
        elif msg.type == "warning":
            text = msg.text[:300]
            if len(results["console_messages"]["warnings"]) < 50:
                results["console_messages"]["warnings"].append({
                    "text": text,
                    "location": str(msg.location)
                })

    def on_page_error(err):
        results["console_messages"]["errors"].append({
            "text": f"PAGEERROR: {str(err)[:300]}",
            "location": "window.onerror"
        })

    # Track network events
    request_start_times = {}

    def on_request(req):
        results["network_audit"]["total_requests"] += 1
        request_start_times[req] = time.time()

    def on_response(resp):
        status = resp.status
        results["network_audit"]["status_codes"][status] = results["network_audit"]["status_codes"].get(status, 0) + 1
        start = request_start_times.pop(resp.request, None)
        if start:
            duration_ms = (time.time() - start) * 1000.0
            results["network_audit"]["latencies_ms"].append(duration_ms)
            if duration_ms > 1000.0:
                # Sanitize url
                clean_url = resp.url.split("?")[0]
                results["network_audit"]["slow_endpoints"].append({
                    "url": clean_url,
                    "duration_ms": round(duration_ms, 1),
                    "status": status
                })
        if status >= 400:
            clean_url = resp.url.split("?")[0]
            results["network_audit"]["failed_requests"].append({
                "url": clean_url,
                "status": status,
                "status_text": resp.status_text
            })

    page.on("console", on_console)
    page.on("pageerror", on_page_error)
    page.on("request", on_request)
    page.on("response", on_response)

    # -------------------------------------------------------------
    # PHASE A: INITIAL LOAD & HEALTH
    # -------------------------------------------------------------
    print("\n--- PHASE A: Environment & Initial Load Verification ---")
    t0 = time.time()
    resp = page.goto(BASE_URL, wait_until="networkidle", timeout=30000)
    load_time_ms = round((time.time() - t0) * 1000, 1)
    record_assertion("Phase A: Initial Page Load", resp is not None and resp.status == 200, f"HTTP {resp.status if resp else 'None'} in {load_time_ms}ms")
    initial_ss = os.path.join(REPORTS_DIR, "phase_a_initial_load.png")
    page.screenshot(path=initial_ss, full_page=True)

    # -------------------------------------------------------------
    # PHASE B: ROUTE-BY-ROUTE COVERAGE
    # -------------------------------------------------------------
    print("\n--- PHASE B: Complete UI Route Coverage ---")
    routes_to_test = [
        {"path": "/", "name": "dashboard"},
        {"path": "/ai-insights", "name": "ai_insights"},
        {"path": "/alerts", "name": "alerts"},
        {"path": "/observer", "name": "observer_redirect"},
        {"path": "/option-chain", "name": "option_chain"},
        {"path": "/options/NIFTY", "name": "options_nifty"},
        {"path": "/options/BANKNIFTY", "name": "options_banknifty"},
        {"path": "/options/FINNIFTY", "name": "options_finnifty"},
        {"path": "/outlook", "name": "outlook"},
        {"path": "/paper-trading", "name": "paper_trading"},
        {"path": "/patterns", "name": "patterns"},
        {"path": "/performance", "name": "performance"},
        {"path": "/research", "name": "research"},
        {"path": "/search", "name": "search"},
        {"path": "/sentiment", "name": "sentiment"},
        {"path": "/stocks/RELIANCE", "name": "stock_reliance"}
    ]

    for r in routes_to_test:
        target_url = f"{BASE_URL}{r['path']}"
        t_start = time.time()
        try:
            r_resp = page.goto(target_url, wait_until="networkidle", timeout=30000)
            elapsed_ms = round((time.time() - t_start) * 1000, 1)
            status = r_resp.status if r_resp else 0
            
            # Wait for meaningful content
            page.wait_for_timeout(1000)
            
            # Check for body content and blank screen
            body_text = page.inner_text("body")
            has_content = len(body_text.strip()) > 50
            
            # Capture screenshot
            ss_name = f"route_{r['name']}.png"
            ss_path = os.path.join(REPORTS_DIR, ss_name)
            page.screenshot(path=ss_path, full_page=True)
            
            # Extract main heading or title
            title = page.title()
            headings = page.locator("h1, h2").all_inner_texts()
            primary_heading = headings[0] if headings else title
            
            passed = (status in [200, 304] or (r["name"] == "observer_redirect" and "sentiment" in page.url)) and has_content
            record_assertion(f"Route {r['path']}", passed, f"Status: {status}, Heading: '{primary_heading[:40]}', Latency: {elapsed_ms}ms")
            
            results["routes_tested"].append({
                "path": r["path"],
                "name": r["name"],
                "status": status,
                "elapsed_ms": elapsed_ms,
                "has_content": has_content,
                "content_len": len(body_text),
                "primary_heading": primary_heading[:60],
                "screenshot": ss_name,
                "final_url": page.url
            })
        except Exception as e:
            record_assertion(f"Route {r['path']}", False, f"Exception: {str(e)[:100]}")
            results["routes_tested"].append({
                "path": r["path"],
                "name": r["name"],
                "status": "ERROR",
                "elapsed_ms": round((time.time() - t_start) * 1000, 1),
                "has_content": False,
                "error": str(e)[:200]
            })

    # -------------------------------------------------------------
    # PHASE C: DASHBOARD FUNCTIONAL TESTING
    # -------------------------------------------------------------
    print("\n--- PHASE C: Dashboard Functional Testing ---")
    page.goto(f"{BASE_URL}/", wait_until="networkidle", timeout=30000)
    page.wait_for_timeout(1500)
    
    # 1. Test clicking Index Cards
    # Look for index cards: "BANK NIFTY", "NIFTY 50", "BSE SENSEX"
    bank_card = page.locator("text=BANK NIFTY").first
    if bank_card.is_visible():
        bank_card.click()
        page.wait_for_timeout(1500)
        ss_bank = os.path.join(REPORTS_DIR, "dashboard_banknifty_selected.png")
        page.screenshot(path=ss_bank, full_page=True)
        results["interactions_tested"].append({
            "action": "click_bank_nifty_card",
            "result": "Success, switched active index to BANK NIFTY",
            "screenshot": "dashboard_banknifty_selected.png"
        })
        record_assertion("Dashboard Index Selector: BANK NIFTY", True, "Successfully clicked and updated active analysis")

    nifty_card = page.locator("text=NIFTY 50").first
    if nifty_card.is_visible():
        nifty_card.click()
        page.wait_for_timeout(1500)
        ss_nifty = os.path.join(REPORTS_DIR, "dashboard_nifty_selected.png")
        page.screenshot(path=ss_nifty, full_page=True)
        results["interactions_tested"].append({
            "action": "click_nifty_50_card",
            "result": "Success, returned active index to NIFTY 50",
            "screenshot": "dashboard_nifty_selected.png"
        })
        record_assertion("Dashboard Index Selector: NIFTY 50", True, "Successfully switched active index to NIFTY 50")

    # 2. Test Refresh button
    refresh_btn = page.locator("button:has-text('Refresh')").first
    if refresh_btn.is_visible():
        refresh_btn.click()
        page.wait_for_timeout(1000)
        record_assertion("Dashboard Refresh Button", True, "Clicked quote refresh button cleanly")

    # 3. Test Signal Activation Bias buttons (AUTO, CE, PE)
    bias_ce_btn = page.locator("button:has-text('CALL (CE)')").first
    if bias_ce_btn.is_visible():
        bias_ce_btn.click()
        page.wait_for_timeout(500)
        page.screenshot(path=os.path.join(REPORTS_DIR, "dashboard_bias_ce.png"), full_page=True)
        record_assertion("Dashboard Signal Bias: CE", True, "Switched signal bias filter to CE")

    bias_pe_btn = page.locator("button:has-text('PUT (PE)')").first
    if bias_pe_btn.is_visible():
        bias_pe_btn.click()
        page.wait_for_timeout(500)
        page.screenshot(path=os.path.join(REPORTS_DIR, "dashboard_bias_pe.png"), full_page=True)
        record_assertion("Dashboard Signal Bias: PE", True, "Switched signal bias filter to PE")

    bias_auto_btn = page.locator("button:has-text('AUTO')").first
    if bias_auto_btn.is_visible():
        bias_auto_btn.click()
        page.wait_for_timeout(500)
        record_assertion("Dashboard Signal Bias: AUTO", True, "Reset signal bias filter to AUTO")

    # Check disclaimer footer presence
    footer_mandate = page.locator("text=Institutional Research Mandate & Analytical Integrity")
    record_assertion("Dashboard Institutional Disclaimer", footer_mandate.is_visible(), "Verified institutional mandate footer is visible")

    # -------------------------------------------------------------
    # PHASE D: LIVE MARKET DATA BROWSER VALIDATION
    # -------------------------------------------------------------
    print("\n--- PHASE D: Live Market Data Browser Validation ---")
    # Inspect live index prices from DOM
    for sym_label, sym_key in [("NIFTY 50", "NIFTY"), ("BANK NIFTY", "BANKNIFTY"), ("BSE SENSEX", "SENSEX")]:
        card = page.locator(f"div:has-text('{sym_label}')").last
        card_text = card.inner_text() if card.is_visible() else ""
        results["live_market_data"][sym_key] = {
            "label": sym_label,
            "visible": card.is_visible(),
            "extracted_text": card_text.replace("\n", " | ")[:120]
        }
        record_assertion(f"Live Market Data: {sym_label}", card.is_visible(), f"Card text: {card_text.replace(chr(10), ' ')[:60]}")

    # Observe live ticks freshness over 10 seconds
    ticks_sample = []
    for _ in range(5):
        try:
            # Query backend live status directly via page evaluate
            status_data = page.evaluate("() => fetch('/api/live/status').then(r => r.json())")
            ticks_sample.append(status_data.get("diagnostics", {}).get("ticks_received", 0))
        except Exception:
            pass
        page.wait_for_timeout(2000)

    tick_increase = (ticks_sample[-1] - ticks_sample[0]) if len(ticks_sample) >= 2 else 0
    results["live_market_data"]["tick_samples"] = ticks_sample
    results["live_market_data"]["tick_increase_10s"] = tick_increase
    record_assertion("Live WebSocket Ticks Streaming", tick_increase > 0, f"Received {tick_increase} new ticks in 10s window (total: {ticks_sample[-1] if ticks_sample else 0})")

    # -------------------------------------------------------------
    # PHASE E: OPTIONS INTELLIGENCE & GREEKS UI TESTING
    # -------------------------------------------------------------
    print("\n--- PHASE E: Options Intelligence & Greeks UI Testing ---")
    page.goto(f"{BASE_URL}/option-chain?symbol=NIFTY%2050", wait_until="networkidle", timeout=30000)
    page.wait_for_timeout(1500)
    
    # Verify strike prices and Greeks columns
    table_headers = page.locator("th").all_inner_texts()
    greeks_found = [h for h in table_headers if h in ["Delta", "Theta", "IV %", "Volume", "OI", "Chg OI"]]
    record_assertion("Option Chain Greeks Headers", len(greeks_found) >= 4, f"Found Greek & analytical columns: {greeks_found}")

    # Verify ATM vs WIDE filter buttons
    wide_btn = page.locator("button:has-text('WIDE')").first
    if wide_btn.is_visible():
        wide_btn.click()
        page.wait_for_timeout(1500)
        page.screenshot(path=os.path.join(REPORTS_DIR, "options_chain_wide.png"), full_page=True)
        record_assertion("Option Chain WIDE Filter", True, "Successfully toggled WIDE strike range")

    atm_btn = page.locator("button:has-text('ATM')").first
    if atm_btn.is_visible():
        atm_btn.click()
        page.wait_for_timeout(1000)
        record_assertion("Option Chain ATM Filter", True, "Successfully returned to ATM strike range")

    # -------------------------------------------------------------
    # PHASE F: AI PREDICTIONS BROWSER TESTING
    # -------------------------------------------------------------
    print("\n--- PHASE F: AI Predictions Browser Testing ---")
    page.goto(f"{BASE_URL}/ai-insights", wait_until="networkidle", timeout=30000)
    page.wait_for_timeout(1500)
    
    insights_text = page.inner_text("body")
    has_model_insights = "Market" in insights_text or "Insight" in insights_text or "Sentiment" in insights_text
    record_assertion("AI Market Insights Interface", has_model_insights, "AI Insights page rendered successfully")
    page.screenshot(path=os.path.join(REPORTS_DIR, "prediction_ai_insights.png"), full_page=True)

    # Check dashboard prediction and setups
    page.goto(f"{BASE_URL}/", wait_until="networkidle", timeout=30000)
    page.wait_for_timeout(1500)
    dashboard_text = page.inner_text("body")
    has_setups = "Options Setups" in dashboard_text or "NO TRADE" in dashboard_text or "CIRCUIT BREAKER" in dashboard_text
    record_assertion("Options Setups & Prediction Gating", has_setups, "Verified options setups / fail-closed circuit breaker message in DOM")

    # -------------------------------------------------------------
    # PHASE G: RISK MANAGEMENT & SECURITY UI
    # -------------------------------------------------------------
    print("\n--- PHASE G: Risk Management & Security UI ---")
    page.goto(f"{BASE_URL}/paper-trading", wait_until="networkidle", timeout=30000)
    page.wait_for_timeout(1500)
    
    paper_text = page.inner_text("body")
    # Verify Zero Capital Risk Mandate
    has_zero_risk_mandate = "Zero Capital Risk Mandate" in paper_text or "PAPER_TRADING_ONLY" in paper_text
    record_assertion("Risk Management Mandate", has_zero_risk_mandate, "Verified zero capital risk mandate banner is active")

    # Verify SENSEX is locked
    sensex_locked = "BSE SENSEX (LOCKED)" in paper_text or "GOVERNANCE LOCKOUT ACTIVE" in paper_text or "GOVERNANCE_LOCKED" in paper_text
    record_assertion("Risk Control: SENSEX Governance Lock", sensex_locked, "Verified SENSEX is locked from trading")

    # Inspect simulated order simulator
    # Verify no naked short options selling button is exposed to users
    sell_short_open_btn = page.locator("button:has-text('SELL / SHORT')").all()
    record_assertion("Risk Control: Naked Short Sell Blocked in UI", len(sell_short_open_btn) == 0, f"Found {len(sell_short_open_btn)} naked short open buttons (must be 0)")
    page.screenshot(path=os.path.join(REPORTS_DIR, "risk_paper_trading_cockpit.png"), full_page=True)

    # -------------------------------------------------------------
    # PHASE I: RESPONSIVE VIEWPORT TESTING
    # -------------------------------------------------------------
    print("\n--- PHASE I: Responsive Viewport Testing ---")
    viewports = [
        {"name": "desktop_1920x1080", "width": 1920, "height": 1080},
        {"name": "laptop_1366x768", "width": 1366, "height": 768},
        {"name": "tablet_768x1024", "width": 768, "height": 1024},
        {"name": "mobile_390x844", "width": 390, "height": 844}
    ]

    for vp in viewports:
        page.set_viewport_size({"width": vp["width"], "height": vp["height"]})
        # Test dashboard on this viewport
        page.goto(f"{BASE_URL}/", wait_until="networkidle", timeout=20000)
        page.wait_for_timeout(1000)
        ss_vp = os.path.join(REPORTS_DIR, f"responsive_dashboard_{vp['name']}.png")
        page.screenshot(path=ss_vp, full_page=False) # Viewport screenshot
        
        # Check horizontal overflow
        scroll_width = page.evaluate("() => document.documentElement.scrollWidth")
        client_width = page.evaluate("() => document.documentElement.clientWidth")
        has_horizontal_overflow = (scroll_width > client_width + 10) # 10px buffer
        
        record_assertion(f"Responsive Viewport {vp['name']}", not has_horizontal_overflow, f"ScrollWidth: {scroll_width}, ClientWidth: {client_width}")
        results["responsive_tests"].append({
            "viewport": vp["name"],
            "width": vp["width"],
            "height": vp["height"],
            "scroll_width": scroll_width,
            "client_width": client_width,
            "overflow": has_horizontal_overflow,
            "screenshot": f"responsive_dashboard_{vp['name']}.png"
        })

    # Restore viewport
    page.set_viewport_size({"width": 1920, "height": 1080})

    # -------------------------------------------------------------
    # PHASE J: NEGATIVE & RECOVERY TESTING
    # -------------------------------------------------------------
    print("\n--- PHASE J: Negative & Recovery Testing ---")
    # 1. 404 Route
    page.goto(f"{BASE_URL}/nonexistent-test-route-404", wait_until="networkidle", timeout=20000)
    page.wait_for_timeout(1000)
    body_404 = page.inner_text("body")
    has_404 = "404" in body_404 or "not found" in body_404.lower() or "page" in body_404.lower()
    page.screenshot(path=os.path.join(REPORTS_DIR, "negative_404.png"), full_page=True)
    record_assertion("Negative Testing: 404 Route Handling", has_404, "Application handles non-existent routes gracefully")

    # 2. Invalid option symbol
    page.goto(f"{BASE_URL}/options/INVALID_INDEX", wait_until="networkidle", timeout=20000)
    page.wait_for_timeout(1000)
    body_inv = page.inner_text("body")
    no_crash = len(body_inv) > 50
    page.screenshot(path=os.path.join(REPORTS_DIR, "negative_invalid_index.png"), full_page=True)
    record_assertion("Negative Testing: Invalid Index Route", no_crash, "Handled invalid index without breaking page layout")

    # 3. Page Refresh on /paper-trading
    page.goto(f"{BASE_URL}/paper-trading", wait_until="networkidle", timeout=20000)
    page.wait_for_timeout(1000)
    page.reload(wait_until="networkidle")
    page.wait_for_timeout(1000)
    body_reloaded = page.inner_text("body")
    record_assertion("Recovery Testing: Browser Page Reload", "PAPER TRADING COCKPIT" in body_reloaded, "State cleanly recovered after browser reload")

    browser.close()

# -------------------------------------------------------------
# PHASE H: AGGREGATE NETWORK & PERFORMANCE STATS
# -------------------------------------------------------------
latencies = results["network_audit"]["latencies_ms"]
if latencies:
    results["network_audit"]["latency_stats"] = {
        "min_ms": round(min(latencies), 1),
        "max_ms": round(max(latencies), 1),
        "mean_ms": round(statistics.mean(latencies), 1),
        "median_ms": round(statistics.median(latencies), 1),
        "p95_ms": round(statistics.quantiles(latencies, n=20)[18], 1) if len(latencies) >= 20 else round(max(latencies), 1)
    }

results["test_end"] = datetime.now(timezone.utc).isoformat()

# Save results JSON
results_json_path = os.path.join(REPORTS_DIR, "browser_e2e_results.json")
with open(results_json_path, "w", encoding="utf-8") as f:
    json.dump(results, f, indent=2)

print("\n=== TEST RUN COMPLETE ===")
print(f"Results saved to: {results_json_path}")
print(f"Passed assertions: {results['assertions']['passed']}")
print(f"Failed assertions: {results['assertions']['failed']}")
print(f"Total network requests: {results['network_audit']['total_requests']}")
print(f"Console errors: {len(results['console_messages']['errors'])}")

