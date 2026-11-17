import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    Column,
    String,
    Integer,
    Float,
    Boolean,
    DateTime,
    Text,
    JSON,
    ForeignKey,
    Index,
    UniqueConstraint
)
from sqlalchemy.orm import relationship
from app.db.database import Base


def utcnow():
    return datetime.now(timezone.utc)


class Stock(Base):
    __tablename__ = "stocks"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    symbol = Column(String(20), unique=True, nullable=False, index=True)
    company_name = Column(String(200), nullable=False)
    exchange = Column(String(10), default="NSE", nullable=False)
    instrument_key = Column(String(50), nullable=True, index=True)
    isin = Column(String(20), nullable=True)
    sector = Column(String(100), nullable=False, index=True)
    instrument_type = Column(String(20), default="EQUITY", nullable=False)
    category = Column(String(50), default="Large Cap", nullable=False)  # Large Cap / Mid Cap / Small Cap
    lot_size = Column(Integer, default=1, nullable=False)
    tick_size = Column(Float, default=0.05, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    is_fno = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    candles = relationship("MarketCandle", back_populates="stock", cascade="all, delete-orphan")
    analyses = relationship("StockAnalysisRecord", back_populates="stock", cascade="all, delete-orphan")


class MarketIndexRecord(Base):
    __tablename__ = "market_indices"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    symbol = Column(String(30), unique=True, nullable=False, index=True)
    name = Column(String(100), nullable=False)
    current_value = Column(Float, nullable=False)
    change = Column(Float, nullable=False)
    change_percent = Column(Float, nullable=False)
    day_high = Column(Float, nullable=False)
    day_low = Column(Float, nullable=False)
    trend = Column(String(20), default="Neutral", nullable=False)
    sparkline = Column(JSON, nullable=True)
    volatility_status = Column(String(20), default="Moderate", nullable=True)
    timestamp = Column(DateTime(timezone=True), default=utcnow, nullable=False)


class MarketCandle(Base):
    __tablename__ = "market_candles"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    stock_id = Column(String(36), ForeignKey("stocks.id"), nullable=False, index=True)
    symbol = Column(String(20), nullable=False, index=True)
    timeframe = Column(String(10), default="15m", nullable=False)  # 1m, 5m, 15m, 30m, 1h, 1d
    timestamp = Column(DateTime(timezone=True), nullable=False, index=True)
    open = Column(Float, nullable=False)
    high = Column(Float, nullable=False)
    low = Column(Float, nullable=False)
    close = Column(Float, nullable=False)
    volume = Column(Float, default=0.0, nullable=False)
    vwap = Column(Float, nullable=True)

    stock = relationship("Stock", back_populates="candles")

    __table_args__ = (
        UniqueConstraint("symbol", "timeframe", "timestamp", name="uq_candle_sym_tf_time"),
        Index("idx_candle_sym_tf_time", "symbol", "timeframe", "timestamp"),
    )


class TechnicalSnapshot(Base):
    __tablename__ = "technical_snapshots"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    symbol = Column(String(20), nullable=False, index=True)
    timestamp = Column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)
    rsi = Column(Float, nullable=True)
    macd_value = Column(Float, nullable=True)
    macd_signal = Column(Float, nullable=True)
    macd_histogram = Column(Float, nullable=True)
    ema_20 = Column(Float, nullable=True)
    ema_50 = Column(Float, nullable=True)
    ema_200 = Column(Float, nullable=True)
    vwap = Column(Float, nullable=True)
    atr = Column(Float, nullable=True)
    volume_avg_20 = Column(Float, nullable=True)
    volume_ratio = Column(Float, nullable=True)
    momentum = Column(Float, nullable=True)
    indicators_json = Column(JSON, nullable=False)


