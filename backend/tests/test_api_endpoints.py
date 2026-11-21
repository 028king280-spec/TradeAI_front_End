import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app


@pytest.mark.asyncio
async def test_health_endpoint():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/api/health")
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        assert data["data"]["status"] == "healthy"
        assert data["data"]["provider"] in ["upstox", "mock", "real", "dhan", "angelone"]


@pytest.mark.asyncio
async def test_market_overview():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/api/market/overview")
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        assert len(data["data"]) >= 4
        symbols = [idx["symbol"] for idx in data["data"]]
        assert "NIFTY 50" in symbols


@pytest.mark.asyncio
async def test_market_live_endpoint():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/api/market/live")
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        assert "indices" in data["data"]
        assert "sentiment" in data["data"]
        assert data["dataStatus"] in ["LIVE", "MOCK", "STALE", "UNAVAILABLE", "MARKET_CLOSED"]


@pytest.mark.asyncio
async def test_stock_search():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/api/stocks/search?q=RELIANCE")
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        assert len(data["data"]) >= 1
        assert data["data"][0]["symbol"] == "RELIANCE"


@pytest.mark.asyncio
async def test_stock_quote_endpoint():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/api/stocks/RELIANCE/quote")
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        assert data["data"]["symbol"] == "RELIANCE"
        assert data["dataStatus"] in ["LIVE", "MOCK", "STALE", "UNAVAILABLE", "MARKET_CLOSED"]


@pytest.mark.asyncio
async def test_stock_candles_endpoint():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/api/stocks/RELIANCE/candles?timeframe=15m&limit=20")
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        assert isinstance(data["data"], list)


@pytest.mark.asyncio
async def test_stock_analysis_endpoint():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/api/stocks/RELIANCE/analysis")
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        payload = data["data"]
        assert payload["symbol"] == "RELIANCE"
        assert "expectedHigh" in payload
        assert "expectedLow" in payload
        assert "probabilities" in payload
        assert "technicalIndicators" in payload
        assert "aiInsights" in payload
        assert "chartData" in payload
        assert "dataStatus" in payload


@pytest.mark.asyncio
async def test_stock_ai_insights_endpoint():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/api/stocks/RELIANCE/ai-insights")
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        assert "headlineQuestion" in data["data"]


@pytest.mark.asyncio
async def test_signals_today_endpoint():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/api/signals/today")
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        assert "calls" in data["data"]
        assert "puts" in data["data"]
