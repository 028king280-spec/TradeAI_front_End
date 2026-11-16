"""
Focused P0 Live-Data Reliability Regression Suite
===================================================
Covers the three P0 remediation targets from the 11-Nov-2026 live observation audit:
1. Angel One SmartAPI v2 WebSocket binary packet decoding & fail-closed validation.
2. Timeframe-aware incomplete/forming candle filtering & no-lookahead guarantees.
3. Elimination of silent synthetic/mock fallback contamination across providers & routes.
"""

import json
import math
import struct
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pandas as pd
import pytest
from httpx import ASGITransport, AsyncClient

from app.data.providers.angelone_provider import AngelOneMarketDataProvider
from app.data.providers.angelone_websocket import (
    AngelOneWebSocketManager,
    MODE_LTP,
    MODE_QUOTE,
    MODE_SNAP_QUOTE,
)
from app.data.providers.mock_provider import MockMarketDataProvider
from app.data.providers.upstox_provider import UpstoxMarketDataProvider
from app.data.quality_validator import DataQualityEngine, FeedStatus
from app.main import app
from app.options.multi_timeframe_engine import (
    _is_candle_complete,
    evaluate_multi_timeframe_confluence,
    filter_completed_candles,
)
from app.options.pipeline_orchestrator import execute_production_signal_pipeline
from app.options.smc_engine import SmartMoneyEngine

IST = timezone(timedelta(hours=5, minutes=30))


def _encode_token_25(token: str) -> bytes:
    raw = token.encode("ascii")
    assert len(raw) <= 25
    return raw.ljust(25, b"\x00")


def _build_ltp_packet(
    *,
    mode: int = MODE_LTP,
    exchange_type: int = 1,
    token_bytes: bytes | None = None,
    sequence_number: int = 1,
    exchange_timestamp_ms: int | None = None,
    raw_ltp: int = 2485240,
) -> bytes:
    ts_ms = exchange_timestamp_ms if exchange_timestamp_ms is not None else int(time.time() * 1000)
    tok = token_bytes if token_bytes is not None else _encode_token_25("99926000")
    return struct.pack("<BB", mode, exchange_type) + tok + struct.pack("<qqq", sequence_number, ts_ms, raw_ltp)


def _build_quote_packet(
    *,
    mode: int = MODE_QUOTE,
    exchange_type: int = 1,
    token: str = "99926000",
    sequence_number: int = 0,
    exchange_timestamp_ms: int | None = None,
    raw_ltp: int = 2485240,
    last_traded_qty: int = 0,
    raw_avg_price: int = 0,
    volume: int = 0,
    total_buy_qty: float = 0.0,
    total_sell_qty: float = 0.0,
    raw_open: int = 2481000,
    raw_high: int = 2490000,
    raw_low: int = 2475000,
    raw_close: int = 2479000,
) -> bytes:
    ltp_hdr = _build_ltp_packet(
        mode=mode,
        exchange_type=exchange_type,
        token_bytes=_encode_token_25(token),
        sequence_number=sequence_number,
        exchange_timestamp_ms=exchange_timestamp_ms,
        raw_ltp=raw_ltp,
    )
    quote_body = struct.pack(
        "<qqqddqqqq",
        last_traded_qty,
        raw_avg_price,
        volume,
        total_buy_qty,
        total_sell_qty,
        raw_open,
        raw_high,
        raw_low,
        raw_close,
    )
    return ltp_hdr + quote_body


def _build_snap_quote_packet(
    *,
    token: str = "2885",
    sequence_number: int = 42,
    exchange_timestamp_ms: int | None = None,
    raw_ltp: int = 145680,
    open_interest: int = 1250000,
    oi_change_pct: float = 4.25,
    upper_circuit: int = 160000,
    lower_circuit: int = 130000,
    w52_high: int = 162000,
    w52_low: int = 115000,
) -> bytes:
    ts_ms = exchange_timestamp_ms if exchange_timestamp_ms is not None else int(time.time() * 1000)
    quote_part = _build_quote_packet(
        mode=MODE_SNAP_QUOTE,
        exchange_type=1,
        token=token,
        sequence_number=sequence_number,
        exchange_timestamp_ms=ts_ms,
        raw_ltp=raw_ltp,
        last_traded_qty=50,
        raw_avg_price=145200,
        volume=987654,
        total_buy_qty=12000.0,
        total_sell_qty=11500.0,
        raw_open=144500,
        raw_high=146200,
        raw_low=144000,
        raw_close=144800,
    )
    snap_prefix = struct.pack("<qqd", ts_ms, open_interest, oi_change_pct)
    depth = b"".join(
        struct.pack("<hqqh", 1 if idx < 5 else 0, 100 * (idx + 1), raw_ltp + (idx * 50), 3)
        for idx in range(10)
    )
    circuits = struct.pack("<qqqq", upper_circuit, lower_circuit, w52_high, w52_low)
    pkt = quote_part + snap_prefix + depth + circuits
    assert len(pkt) == 379
    return pkt