class StockAnalysisRecord(Base):
    __tablename__ = "stock_analysis"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    stock_id = Column(String(36), ForeignKey("stocks.id"), nullable=True, index=True)
    symbol = Column(String(20), nullable=False, index=True)
    timestamp = Column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)
    current_price = Column(Float, nullable=False)
    change = Column(Float, nullable=False)
    change_percent = Column(Float, nullable=False)
    trend = Column(String(20), nullable=False)  # Bullish, Bearish, Neutral
    analysis_score = Column(Integer, nullable=False)
    confidence = Column(Integer, nullable=False)
    expected_high_min = Column(Float, nullable=False)
    expected_high_max = Column(Float, nullable=False)
    expected_low_min = Column(Float, nullable=False)
    expected_low_max = Column(Float, nullable=False)
    upside_prob = Column(Float, nullable=False)
    downside_prob = Column(Float, nullable=False)
    data_status = Column(String(20), default="MOCK", nullable=False)  # LIVE, MOCK, STALE, UNAVAILABLE
    full_payload = Column(JSON, nullable=False)

    stock = relationship("Stock", back_populates="analyses")


class SignalCandidateRecord(Base):
    __tablename__ = "signal_candidates"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    symbol = Column(String(20), nullable=False, index=True)
    signal_type = Column(String(10), nullable=False)  # CALL, PUT, NEUTRAL
    rank = Column(Integer, nullable=False)
    score = Column(Integer, nullable=False)
    confidence = Column(Integer, nullable=False)
    expected_move = Column(String(50), nullable=False)
    qualified = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)


class SectorRecord(Base):
    __tablename__ = "sectors"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(100), unique=True, nullable=False, index=True)
    trend = Column(String(20), default="Neutral", nullable=False)
    performance_percent = Column(Float, default=0.0, nullable=False)
    strength = Column(String(20), default="Moderate", nullable=False)
    top_stock = Column(String(50), nullable=True)
    advancers = Column(Integer, default=0, nullable=False)
    decliners = Column(Integer, default=0, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


class SectorSnapshot(Base):
    __tablename__ = "sector_snapshots"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    sector_name = Column(String(100), nullable=False, index=True)
    performance = Column(Float, nullable=False)
    advancers = Column(Integer, nullable=False)
    decliners = Column(Integer, nullable=False)
    timestamp = Column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)


class NewsEventRecord(Base):
    __tablename__ = "news_events"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    symbol = Column(String(20), nullable=True, index=True)
    headline = Column(String(500), nullable=False)
    source = Column(String(100), nullable=False)
    impact = Column(String(20), default="Medium", nullable=False)  # High, Medium, Low
    sentiment = Column(String(20), default="Neutral", nullable=False)  # Positive, Negative, Neutral
    published_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)


class AnalysisRunAudit(Base):
    __tablename__ = "analysis_runs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    analysis_id = Column(String(36), nullable=False, index=True)
    symbol = Column(String(20), nullable=False, index=True)
    market_data_timestamp = Column(DateTime(timezone=True), nullable=False)
    analysis_timestamp = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    quant_engine_version = Column(String(30), default="1.0.0", nullable=False)
    model_version = Column(String(50), nullable=True)
    knowledge_base_version = Column(String(50), nullable=True)
    ai_prompt_version = Column(String(30), default="v1", nullable=False)
    ai_response_hash = Column(String(64), nullable=True)
    structured_payload = Column(JSON, nullable=False)


# ============================================================
# MODULE 7: RAG KNOWLEDGE SYSTEM MODELS
# ============================================================

class KnowledgeDocument(Base):
    __tablename__ = "knowledge_documents"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    file_name = Column(String(255), nullable=False)
    document_type = Column(String(20), nullable=False)  # pdf, txt, article
    source = Column(String(255), nullable=True)
    author = Column(String(100), nullable=True)
    category = Column(String(100), default="Technical Analysis", nullable=False)
    total_pages = Column(Integer, default=1, nullable=False)
    chunk_count = Column(Integer, default=0, nullable=False)
    uploaded_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    chunks = relationship("KnowledgeChunk", back_populates="document", cascade="all, delete-orphan")


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    document_id = Column(String(36), ForeignKey("knowledge_documents.id"), nullable=False, index=True)
    page_number = Column(Integer, default=1, nullable=False)
    chunk_index = Column(Integer, nullable=False)
    chunk_text = Column(Text, nullable=False)
    # Stored as JSON float array for universal SQLite/PostgreSQL compatibility
    embedding = Column(JSON, nullable=True)
    chunk_metadata = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    document = relationship("KnowledgeDocument", back_populates="chunks")


