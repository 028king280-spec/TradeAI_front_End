import time
import json
import os
import sys
from datetime import datetime
import urllib.request
import urllib.error

REPORT_DIR = os.path.join(os.path.dirname(__file__), "reports")
os.makedirs(REPORT_DIR, exist_ok=True)
LOG_FILE = os.path.join(REPORT_DIR, "live_market_session_test.log")

def fetch_json(url, timeout=5):
    req = urllib.request.Request(url, headers={"User-Agent": "AIVOLVE-LiveMonitor/1.0"})
    start = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            elapsed_ms = round((time.time() - start) * 1000, 1)
            data = json.loads(resp.read().decode("utf-8"))
            return data, elapsed_ms, None
    except Exception as e:
        elapsed_ms = round((time.time() - start) * 1000, 1)
        return None, elapsed_ms, str(e)

def check_frontend(url="http://localhost:3000", timeout=3):
    req = urllib.request.Request(url, headers={"User-Agent": "AIVOLVE-LiveMonitor/1.0"})
    start = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            elapsed_ms = round((time.time() - start) * 1000, 1)
            return (resp.status == 200), elapsed_ms, None
    except Exception as e:
        elapsed_ms = round((time.time() - start) * 1000, 1)
        return False, elapsed_ms, str(e)

def log_line(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    formatted = f"[{ts}] {msg}"
    print(formatted, flush=True)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(formatted + "\n")
    except Exception:
        pass

def main():
    log_line("=" * 80)
    log_line("🟢 AIVOLVE LIVE MARKET TESTING & TELEMETRY MONITOR STARTED")
    log_line("   Target Environment: Live NSE/BSE Trading Session (Angel One SmartStream)")
    log_line("   Safety Boundary: Strictly PAPER_TRADING_ONLY | SENSEX Governance Locked")
    log_line("=" * 80)

    prev_ticks = None
    iteration = 0

    while True:
        iteration += 1
        now_str = datetime.now().strftime("%H:%M:%S")

        # 1. Check Backend Health
        health_data, health_ms, health_err = fetch_json("http://127.0.0.1:8000/api/health")

        # 2. Check Observer Diagnostics (Tick Stream Telemetry)
        obs_data, obs_ms, obs_err = fetch_json("http://127.0.0.1:8000/api/live/status")

        # 3. Check Live Market Feed (Index Quotes)
        market_data, market_ms, market_err = fetch_json("http://127.0.0.1:8000/api/market/live")

        # 4. Check Paper Trading Portfolio Status
        paper_data, paper_ms, paper_err = fetch_json("http://127.0.0.1:8000/api/paper-trading/portfolio")

        # 5. Check Frontend Status
        fe_ok, fe_ms, fe_err = check_frontend("http://localhost:3000", timeout=3)

        # Parse Observer Telemetry
        ticks_total = 0
        tick_delta_str = ""
        staleness = 0.0
        ws_status = "UNKNOWN"
        if obs_data and "diagnostics" in obs_data:
            diag = obs_data["diagnostics"]
            ticks_total = diag.get("ticks_received", 0)
            staleness = diag.get("seconds_since_last_tick")
            if staleness is None:
                staleness = 0.0
            else:
                try:
                    staleness = float(staleness)
                except (ValueError, TypeError):
                    staleness = 0.0
            ws_status = obs_data.get("status", "STREAMING")
            if prev_ticks is not None:
                delta = ticks_total - prev_ticks
                tick_delta_str = f"(+{delta} ticks)"
            prev_ticks = ticks_total

        # Parse Index Prices
        nifty_str = "N/A"
        bank_str = "N/A"
        sensex_str = "N/A"
        vix_str = "N/A"
        if market_data and "data" in market_data:
            for idx in market_data["data"].get("indices", []):
                sym = idx.get("symbol", "")
                val = idx.get("currentValue", 0.0)
                chg = idx.get("changePercent", 0.0)
                sign = "+" if chg >= 0 else ""
                if "NIFTY 50" in sym:
                    nifty_str = f"{val:,.2f} ({sign}{chg:.2f}%)"
                elif "BANK NIFTY" in sym:
                    bank_str = f"{val:,.2f} ({sign}{chg:.2f}%)"
                elif "SENSEX" in sym:
                    sensex_str = f"{val:,.2f} ({sign}{chg:.2f}%)"
                elif "VIX" in sym:
                    vix_str = f"{val:.2f}"

        # Parse Paper Trading Invariants
        balance_str = "₹1,00,000.00"
        positions_cnt = 0
        open_pos_info = ""
        if paper_data and isinstance(paper_data, dict):
            balance_str = f"₹{paper_data.get('currentBalance', 100000):,.2f}"
            open_pos = paper_data.get('openPositions', [])
            positions_cnt = len(open_pos)
            if positions_cnt > 0:
                p0 = open_pos[0]
                open_pos_info = f" | Active Pos: {p0.get('contractSymbol')} ({p0.get('quantity')} qty @ ₹{p0.get('entryPremium')}) Curr=₹{p0.get('currentPremium')} PnL=₹{p0.get('unrealizedGrossPnl', 0.0):+0.1f}"

        # Status Summary Line
        status_flag = "HEALTHY" if (obs_err is None and (staleness or 0.0) < 5.0 and fe_ok) else "ATTENTION"

        log_line(
            f"#{iteration:04d} [{status_flag}] WS: {ws_status} | Ticks: {ticks_total:,} {tick_delta_str} (last tick: {staleness:.2f}s ago) | "
            f"NIFTY: {nifty_str} | BANKNIFTY: {bank_str} | VIX: {vix_str} | "
            f"Paper Margin: {balance_str} (Pos: {positions_cnt}){open_pos_info} | Latency: BE={health_ms}ms, FE={fe_ms}ms"
        )

        # Verification Invariant Check
        if health_err:
            log_line(f"   ⚠️ Backend Health Notice: {health_err}")
        if not fe_ok:
            log_line(f"   ⚠️ Frontend Next.js Notice: {fe_err}")

        # Sleep interval (30 seconds)
        time.sleep(30)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log_line("⏹️ Live market monitor stopped by user.")