# ===========================================================================
# P0 #1 — Angel One SmartAPI v2 WebSocket Binary Packet Decoding
# ===========================================================================


def test_parse_valid_mode_ltp_51b():
    ts_ms = 1794388500000  # 2026-11-11 IST epoch ms
    pkt = _build_ltp_packet(
        mode=MODE_LTP,
        exchange_type=1,
        token_bytes=_encode_token_25("99926000"),
        sequence_number=0,
        exchange_timestamp_ms=ts_ms,
        raw_ltp=2485245,
    )
    assert len(pkt) == 51
    parsed = AngelOneWebSocketManager.parse_binary_packet(pkt)
    assert parsed is not None
    assert parsed["token"] == "99926000"
    assert parsed["exchange"] == "NSE"
    assert parsed["subscription_mode"] == MODE_LTP
    assert parsed["sequence_number"] == 0
    assert parsed["exchange_timestamp"] == ts_ms
    assert parsed["ltp"] == 24852.45


def test_parse_valid_mode_quote_123b_and_cds_divisor():
    ts_ms = 1794388512345
    # Test NSE 123-byte Mode Quote (index stream with seq=0)
    pkt_nse = _build_quote_packet(
        token="99926009",
        sequence_number=0,
        exchange_timestamp_ms=ts_ms,
        raw_ltp=5142080,
        volume=0,
        raw_open=5110000,
        raw_high=5155000,
        raw_low=5108000,
        raw_close=5120000,
    )
    assert len(pkt_nse) == 123
    parsed_nse = AngelOneWebSocketManager.parse_binary_packet(pkt_nse)
    assert parsed_nse is not None
    assert parsed_nse["ltp"] == 51420.80
    assert parsed_nse["open"] == 51100.00
    assert parsed_nse["high"] == 51550.00
    assert parsed_nse["low"] == 51080.00
    assert parsed_nse["close"] == 51200.00
    assert parsed_nse["sequence_number"] == 0
    assert parsed_nse["exchange_timestamp"] == ts_ms

    # Test CDS (exchange_type=13) divisor 1e7
    pkt_cds = _build_quote_packet(
        exchange_type=13,
        token="1001",
        sequence_number=7,
        exchange_timestamp_ms=ts_ms,
        raw_ltp=841250000,  # 84.1250
        raw_open=840000000,
        raw_high=842500000,
        raw_low=839500000,
        raw_close=840500000,
    )
    parsed_cds = AngelOneWebSocketManager.parse_binary_packet(pkt_cds)
    assert parsed_cds is not None
    assert parsed_cds["exchange"] == "CDS"
    assert parsed_cds["ltp"] == pytest.approx(84.125, rel=1e-6)


def test_parse_valid_mode_snap_quote_379b():
    pkt = _build_snap_quote_packet()
    parsed = AngelOneWebSocketManager.parse_binary_packet(pkt)
    assert parsed is not None
    assert parsed["subscription_mode"] == MODE_SNAP_QUOTE
    assert parsed["token"] == "2885"
    assert parsed["sequence_number"] == 42
    assert parsed["ltp"] == 1456.80
    assert parsed["openInterest"] == 1250000
    assert parsed["oiChangePercent"] == pytest.approx(4.25)
    assert parsed["upperCircuit"] == 1600.00
    assert parsed["lowerCircuit"] == 1300.00
    assert len(parsed["best5Buy"]) == 5
    assert len(parsed["best5Sell"]) == 5


@pytest.mark.parametrize(
    "bad_packet",
    [
        None,
        "not-bytes",
        b"",
        b"\x01\x01" + b"\x00" * 48,  # 50 bytes (< 51 minimum)
        _build_quote_packet()[:-1],  # truncated MODE_QUOTE (122 bytes)
        _build_snap_quote_packet()[:-1],  # truncated MODE_SNAP_QUOTE (378 bytes)
        _build_ltp_packet(mode=9),  # unknown subscription mode
        _build_ltp_packet(exchange_type=99),  # unknown exchange type
        _build_ltp_packet(token_bytes=b"\x00" * 25),  # empty token
        _build_ltp_packet(token_bytes=b"\xff\xfe" + b"\x00" * 23),  # invalid ASCII token
        _build_ltp_packet(token_bytes=b"99\n00" + b"\x00" * 20),  # control char in token
        _build_ltp_packet(sequence_number=-1),  # negative sequence
        _build_ltp_packet(exchange_timestamp_ms=0),  # epoch 0 timestamp
        _build_ltp_packet(exchange_timestamp_ms=999_000_000_000),  # pre-2015 invalid ts
        _build_ltp_packet(raw_ltp=0),  # zero LTP
        _build_ltp_packet(raw_ltp=-24500),  # negative LTP
        _build_quote_packet(volume=-10),  # negative volume
        _build_quote_packet(total_buy_qty=float("nan")),  # NaN depth quantity
        _build_quote_packet(total_sell_qty=float("inf")),  # Inf depth quantity
        _build_quote_packet(raw_high=2400000, raw_low=2500000),  # inverted high < low
    ],
)
def test_parse_rejects_malformed_packets_safely(bad_packet):
    assert AngelOneWebSocketManager.parse_binary_packet(bad_packet) is None


