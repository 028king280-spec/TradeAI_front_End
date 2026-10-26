# AIVOLVE Trading AI — Backend & Real Market Analysis Engine

Institutional-grade Indian Stock Market (NSE / BSE) analysis platform, deterministic quantitative calculation pipeline, RAG knowledge system, and time-series Machine Learning Model Lab.

**Domain**: `trade.aivolvetech.in`  
**Target Market**: India Only (NSE / BSE Equities & Derivatives)

---

## 🏛️ Core Architectural Mandate

1. **Deterministic Calculations Only**: All numerical values (support/resistance, expected high/low, probabilities, technical indicators, scores) are strictly computed from real market OHLCV data by the Python Quantitative Engine.
2. **Zero LLM Hallucinations**: The LLM is strictly an explanation and knowledge synthesis layer. It is forbidden from inventing prices, targets, indicators, probabilities, or news.
3. **Module 7 Clean Separation**:
   - **Quant Engine**: Deterministic financial calculations.
   - **RAG Knowledge System**: Vector search across uploaded trading literature (PDF/TXT) using pgvector / cosine similarity.
   - **ML Model Lab**: Time-series aware model training (Random Forest, Gradient Boosting, MLP) with walk-forward validation, zero lookahead bias, and economic backtesting (slippage + brokerage).
   - **AI Explanation Layer**: Synthesizes an audited evidence package (Market + Quant + ML + RAG Knowledge).

---

## 📂 Project Structure

```
aivolve-trading-ai/
├── backend/
│   ├── app/
│   │   ├── api/
│   │   │   └── routes/
│   │   │       ├── health.py        # GET /api/health
│   │   │       ├── market.py        # GET /api/market/overview, /indices, /sectors, /drivers
│   │   │       ├── stocks.py        # GET /api/stocks/search, /api/stocks/{symbol}
│   │   │       ├── analysis.py      # GET /api/stocks/{symbol}/analysis, /technical, /scenarios
│   │   │       ├── ai.py            # GET /api/stocks/{symbol}/ai-insights
│   │   │       ├── signals.py       # GET /api/signals/today, /calls, /puts
│   │   │       ├── knowledge.py     # Module 7: POST /api/knowledge/upload, /search, /documents
│   │   │       └── ml.py            # Module 7: POST /api/ml/train, /backtest, /models/{ver}/promote
│   │   ├── core/
│   │   │   ├── config.py            # Pydantic Settings
│   │   │   ├── logging.py           # Structured JSON logging
│   │   │   ├── security.py          # Input sanitization & security rules
│   │   │   └── cache.py             # Redis + In-Memory TTL fallback
│   │   ├── data/
│   │   │   ├── market_calendar.py   # Indian Market Hours (09:15-15:30 IST) & NSE Holidays
│   │   │   ├── news_provider.py     # Mock & Real news provider abstraction
│   │   │   └── providers/
│   │   │       ├── base.py          # MarketDataProvider interface
│   │   │       ├── mock_provider.py # Deterministic NIFTY 50 Indian universe
│   │   │       ├── real_provider.py # Kite Connect / Upstox / Dhan API client
│   │   │       └── factory.py       # Provider selector
│   │   ├── analysis/
│   │   │   ├── technical.py         # RSI, MACD, EMA 20/50/200, VWAP, ATR, Volume, Momentum
│   │   │   ├── support_resistance.py# Camarilla, Classic Pivots, 20D Swings, ATR bands
│   │   │   ├── market_context.py    # NIFTY 50, BANK NIFTY, India VIX, Market Breadth
│   │   │   ├── sector_analysis.py   # Sector relative strength & performance
│   │   │   ├── expected_range.py    # Probability-based Intraday High/Low Engine
│   │   │   ├── probability.py       # Model-estimated upside/downside probabilities
│   │   │   ├── scenarios.py         # Bullish, Base, Bearish scenario generator
│   │   │   ├── scoring.py           # 100-point multi-factor quantitative scoring
│   │   │   └── qualification.py     # Strict candidate qualification (No forced 5+5)
│   │   ├── rag/
│   │   │   ├── document_processor.py# PDF & TXT extraction, page tracking, chunking
│   │   │   ├── embeddings.py        # 128-d dense semantic embeddings & cosine similarity
│   │   │   └── vector_store.py      # Vector storage and similarity search
│   │   ├── ml/
│   │   │   ├── features.py          # Leak-free feature engineering
│   │   │   ├── validation.py        # Chronological time-series train/val/test split
│   │   │   ├── models.py            # Logistic Regression, Random Forest, GBDT, MLP
│   │   │   ├── backtest.py          # Institutional backtester (slippage + brokerage)
│   │   │   ├── registry.py          # Model states & promotion gates
│   │   │   └── trainer.py           # Asynchronous training runner
│   │   ├── models/db_models.py      # SQLAlchemy PostgreSQL / SQLite models
│   │   ├── schemas/                 # Pydantic schemas matching Next.js types
│   │   ├── services/                # Business services
│   │   ├── jobs/market_refresh.py   # APScheduler pre-market, intraday, post-market
│   │   └── main.py                  # FastAPI application entrypoint
│   ├── tests/                       # 21 Pytest unit & integration tests
│   ├── requirements.txt
│   ├── Dockerfile
│   └── .env.example
├── src/                             # Next.js 16 v0 Frontend
│   ├── lib/api.ts                   # Type-safe API client with offline fallback
│   ├── services/marketDataService.ts# Seamless integration layer
│   └── components/layout/TopHeader.tsx # Displays LIVE DATA / MOCK DATA badge
├── docker-compose.yml               # Multi-container orchestration
└── README.md
```

