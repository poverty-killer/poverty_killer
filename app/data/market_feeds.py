"""
Market Feeds - Centralized Market Data Management
Manages WebSocket and polling clients, provides unified interface for market data.
Handles multiple symbols, data validation, and rolling window storage.

TIMESTAMP TRUTH:
- All market data carries exchange_ts_ns (authoritative)
- Receive timestamps use now_ns() for monitoring only
- No wall-clock substitution in authoritative paths
"""

import asyncio
import logging
from typing import Dict, List, Optional, Callable, Any
from datetime import datetime
from threading import RLock

from app.models import Candle, OrderBookSnapshot
from app.data.rolling_window import RollingWindow
from app.data.validators import DataValidator
from app.data.websocket_client import KrakenWebSocketClient
from app.data.polling_client import PollingClient
from app.utils.time_utils import now_ns

logger = logging.getLogger(__name__)


class MarketFeeds:
    """
    Centralized market data manager.
    Provides unified interface for WebSocket and polling data sources.
    Maintains rolling windows and validates all incoming data.
    """

    def __init__(self, config: Any):
        """
        Initialize market feeds.

        Args:
            config: Configuration object with data settings
        """
        self.config = config
        self.symbols = config.symbol_universe

        # Rolling windows for each symbol
        self.candles = RollingWindow(max_candles=config.data.max_candles_per_symbol)
        self.order_books: Dict[str, OrderBookSnapshot] = {}
        self.depth_history: Dict[str, List[float]] = {}
        self.spread_history: Dict[str, List[float]] = {}

        # Data validator
        self.validator = DataValidator(
            stale_threshold_seconds=config.risk.stale_data_threshold_seconds
        )

        # Clients
        self.websocket_client: Optional[KrakenWebSocketClient] = None
        self.polling_client: Optional[PollingClient] = None

        # Callbacks
        self._candle_callbacks: List[Callable] = []
        self._order_book_callbacks: List[Callable] = []
        self._trade_callbacks: List[Callable] = []  # FIXED: initialized

        self._lock = RLock()

        logger.info(f"MarketFeeds initialized with {len(self.symbols)} symbols")

    async def start(self) -> None:
        """Start all market data feeds."""
        logger.info("Starting market feeds...")

        # Initialize WebSocket client
        self.websocket_client = KrakenWebSocketClient(
            symbols=self.symbols,
            on_candle=self._on_candle,
            on_order_book=self._on_order_book,
            on_trade=self._on_trade
        )
        await self.websocket_client.start()

        # Initialize polling client as fallback
        self.polling_client = PollingClient(
            symbols=self.symbols,
            interval=self.config.data.polling_interval_seconds,
            on_candle=self._on_candle,
            on_order_book=self._on_order_book
        )
        await self.polling_client.start()

        logger.info("Market feeds started")

    async def stop(self) -> None:
        """Stop all market data feeds."""
        logger.info("Stopping market feeds...")

        if self.websocket_client:
            await self.websocket_client.stop()

        if self.polling_client:
            await self.polling_client.stop()

        logger.info("Market feeds stopped")

    def _on_candle(self, candle: Candle) -> None:
        """
        Handle incoming candle data.

        Args:
            candle: Candle to process
        """
        # Validate candle with current time for staleness check
        current_time_ns = now_ns()
        result = self.validator.validate_candle(candle, current_time_ns)
        if not result.is_valid:
            logger.warning(f"Invalid candle for {candle.symbol}: {result.error}")
            return

        # Add to rolling window
        self.candles.add_candle(candle)

        # Notify callbacks
        with self._lock:
            for callback in self._candle_callbacks:
                try:
                    callback(candle)
                except Exception as e:
                    logger.error(f"Candle callback error: {e}")

    def _on_order_book(self, order_book: OrderBookSnapshot) -> None:
        """
        Handle incoming order book data.

        Args:
            order_book: Order book snapshot to process
        """
        # Validate order book with current time for staleness check
        current_time_ns = now_ns()
        result = self.validator.validate_order_book(order_book, current_time_ns)
        if not result.is_valid:
            logger.warning(f"Invalid order book for {order_book.symbol}: {result.error}")
            return

        # Store current order book
        with self._lock:
            self.order_books[order_book.symbol] = order_book

            # Update depth history
            if order_book.symbol not in self.depth_history:
                self.depth_history[order_book.symbol] = []
            self.depth_history[order_book.symbol].append(order_book.market_depth)
            if len(self.depth_history[order_book.symbol]) > 100:
                self.depth_history[order_book.symbol] = self.depth_history[order_book.symbol][-100:]

            # Update spread history
            if order_book.symbol not in self.spread_history:
                self.spread_history[order_book.symbol] = []
            self.spread_history[order_book.symbol].append(order_book.spread_bps)
            if len(self.spread_history[order_book.symbol]) > 100:
                self.spread_history[order_book.symbol] = self.spread_history[order_book.symbol][-100:]

        # Notify callbacks
        with self._lock:
            for callback in self._order_book_callbacks:
                try:
                    callback(order_book)
                except Exception as e:
                    logger.error(f"Order book callback error: {e}")

    def _on_trade(self, trade: Dict[str, Any]) -> None:
        """
        Handle incoming trade data.

        Args:
            trade: Trade dict with keys: symbol, price, volume, side, exchange_ts_ns, receive_ts_ns, trade_id
        """
        # Validate trade data
        price = trade.get("price", 0)
        volume = trade.get("volume", 0)
        exchange_ts_ns = trade.get("exchange_ts_ns", 0)
        
        if price <= 0 or volume <= 0:
            logger.debug(f"Invalid trade: price={price}, volume={volume}")
            return
        
        if exchange_ts_ns <= 0:
            logger.debug(f"Trade missing exchange_ts_ns: {trade}")
            return
        
        # Notify trade callbacks
        with self._lock:
            for callback in self._trade_callbacks:
                try:
                    callback(trade)
                except Exception as e:
                    logger.error(f"Trade callback error: {e}")

    def register_candle_callback(self, callback: Callable) -> None:
        """
        Register callback for new candles.

        Args:
            callback: Function to call on new candle
        """
        with self._lock:
            self._candle_callbacks.append(callback)
            logger.debug(f"Registered candle callback: {callback.__name__}")

    def register_order_book_callback(self, callback: Callable) -> None:
        """
        Register callback for order book updates.

        Args:
            callback: Function to call on order book update
        """
        with self._lock:
            self._order_book_callbacks.append(callback)
            logger.debug(f"Registered order book callback: {callback.__name__}")

    def register_trade_callback(self, callback: Callable) -> None:
        """
        Register callback for trade updates.

        Args:
            callback: Function to call on trade
        """
        with self._lock:
            self._trade_callbacks.append(callback)
            logger.debug(f"Registered trade callback: {callback.__name__}")

    def get_candles(self, symbol: str, count: Optional[int] = None) -> List[Candle]:
        """
        Get recent candles for a symbol.

        Args:
            symbol: Trading symbol
            count: Number of candles to return

        Returns:
            List of candles (most recent last)
        """
        return self.candles.get_candles(symbol, count)

    def get_last_candle(self, symbol: str) -> Optional[Candle]:
        """Get the most recent candle for a symbol."""
        return self.candles.get_last_candle(symbol)

    def get_order_book(self, symbol: str) -> Optional[OrderBookSnapshot]:
        """Get the most recent order book for a symbol."""
        with self._lock:
            return self.order_books.get(symbol)

    def get_depth_history(self, symbol: str, count: int = 50) -> List[float]:
        """Get recent depth history for a symbol."""
        with self._lock:
            history = self.depth_history.get(symbol, [])
            return history[-count:] if history else []

    def get_spread_history(self, symbol: str, count: int = 50) -> List[float]:
        """Get recent spread history for a symbol."""
        with self._lock:
            history = self.spread_history.get(symbol, [])
            return history[-count:] if history else []

    def is_stale(self, symbol: str, current_time_ns: Optional[int] = None) -> bool:
        """
        Check if data for a symbol is stale.

        Args:
            symbol: Trading symbol
            current_time_ns: Current time in nanoseconds (authoritative)

        Returns:
            True if data is stale
        """
        if current_time_ns is None:
            current_time_ns = now_ns()
        
        last_candle = self.get_last_candle(symbol)
        if last_candle is None:
            return True
        
        age_ns = current_time_ns - last_candle.exchange_ts_ns
        age_sec = age_ns / 1_000_000_000.0
        return age_sec > self.validator.stale_threshold_seconds

    def get_stale_status(self, current_time_ns: Optional[int] = None) -> Dict[str, bool]:
        """
        Get stale status for all symbols.

        Args:
            current_time_ns: Current time in nanoseconds (authoritative)

        Returns:
            Dictionary mapping symbol -> is_stale
        """
        if current_time_ns is None:
            current_time_ns = now_ns()
        
        status = {}
        for symbol in self.symbols:
            status[symbol] = self.is_stale(symbol, current_time_ns)
        return status

    def get_latest_price(self, symbol: str) -> Optional[float]:
        """
        Get the latest price for a symbol.

        Args:
            symbol: Trading symbol

        Returns:
            Latest price or None
        """
        order_book = self.get_order_book(symbol)
        if order_book:
            return order_book.mid_price

        candle = self.get_last_candle(symbol)
        if candle:
            return candle.close

        return None

    def get_latest_volume(self, symbol: str) -> Optional[float]:
        """
        Get the latest volume for a symbol.

        Args:
            symbol: Trading symbol

        Returns:
            Latest volume or None
        """
        candle = self.get_last_candle(symbol)
        return candle.volume if candle else None

    def get_market_status(self) -> Dict[str, Any]:
        """
        Get overall market status.

        Returns:
            Dictionary with market status information
        """
        return {
            "symbols": len(self.symbols),
            "candles_per_symbol": {
                sym: self.candles.get_count(sym) for sym in self.symbols
            },
            "order_books_active": len(self.order_books),
            "stale_symbols": [s for s in self.symbols if self.is_stale(s)],
            "websocket_connected": self.websocket_client._connected if self.websocket_client else False,
            "polling_active": self.polling_client.is_running if self.polling_client else False,
            "timestamp_ns": now_ns()
        }

    def get_symbol_stats(self, symbol: str) -> Dict[str, Any]:
        """
        Get detailed statistics for a symbol.

        Args:
            symbol: Trading symbol

        Returns:
            Dictionary with symbol statistics
        """
        candles = self.get_candles(symbol, 100)
        if not candles:
            return {"symbol": symbol, "error": "No data"}

        closes = [c.close for c in candles]
        volumes = [c.volume for c in candles]

        return {
            "symbol": symbol,
            "price": closes[-1] if closes else None,
            "volume_24h": sum(volumes) if volumes else 0,
            "price_change_1h": ((closes[-1] - closes[-20]) / closes[-20] * 100) if len(closes) >= 20 else None,
            "price_change_24h": ((closes[-1] - closes[0]) / closes[0] * 100) if closes else None,
            "high_24h": max(closes) if closes else None,
            "low_24h": min(closes) if closes else None,
            "is_stale": self.is_stale(symbol),
            "candles_count": len(candles),
            "last_exchange_ts_ns": candles[-1].exchange_ts_ns if candles else None
        }