@pytest.mark.asyncio
async def test_ws_handle_message_rejects_malformed_never_fabricates_ticks():
    ws = AngelOneWebSocketManager()
    assert ws.get_all_latest_ticks() == {}

    # Reject malformed bytes without inserting any tick into _latest_ticks
    await ws._handle_message(b"\x02\x01short")
    assert ws.get_all_latest_ticks() == {}
    assert ws.get_diagnostics()["malformed_packets_rejected"] == 1

    # Valid stream for NIFTY 50 with constant seq=0 (NSE index behavior) must not false-flag sequence gaps
    now_ms = int(time.time() * 1000)
    pkt1 = _build_quote_packet(token="99926000", sequence_number=0, exchange_timestamp_ms=now_ms, raw_ltp=2485240)
    pkt2 = _build_quote_packet(token="99926000", sequence_number=0, exchange_timestamp_ms=now_ms + 500, raw_ltp=2485500)

    with patch("app.data.providers.angelone_websocket.CacheService.set", new=AsyncMock(return_value=True)):
        await ws._handle_message(pkt1)
        await ws._handle_message(pkt2)

    assert "NIFTY 50" in ws.get_all_latest_ticks()
    assert ws.get_all_latest_ticks()["NIFTY 50"]["ltp"] == 24855.00
    assert ws._tick_metrics["sequence_gaps"] == 0

    # Sequenced equity tick with skipped sequence must increment sequence_gaps
    pkt_eq1 = _build_ltp_packet(token_bytes=_encode_token_25("2885"), sequence_number=10, exchange_timestamp_ms=now_ms, raw_ltp=145500)
    pkt_eq2 = _build_ltp_packet(token_bytes=_encode_token_25("2885"), sequence_number=13, exchange_timestamp_ms=now_ms + 100, raw_ltp=145600)
    with patch("app.data.providers.angelone_websocket.CacheService.set", new=AsyncMock(return_value=True)):
        await ws._handle_message(pkt_eq1)
        await ws._handle_message(pkt_eq2)

    assert ws._tick_metrics["sequence_gaps"] >= 1


# ===========================================================================
# P0 #2 — Timeframe-Aware Incomplete Candle Filtering & No Lookahead
# ===========================================================================


def test_is_candle_complete_fails_closed_without_flag_or_valid_boundary():
    # Missing is_closed / is_complete AND no timeframe -> fail closed
    row_no_flag = pd.Series({"timestamp": "2026-11-11T10:15:00+05:30", "open": 24800, "high": 24850, "low": 24790, "close": 24840})
    assert _is_candle_complete(row_no_flag, timeframe=None) is False

    # Missing flag AND invalid timestamp -> fail closed
    row_bad_ts = pd.Series({"timestamp": "not-a-ts", "open": 24800, "high": 24850, "low": 24790, "close": 24840})
    assert _is_candle_complete(row_bad_ts, timeframe="5m") is False

    # Explicit False always rejected
    row_false = pd.Series({"timestamp": "2026-11-11T10:00:00+05:30", "is_closed": False, "close": 24840})
    assert _is_candle_complete(row_false, timeframe="5m", now_ist=datetime(2026, 11, 11, 14, 0, tzinfo=IST)) is False


