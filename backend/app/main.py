import time
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError

from app.core.config import settings
from app.core.logging import logger
from app.db.database import init_db
from app.jobs.market_refresh import start_scheduler, scheduler
from app.api.routes import health, market, stocks, analysis, ai, signals, knowledge, ml, options, news, performance
from app.api.routes import live_stream, paper_trading, macro, post_market


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info(f"Starting {settings.APP_NAME} in {settings.APP_ENV} mode...")
    try:
        await init_db()
        logger.info("Database schemas initialized successfully")
    except Exception as e:
        logger.error(f"Database initialization notice: {e}")

    try:
        start_scheduler()
    except Exception as e:
        logger.warning(f"Scheduler start warning: {e}")

    # Start live streaming WebSocket manager based on active provider
    provider_mode = settings.MARKET_DATA_PROVIDER.lower()
    if provider_mode in ["angelone", "smartapi", "angel"]:
        try:
            from app.data.providers.angelone_provider import AngelOneMarketDataProvider
            from app.data.providers.angelone_websocket import angelone_ws_manager
            from app.data.providers.factory import get_market_data_provider

            # Ensure provider login happens first
            provider = get_market_data_provider()
            if isinstance(provider, AngelOneMarketDataProvider):
                login_ok = await provider.login()
                if login_ok and provider.feed_token:
                    angelone_ws_manager.set_tokens(provider.feed_token, provider.jwt_token)
                    await angelone_ws_manager.start()
                    logger.info("✅ Angel One SmartStream WebSocket started.")
                else:
                    logger.warning("Angel One login incomplete — WebSocket not started. Check credentials in .env")
        except Exception as e:
            logger.warning(f"Angel One WebSocket start notice: {e}")
    else:
        try:
            from app.data.providers.upstox_websocket import ws_manager
            await ws_manager.start()
        except Exception as e:
            logger.warning(f"Upstox WebSocket manager start notice: {e}")

    yield

    # Shutdown
    logger.info("Shutting down AIVOLVE Trading AI backend...")
    if provider_mode in ["angelone", "smartapi", "angel"]:
        try:
            from app.data.providers.angelone_websocket import angelone_ws_manager
            await angelone_ws_manager.stop()
        except Exception:
            pass
    else:
        try:
            from app.data.providers.upstox_websocket import ws_manager
            await ws_manager.stop()
        except Exception:
            pass

    if scheduler.running:
        scheduler.shutdown()


app = FastAPI(
    title="AIVOLVE Trading AI — Market Analysis & ML Quant Engine",
    description="Institutional-grade Indian Stock Market (NSE/BSE) Analysis Platform, RAG Knowledge System & ML Lab.",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS Middleware
origins = list(set([
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:3001",
    "http://127.0.0.1:3001",
    *(settings.cors_origins_list or []),
]))

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Request timing & audit middleware
@app.middleware("http")
async def add_process_time_and_log(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    process_time = round((time.time() - start_time) * 1000, 2)
    response.headers["X-Process-Time-Ms"] = str(process_time)
    logger.info(
        f"{request.method} {request.url.path} responded {response.status_code} in {process_time}ms"
    )
    return response


# Global Exception Handlers for consistent JSON contracts
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "success": False,
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "Invalid request payload parameters",
                "details": exc.errors(),
            },
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        },
    )


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled error on {request.method} {request.url.path}: {exc}", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "success": False,
            "error": {
                "code": "INTERNAL_SERVER_ERROR",
                "message": str(exc),
            },
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        },
    )


# Include Routers with /api prefix
app.include_router(health.router, prefix="/api")
app.include_router(market.router, prefix="/api")
app.include_router(stocks.router, prefix="/api")
app.include_router(analysis.router, prefix="/api")
app.include_router(analysis.direct_analysis_router, prefix="/api")
app.include_router(ai.router, prefix="/api")
app.include_router(signals.router, prefix="/api")
app.include_router(knowledge.router, prefix="/api")
app.include_router(ml.router, prefix="/api")
app.include_router(options.router, prefix="/api")
app.include_router(news.router, prefix="/api")
app.include_router(performance.router, prefix="/api")
app.include_router(live_stream.router, prefix="/api")
app.include_router(macro.router, prefix="/api")
app.include_router(post_market.router, prefix="/api")
app.include_router(paper_trading.router)


@app.get("/")
async def root():
    return {
        "service": settings.APP_NAME,
        "market": "INDIA (NSE/BSE)",
        "docs": "/docs",
        "health": "/api/health",
        "provider": settings.MARKET_DATA_PROVIDER,
    }
