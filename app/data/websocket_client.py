"""
WebSocket Client - Kraken Real-Time Market Data Connector
Async WebSocket client with Sovereign Grade features:
- Auto-reconnect with exponential backoff
- Heartbeat monitoring with SovereignSentinel integration
- Backpressure handling with bounded queue
- Kraken-specific subscription and message parsing
- L2 order book and trade feed
"""

import asyncio
import json
import logging
import time
import threading
from typing import Dict, List, Optional, Callable, Any, Tuple
from datetime import datetime
from collections import deque

import websockets
from websockets.exceptions import ConnectionClosed, WebSocketException

from app.models import Candle, OrderBookSnapshot

logger = logging.getLogger(__name__)


class KrakenWebSocketClient:
    """
    Sovereign WebSocket client for Kraken exchange.
    
    Features:
    - Async connection with automatic reconnection
    - Exponential backoff (1s, 2s, 4s, 8s, 16s, max 30s)
    - Heartbeat monitoring with external sentinel
    - Backpressure handling with bounded queue
    - Real-time order book and trade subscriptions
    - Message parsing with validation
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
        
        # Lag monitoring
        self._processing_lag = deque(maxlen=100)
        self._last_message_time = 0.0
        self._last_heartbeat_sent = 0.0
        
        # Subscription status
        self._subscriptions: Dict[str, List[str]] = {}
        
        # Message counters for sequence detection
        self._sequence_counters: Dict[str, int] = {}
        
        logger.info(f"KrakenWebSocketClient initialized: {len(symbols)} symbols")
    
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
            self._last_message_time = time.time()
            self._last_heartbeat_sent = time.time()
            
            # Send initial ping to Kraken (optional, but good practice)
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
                self._last_heartbeat_sent = time.time()
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
                now = time.time()
                time_since_last_message = now - self._last_message_time
                
                if time_since_last_message > 60:
                    logger.warning(f"No messages for {time_since_last_message:.1f}s - connection may be stale")
                    
                    # Alert sentinel if available
                    if self.sentinel:
                        self.sentinel.alert_exchange_outage("kraken", time_since_last_message)
                    
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
                received_at = time.time()
                self._last_message_time = received_at
                
                # Queue message with timestamp
                try:
                    await self._message_queue.put((message, received_at))
                except asyncio.QueueFull:
                    # Backpressure detected - drop message
                    lag = self._calculate_lag()
                    logger.error(f"Queue full! Dropping message. Lag: {lag:.2f}s")
                    
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
        stale_threshold = 30  # seconds
        
        while self._running:
            try:
                message, received_at = await self._message_queue.get()
                
                # Calculate processing lag
                lag = time.time() - received_at
                self._processing_lag.append(lag)
                
                # Check for stale data
                if lag > stale_threshold:
                    logger.warning(f"Stale message detected: {lag:.2f}s lag")
                    continue
                
                # Process message
                await self._process_message(message)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error processing message: {e}")
    
    async def _process_message(self, raw_message: str) -> None:
        """
        Process a single WebSocket message.

        Args:
            raw_message: Raw WebSocket message
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
                await self._parse_order_book(data)
            elif channel == "trade":
                await self._parse_trade(data)
            elif channel == "candle":
                await self._parse_candle(data)
            else:
                logger.debug(f"Unknown channel: {channel}")
                
        except json.JSONDecodeError as e:
            logger.error(f"JSON decode error: {e}")
        except Exception as e:
            logger.error(f"Message processing error: {e}")
    
    # ============================================
    # MESSAGE PARSING
    # ============================================
    
    async def _parse_order_book(self, data: Dict) -> None:
        """
        Parse order book message from Kraken.

        Args:
            data: Raw message data
        """
        try:
            symbol = data.get("symbol", "")
            timestamp_ms = data.get("timestamp", 0)
            timestamp = datetime.fromtimestamp(timestamp_ms / 1000.0) if timestamp_ms else datetime.utcnow()
            exchange_ts_ns = int(timestamp_ms * 1_000_000) if timestamp_ms else int(time.time() * 1_000_000_000)
            
            # Parse bids and asks
            bids = []
            asks = []
            
            book_data = data.get("data", {})
            for bid in book_data.get("bids", []):
                bids.append((float(bid.get("price", 0)), float(bid.get("qty", 0))))
            for ask in book_data.get("asks", []):
                asks.append((float(ask.get("price", 0)), float(ask.get("qty", 0))))
            
            if not bids and not asks:
                return
            
            # Create snapshot
            snapshot = OrderBookSnapshot(
                symbol=symbol,
                timestamp=timestamp,
                bids=bids[:50],
                asks=asks[:50]
            )
            snapshot.exchange_ts_ns = exchange_ts_ns
            
            # Call callback
            if self.on_order_book:
                if asyncio.iscoroutinefunction(self.on_order_book):
                    await self.on_order_book(snapshot)
                else:
                    self.on_order_book(snapshot)
                    
        except Exception as e:
            logger.error(f"Failed to parse order book: {e}")
    
    async def _parse_trade(self, data: Dict) -> None:
        """
        Parse trade message from Kraken.

        Args:
            data: Raw message data
        """
        try:
            symbol = data.get("symbol", "")
            timestamp_ms = data.get("timestamp", 0)
            exchange_ts_ns = int(timestamp_ms * 1_000_000) if timestamp_ms else int(time.time() * 1_000_000_000)
            
            for trade_data in data.get("data", []):
                price = float(trade_data.get("price", 0))
                volume = float(trade_data.get("qty", 0))
                side = trade_data.get("side", "buy")
                
                trade_info = {
                    "symbol": symbol,
                    "price": price,
                    "volume": volume,
                    "side": side,
                    "timestamp_ns": exchange_ts_ns,
                    "trade_id": trade_data.get("trade_id", "")
                }
                
                # Call callback
                if self.on_trade:
                    if asyncio.iscoroutinefunction(self.on_trade):
                        await self.on_trade(trade_info)
                    else:
                        self.on_trade(trade_info)
                        
        except Exception as e:
            logger.error(f"Failed to parse trade: {e}")
    
    async def _parse_candle(self, data: Dict) -> None:
        """
        Parse candle message from Kraken.

        Args:
            data: Raw message data
        """
        try:
            symbol = data.get("symbol", "")
            timestamp_ms = data.get("timestamp", 0)
            timestamp = datetime.fromtimestamp(timestamp_ms / 1000.0) if timestamp_ms else datetime.utcnow()
            exchange_ts_ns = int(timestamp_ms * 1_000_000) if timestamp_ms else int(time.time() * 1_000_000_000)
            
            for candle_data in data.get("data", []):
                candle = Candle(
                    symbol=symbol,
                    timestamp=timestamp,
                    open=float(candle_data.get("open", 0)),
                    high=float(candle_data.get("high", 0)),
                    low=float(candle_data.get("low", 0)),
                    close=float(candle_data.get("close", 0)),
                    volume=float(candle_data.get("volume", 0)),
                    timeframe="1m"
                )
                candle.exchange_ts_ns = exchange_ts_ns
                
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
    
    def _calculate_lag(self) -> float:
        """Calculate average processing lag."""
        if not self._processing_lag:
            return 0.0
        return sum(self._processing_lag) / len(self._processing_lag)
    
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
            "avg_lag_ms": self._calculate_lag() * 1000,
            "last_message_time": self._last_message_time,
            "symbols_subscribed": len(self.symbols),
            "subscriptions": self._subscriptions
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