def test_timeframe_ist_boundary_enforcement_and_lookahead_guard():
    # Clock is 11 Nov 2026 10:19:59 IST
    now_ist = datetime(2026, 11, 11, 10, 19, 59, tzinfo=IST)

    # 5m bar starting at 10:15 ends at 10:20 -> still forming at 10:19:59
    bar_5m_forming = pd.Series({"timestamp": "2026-11-11T10:15:00+05:30", "open": 100, "high": 102, "low": 99, "close": 101})
    assert _is_candle_complete(bar_5m_forming, timeframe="5m", now_ist=now_ist) is False
    # At exact close 10:20:00 -> completed
    assert _is_candle_complete(bar_5m_forming, timeframe="5m", now_ist=datetime(2026, 11, 11, 10, 20, 0, tzinfo=IST)) is True

    # 15m bar starting at 10:15 ends at 10:30 -> still forming at 10:29:59
    assert _is_candle_complete(bar_5m_forming, timeframe="15m", now_ist=datetime(2026, 11, 11, 10, 29, 59, tzinfo=IST)) is False
    assert _is_candle_complete(bar_5m_forming, timeframe="15m", now_ist=datetime(2026, 11, 11, 10, 30, 0, tzinfo=IST)) is True

    # 1m and 3m boundaries
    bar_1018 = pd.Series({"timestamp": "2026-11-11T10:18:00+05:30", "close": 101})
    assert _is_candle_complete(bar_1018, timeframe="1m", now_ist=datetime(2026, 11, 11, 10, 18, 59, tzinfo=IST)) is False
    assert _is_candle_complete(bar_1018, timeframe="1m", now_ist=datetime(2026, 11, 11, 10, 19, 0, tzinfo=IST)) is True
    assert _is_candle_complete(bar_1018, timeframe="3m", now_ist=datetime(2026, 11, 11, 10, 20, 59, tzinfo=IST)) is False
    assert _is_candle_complete(bar_1018, timeframe="3m", now_ist=datetime(2026, 11, 11, 10, 21, 0, tzinfo=IST)) is True

    # NSE 15:15 1h bar closes at 15:30 IST session close (not 16:15)
    bar_1515_1h = pd.Series({"timestamp": "2026-11-11T15:15:00+05:30", "close": 101})
    assert _is_candle_complete(bar_1515_1h, timeframe="1h", now_ist=datetime(2026, 11, 11, 15, 29, 59, tzinfo=IST)) is False
    assert _is_candle_complete(bar_1515_1h, timeframe="1h", now_ist=datetime(2026, 11, 11, 15, 30, 0, tzinfo=IST)) is True

    # Daily bar for 2026-11-11 closes at 15:30 IST
    bar_daily = pd.Series({"timestamp": "2026-11-11T09:15:00+05:30", "close": 101})
    assert _is_candle_complete(bar_daily, timeframe="1d", now_ist=datetime(2026, 11, 11, 15, 29, 0, tzinfo=IST)) is False
    assert _is_candle_complete(bar_daily, timeframe="1d", now_ist=datetime(2026, 11, 11, 15, 30, 0, tzinfo=IST)) is True

    # Lookahead future candle must be rejected EVEN IF spoofed is_closed=True
    future_spoofed = pd.Series({"timestamp": "2026-11-11T11:00:00+05:30", "is_closed": True, "close": 101})
    assert _is_candle_complete(future_spoofed, timeframe="5m", now_ist=now_ist) is False


def test_smc_and_mtf_exclude_incomplete_forming_candles():
    now_ist = datetime(2026, 11, 11, 11, 12, 0, tzinfo=IST)
    # 15 completed 5m bars ending at 11:05..11:10 + 1 huge anomalous forming bar starting at 11:10
    rows = []
    start = datetime(2026, 11, 11, 9, 55, 0, tzinfo=IST)
    for i in range(15):
        ts = start + timedelta(minutes=5 * i)
        rows.append({
            "timestamp": ts,
            "open": 24800.0 + i,
            "high": 24810.0 + i,
            "low": 24795.0 + i,
            "close": 24805.0 + i,
            "volume": 10000,
        })
    # Forming candle at 11:10 (would end at 11:15) with massive spike high=26000
    rows.append({
        "timestamp": start + timedelta(minutes=5 * 15),
        "open": 24820.0,
        "high": 26000.0,
        "low": 24000.0,
        "close": 25950.0,
        "volume": 999999,
    })
    df_5m = pd.DataFrame(rows)
    df_5m.attrs["timeframe"] = "5m"

    filtered = filter_completed_candles(df_5m, timeframe="5m", now_ist=now_ist)
    assert filtered is not None
    assert len(filtered) == 15
    assert float(filtered["high"].max()) < 25000.0

    with patch("app.options.multi_timeframe_engine.MarketCalendar.now_ist", return_value=now_ist):
        smc_res = SmartMoneyEngine.analyze(df_5m, current_price=24820.0, daily_high=24850.0, daily_low=24790.0, timeframe="5m")
        assert smc_res["incompleteCandlesExcluded"] == 1
        assert smc_res["confirmedBarsCount"] == 15

        mtf_res = evaluate_multi_timeframe_confluence(
            symbol="NIFTY 50",
            timeframe_candles={"5m": df_5m},
            current_quote={"currentPrice": 24820.0, "ltp": 24820.0},
            is_live_data=True,
            data_quality_status="VERIFIED_LIVE",
        )
        # Confirmed 5m swing high must come strictly from the 15 closed bars, never 26000.0
        assert mtf_res["itf_structure"]["swing_high"] < 25000.0


