import os
import sys

backend_dir = os.path.join(os.path.dirname(__file__), "..", "backend")
sys.path.insert(0, backend_dir)

from app.options.paper_trading.post_market_pipeline import DailyPostMarketForensicPipeline

p = DailyPostMarketForensicPipeline("2026-11-20")
raw_p, raw_r = p.load_raw_session_trades()
print(f"20 Nov Paper Trades loaded: {len(raw_p)}")
for t in raw_p:
    print(f"ID: {t['id']} | Contract: {t.get('contractSymbol')} | Entry: {t.get('entryTimestamp')} | Exit: {t.get('exitTimestamp')} | Net: {t.get('netPnl')}")
