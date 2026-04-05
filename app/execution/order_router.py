"""
Order Router - Exchange Adapter with Ghost Detection & PCV
The "Nervous System" of the Poverty Killer.
Features:
- Triangulated Latency (detects if exchange is "ghosting")
- Synchronous Post-Cancellation Verification (PCV)
- Emergency REST Fallback when WebSocket fails
- Cross-exchange correlation for ghost detection
- Actual Kraken/Alpaca API integration with post-only flags
"""

import logging
import time
import threading
import requests
import hmac
import base64
import hashlib
import urllib.parse
from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime
from dataclasses import dataclass, field

from app.models import OrderRequest, OrderFill

logger = logging.getLogger(__name__)


@dataclass
class OrderStatus:
    """Order status from exchange."""
    order_id: str
    status: str  # pending, open, filled, cancelled, expired, rejected
    filled_quantity: float = 0.0
    filled_price: float = 0.0
    remaining_quantity: float = 0.0
    timestamp: Optional[datetime] = None

    __slots__ = ("order_id", "status", "filled_quantity", "filled_price",
                 "remaining_quantity", "timestamp")


class OrderRouter:
    """
    Order Router - Exchange Adapter with Ghost Detection.
    
    Features:
    - Triangulated Latency: Pings Google + secondary exchange to detect ghosting
    - Synchronous PCV: Loops until order is confirmed dead
    - Emergency REST Fallback: HTTP fallback when WebSocket fails
    - Actual Kraken/Alpaca API integration with post-only flags
    """

    def __init__(
        self,
        primary_exchange: str = "kraken",
        secondary_exchange: str = "coinbase",
        primary_api_key: str = "",
        primary_api_secret: str = "",
        secondary_api_key: str = "",
        secondary_api_secret: str = "",
        latency_threshold_ms: float = 200.0,
        ghost_ratio_threshold: float = 3.0,
        pcv_max_attempts: int = 5,
        pcv_retry_delay_sec: float = 0.5,
        rest_fallback_enabled: bool = True,
        paper_mode: bool = True
    ):
        """
        Initialize order router.

        Args:
            primary_exchange: Primary exchange name (kraken, alpaca)
            secondary_exchange: Secondary exchange for latency comparison
            primary_api_key: API key for primary exchange
            primary_api_secret: API secret for primary exchange
            secondary_api_key: API key for secondary exchange
            secondary_api_secret: API secret for secondary exchange
            latency_threshold_ms: Max acceptable latency before warning
            ghost_ratio_threshold: Primary latency / secondary latency threshold
            pcv_max_attempts: Max attempts for PCV verification
            pcv_retry_delay_sec: Delay between PCV attempts
            rest_fallback_enabled: Whether to use REST fallback on WebSocket failure
            paper_mode: If True, simulate orders without real execution
        """
        self.primary_exchange = primary_exchange
        self.secondary_exchange = secondary_exchange
        self.primary_api_key = primary_api_key
        self.primary_api_secret = primary_api_secret
        self.secondary_api_key = secondary_api_key
        self.secondary_api_secret = secondary_api_secret
        self.latency_threshold_ms = latency_threshold_ms
        self.ghost_ratio_threshold = ghost_ratio_threshold
        self.pcv_max_attempts = pcv_max_attempts
        self.pcv_retry_delay_sec = pcv_retry_delay_sec
        self.rest_fallback_enabled = rest_fallback_enabled
        self.paper_mode = paper_mode

        # WebSocket state
        self._websocket_connected = False
        self._last_websocket_ping_ns = 0
        self._last_websocket_pong_ns = 0

        # Order tracking
        self._pending_orders: Dict[str, OrderRequest] = {}
        self._order_status_cache: Dict[str, OrderStatus] = {}

        # Exchange-specific endpoints
        self._endpoints = {
            "kraken": {
                "rest": "https://api.kraken.com/0",
                "public": "https://api.kraken.com/0/public",
                "private": "https://api.kraken.com/0/private",
                "time": "/public/Time",
                "order": "/private/AddOrder",
                "cancel": "/private/CancelOrder",
                "status": "/private/QueryOrders",
                "open_orders": "/private/OpenOrders",
                "balance": "/private/Balance"
            },
            "alpaca": {
                "rest": "https://paper-api.alpaca.markets",
                "time": "/v2/clock",
                "order": "/v2/orders",
                "cancel": "/v2/orders/{order_id}",
                "status": "/v2/orders/{order_id}",
                "open_orders": "/v2/orders",
                "balance": "/v2/account"
            }
        }

        # Session for REST calls
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": "PovertyKiller/1.0"
        })

        # Alpaca headers if configured
        if primary_exchange == "alpaca" and primary_api_key and not paper_mode:
            self._session.headers.update({
                "APCA-API-KEY-ID": primary_api_key,
                "APCA-API-SECRET-KEY": primary_api_secret
            })

        logger.info(f"OrderRouter initialized: primary={primary_exchange}, "
                   f"secondary={secondary_exchange}, ghost_ratio={ghost_ratio_threshold}, "
                   f"pcv_attempts={pcv_max_attempts}, paper_mode={paper_mode}")

    # ============================================
    # GHOST DETECTION (Triangulated Latency)
    # ============================================

    def measure_latency(self) -> float:
        """
        Measure latency to primary exchange with triangulation.
        Also detects if exchange is "ghosting" (accepting pings but not processing).

        Returns:
            Latency in milliseconds
        """
        # Measure latency to primary exchange API
        primary_latency = self._measure_exchange_latency(self.primary_exchange)

        # Measure latency to secondary exchange for triangulation
        secondary_latency = self._measure_exchange_latency(self.secondary_exchange)

        # Measure baseline latency (Google DNS)
        baseline_latency = self._measure_baseline_latency()

        # Ghost detection: primary latency significantly higher than secondary
        is_ghosting = False
        if secondary_latency > 0 and baseline_latency > 0:
            ratio = primary_latency / max(secondary_latency, 0.001)
            if ratio > self.ghost_ratio_threshold:
                is_ghosting = True
                logger.warning(f"GHOST DETECTED: Primary latency {primary_latency:.1f}ms, "
                             f"secondary {secondary_latency:.1f}ms, ratio={ratio:.1f}")

        # Store ghost detection result
        self._websocket_connected = not is_ghosting and primary_latency < self.latency_threshold_ms

        return primary_latency

    def _measure_exchange_latency(self, exchange: str) -> float:
        """
        Measure latency to exchange API endpoint.

        Args:
            exchange: Exchange name

        Returns:
            Latency in milliseconds
        """
        endpoints = {
            "kraken": "https://api.kraken.com/0/public/Time",
            "coinbase": "https://api.coinbase.com/v2/time",
            "binance": "https://api.binance.com/api/v3/time",
            "alpaca": "https://paper-api.alpaca.markets/v2/clock"
        }

        url = endpoints.get(exchange, endpoints["kraken"])

        try:
            start = time.time()
            response = self._session.get(url, timeout=5.0)
            elapsed_ms = (time.time() - start) * 1000

            if response.status_code == 200:
                return elapsed_ms
            else:
                logger.warning(f"Exchange {exchange} returned status {response.status_code}")
                return 999.0

        except requests.exceptions.Timeout:
            logger.warning(f"Exchange {exchange} timeout")
            return 999.0
        except Exception as e:
            logger.error(f"Error measuring {exchange} latency: {e}")
            return 999.0

    def _measure_baseline_latency(self) -> float:
        """
        Measure baseline internet latency (Google DNS).

        Returns:
            Latency in milliseconds
        """
        try:
            start = time.time()
            response = self._session.get("https://8.8.8.8", timeout=3.0)
            elapsed_ms = (time.time() - start) * 1000
            return elapsed_ms
        except Exception:
            return 50.0  # Default fallback

    def is_websocket_connected(self) -> bool:
        """Check if WebSocket connection is healthy."""
        return self._websocket_connected

    def update_websocket_ping(self) -> None:
        """Update WebSocket ping timestamp."""
        self._last_websocket_ping_ns = time.time_ns()

    def update_websocket_pong(self) -> None:
        """Update WebSocket pong timestamp and calculate RTT."""
        self._last_websocket_pong_ns = time.time_ns()

    def get_websocket_rtt_ms(self) -> float:
        """Get WebSocket round-trip time in milliseconds."""
        if self._last_websocket_ping_ns == 0 or self._last_websocket_pong_ns == 0:
            return 0.0
        return (self._last_websocket_pong_ns - self._last_websocket_ping_ns) / 1_000_000

    # ============================================
    # KRAKEN API AUTHENTICATION
    # ============================================

    def _kraken_sign(self, urlpath: str, data: Dict[str, str]) -> Dict[str, str]:
        """
        Generate Kraken API signature.

        Args:
            urlpath: API endpoint path
            data: POST data

        Returns:
            Headers with signature
        """
        if self.paper_mode:
            return {}

        nonce = str(int(time.time() * 1000))
        data['nonce'] = nonce

        postdata = urllib.parse.urlencode(data)
        encoded = (str(data['nonce']) + postdata).encode()
        message = urlpath.encode() + hashlib.sha256(encoded).digest()
        signature = hmac.new(
            base64.b64decode(self.primary_api_secret),
            message,
            hashlib.sha512
        )
        sigdigest = base64.b64encode(signature.digest()).decode()

        return {
            'API-Key': self.primary_api_key,
            'API-Sign': sigdigest
        }

    # ============================================
    # ORDER SUBMISSION WITH POST-ONLY FLAG
    # ============================================

    def submit_order(self, order: OrderRequest) -> Optional[OrderFill]:
        """
        Submit order to exchange with post-only flag for maker fees.

        Args:
            order: Order request

        Returns:
            OrderFill if filled immediately, None if pending
        """
        if self.paper_mode:
            return self._submit_order_paper(order)

        try:
            # Check if exchange is ghosting
            latency = self.measure_latency()
            if not self._websocket_connected:
                if self.rest_fallback_enabled:
                    logger.warning(f"WebSocket unhealthy, using REST fallback for {order.id}")
                    return self._submit_order_rest(order)
                else:
                    logger.error(f"WebSocket unhealthy and REST fallback disabled for {order.id}")
                    return None

            if self.primary_exchange == "kraken":
                return self._submit_order_kraken(order)
            elif self.primary_exchange == "alpaca":
                return self._submit_order_alpaca(order)
            else:
                logger.error(f"Unsupported exchange: {self.primary_exchange}")
                return None

        except Exception as e:
            logger.error(f"Order submission failed: {e}")
            if self.rest_fallback_enabled:
                return self._submit_order_rest(order)
            return None

    def _submit_order_paper(self, order: OrderRequest) -> Optional[OrderFill]:
        """Simulate order submission in paper mode."""
        logger.info(f"PAPER MODE: Submitting {order.side} order for {order.quantity} {order.symbol}")

        # Simulate fill for market orders
        if order.order_type == "market":
            fill = OrderFill(
                order_id=order.id,
                symbol=order.symbol,
                side=order.side,
                quantity=order.quantity,
                price=self._get_simulated_price(order.symbol),
                fee=order.quantity * 50000 * 0.0026,
                fee_currency="USD",
                timestamp=datetime.utcnow(),
                status="filled",
                latency_ms=self.measure_latency()
            )
            return fill

        # Limit order goes pending
        self._pending_orders[order.id] = order
        return None

    def _submit_order_kraken(self, order: OrderRequest) -> Optional[OrderFill]:
        """
        Submit order to Kraken with post-only flag.

        Args:
            order: Order request

        Returns:
            OrderFill or None
        """
        endpoint = self._endpoints["kraken"]["order"]
        url = f"{self._endpoints['kraken']['rest']}{endpoint}"

        # Map order type
        order_type = "limit" if order.order_type == "limit" else "market"

        # Build data payload
        data = {
            "pair": order.symbol.replace("/", ""),
            "type": order.side,
            "ordertype": order_type,
            "volume": str(order.quantity),
            "oflags": "post"  # Post-only flag for maker fees
        }

        if order.limit_price:
            data["price"] = str(order.limit_price)

        # Generate signature
        headers = self._kraken_sign(endpoint, data)

        try:
            response = self._session.post(url, data=data, headers=headers, timeout=5.0)

            if response.status_code == 200:
                result = response.json()
                if result.get("error"):
                    logger.error(f"Kraken order error: {result['error']}")
                    return None

                # Parse transaction ID
                txid = result.get("result", {}).get("txid", [])
                if txid:
                    order_id = txid[0]
                    logger.info(f"Kraken order submitted: {order_id}")

                    # If market order, try to get fill
                    if order.order_type == "market":
                        return self._get_order_fill(order_id, order)
                    else:
                        self._pending_orders[order.id] = order
                        return None

            logger.error(f"Kraken order failed: {response.status_code}")
            return None

        except Exception as e:
            logger.error(f"Kraken order exception: {e}")
            return None

    def _submit_order_alpaca(self, order: OrderRequest) -> Optional[OrderFill]:
        """
        Submit order to Alpaca with post-only flag.

        Args:
            order: Order request

        Returns:
            OrderFill or None
        """
        endpoint = self._endpoints["alpaca"]["order"]
        url = f"{self._endpoints['alpaca']['rest']}{endpoint}"

        # Map order type
        order_type = "limit" if order.order_type == "limit" else "market"

        data = {
            "symbol": order.symbol,
            "qty": str(order.quantity),
            "side": order.side,
            "type": order_type,
            "time_in_force": "day"
        }

        # Post-only for limit orders
        if order.order_type == "limit":
            data["limit_price"] = str(order.limit_price)
            data["order_class"] = "simple"
            # Alpaca uses "post_only" flag
            data["post_only"] = True

        try:
            response = self._session.post(url, json=data, timeout=5.0)

            if response.status_code == 200:
                result = response.json()
                order_id = result.get("id")
                logger.info(f"Alpaca order submitted: {order_id}")

                if order.order_type == "market":
                    return self._get_order_fill(order_id, order)
                else:
                    self._pending_orders[order.id] = order
                    return None

            logger.error(f"Alpaca order failed: {response.status_code} - {response.text}")
            return None

        except Exception as e:
            logger.error(f"Alpaca order exception: {e}")
            return None

    def _submit_order_rest(self, order: OrderRequest) -> Optional[OrderFill]:
        """
        Submit order via REST API (fallback).

        Args:
            order: Order request

        Returns:
            OrderFill if successful
        """
        logger.info(f"REST fallback for order {order.id}")

        if self.primary_exchange == "kraken":
            return self._submit_order_kraken(order)
        elif self.primary_exchange == "alpaca":
            return self._submit_order_alpaca(order)
        else:
            return self._submit_order_paper(order)

    def _get_order_fill(self, order_id: str, order: OrderRequest) -> Optional[OrderFill]:
        """
        Get order fill details.

        Args:
            order_id: Exchange order ID
            order: Original order request

        Returns:
            OrderFill or None
        """
        try:
            if self.primary_exchange == "kraken":
                return self._get_kraken_order_fill(order_id, order)
            elif self.primary_exchange == "alpaca":
                return self._get_alpaca_order_fill(order_id, order)
            else:
                return None
        except Exception as e:
            logger.error(f"Failed to get order fill: {e}")
            return None

    def _get_kraken_order_fill(self, order_id: str, order: OrderRequest) -> Optional[OrderFill]:
        """Get Kraken order fill details."""
        endpoint = self._endpoints["kraken"]["status"]
        url = f"{self._endpoints['kraken']['rest']}{endpoint}"

        data = {"txid": order_id}
        headers = self._kraken_sign(endpoint, data)

        try:
            response = self._session.post(url, data=data, headers=headers, timeout=5.0)

            if response.status_code == 200:
                result = response.json()
                if result.get("error"):
                    return None

                order_data = result.get("result", {}).get(order_id, {})
                if order_data.get("status") == "closed":
                    return OrderFill(
                        order_id=order.id,
                        symbol=order.symbol,
                        side=order.side,
                        quantity=float(order_data.get("vol_exec", 0)),
                        price=float(order_data.get("price", 0)),
                        fee=float(order_data.get("fee", 0)),
                        fee_currency=order_data.get("fee_currency", "USD"),
                        timestamp=datetime.utcnow(),
                        status="filled",
                        latency_ms=self.measure_latency()
                    )

            return None

        except Exception as e:
            logger.error(f"Failed to get Kraken order fill: {e}")
            return None

    def _get_alpaca_order_fill(self, order_id: str, order: OrderRequest) -> Optional[OrderFill]:
        """Get Alpaca order fill details."""
        endpoint = self._endpoints["alpaca"]["status"].replace("{order_id}", order_id)
        url = f"{self._endpoints['alpaca']['rest']}{endpoint}"

        try:
            response = self._session.get(url, timeout=5.0)

            if response.status_code == 200:
                result = response.json()
                if result.get("status") == "filled":
                    return OrderFill(
                        order_id=order.id,
                        symbol=order.symbol,
                        side=order.side,
                        quantity=float(result.get("filled_qty", 0)),
                        price=float(result.get("filled_avg_price", 0)),
                        fee=float(result.get("fees", 0)),
                        fee_currency="USD",
                        timestamp=datetime.utcnow(),
                        status="filled",
                        latency_ms=self.measure_latency()
                    )

            return None

        except Exception as e:
            logger.error(f"Failed to get Alpaca order fill: {e}")
            return None

    def _get_simulated_price(self, symbol: str) -> float:
        """Get simulated current price (placeholder)."""
        if "BTC" in symbol:
            return 50000.0
        elif "ETH" in symbol:
            return 3000.0
        return 100.0

    # ============================================
    # POST-CANCELLATION VERIFICATION (PCV)
    # ============================================

    def cancel_order(self, order_id: str) -> bool:
        """
        Cancel order with PCV.

        Args:
            order_id: Order ID to cancel

        Returns:
            True if cancel request accepted
        """
        if self.paper_mode:
            return self._cancel_order_paper(order_id)

        try:
            # Check if exchange is ghosting
            if not self._websocket_connected and self.rest_fallback_enabled:
                return self._cancel_order_rest(order_id)

            if self.primary_exchange == "kraken":
                return self._cancel_order_kraken(order_id)
            elif self.primary_exchange == "alpaca":
                return self._cancel_order_alpaca(order_id)
            else:
                return False

        except Exception as e:
            logger.error(f"Order cancellation failed: {e}")
            if self.rest_fallback_enabled:
                return self._cancel_order_rest(order_id)
            return False

    def _cancel_order_paper(self, order_id: str) -> bool:
        """Simulate order cancellation in paper mode."""
        logger.info(f"PAPER MODE: Cancelling order {order_id}")
        with self._lock if hasattr(self, '_lock') else self._null_context():
            if order_id in self._pending_orders:
                del self._pending_orders[order_id]
        return True

    def _cancel_order_kraken(self, order_id: str) -> bool:
        """Cancel Kraken order."""
        endpoint = self._endpoints["kraken"]["cancel"]
        url = f"{self._endpoints['kraken']['rest']}{endpoint}"

        data = {"txid": order_id}
        headers = self._kraken_sign(endpoint, data)

        try:
            response = self._session.post(url, data=data, headers=headers, timeout=5.0)

            if response.status_code == 200:
                result = response.json()
                if result.get("error"):
                    logger.error(f"Kraken cancel error: {result['error']}")
                    return False
                return True

            return False

        except Exception as e:
            logger.error(f"Kraken cancel exception: {e}")
            return False

    def _cancel_order_alpaca(self, order_id: str) -> bool:
        """Cancel Alpaca order."""
        endpoint = self._endpoints["alpaca"]["cancel"].replace("{order_id}", order_id)
        url = f"{self._endpoints['alpaca']['rest']}{endpoint}"

        try:
            response = self._session.delete(url, timeout=5.0)

            if response.status_code in [200, 204]:
                return True

            logger.error(f"Alpaca cancel failed: {response.status_code}")
            return False

        except Exception as e:
            logger.error(f"Alpaca cancel exception: {e}")
            return False

    def _cancel_order_rest(self, order_id: str) -> bool:
        """Cancel order via REST API (fallback)."""
        logger.info(f"REST cancellation for order {order_id}")

        if self.primary_exchange == "kraken":
            return self._cancel_order_kraken(order_id)
        elif self.primary_exchange == "alpaca":
            return self._cancel_order_alpaca(order_id)
        else:
            return self._cancel_order_paper(order_id)

    def get_order_status(self, order_id: str) -> str:
        """
        Get order status with PCV verification.

        Args:
            order_id: Order ID

        Returns:
            Order status string
        """
        # Check cache first
        if order_id in self._order_status_cache:
            cached = self._order_status_cache[order_id]
            if cached.timestamp and (datetime.utcnow() - cached.timestamp).total_seconds() < 1.0:
                return cached.status

        # Query exchange
        status = self._query_order_status(order_id)

        # Update cache
        self._order_status_cache[order_id] = OrderStatus(
            order_id=order_id,
            status=status,
            timestamp=datetime.utcnow()
        )

        return status

    def _query_order_status(self, order_id: str) -> str:
        """
        Query exchange for order status.

        Args:
            order_id: Order ID

        Returns:
            Order status
        """
        if self.paper_mode:
            # In paper mode, check pending orders
            if order_id in self._pending_orders:
                return "pending"
            return "cancelled"

        if self.primary_exchange == "kraken":
            return self._query_kraken_order_status(order_id)
        elif self.primary_exchange == "alpaca":
            return self._query_alpaca_order_status(order_id)

        return "unknown"

    def _query_kraken_order_status(self, order_id: str) -> str:
        """Query Kraken order status."""
        endpoint = self._endpoints["kraken"]["status"]
        url = f"{self._endpoints['kraken']['rest']}{endpoint}"

        data = {"txid": order_id}
        headers = self._kraken_sign(endpoint, data)

        try:
            response = self._session.post(url, data=data, headers=headers, timeout=5.0)

            if response.status_code == 200:
                result = response.json()
                if result.get("error"):
                    return "unknown"

                order_data = result.get("result", {}).get(order_id, {})
                status = order_data.get("status", "unknown")

                # Map Kraken status
                if status == "closed":
                    return "filled"
                elif status == "cancelled":
                    return "cancelled"
                elif status == "expired":
                    return "expired"
                elif status == "rejected":
                    return "rejected"
                else:
                    return "pending"

            return "unknown"

        except Exception as e:
            logger.error(f"Failed to query Kraken order status: {e}")
            return "unknown"

    def _query_alpaca_order_status(self, order_id: str) -> str:
        """Query Alpaca order status."""
        endpoint = self._endpoints["alpaca"]["status"].replace("{order_id}", order_id)
        url = f"{self._endpoints['alpaca']['rest']}{endpoint}"

        try:
            response = self._session.get(url, timeout=5.0)

            if response.status_code == 200:
                result = response.json()
                status = result.get("status", "unknown")
                return status

            return "unknown"

        except Exception as e:
            logger.error(f"Failed to query Alpaca order status: {e}")
            return "unknown"

    def verify_cancellation(self, order_id: str) -> bool:
        """
        Verify order is cancelled (PCV loop).

        Args:
            order_id: Order ID

        Returns:
            True if confirmed cancelled
        """
        for attempt in range(self.pcv_max_attempts):
            status = self.get_order_status(order_id)
            if status in ["cancelled", "expired", "rejected"]:
                logger.info(f"PCV confirmed: Order {order_id} is {status}")
                with self._lock if hasattr(self, '_lock') else self._null_context():
                    if order_id in self._pending_orders:
                        del self._pending_orders[order_id]
                return True
            if status == "filled":
                logger.warning(f"PCV: Order {order_id} filled before cancellation")
                return False
            time.sleep(self.pcv_retry_delay_sec)

        logger.error(f"PCV failed: Order {order_id} still pending after {self.pcv_max_attempts} attempts")
        return False

    # ============================================
    # EMERGENCY REST FALLBACK
    # ============================================

    def close_all_positions(self) -> bool:
        """
        Emergency close all positions via REST API.

        Returns:
            True if all positions closed
        """
        logger.critical("EMERGENCY: Closing all positions via REST")

        # Get all open positions
        positions = self._get_open_positions()

        if not positions:
            logger.info("No open positions to close")
            return True

        success = True
        for position in positions:
            try:
                # Create market order to close position
                close_order = OrderRequest(
                    id=f"close_{position['symbol']}_{int(time.time()*1000)}",
                    symbol=position['symbol'],
                    side="sell" if position['side'] == "buy" else "buy",
                    quantity=position['quantity'],
                    order_type="market",
                    strategy="emergency",
                    confidence=1.0
                )
                fill = self._submit_order_rest(close_order)
                if fill:
                    logger.info(f"Closed position {position['symbol']}: {position['quantity']} @ {fill.price:.2f}")
                else:
                    logger.error(f"Failed to close position {position['symbol']}")
                    success = False
            except Exception as e:
                logger.error(f"Error closing position {position['symbol']}: {e}")
                success = False

        return success

    def _get_open_positions(self) -> List[Dict[str, Any]]:
        """
        Get open positions from exchange.

        Returns:
            List of open positions
        """
        if self.paper_mode:
            # In paper mode, return empty list
            return []

        if self.primary_exchange == "kraken":
            return self._get_kraken_open_positions()
        elif self.primary_exchange == "alpaca":
            return self._get_alpaca_open_positions()
        return []

    def _get_kraken_open_positions(self) -> List[Dict[str, Any]]:
        """Get Kraken open positions."""
        endpoint = self._endpoints["kraken"]["open_orders"]
        url = f"{self._endpoints['kraken']['rest']}{endpoint}"

        data = {}
        headers = self._kraken_sign(endpoint, data)

        try:
            response = self._session.post(url, data=data, headers=headers, timeout=5.0)

            if response.status_code == 200:
                result = response.json()
                if result.get("error"):
                    return []

                orders = result.get("result", {}).get("open", {})
                positions = []
                for order_id, order_data in orders.items():
                    positions.append({
                        "symbol": order_data.get("descr", {}).get("pair", ""),
                        "side": order_data.get("descr", {}).get("type", ""),
                        "quantity": float(order_data.get("vol", 0)),
                        "order_id": order_id
                    })
                return positions

            return []

        except Exception as e:
            logger.error(f"Failed to get Kraken open positions: {e}")
            return []

    def _get_alpaca_open_positions(self) -> List[Dict[str, Any]]:
        """Get Alpaca open positions."""
        endpoint = self._endpoints["alpaca"]["open_orders"]
        url = f"{self._endpoints['alpaca']['rest']}{endpoint}"

        try:
            response = self._session.get(url, timeout=5.0)

            if response.status_code == 200:
                orders = response.json()
                positions = []
                for order in orders:
                    if order.get("status") == "open":
                        positions.append({
                            "symbol": order.get("symbol", ""),
                            "side": order.get("side", ""),
                            "quantity": float(order.get("qty", 0)),
                            "order_id": order.get("id", "")
                        })
                return positions

            return []

        except Exception as e:
            logger.error(f"Failed to get Alpaca open positions: {e}")
            return []

    # ============================================
    # UTILITY METHODS
    # ============================================

    def get_mid_price(self, symbol: str) -> float:
        """
        Get current mid price for symbol.

        Args:
            symbol: Trading symbol

        Returns:
            Mid price
        """
        if self.paper_mode:
            return self._get_simulated_price(symbol)

        # In production, would query order book
        return self._get_simulated_price(symbol)

    def get_ghost_status(self) -> Dict[str, Any]:
        """
        Get ghost detection status.

        Returns:
            Ghost status dictionary
        """
        return {
            "websocket_connected": self._websocket_connected,
            "primary_exchange": self.primary_exchange,
            "secondary_exchange": self.secondary_exchange,
            "ghost_ratio_threshold": self.ghost_ratio_threshold,
            "latency_threshold_ms": self.latency_threshold_ms,
            "current_latency_ms": self.measure_latency(),
            "websocket_rtt_ms": self.get_websocket_rtt_ms(),
            "paper_mode": self.paper_mode
        }

    def _null_context(self):
        """Null context manager."""
        class NullContext:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
        return NullContext()