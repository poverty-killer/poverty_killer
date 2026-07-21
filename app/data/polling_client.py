"""
Polling Client - REST API Fallback for Market Data
Provides REST API polling for symbols without WebSocket support.
Acts as fallback when WebSocket connection fails.

TIMESTAMP TRUTH:
- exchange_ts_ns extracted from exchange response where available
- Kraken depth without a source-level timestamp fails closed
- receive_ts_ns remains distinct transport receipt evidence
"""

import asyncio
import calendar
import logging
import math
import random
import socket
import time
from collections import deque
from contextlib import asynccontextmanager
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Dict, List, Optional, Callable, Any, Mapping
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

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
        on_feed_truth: Optional[Callable[[Dict[str, Any]], None]] = None,
        on_rest_latency: Optional[Callable[[Dict[str, Any]], None]] = None,
        exchange: str = "kraken",
        dns_backoff_seconds: float = 15.0,
        provider_id: Optional[str] = None,
        freshness_policy: Optional[Mapping[str, Any]] = None,
        max_concurrency: int = 4,
        failure_history_size: int = 100,
    ):
        """
        Initialize polling client.

        Args:
            symbols: List of symbols to poll
            interval: Polling interval in seconds
            on_candle: Callback for candle data
            on_order_book: Callback for order book data
            exchange: Exchange name for API endpoints
            dns_backoff_seconds: Fail-closed REST DNS retry backoff per endpoint domain
        """
        self.symbols = symbols
        self.interval = interval
        self.on_candle = on_candle
        self.on_order_book = on_order_book
        self.on_feed_truth = on_feed_truth
        self.on_rest_latency = on_rest_latency
        self.exchange = exchange
        self.dns_backoff_seconds = max(1.0, float(dns_backoff_seconds))
        self.provider_id = provider_id or self._default_provider_id(exchange)
        self.freshness_policy = dict(freshness_policy or {})
        self.max_concurrency = max(1, int(max_concurrency))
        self.failure_history_size = max(10, int(failure_history_size))

        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._session: Optional[aiohttp.ClientSession] = None

        # Track last candle timestamps to avoid duplicates
        self._last_candle_timestamps_ns: Dict[str, int] = {}
        self._last_failure_status: Dict[str, Any] = {}
        self._last_success_status: Dict[str, Any] = {}
        self._last_rest_latency_status: Dict[str, Any] = {}
        self._last_recovery_status: Dict[str, Any] = {}
        self._failure_status_by_symbol_feed: Dict[str, Dict[str, Dict[str, Any]]] = {}
        self._failure_history: List[Dict[str, Any]] = []
        self._dns_backoff_until_ns_by_domain: Dict[str, int] = {}

        # Public market-data endpoints only. Trading/account endpoints are not used here.
        self._endpoints = {
            "kraken": {
                "candle": "https://api.kraken.com/0/public/OHLC",
                "order_book": "https://api.kraken.com/0/public/Depth"
            },
            "coinbase": {
                "candle": "https://api.exchange.coinbase.com/products/{product_id}/candles",
                "order_book": "https://api.exchange.coinbase.com/products/{product_id}/book",
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
        # Use Python's socket.getaddrinfo path explicitly. In WSL-launched
        # Windows Python, aiohttp's optional async DNS resolver can diverge
        # from the resolver the diagnostics and runtime process actually use.
        connector = aiohttp.TCPConnector(
            resolver=aiohttp.ThreadedResolver(),
            ttl_dns_cache=30,
            use_dns_cache=True,
        )
        timeout = aiohttp.ClientTimeout(total=10)
        self._session = aiohttp.ClientSession(connector=connector, timeout=timeout)
        self._task = asyncio.create_task(self._poll_loop())
        logger.info("PollingClient started: resolver=threaded_socket_getaddrinfo exchange=%s", self.exchange)

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
        # Legacy cross-venue polling is restricted to the bounded deep set. The
        # Alpaca full-catalog path below batches symbols at the provider API.
        for start in range(0, len(self.symbols), self.max_concurrency):
            symbol_batch = self.symbols[start : start + self.max_concurrency]
            if self.on_candle:
                await asyncio.gather(
                    *(self._fetch_candles(symbol) for symbol in symbol_batch),
                    return_exceptions=True,
                )
            if self.on_order_book:
                await asyncio.gather(
                    *(self._fetch_order_book(symbol) for symbol in symbol_batch),
                    return_exceptions=True,
                )

    async def _fetch_candles(self, symbol: str) -> None:
        """
        Fetch candles for a symbol.

        Args:
            symbol: Trading symbol
        """
        try:
            formatted_symbol = self._format_symbol(symbol)
            endpoint = self._resolve_endpoint("candle", formatted_symbol)
            if not endpoint:
                self._record_polling_failure(
                    symbol,
                    "candle",
                    RuntimeError("missing REST candle endpoint"),
                    endpoint=None,
                    status="MISSING_CANDLE_TRUTH",
                )
                return
            if self._dns_backoff_active(endpoint):
                return

            params = self._build_candle_params(formatted_symbol)

            request_start_ns = now_ns()
            async with self._session.get(endpoint, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    response_received_ns = now_ns()
                    candles = self._parse_candles(data, symbol)
                    provider_batch_head_ts_ns = max(
                        (candle.exchange_ts_ns for candle in candles),
                        default=0,
                    )
                    latest_batch_ts_ns = self._latest_executable_batch_ts_ns(
                        candles,
                        response_received_ns=response_received_ns,
                    )
                    candle_policy_ms = self._candle_freshness_policy_ms()

                    for candle in candles:
                        if latest_batch_ts_ns <= 0:
                            continue
                        if candle.exchange_ts_ns != latest_batch_ts_ns:
                            continue
                        # Check for duplicate
                        last_ts_ns = self._last_candle_timestamps_ns.get(symbol)
                        if last_ts_ns and candle.exchange_ts_ns <= last_ts_ns:
                            continue

                        self._last_candle_timestamps_ns[symbol] = candle.exchange_ts_ns
                        candle = self._with_candle_runtime_metadata(
                            candle,
                            latest_batch_ts_ns=latest_batch_ts_ns,
                            provider_batch_head_ts_ns=provider_batch_head_ts_ns,
                            response_received_ns=response_received_ns,
                            candle_policy_ms=candle_policy_ms,
                        )

                        if self.on_candle:
                            await self._safe_callback(self.on_candle, candle)
                    self._record_polling_success(
                        symbol,
                        "candle",
                        endpoint,
                        request_start_ns=request_start_ns,
                        response_received_ns=response_received_ns,
                    )
                else:
                    self._record_polling_failure(
                        symbol,
                        "candle",
                        RuntimeError(f"HTTP {response.status}"),
                        endpoint=endpoint,
                        status="REST_POLLING_FAILED",
                    )

        except aiohttp.ClientError as e:
            self._record_polling_failure(symbol, "candle", e, endpoint=endpoint)
            logger.error(f"HTTP error fetching candles for {symbol}: {e}")
        except asyncio.TimeoutError as e:
            self._record_polling_failure(symbol, "candle", e, endpoint=endpoint, status="REST_POLLING_FAILED")
            logger.error(f"Timeout fetching candles for {symbol}: {e}")
        except Exception as e:
            self._record_polling_failure(symbol, "candle", e, endpoint=endpoint)
            logger.error(f"Error fetching candles for {symbol}: {e}")

    async def _fetch_order_book(self, symbol: str) -> None:
        """
        Fetch order book for a symbol.

        Args:
            symbol: Trading symbol
        """
        try:
            formatted_symbol = self._format_symbol(symbol)
            endpoint = self._resolve_endpoint("order_book", formatted_symbol)
            if not endpoint:
                self._record_polling_failure(
                    symbol,
                    "order_book",
                    RuntimeError("missing REST order book endpoint"),
                    endpoint=None,
                    status="MISSING_ORDER_BOOK_TRUTH",
                )
                return
            if self._dns_backoff_active(endpoint):
                return

            params = self._build_order_book_params(formatted_symbol)

            request_start_ns = now_ns()
            async with self._session.get(endpoint, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    response_received_ns = now_ns()
                    order_book = self._parse_order_book(
                        data,
                        symbol,
                        receive_ts_ns=response_received_ns,
                    )

                    if order_book and self.on_order_book:
                        await self._safe_callback(self.on_order_book, order_book)
                    if order_book:
                        self._record_polling_success(
                            symbol,
                            "order_book",
                            endpoint,
                            request_start_ns=request_start_ns,
                            response_received_ns=response_received_ns,
                        )
                    else:
                        self._record_polling_failure(
                            symbol,
                            "order_book",
                            RuntimeError("REST order book parse returned no snapshot"),
                            endpoint=endpoint,
                            status="MISSING_ORDER_BOOK_TRUTH",
                        )
                else:
                    self._record_polling_failure(
                        symbol,
                        "order_book",
                        RuntimeError(f"HTTP {response.status}"),
                        endpoint=endpoint,
                        status="REST_POLLING_FAILED",
                    )

        except aiohttp.ClientError as e:
            self._record_polling_failure(symbol, "order_book", e, endpoint=endpoint)
            logger.error(f"HTTP error fetching order book for {symbol}: {e}")
        except asyncio.TimeoutError as e:
            self._record_polling_failure(symbol, "order_book", e, endpoint=endpoint, status="REST_POLLING_FAILED")
            logger.error(f"Timeout fetching order book for {symbol}: {e}")
        except Exception as e:
            self._record_polling_failure(symbol, "order_book", e, endpoint=endpoint)
            logger.error(f"Error fetching order book for {symbol}: {e}")

    def _format_symbol(self, symbol: str) -> str:
        """
        Format a canonical slash-form symbol for the configured public REST API.

        Args:
            symbol: Trading symbol in canonical slash-form (e.g., "BTC/USD")

        Returns:
            Exchange REST pair identifier.
        """
        if self.exchange == "coinbase":
            return symbol.replace("/", "-")
        if "/" in symbol:
            base, quote = symbol.split("/", 1)
            base = _KRAKEN_BASE_MAP.get(base, base)
            return f"{base}{quote}"
        return symbol

    def _default_provider_id(self, exchange: str) -> str:
        if exchange == "coinbase":
            return "coinbase_public"
        if exchange == "kraken":
            return "kraken_public"
        return f"{exchange}_public"

    def _candle_freshness_policy_ms(self) -> Optional[float]:
        raw_seconds = self.freshness_policy.get("candle_stale_seconds")
        if raw_seconds is None:
            if self.exchange in {"coinbase", "kraken"}:
                raw_seconds = 60
        try:
            seconds = float(raw_seconds)
        except (TypeError, ValueError):
            return None
        if seconds <= 0:
            return None
        return seconds * 1000.0

    def _candle_timeframe_ns(self, candle: Candle) -> Optional[int]:
        timeframe = str(getattr(candle, "timeframe", "") or "").strip().lower()
        if not timeframe:
            return None
        units = {
            "s": 1_000_000_000,
            "m": 60_000_000_000,
            "h": 3_600_000_000_000,
            "d": 86_400_000_000_000,
        }
        suffix = timeframe[-1]
        if suffix not in units:
            return None
        try:
            count = int(timeframe[:-1] or "1")
        except ValueError:
            return None
        if count <= 0:
            return None
        return count * units[suffix]

    def _candle_close_ts_ns(self, candle: Candle) -> int:
        timeframe_ns = self._candle_timeframe_ns(candle)
        start_ns = int(candle.exchange_ts_ns or 0)
        return start_ns + timeframe_ns if start_ns > 0 and timeframe_ns else start_ns

    def _latest_executable_batch_ts_ns(
        self,
        candles: List[Candle],
        *,
        response_received_ns: int,
    ) -> int:
        closed = [
            int(candle.exchange_ts_ns)
            for candle in candles
            if self._candle_close_ts_ns(candle) <= int(response_received_ns)
        ]
        return max(closed, default=0)

    def _with_candle_runtime_metadata(
        self,
        candle: Candle,
        *,
        latest_batch_ts_ns: int,
        provider_batch_head_ts_ns: Optional[int] = None,
        response_received_ns: int,
        candle_policy_ms: Optional[float],
    ) -> Candle:
        provider_head_ts_ns = int(provider_batch_head_ts_ns or latest_batch_ts_ns or 0)
        candle_close_ts_ns = self._candle_close_ts_ns(candle)
        closed_at_receive = candle_close_ts_ns <= int(response_received_ns)
        latest_closed_batch_candle = (
            closed_at_receive
            and int(candle.exchange_ts_ns) == int(latest_batch_ts_ns or 0)
            and latest_batch_ts_ns > 0
        )
        return candle.model_copy(
            update={
                "data_source_type": "runtime",
                "provider_id": self.provider_id,
                "latest_batch_candle": latest_closed_batch_candle,
                "latest_provider_batch_candle": candle.exchange_ts_ns == provider_head_ts_ns,
                "latest_closed_batch_candle": latest_closed_batch_candle,
                "provider_batch_head_ts_ns": provider_head_ts_ns or None,
                "candle_close_ts_ns": candle_close_ts_ns,
                "candle_closed_at_receive": closed_at_receive,
                "candle_batch_received_ns": response_received_ns,
                "candle_freshness_policy_ms": candle_policy_ms,
            }
        )

    def _resolve_endpoint(self, feed_type: str, formatted_symbol: str) -> Optional[str]:
        endpoint = self._endpoints.get(self.exchange, {}).get(feed_type)
        if not endpoint:
            return None
        return endpoint.format(product_id=formatted_symbol)

    def _build_candle_params(self, formatted_symbol: str) -> Dict[str, Any]:
        if self.exchange == "coinbase":
            return {"granularity": 60}
        return {
            "pair": formatted_symbol,
            "interval": 1,
        }

    def _build_order_book_params(self, formatted_symbol: str) -> Dict[str, Any]:
        if self.exchange == "coinbase":
            return {"level": 2}
        return {
            "pair": formatted_symbol,
            "count": 50,
        }

    def _parse_iso8601_to_ns(self, value: Any) -> Optional[int]:
        if not value:
            return None
        try:
            text = str(value).strip()
            if text.endswith("Z"):
                text = f"{text[:-1]}+00:00"
            parsed = datetime.fromisoformat(text)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            parsed_utc = parsed.astimezone(timezone.utc)
            return calendar.timegm(parsed_utc.utctimetuple()) * 1_000_000_000 + parsed_utc.microsecond * 1_000
        except Exception as exc:
            logger.warning("Failed to parse %s timestamp %r: %s", self.exchange, value, exc)
            return None

    def _classify_polling_failure(self, exc: Exception, explicit_status: Optional[str] = None) -> str:
        if explicit_status:
            return explicit_status

        message = str(exc).lower()
        os_error = getattr(exc, "os_error", None)
        os_error_message = str(os_error).lower() if os_error is not None else ""
        is_connector_dns = isinstance(exc, aiohttp.ClientConnectorError) and any(
            token in f"{message} {os_error_message}"
            for token in ("dns", "name resolution", "resolve", "temporary failure", "could not contact dns")
        )
        if is_connector_dns:
            return "DNS_FAILURE_RECORDED"

        if isinstance(exc, (aiohttp.ClientConnectorError, asyncio.TimeoutError)):
            return "REST_POLLING_FAILED"

        return "FAILED_CLOSED"

    def _endpoint_domain(self, endpoint: Optional[str]) -> Optional[str]:
        if not endpoint:
            return None
        parsed = urlparse(endpoint)
        return parsed.hostname

    def _dns_backoff_active(self, endpoint: Optional[str], current_ns: Optional[int] = None) -> bool:
        domain = self._endpoint_domain(endpoint)
        if not domain:
            return False
        current_ns = int(current_ns or now_ns())
        until_ns = int(self._dns_backoff_until_ns_by_domain.get(domain, 0) or 0)
        if until_ns <= current_ns:
            self._dns_backoff_until_ns_by_domain.pop(domain, None)
            return False
        return True

    def _record_polling_failure(
        self,
        symbol: str,
        feed_type: str,
        exc: Exception,
        *,
        endpoint: Optional[str] = None,
        status: Optional[str] = None,
    ) -> None:
        reason = self._classify_polling_failure(exc, status)
        failure_status = {
            "status": reason,
            "symbol": symbol,
            "feed_type": feed_type,
            "exception_type": exc.__class__.__name__,
            "exchange": self.exchange,
            "endpoint_domain": self._endpoint_domain(endpoint),
            "rest_status": "REST_POLLING_DEGRADED",
            "market_truth": "MISSING_CANDLE_TRUTH" if feed_type == "candle" else "MISSING_ORDER_BOOK_TRUTH",
            "timestamp_ns": now_ns(),
        }
        if reason == "DNS_FAILURE_RECORDED" and failure_status["endpoint_domain"]:
            self._dns_backoff_until_ns_by_domain[failure_status["endpoint_domain"]] = (
                failure_status["timestamp_ns"] + int(self.dns_backoff_seconds * 1_000_000_000)
            )
        self._last_failure_status = failure_status
        self._failure_status_by_symbol_feed.setdefault(symbol, {})[feed_type] = failure_status
        self._failure_history.append(failure_status)
        if len(self._failure_history) > self.failure_history_size:
            self._failure_history = self._failure_history[-self.failure_history_size:]
        if self.on_feed_truth:
            self.on_feed_truth(dict(failure_status))

    def _latest_unresolved_failure_status(self) -> Dict[str, Any]:
        unresolved = [
            status
            for by_feed in self._failure_status_by_symbol_feed.values()
            for status in by_feed.values()
        ]
        if not unresolved:
            return {}
        return dict(max(unresolved, key=lambda status: int(status.get("timestamp_ns", 0) or 0)))

    def _record_polling_success(
        self,
        symbol: str,
        feed_type: str,
        endpoint: Optional[str],
        *,
        request_start_ns: Optional[int] = None,
        response_received_ns: Optional[int] = None,
    ) -> None:
        recovered_status = self._failure_status_by_symbol_feed.get(symbol, {}).pop(feed_type, None)
        if symbol in self._failure_status_by_symbol_feed and not self._failure_status_by_symbol_feed[symbol]:
            self._failure_status_by_symbol_feed.pop(symbol, None)

        timestamp_ns = now_ns()
        request_start_ns = int(request_start_ns or timestamp_ns)
        response_received_ns = int(response_received_ns or timestamp_ns)
        rest_latency_ms = max(0.0, (response_received_ns - request_start_ns) / 1_000_000.0)
        self._last_success_status = {
            "status": "REST_ACTIVE",
            "symbol": symbol,
            "feed_type": feed_type,
            "exchange": self.exchange,
            "endpoint_domain": self._endpoint_domain(endpoint),
            "timestamp_ns": timestamp_ns,
            "request_start_ns": request_start_ns,
            "response_received_ns": response_received_ns,
            "rest_latency_ms": rest_latency_ms,
        }
        self._last_rest_latency_status = {
            "status": "REST_LATENCY_OK",
            "symbol": symbol,
            "feed_type": feed_type,
            "exchange": self.exchange,
            "endpoint_domain": self._endpoint_domain(endpoint),
            "request_start_ns": request_start_ns,
            "response_received_ns": response_received_ns,
            "latency_ms": rest_latency_ms,
            "timestamp_ns": timestamp_ns,
            "source": "market_data.rest_polling_rtt",
        }
        if self.on_rest_latency:
            self.on_rest_latency(dict(self._last_rest_latency_status))
        if recovered_status:
            self._last_recovery_status = {
                "status": "REST_FAILURE_RECOVERED",
                "recovered_status": recovered_status.get("status"),
                "symbol": symbol,
                "feed_type": feed_type,
                "exchange": self.exchange,
                "endpoint_domain": self._endpoint_domain(endpoint),
                "timestamp_ns": timestamp_ns,
            }
        endpoint_domain = self._endpoint_domain(endpoint)
        if endpoint_domain:
            self._dns_backoff_until_ns_by_domain.pop(endpoint_domain, None)
        self._last_failure_status = self._latest_unresolved_failure_status()

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
            if self.exchange == "coinbase":
                for item in data if isinstance(data, list) else []:
                    if len(item) >= 6:
                        timestamp_sec = item[0]
                        candle = Candle(
                            symbol=symbol,
                            exchange_ts_ns=int(timestamp_sec) * 1_000_000_000,
                            open=float(item[3]),
                            high=float(item[2]),
                            low=float(item[1]),
                            close=float(item[4]),
                            volume=float(item[5]),
                            timeframe="1m",
                        )
                        candles.append(candle)
                return sorted(candles, key=lambda candle: candle.exchange_ts_ns)

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

    def _parse_order_book(
        self,
        data: Dict,
        symbol: str,
        *,
        receive_ts_ns: Optional[int] = None,
    ) -> Optional[OrderBookSnapshot]:
        """
        Parse order book from exchange response.

        Kraken Depth response format:
        {
            "result": {
                "XBTUSD": {
                    "bids": [["price", "size", "timestamp"], ...],
                    "asks": [["price", "size", "timestamp"], ...]
                }
            }
        }

        Some entries may have 2 fields (price, size) or 3+ fields (price, size, timestamp, ...).
        This parser safely extracts the first 2 fields (price, size) and ignores extras.

        Args:
            data: Raw API response
            symbol: Trading symbol

        Returns:
            OrderBookSnapshot or None
        """
        try:
            if self.exchange == "coinbase":
                bids = self._parse_price_size_levels(data.get("bids", []), symbol, "bid")
                asks = self._parse_price_size_levels(data.get("asks", []), symbol, "ask")
                exchange_ts_ns = self._parse_iso8601_to_ns(data.get("time"))
                if exchange_ts_ns is None:
                    logger.warning("Coinbase order book missing authoritative time for %s", symbol)
                    return None
                return OrderBookSnapshot(
                    symbol=symbol,
                    exchange_ts_ns=exchange_ts_ns,
                    bids=bids[:50],
                    asks=asks[:50],
                    receive_ts_ns=receive_ts_ns,
                )

            result = data.get("result", {})
            for key, book_data in result.items():
                if isinstance(book_data, dict):
                    bids_raw = book_data.get("bids", [])
                    asks_raw = book_data.get("asks", [])

                    source_level_ts_ns: list[int] = []
                    bids = []
                    for entry in bids_raw:
                        try:
                            # Safely extract first two fields regardless of entry length
                            if isinstance(entry, (list, tuple)) and len(entry) >= 2:
                                price = float(entry[0])
                                size = float(entry[1])
                                bids.append((price, size))
                                if len(entry) >= 3:
                                    source_level_ts_ns.append(
                                        int(Decimal(str(entry[2])) * Decimal(1_000_000_000))
                                    )
                            else:
                                logger.warning(f"Malformed bid entry in order book for {symbol}: {entry}")
                        except (ValueError, TypeError) as e:
                            logger.warning(f"Failed to convert bid entry for {symbol}: {entry} - {e}")

                    asks = []
                    for entry in asks_raw:
                        try:
                            if isinstance(entry, (list, tuple)) and len(entry) >= 2:
                                price = float(entry[0])
                                size = float(entry[1])
                                asks.append((price, size))
                                if len(entry) >= 3:
                                    source_level_ts_ns.append(
                                        int(Decimal(str(entry[2])) * Decimal(1_000_000_000))
                                    )
                            else:
                                logger.warning(f"Malformed ask entry in order book for {symbol}: {entry}")
                        except (ValueError, TypeError) as e:
                            logger.warning(f"Failed to convert ask entry for {symbol}: {entry} - {e}")

                    if not source_level_ts_ns:
                        logger.warning(
                            "Kraken order book missing source-level timestamp for %s; rejecting",
                            symbol,
                        )
                        return None
                    exchange_ts_ns = max(source_level_ts_ns)

                    return OrderBookSnapshot(
                        symbol=symbol,
                        exchange_ts_ns=exchange_ts_ns,
                        bids=bids[:50],
                        asks=asks[:50],
                        receive_ts_ns=receive_ts_ns,
                    )

        except (InvalidOperation, ValueError, TypeError) as e:
            logger.error(f"Failed to parse order book timestamps for {symbol}: {e}")
        except Exception as e:
            logger.error(f"Failed to parse order book for {symbol}: {e}")

        return None

    def _parse_price_size_levels(
        self,
        raw_levels: Any,
        symbol: str,
        side: str,
    ) -> List[tuple[float, float]]:
        levels: List[tuple[float, float]] = []
        if not isinstance(raw_levels, list):
            logger.warning("Malformed %s levels in order book for %s: %r", side, symbol, raw_levels)
            return levels

        for entry in raw_levels:
            try:
                if isinstance(entry, dict):
                    price = float(entry["price"])
                    size = float(entry["size"])
                elif isinstance(entry, (list, tuple)) and len(entry) >= 2:
                    price = float(entry[0])
                    size = float(entry[1])
                else:
                    logger.warning("Malformed %s entry in order book for %s: %r", side, symbol, entry)
                    continue
                if price <= 0 or size <= 0:
                    logger.warning("Non-positive %s entry in order book for %s: %r", side, symbol, entry)
                    continue
                levels.append((price, size))
            except (KeyError, ValueError, TypeError) as exc:
                logger.warning("Failed to convert %s entry for %s: %r - %s", side, symbol, entry, exc)

        reverse = side == "bid"
        return sorted(levels, key=lambda level: level[0], reverse=reverse)

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
            "last_candle_timestamps_ns": self._last_candle_timestamps_ns.copy(),
            "last_failure_status": dict(self._last_failure_status),
            "last_success_status": dict(self._last_success_status),
            "last_rest_latency_status": dict(self._last_rest_latency_status),
            "last_recovery_status": dict(self._last_recovery_status),
            "dns_backoff_seconds": self.dns_backoff_seconds,
            "max_concurrency": self.max_concurrency,
            "failure_history_size": self.failure_history_size,
            "dns_backoff_until_ns_by_domain": dict(self._dns_backoff_until_ns_by_domain),
            "failure_status_by_symbol_feed": {
                symbol: {feed_type: dict(status) for feed_type, status in feeds.items()}
                for symbol, feeds in self._failure_status_by_symbol_feed.items()
            },
            "failure_history": [dict(item) for item in self._failure_history[-20:]],
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


@dataclass(frozen=True)
class MarketDataTransportPolicy:
    batch_size: int = 50
    max_concurrency: int = 4
    global_requests_per_minute: int = 180
    provider_requests_per_minute: int = 180
    request_timeout_seconds: float = 10.0
    max_retries: int = 3
    backoff_base_seconds: float = 0.5
    backoff_max_seconds: float = 30.0
    circuit_failure_threshold: int = 5
    circuit_cooldown_seconds: float = 30.0
    job_queue_size: int = 128
    failure_history_size: int = 100
    callback_timeout_seconds: float = 5.0

    def __post_init__(self) -> None:
        integer_positive = (
            self.batch_size,
            self.max_concurrency,
            self.global_requests_per_minute,
            self.provider_requests_per_minute,
            self.circuit_failure_threshold,
            self.job_queue_size,
            self.failure_history_size,
        )
        if any(isinstance(value, bool) or not isinstance(value, int) or value <= 0 for value in integer_positive):
            raise ValueError("market_data_transport_positive_limits_required")
        if self.provider_requests_per_minute > self.global_requests_per_minute:
            raise ValueError("market_data_provider_budget_exceeds_global")
        if isinstance(self.max_retries, bool) or not isinstance(self.max_retries, int) or self.max_retries < 0:
            raise ValueError("market_data_max_retries_invalid")
        numeric_positive = (
            self.request_timeout_seconds,
            self.backoff_base_seconds,
            self.backoff_max_seconds,
            self.circuit_cooldown_seconds,
            self.callback_timeout_seconds,
        )
        if any(isinstance(value, bool) or not math.isfinite(float(value)) or float(value) <= 0 for value in numeric_positive):
            raise ValueError("market_data_timeout_invalid")
        if not self.backoff_base_seconds <= self.backoff_max_seconds:
            raise ValueError("market_data_backoff_invalid")


class MarketDataRequestBudget:
    """Bounded market-data rate/concurrency controller; never order authority."""

    def __init__(self, policy: MarketDataTransportPolicy, *, monotonic: Callable[[], float], sleep: Callable[[float], Any]):
        self.policy = policy
        self._monotonic = monotonic
        self._sleep = sleep
        self._semaphore = asyncio.Semaphore(policy.max_concurrency)
        self._lock = asyncio.Lock()
        self._global_starts: deque[float] = deque()
        self._provider_starts: Dict[str, deque[float]] = {}
        self.inflight = 0
        self.max_inflight = 0
        self.wait_count = 0

    @asynccontextmanager
    async def slot(self, provider_id: str):
        await self._semaphore.acquire()
        counted_inflight = False
        try:
            while True:
                async with self._lock:
                    current = self._monotonic()
                    cutoff = current - 60.0
                    while self._global_starts and self._global_starts[0] <= cutoff:
                        self._global_starts.popleft()
                    provider_starts = self._provider_starts.setdefault(provider_id, deque())
                    while provider_starts and provider_starts[0] <= cutoff:
                        provider_starts.popleft()
                    global_full = len(self._global_starts) >= self.policy.global_requests_per_minute
                    provider_full = len(provider_starts) >= self.policy.provider_requests_per_minute
                    if not global_full and not provider_full:
                        self._global_starts.append(current)
                        provider_starts.append(current)
                        self.inflight += 1
                        counted_inflight = True
                        self.max_inflight = max(self.max_inflight, self.inflight)
                        break
                    release_times: list[float] = []
                    if global_full:
                        release_times.append(self._global_starts[0] + 60.0)
                    if provider_full:
                        release_times.append(provider_starts[0] + 60.0)
                    delay = max(0.001, max(release_times) - current)
                    self.wait_count += 1
                await self._sleep(delay)
            yield
        finally:
            if counted_inflight:
                self.inflight -= 1
            self._semaphore.release()


# Compatibility alias for existing focused tests and internal imports.
_RequestBudget = MarketDataRequestBudget


class BatchedAlpacaPollingClient:
    """Alpaca execution-location REST breadth/deep transport with hard bounds."""

    SNAPSHOTS_ENDPOINT = "https://data.alpaca.markets/v1beta3/crypto/us/snapshots"
    ORDERBOOKS_ENDPOINT = "https://data.alpaca.markets/v1beta3/crypto/us/latest/orderbooks"

    def __init__(
        self,
        *,
        breadth_symbols: List[str],
        deep_symbols: Optional[List[str]] = None,
        protected_symbols: Optional[List[str]] = None,
        breadth_interval_seconds: float = 15.0,
        deep_interval_seconds: float = 1.0,
        deep_poll_enabled: bool = False,
        quote_freshness_policy_ms: float = 10_000.0,
        order_book_freshness_policy_ms: float = 10_000.0,
        candle_freshness_policy_ms: float = 60_000.0,
        order_book_level_limit: int = 1000,
        request_headers: Optional[Mapping[str, str]] = None,
        policy: Optional[MarketDataTransportPolicy] = None,
        on_breadth_snapshot: Optional[Callable[[Dict[str, Any]], Any]] = None,
        on_candle: Optional[Callable[[Candle], Any]] = None,
        on_order_book: Optional[Callable[[OrderBookSnapshot], Any]] = None,
        on_feed_truth: Optional[Callable[[Dict[str, Any]], Any]] = None,
        on_rest_latency: Optional[Callable[[Dict[str, Any]], Any]] = None,
        request_json: Optional[Callable[..., Any]] = None,
        request_budget: Optional[MarketDataRequestBudget] = None,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Any] = asyncio.sleep,
        random_seed: int = 0,
    ) -> None:
        self.provider_id = "alpaca_crypto_rest"
        self.execution_location = "alpaca"
        self.breadth_symbols = tuple(dict.fromkeys(str(item).strip().upper() for item in breadth_symbols if str(item).strip()))
        if not self.breadth_symbols:
            raise ValueError("alpaca_breadth_symbols_required")
        self.protected_symbols = frozenset(str(item).strip().upper() for item in (protected_symbols or ()) if str(item).strip())
        self.deep_symbols = tuple(dict.fromkeys(str(item).strip().upper() for item in (deep_symbols or ()) if str(item).strip()))
        if not self.protected_symbols.issubset(self.deep_symbols):
            raise ValueError("protected_symbols_must_be_deep")
        if not set(self.deep_symbols).issubset(self.breadth_symbols):
            raise ValueError("deep_symbols_must_be_in_breadth")
        self.breadth_interval_seconds = max(1.0, float(breadth_interval_seconds))
        self.deep_interval_seconds = max(0.1, float(deep_interval_seconds))
        self.deep_poll_enabled = bool(deep_poll_enabled)
        self.quote_freshness_policy_ms = float(quote_freshness_policy_ms)
        self.order_book_freshness_policy_ms = float(order_book_freshness_policy_ms)
        self.candle_freshness_policy_ms = float(candle_freshness_policy_ms)
        if isinstance(order_book_level_limit, bool) or not isinstance(order_book_level_limit, int) or order_book_level_limit <= 0:
            raise ValueError("alpaca_order_book_level_limit_invalid")
        self.order_book_level_limit = order_book_level_limit
        for field_name, value in (
            ("quote", self.quote_freshness_policy_ms),
            ("order_book", self.order_book_freshness_policy_ms),
            ("candle", self.candle_freshness_policy_ms),
        ):
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"alpaca_{field_name}_freshness_policy_invalid")
        self.request_headers = {str(key): str(value) for key, value in (request_headers or {}).items() if str(value)}
        self.policy = policy or MarketDataTransportPolicy()
        if request_budget is not None and request_budget.policy != self.policy:
            raise ValueError("market_data_request_budget_policy_mismatch")
        self.on_breadth_snapshot = on_breadth_snapshot
        self.on_candle = on_candle
        self.on_order_book = on_order_book
        self.on_feed_truth = on_feed_truth
        self.on_rest_latency = on_rest_latency
        self._request_json_override = request_json
        self._monotonic = monotonic
        self._sleep = sleep
        self._random = random.Random(random_seed)
        self._budget = request_budget
        self._session: Optional[aiohttp.ClientSession] = None
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._last_breadth_poll = float("-inf")
        self._last_snapshot_source_ns: Dict[tuple[str, str], int] = {}
        self._last_order_book_source_ns: Dict[str, int] = {}
        self._consecutive_failures = 0
        self._circuit_open_until = 0.0
        self._circuit_state = "CLOSED"
        self._failure_history: deque[Dict[str, Any]] = deque(maxlen=self.policy.failure_history_size)
        self._events: deque[Dict[str, Any]] = deque(maxlen=self.policy.failure_history_size)
        self._metrics: Dict[str, int] = {
            "requests_started": 0,
            "requests_completed": 0,
            "requests_failed": 0,
            "rate_limited": 0,
            "retries": 0,
            "batches_submitted": 0,
            "malformed_payloads": 0,
            "callback_timeouts": 0,
            "truth_callback_failures": 0,
            "duplicate_snapshots_suppressed": 0,
            "duplicate_candles_suppressed": 0,
            "duplicate_order_books_suppressed": 0,
            "out_of_order_events_rejected": 0,
            "queue_high_water": 0,
        }

    @property
    def is_running(self) -> bool:
        return self._running

    async def start(self, *, require_initial_success: bool = False) -> None:
        if self._running:
            return
        self._running = True
        if self._budget is None:
            self._budget = MarketDataRequestBudget(self.policy, monotonic=self._monotonic, sleep=self._sleep)
        if self._request_json_override is None:
            connector = aiohttp.TCPConnector(resolver=aiohttp.ThreadedResolver(), ttl_dns_cache=30, use_dns_cache=True)
            self._session = aiohttp.ClientSession(
                connector=connector,
                timeout=aiohttp.ClientTimeout(total=self.policy.request_timeout_seconds),
            )
        if require_initial_success and not await self.probe_protected_once():
            self._running = False
            if self._session is not None:
                await self._session.close()
                self._session = None
            raise RuntimeError("alpaca_rest_initial_probe_failed")
        self._task = asyncio.create_task(self._poll_loop())

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        if self._session is not None:
            await self._session.close()
            self._session = None

    def update_deep_symbols(self, candidates: List[str], *, protected_symbols: List[str], limit: int) -> tuple[str, ...]:
        protected = tuple(dict.fromkeys(str(item).strip().upper() for item in protected_symbols if str(item).strip()))
        if len(protected) > int(limit):
            raise ValueError("protected_deep_capacity_exceeded")
        ordered = list(protected)
        for symbol in candidates:
            normalized = str(symbol).strip().upper()
            if normalized and normalized not in ordered and len(ordered) < int(limit):
                ordered.append(normalized)
        if not set(ordered).issubset(self.breadth_symbols):
            raise ValueError("deep_symbols_must_be_in_breadth")
        self.protected_symbols = frozenset(protected)
        self.deep_symbols = tuple(ordered)
        return self.deep_symbols

    async def _poll_loop(self) -> None:
        while self._running:
            started = self._monotonic()
            try:
                include_breadth = started - self._last_breadth_poll >= self.breadth_interval_seconds
                await self.poll_once(include_breadth=include_breadth)
                if include_breadth:
                    self._last_breadth_poll = started
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                await self._emit_failure("POLL_LOOP_FAILED", exc)
            elapsed = self._monotonic() - started
            await self._sleep(max(0.0, self.deep_interval_seconds - elapsed))

    def _batches(self, symbols: tuple[str, ...]) -> tuple[tuple[str, ...], ...]:
        return tuple(
            tuple(symbols[index : index + self.policy.batch_size])
            for index in range(0, len(symbols), self.policy.batch_size)
        )

    async def poll_once(self, *, include_breadth: bool = True) -> bool:
        snapshot_symbols = self._ordered_snapshot_symbols(include_breadth=include_breadth)
        # Deep books and the deep-containing snapshot batch enter the worker
        # queue first, so catalogue breadth cannot starve lifecycle truth.
        jobs: list[tuple[str, tuple[str, ...]]] = []
        if self.deep_poll_enabled:
            jobs.extend(("order_book", batch) for batch in self._batches(self.deep_symbols))
        jobs.extend(("snapshot", batch) for batch in self._batches(snapshot_symbols))
        self._metrics["batches_submitted"] += len(jobs)
        return await self._run_jobs(jobs)

    def _ordered_snapshot_symbols(self, *, include_breadth: bool) -> tuple[str, ...]:
        if not include_breadth:
            return self.deep_symbols if self.deep_poll_enabled else ()
        ordered = list(self.deep_symbols)
        ordered.extend(symbol for symbol in self.breadth_symbols if symbol not in self.deep_symbols)
        return tuple(ordered)

    async def probe_protected_once(self) -> bool:
        """Confirm protected/deep REST truth before declaring fallback active."""
        symbols = tuple(sorted(self.protected_symbols)) or self.deep_symbols
        if not symbols:
            return False
        jobs = [("snapshot", batch) for batch in self._batches(symbols)]
        jobs.extend(("order_book", batch) for batch in self._batches(symbols))
        self._metrics["batches_submitted"] += len(jobs)
        return await self._run_jobs(jobs)

    async def _run_jobs(self, jobs: List[tuple[str, tuple[str, ...]]]) -> bool:
        queue: asyncio.Queue[Optional[tuple[str, tuple[str, ...]]]] = asyncio.Queue(maxsize=self.policy.job_queue_size)
        results: list[bool] = []

        async def worker() -> None:
            while True:
                job = await queue.get()
                try:
                    if job is None:
                        return
                    feed_type, symbols = job
                    if feed_type == "snapshot":
                        results.append(await self._fetch_snapshot_batch(symbols))
                    else:
                        results.append(await self._fetch_order_book_batch(symbols))
                finally:
                    queue.task_done()

        workers = [asyncio.create_task(worker()) for _ in range(min(self.policy.max_concurrency, max(1, len(jobs))))]
        try:
            for job in jobs:
                await queue.put(job)
                self._metrics["queue_high_water"] = max(self._metrics["queue_high_water"], queue.qsize())
            for _ in workers:
                await queue.put(None)
            await queue.join()
            await asyncio.gather(*workers)
            return len(results) == len(jobs) and all(results)
        finally:
            for task in workers:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*workers, return_exceptions=True)

    async def _default_request_json(self, endpoint: str, params: Mapping[str, Any]) -> tuple[int, Mapping[str, str], Any]:
        if self._session is None:
            raise RuntimeError("alpaca_market_data_session_not_started")
        async with self._session.get(endpoint, params=params, headers=self.request_headers) as response:
            try:
                payload = await response.json(content_type=None)
            except ValueError as exc:
                if int(response.status) == 200:
                    raise ValueError("alpaca_market_data_json_invalid") from exc
                # Error status and headers remain authoritative even when an
                # intermediary/provider returns a non-JSON error body.
                payload = {}
            return response.status, dict(response.headers), payload

    async def _request(self, endpoint: str, params: Mapping[str, Any]) -> Any:
        if self._budget is None:
            self._budget = MarketDataRequestBudget(self.policy, monotonic=self._monotonic, sleep=self._sleep)
        half_open_probe = False
        if self._circuit_state == "OPEN":
            if self._monotonic() < self._circuit_open_until:
                raise RuntimeError("market_data_circuit_open")
            self._circuit_state = "HALF_OPEN"
            half_open_probe = True
        elif self._circuit_state == "HALF_OPEN":
            # State transitions before the first await are atomic within this
            # client's event loop. Only the request that opened HALF_OPEN may
            # probe; concurrent batches remain refused until it resolves.
            raise RuntimeError("market_data_circuit_half_open_probe_inflight")
        request_json = self._request_json_override or self._default_request_json
        last_error: Optional[Exception] = None
        try:
            for attempt in range(self.policy.max_retries + 1):
                request_started_ns = now_ns()
                retry_delay_override: Optional[float] = None
                try:
                    async with self._budget.slot(self.provider_id):
                        self._metrics["requests_started"] += 1
                        status, headers, payload = await asyncio.wait_for(
                            request_json(endpoint, dict(params)),
                            timeout=self.policy.request_timeout_seconds,
                        )
                    response_received_ns = now_ns()
                    if self.on_rest_latency:
                        await self._safe_callback(
                            self.on_rest_latency,
                            {
                                "status": "REST_LATENCY_OBSERVED",
                                "provider_id": self.provider_id,
                                "exchange": self.execution_location,
                                "feed_type": "batch",
                                "symbol": ",".join(str(params.get("symbols") or "").split(",")[:3]),
                                "request_start_ns": request_started_ns,
                                "response_received_ns": response_received_ns,
                                "latency_ms": max(0.0, (response_received_ns - request_started_ns) / 1_000_000.0),
                                "http_status": int(status),
                                "request_succeeded": int(status) == 200,
                                "source": "market_data.rest_polling_rtt",
                            },
                        )
                    if int(status) == 200:
                        self._consecutive_failures = 0
                        if (
                            half_open_probe
                            and self._circuit_state == "HALF_OPEN"
                        ) or (
                            not half_open_probe
                            and self._circuit_state == "CLOSED"
                        ):
                            self._circuit_state = "CLOSED"
                            self._circuit_open_until = 0.0
                        self._metrics["requests_completed"] += 1
                        return payload
                    if int(status) == 429:
                        self._metrics["rate_limited"] += 1
                        last_error = RuntimeError("HTTP_429_RATE_LIMITED")
                        retry_after = self._retry_after_seconds(headers)
                        self._open_circuit("RATE_LIMITED", retry_after)
                        retry_delay_override = retry_after
                    else:
                        last_error = RuntimeError(f"HTTP_{int(status)}")
                        self._record_transport_failure()
                        if int(status) < 500:
                            break
                except (asyncio.TimeoutError, aiohttp.ClientError, OSError, RuntimeError) as exc:
                    last_error = exc
                    self._record_transport_failure()
                if self._circuit_state == "OPEN":
                    break
                if attempt < self.policy.max_retries:
                    self._metrics["retries"] += 1
                    exponential = min(self.policy.backoff_max_seconds, self.policy.backoff_base_seconds * (2 ** attempt))
                    delay = max(exponential, retry_delay_override or 0.0)
                    await self._sleep(delay + self._random.uniform(0.0, exponential * 0.25))
            self._metrics["requests_failed"] += 1
            raise last_error or RuntimeError("market_data_request_failed")
        finally:
            if half_open_probe and self._circuit_state == "HALF_OPEN":
                self._open_circuit("HALF_OPEN_PROBE_FAILED", self.policy.circuit_cooldown_seconds)

    def _retry_after_seconds(self, headers: Mapping[str, str]) -> float:
        try:
            value = float(headers.get("Retry-After", self.policy.circuit_cooldown_seconds))
        except (TypeError, ValueError):
            value = self.policy.circuit_cooldown_seconds
        if not math.isfinite(value) or value <= 0:
            value = self.policy.circuit_cooldown_seconds
        # Retry-After is provider authority. Exponential-backoff bounds do not
        # permit an earlier request than the provider explicitly allowed.
        return max(1.0, value)

    def _record_transport_failure(self) -> None:
        self._consecutive_failures += 1
        if self._consecutive_failures >= self.policy.circuit_failure_threshold:
            self._open_circuit("FAILURE_THRESHOLD", self.policy.circuit_cooldown_seconds)

    def _open_circuit(self, reason: str, seconds: float) -> None:
        proposed_open_until = self._monotonic() + max(1.0, float(seconds))
        self._circuit_state = "OPEN"
        self._circuit_open_until = max(self._circuit_open_until, proposed_open_until)
        self._events.append({"event": "CIRCUIT_OPEN", "reason": reason, "timestamp_ns": now_ns()})

    async def _fetch_snapshot_batch(self, symbols: tuple[str, ...]) -> bool:
        try:
            payload = await self._request(self.SNAPSHOTS_ENDPOINT, {"symbols": ",".join(symbols)})
            snapshots = payload.get("snapshots") if isinstance(payload, Mapping) else None
            if not isinstance(snapshots, Mapping):
                raise ValueError("alpaca_snapshots_mapping_required")
            valid = True
            for symbol in symbols:
                try:
                    raw = snapshots.get(symbol)
                    if not isinstance(raw, Mapping):
                        raise ValueError("symbol_snapshot_missing")
                    normalized = self._normalize_snapshot(symbol, raw)
                    source_times = {
                        "quote": int(normalized["quote_exchange_ts_ns"]),
                        "trade": int(normalized["trade_exchange_ts_ns"]),
                        "bar": int(normalized["bar_exchange_ts_ns"]),
                    }
                    previous_times = {
                        channel: self._last_snapshot_source_ns.get((channel, symbol), 0)
                        for channel in source_times
                    }
                    if any(source_times[channel] < previous_times[channel] for channel in source_times):
                        self._metrics["out_of_order_events_rejected"] += 1
                        await self._emit_failure(
                            "OUT_OF_ORDER_SNAPSHOT",
                            ValueError("alpaca_snapshot_source_time_regression"),
                            symbol=symbol,
                        )
                        valid = False
                        continue
                    if all(source_times[channel] == previous_times[channel] for channel in source_times):
                        self._metrics["duplicate_snapshots_suppressed"] += 1
                        continue
                    candle = normalized.get("candle")
                    callback_valid = True
                    candle_callback_accepted = False
                    if self.deep_poll_enabled and symbol in self.deep_symbols and isinstance(candle, Candle) and self.on_candle:
                        if source_times["bar"] == previous_times["bar"]:
                            self._metrics["duplicate_candles_suppressed"] += 1
                        else:
                            callback_valid = await self._safe_callback(self.on_candle, candle)
                            candle_callback_accepted = callback_valid
                    if candle_callback_accepted:
                        self._last_snapshot_source_ns[("bar", symbol)] = source_times["bar"]
                    if callback_valid and self.on_breadth_snapshot:
                        callback_valid = await self._safe_callback(self.on_breadth_snapshot, normalized)
                    if not callback_valid:
                        valid = False
                        continue
                    for channel, timestamp_ns in source_times.items():
                        self._last_snapshot_source_ns[(channel, symbol)] = timestamp_ns
                except Exception as exc:
                    await self._emit_failure("MALFORMED_SNAPSHOT", exc, symbol=symbol)
                    valid = False
            return valid
        except Exception as exc:
            await self._emit_failure("SNAPSHOT_BATCH_FAILED", exc, symbols=symbols)
            return False

    async def _fetch_order_book_batch(self, symbols: tuple[str, ...]) -> bool:
        try:
            payload = await self._request(self.ORDERBOOKS_ENDPOINT, {"symbols": ",".join(symbols)})
            books = payload.get("orderbooks") if isinstance(payload, Mapping) else None
            if not isinstance(books, Mapping):
                raise ValueError("alpaca_orderbooks_mapping_required")
            receive_ts_ns = now_ns()
            valid = True
            for symbol in symbols:
                try:
                    raw = books.get(symbol)
                    book = self._normalize_order_book(symbol, raw, receive_ts_ns=receive_ts_ns)
                    if book is None:
                        raise ValueError("order_book_invalid")
                    previous_ns = self._last_order_book_source_ns.get(symbol, 0)
                    if book.exchange_ts_ns < previous_ns:
                        self._metrics["out_of_order_events_rejected"] += 1
                        await self._emit_failure(
                            "OUT_OF_ORDER_ORDER_BOOK",
                            ValueError("alpaca_order_book_source_time_regression"),
                            symbol=symbol,
                        )
                        valid = False
                        continue
                    if book.exchange_ts_ns == previous_ns:
                        self._metrics["duplicate_order_books_suppressed"] += 1
                        continue
                    if self.on_order_book and not await self._safe_callback(self.on_order_book, book):
                        valid = False
                        continue
                    self._last_order_book_source_ns[symbol] = book.exchange_ts_ns
                except Exception as exc:
                    await self._emit_failure("MALFORMED_ORDER_BOOK", exc, symbol=symbol)
                    valid = False
            return valid
        except Exception as exc:
            await self._emit_failure("ORDER_BOOK_BATCH_FAILED", exc, symbols=symbols)
            return False

    def _normalize_snapshot(self, symbol: str, raw: Mapping[str, Any]) -> Dict[str, Any]:
        received_at_ns = now_ns()
        quote = raw.get("latestQuote") or raw.get("latest_quote")
        trade = raw.get("latestTrade") or raw.get("latest_trade")
        bar = raw.get("minuteBar") or raw.get("minute_bar")
        if not isinstance(quote, Mapping) or not isinstance(trade, Mapping) or not isinstance(bar, Mapping):
            self._metrics["malformed_payloads"] += 1
            raise ValueError("alpaca_snapshot_components_required")
        quote_ts_ns = self._parse_iso8601_ns(quote.get("t") or quote.get("timestamp"))
        trade_ts_ns = self._parse_iso8601_ns(trade.get("t") or trade.get("timestamp"))
        bar_ts_ns = self._parse_iso8601_ns(bar.get("t") or bar.get("timestamp"))
        if max(quote_ts_ns, trade_ts_ns, bar_ts_ns) > received_at_ns:
            raise ValueError("alpaca_future_snapshot_event_refused")
        quote_limit_ns = int(self.quote_freshness_policy_ms * 1_000_000.0)
        if received_at_ns - quote_ts_ns > quote_limit_ns:
            raise ValueError("alpaca_stale_quote_refused")
        bid = self._positive_finite(quote.get("bp") or quote.get("bid_price"), "bid_price")
        ask = self._positive_finite(quote.get("ap") or quote.get("ask_price"), "ask_price")
        if bid >= ask:
            raise ValueError("alpaca_crossed_or_locked_quote_refused")
        price = self._positive_finite(trade.get("p") or trade.get("price"), "trade_price")
        size = self._positive_finite(trade.get("s") or trade.get("size"), "trade_size")
        candle_close_ts_ns = bar_ts_ns + 60_000_000_000
        if candle_close_ts_ns > received_at_ns:
            raise ValueError("alpaca_in_progress_minute_bar_refused")
        if received_at_ns - candle_close_ts_ns > int(self.candle_freshness_policy_ms * 1_000_000.0):
            raise ValueError("alpaca_stale_closed_minute_bar_refused")
        candle = Candle(
            symbol=symbol,
            exchange_ts_ns=bar_ts_ns,
            open=self._positive_finite(bar.get("o") or bar.get("open"), "bar_open"),
            high=self._positive_finite(bar.get("h") or bar.get("high"), "bar_high"),
            low=self._positive_finite(bar.get("l") or bar.get("low"), "bar_low"),
            close=self._positive_finite(bar.get("c") or bar.get("close"), "bar_close"),
            volume=self._nonnegative_finite(bar.get("v") if bar.get("v") is not None else bar.get("volume"), "bar_volume"),
            timeframe="1m",
            data_source_type="runtime",
            provider_id=self.provider_id,
            latest_batch_candle=True,
            latest_provider_batch_candle=True,
            latest_closed_batch_candle=True,
            provider_batch_head_ts_ns=bar_ts_ns,
            candle_close_ts_ns=candle_close_ts_ns,
            candle_closed_at_receive=True,
            candle_batch_received_ns=received_at_ns,
            candle_freshness_policy_ms=self.candle_freshness_policy_ms,
        )
        return {
            "symbol": symbol,
            "provider_id": self.provider_id,
            "execution_location": self.execution_location,
            "executable_source": True,
            "quote_exchange_ts_ns": quote_ts_ns,
            "trade_exchange_ts_ns": trade_ts_ns,
            "trade_age_ms": (received_at_ns - trade_ts_ns) / 1_000_000.0,
            "bar_exchange_ts_ns": bar_ts_ns,
            "bar_close_ts_ns": candle_close_ts_ns,
            "quote_age_ms": (received_at_ns - quote_ts_ns) / 1_000_000.0,
            "bar_close_age_ms": (received_at_ns - candle_close_ts_ns) / 1_000_000.0,
            "component_max_age_ms": max(
                received_at_ns - quote_ts_ns,
                received_at_ns - trade_ts_ns,
                received_at_ns - candle_close_ts_ns,
            ) / 1_000_000.0,
            "bid": bid,
            "ask": ask,
            "bid_size": self._nonnegative_finite(quote.get("bs") if quote.get("bs") is not None else quote.get("bid_size"), "bid_size"),
            "ask_size": self._nonnegative_finite(quote.get("as") if quote.get("as") is not None else quote.get("ask_size"), "ask_size"),
            "trade_price": price,
            "trade_size": size,
            "trade_count": self._nonnegative_integer(
                bar.get("n") if bar.get("n") is not None else bar.get("trade_count", 0),
                "trade_count",
            ),
            "candle": candle,
            "received_at_ns": received_at_ns,
        }

    def _normalize_order_book(self, symbol: str, raw: Any, *, receive_ts_ns: int) -> Optional[OrderBookSnapshot]:
        if not isinstance(raw, Mapping):
            return None
        timestamp_ns = self._parse_iso8601_ns(raw.get("t") or raw.get("timestamp"))
        if timestamp_ns > receive_ts_ns:
            raise ValueError("alpaca_future_order_book_refused")
        if receive_ts_ns - timestamp_ns > int(self.order_book_freshness_policy_ms * 1_000_000.0):
            raise ValueError("alpaca_stale_order_book_refused")
        bids = self._levels(raw.get("b") or raw.get("bids"), reverse=True)
        asks = self._levels(raw.get("a") or raw.get("asks"), reverse=False)
        if not bids or not asks or bids[0][0] >= asks[0][0]:
            return None
        return OrderBookSnapshot(
            symbol=symbol,
            exchange_ts_ns=timestamp_ns,
            receive_ts_ns=receive_ts_ns,
            bids=bids,
            asks=asks,
        )

    def _levels(self, raw: Any, *, reverse: bool) -> List[tuple[float, float]]:
        if not isinstance(raw, list):
            return []
        levels: list[tuple[float, float]] = []
        for item in raw:
            if not isinstance(item, Mapping):
                return []
            price = self._positive_finite(item.get("p") or item.get("price"), "level_price")
            size = self._positive_finite(item.get("s") or item.get("size"), "level_size")
            levels.append((price, size))
        return sorted(levels, key=lambda item: item[0], reverse=reverse)[: self.order_book_level_limit]

    @staticmethod
    def _parse_iso8601_ns(value: Any) -> int:
        if not value:
            raise ValueError("source_timestamp_required")
        text = str(value).strip()
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        fraction_ns = 0
        main = text
        if "." in text:
            prefix, suffix = text.split(".", 1)
            timezone_index = next(
                (index for index, character in enumerate(suffix) if character in "+-"),
                len(suffix),
            )
            fraction = suffix[:timezone_index]
            offset = suffix[timezone_index:]
            if not fraction.isdigit() or len(fraction) > 9:
                raise ValueError("source_timestamp_fraction_invalid")
            fraction_ns = int(fraction.ljust(9, "0"))
            main = f"{prefix}{offset}"
        parsed = datetime.fromisoformat(main)
        if parsed.tzinfo is None:
            raise ValueError("source_timestamp_timezone_required")
        parsed_utc = parsed.astimezone(timezone.utc)
        return calendar.timegm(parsed_utc.utctimetuple()) * 1_000_000_000 + fraction_ns

    @staticmethod
    def _positive_finite(value: Any, field_name: str) -> float:
        if isinstance(value, bool):
            raise ValueError(f"{field_name}_numeric_required")
        parsed = float(value)
        if not math.isfinite(parsed) or parsed <= 0:
            raise ValueError(f"{field_name}_positive_finite_required")
        return parsed

    @staticmethod
    def _nonnegative_finite(value: Any, field_name: str) -> float:
        if isinstance(value, bool):
            raise ValueError(f"{field_name}_numeric_required")
        parsed = float(value)
        if not math.isfinite(parsed) or parsed < 0:
            raise ValueError(f"{field_name}_nonnegative_finite_required")
        return parsed

    @staticmethod
    def _nonnegative_integer(value: Any, field_name: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"{field_name}_nonnegative_integer_required")
        return value

    async def _safe_callback(self, callback: Callable, value: Any) -> bool:
        try:
            started = self._monotonic()
            result = callback(value)
            if asyncio.iscoroutine(result):
                result = await asyncio.wait_for(result, timeout=self.policy.callback_timeout_seconds)
            elif self._monotonic() - started > self.policy.callback_timeout_seconds:
                raise asyncio.TimeoutError("synchronous_callback_timeout")
            if result is False:
                await self._emit_failure("CALLBACK_REJECTED", ValueError("callback_rejected_value"))
                return False
            return True
        except asyncio.TimeoutError:
            self._metrics["callback_timeouts"] += 1
            await self._emit_failure("SLOW_CONSUMER", RuntimeError("callback_timeout"))
            return False
        except Exception as exc:
            await self._emit_failure("CALLBACK_FAILED", exc)
            return False

    async def _emit_failure(
        self,
        status: str,
        exc: Exception,
        *,
        symbol: Optional[str] = None,
        symbols: Optional[tuple[str, ...]] = None,
    ) -> None:
        event = {
            "status": status,
            "provider_id": self.provider_id,
            "execution_location": self.execution_location,
            "symbol": symbol,
            "symbol_count": len(symbols or ()),
            "exception_type": exc.__class__.__name__,
            "reason_code": self._failure_reason(exc),
            "timestamp_ns": now_ns(),
            "executable_truth": False,
        }
        self._failure_history.append(event)
        self._events.append({"event": status, "timestamp_ns": event["timestamp_ns"]})
        if self.on_feed_truth:
            try:
                result = self.on_feed_truth(dict(event))
                if asyncio.iscoroutine(result):
                    await asyncio.wait_for(result, timeout=self.policy.callback_timeout_seconds)
            except Exception as callback_exc:
                self._metrics["truth_callback_failures"] += 1
                logger.error("Market-data truth callback failed: %s", callback_exc.__class__.__name__)

    @staticmethod
    def _failure_reason(exc: Exception) -> str:
        if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
            return "REQUEST_TIMEOUT"
        if isinstance(exc, socket.gaierror):
            return "DNS_FAILURE"
        text = str(exc)
        if "429" in text or "rate" in text.lower():
            return "RATE_LIMITED"
        if "circuit_open" in text or "circuit_half_open" in text:
            return "CIRCUIT_OPEN"
        if isinstance(exc, (aiohttp.ClientConnectionError, ConnectionError, OSError)):
            return "CONNECTION_FAILURE"
        if isinstance(exc, ValueError):
            return "MALFORMED_PROVIDER_PAYLOAD"
        return "TRANSPORT_FAILURE"

    def get_stats(self) -> Dict[str, Any]:
        budget = self._budget
        return {
            "running": self._running,
            "provider_id": self.provider_id,
            "execution_location": self.execution_location,
            "breadth_symbol_count": len(self.breadth_symbols),
            "deep_symbols": self.deep_symbols,
            "protected_symbols": tuple(sorted(self.protected_symbols)),
            "deep_poll_enabled": self.deep_poll_enabled,
            "quote_freshness_policy_ms": self.quote_freshness_policy_ms,
            "order_book_freshness_policy_ms": self.order_book_freshness_policy_ms,
            "candle_freshness_policy_ms": self.candle_freshness_policy_ms,
            "order_book_level_limit": self.order_book_level_limit,
            "policy": self.policy.__dict__.copy(),
            "metrics": {
                **self._metrics,
                "max_inflight": budget.max_inflight if budget else 0,
                "rate_budget_wait_count": budget.wait_count if budget else 0,
            },
            "circuit_state": self._circuit_state,
            "circuit_open_until_monotonic": self._circuit_open_until,
            "consecutive_failures": self._consecutive_failures,
            "failure_history": list(self._failure_history),
            "event_history": list(self._events),
        }
