import asyncio
import json
import os
import sys

backend_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend")
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

# Ensure environment variables are loaded
os.chdir(backend_dir)

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def run_tests():
    print("=================== 1. MARKET STATUS ===================")
    res = client.get("/api/market/status")
    print(f"Status: {res.status_code}")
    print(json.dumps(res.json(), indent=2))

    print("\n=================== 2. STOCK QUOTES (RELIANCE, TCS, HDFCBANK) ===================")
    for sym in ["RELIANCE", "TCS", "HDFCBANK"]:
        res = client.get(f"/api/stocks/{sym}/quote")
        print(f"Quote {sym} ({res.status_code}):")
        data = res.json()
        print(json.dumps(data, indent=2))
        assert res.status_code == 200
        assert data["success"] is True
        assert data["data"]["currentPrice"] > 0
        assert data["dataStatus"] in ("LIVE", "MARKET_CLOSED")
        assert data["data"]["timestamp"] is not None

    print("\n=================== 3. STOCK SENTIMENT (RELIANCE, TCS, HDFCBANK) ===================")
    for sym in ["RELIANCE", "TCS", "HDFCBANK"]:
        res = client.get(f"/api/news/stock-sentiment/{sym}")
        print(f"Sentiment {sym} ({res.status_code}):")
        data = res.json()
        pm = data.get("data", {}).get("priceMetrics", {})
        print(f"priceMetrics: currentPrice={pm.get('currentPrice')}, isLive={pm.get('isLive')}, isEod={pm.get('isEod')}, dataStatus={pm.get('dataStatus')}, priceLabel={pm.get('priceLabel')}")
        assert res.status_code == 200
        assert data["success"] is True
        assert pm["currentPrice"] > 0
        assert pm["dataStatus"] in ("LIVE", "MARKET_CLOSED")
        assert pm["priceLabel"] in ("Live CMP", "Last Verified Close")

    print("\n=================== 4. INTRADAY NEWS SCANNER TOP STOCKS ===================")
    res = client.get("/api/news/intraday/top-stocks?direction=all&limit=5")
    print(f"Scanner ({res.status_code}):")
    data = res.json()
    stocks = data.get("data", {}).get("stocks", [])
    print(f"Total qualified stocks returned: {len(stocks)}")
    for s in stocks[:5]:
        print(f"Stock {s.get('symbol')}: price={s.get('currentPrice')}, dataStatus={s.get('dataStatus')}, conf={s.get('priceConfirmation')}")

    print("\n=================== ALL LIVE API VERIFICATION CHECKS COMPLETED ===================")

if __name__ == "__main__":
    run_tests()