@pytest.mark.asyncio
async def test_pipeline_excludes_forming_candle_from_confirmed_analysis():
    now_ist = datetime(2026, 11, 11, 11, 12, 0, tzinfo=IST)
    df_15m = pd.DataFrame([
        {
            "timestamp": datetime(2026, 11, 11, 7, 15, tzinfo=IST) + timedelta(minutes=15 * i),
            "open": 24400.0 + (i * 15.0),
            "high": 24418.0 + (i * 15.0),
            "low": 24395.0 + (i * 15.0),
            "close": 24412.0 + (i * 15.0),
            "volume": 15000 + (i * 500),
        }
        for i in range(15)
    ])
    # Forming bar at 11:00 on 15m (ends 11:15 > 11:12) & forming bar at 11:10 on 5m (ends 11:15 > 11:12)
    df_forming_15m = pd.DataFrame([{
        "timestamp": datetime(2026, 11, 11, 11, 0, tzinfo=IST),
        "open": 24630.0,
        "high": 25500.0,
        "low": 24200.0,
        "close": 25400.0,
        "volume": 90000,
    }])
    df_forming_5m = pd.DataFrame([{
        "timestamp": datetime(2026, 11, 11, 11, 10, tzinfo=IST),
        "open": 24630.0,
        "high": 25600.0,
        "low": 24200.0,
        "close": 25500.0,
        "volume": 90000,
    }])
    combined_15m = pd.concat([df_15m, df_forming_15m], ignore_index=True)
    df_5m_closed = pd.DataFrame([
        {
            "timestamp": datetime(2026, 11, 11, 9, 55, tzinfo=IST) + timedelta(minutes=5 * i),
            "open": 24480.0 + (i * 10.0),
            "high": 24495.0 + (i * 10.0),
            "low": 24475.0 + (i * 10.0),
            "close": 24490.0 + (i * 10.0),
            "volume": 12000 + (i * 300),
        }
        for i in range(15)
    ])
    combined_5m = pd.concat([df_5m_closed, df_forming_5m], ignore_index=True)

    closed_last = float(df_5m_closed["close"].iloc[-1])
    provider = MagicMock()
    provider.get_provider_name.return_value = "angelone"
    provider.is_authenticated = True
    quote = {
        "symbol": "NIFTY 50",
        "ltp": closed_last,
        "currentPrice": closed_last,
        "open": float(df_15m["open"].iloc[0]),
        "high": max(float(df_15m["high"].max()), closed_last + 10.0),
        "low": float(df_15m["low"].min()),
        "close": float(df_15m["open"].iloc[0]) - 20.0,
        "previousClose": float(df_15m["open"].iloc[0]) - 20.0,
        "change": 240.0,
        "timestamp": datetime.now(IST).isoformat(),
        "dataStatus": "LIVE",
        "provider": "angelone",
    }

    from app.options.pipeline_orchestrator import PipelineStage

    with patch("app.options.multi_timeframe_engine.MarketCalendar.now_ist", return_value=now_ist):
        res = await execute_production_signal_pipeline(
            symbol="NIFTY 50",
            provider=provider,
            custom_quote=quote,
            custom_timeframes={"15m": combined_15m, "5m": combined_5m},
            custom_option_chain={"strikes": [], "pcr": {"pcrOi": 1.2}},
        )

    assert res["stage_status"][PipelineStage.STAGE_3_CANDLE_COMPLETENESS] == "SUCCESS"
    assert res["mtf_confluence"]["itf_structure"]["swing_high"] < 25000.0
    assert res["mtf_confluence"]["htf_bias"]["has_15m"] is True
    assert res["mtf_confluence"]["itf_structure"]["has_5m"] is True


# ===========================================================================
# P0 #3 — Zero Silent Synthetic / Mock Fallback Contamination
# ===========================================================================


@pytest.mark.asyncio
async def test_angelone_provider_unauthenticated_returns_explicit_offline_no_mock():
    with (
        patch("app.data.providers.angelone_provider.CacheService.get", new=AsyncMock(return_value=None)),
        patch("app.data.providers.angelone_provider.httpx.AsyncClient", side_effect=AssertionError("Must not issue HTTP requests without credentials")),
    ):
        p = AngelOneMarketDataProvider()
        p.api_key = ""
        p.client_code = ""
        p.pin = ""
        p.totp_secret = ""
        p._jwt_token = None
        p._is_logged_in = False

        quote = await p.get_quote("NIFTY 50")
        assert quote["dataStatus"] == "DATA_OFFLINE"
        assert quote["is_mock"] is False
        assert quote["is_synthetic"] is False
        assert quote["ltp"] == 0.0
        assert "degradedReason" in quote

        df = await p.get_intraday_candles("NIFTY 50", "15m")
        assert df.empty
        assert df.attrs["dataStatus"] == "DATA_OFFLINE"
        assert df.attrs["is_mock"] is False
        assert df.attrs["degraded_reason"]

        indices = await p.get_all_indices()
        assert len(indices) >= 4
        assert all(idx["dataStatus"] == "DATA_OFFLINE" and idx["is_mock"] is False for idx in indices)

        breadth = await p.get_market_breadth()
        assert breadth["dataStatus"] == "DATA_UNAVAILABLE"
        assert breadth["is_mock"] is False
        assert await p.get_sector_data() == []