# ============================================================
# MODULE 7: MACHINE LEARNING MODEL REGISTRY
# ============================================================

class MLModelRecord(Base):
    __tablename__ = "ml_models"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    model_version = Column(String(50), unique=True, nullable=False, index=True)
    model_name = Column(String(100), nullable=False)
    model_type = Column(String(50), nullable=False)  # logistic_regression, random_forest, gradient_boosting, mlp
    target_variable = Column(String(50), nullable=False)  # next_30m_direction, intraday_range, etc.
    training_dataset_version = Column(String(50), nullable=False)
    feature_version = Column(String(50), default="v1", nullable=False)
    training_start = Column(DateTime(timezone=True), nullable=False)
    training_end = Column(DateTime(timezone=True), nullable=False)
    validation_metrics = Column(JSON, nullable=False)
    test_metrics = Column(JSON, nullable=False)
    backtest_metrics = Column(JSON, nullable=True)
    status = Column(String(30), default="CANDIDATE", nullable=False)  # TRAINING, CANDIDATE, VALIDATION, APPROVED, PRODUCTION, REJECTED, ARCHIVED
    file_path = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)


class MLTrainingJob(Base):
    __tablename__ = "ml_training_jobs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    model_type = Column(String(50), nullable=False)
    target = Column(String(50), nullable=False)
    dataset_range = Column(String(100), nullable=False)
    features = Column(JSON, nullable=False)
    status = Column(String(30), default="RUNNING", nullable=False)  # RUNNING, COMPLETED, FAILED
    progress = Column(Integer, default=0, nullable=False)
    result_model_version = Column(String(50), nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)


# ============================================================
# LIVE SIGNAL TRACKING, OUTCOME ENGINE & PERFORMANCE MODELS
# ============================================================

class StrategyPolicyRecord(Base):
    __tablename__ = "strategy_policies"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    policy_name = Column(String(100), unique=True, nullable=False)
    version = Column(String(30), default="v2.1", nullable=False)
    t1_exit_fraction = Column(Float, default=0.50, nullable=False)
    t2_exit_fraction = Column(Float, default=0.30, nullable=False)
    t3_exit_fraction = Column(Float, default=0.20, nullable=False)
    move_sl_to_cost_on_t1 = Column(Boolean, default=True, nullable=False)
    trailing_stop_points = Column(Float, default=0.0, nullable=False)
    eod_exit_time = Column(String(10), default="15:25", nullable=False)
    brokerage_per_roundtrip = Column(Float, default=40.0, nullable=False)
    slippage_percent = Column(Float, default=0.0005, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)


class SignalEvaluationRecord(Base):
    """One observed analysis evaluation, including rejected and unavailable data."""
    __tablename__ = "signal_evaluations"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    symbol = Column(String(30), nullable=False, index=True)
    evaluated_at = Column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)
    data_status = Column(String(30), nullable=False)
    action = Column(String(30), nullable=False)
    qualified = Column(Boolean, nullable=False)
    rejection_reasons = Column(JSON, nullable=False, default=list)
    stage_status = Column(JSON, nullable=False, default=dict)
    persisted_signal_id = Column(String(60), nullable=True)


