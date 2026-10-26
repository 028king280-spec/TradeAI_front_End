from datetime import datetime, time, date
import zoneinfo

IST_ZONE = zoneinfo.ZoneInfo("Asia/Kolkata")

# Recognized NSE / BSE standard market holidays (YYYY-MM-DD)
NSE_HOLIDAYS = {
    date(2026, 1, 26),  # Republic Day
    date(2026, 3, 3),   # Mahashivratri
    date(2026, 3, 17),  # Holi
    date(2026, 4, 3),   # Good Friday
    date(2026, 4, 14),  # Dr. Ambedkar Jayanti
    date(2026, 5, 1),   # Maharashtra Day
    date(2026, 8, 15),  # Independence Day
    date(2026, 9, 16),  # Eid-e-Milad
    date(2026, 10, 2),  # Mahatma Gandhi Jayanti
    date(2026, 10, 20), # Dussehra
    date(2026, 11, 9),  # Diwali Laxmi Pujan
    date(2026, 11, 10), # Diwali Balipratipada
    date(2026, 11, 24), # Gurunanak Jayanti
    date(2026, 12, 25), # Christmas
}


class MarketCalendar:
    @staticmethod
    def now_ist() -> datetime:
        return datetime.now(IST_ZONE)

    now = now_ist

    @classmethod
    def is_trading_day(cls, dt: datetime = None) -> bool:
        if dt is None:
            dt = cls.now_ist()
        d = dt.date() if isinstance(dt, datetime) else dt
        # Weekends: Saturday is 5, Sunday is 6
        if d.weekday() >= 5:
            return False
        if d in NSE_HOLIDAYS:
            return False
        return True

    @classmethod
    def is_market_open(cls, dt: datetime = None) -> bool:
        if dt is None:
            dt = cls.now_ist()
        if not cls.is_trading_day(dt):
            return False

        t = dt.time()
        market_open = time(9, 15)
        market_close = time(15, 30)
        return market_open <= t <= market_close

    @classmethod
    def get_market_status(cls, dt: datetime = None) -> str:
        return "OPEN" if cls.is_market_open(dt) else "CLOSED"

    @classmethod
    def get_session_stage(cls, dt: datetime = None) -> str:
        """
        Determines recommendation stage:
        - STAGE_1_PRE_MARKET: Before market open (09:15 IST) or on market closure/holidays.
        - STAGE_2_LIVE_CONFIRMED: Intraday market hours (09:15 - 15:30 IST) with live opening price confirmation.
        """
        return "STAGE_2_LIVE_CONFIRMED" if cls.is_market_open(dt) else "STAGE_1_PRE_MARKET"


    @classmethod
    def get_next_trading_session(cls, dt: datetime = None) -> date:
        from datetime import timedelta
        if dt is None:
            dt = cls.now_ist()
        curr_d = dt.date() if isinstance(dt, datetime) else dt
        next_d = curr_d + timedelta(days=1)
        while not cls.is_trading_day(next_d):
            next_d += timedelta(days=1)
        return next_d

    @classmethod
    def format_ist_timestamp(cls, dt: datetime = None) -> str:
        if dt is None:
            dt = cls.now_ist()
        return dt.strftime("%d %b %Y, %I:%M %p IST")

    @classmethod
    def to_ist_str(cls, dt: datetime = None) -> str:
        if dt is None:
            return ""
        if isinstance(dt, str):
            return dt
        try:
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc).astimezone(IST_ZONE)
            else:
                dt = dt.astimezone(IST_ZONE)
            return dt.strftime("%d %b %Y, %I:%M %p IST")
        except Exception:
            return str(dt)