@pytest.mark.asyncio
async def test_angelone_provider_retries_on_429_then_returns_degraded_without_mock():
    p = AngelOneMarketDataProvider()
    p.api_key = "test-key"
    p._jwt_token = "test-jwt"
    p._is_logged_in = True
    p._max_retries = 2
    p._retry_backoff_seconds = 0.001

    rate_limit_resp = MagicMock()
    rate_limit_resp.status_code = 429
    rate_limit_resp.json.return_value = {"status": False, "errorcode": "AB1004", "message": "TooManyRequests"}

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=rate_limit_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("app.data.providers.angelone_provider.CacheService.get", new=AsyncMock(return_value=None)),
        patch("app.data.providers.angelone_provider.httpx.AsyncClient", return_value=mock_client),
    ):
        df = await p.get_historical_candles(
            "NIFTY 50",
            "15m",
            datetime(2026, 11, 11, 9, 15, tzinfo=IST),
            datetime(2026, 11, 11, 11, 0, tzinfo=IST),
        )

    assert mock_client.post.call_count == 3  # 1 initial + 2 retries
    assert df.empty
    assert df.attrs["dataStatus"] == "DEGRADED"
    assert df.attrs["retry_attempts"] == 2
    assert df.attrs["http_status"] == 429
    assert df.attrs["is_mock"] is False
    assert "HTTP 429" in df.attrs["degraded_reason"]


@pytest.mark.asyncio
async def test_angelone_intraday_preserves_short_genuine_morning_series():
    p = AngelOneMarketDataProvider()
    p.api_key = "test-key"
    p._jwt_token = "test-jwt"
    p._is_logged_in = True

    two_bars = pd.DataFrame([
        {"timestamp": datetime(2026, 11, 11, 9, 15, tzinfo=IST), "open": 24800.0, "high": 24830.0, "low": 24790.0, "close": 24820.0, "volume": 1000, "vwap": 24813.0},
        {"timestamp": datetime(2026, 11, 11, 10, 15, tzinfo=IST), "open": 24820.0, "high": 24850.0, "low": 24810.0, "close": 24845.0, "volume": 1200, "vwap": 24835.0},
    ])
    two_bars.attrs["dataStatus"] = "LIVE"
    two_bars.attrs["provider"] = "angelone"

    with patch.object(p, "get_historical_candles", new=AsyncMock(return_value=two_bars)):
        df_1h = await p.get_intraday_candles("NIFTY 50", "1h")

    assert len(df_1h) == 2
    assert float(df_1h["close"].iloc[-1]) == 24845.0
    assert df_1h.attrs.get("is_mock", False) is False


@pytest.mark.asyncio
async def test_upstox_provider_returns_explicit_unavailable_no_mock():
    u = UpstoxMarketDataProvider()
    u.access_token = ""
    assert not hasattr(u, "fallback")

    quote = await u.get_quote("NIFTY 50")
    assert quote["dataStatus"] == "UNAVAILABLE"
    assert quote["is_mock"] is False
    assert quote["ltp"] == 0.0

    df = await u.get_intraday_candles("NIFTY 50", "15m")
    assert df.empty
    assert df.attrs["dataStatus"] == "DATA_UNAVAILABLE"
    assert df.attrs["is_mock"] is False


@pytest.mark.asyncio
async def test_mock_provider_data_strictly_tagged_and_rejected_by_quality_and_smc():
    mock_prov = MockMarketDataProvider()
    mock_quote = await mock_prov.get_quote("NIFTY 50")
    mock_df = await mock_prov.get_intraday_candles("NIFTY 50", "15m")

    assert mock_quote["is_mock"] is True
    assert mock_quote["is_synthetic"] is True
    assert mock_df.attrs["is_mock"] is True
    assert mock_df.attrs["is_synthetic"] is True

    # Even if an upstream bug tries to spoof dataStatus="LIVE" on a mock-marked quote/df, validator fails closed
    spoofed_quote = {**mock_quote, "dataStatus": "LIVE"}
    q_audit = DataQualityEngine.validate_quote("NIFTY 50", spoofed_quote, reference_candles=mock_df)
    assert q_audit["dataQualityReport"]["feedStatus"] == FeedStatus.SYNTHETIC
    assert q_audit["dataQualityReport"]["isTradeQualified"] is False

    ohlc_audit = DataQualityEngine.validate_ohlc(mock_df, timeframe="15m")
    assert ohlc_audit["isValid"] is False
    assert ohlc_audit["is_synthetic"] is True

    smc_mock = SmartMoneyEngine.analyze(mock_df, 24850.0, 24900.0, 24800.0, timeframe="15m")
    assert smc_mock["executionModels"]["status"] == "DATA_GATED"
    assert smc_mock["advancedIct"]["status"] == "DATA_GATED"
    assert smc_mock["orderBlocks"] == []

    pipe_res = await execute_production_signal_pipeline(
        symbol="NIFTY 50",
        provider=mock_prov,
        custom_quote=spoofed_quote,
        custom_timeframes={"15m": mock_df, "5m": mock_df},
        custom_option_chain={"strikes": [], "pcr": {"pcrOi": 1.0}},
    )
    assert pipe_res["is_trade_qualified"] is False
    assert pipe_res["data_quality_report"]["feedStatus"] == FeedStatus.SYNTHETIC