---

## 🚀 Local Development (7 Step Setup)

### 1. Install Dependencies
```powershell
# Backend (Python 3.12+)
cd backend
.venv\Scripts\activate
pip install -r requirements.txt

# Frontend (Next.js 16)
cd ..
npm install
```

### 2. Configure .env
```powershell
cd backend
copy .env.example .env
```

### 3. Add Upstox Token
Open `backend/.env` and configure your official Upstox Developer API credentials:
```env
UPSTOX_ACCESS_TOKEN=your_upstox_access_token_here
UPSTOX_CLIENT_ID=your_client_id_here
UPSTOX_CLIENT_SECRET=your_client_secret_here
MARKET_DATA_PROVIDER=upstox
```
*(If credentials are not yet configured, the system automatically runs in development mode with `dataStatus: "MOCK"`, never faking live connectivity).*

### 4. Start Backend
```powershell
cd backend
python -m uvicorn app.main:app --reload --port 8000
```
API Documentation available at: `http://localhost:8000/docs`

### 5. Start Frontend
```powershell
# From project root (aivolve-trading-ai)
$env:NEXT_PUBLIC_API_BASE_URL = "http://localhost:8000"
npm run dev
```
Open `http://localhost:3000` in your browser.

### 6. Verify Live Market Connection
- Health status: `GET http://localhost:8000/api/health`
- Live market feed & breadth: `GET http://localhost:8000/api/market/live`
- Top qualified setups: `GET http://localhost:8000/api/signals/today`
- In Next.js: Verify the header badge shows `LIVE DATA` with timestamp when authenticated, or `MOCK DATA` when offline.

### 7. Run Tests
```powershell
# Backend Pytest suite
cd backend
pytest -v

# Frontend TypeScript & Build verification
cd ..
npm run build
npm run lint
```

---

## 🐳 Docker Compose Deployment

To run the complete platform (Frontend, Backend, PostgreSQL with pgvector, and Redis) in Docker:

```powershell
docker-compose up --build -d
```

| Service | Port | Description |
| :--- | :--- | :--- |
| **Frontend** | `3000` | Next.js 16 UI |
| **Backend** | `8000` | FastAPI Quantitative Analysis Engine |
| **PostgreSQL** | `5432` | Database with `pgvector` extension |
| **Redis** | `6379` | Cache for market data & analysis runs |

---

## 🧪 Automated Testing

The platform includes full test coverage across all quantitative engines, ML lab, and API endpoints:

```powershell
cd backend
.venv\Scripts\pytest.exe -v
```

Test suite covers:
- Mathematical accuracy of RSI, MACD, EMA, VWAP, and ATR
- Support & Resistance pivot and swing level calculations
- Expected Range probability boundaries (`extremeLow < likelyLow <= currentPrice <= likelyHigh < extremeHigh`)
- 100-point deterministic scoring model
- Candidate qualification (strictly prevents forcing 5+5 candidates)
- Time-series cross-validation (prohibiting random future lookahead shuffling)
- Machine Learning training, metrics, and economic backtesting
- Document chunking, dense vector embeddings, and cosine similarity search
- FastAPI endpoint responses and error status codes

---

## 🌐 Production Deployment Architecture (`trade.aivolvetech.in`)

```
                         Cloudflare / DNS (trade.aivolvetech.in)
                                      │
                 ┌────────────────────┴────────────────────┐
                 │                                         │
                 ▼                                         ▼
         Vercel Edge Network                     Containerized FastAPI
        (Next.js 16 Frontend)                      (AWS ECS / GCP Cloud Run)
                 │                                         │
                 │                                         ▼
                 └───────────────────────────────► Managed PostgreSQL (AWS RDS)
                                                 + Managed Redis (AWS ElastiCache)
```

1. **Frontend**: Deploy `aivolve-trading-ai` on Vercel. Set `NEXT_PUBLIC_API_BASE_URL=https://api.trade.aivolvetech.in`.
2. **Backend**: Build and deploy `backend/Dockerfile` to AWS ECS or GCP Cloud Run. Set production environment variables (`DATABASE_URL`, `REDIS_URL`, `MARKET_DATA_PROVIDER=real`, `MARKET_API_KEY`, etc.).
3. **Database**: Managed PostgreSQL with `pgvector` enabled (`CREATE EXTENSION vector;`).
4. **Redis**: Managed AWS ElastiCache / Redis Cloud instance.
