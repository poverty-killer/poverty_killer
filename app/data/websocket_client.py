"""
WebSocket Clients - Kraken and Alpaca Real-Time Market Data Connectors
Async WebSocket client with Sovereign Grade features:
- Auto-reconnect with exponential backoff
- Heartbeat monitoring with SovereignSentinel integration
- Backpressure handling with bounded queue
- Venue-specific subscription and message parsing
- L2 order book and trade feed

TIMESTAMP TRUTH (STRICT AUTHORITATIVE PATH):
- exchange_ts_ns MUST come from exchange-provided nested Kraken v2 timestamps
- Messages WITHOUT lawful exchange timestamp are REJECTED (dropped, logged)
- No wall-clock substitution for authoritative timestamps
- receive_ts_ns is explicit causal-availability and transport-health evidence
"""

import asyncio
import calendar
import hashlib
import json
import logging
import math
import time
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Dict, List, Optional, Callable, Any, Tuple, Mapping
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
    - receive_ts_ns is retained separately from exchange event identity
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
        application_ping_interval: Optional[float] = None,
        close_timeout: int = 5,
        reconnect_base_delay: float = 1.0,
        reconnect_max_delay: float = 30.0,
        sentinel: Optional[Any] = None,
        on_health: Optional[Callable[[int, int], None]] = None,
        book_depth: int = 10,
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
            application_ping_interval: Kraken application-level ping interval (seconds)
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
        self.application_ping_interval = max(
            1.0,
            float(
                application_ping_interval
                if application_ping_interval is not None
                else min(10.0, max(1.0, ping_interval / 3.0))
            ),
        )
        self.close_timeout = close_timeout
        self.reconnect_base_delay = reconnect_base_delay
        self.reconnect_max_delay = reconnect_max_delay
        self.sentinel = sentinel
        self.on_health = on_health
        self.book_depth = max(1, int(book_depth))
        
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
        self._last_pong_received_ns = 0
        self._last_rtt_ms: Optional[float] = None
        self._pong_count = 0
        
        # Subscription status
        self._subscriptions: Dict[str, List[str]] = {}
        
        # Message counters for sequence detection
        self._sequence_counters: Dict[str, int] = {}

        # Per-symbol accumulated order book state
        self._book_bids_by_symbol: Dict[str, Dict[float, float]] = {}
        self._book_asks_by_symbol: Dict[str, Dict[float, float]] = {}
        self._book_quality_by_symbol: Dict[str, Dict[str, Any]] = {}
        self._book_crossed_rejections_by_symbol: Dict[str, int] = {}

        # Monotonic timestamp tracking per symbol for Kraken delta stream emission.
        # Raw exchange timestamps may arrive out of order or with coarse resolution;
        # emitted internal snapshots must remain strictly monotonic per symbol.
        self._last_emitted_ts_ns_by_symbol: Dict[str, int] = {}
        self._last_candle_ts_ns_by_symbol: Dict[str, int] = {}
        self._candle_duplicate_rejections_by_symbol: Dict[str, int] = {}

        # Statistics
        self._messages_received = 0
        self._messages_rejected_no_timestamp = 0
        self._messages_processed = 0
        
        logger.info(f"KrakenWebSocketClient initialized: {len(symbols)} symbols")
        logger.info(
            "  RTT TRUTH: Kraken app ping interval=%.1fs, explicit pong required for finite RTT",
            self.application_ping_interval,
        )
        logger.info("  BOOK TRUTH: local L2 book truncates to subscribed depth=%d after every update", self.book_depth)
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
        Sends explicit Kraken app pings inside the 30s RTT stale window and
        checks for responses.
        Does NOT report health via on_health to avoid false latency spikes.
        """
        while self._running and self._connected:
            try:
                await asyncio.sleep(self.application_ping_interval)
                
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
                "depth": self.book_depth
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
            receive_ts_ns: Local receipt timestamp for transport and causal evidence
        """
        try:
            data = json.loads(raw_message)

            # Check for heartbeat/pong response
            if data.get("method") == "pong":
                if self._last_heartbeat_sent_ns > 0:
                    if receive_ts_ns >= self._last_heartbeat_sent_ns:
                        self._last_pong_received_ns = receive_ts_ns
                        self._last_rtt_ms = (receive_ts_ns - self._last_heartbeat_sent_ns) / 1_000_000.0
                        self._pong_count += 1
                        if self.on_health:
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

    def _replace_book_side(self, side_map: Dict[float, float], entries: List[Any]) -> None:
        side_map.clear()
        for entry in entries:
            price_f, qty_f = self._parse_book_level(entry)
            if price_f is None or qty_f is None or price_f <= 0 or qty_f <= 0:
                continue
            side_map[price_f] = qty_f

    def _apply_book_side_updates(self, side_map: Dict[float, float], entries: List[Any]) -> None:
        for entry in entries:
            price_f, qty_f = self._parse_book_level(entry)
            if price_f is None or qty_f is None or price_f <= 0:
                continue
            if qty_f <= 0:
                side_map.pop(price_f, None)
            else:
                side_map[price_f] = qty_f

    def _parse_book_level(self, entry: Any) -> Tuple[Optional[float], Optional[float]]:
        try:
            if isinstance(entry, dict):
                return float(entry.get("price", 0)), float(entry.get("qty", 0))
            if isinstance(entry, (list, tuple)) and len(entry) >= 2:
                return float(entry[0]), float(entry[1])
        except Exception:
            return None, None
        return None, None

    def _truncate_book_to_depth(self, bid_map: Dict[float, float], ask_map: Dict[float, float]) -> None:
        if len(bid_map) > self.book_depth:
            keep_bids = {price for price, _ in sorted(bid_map.items(), key=lambda x: x[0], reverse=True)[:self.book_depth]}
            for price in list(bid_map):
                if price not in keep_bids:
                    bid_map.pop(price, None)

        if len(ask_map) > self.book_depth:
            keep_asks = {price for price, _ in sorted(ask_map.items(), key=lambda x: x[0])[:self.book_depth]}
            for price in list(ask_map):
                if price not in keep_asks:
                    ask_map.pop(price, None)

    def _record_book_quality(
        self,
        symbol: str,
        *,
        status: str,
        reason: str,
        source: str,
        exchange_ts_ns: int,
        best_bid: Optional[float] = None,
        best_ask: Optional[float] = None,
    ) -> None:
        self._book_quality_by_symbol[symbol] = {
            "status": status,
            "reason": reason,
            "source": source,
            "exchange_ts_ns": exchange_ts_ns,
            "best_bid": best_bid,
            "best_ask": best_ask,
            "subscribed_depth": self.book_depth,
            "timestamp_ns": now_ns(),
        }
    
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

                source_type = str(data.get("type") or book_data.get("type") or "update")
                if source_type == "snapshot":
                    self._replace_book_side(bid_map, book_data.get("bids", []))
                    self._replace_book_side(ask_map, book_data.get("asks", []))
                else:
                    self._apply_book_side_updates(bid_map, book_data.get("bids", []))
                    self._apply_book_side_updates(ask_map, book_data.get("asks", []))

                # Kraken's L2 book contract requires truncating to the subscribed
                # depth after every update because fallen-out levels may not be
                # sent back as qty=0 deletes.
                self._truncate_book_to_depth(bid_map, ask_map)

                # Emit only when accumulated book has both sides
                if not bid_map or not ask_map:
                    logger.info(
                        "[BOOK_DIAG] WAITING_FOR_TWO_SIDED_BOOK symbol=%s bids=%d asks=%d",
                        symbol,
                        len(bid_map),
                        len(ask_map),
                    )
                    continue

                # Sort bids descending, asks ascending; cap at subscribed depth.
                sorted_bids = sorted(bid_map.items(), key=lambda x: x[0], reverse=True)[:self.book_depth]
                sorted_asks = sorted(ask_map.items(), key=lambda x: x[0])[:self.book_depth]

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

                # Do not emit crossed or inverted books. Quarantine the local
                # accumulator because one side may contain stale depth that fell
                # out of scope. A later clean snapshot/update must rebuild truth.
                best_bid = sorted_bids[0][0]
                best_ask = sorted_asks[0][0]
                if best_bid >= best_ask:
                    self._book_crossed_rejections_by_symbol[symbol] = (
                        self._book_crossed_rejections_by_symbol.get(symbol, 0) + 1
                    )
                    self._record_book_quality(
                        symbol,
                        status="BOOK_QUARANTINED",
                        reason="CROSSED_BOOK_PREVENTED",
                        source=source_type,
                        exchange_ts_ns=exchange_ts_ns,
                        best_bid=best_bid,
                        best_ask=best_ask,
                    )
                    logger.warning(
                        "[BOOK_DIAG] CROSSED_BOOK_PREVENTED symbol=%s source=%s best_bid=%.8f best_ask=%.8f spread=%.8f bids=%d asks=%d subscribed_depth=%d quarantined_count=%d",
                        symbol,
                        source_type,
                        best_bid,
                        best_ask,
                        best_ask - best_bid,
                        len(sorted_bids),
                        len(sorted_asks),
                        self.book_depth,
                        self._book_crossed_rejections_by_symbol[symbol],
                    )
                    bid_map.clear()
                    ask_map.clear()
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
                self._record_book_quality(
                    symbol,
                    status="BOOK_ACTIVE",
                    reason="CLEAN_BOOK_EMITTED",
                    source=source_type,
                    exchange_ts_ns=effective_ts_ns,
                    best_bid=best_bid,
                    best_ask=best_ask,
                )

                snapshot = OrderBookSnapshot(
                    symbol=symbol,
                    exchange_ts_ns=effective_ts_ns,
                    bids=sorted_bids,
                    asks=sorted_asks,
                    receive_ts_ns=receive_ts_ns,
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

                last_candle_ts_ns = self._last_candle_ts_ns_by_symbol.get(symbol, 0)
                if exchange_ts_ns <= last_candle_ts_ns:
                    reason = (
                        "CANDLE_DUPLICATE_QUARANTINED"
                        if exchange_ts_ns == last_candle_ts_ns
                        else "CANDLE_STALE_QUARANTINED"
                    )
                    self._candle_duplicate_rejections_by_symbol[symbol] = (
                        self._candle_duplicate_rejections_by_symbol.get(symbol, 0) + 1
                    )
                    logger.info(
                        "%s: symbol=%s ts_ns=%d last_ts_ns=%d source=kraken_ws_ohlc total_duplicates=%d",
                        reason,
                        symbol,
                        exchange_ts_ns,
                        last_candle_ts_ns,
                        self._candle_duplicate_rejections_by_symbol[symbol],
                    )
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
                        timeframe="1m",
                        candle_batch_received_ns=receive_ts_ns,
                        provider_id="kraken_ws",
                    )
                except Exception:
                    logger.warning("Candle payload has non-numeric OHLCV fields — rejecting")
                    continue
                
                self._messages_processed += 1
                self._last_candle_ts_ns_by_symbol[symbol] = exchange_ts_ns
                
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
            "messages_processed": self._messages_processed,
            "application_ping_interval": self.application_ping_interval,
            "last_heartbeat_sent_ns": self._last_heartbeat_sent_ns,
            "last_pong_received_ns": self._last_pong_received_ns,
            "last_rtt_ms": self._last_rtt_ms,
            "pong_count": self._pong_count,
            "book_quality_by_symbol": {
                symbol: dict(status)
                for symbol, status in self._book_quality_by_symbol.items()
            },
            "book_crossed_rejections_by_symbol": dict(self._book_crossed_rejections_by_symbol),
            "candle_duplicate_rejections_by_symbol": dict(self._candle_duplicate_rejections_by_symbol),
        }

    def _websocket_rtt_truth(self, current_ns: Optional[int] = None) -> Dict[str, Any]:
        current_ns = int(current_ns or now_ns())
        if self._last_pong_received_ns <= 0:
            return {
                "status": "MISSING_LATENCY_TRUTH",
                "reason": "WEBSOCKET_RTT_NOT_READY",
                "application_ping_interval": self.application_ping_interval,
                "last_heartbeat_sent_ns": self._last_heartbeat_sent_ns,
                "last_pong_received_ns": self._last_pong_received_ns,
                "last_rtt_ms": self._last_rtt_ms,
                "pong_count": self._pong_count,
            }

        staleness_ms = max(0.0, (current_ns - self._last_pong_received_ns) / 1_000_000.0)
        if staleness_ms > 30_000.0:
            return {
                "status": "STALE_MARKET_TRUTH",
                "reason": "WEBSOCKET_RTT_STALE",
                "application_ping_interval": self.application_ping_interval,
                "last_heartbeat_sent_ns": self._last_heartbeat_sent_ns,
                "last_pong_received_ns": self._last_pong_received_ns,
                "last_rtt_ms": self._last_rtt_ms,
                "pong_count": self._pong_count,
                "staleness_ms": staleness_ms,
            }

        return {
            "status": "WEBSOCKET_RTT_ACTIVE",
            "reason": "EXPLICIT_KRAKEN_PONG",
            "application_ping_interval": self.application_ping_interval,
            "last_heartbeat_sent_ns": self._last_heartbeat_sent_ns,
            "last_pong_received_ns": self._last_pong_received_ns,
            "last_rtt_ms": self._last_rtt_ms,
            "pong_count": self._pong_count,
            "staleness_ms": staleness_ms,
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
            "rtt": self._websocket_rtt_truth(),
            "book_quality_by_symbol": {
                symbol: dict(status)
                for symbol, status in self._book_quality_by_symbol.items()
            },
            "book_crossed_rejections_by_symbol": dict(self._book_crossed_rejections_by_symbol),
            "candle_duplicate_rejections_by_symbol": dict(self._candle_duplicate_rejections_by_symbol),
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


class AlpacaCryptoWebSocketClient:
    """Bounded Alpaca crypto deep-stream adapter with strict source truth."""

    ws_url = "wss://stream.data.alpaca.markets/v1beta3/crypto/us"

    def __init__(
        self,
        *,
        symbols: List[str],
        key_id: str,
        secret_key: str,
        on_order_book: Optional[Callable] = None,
        on_trade: Optional[Callable] = None,
        on_quote: Optional[Callable] = None,
        on_candle: Optional[Callable] = None,
        on_feed_truth: Optional[Callable] = None,
        on_health: Optional[Callable[[int, int], Any]] = None,
        max_queue_size: int = 10000,
        ping_interval: int = 30,
        ping_timeout: int = 10,
        close_timeout: int = 5,
        callback_timeout_seconds: float = 5.0,
        quote_freshness_policy_ms: float = 10_000.0,
        order_book_freshness_policy_ms: float = 10_000.0,
        candle_freshness_policy_ms: float = 60_000.0,
        dedupe_history_size: int = 10000,
        order_book_level_limit: int = 1000,
        connect_factory: Optional[Callable] = None,
    ) -> None:
        normalized = tuple(dict.fromkeys(str(symbol).strip().upper() for symbol in symbols if str(symbol).strip()))
        if not normalized:
            raise ValueError("alpaca_crypto_stream_symbols_required")
        if not str(key_id).strip() or not str(secret_key).strip():
            raise ValueError("alpaca_crypto_stream_credentials_required")
        self.symbols = normalized
        self._key_id = str(key_id)
        self._secret_key = str(secret_key)
        self.on_order_book = on_order_book
        self.on_trade = on_trade
        self.on_quote = on_quote
        self.on_candle = on_candle
        self.on_feed_truth = on_feed_truth
        self.on_health = on_health
        self.max_queue_size = max(1, int(max_queue_size))
        self.ping_interval = max(1, int(ping_interval))
        self.ping_timeout = max(1, int(ping_timeout))
        self.close_timeout = max(1, int(close_timeout))
        self.callback_timeout_seconds = max(0.1, float(callback_timeout_seconds))
        self.quote_freshness_policy_ms = float(quote_freshness_policy_ms)
        self.order_book_freshness_policy_ms = float(order_book_freshness_policy_ms)
        self.candle_freshness_policy_ms = float(candle_freshness_policy_ms)
        for field_name, value in (
            ("quote", self.quote_freshness_policy_ms),
            ("order_book", self.order_book_freshness_policy_ms),
            ("candle", self.candle_freshness_policy_ms),
        ):
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"alpaca_{field_name}_freshness_policy_invalid")
        if isinstance(dedupe_history_size, bool) or not isinstance(dedupe_history_size, int) or dedupe_history_size <= 0:
            raise ValueError("alpaca_websocket_dedupe_history_size_invalid")
        if isinstance(order_book_level_limit, bool) or not isinstance(order_book_level_limit, int) or order_book_level_limit <= 0:
            raise ValueError("alpaca_order_book_level_limit_invalid")
        self.dedupe_history_size = dedupe_history_size
        self.order_book_level_limit = order_book_level_limit
        self._connect_factory = connect_factory or websockets.connect
        self._websocket = None
        self._running = False
        self._connected = False
        self._authenticated = False
        self._message_queue: asyncio.Queue = asyncio.Queue(maxsize=self.max_queue_size)
        self._tasks: list[asyncio.Task] = []
        self._messages_received = 0
        self._messages_processed = 0
        self._messages_rejected = 0
        self._queue_drops = 0
        self._queue_high_water = 0
        self._last_message_time_ns = 0
        self._last_event_time_ns_by_channel_symbol: Dict[Tuple[str, str], int] = {}
        self._last_candle_time_ns_by_symbol: Dict[str, int] = {}
        self._order_book_levels_by_symbol: Dict[str, Dict[str, Dict[Decimal, Decimal]]] = {}
        self._event_identities: deque[bytes] = deque()
        self._event_identity_set: set[bytes] = set()
        self._duplicate_events_rejected = 0
        self._last_failure: Dict[str, Any] = {}
        self._subscriptions: Dict[str, tuple[str, ...]] = {}
        self._subscription_lock = asyncio.Lock()
        self._subscription_waiter: Optional[asyncio.Future] = None
        self._pending_subscription_symbols: Optional[frozenset[str]] = None
        self._subscription_transition_allowed_symbols: Optional[frozenset[str]] = None
        self._subscription_transition_target_symbols: Optional[frozenset[str]] = None
        self._subscription_transition_events_dropped = 0
        self._fatal_truth_emitted = False

    @property
    def is_connected(self) -> bool:
        return self._connected and self._authenticated

    async def connect(self) -> bool:
        self._fatal_truth_emitted = False
        try:
            self._websocket = await self._connect_factory(
                self.ws_url,
                ping_interval=self.ping_interval,
                ping_timeout=self.ping_timeout,
                close_timeout=self.close_timeout,
            )
            connected_raw = await asyncio.wait_for(self._websocket.recv(), timeout=float(self.ping_timeout))
            if not self._success_message(connected_raw, "connected"):
                raise RuntimeError("alpaca_crypto_stream_connection_greeting_failed")
            await self._websocket.send(json.dumps({"action": "auth", "key": self._key_id, "secret": self._secret_key}))
            auth_raw = await asyncio.wait_for(self._websocket.recv(), timeout=float(self.ping_timeout))
            if not self._authentication_succeeded(auth_raw):
                raise RuntimeError("alpaca_crypto_stream_authentication_failed")
            self._authenticated = True
            await self._subscribe(self.symbols)
            subscription_raw = await asyncio.wait_for(self._websocket.recv(), timeout=float(self.ping_timeout))
            subscription_received_ns = now_ns()
            subscriptions = self._subscription_from_raw(subscription_raw)
            self._validate_subscriptions(subscriptions, expected_symbols=self.symbols)
            self._subscriptions = subscriptions
            self._connected = True
            self._last_message_time_ns = subscription_received_ns
            handshake_events = [
                message
                for message in self._decoded_messages(subscription_raw)
                if str(message.get("T") or "") != "subscription"
            ]
            if handshake_events:
                await self._process_message(handshake_events, subscription_received_ns)
            await self._emit_truth("WEBSOCKET_ACTIVE", executable_truth=False)
            return True
        except Exception as exc:
            self._connected = False
            self._authenticated = False
            websocket = self._websocket
            self._websocket = None
            if websocket is not None:
                try:
                    await websocket.close()
                except Exception:
                    pass
            try:
                await self._emit_truth("WEBSOCKET_UNAVAILABLE", exc=exc, executable_truth=False)
            except Exception:
                logger.error("Alpaca WebSocket failure callback failed: %s", exc.__class__.__name__)
            return False

    @staticmethod
    def _decoded_messages(raw: Any) -> list[Mapping[str, Any]]:
        try:
            payload = json.loads(raw) if isinstance(raw, (str, bytes, bytearray)) else raw
        except json.JSONDecodeError as exc:
            raise ValueError("alpaca_websocket_json_invalid") from exc
        messages = payload if isinstance(payload, list) else [payload]
        if not all(isinstance(item, Mapping) for item in messages):
            raise ValueError("alpaca_websocket_message_mapping_required")
        return list(messages)

    @classmethod
    def _success_message(cls, raw: Any, expected: str) -> bool:
        try:
            messages = cls._decoded_messages(raw)
        except ValueError:
            return False
        return not any(item.get("T") == "error" for item in messages) and any(
            item.get("T") == "success" and str(item.get("msg") or "").lower() == expected
            for item in messages
        )

    def _authentication_succeeded(self, raw: Any) -> bool:
        try:
            messages = self._decoded_messages(raw)
        except ValueError:
            return False
        return not any(item.get("T") == "error" for item in messages) and any(
            item.get("T") == "success"
            and str(item.get("msg") or "").lower() == "authenticated"
            for item in messages
        )

    @classmethod
    def _subscription_from_raw(cls, raw: Any) -> Dict[str, tuple[str, ...]]:
        messages = cls._decoded_messages(raw)
        error = next((item for item in messages if item.get("T") == "error"), None)
        if error is not None:
            raise RuntimeError(f"alpaca_websocket_provider_error:{error.get('code')}")
        subscription = next((item for item in messages if item.get("T") == "subscription"), None)
        if subscription is None:
            raise RuntimeError("alpaca_websocket_subscription_ack_required")
        normalized: Dict[str, tuple[str, ...]] = {}
        for channel in ("trades", "quotes", "orderbooks", "bars", "updatedBars", "dailyBars"):
            values = subscription.get(channel)
            if not isinstance(values, list) or any(not isinstance(item, str) or not item.strip() for item in values):
                raise RuntimeError("alpaca_websocket_subscription_ack_invalid")
            normalized[channel] = tuple(dict.fromkeys(item.strip().upper() for item in values))
        return normalized

    @staticmethod
    def _validate_subscriptions(
        subscriptions: Mapping[str, tuple[str, ...]],
        *,
        expected_symbols: tuple[str, ...],
    ) -> None:
        expected = set(expected_symbols)
        if any(set(subscriptions.get(channel, ())) != expected for channel in ("trades", "quotes", "orderbooks", "bars")):
            raise RuntimeError("alpaca_websocket_subscription_ack_mismatch")
        if subscriptions.get("updatedBars") or subscriptions.get("dailyBars"):
            raise RuntimeError("alpaca_websocket_unrequested_subscription_ack")

    async def _subscribe(self, symbols: tuple[str, ...]) -> None:
        if self._websocket is None or not self._authenticated:
            raise RuntimeError("alpaca_crypto_stream_not_authenticated")
        request = {
            "action": "subscribe",
            "trades": list(symbols),
            "quotes": list(symbols),
            "orderbooks": list(symbols),
            "bars": list(symbols),
        }
        await self._websocket.send(json.dumps(request))

    async def _request_subscription_change(
        self,
        *,
        action: str,
        symbols: tuple[str, ...],
        expected_symbols: tuple[str, ...],
    ) -> None:
        if self._websocket is None or not self.is_connected:
            raise RuntimeError("alpaca_crypto_stream_not_connected")
        if self._subscription_waiter is not None and not self._subscription_waiter.done():
            raise RuntimeError("alpaca_subscription_change_already_pending")
        loop = asyncio.get_running_loop()
        waiter = loop.create_future()
        self._subscription_waiter = waiter
        self._pending_subscription_symbols = frozenset(expected_symbols)
        request = {"action": action}
        for channel in ("trades", "quotes", "orderbooks", "bars"):
            request[channel] = list(symbols)
        try:
            await self._websocket.send(json.dumps(request))
            subscriptions = await asyncio.wait_for(waiter, timeout=float(self.ping_timeout))
            self._validate_subscriptions(subscriptions, expected_symbols=expected_symbols)
            self._subscriptions = dict(subscriptions)
        finally:
            if self._subscription_waiter is waiter:
                self._subscription_waiter = None
            self._pending_subscription_symbols = None

    async def update_symbols(self, symbols: List[str]) -> tuple[str, ...]:
        normalized = tuple(dict.fromkeys(str(symbol).strip().upper() for symbol in symbols if str(symbol).strip()))
        if not normalized:
            raise ValueError("alpaca_crypto_stream_symbols_required")
        async with self._subscription_lock:
            previous_order = tuple(self.symbols)
            previous = set(previous_order)
            requested = set(normalized)
            removed = tuple(sorted(previous - requested))
            added = tuple(sorted(requested - previous))
            intermediate = tuple(item for item in previous_order if item not in removed)
            self._subscription_transition_allowed_symbols = frozenset(previous | requested)
            self._subscription_transition_target_symbols = frozenset(requested)
            try:
                if removed:
                    await self._request_subscription_change(
                        action="unsubscribe",
                        symbols=removed,
                        expected_symbols=intermediate,
                    )
                    self.symbols = intermediate
                if added:
                    await self._request_subscription_change(
                        action="subscribe",
                        symbols=added,
                        expected_symbols=normalized,
                    )
                self.symbols = normalized
            except Exception as exc:
                # Provider subscription state is uncertain after any failed ack;
                # continuing would create a second, implicit symbol authority.
                self._connected = False
                self._authenticated = False
                await self._emit_truth(
                    "WEBSOCKET_SUBSCRIPTION_FAILED",
                    exc=exc,
                    executable_truth=False,
                )
                raise
            finally:
                self._subscription_transition_allowed_symbols = None
                self._subscription_transition_target_symbols = None
            for channel_symbol in tuple(self._last_event_time_ns_by_channel_symbol):
                if channel_symbol[1] in removed:
                    self._last_event_time_ns_by_channel_symbol.pop(channel_symbol, None)
            for symbol in removed:
                self._last_candle_time_ns_by_symbol.pop(symbol, None)
                self._order_book_levels_by_symbol.pop(symbol, None)
            return normalized

    async def _receive_messages(self) -> None:
        while self._running and self._connected and self._websocket is not None:
            try:
                raw = await self._websocket.recv()
                receive_ts_ns = now_ns()
                self._last_message_time_ns = receive_ts_ns
                self._messages_received += 1
                try:
                    self._message_queue.put_nowait((raw, receive_ts_ns))
                    self._queue_high_water = max(self._queue_high_water, self._message_queue.qsize())
                except asyncio.QueueFull:
                    self._queue_drops += 1
                    self._connected = False
                    self._authenticated = False
                    await self._emit_truth("WEBSOCKET_BACKPRESSURE", executable_truth=False)
                    return
            except asyncio.CancelledError:
                raise
            except (ConnectionClosed, WebSocketException, OSError) as exc:
                self._connected = False
                self._authenticated = False
                await self._emit_truth("WEBSOCKET_UNAVAILABLE", exc=exc, executable_truth=False)
                return
            except Exception as exc:
                self._connected = False
                self._authenticated = False
                await self._emit_truth("WEBSOCKET_UNAVAILABLE", exc=exc, executable_truth=False)
                return

    async def _process_queue(self) -> None:
        while self._running:
            try:
                raw, receive_ts_ns = await self._message_queue.get()
                try:
                    await self._process_message(raw, receive_ts_ns)
                finally:
                    self._message_queue.task_done()
            except asyncio.CancelledError:
                raise
            except asyncio.TimeoutError as exc:
                self._messages_rejected += 1
                self._connected = False
                self._authenticated = False
                await self._emit_truth("WEBSOCKET_SLOW_CONSUMER", exc=exc, executable_truth=False)
                return
            except Exception as exc:
                self._messages_rejected += 1
                self._connected = False
                self._authenticated = False
                await self._emit_truth("MALFORMED_WEBSOCKET_PAYLOAD", exc=exc, executable_truth=False)
                return

    async def _heartbeat_loop(self) -> None:
        while self._running and self._connected and self._websocket is not None:
            try:
                await asyncio.sleep(float(self.ping_interval))
                ping_ns = now_ns()
                pong_waiter = await self._websocket.ping()
                await asyncio.wait_for(pong_waiter, timeout=float(self.ping_timeout))
                pong_ns = now_ns()
                if self.on_health is not None:
                    result = self.on_health(ping_ns, pong_ns)
                    if asyncio.iscoroutine(result):
                        await result
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._connected = False
                self._authenticated = False
                await self._emit_truth("WEBSOCKET_UNAVAILABLE", exc=exc, executable_truth=False)
                return

    async def _process_message(self, raw: Any, receive_ts_ns: int) -> None:
        messages = self._decoded_messages(raw)
        for message in messages:
            message_type = str(message.get("T") or "")
            if message_type == "success":
                continue
            if message_type == "subscription":
                subscriptions = self._subscription_from_raw([message])
                waiter = self._subscription_waiter
                if waiter is not None and not waiter.done():
                    waiter.set_result(subscriptions)
                else:
                    self._validate_subscriptions(subscriptions, expected_symbols=self.symbols)
                    self._subscriptions = subscriptions
                continue
            if message_type == "error":
                waiter = self._subscription_waiter
                error = RuntimeError(f"alpaca_websocket_provider_error:{message.get('code')}")
                if waiter is not None and not waiter.done():
                    waiter.set_exception(error)
                raise ValueError("alpaca_websocket_provider_error")
            symbol = str(message.get("S") or "").strip().upper()
            transition_allowed = self._subscription_transition_allowed_symbols
            transition_target = self._subscription_transition_target_symbols
            permitted_symbols = transition_allowed or frozenset(self.symbols)
            if symbol not in permitted_symbols:
                raise ValueError("alpaca_websocket_unsubscribed_symbol")
            if transition_target is not None and symbol not in transition_target:
                # An unsubscribe acknowledgement cannot prevent an already
                # queued event for the removed symbol. It is known transition
                # traffic, but it must not reach the new deep-universe owner.
                self._subscription_transition_events_dropped += 1
                continue
            identity = hashlib.sha256(
                json.dumps(message, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
            ).digest()
            if identity in self._event_identity_set:
                self._duplicate_events_rejected += 1
                continue
            event_ts_ns = self._parse_rfc3339_ns(message.get("t"))
            if event_ts_ns > receive_ts_ns:
                raise ValueError("alpaca_websocket_future_event_refused")
            if message_type in {"t", "q"} and receive_ts_ns - event_ts_ns > int(
                self.quote_freshness_policy_ms * 1_000_000.0
            ):
                raise ValueError("alpaca_websocket_stale_quote_or_trade_refused")
            if message_type == "o" and receive_ts_ns - event_ts_ns > int(
                self.order_book_freshness_policy_ms * 1_000_000.0
            ):
                raise ValueError("alpaca_websocket_stale_order_book_refused")
            channel_key = (message_type, symbol)
            previous = self._last_event_time_ns_by_channel_symbol.get(channel_key, 0)
            if event_ts_ns < previous:
                raise ValueError("alpaca_websocket_out_of_order_event")
            if message_type == "t":
                trade = {
                    "symbol": symbol,
                    "price": self._positive_float(message.get("p"), "trade_price"),
                    "volume": self._positive_float(message.get("s"), "trade_size"),
                    "side": self._taker_side_direction(message.get("tks")),
                    "exchange_ts_ns": event_ts_ns,
                    "receive_ts_ns": receive_ts_ns,
                    "trade_id": str(message.get("i") or ""),
                    "provider_id": "alpaca_crypto_stream",
                    "execution_location": "alpaca",
                }
                await self._callback(self.on_trade, trade)
            elif message_type == "q":
                bid = self._positive_float(message.get("bp"), "bid_price")
                ask = self._positive_float(message.get("ap"), "ask_price")
                if bid >= ask:
                    raise ValueError("alpaca_crossed_or_locked_quote_refused")
                quote = {
                    "symbol": symbol,
                    "bid": bid,
                    "ask": ask,
                    "bid_size": self._nonnegative_float(message.get("bs"), "bid_size"),
                    "ask_size": self._nonnegative_float(message.get("as"), "ask_size"),
                    "exchange_ts_ns": event_ts_ns,
                    "receive_ts_ns": receive_ts_ns,
                    "provider_id": "alpaca_crypto_stream",
                    "execution_location": "alpaca",
                }
                await self._callback(self.on_quote, quote)
            elif message_type == "o":
                book, candidate_levels = self._build_order_book_snapshot(
                    message,
                    symbol=symbol,
                    event_ts_ns=event_ts_ns,
                    receive_ts_ns=receive_ts_ns,
                )
                await self._callback(self.on_order_book, book)
                self._order_book_levels_by_symbol[symbol] = candidate_levels
            elif message_type == "b":
                if event_ts_ns <= self._last_candle_time_ns_by_symbol.get(symbol, 0):
                    raise ValueError("alpaca_duplicate_or_out_of_order_candle")
                candle_close_ts_ns = event_ts_ns + 60_000_000_000
                if candle_close_ts_ns > receive_ts_ns:
                    raise ValueError("alpaca_in_progress_minute_bar_refused")
                if receive_ts_ns - candle_close_ts_ns > int(self.candle_freshness_policy_ms * 1_000_000.0):
                    raise ValueError("alpaca_websocket_stale_closed_minute_bar_refused")
                await self._callback(
                    self.on_candle,
                    Candle(
                        symbol=symbol,
                        exchange_ts_ns=event_ts_ns,
                        open=self._positive_float(message.get("o"), "bar_open"),
                        high=self._positive_float(message.get("h"), "bar_high"),
                        low=self._positive_float(message.get("l"), "bar_low"),
                        close=self._positive_float(message.get("c"), "bar_close"),
                        volume=self._nonnegative_float(message.get("v"), "bar_volume"),
                        timeframe="1m",
                        data_source_type="runtime",
                        provider_id="alpaca_crypto_stream",
                        latest_batch_candle=True,
                        latest_provider_batch_candle=True,
                        latest_closed_batch_candle=True,
                        provider_batch_head_ts_ns=event_ts_ns,
                        candle_close_ts_ns=candle_close_ts_ns,
                        candle_closed_at_receive=True,
                        candle_batch_received_ns=receive_ts_ns,
                        candle_freshness_policy_ms=self.candle_freshness_policy_ms,
                    ),
                )
            else:
                raise ValueError("alpaca_websocket_message_type_unsupported")
            self._last_event_time_ns_by_channel_symbol[channel_key] = event_ts_ns
            if message_type == "b":
                self._last_candle_time_ns_by_symbol[symbol] = event_ts_ns
            self._event_identities.append(identity)
            self._event_identity_set.add(identity)
            if len(self._event_identities) > self.dedupe_history_size:
                expired = self._event_identities.popleft()
                self._event_identity_set.discard(expired)
            self._messages_processed += 1

    async def _callback(self, callback: Optional[Callable], value: Any) -> None:
        if callback is None:
            return
        started = time.monotonic()
        result = callback(value)
        if asyncio.iscoroutine(result):
            result = await asyncio.wait_for(result, timeout=self.callback_timeout_seconds)
        elif time.monotonic() - started > self.callback_timeout_seconds:
            raise asyncio.TimeoutError("alpaca_websocket_callback_timeout")
        if result is False:
            raise ValueError("alpaca_websocket_callback_rejected")

    async def _emit_truth(self, status: str, *, exc: Optional[Exception] = None, executable_truth: bool) -> None:
        terminal = status != "WEBSOCKET_ACTIVE"
        if terminal and self._fatal_truth_emitted:
            return
        if terminal:
            self._fatal_truth_emitted = True
        truth = {
            "status": status,
            "provider_id": "alpaca_crypto_stream",
            "execution_location": "alpaca",
            "transport_adapter": "alpaca_crypto_websocket",
            "connected": self._connected,
            "authenticated": self._authenticated,
            "transport_active": self.is_connected,
            "executable_truth": bool(executable_truth and self.is_connected),
            "timestamp_ns": now_ns(),
            "exception_type": exc.__class__.__name__ if exc is not None else None,
        }
        if terminal:
            self._last_failure = truth
        if self.on_feed_truth:
            await self._callback(self.on_feed_truth, truth)

    @staticmethod
    def _parse_rfc3339_ns(value: Any) -> int:
        if not value:
            raise ValueError("alpaca_source_timestamp_required")
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
                raise ValueError("alpaca_source_timestamp_fraction_invalid")
            fraction_ns = int(fraction.ljust(9, "0"))
            main = f"{prefix}{offset}"
        parsed = datetime.fromisoformat(main)
        if parsed.tzinfo is None:
            raise ValueError("alpaca_source_timestamp_timezone_required")
        parsed_utc = parsed.astimezone(timezone.utc)
        return calendar.timegm(parsed_utc.utctimetuple()) * 1_000_000_000 + fraction_ns

    @staticmethod
    def _positive_float(value: Any, field_name: str) -> float:
        if isinstance(value, bool):
            raise ValueError(f"{field_name}_numeric_required")
        parsed = float(value)
        if not math.isfinite(parsed) or parsed <= 0:
            raise ValueError(f"{field_name}_positive_finite_required")
        return parsed

    @staticmethod
    def _nonnegative_float(value: Any, field_name: str) -> float:
        if isinstance(value, bool):
            raise ValueError(f"{field_name}_numeric_required")
        parsed = float(value)
        if not math.isfinite(parsed) or parsed < 0:
            raise ValueError(f"{field_name}_nonnegative_finite_required")
        return parsed

    @staticmethod
    def _taker_side_direction(value: Any) -> int:
        if not isinstance(value, str):
            raise ValueError("alpaca_trade_taker_side_required")
        side = value.strip().upper()
        if side == "B":
            return 1
        if side == "S":
            return -1
        raise ValueError("alpaca_trade_taker_side_invalid")

    @staticmethod
    def _book_decimal(value: Any, field_name: str, *, allow_zero: bool) -> Decimal:
        if isinstance(value, bool):
            raise ValueError(f"{field_name}_numeric_required")
        try:
            parsed = Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise ValueError(f"{field_name}_numeric_required") from exc
        if not parsed.is_finite() or parsed < 0 or (not allow_zero and parsed == 0):
            qualifier = "nonnegative_finite" if allow_zero else "positive_finite"
            raise ValueError(f"{field_name}_{qualifier}_required")
        return parsed

    @classmethod
    def _parse_book_updates(cls, value: Any) -> tuple[tuple[Decimal, Decimal], ...]:
        if not isinstance(value, list):
            raise ValueError("alpaca_order_book_levels_list_required")
        updates: list[tuple[Decimal, Decimal]] = []
        for item in value:
            if not isinstance(item, Mapping):
                raise ValueError("alpaca_order_book_level_mapping_required")
            updates.append(
                (
                    cls._book_decimal(item.get("p"), "level_price", allow_zero=False),
                    cls._book_decimal(item.get("s"), "level_size", allow_zero=True),
                )
            )
        return tuple(updates)

    def _build_order_book_snapshot(
        self,
        message: Mapping[str, Any],
        *,
        symbol: str,
        event_ts_ns: int,
        receive_ts_ns: int,
    ) -> tuple[OrderBookSnapshot, Dict[str, Dict[Decimal, Decimal]]]:
        reset_value = message.get("r", False)
        if type(reset_value) is not bool:
            raise ValueError("alpaca_order_book_reset_flag_invalid")
        previous = self._order_book_levels_by_symbol.get(symbol)
        if not reset_value and previous is None:
            raise ValueError("alpaca_order_book_incremental_before_reset")
        candidate = {
            "bids": {} if reset_value else dict(previous["bids"]),
            "asks": {} if reset_value else dict(previous["asks"]),
        }
        for side_name, field_name in (("bids", "b"), ("asks", "a")):
            for price, size in self._parse_book_updates(message.get(field_name)):
                if size == 0:
                    candidate[side_name].pop(price, None)
                else:
                    candidate[side_name][price] = size
        candidate["bids"] = dict(
            sorted(candidate["bids"].items(), key=lambda item: item[0], reverse=True)[
                : self.order_book_level_limit
            ]
        )
        candidate["asks"] = dict(
            sorted(candidate["asks"].items(), key=lambda item: item[0])[
                : self.order_book_level_limit
            ]
        )
        if not candidate["bids"] or not candidate["asks"]:
            raise ValueError("alpaca_order_book_two_sided_truth_required")
        best_bid = next(iter(candidate["bids"]))
        best_ask = next(iter(candidate["asks"]))
        if best_bid >= best_ask:
            raise ValueError("alpaca_order_book_invalid_or_crossed")
        book = OrderBookSnapshot(
            symbol=symbol,
            exchange_ts_ns=event_ts_ns,
            receive_ts_ns=receive_ts_ns,
            bids=[(float(price), float(size)) for price, size in candidate["bids"].items()],
            asks=[(float(price), float(size)) for price, size in candidate["asks"].items()],
        )
        return book, candidate

    def _parse_levels(self, value: Any, *, reverse: bool) -> List[Tuple[float, float]]:
        if not isinstance(value, list):
            return []
        levels: list[Tuple[float, float]] = []
        for item in value:
            if not isinstance(item, Mapping):
                return []
            levels.append((self._positive_float(item.get("p"), "level_price"), self._positive_float(item.get("s"), "level_size")))
        return sorted(levels, key=lambda item: item[0], reverse=reverse)[:50]

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        if not await self.connect():
            self._running = False
            raise RuntimeError("alpaca_crypto_stream_start_failed")
        self._tasks = [
            asyncio.create_task(self._receive_messages()),
            asyncio.create_task(self._process_queue()),
            asyncio.create_task(self._heartbeat_loop()),
        ]

    async def stop(self) -> None:
        self._running = False
        self._connected = False
        self._authenticated = False
        waiter = self._subscription_waiter
        if waiter is not None and not waiter.done():
            waiter.cancel()
        self._subscription_waiter = None
        self._pending_subscription_symbols = None
        self._subscription_transition_allowed_symbols = None
        self._subscription_transition_target_symbols = None
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        if self._websocket is not None:
            await self._websocket.close()
        self._websocket = None
        while True:
            try:
                self._message_queue.get_nowait()
                self._message_queue.task_done()
            except asyncio.QueueEmpty:
                break
        self._subscriptions = {}
        self._last_event_time_ns_by_channel_symbol.clear()
        self._last_candle_time_ns_by_symbol.clear()
        self._order_book_levels_by_symbol.clear()
        self._event_identities.clear()
        self._event_identity_set.clear()

    def get_feed_truth_status(self) -> Dict[str, Any]:
        return {
            "status": "WEBSOCKET_ACTIVE" if self.is_connected else "WEBSOCKET_INACTIVE",
            "provider_id": "alpaca_crypto_stream",
            "execution_location": "alpaca",
            "endpoint": self.ws_url,
            "connected": self._connected,
            "authenticated": self._authenticated,
            "transport_active": self.is_connected,
            "executable_truth": False,
            "symbols": self.symbols,
            "subscriptions": dict(self._subscriptions),
            "subscription_transition_events_dropped": self._subscription_transition_events_dropped,
            "messages_received": self._messages_received,
            "messages_processed": self._messages_processed,
            "messages_rejected": self._messages_rejected,
            "duplicate_events_rejected": self._duplicate_events_rejected,
            "dedupe_history_size": len(self._event_identities),
            "dedupe_history_limit": self.dedupe_history_size,
            "order_book_level_limit": self.order_book_level_limit,
            "quote_freshness_policy_ms": self.quote_freshness_policy_ms,
            "order_book_freshness_policy_ms": self.order_book_freshness_policy_ms,
            "candle_freshness_policy_ms": self.candle_freshness_policy_ms,
            "queue_size": self._message_queue.qsize(),
            "queue_high_water": self._queue_high_water,
            "queue_drops": self._queue_drops,
            "last_message_time_ns": self._last_message_time_ns,
            "last_failure": dict(self._last_failure),
        }


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
