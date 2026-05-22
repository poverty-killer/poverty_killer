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
import calendar
import logging
import time
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
                    latest_batch_ts_ns = max(
                        (candle.exchange_ts_ns for candle in candles),
                        default=0,
                    )
                    candle_policy_ms = self._candle_freshness_policy_ms()

                    for candle in candles:
                        # Check for duplicate
                        last_ts_ns = self._last_candle_timestamps_ns.get(symbol)
                        if last_ts_ns and candle.exchange_ts_ns <= last_ts_ns:
                            continue

                        self._last_candle_timestamps_ns[symbol] = candle.exchange_ts_ns
                        candle = self._with_candle_runtime_metadata(
                            candle,
                            latest_batch_ts_ns=latest_batch_ts_ns,
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
                    order_book = self._parse_order_book(data, symbol)

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

    def _with_candle_runtime_metadata(
        self,
        candle: Candle,
        *,
        latest_batch_ts_ns: int,
        response_received_ns: int,
        candle_policy_ms: Optional[float],
    ) -> Candle:
        return candle.model_copy(
            update={
                "data_source_type": "runtime",
                "provider_id": self.provider_id,
                "latest_batch_candle": candle.exchange_ts_ns == latest_batch_ts_ns,
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
        if len(self._failure_history) > 100:
            self._failure_history = self._failure_history[-100:]
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

    def _parse_order_book(self, data: Dict, symbol: str) -> Optional[OrderBookSnapshot]:
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
                )

            result = data.get("result", {})
            for key, book_data in result.items():
                if isinstance(book_data, dict):
                    bids_raw = book_data.get("bids", [])
                    asks_raw = book_data.get("asks", [])

                    bids = []
                    for entry in bids_raw:
                        try:
                            # Safely extract first two fields regardless of entry length
                            if isinstance(entry, (list, tuple)) and len(entry) >= 2:
                                price = float(entry[0])
                                size = float(entry[1])
                                bids.append((price, size))
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
                            else:
                                logger.warning(f"Malformed ask entry in order book for {symbol}: {entry}")
                        except (ValueError, TypeError) as e:
                            logger.warning(f"Failed to convert ask entry for {symbol}: {entry} - {e}")

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
