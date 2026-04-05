"""
Session Manager - Market Hours and Trading Session Management
Handles market sessions for crypto (24/7), equities (9:30-4pm EST), and futures.
Uses holidays library for dynamic US market holidays.
HARDENED: Dynamic holiday calculation via holidays library, no static date tuples.
"""

import logging
from datetime import datetime, time, timedelta, date
from typing import Optional, Dict, List, Tuple
from enum import Enum

import pytz

# Dynamic holiday calendar
try:
    import holidays
    HOLIDAYS_AVAILABLE = True
except ImportError:
    HOLIDAYS_AVAILABLE = False
    logging.warning("holidays library not available, falling back to static holiday list")

from app.constants import MarketSession, AssetClass

logger = logging.getLogger(__name__)


class SessionManager:
    """
    Manages trading sessions across all markets.
    Crypto: 24/7 always open
    Equities: 9:30 AM - 4:00 PM EST, with early closes on certain days
    Futures: Sunday 6:00 PM - Friday 5:00 PM EST
    Extended Hours: 8:00 AM - 9:30 AM and 4:00 PM - 8:00 PM EST
    """

    # US Eastern timezone (hard requirement)
    EST = pytz.timezone('US/Eastern')
    UTC = pytz.UTC

    # Early close days: (month, day) -> close hour (13 = 1pm)
    EARLY_CLOSE_DAYS: Dict[Tuple[int, int], int] = {
        # Day before Thanksgiving (floating, handled dynamically)
        # Black Friday (day after Thanksgiving)
        # Christmas Eve (Dec 24)
        (12, 24): 13,  # Christmas Eve - 1pm close
        (7, 3): 13,    # Day before Independence Day (if July 4 is Tue-Thu)
        (7, 5): 13,    # Day after Independence Day (if July 4 is Thu)
    }

    def __init__(self):
        """Initialize session manager with dynamic holiday calendar."""
        self._holiday_cache: Dict[int, List[date]] = {}
        logger.info("SessionManager initialized")

    def _get_us_holidays(self, year: int) -> List[date]:
        """
        Get US market holidays for a given year using holidays library.
        Caches results for performance.

        Args:
            year: Year to get holidays for

        Returns:
            List of holiday dates
        """
        if year in self._holiday_cache:
            return self._holiday_cache[year]

        holidays_list = []

        if HOLIDAYS_AVAILABLE:
            try:
                # US holidays including NYSE observed holidays
                us_holidays = holidays.US(years=year, observed=True)

                # NYSE-specific holidays (subset of US holidays)
                # NYSE is closed on: New Year's Day, MLK Day, Presidents Day,
                # Good Friday, Memorial Day, Juneteenth, Independence Day,
                # Labor Day, Thanksgiving, Christmas Day
                for dt, name in us_holidays.items():
                    # Filter to NYSE holidays
                    nyse_holidays = [
                        "New Year's Day", "Martin Luther King Jr. Day",
                        "Washington's Birthday", "Presidents Day",
                        "Good Friday", "Memorial Day", "Juneteenth",
                        "Independence Day", "Labor Day", "Thanksgiving",
                        "Christmas Day", "Christmas observed", "New Year's Day (observed)"
                    ]
                    if any(hol in name for hol in nyse_holidays):
                        holidays_list.append(dt)

                logger.debug(f"Found {len(holidays_list)} NYSE holidays for {year}")
            except Exception as e:
                logger.error(f"Failed to get holidays for {year}: {e}")
                holidays_list = self._get_fallback_holidays(year)
        else:
            holidays_list = self._get_fallback_holidays(year)

        self._holiday_cache[year] = holidays_list
        return holidays_list

    def _get_fallback_holidays(self, year: int) -> List[date]:
        """
        Fallback static holiday list when holidays library is unavailable.
        These are approximate dates for 2024-2028.

        Args:
            year: Year to get holidays for

        Returns:
            List of holiday dates
        """
        fallback = []

        # New Year's Day
        fallback.append(date(year, 1, 1))

        # MLK Day - Third Monday of January
        mlk = self._get_nth_weekday_of_month(year, 1, 0, 3)
        fallback.append(mlk)

        # Presidents Day - Third Monday of February
        presidents = self._get_nth_weekday_of_month(year, 2, 0, 3)
        fallback.append(presidents)

        # Good Friday - Approximate (2 days before Easter)
        easter_dates = {
            2024: (3, 31), 2025: (4, 20), 2026: (4, 5),
            2027: (3, 28), 2028: (4, 16),
        }
        if year in easter_dates:
            easter_month, easter_day = easter_dates[year]
            easter = date(year, easter_month, easter_day)
            good_friday = easter - timedelta(days=2)
            fallback.append(good_friday)

        # Memorial Day - Last Monday of May
        memorial = self._get_nth_weekday_of_month(year, 5, 0, 5)
        fallback.append(memorial)

        # Juneteenth - June 19
        fallback.append(date(year, 6, 19))

        # Independence Day - July 4
        fallback.append(date(year, 7, 4))

        # Labor Day - First Monday of September
        labor = self._get_nth_weekday_of_month(year, 9, 0, 1)
        fallback.append(labor)

        # Thanksgiving - Fourth Thursday of November
        thanksgiving = self._get_nth_weekday_of_month(year, 11, 3, 4)
        fallback.append(thanksgiving)

        # Christmas Day - December 25
        fallback.append(date(year, 12, 25))

        return fallback

    def _get_nth_weekday_of_month(self, year: int, month: int, weekday: int, n: int) -> date:
        """
        Get the nth occurrence of a weekday in a month.
        weekday: 0=Monday, 1=Tuesday, ..., 6=Sunday
        n: 1=first, 2=second, 3=third, 4=fourth, 5=last (use 5 for last)
        """
        first_day = date(year, month, 1)
        first_weekday = first_day.weekday()

        # Days to first target weekday
        days_to_target = (weekday - first_weekday) % 7
        first_target = first_day + timedelta(days=days_to_target)

        if n == 5:  # Last occurrence
            # Get last day of month
            last_day = date(year, month, 28) + timedelta(days=4)
            last_day = last_day - timedelta(days=last_day.day - 1)
            last_day = last_day.replace(day=28) + timedelta(days=4)
            last_day = last_day - timedelta(days=last_day.day)
            last_weekday = last_day.weekday()
            days_from_last = (last_weekday - weekday) % 7
            return last_day - timedelta(days=days_from_last)

        return first_target + timedelta(days=(n - 1) * 7)

    def _is_early_close_day(self, dt: datetime) -> Optional[int]:
        """
        Check if a given datetime is an early close day.
        Returns close hour (13 for 1pm) or None.

        Args:
            dt: Datetime to check (EST)

        Returns:
            Close hour if early close, None otherwise
        """
        # Check static early close days
        key = (dt.month, dt.day)
        if key in self.EARLY_CLOSE_DAYS:
            return self.EARLY_CLOSE_DAYS[key]

        # Check day before Thanksgiving
        if HOLIDAYS_AVAILABLE:
            thanksgiving = self._get_thanksgiving(dt.year)
            if thanksgiving and dt.date() == thanksgiving - timedelta(days=1):
                return 13  # 1pm close day before Thanksgiving
        else:
            # Fallback: approximate Thanksgiving (4th Thursday)
            thanksgiving = self._get_nth_weekday_of_month(dt.year, 11, 3, 4)
            if dt.date() == thanksgiving - timedelta(days=1):
                return 13

        # Check Black Friday (day after Thanksgiving)
        if HOLIDAYS_AVAILABLE:
            thanksgiving = self._get_thanksgiving(dt.year)
            if thanksgiving and dt.date() == thanksgiving + timedelta(days=1):
                return 13  # 1pm close Black Friday
        else:
            thanksgiving = self._get_nth_weekday_of_month(dt.year, 11, 3, 4)
            if dt.date() == thanksgiving + timedelta(days=1):
                return 13

        return None

    def _get_thanksgiving(self, year: int) -> Optional[date]:
        """Get Thanksgiving date for a given year."""
        if HOLIDAYS_AVAILABLE:
            us_holidays = holidays.US(years=year)
            for dt, name in us_holidays.items():
                if "Thanksgiving" in name:
                    return dt
        return self._get_nth_weekday_of_month(year, 11, 3, 4)

    def is_holiday(self, dt: datetime) -> bool:
        """
        Check if a given datetime is a US market holiday.

        Args:
            dt: Datetime to check

        Returns:
            True if holiday
        """
        dt_est = dt.astimezone(self.EST)
        holidays_list = self._get_us_holidays(dt_est.year)
        return dt_est.date() in holidays_list

    def is_trading_day(self, dt: datetime) -> bool:
        """
        Check if it's a trading day (weekday and not holiday).

        Args:
            dt: Datetime to check

        Returns:
            True if trading day
        """
        dt_est = dt.astimezone(self.EST)

        # Weekend
        if dt_est.weekday() >= 5:  # Saturday = 5, Sunday = 6
            return False

        # Holiday
        if self.is_holiday(dt_est):
            return False

        return True

    def is_equity_hours(self, dt: Optional[datetime] = None, extended: bool = False) -> bool:
        """
        Check if during equity trading hours.

        Args:
            dt: Datetime to check (defaults to now)
            extended: If True, includes extended hours (8am-9:30am, 4pm-8pm)

        Returns:
            True if market is open
        """
        if dt is None:
            dt = datetime.now(self.UTC)

        # Convert to EST
        dt_est = dt.astimezone(self.EST)

        # Check trading day
        if not self.is_trading_day(dt_est):
            return False

        # Check if early close
        early_close_hour = self._is_early_close_day(dt_est)

        if extended:
            # Extended hours: 8:00 AM - 9:30 AM and 4:00 PM - 8:00 PM
            regular_open = dt_est.replace(hour=9, minute=30, second=0, microsecond=0)
            regular_close = dt_est.replace(hour=16, minute=0, second=0, microsecond=0)

            if early_close_hour:
                regular_close = dt_est.replace(hour=early_close_hour, minute=0, second=0, microsecond=0)

            extended_open = dt_est.replace(hour=8, minute=0, second=0, microsecond=0)

            # Pre-market: 8:00 AM - 9:30 AM
            if extended_open <= dt_est < regular_open:
                return True
            # Post-market: 4:00 PM - 8:00 PM (or early close time)
            if regular_close <= dt_est < regular_close.replace(hour=20):
                return True
            # Regular hours
            return regular_open <= dt_est <= regular_close
        else:
            # Regular hours only
            regular_open = dt_est.replace(hour=9, minute=30, second=0, microsecond=0)
            regular_close = dt_est.replace(hour=16, minute=0, second=0, microsecond=0)

            if early_close_hour:
                regular_close = dt_est.replace(hour=early_close_hour, minute=0, second=0, microsecond=0)

            return regular_open <= dt_est <= regular_close

    def is_futures_hours(self, dt: Optional[datetime] = None) -> bool:
        """
        Check if during futures trading hours (Sunday 6pm - Friday 5pm EST).

        Args:
            dt: Datetime to check (defaults to now)

        Returns:
            True if market is open
        """
        if dt is None:
            dt = datetime.now(self.UTC)

        # Convert to EST
        dt_est = dt.astimezone(self.EST)

        # Sunday after 6pm is open
        if dt_est.weekday() == 6 and dt_est.hour >= 18:
            return True

        # Monday-Thursday: all day
        if 0 <= dt_est.weekday() <= 3:
            return True

        # Friday: before 5pm
        if dt_est.weekday() == 4 and dt_est.hour < 17:
            return True

        return False

    def is_crypto_hours(self, dt: Optional[datetime] = None) -> bool:
        """
        Crypto markets are 24/7, always open.

        Args:
            dt: Datetime (ignored, always True)

        Returns:
            Always True
        """
        return True

    def is_session_open(self, session: MarketSession, dt: Optional[datetime] = None, extended: bool = False) -> bool:
        """
        Check if a specific market session is open.

        Args:
            session: Market session to check
            dt: Datetime to check (defaults to now)
            extended: For equities, include extended hours

        Returns:
            True if session is open
        """
        if dt is None:
            dt = datetime.now(self.UTC)

        if session == MarketSession.CRYPTO_24_7:
            return self.is_crypto_hours(dt)
        elif session == MarketSession.EQUITY:
            return self.is_equity_hours(dt, extended)
        elif session == MarketSession.FUTURES:
            return self.is_futures_hours(dt)
        else:
            logger.warning(f"Unknown session: {session}")
            return False

    def get_next_open_time(self, session: MarketSession, from_time: Optional[datetime] = None, extended: bool = False) -> Optional[datetime]:
        """
        Get the next time a session opens.

        Args:
            session: Market session
            from_time: Starting time (defaults to now)
            extended: For equities, consider extended hours

        Returns:
            Next open time, or None if cannot determine
        """
        if from_time is None:
            from_time = datetime.now(self.UTC)

        # Convert to EST for equity/futures calculations
        from_est = from_time.astimezone(self.EST)

        if session == MarketSession.CRYPTO_24_7:
            return from_time

        elif session == MarketSession.EQUITY:
            # Start checking from next day
            next_day = from_est + timedelta(days=1)
            next_day = next_day.replace(hour=8 if extended else 9, minute=30, second=0, microsecond=0)

            # Skip weekends and holidays
            while not self.is_trading_day(next_day):
                next_day += timedelta(days=1)
                next_day = next_day.replace(hour=8 if extended else 9, minute=30, second=0, microsecond=0)

            return next_day.astimezone(self.UTC)

        elif session == MarketSession.FUTURES:
            weekday = from_est.weekday()
            hour = from_est.hour

            # Friday after 5pm: next open is Sunday 6pm
            if weekday == 4 and hour >= 17:
                days_to_add = 2
                next_open = from_est + timedelta(days=days_to_add)
                next_open = next_open.replace(hour=18, minute=0, second=0, microsecond=0)
            # Saturday: next open is Sunday 6pm
            elif weekday == 5:
                days_to_add = 1
                next_open = from_est + timedelta(days=days_to_add)
                next_open = next_open.replace(hour=18, minute=0, second=0, microsecond=0)
            # Sunday before 6pm: open at 6pm same day
            elif weekday == 6 and hour < 18:
                next_open = from_est.replace(hour=18, minute=0, second=0, microsecond=0)
            else:
                # Already open
                return from_time

            return next_open.astimezone(self.UTC)

        return None

    def get_next_close_time(self, session: MarketSession, from_time: Optional[datetime] = None) -> Optional[datetime]:
        """
        Get the next time a session closes.

        Args:
            session: Market session
            from_time: Starting time (defaults to now)

        Returns:
            Next close time, or None if cannot determine
        """
        if from_time is None:
            from_time = datetime.now(self.UTC)

        from_est = from_time.astimezone(self.EST)

        if session == MarketSession.CRYPTO_24_7:
            return None

        elif session == MarketSession.EQUITY:
            # Check if today has early close
            early_close_hour = self._is_early_close_day(from_est)
            close_hour = early_close_hour if early_close_hour else 16
            close_time = from_est.replace(hour=close_hour, minute=0, second=0, microsecond=0)

            if from_est < close_time and self.is_trading_day(from_est):
                return close_time.astimezone(self.UTC)
            else:
                # Next trading day
                next_day = from_est + timedelta(days=1)
                next_day = next_day.replace(hour=16, minute=0, second=0, microsecond=0)

                while not self.is_trading_day(next_day):
                    next_day += timedelta(days=1)

                # Check early close on next trading day
                early_close_next = self._is_early_close_day(next_day)
                if early_close_next:
                    next_day = next_day.replace(hour=early_close_next, minute=0, second=0, microsecond=0)

                return next_day.astimezone(self.UTC)

        elif session == MarketSession.FUTURES:
            weekday = from_est.weekday()
            hour = from_est.hour

            if weekday == 4 and hour < 17:
                # Friday before close
                close_time = from_est.replace(hour=17, minute=0, second=0, microsecond=0)
                return close_time.astimezone(self.UTC)
            elif weekday < 4:
                # Next close is Friday 5pm
                days_to_friday = 4 - weekday
                close_time = from_est + timedelta(days=days_to_friday)
                close_time = close_time.replace(hour=17, minute=0, second=0, microsecond=0)
                return close_time.astimezone(self.UTC)
            else:
                return None

        return None

    def get_remaining_session_time(self, session: MarketSession, dt: Optional[datetime] = None) -> float:
        """Get remaining time in current session in seconds."""
        if dt is None:
            dt = datetime.now(self.UTC)

        if not self.is_session_open(session, dt):
            return 0.0

        next_close = self.get_next_close_time(session, dt)
        if next_close is None:
            return float('inf')

        return (next_close - dt).total_seconds()

    def get_asset_class_session(self, asset_class: AssetClass) -> MarketSession:
        """Get the market session for an asset class."""
        session_map = {
            AssetClass.CRYPTO: MarketSession.CRYPTO_24_7,
            AssetClass.EQUITY: MarketSession.EQUITY,
            AssetClass.ETF: MarketSession.EQUITY,
            AssetClass.FUTURE: MarketSession.FUTURES,
        }
        return session_map.get(asset_class, MarketSession.CRYPTO_24_7)

    def is_tradable(self, asset_class: AssetClass, dt: Optional[datetime] = None, extended: bool = False) -> bool:
        """Check if an asset class is tradable now."""
        session = self.get_asset_class_session(asset_class)
        return self.is_session_open(session, dt, extended)

    def get_session_status(self, dt: Optional[datetime] = None) -> Dict[str, bool]:
        """Get status of all sessions."""
        if dt is None:
            dt = datetime.now(self.UTC)

        return {
            "crypto": self.is_crypto_hours(dt),
            "equity": self.is_equity_hours(dt, extended=False),
            "equity_extended": self.is_equity_hours(dt, extended=True),
            "futures": self.is_futures_hours(dt),
            "is_trading_day": self.is_trading_day(dt),
        }

    def is_extended_hours(self, dt: Optional[datetime] = None) -> bool:
        """Check if currently in extended hours (pre-market or post-market)."""
        if dt is None:
            dt = datetime.now(self.UTC)
        return self.is_equity_hours(dt, extended=True) and not self.is_equity_hours(dt, extended=False)