import asyncio
import sys
import os

backend_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend")
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

from app.data.providers.factory import get_market_data_provider
from app.services.stock_sentiment_service import StockSentimentCalculatorService
from app.services.news_scanner_service import IntradayNewsScannerService


async def verify_endpoints():
    print("=== 1. VERIFYING STOCK QUOTES ===")
    prov = get_market_data_provider()
    for sym in ["RELIANCE", "TCS", "HDFCBANK"]:
        q = await prov.get_quote(sym)
        ltp = q.get("currentPrice")
        status = q.get("dataStatus")
        feed = q.get("feedStatus")
        trade_q = q.get("isTradeQualified")
        ts = q.get("timestamp")
        print(f"QUOTE {sym}: LTP={ltp} dataStatus={status} feedStatus={feed} isTradeQualified={trade_q} timestamp={ts}")
        assert ltp and ltp > 0, f"Expected non-zero LTP for {sym}, got {ltp}"
        assert status in ("LIVE", "MARKET_CLOSED"), f"Unexpected status {status} for {sym}"
        assert ts, f"Missing timestamp for {sym}"

    print("\n=== 2. VERIFYING STOCK SENTIMENT PRICE METRICS ===")
    for sym in ["RELIANCE", "TCS", "HDFCBANK"]:
        sent = await StockSentimentCalculatorService.calculate(sym)
        pm = sent.get("priceMetrics", {})
        price = pm.get("currentPrice")
        is_live = pm.get("isLive")
        is_eod = pm.get("isEod")
        status = pm.get("dataStatus")
        label = pm.get("priceLabel")
        print(f"SENTIMENT {sym}: currentPrice={price} isLive={is_live} isEod={is_eod} dataStatus={status} label='{label}'")
        assert price and price > 0, f"Expected non-zero priceMetrics.currentPrice for {sym}, got {price}"
        assert status in ("LIVE", "MARKET_CLOSED"), f"Unexpected sentiment status for {sym}"

    print("\n=== 3. VERIFYING INTRADAY NEWS SCANNER STOCKS ===")
    scanner = IntradayNewsScannerService()
    top_stocks = await scanner.get_top_stocks(direction="all", limit=5)
    print(f"SCANNER: totalQualified={top_stocks.get('totalQualifiedStocks')}")
    for st in top_stocks.get("stocks", [])[:5]:
        sym = st.get("symbol")
        p = st.get("currentPrice")
        d_stat = st.get("dataStatus")
        conf = st.get("priceConfirmation")
        print(f"SCANNER STOCK {sym}: price={p} dataStatus={d_stat} priceConfirmation={conf}")

    print("\n=== ALL REAL LIVE / EOD CHECKS PASSED SUCCESSFULLY ===")


if __name__ == "__main__":
    asyncio.run(verify_endpoints())