class SignalRecord(Base):
    __tablename__ = "signals"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    symbol = Column(String(30), nullable=False, index=True)  # Underlying e.g. NIFTY 50
    contract_symbol = Column(String(60), nullable=False, index=True)  # e.g. NIFTY19OCT2623100CE
    exchange = Column(String(10), default="NFO", nullable=False)
    instrument_token = Column(String(30), nullable=False, index=True)
    strike = Column(Float, nullable=False)
    expiry = Column(String(20), nullable=False)
    option_type = Column(String(10), nullable=False)  # CE or PE
    status = Column(String(30), default="GENERATED", nullable=False, index=True)
    # Lifecycle: GENERATED, WAITING_FOR_ENTRY, ACTIVE, TARGET_1_HIT, TARGET_2_HIT, TARGET_3_HIT,
    # STOP_LOSS_HIT, CLOSED_EOD, EXPIRED, MISSED, CANCELLED, DATA_GAP, AMBIGUOUS

    underlying_price_at_signal = Column(Float, nullable=False)
    signal_premium = Column(Float, nullable=False)  # Observed LTP at signal creation
    signal_bid = Column(Float, nullable=True)
    signal_ask = Column(Float, nullable=True)
    entry_zone_min = Column(Float, nullable=False)
    entry_zone_max = Column(Float, nullable=False)
    entry_trigger_condition = Column(String(255), nullable=False)
    stop_loss_premium = Column(Float, nullable=False)
    target_1_premium = Column(Float, nullable=False)
    target_2_premium = Column(Float, nullable=False)
    target_3_premium = Column(Float, nullable=False)
    trailing_stop_rule = Column(String(100), default="MOVE_TO_COST_ON_T1", nullable=False)
    horizon = Column(String(50), default="Next Session (1-2 Days)", nullable=False)
    sentiment = Column(String(20), default="BULLISH", nullable=False)
    analysis_score = Column(Integer, default=70, nullable=False)
    confidence = Column(String(20), default="High", nullable=False)

    strategy_policy_id = Column(String(36), ForeignKey("strategy_policies.id"), nullable=True)
    strategy_version = Column(String(30), default="v2.1-conservative", nullable=False)
    quant_engine_version = Column(String(30), default="1.0.0", nullable=False)
    model_version = Column(String(50), default="1.0.0", nullable=False)
    exit_policy_version = Column(String(30), default="v2.1", nullable=False)
    initial_market_state = Column(String(30), default="BULLISH", nullable=False)
    supporting_factors = Column(JSON, nullable=True)
    contradicting_factors = Column(JSON, nullable=True)
    provider = Column(String(30), default="angelone", nullable=False)
    data_status = Column(String(20), default="LIVE", nullable=False)

    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)
    entry_triggered_at = Column(DateTime(timezone=True), nullable=True)
    entry_observed_price = Column(Float, nullable=True)
    entry_observed_bid = Column(Float, nullable=True)
    entry_observed_ask = Column(Float, nullable=True)
    entry_reference_method = Column(String(50), nullable=True)  # ASK_EXECUTION or LTP_TOUCH
    closed_at = Column(DateTime(timezone=True), nullable=True)
    final_outcome = Column(String(50), nullable=True)  # WIN_T1, WIN_T2, WIN_T3, LOSS_SL, MISSED, EXPIRED, CLOSED_EOD
    gross_pnl_points = Column(Float, default=0.0, nullable=False)
    net_pnl_inr = Column(Float, default=0.0, nullable=False)
    lot_size = Column(Integer, default=25, nullable=False)
    allocated_lots = Column(Integer, default=1, nullable=False)
    remaining_fraction = Column(Float, default=1.0, nullable=False)
    data_quality_notes = Column(Text, nullable=True)
    is_live = Column(Boolean, default=True, nullable=False)

    # Relationships
    snapshots = relationship("SignalSnapshotRecord", back_populates="signal", cascade="all, delete-orphan", lazy="selectin")
    events = relationship("SignalEventRecord", back_populates="signal", cascade="all, delete-orphan", lazy="selectin")
    price_observations = relationship("SignalPriceObservationRecord", back_populates="signal", cascade="all, delete-orphan", lazy="selectin")
    status_history = relationship("SignalStatusHistoryRecord", back_populates="signal", cascade="all, delete-orphan", lazy="selectin")


