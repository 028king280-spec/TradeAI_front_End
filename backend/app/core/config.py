from typing import List
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    APP_ENV: str = "development"
    APP_NAME: str = "AIVOLVE Trading AI"
    DEBUG: bool = True

    @field_validator("DEBUG", mode="before")
    @classmethod
    def parse_debug(cls, v):
        if isinstance(v, str):
            if v.strip().lower() in ("release", "prod", "production", "false", "0", "no"):
                return False
            if v.strip().lower() in ("debug", "dev", "development", "true", "1", "yes"):
                return True
        return bool(v)

    PORT: int = 8000
    HOST: str = "0.0.0.0"

    # CORS
    CORS_ORIGINS: str = "http://localhost:3000,http://127.0.0.1:3000,https://trade.aivolvetech.in,https://tradeai.aivolvetech.in"

    @property
    def cors_origins_list(self) -> List[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]

    # Database
    DATABASE_URL: str = "sqlite+aiosqlite:///./aivolve_trading.db"
    SYNC_DATABASE_URL: str = "sqlite:///./aivolve_trading.db"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # Market Data Provider ("angelone" | "upstox" | "dhan" | "mock")
    MARKET_DATA_PROVIDER: str = "angelone"
    MARKET_API_KEY: str = ""
    MARKET_API_SECRET: str = ""
    MARKET_API_BASE_URL: str = "https://api.kite.trade"

    # Upstox API v2 Credentials
    UPSTOX_ACCESS_TOKEN: str = ""
    UPSTOX_CLIENT_ID: str = ""
    UPSTOX_CLIENT_SECRET: str = ""
    UPSTOX_REDIRECT_URI: str = "http://localhost:8000/api/auth/upstox/callback"
    UPSTOX_ANALYTICS_TOKEN: str = ""
    UPSTOX_BASE_URL: str = "https://api.upstox.com/v2"

    # DhanHQ Specific Credentials (Optional Secondary Provider)
    DHAN_CLIENT_ID: str = ""
    DHAN_ACCESS_TOKEN: str = ""
    DHAN_BASE_URL: str = "https://api.dhan.co/v2"

    # Security & API Authorization (Workstream B2 & D)
    OPERATOR_SECRET_KEY: str = "aivolve-internal-operator"
    ML_GOVERNANCE_SECRET_KEY: str = ""

    # Angel One SmartAPI Credentials
    ANGELONE_API_KEY: str = ""
    ANGELONE_CLIENT_CODE: str = ""
    ANGELONE_PIN: str = ""
    ANGELONE_TOTP_SECRET: str = ""
    ANGELONE_BASE_URL: str = "https://apiconnect.angelbroking.com"
    ANGELONE_WS_URL: str = "wss://smartapisocket.angelone.in/smart-stream"

    # AI & LLM Explanation
    AI_PROVIDER: str = "arcee"
    AI_API_KEY: str = ""
    AI_MODEL: str = "trinity-large-thinking"
    AI_TEMPERATURE: float = 0.2

    # Arcee AI Specific
    ARCEE_API_KEY: str = ""
    ARCEE_BASE_URL: str = "https://api.arcee.ai/api/v1"
    ARCEE_MODEL: str = "trinity-large-thinking"

    # News Provider
    NEWS_PROVIDER: str = "mock"
    NEWS_API_KEY: str = ""
    NEWS_API_BASE_URL: str = "https://newsapi.org/v2"

    # Indian Market Hours (IST)
    MARKET_TIMEZONE: str = "Asia/Kolkata"
    MARKET_OPEN_TIME: str = "09:15"
    MARKET_CLOSE_TIME: str = "15:30"

    # Scoring & Qualification Thresholds
    QUALIFICATION_SCORE_THRESHOLD: int = 80
    PUT_QUALIFICATION_SCORE_THRESHOLD: int = 75
    WATCH_SCORE_THRESHOLD: int = 60

    LOG_LEVEL: str = "INFO"


settings = Settings()
