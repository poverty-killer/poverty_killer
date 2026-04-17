"""
Polling Client - REST API Fallback for Market Data
Provides REST API polling for symbols without WebSocket support.
Acts as fallback when WebSocket connection fails.

TIMESTAMP TRUTH:
- exchange_ts_ns extracted from exchange response where available
- Fallback to now_ns() is permitted for REST polling (non-authoritative fallback)
- receive_ts_ns captured at response receipt for monitoring
"""

import asyncio
import logging
import time
from typing import Dict, List, Optional, Callable, Any
from datetime import datetime, timedelta

import aiohttp

from app.models import Candle, OrderBookSnapshot
from app.utils.time_utils import now_ns

logger = logging.getLogger(__name__)

# Kraken REST uses XBT for Bitcoin, not BTC
_KRAKEN_BASE_MAP = {"BTC": "XBT"}


class PollingClient:
    """
    REST API polling client for market data.
    Used as fallback when WebSocket is unavailable.
    """

    def __init__(
        self,
        symbols: List[str],
        interval: float = 1.0,
        on_candle: Optional[Callable] = None,
        on_order_book: Optional[Callable] = None,
        exchange: str = "kraken"
    ):
        """
        Initialize polling client.

        Args:
            symbols: List of symbols to poll
            interval: Polling interval in seconds
            on_candle: Callback for candle data
            on_order_book: Callback for order book data
            exchange: Exchange name for API endpoints
        """
        self.symbols = symbols
        self.interval = interval
        self.on_candle = on_candle
        self.on_order_book = on_order_book
        self.exchange = exchange

        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._session: Optional[aiohttp.ClientSession] = None

        # Track last candle timestamps to avoid duplicates
        self._last_candle_timestamps_ns: Dict[str, int] = {}

        # API endpoints (example for Kraken)
        self._endpoints = {
            "kraken": {
                "candle": "https://api.kraken.com/0/public/OHLC",
                "order_book": "https://api.kraken.com/0/public/Depth"
            }
        }

        logger.info(f"PollingClient initialized: {len(symbols)} symbols, interval={interval}s")

    @property
    def is_running(self) -> bool:
        """Return running status."""
        return self._running

    async def start(self) -> None:
        """Start polling loop."""
        if self._running:
            logger.warning("PollingClient already running")
            return

        self._running = True
        self._session = aiohttp.ClientSession()
        self._task = asyncio.create_task(self._poll_loop())
        logger.info("PollingClient started")

    async def stop(self) -> None:
        """Stop polling loop."""
        self._running = False

        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        if self._session:
            await self._session.close()

        logger.info("PollingClient stopped")

    async def _poll_loop(self) -> None:
        """Main polling loop."""
        while self._running:
            try:
                start_time_ns = now_ns()

                # Poll all symbols
                await self._poll_all_symbols()

                # Calculate sleep time to maintain interval
                elapsed_ns = now_ns() - start_time_ns
                elapsed_sec = elapsed_ns / 1_000_000_000.0
                sleep_sec = max(0, self.interval - elapsed_sec)
                await asyncio.sleep(sleep_sec)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Polling loop error: {e}")
                await asyncio.sleep(self.interval)

    async def _poll_all_symbols(self) -> None:
        """Poll all symbols for data."""
        # Poll candles
        if self.on_candle:
            candle_tasks = [self._fetch_candles(symbol) for symbol in self.symbols]
            await asyncio.gather(*candle_tasks, return_exceptions=True)

        # Poll order books
        if self.on_order_book:
            book_tasks = [self._fetch_order_book(symbol) for symbol in self.symbols]
            await asyncio.gather(*book_tasks, return_exceptions=True)

    async def _fetch_candles(self, symbol: str) -> None:
        """
        Fetch candles for a symbol.

        Args:
            symbol: Trading symbol
        """
        try:
            endpoint = self._endpoints.get(self.exchange, {}).get("candle")
            if not endpoint:
                return

            # Format symbol for exchange
            formatted_symbol = self._format_symbol(symbol)

            params = {
                "pair": formatted_symbol,
                "interval": 1  # 1 minute
            }

            async with self._session.get(endpoint, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    candles = self._parse_candles(data, symbol)

                    for candle in candles:
                        # Check for duplicate
                        last_ts_ns = self._last_candle_timestamps_ns.get(symbol)
                        if last_ts_ns and candle.exchange_ts_ns <= last_ts_ns:
                            continue

                        self._last_candle_timestamps_ns[symbol] = candle.exchange_ts_ns

                        if self.on_candle:
                            await self._safe_callback(self.on_candle, candle)

        except aiohttp.ClientError as e:
            logger.error(f"HTTP error fetching candles for {symbol}: {e}")
        except Exception as e:
            logger.error(f"Error fetching candles for {symbol}: {e}")

    async def _fetch_order_book(self, symbol: str) -> None:
        """
        Fetch order book for a symbol.

        Args:
            symbol: Trading symbol
        """
        try:
            endpoint = self._endpoints.get(self.exchange, {}).get("order_book")
            if not endpoint:
                return

            formatted_symbol = self._format_symbol(symbol)

            params = {
                "pair": formatted_symbol,
                "count": 50
            }

            async with self._session.get(endpoint, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    order_book = self._parse_order_book(data, symbol)

                    if order_book and self.on_order_book:
                        await self._safe_callback(self.on_order_book, order_book)

        except aiohttp.ClientError as e:
            logger.error(f"HTTP error fetching order book for {symbol}: {e}")
        except Exception as e:
            logger.error(f"Error fetching order book for {symbol}: {e}")

    def _format_symbol(self, symbol: str) -> str:
        """
        Format symbol for Kraken REST API.

        Args:
            symbol: Trading symbol in canonical slash-form (e.g., "BTC/USD")

        Returns:
            Kraken REST pair identifier (e.g., "XBTUSD")
        """
        if "/" in symbol:
            base, quote = symbol.split("/", 1)
            base = _KRAKEN_BASE_MAP.get(base, base)
            return f"{base}{quote}"
        return symbol

    def _parse_candles(self, data: Dict, symbol: str) -> List[Candle]:
        """
        Parse candles from exchange response.

        Args:
            data: Raw API response
            symbol: Trading symbol

        Returns:
            List of Candle objects
        """
        candles = []

        try:
            # Kraken format: result[formatted_symbol] = [[time, open, high, low, close, vwap, volume, count], ...]
            result = data.get("result", {})
            for key, ohlc_data in result.items():
                if isinstance(ohlc_data, list):
                    for item in ohlc_data:
                        if len(item) >= 7:
                            # Kraken REST OHLC returns time as Unix seconds (not ms)
                            timestamp_sec = item[0]
                            exchange_ts_ns = int(timestamp_sec) * 1_000_000_000
                            
                            candle = Candle(
                                symbol=symbol,
                                exchange_ts_ns=exchange_ts_ns,
                                open=float(item[1]),
                                high=float(item[2]),
                                low=float(item[3]),
                                close=float(item[4]),
                                volume=float(item[6]),
                                timeframe="1m"
                            )
                            candles.append(candle)
                    break

        except Exception as e:
            logger.error(f"Failed to parse candles: {e}")

        return candles

    def _parse_order_book(self, data: Dict, symbol: str) -> Optional[OrderBookSnapshot]:
        """
        Parse order book from exchange response.

        Args:
            data: Raw API response
            symbol: Trading symbol

        Returns:
            OrderBookSnapshot or None
        """
        try:
            result = data.get("result", {})
            for key, book_data in result.items():
                if isinstance(book_data, dict):
                    bids = [(float(price), float(size)) for price, size in book_data.get("bids", [])]
                    asks = [(float(price), float(size)) for price, size in book_data.get("asks", [])]
                    
                    # REST responses often lack timestamp; use receipt time as fallback
                    # This is a REST polling fallback, not authoritative WebSocket path
                    exchange_ts_ns = now_ns()

                    return OrderBookSnapshot(
                        symbol=symbol,
                        exchange_ts_ns=exchange_ts_ns,
                        bids=bids[:50],
                        asks=asks[:50]
                    )

        except Exception as e:
            logger.error(f"Failed to parse order book: {e}")

        return None

    async def _safe_callback(self, callback: Callable, data: Any) -> None:
        """
        Execute callback safely.

        Args:
            callback: Callback function
            data: Data to pass to callback
        """
        try:
            if asyncio.iscoroutinefunction(callback):
                await callback(data)
            else:
                callback(data)
        except Exception as e:
            logger.error(f"Callback error: {e}")

    def get_stats(self) -> Dict[str, Any]:
        """
        Get polling client statistics.

        Returns:
            Dictionary with polling stats
        """
        return {
            "running": self._running,
            "interval": self.interval,
            "symbols": len(self.symbols),
            "last_candle_timestamps_ns": self._last_candle_timestamps_ns.copy()
        }

    async def force_poll(self, symbol: Optional[str] = None) -> None:
        """
        Force immediate poll for a symbol.

        Args:
            symbol: Symbol to poll (None for all)
        """
        if symbol:
            await self._fetch_candles(symbol)
            await self._fetch_order_book(symbol)
        else:
            await self._poll_all_symbols()