class SignalSnapshotRecord(Base):
    __tablename__ = "signal_snapshots"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    signal_id = Column(String(36), ForeignKey("signals.id"), nullable=False, index=True)
    snapshot_timestamp = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    raw_snapshot = Column(JSON, nullable=False)

    signal = relationship("SignalRecord", back_populates="snapshots")


class SignalEventRecord(Base):
    __tablename__ = "signal_events"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    idempotency_key = Column(String(120), unique=True, nullable=True, index=True)
    signal_id = Column(String(36), ForeignKey("signals.id"), nullable=False, index=True)
    event_type = Column(String(40), nullable=False)  # ENTRY_TRIGGERED, T1_HIT, T2_HIT, T3_HIT, STOP_LOSS_HIT, EXIT_CONDITION_HIT, TIME_EXIT, END_OF_DAY_CLOSE, MISSED, CANCELLED, DATA_GAP, AMBIGUOUS
    target_number = Column(Integer, nullable=True)
    market_price = Column(Float, nullable=False)
    bid = Column(Float, nullable=True)
    ask = Column(Float, nullable=True)
    volume = Column(Integer, nullable=True)
    market_timestamp = Column(DateTime(timezone=True), nullable=False)
    received_timestamp = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    elapsed_seconds_from_signal = Column(Float, nullable=False)
    elapsed_seconds_from_entry = Column(Float, nullable=True)
    price_source = Column(String(50), default="angelone_websocket_smartstream", nullable=False)
    data_quality_status = Column(String(30), default="CONFIRMED", nullable=False)
    position_fraction_closed = Column(Float, default=0.0, nullable=False)
    remaining_position_fraction = Column(Float, default=1.0, nullable=False)
    event_details = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    signal = relationship("SignalRecord", back_populates="events")


class SignalPriceObservationRecord(Base):
    __tablename__ = "signal_price_observations"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    signal_id = Column(String(36), ForeignKey("signals.id"), nullable=False, index=True)
    contract_symbol = Column(String(60), nullable=False)
    instrument_token = Column(String(30), nullable=False, index=True)
    market_timestamp = Column(DateTime(timezone=True), nullable=False)
    received_timestamp = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    ltp = Column(Float, nullable=False)
    bid = Column(Float, nullable=True)
    ask = Column(Float, nullable=True)
    volume = Column(Integer, nullable=True)
    source = Column(String(30), default="angelone_stream", nullable=False)
    data_status = Column(String(20), default="LIVE", nullable=False)

    signal = relationship("SignalRecord", back_populates="price_observations")


class SignalStatusHistoryRecord(Base):
    __tablename__ = "signal_status_history"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    signal_id = Column(String(36), ForeignKey("signals.id"), nullable=False, index=True)
    from_status = Column(String(30), nullable=False)
    to_status = Column(String(30), nullable=False)
    reason = Column(String(255), nullable=True)
    timestamp = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    signal = relationship("SignalRecord", back_populates="status_history")