@pytest.mark.asyncio
async def test_stock_analysis_service_handles_empty_degraded_candles_cleanly():
    from app.services.analysis_service import AnalysisService

    offline_prov = AngelOneMarketDataProvider()
    offline_prov.api_key = ""
    offline_prov.client_code = ""
    offline_prov.pin = ""
    offline_prov.totp_secret = ""
    offline_prov._jwt_token = None
    offline_prov._is_logged_in = False

    fake_news = MagicMock()
    fake_news.get_news_for_stock = AsyncMock(return_value=[])

    with (
        patch("app.services.analysis_service.CacheService.get", new=AsyncMock(return_value=None)),
        patch("app.services.analysis_service.CacheService.set", new=AsyncMock(return_value=True)),
        patch("app.data.providers.angelone_provider.CacheService.get", new=AsyncMock(return_value=None)),
        patch("app.services.analysis_service.get_market_data_provider", return_value=offline_prov),
        patch("app.services.analysis_service.get_financial_news_provider", return_value=fake_news),
    ):
        analysis = await AnalysisService.get_analysis("RELIANCE")

    assert analysis["symbol"] == "RELIANCE"
    assert analysis["dataStatus"] == "DATA_OFFLINE"
    assert analysis["volumeAnalysis"]["averageVolume"] == "0K"


@pytest.mark.asyncio
async def test_ict_analysis_route_fails_closed_on_mock_and_unavailable():
    mock_prov = MockMarketDataProvider()
    with patch("app.api.routes.options.get_market_data_provider", return_value=mock_prov):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            res = await client.get("/api/options/NIFTY%2050/ict-analysis?timeframe=15m")
            assert res.status_code == 200
            body = res.json()
            assert body["status"] == "DATA_UNAVAILABLE"
            assert body["dataStatus"] == "SYNTHETIC"


# =====================================================================
# Dedicated Direct Verification for Remediated P0 Defects (P0-1 .. P0-5)
# =====================================================================

def test_p0_1_token_mapping_uniqueness_and_reverse_lookup():
    """P0-1 Fix: Token mapping collision between INDIA VIX and NIFTY METAL is eliminated."""
    from app.data.providers.angelone_provider import ANGELONE_TOKEN_MAP
    from app.data.providers.angelone_websocket import AngelOneWebSocketManager
    from app.backtesting.market_data_readiness import _extract_token_collisions

    # 1. Distinct tokens for INDIA VIX and NIFTY METAL
    assert ANGELONE_TOKEN_MAP["INDIA VIX"]["token"] == "99926017"
    assert ANGELONE_TOKEN_MAP["NIFTY METAL"]["token"] == "99926030"
    assert ANGELONE_TOKEN_MAP["INDIA VIX"]["token"] != ANGELONE_TOKEN_MAP["NIFTY METAL"]["token"]

    # 2. Zero collisions across the entire token map
    collisions = _extract_token_collisions()
    assert collisions == {}, f"Unexpected token collisions: {collisions}"

    # 3. WebSocket reverse lookup resolves correctly
    mgr = AngelOneWebSocketManager()
    assert mgr._resolve_token_to_symbol("99926030", 1) == "NIFTY METAL"
    assert mgr._resolve_token_to_symbol("99926017", 1) == "INDIA VIX"
    assert mgr._resolve_token_to_symbol("99926000", 1) in ("NIFTY 50", "NIFTY")


@pytest.mark.asyncio
async def test_p0_2_live_status_requires_verified_usable_ticks():
    """P0-2 Fix: Live status reports STREAMING only when healthy with usable ticks received."""
    from app.data.providers.angelone_websocket import angelone_ws_manager

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Case A: WebSocket running but 0 ticks received -> CONNECTED_WAITING_TICKS
        with patch.object(angelone_ws_manager, "is_running", True), \
             patch.object(angelone_ws_manager, "get_diagnostics", return_value={"is_healthy": False, "ticks_received": 0}):
            res = await client.get("/api/live/status")
            assert res.status_code == 200
            data = res.json()
            assert data["status"] == "CONNECTED_WAITING_TICKS"
            assert data["status"] != "STREAMING"

        # Case B: WebSocket offline -> DISCONNECTED
        with patch.object(angelone_ws_manager, "is_running", False), \
             patch.object(angelone_ws_manager, "get_diagnostics", return_value={"is_healthy": False, "ticks_received": 0}):
            res = await client.get("/api/live/status")
            assert res.status_code == 200
            data = res.json()
            assert data["status"] == "DISCONNECTED"

        # Case C: WebSocket running, healthy, and ticks > 0 -> STREAMING
        with patch.object(angelone_ws_manager, "is_running", True), \
             patch.object(angelone_ws_manager, "get_diagnostics", return_value={"is_healthy": True, "ticks_received": 42}):
            res = await client.get("/api/live/status")
            assert res.status_code == 200
            data = res.json()
            assert data["status"] == "STREAMING"


