"""
WebSocket Client - Kraken Real-Time Market Data Connector
Async WebSocket client with Sovereign Grade features:
- Auto-reconnect with exponential backoff
- Heartbeat monitoring with SovereignSentinel integration
- Backpressure handling with bounded queue
- Kraken-specific subscription and message parsing
- L2 order book and trade feed

TIMESTAMP TRUTH (STRICT AUTHORITATIVE PATH):
- exchange_ts_ns MUST come from exchange-provided nested Kraken v2 timestamps
- Messages WITHOUT lawful exchange timestamp are REJECTED (dropped, logged)
- No wall-clock substitution for authoritative timestamps
- receive_ts_ns captured for telemetry only (not passed to canonical models)
"""

import asyncio
import json
import logging
import time
from datetime import datetime
from typing import Dict, List, Optional, Callable, Any, Tuple
from collections import deque

import websockets
from websockets.exceptions import ConnectionClosed, WebSocketException

from app.models import Candle, OrderBookSnapshot
from app.utils.time_utils import now_ns

logger = logging.getLogger(__name__)


class KrakenWebSocketClient:
    """
    Sovereign WebSocket client for Kraken exchange.
    
    TIMESTAMP AUTHORITY:
    - exchange_ts_ns extracted from nested Kraken v2 RFC3339 timestamps
    - Messages missing lawful exchange timestamp are REJECTED (not fabricated)
    - receive_ts_ns captured for monitoring only
    """
    
    def __init__(
        self,
        symbols: List[str],
        on_order_book: Optional[Callable] = None,
        on_trade: Optional[Callable] = None,
        on_candle: Optional[Callable] = None,
        max_queue_size: int = 10000,
        ping_interval: int = 30,
        ping_timeout: int = 10,
        close_timeout: int = 5,
        reconnect_base_delay: float = 1.0,
        reconnect_max_delay: float = 30.0,
        sentinel: Optional[Any] = None,
        on_health: Optional[Callable[[int, int], None]] = None
    ):
        """
        Initialize Kraken WebSocket client.

        Args:
            symbols: List of symbols to subscribe to
            on_order_book: Callback for order book updates
            on_trade: Callback for trade updates
            on_candle: Callback for candle updates
            max_queue_size: Maximum queued messages before dropping
            ping_interval: WebSocket ping interval (seconds)
            ping_timeout: WebSocket ping timeout (seconds)
            close_timeout: WebSocket close timeout (seconds)
            reconnect_base_delay: Initial reconnect delay (seconds)
            reconnect_max_delay: Maximum reconnect delay (seconds)
            sentinel: SovereignSentinel instance for heartbeat monitoring
            on_health: Optional callback for WebSocket health with (ping_ns, pong_ns)
        """
        self.symbols = symbols
        self.on_order_book = on_order_book
        self.on_trade = on_trade
        self.on_candle = on_candle
        self.max_queue_size = max_queue_size
        self.ping_interval = ping_interval
        self.ping_timeout = ping_timeout
        self.close_timeout = close_timeout
        self.reconnect_base_delay = reconnect_base_delay
        self.reconnect_max_delay = reconnect_max_delay
        self.sentinel = sentinel
        self.on_health = on_health
        
        # Kraken WebSocket endpoint
        self.ws_url = "wss://ws.kraken.com/v2"
        
        # Connection state
        self._websocket = None
        self._running = False
        self._connected = False
        self._reconnect_task = None
        self._message_queue: asyncio.Queue = asyncio.Queue(maxsize=max_queue_size)
        
        # Lag monitoring (telemetry only)
        self._processing_lag = deque(maxlen=100)
        self._last_message_time_ns = 0
        self._last_heartbeat_sent_ns = 0
        
        # Subscription status
        self._subscriptions: Dict[str, List[str]] = {}
        
        # Message counters for sequence detection
        self._sequence_counters: Dict[str, int] = {}

        # Per-symbol accumulated order book state
        self._book_bids_by_symbol: Dict[str, Dict[float, float]] = {}
        self._book_asks_by_symbol: Dict[str, Dict[float, float]] = {}

        # Monotonic timestamp tracking per symbol for Kraken delta stream emission.
        # Raw exchange timestamps may arrive out of order or with coarse resolution;
        # emitted internal snapshots must remain strictly monotonic per symbol.
        self._last_emitted_ts_ns_by_symbol: Dict[str, int] = {}

        # Statistics
        self._messages_received = 0
        self._messages_rejected_no_timestamp = 0
        self._messages_processed = 0
        
        logger.info(f"KrakenWebSocketClient initialized: {len(symbols)} symbols")
        logger.info("  TIMESTAMP TRUTH: Strict authoritative path — messages without lawful nested exchange timestamp are REJECTED")
    
    # ============================================
    # CONNECTION MANAGEMENT
    # ============================================
    
    async def connect(self) -> bool:
        """
        Establish WebSocket connection.

        Returns:
            True if connection successful
        """
        try:
            logger.info(f"Connecting to {self.ws_url}")
            self._websocket = await websockets.connect(
                self.ws_url,
                ping_interval=self.ping_interval,
                ping_timeout=self.ping_timeout,
                close_timeout=self.close_timeout
            )
            self._connected = True
            self._last_message_time_ns = now_ns()
            self._last_heartbeat_sent_ns = now_ns()
            
            # Send initial ping to Kraken
            await self._send_ping()
            
            # Subscribe to channels
            await self._subscribe_all()
            
            # Start message processing tasks
            asyncio.create_task(self._receive_messages())
            asyncio.create_task(self._process_queue())
            asyncio.create_task(self._heartbeat_loop())
            
            logger.info(f"WebSocket connected to {self.ws_url}")
            return True
            
        except Exception as e:
            logger.error(f"WebSocket connection failed: {e}")
            self._connected = False
            return False
    
    async def disconnect(self) -> None:
        """Disconnect WebSocket connection."""
        self._running = False
        self._connected = False

        self._last_emitted_ts_ns_by_symbol.clear()

        if self._websocket:
            try:
                await self._websocket.close()
            except Exception as e:
                logger.warning(f"Error closing WebSocket: {e}")
        
        if self._reconnect_task:
            self._reconnect_task.cancel()
        
        logger.info("WebSocket disconnected")
    
    async def _send_ping(self) -> None:
        """Send a ping message to keep connection alive."""
        if self._websocket and self._connected:
            try:
                ping_msg = {"method": "ping"}
                await self._websocket.send(json.dumps(ping_msg))
                self._last_heartbeat_sent_ns = now_ns()
                logger.debug("Ping sent")
            except Exception as e:
                logger.warning(f"Ping failed: {e}")
    
    async def _heartbeat_loop(self) -> None:
        """
        Heartbeat loop to monitor connection health.
        Sends pings every 30 seconds and checks for responses.
        Does NOT report health via on_health to avoid false latency spikes.
        """
        while self._running and self._connected:
            try:
                await asyncio.sleep(30)
                
                # Send ping
                await self._send_ping()
                
                # Check for stale connection
                now = now_ns()
                time_since_last_message_ns = now - self._last_message_time_ns
                time_since_last_message_sec = time_since_last_message_ns / 1_000_000_000.0
                
                if time_since_last_message_sec > 60:
                    logger.warning(f"No messages for {time_since_last_message_sec:.1f}s - connection may be stale")
                    
                    # Alert sentinel if available
                    if self.sentinel:
                        self.sentinel.alert_exchange_outage("kraken", time_since_last_message_sec)
                    
                    # Force reconnect
                    self._connected = False
                    await self._reconnect()
                    break
                    
            except Exception as e:
                logger.error(f"Heartbeat loop error: {e}")
    
    async def _subscribe_all(self) -> None:
        """Subscribe to all channels for configured symbols."""
        if not self._websocket:
            return
        
        # Subscribe to order book (book) channel
        book_msg = {
            "method": "subscribe",
            "params": {
                "channel": "book",
                "symbol": self.symbols,
                "depth": 10
            }
        }
        await self._websocket.send(json.dumps(book_msg))
        logger.info(f"Subscribed to book for {len(self.symbols)} symbols")
        
        # Subscribe to trades channel
        trade_msg = {
            "method": "subscribe",
            "params": {
                "channel": "trade",
                "symbol": self.symbols
            }
        }
        await self._websocket.send(json.dumps(trade_msg))
        logger.info(f"Subscribed to trades for {len(self.symbols)} symbols")
        
        # Subscribe to OHLC channel (1 minute) — Kraken v2 authority
        candle_msg = {
            "method": "subscribe",
            "params": {
                "channel": "ohlc",
                "symbol": self.symbols,
                "interval": 1
            }
        }
        await self._websocket.send(json.dumps(candle_msg))
        logger.info(f"Subscribed to ohlc for {len(self.symbols)} symbols")
        
        # Record subscriptions
        self._subscriptions = {
            "book": self.symbols.copy(),
            "trade": self.symbols.copy(),
            "ohlc": self.symbols.copy()
        }
    
    async def _reconnect(self) -> None:
        """
        Attempt to reconnect with exponential backoff.
        """
        delay = self.reconnect_base_delay
        attempt = 1
        
        while self._running and not self._connected:
            logger.info(f"Reconnect attempt {attempt} in {delay:.1f}s...")
            await asyncio.sleep(delay)
            
            if await self.connect():
                logger.info("Reconnected successfully")
                return
            
            # Exponential backoff
            delay = min(delay * 2, self.reconnect_max_delay)
            attempt += 1
    
    # ============================================
    # MESSAGE HANDLING
    # ============================================
    
    async def _receive_messages(self) -> None:
        """
        Receive messages from WebSocket and queue them.
        """
        while self._running and self._websocket:
            try:
                message = await self._websocket.recv()
                received_at_ns = now_ns()
                self._last_message_time_ns = received_at_ns
                self._messages_received += 1
                
                # Queue message with timestamp
                try:
                    await self._message_queue.put((message, received_at_ns))
                except asyncio.QueueFull:
                    # Backpressure detected - drop message
                    logger.error(f"Queue full! Dropping message.")
                    
            except ConnectionClosed:
                logger.warning("WebSocket connection closed")
                self._connected = False
                await self._reconnect()
                break
            except WebSocketException as e:
                logger.error(f"WebSocket error: {e}")
                self._connected = False
                await self._reconnect()
                break
            except Exception as e:
                logger.error(f"Unexpected error in receive loop: {e}")
                await asyncio.sleep(1)
    
    async def _process_queue(self) -> None:
        """
        Process queued messages with lag monitoring.
        """
        stale_threshold_ns = 30_000_000_000  # 30 seconds
        
        while self._running:
            try:
                message, received_at_ns = await self._message_queue.get()
                
                # Calculate processing lag (telemetry only)
                lag_ns = now_ns() - received_at_ns
                self._processing_lag.append(lag_ns)
                
                # Check for stale data (telemetry warning only)
                if lag_ns > stale_threshold_ns:
                    lag_sec = lag_ns / 1_000_000_000.0
                    logger.warning(f"Stale message detected: {lag_sec:.2f}s lag")
                    # Still process — staleness is telemetry, not authority rejection
                
                # Process message
                await self._process_message(message, received_at_ns)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error processing message: {e}")
    
    async def _process_message(self, raw_message: str, receive_ts_ns: int) -> None:
        """
        Process a single WebSocket message.

        Args:
            raw_message: Raw WebSocket message
            receive_ts_ns: Nanosecond timestamp when message was received (telemetry only)
        """
        try:
            data = json.loads(raw_message)

            # Check for heartbeat/pong response
            if data.get("method") == "pong":
                if self.on_health and self._last_heartbeat_sent_ns > 0:
                    if receive_ts_ns >= self._last_heartbeat_sent_ns:
                        self.on_health(self._last_heartbeat_sent_ns, receive_ts_ns)
                    else:
                        logger.warning("Pong received before recorded ping timestamp; RTT truth not emitted")
                logger.debug("Pong received")
                return
            
            # Check for subscription confirmation
            if data.get("method") == "subscribe":
                status = data.get("params", {}).get("status")
                if status == "subscribed":
                    logger.debug(f"Subscription confirmed: {data.get('params', {}).get('channel')}")
                return
            
            # Check for error
            if data.get("method") == "error":
                logger.error(f"WebSocket error: {data}")
                return
            
            # Parse based on channel type
            channel = data.get("channel")
            
            if channel == "book":
                await self._parse_order_book(data, receive_ts_ns)
            elif channel == "trade":
                await self._parse_trade(data, receive_ts_ns)
            elif channel in ("ohlc", "candle"):
                await self._parse_candle(data, receive_ts_ns)
            else:
                logger.debug(f"Unknown channel: {channel}")
                
        except json.JSONDecodeError as e:
            logger.error(f"JSON decode error: {e}")
        except Exception as e:
            logger.error(f"Message processing error: {e}")
    
    # ============================================
    # MESSAGE PARSING — STRICT AUTHORITATIVE PATH
    # ============================================

    def _parse_rfc3339_to_ns(self, timestamp_value: Any, channel_type: str) -> Optional[int]:
        """
        Parse Kraken v2 RFC3339 timestamp into canonical ns.

        STRICT RULE:
        - No wall-clock substitution
        - Invalid or missing exchange timestamp -> reject
        """
        if timestamp_value is None:
            logger.warning(f"Missing RFC3339 timestamp in {channel_type} message — rejecting")
            self._messages_rejected_no_timestamp += 1
            return None

        if not isinstance(timestamp_value, str):
            logger.warning(f"Non-string timestamp in {channel_type} message: {timestamp_value} — rejecting")
            self._messages_rejected_no_timestamp += 1
            return None

        ts = timestamp_value.strip()
        if not ts:
            logger.warning(f"Empty timestamp string in {channel_type} message — rejecting")
            self._messages_rejected_no_timestamp += 1
            return None

        try:
            if ts.endswith("Z"):
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            else:
                dt = datetime.fromisoformat(ts)

            if dt.tzinfo is None:
                logger.warning(f"Naive timestamp in {channel_type} message: {timestamp_value} — rejecting")
                self._messages_rejected_no_timestamp += 1
                return None

            return int(dt.timestamp() * 1_000_000_000)
        except Exception:
            logger.warning(f"Invalid RFC3339 timestamp in {channel_type} message: {timestamp_value} — rejecting")
            self._messages_rejected_no_timestamp += 1
            return None

    def _get_nested_payload_objects(self, data: Dict) -> List[Dict]:
        """
        Extract Kraken v2 nested payload objects from data[].

        Returns:
            List of nested dict payload entries
        """
        payload = data.get("data", [])
        if not isinstance(payload, list):
            return []
        return [entry for entry in payload if isinstance(entry, dict)]

    def _extract_nested_symbol(self, payload_obj: Dict) -> str:
        """
        Extract symbol from nested Kraken v2 payload object.
        """
        for key in ("symbol", "pair", "instrument_name"):
            value = payload_obj.get(key)
            if isinstance(value, str) and value:
                return value
        return ""

    def _extract_nested_exchange_timestamp_ns(self, payload_obj: Dict, channel_type: str, candidate_keys: List[str]) -> Optional[int]:
        """
        Extract authoritative nested exchange timestamp from Kraken v2 payload object.

        Args:
            payload_obj: Nested payload dict
            channel_type: Logical channel name for logging
            candidate_keys: Ordered candidate timestamp keys

        Returns:
            exchange_ts_ns if valid, None otherwise
        """
        for key in candidate_keys:
            if key in payload_obj:
                exchange_ts_ns = self._parse_rfc3339_to_ns(payload_obj.get(key), channel_type)
                if exchange_ts_ns is not None:
                    return exchange_ts_ns

        logger.warning(f"Missing nested exchange timestamp in {channel_type} payload — rejecting")
        self._messages_rejected_no_timestamp += 1
        return None
    
    async def _parse_order_book(self, data: Dict, receive_ts_ns: int) -> None:
        """
        Parse order book message from Kraken v2.

        STRICT AUTHORITATIVE PATH:
        - symbol MUST come from nested payload object(s) inside data[]
        - exchange_ts_ns MUST come from nested Kraken v2 RFC3339 timestamp
        - Missing or invalid nested fields -> message REJECTED
        """
        try:
            payload_objects = self._get_nested_payload_objects(data)
            if not payload_objects:
                logger.warning("Order book message missing nested payload data[] — rejecting")
                return

            for book_data in payload_objects:
                symbol = self._extract_nested_symbol(book_data)
                if not symbol:
                    logger.warning("Order book nested payload missing symbol — rejecting")
                    continue

                exchange_ts_ns = self._extract_nested_exchange_timestamp_ns(
                    book_data,
                    "order_book",
                    ["timestamp", "time", "ts"]
                )
                if exchange_ts_ns is None:
                    continue

                # Initialize per-symbol book state if not yet present
                if symbol not in self._book_bids_by_symbol:
                    self._book_bids_by_symbol[symbol] = {}
                if symbol not in self._book_asks_by_symbol:
                    self._book_asks_by_symbol[symbol] = {}
                if symbol not in self._last_emitted_ts_ns_by_symbol:
                    self._last_emitted_ts_ns_by_symbol[symbol] = 0

                bid_map = self._book_bids_by_symbol[symbol]
                ask_map = self._book_asks_by_symbol[symbol]

                # Apply bid updates: qty <= 0 removes level, qty > 0 sets level
                for bid in book_data.get("bids", []):
                    try:
                        price_f = float(bid.get("price", 0))
                        qty_f = float(bid.get("qty", 0))
                        if price_f <= 0:
                            continue
                        if qty_f <= 0:
                            bid_map.pop(price_f, None)
                        else:
                            bid_map[price_f] = qty_f
                    except Exception:
                        continue

                # Apply ask updates: qty <= 0 removes level, qty > 0 sets level
                for ask in book_data.get("asks", []):
                    try:
                        price_f = float(ask.get("price", 0))
                        qty_f = float(ask.get("qty", 0))
                        if price_f <= 0:
                            continue
                        if qty_f <= 0:
                            ask_map.pop(price_f, None)
                        else:
                            ask_map[price_f] = qty_f
                    except Exception:
                        continue

                # Emit only when accumulated book has both sides
                if not bid_map or not ask_map:
                    logger.info(
                        "[BOOK_DIAG] WAITING_FOR_TWO_SIDED_BOOK symbol=%s bids=%d asks=%d",
                        symbol,
                        len(bid_map),
                        len(ask_map),
                    )
                    continue

                # Sort bids descending, asks ascending; cap at 50 levels
                sorted_bids = sorted(bid_map.items(), key=lambda x: x[0], reverse=True)[:50]
                sorted_asks = sorted(ask_map.items(), key=lambda x: x[0])[:50]

                # Do not emit one-sided books. They are not valid internal market snapshots.
                if not sorted_bids or not sorted_asks:
                    if self._messages_processed % 100 == 0:
                        logger.warning(
                            "[BOOK_DIAG] ONE_SIDED_BOOK_PREVENTED symbol=%s bids=%d asks=%d",
                            symbol,
                            len(sorted_bids),
                            len(sorted_asks),
                        )
                    continue

                # Do not emit crossed or inverted books. Preserve accumulator state and
                # wait for the next delta to restore a valid market view.
                best_bid = sorted_bids[0][0]
                best_ask = sorted_asks[0][0]
                if best_bid >= best_ask:
                    if self._messages_processed % 100 == 0:
                        logger.warning(
                            "[BOOK_DIAG] CROSSED_BOOK_PREVENTED symbol=%s best_bid=%.8f best_ask=%.8f spread=%.8f bids=%d asks=%d",
                            symbol,
                            best_bid,
                            best_ask,
                            best_ask - best_bid,
                            len(sorted_bids),
                            len(sorted_asks),
                        )
                    continue

                # Enforce strictly monotonic internal snapshot timestamps per symbol.
                # Preserve raw exchange_ts_ns in diagnostic logs; emit only effective_ts_ns.
                last_emitted = self._last_emitted_ts_ns_by_symbol.get(symbol, 0)
                effective_ts_ns = exchange_ts_ns or 0

                if effective_ts_ns <= last_emitted:
                    effective_ts_ns = last_emitted + 1
                    logger.debug(
                        "[BOOK_DIAG] TIMESTAMP_ADJUSTED symbol=%s raw_ts_ns=%d effective_ts_ns=%d diff_ns=%d",
                        symbol,
                        exchange_ts_ns or 0,
                        effective_ts_ns,
                        effective_ts_ns - (exchange_ts_ns or 0),
                    )

                self._last_emitted_ts_ns_by_symbol[symbol] = effective_ts_ns

                snapshot = OrderBookSnapshot(
                    symbol=symbol,
                    exchange_ts_ns=effective_ts_ns,
                    bids=sorted_bids,
                    asks=sorted_asks,
                )

                self._messages_processed += 1

                if self.on_order_book:
                    if asyncio.iscoroutinefunction(self.on_order_book):
                        await self.on_order_book(snapshot)
                    else:
                        self.on_order_book(snapshot)
                    
        except Exception as e:
            logger.error(f"Failed to parse order book: {e}")
    
    async def _parse_trade(self, data: Dict, receive_ts_ns: int) -> None:
        """
        Parse trade message from Kraken v2.

        STRICT AUTHORITATIVE PATH:
        - symbol MUST come from each nested trade object if present, otherwise
          from enclosing nested payload object
        - exchange_ts_ns MUST come from nested trade/object RFC3339 timestamp
        - Missing or invalid nested fields -> trade REJECTED
        """
        try:
            payload_objects = self._get_nested_payload_objects(data)
            if not payload_objects:
                logger.warning("Trade message missing nested payload data[] — rejecting")
                return

            for payload_obj in payload_objects:
                payload_symbol = self._extract_nested_symbol(payload_obj)

                # Some Kraken v2 payloads place actual trade records inside nested arrays/objects;
                # preserve-first handling: if payload_obj itself looks like a trade, process it directly,
                # otherwise process entries in payload_obj["trades"] if present.
                trade_entries = []
                if "price" in payload_obj and ("qty" in payload_obj or "quantity" in payload_obj):
                    trade_entries = [payload_obj]
                elif isinstance(payload_obj.get("trades"), list):
                    trade_entries = [t for t in payload_obj.get("trades", []) if isinstance(t, dict)]
                else:
                    trade_entries = [payload_obj]

                for trade_data in trade_entries:
                    symbol = self._extract_nested_symbol(trade_data) or payload_symbol
                    if not symbol:
                        logger.warning("Trade payload missing symbol — rejecting")
                        continue

                    exchange_ts_ns = self._extract_nested_exchange_timestamp_ns(
                        trade_data if any(k in trade_data for k in ("timestamp", "time", "trade_time")) else payload_obj,
                        "trade",
                        ["timestamp", "time", "trade_time"]
                    )
                    if exchange_ts_ns is None:
                        continue

                    try:
                        price = float(trade_data.get("price", 0))
                        volume = float(trade_data.get("qty", trade_data.get("quantity", 0)))
                    except Exception:
                        logger.warning("Trade payload has non-numeric price/qty — rejecting")
                        continue

                    side_str = trade_data.get("side", trade_data.get("taker_side", "buy"))
                    side = 1 if side_str == "buy" else -1

                    trade_info = {
                        "symbol": symbol,
                        "price": price,
                        "volume": volume,
                        "side": side,
                        "exchange_ts_ns": exchange_ts_ns,
                        "receive_ts_ns": receive_ts_ns,
                        "trade_id": trade_data.get("trade_id", "")
                    }

                    self._messages_processed += 1

                    if self.on_trade:
                        if asyncio.iscoroutinefunction(self.on_trade):
                            await self.on_trade(trade_info)
                        else:
                            self.on_trade(trade_info)
                        
        except Exception as e:
            logger.error(f"Failed to parse trade: {e}")
    
    async def _parse_candle(self, data: Dict, receive_ts_ns: int) -> None:
        """
        Parse candle message from Kraken v2.

        STRICT AUTHORITATIVE PATH:
        - symbol MUST come from nested payload object(s) inside data[]
        - exchange_ts_ns MUST come from nested Kraken v2 RFC3339 timestamp
        - Missing or invalid nested fields -> candle REJECTED

        Assumption:
        - active candle payload may provide authoritative timestamp under:
          interval_begin, timestamp, or time
        """
        try:
            payload_objects = self._get_nested_payload_objects(data)
            if not payload_objects:
                logger.warning("Candle message missing nested payload data[] — rejecting")
                return

            for candle_data in payload_objects:
                symbol = self._extract_nested_symbol(candle_data)
                if not symbol:
                    logger.warning("Candle nested payload missing symbol — rejecting")
                    continue

                exchange_ts_ns = self._extract_nested_exchange_timestamp_ns(
                    candle_data,
                    "candle",
                    ["interval_begin", "timestamp", "time"]
                )
                if exchange_ts_ns is None:
                    continue

                try:
                    candle = Candle(
                        symbol=symbol,
                        exchange_ts_ns=exchange_ts_ns,
                        open=float(candle_data.get("open", 0)),
                        high=float(candle_data.get("high", 0)),
                        low=float(candle_data.get("low", 0)),
                        close=float(candle_data.get("close", 0)),
                        volume=float(candle_data.get("volume", 0)),
                        timeframe="1m"
                    )
                except Exception:
                    logger.warning("Candle payload has non-numeric OHLCV fields — rejecting")
                    continue
                
                self._messages_processed += 1
                
                if self.on_candle:
                    if asyncio.iscoroutinefunction(self.on_candle):
                        await self.on_candle(candle)
                    else:
                        self.on_candle(candle)
                        
        except Exception as e:
            logger.error(f"Failed to parse candle: {e}")
    
    # ============================================
    # UTILITY METHODS
    # ============================================
    
    def _calculate_lag_ms(self) -> float:
        """Calculate average processing lag in milliseconds (telemetry only)."""
        if not self._processing_lag:
            return 0.0
        avg_lag_ns = sum(self._processing_lag) / len(self._processing_lag)
        return avg_lag_ns / 1_000_000.0
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Get WebSocket statistics.

        Returns:
            Dictionary with connection stats
        """
        return {
            "connected": self._connected,
            "queue_size": self._message_queue.qsize(),
            "max_queue_size": self.max_queue_size,
            "avg_lag_ms": self._calculate_lag_ms(),
            "last_message_time_ns": self._last_message_time_ns,
            "symbols_subscribed": len(self.symbols),
            "subscriptions": self._subscriptions,
            "messages_received": self._messages_received,
            "messages_rejected_no_timestamp": self._messages_rejected_no_timestamp,
            "messages_processed": self._messages_processed
        }

    def get_feed_truth_status(self) -> Dict[str, Any]:
        """Return machine-readable websocket feed truth without inventing REST state."""
        status = "WEBSOCKET_ACTIVE" if self._connected or self._messages_processed > 0 else "WEBSOCKET_INACTIVE"
        return {
            "status": status,
            "exchange": "kraken",
            "endpoint": self.ws_url,
            "connected": self._connected,
            "last_message_time_ns": self._last_message_time_ns,
            "messages_processed": self._messages_processed,
            "messages_rejected_no_timestamp": self._messages_rejected_no_timestamp,
        }
    
    async def start(self) -> None:
        """Start the WebSocket client."""
        if self._running:
            logger.warning("WebSocket client already running")
            return
        
        self._running = True
        await self.connect()
    
    async def stop(self) -> None:
        """Stop the WebSocket client."""
        self._running = False
        await self.disconnect()


# ============================================
# FACTORY FUNCTION
# ============================================

def create_kraken_websocket(
    symbols: List[str],
    on_order_book: Optional[Callable] = None,
    on_trade: Optional[Callable] = None,
    on_candle: Optional[Callable] = None,
    sentinel: Optional[Any] = None,
    on_health: Optional[Callable[[int, int], None]] = None
) -> KrakenWebSocketClient:
    """
    Factory function to create a configured Kraken WebSocket client.

    Args:
        symbols: List of symbols to subscribe to
        on_order_book: Callback for order book updates
        on_trade: Callback for trade updates
        on_candle: Callback for candle updates
        sentinel: SovereignSentinel instance for monitoring
        on_health: Optional callback for WebSocket health with (ping_ns, pong_ns)

    Returns:
        Configured KrakenWebSocketClient
    """
    return KrakenWebSocketClient(
        symbols=symbols,
        on_order_book=on_order_book,
        on_trade=on_trade,
        on_candle=on_candle,
        sentinel=sentinel,
        on_health=on_health
    )