class PerformanceSnapshotRecord(Base):
    __tablename__ = "performance_snapshots"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    snapshot_date = Column(String(10), nullable=False, index=True)  # YYYY-MM-DD
    symbol_scope = Column(String(30), default="ALL", nullable=False, index=True)
    strategy_version = Column(String(30), default="v2.1", nullable=False)
    total_signals = Column(Integer, default=0, nullable=False)
    triggered_entries = Column(Integer, default=0, nullable=False)
    untriggered_entries = Column(Integer, default=0, nullable=False)
    active_setups = Column(Integer, default=0, nullable=False)
    t1_hit_count = Column(Integer, default=0, nullable=False)
    t2_hit_count = Column(Integer, default=0, nullable=False)
    t3_hit_count = Column(Integer, default=0, nullable=False)
    sl_hit_count = Column(Integer, default=0, nullable=False)
    sl_after_partial_count = Column(Integer, default=0, nullable=False)
    expired_count = Column(Integer, default=0, nullable=False)
    missed_count = Column(Integer, default=0, nullable=False)
    ambiguous_count = Column(Integer, default=0, nullable=False)
    data_gap_count = Column(Integer, default=0, nullable=False)
    t1_hit_rate = Column(Float, default=0.0, nullable=False)
    avg_seconds_to_t1 = Column(Float, default=0.0, nullable=False)
    median_seconds_to_t1 = Column(Float, default=0.0, nullable=False)
    avg_seconds_to_t2 = Column(Float, default=0.0, nullable=False)
    median_seconds_to_t2 = Column(Float, default=0.0, nullable=False)
    avg_seconds_to_t3 = Column(Float, default=0.0, nullable=False)
    median_seconds_to_t3 = Column(Float, default=0.0, nullable=False)
    avg_seconds_to_sl = Column(Float, default=0.0, nullable=False)
    gross_paper_pnl = Column(Float, default=0.0, nullable=False)
    net_paper_pnl = Column(Float, default=0.0, nullable=False)
    profit_factor = Column(Float, default=0.0, nullable=False)
    max_drawdown = Column(Float, default=0.0, nullable=False)
    expectancy_r = Column(Float, default=0.0, nullable=False)
    metrics_payload = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)


class DailyPerformanceRecord(Base):
    __tablename__ = "daily_performance"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    performance_date = Column(String(10), nullable=False, index=True)  # YYYY-MM-DD
    symbol = Column(String(30), default="ALL", nullable=False, index=True)
    strategy_version = Column(String(30), default="v2.1", nullable=False)
    total_signals = Column(Integer, default=0, nullable=False)
    call_signals = Column(Integer, default=0, nullable=False)
    put_signals = Column(Integer, default=0, nullable=False)
    triggered_entries = Column(Integer, default=0, nullable=False)
    missed_setups = Column(Integer, default=0, nullable=False)
    expired_setups = Column(Integer, default=0, nullable=False)
    cancelled_setups = Column(Integer, default=0, nullable=False)
    unresolved_signals = Column(Integer, default=0, nullable=False)
    successful_outcomes = Column(Integer, default=0, nullable=False)
    failed_outcomes = Column(Integer, default=0, nullable=False)
    sl_hits_before_target = Column(Integer, default=0, nullable=False)
    sl_hits_after_partial = Column(Integer, default=0, nullable=False)
    t1_hits = Column(Integer, default=0, nullable=False)
    t2_hits = Column(Integer, default=0, nullable=False)
    t3_hits = Column(Integer, default=0, nullable=False)
    data_gap_count = Column(Integer, default=0, nullable=False)
    ambiguous_count = Column(Integer, default=0, nullable=False)
    entry_trigger_rate = Column(Float, default=0.0, nullable=False)
    t1_hit_rate = Column(Float, default=0.0, nullable=False)
    final_win_rate = Column(Float, default=0.0, nullable=False)
    stop_loss_rate = Column(Float, default=0.0, nullable=False)
    avg_seconds_to_t1 = Column(Float, default=0.0, nullable=False)
    median_seconds_to_t1 = Column(Float, default=0.0, nullable=False)
    avg_seconds_to_t2 = Column(Float, default=0.0, nullable=False)
    avg_seconds_to_t3 = Column(Float, default=0.0, nullable=False)
    avg_seconds_to_sl = Column(Float, default=0.0, nullable=False)
    gross_paper_pnl = Column(Float, default=0.0, nullable=False)
    net_paper_pnl = Column(Float, default=0.0, nullable=False)
    metrics_payload = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)



class ResearchSetupEvaluationRecord(Base):
    """Separate research observations; never counted as production signals or fills."""
    __tablename__ = "research_setup_evaluations"
    id = Column(String(36), primary_key=True)
    engine_id = Column(String(50), nullable=False, index=True)
    symbol = Column(String(30), nullable=False, index=True)
    evaluated_at = Column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)
    qualified = Column(Boolean, nullable=False)
    payload = Column(JSON, nullable=False)