def test_p0_3_coerce_bool_flag_strict_fail_closed():
    """P0-3 Fix: _coerce_bool_flag fails closed on NaN, null, and invalid string values."""
    from app.options.multi_timeframe_engine import _coerce_bool_flag
    import math

    # String representations of missing/invalid values must return None (NEVER True)
    for invalid_str in ("nan", "NaN", "NAN", "null", "NULL", "none", "NONE", "undefined", "foo", "?"):
        assert _coerce_bool_flag(invalid_str) is None, f"Failed for {invalid_str}"

    # Float NaN must return None
    assert _coerce_bool_flag(float("nan")) is None
    assert _coerce_bool_flag(math.nan) is None
    assert _coerce_bool_flag(None) is None

    # Valid values must coerce correctly
    assert _coerce_bool_flag(True) is True
    assert _coerce_bool_flag(False) is False
    assert _coerce_bool_flag("true") is True
    assert _coerce_bool_flag("closed") is True
    assert _coerce_bool_flag("false") is False
    assert _coerce_bool_flag("open") is False
    assert _coerce_bool_flag("forming") is False


def test_p0_4_tick_validation_future_stale_duplicate_out_of_order_rejection():
    """P0-4 Fix: validate_tick strictly rejects future, stale, duplicate, and out-of-order ticks."""
    from datetime import timezone
    now_sec = datetime.now(timezone.utc).timestamp()

    # 1. Future tick (+60s) must be rejected
    fut = DataQualityEngine.validate_tick(
        "NIFTY 50",
        {"ltp": 24500.0, "volume": 1000, "timestamp": now_sec + 60.0},
    )
    assert fut["isValid"] is False
    assert fut["feedStatus"] == FeedStatus.ANOMALOUS

    # 2. Stale tick (-60s) must be rejected consistently
    stale = DataQualityEngine.validate_tick(
        "NIFTY 50",
        {"ltp": 24500.0, "volume": 1000, "timestamp": now_sec - 60.0},
    )
    assert stale["isValid"] is False
    assert stale["feedStatus"] == FeedStatus.STALE_TICK

    # 3. Out-of-order sequence tick must be rejected
    ooo = DataQualityEngine.validate_tick(
        "NIFTY 50",
        {"ltp": 24500.0, "volume": 1000, "sequence_number": 1, "timestamp": now_sec},
        expected_sequence=5,
    )
    assert ooo["isValid"] is False
    assert ooo["sequenceStatus"] == "OUT_OF_ORDER"
    assert ooo["feedStatus"] == FeedStatus.DEGRADED

    # 4. Duplicate sequence packet must be rejected
    dup = DataQualityEngine.validate_tick(
        "NIFTY 50",
        {"ltp": 24500.0, "volume": 1000, "sequence_number": 5, "timestamp": now_sec},
        last_tick={"ltp": 24500.0, "volume": 1000, "sequence_number": 5},
    )
    assert dup["isValid"] is False
    assert dup["sequenceStatus"] == "DUPLICATE_PACKET"
    assert dup["feedStatus"] == FeedStatus.DEGRADED


@pytest.mark.asyncio
async def test_p0_5_provider_validation_parity_and_offline_consistency():
    """P0-5 Fix: Upstox validates candles and AngelOne consistently reports DATA_OFFLINE unauthenticated."""
    from app.backtesting.market_data_readiness import _check_provider_ohlc_and_status_parity
    from app.data.providers.angelone_provider import AngelOneMarketDataProvider

    # 1. Readiness audit check passes
    has_gap, detail = _check_provider_ohlc_and_status_parity()
    assert not has_gap, f"Provider parity audit gap detected: {detail}"

    # 2. AngelOne quote consistently DATA_OFFLINE when unauthenticated
    p = AngelOneMarketDataProvider()
    p.api_key = ""
    p.client_code = ""
    p._jwt_token = None
    p._is_logged_in = False
    quote = await p.get_quote("NIFTY 50")
    assert quote["dataStatus"] == "DATA_OFFLINE"
    assert quote["feedStatus"] == "DATA_OFFLINE"
    assert quote["is_mock"] is False
