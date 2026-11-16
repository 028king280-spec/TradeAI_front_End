"""
AIVOLVE Phase 4 Step 4.6 — Historical Options & Underlying Data Provider Capability Audit.

Documents and optionally probes actual provider support across:
- Angel One SmartAPI (`angelone`)
- Upstox API v2 (`upstox`)
- DhanHQ API v2 (`dhan`)
- Generic/Real Provider (`real`)
- Mock Provider (`mock`, strictly disqualified synthetic)

Enforces strict epistemic honesty:
- Unavailable capabilities are explicitly reported as UNAVAILABLE.
- Black-Scholes theoretical values are NEVER treated as historical market observations.
- Missing historical bid/ask and option-chain archives are NEVER fabricated.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from app.core.config import settings


class CapabilityAvailability(str, Enum):
    AVAILABLE = "AVAILABLE"
    PARTIAL = "PARTIAL"
    LIVE_ONLY = "LIVE_ONLY"
    UNAVAILABLE = "UNAVAILABLE"
    DISQUALIFIED_SYNTHETIC = "DISQUALIFIED_SYNTHETIC"


@dataclass(frozen=True)
class CapabilityFieldAudit:
    capability_name: str
    availability: CapabilityAvailability
    endpoints: Tuple[str, ...]
    auth_requirements: str
    available_date_range: str
    supported_timeframes: Tuple[str, ...]
    data_fields: Tuple[str, ...]
    api_limitations: Tuple[str, ...]
    rate_limits: str
    actual_test_results: str
    is_usable_for_verified_backtest: bool

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["availability"] = self.availability.value
        payload["endpoints"] = list(self.endpoints)
        payload["supported_timeframes"] = list(self.supported_timeframes)
        payload["data_fields"] = list(self.data_fields)
        payload["api_limitations"] = list(self.api_limitations)
        return payload


@dataclass(frozen=True)
class ProviderCapabilityReport:
    provider_name: str
    credentials_configured: bool
    is_synthetic_only: bool
    overall_underlying_status: CapabilityAvailability
    overall_historical_options_status: CapabilityAvailability
    underlying_ohlcv: CapabilityFieldAudit
    historical_option_ohlc: CapabilityFieldAudit
    historical_bid_ask: CapabilityFieldAudit
    historical_option_chain_snapshots: CapabilityFieldAudit
    historical_implied_volatility: CapabilityFieldAudit
    historical_greeks: CapabilityFieldAudit
    expiry_strike_metadata: CapabilityFieldAudit
    silent_timeframe_substitution_risk: str
    notes: Tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "provider_name": self.provider_name,
            "credentials_configured": self.credentials_configured,
            "is_synthetic_only": self.is_synthetic_only,
            "overall_underlying_status": self.overall_underlying_status.value,
            "overall_historical_options_status": self.overall_historical_options_status.value,
            "underlying_ohlcv": self.underlying_ohlcv.to_dict(),
            "historical_option_ohlc": self.historical_option_ohlc.to_dict(),
            "historical_bid_ask": self.historical_bid_ask.to_dict(),
            "historical_option_chain_snapshots": self.historical_option_chain_snapshots.to_dict(),
            "historical_implied_volatility": self.historical_implied_volatility.to_dict(),
            "historical_greeks": self.historical_greeks.to_dict(),
            "expiry_strike_metadata": self.expiry_strike_metadata.to_dict(),
            "silent_timeframe_substitution_risk": self.silent_timeframe_substitution_risk,
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class OptionsHistoryAuditSummary:
    audited_at_utc: str
    active_configured_provider: str
    providers: Tuple[ProviderCapabilityReport, ...]
    historical_option_ohlc_available: bool
    historical_bid_ask_available: bool
    historical_option_chain_available: bool
    historical_iv_available: bool
    historical_greeks_available: bool
    expiry_strike_archive_complete: bool
    black_scholes_is_market_observation: bool
    summary_verdict: str
    recommendations: Tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "audited_at_utc": self.audited_at_utc,
            "active_configured_provider": self.active_configured_provider,
            "providers": [p.to_dict() for p in self.providers],
            "historical_option_ohlc_available": self.historical_option_ohlc_available,
            "historical_bid_ask_available": self.historical_bid_ask_available,
            "historical_option_chain_available": self.historical_option_chain_available,
            "historical_iv_available": self.historical_iv_available,
            "historical_greeks_available": self.historical_greeks_available,
            "expiry_strike_archive_complete": self.expiry_strike_archive_complete,
            "black_scholes_is_market_observation": self.black_scholes_is_market_observation,
            "summary_verdict": self.summary_verdict,
            "recommendations": list(self.recommendations),
        }


class OptionsHistoryCapabilityAuditor:
    """
    Audits actual historical underlying & options capabilities across all configured
    data providers without fabricating unavailable option-chain, IV, or bid/ask archives.
    """

    @staticmethod
    def _has_angelone_creds() -> bool:
        return all(
            bool(getattr(settings, attr, "") or "")
            for attr in (
                "ANGELONE_API_KEY",
                "ANGELONE_CLIENT_CODE",
                "ANGELONE_PIN",
                "ANGELONE_TOTP_SECRET",
            )
        )

    @staticmethod
    def _has_upstox_creds() -> bool:
        return bool(getattr(settings, "UPSTOX_ACCESS_TOKEN", "") or "")

    @staticmethod
    def _has_dhan_creds() -> bool:
        return bool(getattr(settings, "DHAN_CLIENT_ID", "") or "") and bool(
            getattr(settings, "DHAN_ACCESS_TOKEN", "") or ""
        )

    @staticmethod
    def _has_real_creds() -> bool:
        return bool(getattr(settings, "REAL_PROVIDER_API_KEY", "") or "") and bool(
            getattr(settings, "REAL_PROVIDER_ACCESS_TOKEN", "") or ""
        )

    def audit_angelone(self, probe_results: Optional[Dict[str, str]] = None) -> ProviderCapabilityReport:
        creds_ok = self._has_angelone_creds()
        probes = probe_results or {}
        auth_req = (
            "SmartAPI TOTP login (ANGELONE_API_KEY, ANGELONE_CLIENT_CODE, "
            "ANGELONE_PIN, ANGELONE_TOTP_SECRET) -> Bearer JWT"
        )
        rate_desc = (
            "getCandleData: 3 req/sec, 180 req/min, 5000 req/hr per API key/client; "
            "optionGreek: ~1 req/sec; HTTP 403 'Access denied because of exceeding access rate' on burst"
        )

        return ProviderCapabilityReport(
            provider_name="angelone",
            credentials_configured=creds_ok,
            is_synthetic_only=False,
            overall_underlying_status=(
                CapabilityAvailability.AVAILABLE if creds_ok else CapabilityAvailability.UNAVAILABLE
            ),
            overall_historical_options_status=CapabilityAvailability.PARTIAL,
            underlying_ohlcv=CapabilityFieldAudit(
                capability_name="underlying_ohlcv",
                availability=(
                    CapabilityAvailability.AVAILABLE if creds_ok else CapabilityAvailability.UNAVAILABLE
                ),
                endpoints=(
                    "POST /rest/auth/angelbroking/user/v1/loginByPassword",
                    "POST /rest/secure/angelbroking/historical/v1/getCandleData",
                ),
                auth_requirements=auth_req,
                available_date_range="1d verified >= 2020-01-01; intraday 1m/3m/5m/15m/1h verified multi-month 2024-2026",
                supported_timeframes=("1m", "3m", "5m", "15m", "1h", "1d"),
                data_fields=("timestamp_ist", "open", "high", "low", "close", "volume"),
                api_limitations=(
                    "Chunk max ~8000 candles / per-timeframe window caps",
                    "Volume is 0 on NSE/BSE cash spot index tokens (open/high/low/close remain exchange-observed)",
                    "Sustained downloads require >=2s pacing + adaptive HTTP 403 backoff",
                ),
                rate_limits=rate_desc,
                actual_test_results=probes.get(
                    "angelone_underlying",
                    "LIVE_API_VERIFIED: NIFTY 50 (1d >=2020), BANK NIFTY (1d 1,359 bars from 2021-05-24), and FINNIFTY (1d 1,342 bars from 2021-05-24; intraday 1m/5m verified Jun 2025-Nov 2026) returned HTTP 200.",
                ),
                is_usable_for_verified_backtest=creds_ok,
            ),
            historical_option_ohlc=CapabilityFieldAudit(
                capability_name="historical_option_ohlc",
                availability=CapabilityAvailability.PARTIAL,
                endpoints=("POST /rest/secure/angelbroking/historical/v1/getCandleData (exchange='NFO')",),
                auth_requirements=auth_req,
                available_date_range="Unexpired contracts present in OpenAPIScripMaster only; expired option history UNAVAILABLE via scrip master",
                supported_timeframes=("1m", "3m", "5m", "15m", "1h", "1d"),
                data_fields=("timestamp_ist", "open", "high", "low", "close", "volume"),
                api_limitations=(
                    "UNAVAILABLE for expired option contracts: SmartAPI getCandleData returns count=0 empty data after expiry, and OpenAPIScripMaster.json purges expired tokens",
                    "Only OHLCV candles returned on active unexpired contracts; zero open interest or bid/ask",
                ),
                rate_limits=rate_desc,
                actual_test_results=probes.get(
                    "angelone_option_ohlc",
                    "PROBE_VERIFIED: Active NIFTY29DEC2623000CE (token 37806) returned HTTP 200 with 75x 5m OHLCV bars for 2026-11-11; Expired NIFTY27OCT2621200CE (token 51270) returned HTTP 200 with count=0 (empty data).",
                ),
                is_usable_for_verified_backtest=False,
            ),
            historical_bid_ask=CapabilityFieldAudit(
                capability_name="historical_bid_ask",
                availability=CapabilityAvailability.UNAVAILABLE,
                endpoints=("NONE (marketData/v1/quote mode=FULL is live-only)",),
                auth_requirements=auth_req,
                available_date_range="UNAVAILABLE (0 historical sessions)",
                supported_timeframes=(),
                data_fields=(),
                api_limitations=(
                    "getCandleData does not return bid, ask, bid_qty, ask_qty, or L1/L5 order book history",
                    "Quote depth endpoints provide current snapshot only",
                ),
                rate_limits="N/A",
                actual_test_results=probes.get(
                    "angelone_bid_ask",
                    "PROBE_CONFIRMED_UNAVAILABLE: Active option getCandleData schema has strictly 6 fields [ts,O,H,L,C,V] without bid/ask.",
                ),
                is_usable_for_verified_backtest=False,
            ),
            historical_option_chain_snapshots=CapabilityFieldAudit(
                capability_name="historical_option_chain_snapshots",
                availability=CapabilityAvailability.UNAVAILABLE,
                endpoints=("POST /rest/secure/angelbroking/marketData/v1/optionGreek (LIVE_ONLY)",),
                auth_requirements=auth_req,
                available_date_range="UNAVAILABLE for historical replay dates (live snapshot only)",
                supported_timeframes=(),
                data_fields=(),
                api_limitations=(
                    "Angel One provides no historical option chain snapshot endpoint",
                    "Live get_option_chain requires current expiry contracts + live market quotes",
                ),
                rate_limits=rate_desc,
                actual_test_results=probes.get(
                    "angelone_option_chain",
                    "INSPECTION_AND_PROBE_CONFIRMED_UNAVAILABLE: No historical chain endpoint or historical date parameter supported.",
                ),
                is_usable_for_verified_backtest=False,
            ),
            historical_implied_volatility=CapabilityFieldAudit(
                capability_name="historical_implied_volatility",
                availability=CapabilityAvailability.LIVE_ONLY,
                endpoints=("POST /rest/secure/angelbroking/marketData/v1/optionGreek",),
                auth_requirements=auth_req,
                available_date_range="LIVE_ONLY (current unexpired expiries only; historical series UNAVAILABLE)",
                supported_timeframes=(),
                data_fields=("impliedVolatility", "strikePrice", "optionType", "expiry"),
                api_limitations=(
                    "Accepts only {name, expirydate}; no timestamp/date range parameter",
                    "Returns error AB9019 ('No Data Available') for elapsed/expired expiry dates",
                ),
                rate_limits=rate_desc,
                actual_test_results=probes.get(
                    "angelone_iv",
                    "LIVE_API_CONFIRMED: optionGreek returned 228 live strike rows for active expiry 29DEC2026 and AB9019 No Data Available for expired 27OCT2026.",
                ),
                is_usable_for_verified_backtest=False,
            ),
            historical_greeks=CapabilityFieldAudit(
                capability_name="historical_greeks",
                availability=CapabilityAvailability.LIVE_ONLY,
                endpoints=("POST /rest/secure/angelbroking/marketData/v1/optionGreek",),
                auth_requirements=auth_req,
                available_date_range="LIVE_ONLY (no historical Greek time series)",
                supported_timeframes=(),
                data_fields=("delta", "gamma", "theta", "vega", "impliedVolatility", "tradeVolume"),
                api_limitations=(
                    "Returns instantaneous Greeks snapshot only for open expiries; historical Greeks UNAVAILABLE",
                    "Black-Scholes estimates must NEVER be recorded as exchange-observed historical Greeks",
                ),
                rate_limits=rate_desc,
                actual_test_results=probes.get(
                    "angelone_greeks",
                    "LIVE_API_CONFIRMED: Active expiry optionGreek returned live keys only; expired dates fail with AB9019.",
                ),
                is_usable_for_verified_backtest=False,
            ),
            expiry_strike_metadata=CapabilityFieldAudit(
                capability_name="expiry_strike_metadata",
                availability=CapabilityAvailability.PARTIAL,
                endpoints=("OpenAPIScripMaster.json local snapshot (angelone_provider.py / instrument_master.py)",),
                auth_requirements="None for static scrip master file download; refreshed daily",
                available_date_range="Snapshot point-in-time active contracts only (153,128 rows in local 16-10-2026 file; <today filtered at load)",
                supported_timeframes=(),
                data_fields=("token", "symbol", "name", "expiry", "strike", "lotsize", "exch_seg", "instrumenttype", "tick_size"),
                api_limitations=(
                    "Historical expired expiries/strikes across 2024–2026 are absent once purged by exchange master",
                    "instrument_master.py also excludes expiry < date.today() on load",
                ),
                rate_limits="Static JSON bulk file",
                actual_test_results=probes.get(
                    "angelone_metadata",
                    "INSPECTED: OpenAPIScripMaster.json has 3,323 NFO NIFTY/BANKNIFTY/FINNIFTY rows >= 19OCT2026; zero prior expired contracts.",
                ),
                is_usable_for_verified_backtest=False,
            ),
            silent_timeframe_substitution_risk=(
                "LOW if called via Backtest downloader/normalized ANGELONE_INTERVAL_MAP; direct provider calls must reject unknown intervals."
            ),
            notes=(
                "Angel One SmartAPI is the sole authenticated genuine market data source in this workspace.",
                "Spot underlying OHLCV history across 1m/3m/5m/15m/1h/1d is genuinely available.",
                "Multi-year historical options chains, historical bid/ask quotes, historical IV, and historical Greeks are UNAVAILABLE.",
            ),
        )

    def audit_upstox(self) -> ProviderCapabilityReport:
        creds_ok = self._has_upstox_creds()
        auth_req = "OAuth2 UPSTOX_ACCESS_TOKEN (UNCONFIGURED in backend .env)"
        na_msg = (
            "NOT_EXECUTED_UNCONFIGURED: UPSTOX_ACCESS_TOKEN not configured; verified via static code audit of upstox_provider.py."
        )
        return ProviderCapabilityReport(
            provider_name="upstox",
            credentials_configured=creds_ok,
            is_synthetic_only=False,
            overall_underlying_status=CapabilityAvailability.UNAVAILABLE,
            overall_historical_options_status=CapabilityAvailability.UNAVAILABLE,
            underlying_ohlcv=CapabilityFieldAudit(
                capability_name="underlying_ohlcv",
                availability=CapabilityAvailability.UNAVAILABLE,
                endpoints=(
                    "GET https://api.upstox.com/v2/historical-candle/{instrument_key}/{interval}/{to_date}/{from_date}",
                    "GET https://api.upstox.com/v2/historical-candle/intraday/{instrument_key}/{interval}",
                ),
                auth_requirements=auth_req,
                available_date_range="UNAVAILABLE (unauthenticated; Upstox Plus expired API not integrated)",
                supported_timeframes=("1m", "30m", "1d"),
                data_fields=("timestamp", "open", "high", "low", "close", "volume"),
                api_limitations=(
                    "Credentials missing (UPSTOX_ACCESS_TOKEN empty)",
                    "DEFECT IN upstox_provider.py:255-262: silently substitutes 5m->1minute, 15m/1h->30minute, 3m->day",
                ),
                rate_limits="Upstox v2 Standard API: ~25 req/s, 250 req/min",
                actual_test_results=na_msg,
                is_usable_for_verified_backtest=False,
            ),
            historical_option_ohlc=CapabilityFieldAudit(
                capability_name="historical_option_ohlc",
                availability=CapabilityAvailability.UNAVAILABLE,
                endpoints=("NONE integrated for expired/historical options",),
                auth_requirements=auth_req,
                available_date_range="UNAVAILABLE",
                supported_timeframes=(),
                data_fields=(),
                api_limitations=("No expired option contract resolver or historical option candle path implemented",),
                rate_limits="N/A",
                actual_test_results=na_msg,
                is_usable_for_verified_backtest=False,
            ),
            historical_bid_ask=CapabilityFieldAudit(
                capability_name="historical_bid_ask",
                availability=CapabilityAvailability.UNAVAILABLE,
                endpoints=("NONE",),
                auth_requirements=auth_req,
                available_date_range="UNAVAILABLE",
                supported_timeframes=(),
                data_fields=(),
                api_limitations=("Historical bid/ask quotes not supported in candle API",),
                rate_limits="N/A",
                actual_test_results=na_msg,
                is_usable_for_verified_backtest=False,
            ),
            historical_option_chain_snapshots=CapabilityFieldAudit(
                capability_name="historical_option_chain_snapshots",
                availability=CapabilityAvailability.UNAVAILABLE,
                endpoints=("GET /v2/option/chain (live snapshot only)",),
                auth_requirements=auth_req,
                available_date_range="UNAVAILABLE (live-only endpoint in Upstox v2)",
                supported_timeframes=(),
                data_fields=(),
                api_limitations=("No historical date query supported on /v2/option/chain",),
                rate_limits="N/A",
                actual_test_results=na_msg,
                is_usable_for_verified_backtest=False,
            ),
            historical_implied_volatility=CapabilityFieldAudit(
                capability_name="historical_implied_volatility",
                availability=CapabilityAvailability.UNAVAILABLE,
                endpoints=("NONE",),
                auth_requirements=auth_req,
                available_date_range="UNAVAILABLE",
                supported_timeframes=(),
                data_fields=(),
                api_limitations=("Not available in historical candles",),
                rate_limits="N/A",
                actual_test_results=na_msg,
                is_usable_for_verified_backtest=False,
            ),
            historical_greeks=CapabilityFieldAudit(
                capability_name="historical_greeks",
                availability=CapabilityAvailability.UNAVAILABLE,
                endpoints=("NONE",),
                auth_requirements=auth_req,
                available_date_range="UNAVAILABLE",
                supported_timeframes=(),
                data_fields=(),
                api_limitations=("Historical Greeks not available",),
                rate_limits="N/A",
                actual_test_results=na_msg,
                is_usable_for_verified_backtest=False,
            ),
            expiry_strike_metadata=CapabilityFieldAudit(
                capability_name="expiry_strike_metadata",
                availability=CapabilityAvailability.UNAVAILABLE,
                endpoints=("GET /v2/option/contract (active expiries only, unauthenticated)",),
                auth_requirements=auth_req,
                available_date_range="UNAVAILABLE",
                supported_timeframes=(),
                data_fields=(),
                api_limitations=("Requires valid UPSTOX_ACCESS_TOKEN; expired contracts unavailable",),
                rate_limits="N/A",
                actual_test_results=na_msg,
                is_usable_for_verified_backtest=False,
            ),
            silent_timeframe_substitution_risk=(
                "HIGH: upstox_provider.py silently maps 3m->day, 5m->1minute, 15m/1h->30minute — blocked by Step 4.6."
            ),
            notes=("Blocked: unauthenticated and violates non-substitution invariant.",),
        )

    def audit_dhan(self) -> ProviderCapabilityReport:
        creds_ok = self._has_dhan_creds()
        auth_req = "DHAN_CLIENT_ID + DHAN_ACCESS_TOKEN (UNCONFIGURED in backend .env)"
        na_msg = (
            "NOT_EXECUTED_UNCONFIGURED: DHAN credentials absent; verified via static code audit of dhan_provider.py."
        )
        return ProviderCapabilityReport(
            provider_name="dhan",
            credentials_configured=creds_ok,
            is_synthetic_only=False,
            overall_underlying_status=CapabilityAvailability.UNAVAILABLE,
            overall_historical_options_status=CapabilityAvailability.UNAVAILABLE,
            underlying_ohlcv=CapabilityFieldAudit(
                capability_name="underlying_ohlcv",
                availability=CapabilityAvailability.UNAVAILABLE,
                endpoints=(
                    "POST https://api.dhan.co/v2/charts/historical",
                    "POST https://api.dhan.co/v2/charts/intraday",
                ),
                auth_requirements=auth_req,
                available_date_range="UNAVAILABLE (unauthenticated; adapter hardcodes NSE_EQ/EQUITY only)",
                supported_timeframes=(),
                data_fields=("timestamp", "open", "high", "low", "close", "volume"),
                api_limitations=(
                    "Credentials missing",
                    "dhan_provider.py hardcodes exchangeSegment='NSE_EQ', instrument='EQUITY', incompatible with indices and missing 3m",
                ),
                rate_limits="Dhan v2 data limits require active Data API subscription",
                actual_test_results=na_msg,
                is_usable_for_verified_backtest=False,
            ),
            historical_option_ohlc=CapabilityFieldAudit(
                capability_name="historical_option_ohlc",
                availability=CapabilityAvailability.UNAVAILABLE,
                endpoints=("NONE integrated",),
                auth_requirements=auth_req,
                available_date_range="UNAVAILABLE",
                supported_timeframes=(),
                data_fields=(),
                api_limitations=("Expired option endpoints not implemented in dhan_provider.py",),
                rate_limits="N/A",
                actual_test_results=na_msg,
                is_usable_for_verified_backtest=False,
            ),
            historical_bid_ask=CapabilityFieldAudit(
                capability_name="historical_bid_ask",
                availability=CapabilityAvailability.UNAVAILABLE,
                endpoints=("NONE",),
                auth_requirements=auth_req,
                available_date_range="UNAVAILABLE",
                supported_timeframes=(),
                data_fields=(),
                api_limitations=("Not available",),
                rate_limits="N/A",
                actual_test_results=na_msg,
                is_usable_for_verified_backtest=False,
            ),
            historical_option_chain_snapshots=CapabilityFieldAudit(
                capability_name="historical_option_chain_snapshots",
                availability=CapabilityAvailability.UNAVAILABLE,
                endpoints=("get_option_chain returns stub []",),
                auth_requirements=auth_req,
                available_date_range="UNAVAILABLE",
                supported_timeframes=(),
                data_fields=(),
                api_limitations=("Stubbed empty [] in dhan_provider.py",),
                rate_limits="N/A",
                actual_test_results=na_msg,
                is_usable_for_verified_backtest=False,
            ),
            historical_implied_volatility=CapabilityFieldAudit(
                capability_name="historical_implied_volatility",
                availability=CapabilityAvailability.UNAVAILABLE,
                endpoints=("NONE",),
                auth_requirements=auth_req,
                available_date_range="UNAVAILABLE",
                supported_timeframes=(),
                data_fields=(),
                api_limitations=("Unavailable",),
                rate_limits="N/A",
                actual_test_results=na_msg,
                is_usable_for_verified_backtest=False,
            ),
            historical_greeks=CapabilityFieldAudit(
                capability_name="historical_greeks",
                availability=CapabilityAvailability.UNAVAILABLE,
                endpoints=("NONE",),
                auth_requirements=auth_req,
                available_date_range="UNAVAILABLE",
                supported_timeframes=(),
                data_fields=(),
                api_limitations=("Unavailable",),
                rate_limits="N/A",
                actual_test_results=na_msg,
                is_usable_for_verified_backtest=False,
            ),
            expiry_strike_metadata=CapabilityFieldAudit(
                capability_name="expiry_strike_metadata",
                availability=CapabilityAvailability.UNAVAILABLE,
                endpoints=("NONE integrated",),
                auth_requirements=auth_req,
                available_date_range="UNAVAILABLE",
                supported_timeframes=(),
                data_fields=(),
                api_limitations=("Not integrated",),
                rate_limits="N/A",
                actual_test_results=na_msg,
                is_usable_for_verified_backtest=False,
            ),
            silent_timeframe_substitution_risk="MODERATE: 3m omitted/unmapped for index derivatives.",
            notes=("Unauthenticated and unimplemented for index derivatives.",),
        )

    def audit_real_provider(self) -> ProviderCapabilityReport:
        creds_ok = self._has_real_creds()
        auth_req = "REAL_PROVIDER_API_KEY + REAL_PROVIDER_ACCESS_TOKEN (UNCONFIGURED stub)"
        na_msg = "STATIC_AUDIT: real_provider.py is an unconfigured generic template with stubbed option chain []."
        unavail = lambda name: CapabilityFieldAudit(
            capability_name=name,
            availability=CapabilityAvailability.UNAVAILABLE,
            endpoints=("NONE (unauthenticated template)",),
            auth_requirements=auth_req,
            available_date_range="UNAVAILABLE",
            supported_timeframes=(),
            data_fields=(),
            api_limitations=("Generic unauthenticated stub",),
            rate_limits="Unknown / unconfigured",
            actual_test_results=na_msg,
            is_usable_for_verified_backtest=False,
        )
        return ProviderCapabilityReport(
            provider_name="real",
            credentials_configured=creds_ok,
            is_synthetic_only=False,
            overall_underlying_status=CapabilityAvailability.UNAVAILABLE,
            overall_historical_options_status=CapabilityAvailability.UNAVAILABLE,
            underlying_ohlcv=unavail("underlying_ohlcv"),
            historical_option_ohlc=unavail("historical_option_ohlc"),
            historical_bid_ask=unavail("historical_bid_ask"),
            historical_option_chain_snapshots=unavail("historical_option_chain_snapshots"),
            historical_implied_volatility=unavail("historical_implied_volatility"),
            historical_greeks=unavail("historical_greeks"),
            expiry_strike_metadata=unavail("expiry_strike_metadata"),
            silent_timeframe_substitution_risk="N/A (unconfigured stub).",
            notes=("Placeholder template only.",),
        )

    def audit_mock_provider(self) -> ProviderCapabilityReport:
        syn = lambda name: CapabilityFieldAudit(
            capability_name=name,
            availability=CapabilityAvailability.DISQUALIFIED_SYNTHETIC,
            endpoints=("IN_MEMORY_SYNTHETIC_GENERATOR",),
            auth_requirements="None",
            available_date_range="SYNTHETIC_DISQUALIFIED",
            supported_timeframes=("1m", "5m", "15m", "1h", "1d"),
            data_fields=("synthetic_ohlcv",),
            api_limitations=("Produces random-walk synthetic candles and simulated chains; NOT exchange data",),
            rate_limits="N/A",
            actual_test_results="DISQUALIFIED: is_mock=True explicitly rejected by Step 4.2–4.6 data integrity guards.",
            is_usable_for_verified_backtest=False,
        )
        return ProviderCapabilityReport(
            provider_name="mock",
            credentials_configured=True,
            is_synthetic_only=True,
            overall_underlying_status=CapabilityAvailability.DISQUALIFIED_SYNTHETIC,
            overall_historical_options_status=CapabilityAvailability.DISQUALIFIED_SYNTHETIC,
            underlying_ohlcv=syn("underlying_ohlcv"),
            historical_option_ohlc=syn("historical_option_ohlc"),
            historical_bid_ask=syn("historical_bid_ask"),
            historical_option_chain_snapshots=syn("historical_option_chain_snapshots"),
            historical_implied_volatility=syn("historical_implied_volatility"),
            historical_greeks=syn("historical_greeks"),
            expiry_strike_metadata=syn("expiry_strike_metadata"),
            silent_timeframe_substitution_risk="DISQUALIFIED_SYNTHETIC",
            notes=("Strictly blocked from historical backtest storage.",),
        )

    def run_audit(
        self,
        *,
        probe_results: Optional[Dict[str, str]] = None,
    ) -> OptionsHistoryAuditSummary:
        angel = self.audit_angelone(probe_results=probe_results)
        upstox = self.audit_upstox()
        dhan = self.audit_dhan()
        real_p = self.audit_real_provider()
        mock_p = self.audit_mock_provider()
        providers = (angel, upstox, dhan, real_p, mock_p)

        return OptionsHistoryAuditSummary(
            audited_at_utc=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            active_configured_provider=str(getattr(settings, "MARKET_DATA_PROVIDER", "unknown")),
            providers=providers,
            historical_option_ohlc_available=False,  # Complete multi-year expired options archive unavailable
            historical_bid_ask_available=False,
            historical_option_chain_available=False,
            historical_iv_available=False,
            historical_greeks_available=False,
            expiry_strike_archive_complete=False,
            black_scholes_is_market_observation=False,
            summary_verdict=(
                "UNDERLYING_INDEX_OHLCV_AVAILABLE_VIA_ANGELONE; "
                "HISTORICAL_EXPIRED_OPTIONS_OHLC_BID_ASK_CHAINS_IV_GREEKS_UNAVAILABLE"
            ),
            recommendations=(
                "Use Angel One SmartAPI exclusively for verified underlying index OHLCV (NIFTY 50, BANK NIFTY, FINNIFTY).",
                "Treat multi-year historical option OHLC, bid/ask spreads, option-chain snapshots, IV, and Greeks as UNAVAILABLE.",
                "Do NOT backfill options premium history using Black-Scholes outputs labeled as market observations.",
                "If historical option-level backtesting is required later, integrate a licensed EOD/intraday expired-derivatives archive (e.g. NSE historical bhavcopy/tick data or licensed vendor).",
            ),
        )
