"""
WebSocket Client - Kraken Real-Time Market Data Connector
Async WebSocket client with Sovereign Grade features:
- Auto-reconnect with exponential backoff
- Heartbeat monitoring with SovereignSentinel integration
- Backpressure handling with bounded queue
- Kraken-specific subscription and message parsing
- L2 order book and trade feed

TIMESTAMP TRUTH (STRICT AUTHORITATIVE PATH):
- exchange_ts_ns MUST come from exchange timestamp_ms
- Messages WITHOUT timestamp_ms are REJECTED (dropped, logged)
- No wall-clock substitution for authoritative timestamps
- receive_ts_ns captured for telemetry only (not passed to canonical models)
"""

import asyncio
import json
import logging
import time
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
    - exchange_ts_ns extracted from Kraken message timestamp_ms
    - Messages missing timestamp_ms are REJECTED (not fabricated)
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
        sentinel: Optional[Any] = None
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
        
        # Statistics
        self._messages_received = 0
        self._messages_rejected_no_timestamp = 0
        self._messages_processed = 0
        
        logger.info(f"KrakenWebSocketClient initialized: {len(symbols)} symbols")
        logger.info("  TIMESTAMP TRUTH: Strict authoritative path — messages without exchange timestamp are REJECTED")
    
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
        
        # Subscribe to candle channel (1 minute)
        candle_msg = {
            "method": "subscribe",
            "params": {
                "channel": "candle",
                "symbol": self.symbols,
                "interval": 1
            }
        }
        await self._websocket.send(json.dumps(candle_msg))
        logger.info(f"Subscribed to candles for {len(self.symbols)} symbols")
        
        # Record subscriptions
        self._subscriptions = {
            "book": self.symbols.copy(),
            "trade": self.symbols.copy(),
            "candle": self.symbols.copy()
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
            elif channel == "candle":
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
    
    def _extract_exchange_timestamp_ns(self, data: Dict, channel_type: str) -> Optional[int]:
        """
        Extract authoritative exchange timestamp from message.
        
        Returns:
            exchange_ts_ns if valid, None otherwise
        
        STRICT RULE: If exchange does not provide timestamp_ms, return None.
        NO FALLBACK to local time. Messages without timestamp are REJECTED.
        """
        timestamp_ms = data.get("timestamp")
        
        if timestamp_ms is None:
            logger.warning(f"Missing timestamp_ms in {channel_type} message — rejecting")
            self._messages_rejected_no_timestamp += 1
            return None
        
        if not isinstance(timestamp_ms, (int, float)) or timestamp_ms <= 0:
            logger.warning(f"Invalid timestamp_ms in {channel_type} message: {timestamp_ms} — rejecting")
            self._messages_rejected_no_timestamp += 1
            return None
        
        return int(timestamp_ms * 1_000_000)
    
    async def _parse_order_book(self, data: Dict, receive_ts_ns: int) -> None:
        """
        Parse order book message from Kraken.
        
        STRICT AUTHORITATIVE PATH:
        - exchange_ts_ns MUST come from message timestamp_ms
        - Missing or invalid timestamp → message REJECTED
        """
        try:
            symbol = data.get("symbol", "")
            if not symbol:
                logger.warning("Order book message missing symbol — rejecting")
                return
            
            # Extract authoritative timestamp — strict
            exchange_ts_ns = self._extract_exchange_timestamp_ns(data, "order_book")
            if exchange_ts_ns is None:
                return  # Message rejected, already logged
            
            # Parse bids and asks
            bids = []
            asks = []
            
            book_data = data.get("data", {})
            for bid in book_data.get("bids", []):
                bids.append((float(bid.get("price", 0)), float(bid.get("qty", 0))))
            for ask in book_data.get("asks", []):
                asks.append((float(ask.get("price", 0)), float(ask.get("qty", 0))))
            
            if not bids and not asks:
                logger.debug(f"Empty order book for {symbol} — skipping")
                return
            
            # Create snapshot using canonical OrderBookSnapshot
            snapshot = OrderBookSnapshot(
                symbol=symbol,
                exchange_ts_ns=exchange_ts_ns,
                bids=bids[:50],
                asks=asks[:50]
            )
            
            self._messages_processed += 1
            
            # Call callback
            if self.on_order_book:
                if asyncio.iscoroutinefunction(self.on_order_book):
                    await self.on_order_book(snapshot)
                else:
                    self.on_order_book(snapshot)
                    
        except Exception as e:
            logger.error(f"Failed to parse order book: {e}")
    
    async def _parse_trade(self, data: Dict, receive_ts_ns: int) -> None:
        """
        Parse trade message from Kraken.
        
        STRICT AUTHORITATIVE PATH:
        - exchange_ts_ns MUST come from message timestamp_ms
        - Missing or invalid timestamp → message REJECTED
        """
        try:
            symbol = data.get("symbol", "")
            if not symbol:
                logger.warning("Trade message missing symbol — rejecting")
                return
            
            # Extract authoritative timestamp — strict
            exchange_ts_ns = self._extract_exchange_timestamp_ns(data, "trade")
            if exchange_ts_ns is None:
                return  # Message rejected, already logged
            
            for trade_data in data.get("data", []):
                price = float(trade_data.get("price", 0))
                volume = float(trade_data.get("qty", 0))
                side_str = trade_data.get("side", "buy")
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
                
                # Call callback
                if self.on_trade:
                    if asyncio.iscoroutinefunction(self.on_trade):
                        await self.on_trade(trade_info)
                    else:
                        self.on_trade(trade_info)
                        
        except Exception as e:
            logger.error(f"Failed to parse trade: {e}")
    
    async def _parse_candle(self, data: Dict, receive_ts_ns: int) -> None:
        """
        Parse candle message from Kraken.
        
        STRICT AUTHORITATIVE PATH:
        - exchange_ts_ns MUST come from message timestamp_ms
        - Missing or invalid timestamp → message REJECTED
        """
        try:
            symbol = data.get("symbol", "")
            if not symbol:
                logger.warning("Candle message missing symbol — rejecting")
                return
            
            # Extract authoritative timestamp — strict
            exchange_ts_ns = self._extract_exchange_timestamp_ns(data, "candle")
            if exchange_ts_ns is None:
                return  # Message rejected, already logged
            
            for candle_data in data.get("data", []):
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
                
                self._messages_processed += 1
                
                # Call callback
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
    sentinel: Optional[Any] = None
) -> KrakenWebSocketClient:
    """
    Factory function to create a configured Kraken WebSocket client.

    Args:
        symbols: List of symbols to subscribe to
        on_order_book: Callback for order book updates
        on_trade: Callback for trade updates
        on_candle: Callback for candle updates
        sentinel: SovereignSentinel instance for monitoring

    Returns:
        Configured KrakenWebSocketClient
    """
    return KrakenWebSocketClient(
        symbols=symbols,
        on_order_book=on_order_book,
        on_trade=on_trade,
        on_candle=on_candle,
        sentinel=sentinel
    )