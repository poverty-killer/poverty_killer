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
import math
import os
import time
from collections import deque
from decimal import Decimal
from typing import Dict, List, Optional, Callable, Any
from datetime import datetime
from threading import RLock

from app.models import Candle, OrderBookSnapshot
from app.data.rolling_window import RollingWindow
from app.data.validators import DataValidator
from app.data.websocket_client import AlpacaCryptoWebSocketClient, KrakenWebSocketClient
from app.data.polling_client import (
    BatchedAlpacaPollingClient,
    MarketDataRequestBudget,
    MarketDataTransportPolicy,
    PollingClient,
)
from app.data.feed_provider_router import (
    FeedProviderHealth,
    FeedProviderLane,
    FeedProviderRequest,
    FeedSelectionResult,
    ProviderRuntimeStatus,
    build_feed_provider_router,
)
from app.market.capability_registry import MARKET_DATA_OBSERVE_ONLY, MarketDataUniverseSnapshot
from app.market.capability_registry import MarketBreadthObservation, build_market_data_universe_snapshot
from app.utils.time_utils import now_ns

logger = logging.getLogger(__name__)


class MarketFeeds:
    """
    Centralized market data manager.
    Provides unified interface for WebSocket and polling data sources.
    Maintains rolling windows and validates all incoming data.
    """

    def __init__(
        self,
        config: Any,
        *,
        symbols: Optional[List[str]] = None,
        deep_symbols: Optional[List[str]] = None,
        protected_symbols: Optional[List[str]] = None,
        env: Optional[Dict[str, str]] = None,
        feed_provider_router: Optional[Any] = None,
        initial_selection: Optional[FeedSelectionResult] = None,
        alpaca_websocket_factory: Callable[..., Any] = AlpacaCryptoWebSocketClient,
        alpaca_polling_factory: Callable[..., Any] = BatchedAlpacaPollingClient,
        legacy_polling_factory: Callable[..., Any] = PollingClient,
        ranking_constraints: Optional[Dict[str, Dict[str, Any]]] = None,
        ranking_state_store: Optional[Any] = None,
        ranking_catalog_snapshot_id: Optional[str] = None,
        ranking_broker_universe_snapshot_id: Optional[str] = None,
        held_symbols: Optional[List[str]] = None,
        open_order_symbols: Optional[List[str]] = None,
        lifecycle_symbols: Optional[List[str]] = None,
    ):
        """
        Initialize market feeds.

        Args:
            config: Configuration object with data settings
        """
        self.config = config
        self.symbols = list(
            dict.fromkeys(
                str(symbol).strip().upper()
                for symbol in (symbols if symbols is not None else config.symbol_universe)
                if str(symbol).strip()
            )
        )
        self.deep_symbols = tuple(
            dict.fromkeys(
                str(symbol).strip().upper()
                for symbol in (deep_symbols or protected_symbols or ())
                if str(symbol).strip()
            )
        )
        self.protected_symbols = frozenset(
            str(symbol).strip().upper() for symbol in (protected_symbols or ()) if str(symbol).strip()
        )
        if not self.protected_symbols.issubset(self.deep_symbols):
            raise ValueError("protected_symbols_must_be_deep")
        if not set(self.deep_symbols).issubset(self.symbols):
            raise ValueError("deep_symbols_must_be_in_breadth")
        self._env = dict(os.environ if env is None else env)
        self._alpaca_websocket_factory = alpaca_websocket_factory
        self._alpaca_polling_factory = alpaca_polling_factory
        self._legacy_polling_factory = legacy_polling_factory
        self._ranking_constraints = {
            str(symbol).strip().upper(): dict(values)
            for symbol, values in (ranking_constraints or {}).items()
            if str(symbol).strip() and isinstance(values, dict)
        }
        self._ranking_state_store = ranking_state_store
        self._ranking_catalog_snapshot_id = str(ranking_catalog_snapshot_id or "").strip()
        self._ranking_broker_universe_snapshot_id = str(ranking_broker_universe_snapshot_id or "").strip()
        self._ranking_held_symbols = tuple(
            dict.fromkeys(str(symbol).strip().upper() for symbol in (held_symbols or ()) if str(symbol).strip())
        )
        self._ranking_open_order_symbols = tuple(
            dict.fromkeys(str(symbol).strip().upper() for symbol in (open_order_symbols or ()) if str(symbol).strip())
        )
        self._ranking_lifecycle_symbols = tuple(
            dict.fromkeys(str(symbol).strip().upper() for symbol in (lifecycle_symbols or ()) if str(symbol).strip())
        )
        self._ranking_enabled = bool(
            self._ranking_constraints
            and self._ranking_state_store is not None
            and self._ranking_catalog_snapshot_id
            and self._ranking_broker_universe_snapshot_id
        )
        role_protected = frozenset(
            (*self._ranking_held_symbols, *self._ranking_open_order_symbols, *self._ranking_lifecycle_symbols)
        )
        if self._ranking_enabled and role_protected != self.protected_symbols:
            raise ValueError("market_data_protected_role_authority_mismatch")
        if self._ranking_enabled and not set(self._ranking_constraints).issubset(self.symbols):
            raise ValueError("market_data_ranking_constraint_outside_breadth")

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
        self.websocket_client: Optional[Any] = None
        self.polling_client: Optional[Any] = None
        self._websocket_truth: Dict[str, Any] = {
            "status": "WEBSOCKET_INACTIVE",
            "exchange": "kraken",
        }
        self._rest_truth_by_symbol_feed: Dict[str, Dict[str, Dict[str, Any]]] = {}
        self.feed_provider_router = feed_provider_router or build_feed_provider_router(
            configured_provider_ids=getattr(config, "crypto_market_data_providers", ()),
            env=self._env,
        )
        self._feed_provider_selection = initial_selection or self.feed_provider_router.select_provider(
            FeedProviderRequest(
                symbol=self.symbols[0] if self.symbols else "",
                asset_class="crypto",
                required_data_type="order_book",
                provider_lane=FeedProviderLane.CRYPTO_MARKET_DATA.value,
                execution_required=True,
            )
        )

        # Callbacks
        self._candle_callbacks: List[Callable] = []
        self._order_book_callbacks: List[Callable] = []
        self._trade_callbacks: List[Callable] = []  # FIXED: initialized
        self._quote_callbacks: List[Callable] = []
        self._breadth_callbacks: List[Callable] = []
        self._transport_truth_callbacks: List[Callable] = []
        self._rest_latency_callbacks: List[Callable] = []
        self._websocket_health_callbacks: List[Callable] = []
        observation_limit = max(10, int(getattr(config.data, "market_data_observations_per_symbol", 120)))
        self._breadth_observations: Dict[str, deque] = {
            symbol: deque(maxlen=observation_limit) for symbol in self.symbols
        }
        self._active_provider_id: Optional[str] = None
        self._active_transport_generation = 0
        self._pending_deep_symbols: Optional[frozenset[str]] = None
        self._execution_truth_active = False
        self._execution_consumer_seeded = False
        self._transport_state = "NOT_STARTED"
        self._transport_truth: Dict[str, Any] = {}
        self._activation_failure: Optional[Dict[str, Any]] = None
        self._provider_runtime_status: Dict[str, ProviderRuntimeStatus] = {}
        self._request_budget = MarketDataRequestBudget(
            self._transport_policy(),
            monotonic=time.monotonic,
            sleep=asyncio.sleep,
        )
        self._started = False
        self._managed_transport_engaged = False
        self._switch_lock = asyncio.Lock()
        self._failover_task: Optional[asyncio.Task] = None
        self._transport_health_task: Optional[asyncio.Task] = None
        self._transport_activated_at_ns = 0
        self._rank_refresh_task: Optional[asyncio.Task] = None
        self._rank_refresh_lock = asyncio.Lock()
        self._last_rank_refresh_ns = 0
        self._latest_universe_snapshot: Optional[MarketDataUniverseSnapshot] = None
        self._cross_venue_advisory: Dict[str, Dict[str, Any]] = {}
        self._observe_only_rejections: deque[Dict[str, Any]] = deque(
            maxlen=max(10, int(getattr(config.data, "market_data_failure_history_size", 100)))
        )
        self._ranking_status: Dict[str, Any] = {
            "status": "COLLECTING_BREADTH" if self._ranking_enabled else "DISABLED_NO_RANKING_CONTEXT",
            "activation_mode": MARKET_DATA_OBSERVE_ONLY,
            "execution_authorized": False,
        }
        self._restore_ranked_universe()

        self._lock = RLock()

        logger.info(f"MarketFeeds initialized with {len(self.symbols)} symbols")

    async def start(self) -> None:
        """Start the selected transport or its actually activated fallback."""
        logger.info("Starting market feeds...")
        self._started = True
        selection = self._feed_provider_selection
        attempted: set[str] = set()
        while selection.selected_provider_id is not None and selection.selected_provider_id not in attempted:
            attempted.add(selection.selected_provider_id)
            try:
                await self._activate_selection(selection)
                self._feed_provider_selection = selection
                if self._transport_health_task is None or self._transport_health_task.done():
                    self._transport_health_task = asyncio.create_task(self._transport_health_loop())
                logger.info("Market-data transport active: %s", selection.selected_provider_id)
                return
            except Exception as exc:
                await self._stop_active_clients()
                failed_id = selection.selected_provider_id
                self._provider_runtime_status[failed_id] = ProviderRuntimeStatus(
                    provider_id=failed_id,
                    health=FeedProviderHealth.FAILED.value,
                    reason_codes=("WEBSOCKET_UNAVAILABLE" if "stream" in failed_id else "REST_UNAVAILABLE",),
                    last_error=exc.__class__.__name__,
                )
                selection = self.feed_provider_router.select_provider(
                    self._execution_request(),
                    provider_status=self._provider_runtime_status,
                )
        self._feed_provider_selection = selection
        self._execution_truth_active = False
        self._transport_state = "FAILED_CLOSED"
        self._transport_truth = {
            "status": "FAILED_CLOSED",
            "reason": selection.reason,
            "selected_provider_id": None,
            "active_provider_id": None,
            "transport_activated": False,
            "executable_truth": False,
            "timestamp_ns": now_ns(),
        }
        await self._notify_async(self._transport_truth_callbacks, dict(self._transport_truth))
        raise RuntimeError(f"selected_market_data_transport_unavailable:{selection.reason}")

    def _execution_request(self) -> FeedProviderRequest:
        return FeedProviderRequest(
            symbol=self.symbols[0] if self.symbols else "",
            asset_class="crypto",
            required_data_type="order_book",
            provider_lane=FeedProviderLane.CRYPTO_MARKET_DATA.value,
            execution_required=True,
        )

    def _transport_policy(self) -> MarketDataTransportPolicy:
        data = self.config.data
        return MarketDataTransportPolicy(
            batch_size=int(getattr(data, "market_data_batch_size", 50)),
            max_concurrency=int(getattr(data, "market_data_max_concurrency", 4)),
            global_requests_per_minute=int(getattr(data, "market_data_global_requests_per_minute", 180)),
            provider_requests_per_minute=int(getattr(data, "market_data_provider_requests_per_minute", 180)),
            request_timeout_seconds=float(getattr(data, "market_data_request_timeout_seconds", 10.0)),
            callback_timeout_seconds=float(getattr(data, "market_data_callback_timeout_seconds", 5.0)),
            max_retries=int(getattr(data, "market_data_max_retries", 3)),
            backoff_base_seconds=float(getattr(data, "market_data_backoff_base_seconds", 0.5)),
            backoff_max_seconds=float(getattr(data, "market_data_backoff_max_seconds", 30.0)),
            circuit_failure_threshold=int(getattr(data, "market_data_circuit_failure_threshold", 5)),
            circuit_cooldown_seconds=float(getattr(data, "market_data_circuit_cooldown_seconds", 30.0)),
            job_queue_size=int(getattr(data, "market_data_job_queue_size", 128)),
            failure_history_size=int(getattr(data, "market_data_failure_history_size", 100)),
        )

    async def _activate_selection(self, selection: FeedSelectionResult) -> None:
        provider = selection.selected_provider
        if provider is None or provider.execution_location != "alpaca" or provider.advisory_only:
            raise RuntimeError("execution_location_transport_required")
        async with self._switch_lock:
            self._managed_transport_engaged = True
            await self._stop_active_clients()
            self._active_transport_generation += 1
            generation = self._active_transport_generation
            provider_id = provider.provider_id
            self._active_provider_id = provider_id
            self._execution_truth_active = False
            self._execution_consumer_seeded = False
            self._transport_state = "ACTIVATING"
            self._activation_failure = None
            headers = {
                "APCA-API-KEY-ID": str(self._env.get("APCA_API_KEY_ID") or ""),
                "APCA-API-SECRET-KEY": str(self._env.get("APCA_API_SECRET_KEY") or ""),
            }
            if not all(headers.values()):
                raise RuntimeError("alpaca_market_data_credentials_missing")
            candle_freshness_policy_ms = (
                float(provider.freshness_policy.get("candle_stale_seconds", 60.0)) * 1000.0
            )
            quote_freshness_policy_ms = (
                float(provider.freshness_policy.get("quote_stale_seconds", 10.0)) * 1000.0
            )
            order_book_freshness_policy_ms = (
                float(provider.freshness_policy.get("order_book_stale_seconds", 10.0)) * 1000.0
            )
            callback_kwargs = {
                "on_candle": lambda value: self._on_transport_candle(value, generation, provider_id),
                "on_order_book": lambda value: self._on_transport_order_book(value, generation, provider_id),
                "on_feed_truth": lambda value: self._on_transport_truth(value, generation, provider_id),
            }
            if provider.transport_adapter == "alpaca_crypto_websocket":
                if not self.deep_symbols:
                    raise RuntimeError("alpaca_deep_symbols_required")
                self.polling_client = self._alpaca_polling_factory(
                    breadth_symbols=self.symbols,
                    deep_symbols=list(self.deep_symbols),
                    protected_symbols=list(self.protected_symbols),
                    breadth_interval_seconds=float(getattr(self.config.data, "breadth_poll_interval_seconds", 15.0)),
                    deep_interval_seconds=float(getattr(self.config.data, "polling_interval_seconds", 1.0)),
                    deep_poll_enabled=False,
                    request_headers=headers,
                    policy=self._transport_policy(),
                    request_budget=self._request_budget,
                    quote_freshness_policy_ms=quote_freshness_policy_ms,
                    order_book_freshness_policy_ms=order_book_freshness_policy_ms,
                    candle_freshness_policy_ms=candle_freshness_policy_ms,
                    order_book_level_limit=int(
                        getattr(self.config.data, "market_data_order_book_levels_per_side", 1000)
                    ),
                    on_breadth_snapshot=lambda value: self._on_breadth_snapshot(value, generation),
                    on_feed_truth=lambda value: self._on_transport_truth(value, generation, "alpaca_crypto_rest"),
                    on_rest_latency=self._on_transport_rest_latency,
                )
                self.websocket_client = self._alpaca_websocket_factory(
                    symbols=list(self.deep_symbols),
                    key_id=headers["APCA-API-KEY-ID"],
                    secret_key=headers["APCA-API-SECRET-KEY"],
                    max_queue_size=int(getattr(self.config.data, "websocket_max_queue_size", 10000)),
                    ping_interval=int(getattr(self.config.data, "websocket_ping_interval", 30)),
                    callback_timeout_seconds=float(getattr(self.config.data, "market_data_callback_timeout_seconds", 5.0)),
                    dedupe_history_size=int(getattr(self.config.data, "market_data_event_dedupe_history_size", 10000)),
                    quote_freshness_policy_ms=quote_freshness_policy_ms,
                    order_book_freshness_policy_ms=order_book_freshness_policy_ms,
                    candle_freshness_policy_ms=candle_freshness_policy_ms,
                    order_book_level_limit=int(
                        getattr(self.config.data, "market_data_order_book_levels_per_side", 1000)
                    ),
                    on_trade=lambda value: self._on_transport_trade(value, generation, provider_id),
                    on_quote=lambda value: self._on_transport_quote(value, generation, provider_id),
                    on_health=self._on_alpaca_websocket_health,
                    **callback_kwargs,
                )
                await self.polling_client.start()
                await self.websocket_client.start()
                stream_status = self.websocket_client.get_feed_truth_status()
                if stream_status.get("status") != "WEBSOCKET_ACTIVE":
                    raise RuntimeError("alpaca_stream_not_active_after_start")
            elif provider.transport_adapter == "alpaca_crypto_rest":
                self.polling_client = self._alpaca_polling_factory(
                    breadth_symbols=self.symbols,
                    deep_symbols=list(self.deep_symbols),
                    protected_symbols=list(self.protected_symbols),
                    breadth_interval_seconds=float(getattr(self.config.data, "breadth_poll_interval_seconds", 15.0)),
                    deep_interval_seconds=float(getattr(self.config.data, "polling_interval_seconds", 1.0)),
                    deep_poll_enabled=True,
                    request_headers=headers,
                    policy=self._transport_policy(),
                    request_budget=self._request_budget,
                    quote_freshness_policy_ms=quote_freshness_policy_ms,
                    order_book_freshness_policy_ms=order_book_freshness_policy_ms,
                    candle_freshness_policy_ms=candle_freshness_policy_ms,
                    order_book_level_limit=int(
                        getattr(self.config.data, "market_data_order_book_levels_per_side", 1000)
                    ),
                    on_breadth_snapshot=lambda value: self._on_breadth_snapshot(value, generation),
                    on_rest_latency=self._on_transport_rest_latency,
                    **callback_kwargs,
                )
                await self.polling_client.start(require_initial_success=True)
            else:
                raise RuntimeError(f"transport_adapter_not_implemented:{provider.transport_adapter}")
            if self._activation_failure is not None:
                raise RuntimeError(
                    "market_data_transport_failed_during_activation:"
                    + str(self._activation_failure.get("status") or "UNKNOWN")
                )
            self._execution_truth_active = True
            self._transport_state = "ACTIVE"
            self._transport_activated_at_ns = now_ns()
            self._transport_truth = {
                "status": "TRANSPORT_ACTIVE",
                "selected_provider_id": provider_id,
                "transport_adapter": provider.transport_adapter,
                "execution_location": provider.execution_location,
                "generation": generation,
                "transport_activated": True,
                "executable_truth": False,
                "reason": "AWAITING_FRESH_PROTECTED_SYMBOL_MARKET_TRUTH",
                "timestamp_ns": now_ns(),
            }
            if self._protected_execution_truth_ready() and not self._seed_protected_execution_callbacks():
                await self._revoke_execution_consumer_truth()
                raise RuntimeError("market_data_execution_consumer_seed_rejected")
            await self._refresh_executable_transport_truth(force=True)

    async def _stop_active_clients(self) -> None:
        self._execution_truth_active = False
        self._execution_consumer_seeded = False
        self._activation_failure = None
        self._transport_activated_at_ns = 0
        self._pending_deep_symbols = None
        self._active_transport_generation += 1
        websocket_client, polling_client = self.websocket_client, self.polling_client
        self.websocket_client = None
        self.polling_client = None
        self._active_provider_id = None
        self.candles.clear_all()
        self.validator.reset_all()
        with self._lock:
            self.order_books.clear()
            self.depth_history.clear()
            self.spread_history.clear()
        if websocket_client is not None:
            await websocket_client.stop()
        if polling_client is not None:
            await polling_client.stop()

    async def stop(self) -> None:
        """Stop all market data feeds."""
        logger.info("Stopping market feeds...")
        self._started = False
        self._execution_truth_active = False
        self._transport_state = "STOPPING"
        if self._failover_task is not None and self._failover_task is not asyncio.current_task():
            self._failover_task.cancel()
            await asyncio.gather(self._failover_task, return_exceptions=True)
        if self._transport_health_task is not None and self._transport_health_task is not asyncio.current_task():
            self._transport_health_task.cancel()
            await asyncio.gather(self._transport_health_task, return_exceptions=True)
        self._transport_health_task = None
        if self._rank_refresh_task is not None and self._rank_refresh_task is not asyncio.current_task():
            self._rank_refresh_task.cancel()
            await asyncio.gather(self._rank_refresh_task, return_exceptions=True)
        await self._stop_active_clients()
        self._transport_state = "STOPPED"
        logger.info("Market feeds stopped")

    def _on_websocket_health(self, ping_ns: int, pong_ns: int) -> None:
        self._websocket_truth = {
            "status": "WEBSOCKET_ACTIVE",
            "exchange": "kraken",
            "ping_ns": ping_ns,
            "pong_ns": pong_ns,
            "timestamp_ns": now_ns(),
        }

    def _on_rest_feed_truth(self, status: Dict[str, Any]) -> None:
        symbol = str(status.get("symbol", ""))
        feed_type = str(status.get("feed_type", ""))
        if not symbol or not feed_type:
            return
        self._rest_truth_by_symbol_feed.setdefault(symbol, {})[feed_type] = dict(status)

    async def _on_transport_truth(self, status: Dict[str, Any], generation: int, provider_id: str) -> None:
        if generation != self._active_transport_generation or provider_id != self._active_provider_id:
            return
        failure_statuses = {
            "WEBSOCKET_UNAVAILABLE",
            "WEBSOCKET_BACKPRESSURE",
            "WEBSOCKET_SLOW_CONSUMER",
            "MALFORMED_WEBSOCKET_PAYLOAD",
            "REST_POLLING_FAILED",
            "SNAPSHOT_BATCH_FAILED",
            "ORDER_BOOK_BATCH_FAILED",
            "POLL_LOOP_FAILED",
            "RATE_LIMITED",
            "SLOW_CONSUMER",
            "CALLBACK_FAILED",
            "CALLBACK_REJECTED",
            "WEBSOCKET_STALE",
            "CANDLE_STALE",
            "ORDER_BOOK_STALE",
            "MALFORMED_SNAPSHOT",
            "MALFORMED_ORDER_BOOK",
            "OUT_OF_ORDER_SNAPSHOT",
            "OUT_OF_ORDER_ORDER_BOOK",
            "WEBSOCKET_SUBSCRIPTION_FAILED",
        }
        status_code = str(status.get("status") or "")
        symbol = str(status.get("symbol") or "").strip().upper()
        if status_code in failure_statuses and symbol and symbol not in self.protected_symbols:
            # A malformed observe-only breadth member is isolated and remains
            # visible in REST statistics; it cannot revoke protected truth.
            return
        self._transport_truth = {
            **dict(status),
            "active_provider_id": self._active_provider_id,
            "generation": generation,
            "transport_state": self._transport_state,
        }
        await self._notify_async(self._transport_truth_callbacks, dict(self._transport_truth))
        if status_code not in failure_statuses:
            return
        reason = (
            status_code
            if status_code in {"WEBSOCKET_STALE", "CANDLE_STALE", "ORDER_BOOK_STALE"}
            else "WEBSOCKET_UNAVAILABLE" if "stream" in provider_id else "REST_UNAVAILABLE"
        )
        self._provider_runtime_status[provider_id] = ProviderRuntimeStatus(
            provider_id=provider_id,
            health=FeedProviderHealth.FAILED.value,
            reason_codes=(reason,),
            last_error=str(status.get("exception_type") or "transport_failure"),
        )
        self._execution_truth_active = False
        if self._transport_state == "ACTIVATING":
            self._activation_failure = dict(status)
            return
        if self._started and self._transport_state == "ACTIVE" and (
            self._failover_task is None or self._failover_task.done()
        ):
            self._failover_task = asyncio.create_task(self._perform_failover(provider_id))

    async def _perform_failover(self, failed_provider_id: str) -> None:
        self._transport_state = "FAILING_OVER"
        await self._stop_active_clients()
        selection = self.feed_provider_router.select_provider(
            self._execution_request(),
            provider_status=self._provider_runtime_status,
        )
        self._feed_provider_selection = selection
        if selection.selected_provider_id is None:
            self._active_provider_id = None
            self._execution_truth_active = False
            self._transport_state = "FAILED_CLOSED"
            self._transport_truth = {
                "status": "FAILED_CLOSED",
                "reason": selection.reason,
                "failed_provider_id": failed_provider_id,
                "executable_truth": False,
                "timestamp_ns": now_ns(),
            }
            await self._notify_async(self._transport_truth_callbacks, dict(self._transport_truth))
            return
        try:
            await self._activate_selection(selection)
        except Exception as exc:
            selected_id = str(selection.selected_provider_id or "")
            self._provider_runtime_status[selected_id] = ProviderRuntimeStatus(
                provider_id=selected_id,
                health=FeedProviderHealth.FAILED.value,
                reason_codes=("WEBSOCKET_UNAVAILABLE" if "stream" in selected_id else "REST_UNAVAILABLE",),
                last_error=exc.__class__.__name__,
            )
            await self._perform_failover(selected_id)

    def _active_freshness_seconds(self, field_name: str, default: float) -> float:
        descriptor = self.feed_provider_router.providers.get(str(self._active_provider_id or ""))
        raw = descriptor.freshness_policy.get(field_name, default) if descriptor is not None else default
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return default
        return value if math.isfinite(value) and value > 0 else default

    @staticmethod
    def _candle_freshness_timestamp_ns(candle: Candle) -> int:
        close_ns = getattr(candle, "candle_close_ts_ns", None)
        if type(close_ns) is int and close_ns > 0:
            return close_ns
        return int(candle.exchange_ts_ns)

    @staticmethod
    def _truth_is_stale(source_ns: int, *, current_ns: int, threshold_seconds: float) -> bool:
        return source_ns <= 0 or source_ns > current_ns or current_ns - source_ns > int(threshold_seconds * 1_000_000_000)

    async def _check_transport_health_once(self, *, current_ns: Optional[int] = None) -> Optional[str]:
        """Fail over an active but silent transport after its declared freshness grace."""
        if not self._started or self._transport_state != "ACTIVE" or not self._execution_truth_active:
            return None
        provider_id = str(self._active_provider_id or "")
        generation = self._active_transport_generation
        if not provider_id or self._transport_activated_at_ns <= 0:
            return None
        checked_ns = int(current_ns if current_ns is not None else now_ns())
        candle_seconds = self._active_freshness_seconds("candle_stale_seconds", 60.0)
        order_book_seconds = self._active_freshness_seconds("order_book_stale_seconds", 10.0)
        active_age_ns = checked_ns - self._transport_activated_at_ns
        for symbol in sorted(self.protected_symbols):
            book = self.get_order_book(symbol)
            book_expired = book is None or self._truth_is_stale(
                int(book.exchange_ts_ns) if book is not None else 0,
                current_ns=checked_ns,
                threshold_seconds=order_book_seconds,
            )
            if book_expired and active_age_ns > int(order_book_seconds * 1_000_000_000):
                status = "ORDER_BOOK_STALE"
            else:
                candle = self.get_last_candle(symbol)
                candle_current = candle is not None and not self._truth_is_stale(
                    self._candle_freshness_timestamp_ns(candle),
                    current_ns=checked_ns,
                    threshold_seconds=candle_seconds,
                )
                if candle_current or active_age_ns <= int(candle_seconds * 1_000_000_000):
                    continue
                status = "CANDLE_STALE"
            await self._on_transport_truth(
                {
                    "status": status,
                    "provider_id": provider_id,
                    "symbol": symbol,
                    "exception_type": "StaleMarketData",
                    "executable_truth": False,
                    "timestamp_ns": checked_ns,
                },
                generation,
                provider_id,
            )
            return status
        return None

    async def _transport_health_loop(self) -> None:
        while self._started:
            try:
                await asyncio.sleep(1.0)
                await self._check_transport_health_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("Market-data transport health check failed: %s", exc.__class__.__name__)

    async def _on_breadth_snapshot(self, observation: Dict[str, Any], generation: int) -> None:
        if generation != self._active_transport_generation:
            return
        symbol = str(observation.get("symbol") or "").strip().upper()
        if symbol not in self._breadth_observations:
            return
        if observation.get("execution_location") != "alpaca" or observation.get("executable_source") is not True:
            return
        self._breadth_observations[symbol].append(dict(observation))
        await self._notify_async(self._breadth_callbacks, dict(observation))
        self._maybe_schedule_rank_refresh()

    def record_cross_venue_advisory(
        self,
        *,
        symbol: str,
        provider_id: str,
        midpoint: Decimal | str,
        source_event_ns: int,
        received_at_ns: int,
    ) -> None:
        """Record source/time-attributed advisory basis evidence without execution authority."""
        normalized_symbol = str(symbol or "").strip().upper()
        descriptor = self.feed_provider_router.providers.get(str(provider_id or "").strip())
        if normalized_symbol not in self._breadth_observations:
            raise ValueError("cross_venue_advisory_symbol_outside_breadth")
        if (
            descriptor is None
            or descriptor.advisory_only is not True
            or descriptor.execution_location == "alpaca"
            or descriptor.execution_eligible
        ):
            raise ValueError("cross_venue_advisory_provider_required")
        if isinstance(midpoint, (bool, float)):
            raise ValueError("cross_venue_advisory_exact_midpoint_required")
        parsed_midpoint = Decimal(str(midpoint))
        if not parsed_midpoint.is_finite() or parsed_midpoint <= 0:
            raise ValueError("cross_venue_advisory_midpoint_invalid")
        if type(source_event_ns) is not int or type(received_at_ns) is not int or not 0 < source_event_ns <= received_at_ns:
            raise ValueError("cross_venue_advisory_time_invalid")
        if received_at_ns > now_ns():
            raise ValueError("cross_venue_advisory_future_receipt_refused")
        previous = self._cross_venue_advisory.get(normalized_symbol)
        if previous is not None and (
            source_event_ns <= int(previous["source_event_ns"])
            or received_at_ns <= int(previous["received_at_ns"])
        ):
            raise ValueError("cross_venue_advisory_time_regression")
        self._cross_venue_advisory[normalized_symbol] = {
            "provider_id": descriptor.provider_id,
            "midpoint": parsed_midpoint,
            "source_event_ns": source_event_ns,
            "received_at_ns": received_at_ns,
            "advisory_only": True,
            "execution_authorized": False,
        }

    def _restore_ranked_universe(self) -> None:
        if not self._ranking_enabled:
            return
        try:
            value = self._ranking_state_store.get_latest_market_data_universe_snapshot(
                catalog_snapshot_id=self._ranking_catalog_snapshot_id,
                broker_universe_snapshot_id=self._ranking_broker_universe_snapshot_id,
                strict=True,
            )
            if value is None:
                return
            snapshot = MarketDataUniverseSnapshot.from_dict(value)
            current_ns = now_ns()
            if snapshot.as_of_ns > current_ns or snapshot.created_at_ns > current_ns:
                raise ValueError("future_market_data_universe_refused")
            configured_limits = (
                int(getattr(self.config.data, "market_data_deep_candidate_limit", 12)),
                int(getattr(self.config.data, "market_data_deep_subscription_limit", 30)),
                int(getattr(self.config.data, "market_data_min_residence_seconds", 900)) * 1_000_000_000,
            )
            if configured_limits != (
                snapshot.deep_candidate_limit,
                snapshot.deep_subscription_limit,
                snapshot.min_residence_ns,
            ):
                self._ranking_status = {
                    "status": "PRIOR_CONFIG_MISMATCH_COLLECTING_BREADTH",
                    "activation_mode": MARKET_DATA_OBSERVE_ONLY,
                    "execution_authorized": False,
                }
                return
            expected_held = tuple(sorted(set(self._ranking_held_symbols)))
            expected_open_orders = tuple(sorted(set(self._ranking_open_order_symbols)))
            expected_lifecycle = tuple(sorted(set(self._ranking_lifecycle_symbols)))
            expected_protected = frozenset((*expected_held, *expected_open_orders, *expected_lifecycle))
            roles_match = (
                snapshot.held_symbols == expected_held
                and snapshot.open_order_symbols == expected_open_orders
                and snapshot.lifecycle_symbols == expected_lifecycle
            )
            membership_symbols = {item.symbol for item in snapshot.memberships}
            snapshot_scope = membership_symbols | set(snapshot.unranked_symbols)
            if (
                not roles_match
                or snapshot_scope != set(self._ranking_constraints)
                or not snapshot_scope.issubset(self.symbols)
            ):
                self._ranking_status = {
                    "status": "PRIOR_SCOPE_MISMATCH_COLLECTING_BREADTH",
                    "activation_mode": MARKET_DATA_OBSERVE_ONLY,
                    "execution_authorized": False,
                }
                return
            self._latest_universe_snapshot = snapshot
            self._last_rank_refresh_ns = snapshot.as_of_ns
            self.protected_symbols = expected_protected
            self.deep_symbols = snapshot.deep_symbols
            self._ranking_status = {
                "status": "OBSERVE_ONLY_UNIVERSE_RESTORED",
                "snapshot_id": snapshot.snapshot_id,
                "as_of_ns": snapshot.as_of_ns,
                "deep_symbols": snapshot.deep_symbols,
                "unranked_symbols": snapshot.unranked_symbols,
                "unranked_reason": (
                    "INSUFFICIENT_EXECUTION_LOCATION_OBSERVATIONS"
                    if snapshot.unranked_symbols
                    else None
                ),
                "activation_mode": snapshot.activation_mode,
                "execution_authorized": snapshot.execution_authorized,
            }
        except Exception as exc:
            self._ranking_enabled = False
            self._ranking_status = {
                "status": "BLOCKED_RANKING_STATE_INVALID",
                "exception_type": exc.__class__.__name__,
                "activation_mode": MARKET_DATA_OBSERVE_ONLY,
                "execution_authorized": False,
            }

    def _maybe_schedule_rank_refresh(self) -> None:
        if not self._ranking_enabled:
            return
        current_ns = now_ns()
        minimum = int(getattr(self.config.data, "market_data_rank_min_observations", 8))
        protected = set(self.protected_symbols)
        missing_constraints = protected - set(self._ranking_constraints)
        if missing_constraints:
            self._ranking_status = {
                "status": "BLOCKED_MISSING_PROTECTED_CONSTRAINTS",
                "symbols": tuple(sorted(missing_constraints)),
                "activation_mode": MARKET_DATA_OBSERVE_ONLY,
                "execution_authorized": False,
            }
            return
        insufficient = tuple(
            sorted(
                symbol
                for symbol in protected
                if self._rankable_breadth_count(symbol, current_ns=current_ns) < minimum
            )
        )
        if insufficient:
            self._ranking_status = {
                "status": "COLLECTING_PROTECTED_BREADTH",
                "symbols": insufficient,
                "minimum_observations": minimum,
                "activation_mode": MARKET_DATA_OBSERVE_ONLY,
                "execution_authorized": False,
            }
            return
        refresh_ns = int(getattr(self.config.data, "market_data_rank_refresh_seconds", 300)) * 1_000_000_000
        if self._last_rank_refresh_ns and current_ns - self._last_rank_refresh_ns < refresh_ns:
            return
        if self._rank_refresh_task is not None and not self._rank_refresh_task.done():
            return
        self._rank_refresh_task = asyncio.create_task(self._refresh_ranked_universe())

    def _rankable_breadth_count(self, symbol: str, *, current_ns: Optional[int] = None) -> int:
        return len(self._rankable_breadth_rows(symbol, current_ns=current_ns))

    def _rankable_breadth_rows(self, symbol: str, *, current_ns: Optional[int] = None) -> list[Dict[str, Any]]:
        checked_ns = int(current_ns if current_ns is not None else now_ns())
        maximum_age_ns = int(
            float(
                getattr(
                    self.config.data,
                    "market_data_rank_observation_max_age_seconds",
                    45.0,
                )
            )
            * 1_000_000_000
        )
        retention_ns = int(
            max(
                float(getattr(self.config.data, "market_data_rank_observation_max_age_seconds", 45.0)),
                float(getattr(self.config.data, "breadth_poll_interval_seconds", 15.0))
                * int(getattr(self.config.data, "market_data_observations_per_symbol", 120)),
            )
            * 1_000_000_000
        )
        retention_cutoff_ns = checked_ns - retention_ns
        unique: Dict[tuple[int, int, int], Dict[str, Any]] = {}
        for raw in self._breadth_observations.get(symbol, ()):
            value = dict(raw)
            received_at_ns = int(value.get("received_at_ns") or 0)
            if (
                not isinstance(value.get("candle"), Candle)
                or value.get("execution_location") != "alpaca"
                or value.get("executable_source") is not True
                or received_at_ns <= retention_cutoff_ns
                or received_at_ns > checked_ns
            ):
                continue
            identity = (
                int(value.get("quote_exchange_ts_ns") or 0),
                int(value.get("trade_exchange_ts_ns") or 0),
                int(value.get("bar_exchange_ts_ns") or 0),
            )
            previous = unique.get(identity)
            if previous is None or int(value.get("received_at_ns") or 0) < int(previous.get("received_at_ns") or 0):
                unique[identity] = value
        ordered = sorted(
            unique.values(),
            key=lambda value: (int(value.get("received_at_ns") or 0), int(value.get("bar_exchange_ts_ns") or 0)),
        )
        if (
            not ordered
            or checked_ns - int(ordered[-1].get("received_at_ns") or 0) > maximum_age_ns
        ):
            return []
        return ordered

    def _build_rank_observation(
        self,
        symbol: str,
        *,
        current_ns: Optional[int] = None,
    ) -> MarketBreadthObservation:
        rows = self._rankable_breadth_rows(symbol, current_ns=current_ns)
        if not rows:
            raise ValueError("rank_observation_rows_required")
        constraints = self._ranking_constraints.get(symbol)
        if constraints is None:
            raise ValueError("rank_observation_constraints_required")
        source_times: list[int] = []
        received_times: list[int] = []
        trade_prices: list[float] = []
        dollar_volumes: list[Decimal] = []
        trade_counts: list[int] = []
        spreads_bps: list[float] = []
        depth_usd: list[Decimal] = []
        event_lag_ms: list[float] = []
        for value in rows:
            candle = value["candle"]
            source_ns = max(
                int(value.get("quote_exchange_ts_ns") or 0),
                int(value.get("trade_exchange_ts_ns") or 0),
                int(value.get("bar_close_ts_ns") or value.get("bar_exchange_ts_ns") or 0),
            )
            received_ns = int(value.get("received_at_ns") or 0)
            if source_ns <= 0 or received_ns <= 0 or source_ns > received_ns:
                raise ValueError("rank_observation_causal_timestamp_invalid")
            bid = float(value.get("bid"))
            ask = float(value.get("ask"))
            bid_size = float(value.get("bid_size"))
            ask_size = float(value.get("ask_size"))
            trade_price = float(value.get("trade_price"))
            if not all(math.isfinite(item) and item > 0 for item in (bid, ask, trade_price)):
                raise ValueError("rank_observation_price_invalid")
            if bid >= ask or not all(math.isfinite(item) and item >= 0 for item in (bid_size, ask_size)):
                raise ValueError("rank_observation_quote_invalid")
            trade_count = value.get("trade_count")
            if isinstance(trade_count, bool) or not isinstance(trade_count, int) or trade_count < 0:
                raise ValueError("rank_observation_trade_count_invalid")
            midpoint = (bid + ask) / 2.0
            source_times.append(source_ns)
            received_times.append(received_ns)
            trade_prices.append(trade_price)
            dollar_volumes.append(Decimal(str(candle.close)) * Decimal(str(candle.volume)))
            trade_counts.append(trade_count)
            spreads_bps.append((ask - bid) / midpoint * 10_000.0)
            depth_usd.append(
                min(
                    Decimal(str(bid)) * Decimal(str(bid_size)),
                    Decimal(str(ask)) * Decimal(str(ask_size)),
                )
            )
            component_source_times = (
                int(value.get("quote_exchange_ts_ns") or 0),
                int(value.get("trade_exchange_ts_ns") or 0),
                int(value.get("bar_close_ts_ns") or value.get("bar_exchange_ts_ns") or 0),
            )
            if any(source_time <= 0 or source_time > received_ns for source_time in component_source_times):
                raise ValueError("rank_observation_component_timestamp_invalid")
            event_lag_ms.append(
                max(received_ns - source_time for source_time in component_source_times)
                / 1_000_000.0
            )
        log_returns = tuple(
            math.log(current / previous)
            for previous, current in zip(trade_prices, trade_prices[1:])
        )
        if any(current < previous for previous, current in zip(source_times, source_times[1:])):
            raise ValueError("rank_observation_source_time_regression")
        gap_seconds = tuple(
            (current - previous) / 1_000_000_000.0
            for previous, current in zip(source_times, source_times[1:])
        )
        advisory = self._cross_venue_advisory.get(symbol)
        observation_received_cutoff_ns = max(received_times)
        if advisory is not None and (
            int(advisory.get("source_event_ns") or 0) > observation_received_cutoff_ns
            or int(advisory.get("received_at_ns") or 0) > observation_received_cutoff_ns
        ):
            advisory = None
        latest_mid = (Decimal(str(rows[-1]["bid"])) + Decimal(str(rows[-1]["ask"]))) / Decimal("2")
        return MarketBreadthObservation.from_dict(
            {
                "symbol": symbol,
                "provider_id": "alpaca_crypto_rest",
                "execution_location": "alpaca",
                "observed_at_ns": max(received_times),
                "latest_source_event_ns": max(source_times),
                "expected_samples": int(getattr(self.config.data, "market_data_observations_per_symbol", 120)),
                "received_samples": len(rows),
                "dollar_volumes": [str(value) for value in dollar_volumes],
                "trade_counts": trade_counts,
                "spreads_bps": spreads_bps,
                "depth_usd": [str(value) for value in depth_usd],
                "log_returns": log_returns,
                "event_lag_ms": event_lag_ms,
                "gap_seconds": gap_seconds,
                "observation_started_ns": min(source_times),
                "listing_started_ns": constraints.get("listing_started_ns"),
                "listing_age_source": constraints.get("listing_age_source"),
                "quote_currency": constraints.get("quote_currency"),
                "quote_currency_fundable": constraints.get("quote_currency_fundable") is True,
                "execution_mid": str(latest_mid),
                "cross_venue_mid": str(advisory["midpoint"]) if advisory else None,
                "cross_venue_provider_id": advisory.get("provider_id") if advisory else None,
                "cross_venue_source_event_ns": advisory.get("source_event_ns") if advisory else None,
                "cross_venue_received_at_ns": advisory.get("received_at_ns") if advisory else None,
                "min_order_size": constraints.get("min_order_size"),
                "min_trade_increment": constraints.get("min_trade_increment"),
                "price_increment": constraints.get("price_increment"),
            }
        )

    async def _refresh_ranked_universe(self) -> None:
        async with self._rank_refresh_lock:
            try:
                minimum = int(getattr(self.config.data, "market_data_rank_min_observations", 8))
                current_ns = now_ns()
                observed_symbols = tuple(
                    sorted(
                        symbol
                        for symbol in self._ranking_constraints
                        if self._rankable_breadth_count(symbol, current_ns=current_ns) >= minimum
                    )
                )
                if not observed_symbols:
                    self._ranking_status = {
                        "status": "COLLECTING_BREADTH",
                        "minimum_observations": minimum,
                        "activation_mode": MARKET_DATA_OBSERVE_ONLY,
                        "execution_authorized": False,
                    }
                    return
                unranked_symbols = tuple(
                    sorted(set(self._ranking_constraints) - set(observed_symbols))
                )
                observations = [
                    self._build_rank_observation(symbol, current_ns=current_ns)
                    for symbol in observed_symbols
                ]
                snapshot = await self.build_persist_and_apply_universe(
                    observations,
                    catalog_snapshot_id=self._ranking_catalog_snapshot_id,
                    broker_universe_snapshot_id=self._ranking_broker_universe_snapshot_id,
                    as_of_ns=current_ns,
                    created_at_ns=current_ns,
                    state_store=self._ranking_state_store,
                    prior_snapshot=self._latest_universe_snapshot,
                    held_symbols=list(self._ranking_held_symbols),
                    open_order_symbols=list(self._ranking_open_order_symbols),
                    lifecycle_symbols=list(self._ranking_lifecycle_symbols),
                    unranked_symbols=list(unranked_symbols),
                )
                self._latest_universe_snapshot = snapshot
                self._last_rank_refresh_ns = current_ns
                self._ranking_status = {
                    "status": "OBSERVE_ONLY_UNIVERSE_CURRENT",
                    "snapshot_id": snapshot.snapshot_id,
                    "as_of_ns": snapshot.as_of_ns,
                    "ranked_symbol_count": len(snapshot.memberships),
                    "unranked_symbols": snapshot.unranked_symbols,
                    "unranked_reason": (
                        "INSUFFICIENT_EXECUTION_LOCATION_OBSERVATIONS"
                        if snapshot.unranked_symbols
                        else None
                    ),
                    "deep_symbols": snapshot.deep_symbols,
                    "activation_mode": snapshot.activation_mode,
                    "execution_authorized": snapshot.execution_authorized,
                }
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._ranking_status = {
                    "status": "RANKING_FAILED",
                    "exception_type": exc.__class__.__name__,
                    "activation_mode": MARKET_DATA_OBSERVE_ONLY,
                    "execution_authorized": False,
                }

    async def _on_transport_rest_latency(self, observation: Dict[str, Any]) -> None:
        await self._notify_async(self._rest_latency_callbacks, dict(observation))

    async def _on_alpaca_websocket_health(self, ping_ns: int, pong_ns: int) -> None:
        self._websocket_truth = {
            "status": "WEBSOCKET_ACTIVE",
            "exchange": "alpaca",
            "provider_id": "alpaca_crypto_stream",
            "ping_ns": ping_ns,
            "pong_ns": pong_ns,
            "timestamp_ns": now_ns(),
        }
        for callback in tuple(self._websocket_health_callbacks):
            try:
                result = callback(ping_ns, pong_ns)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as exc:
                logger.error("WebSocket health callback failed: %s", exc.__class__.__name__)

    async def _on_transport_candle(self, candle: Candle, generation: int, provider_id: str) -> bool:
        if not self._transport_callback_current(generation, provider_id, candle.symbol):
            return False
        protected = candle.symbol in self.protected_symbols
        ready_before = self._protected_execution_truth_ready()
        accepted = self._accept_candle(
            candle,
            notify=(
                self._execution_truth_active
                and protected
                and self._execution_consumer_seeded
            ),
            log_invalid=protected,
        )
        if accepted and self._execution_truth_active:
            if (
                not self._execution_consumer_seeded
                and not ready_before
                and self._protected_execution_truth_ready()
            ):
                accepted = self._seed_protected_execution_callbacks()
        if not accepted:
            if not protected:
                self._record_observe_only_rejection(candle.symbol, "CANDLE_VALIDATION_REJECTED")
                return True
            await self._revoke_execution_consumer_truth()
            return False
        if accepted and self._execution_truth_active:
            await self._refresh_executable_transport_truth()
        return accepted

    async def _on_transport_order_book(self, order_book: OrderBookSnapshot, generation: int, provider_id: str) -> bool:
        if not self._transport_callback_current(generation, provider_id, order_book.symbol):
            return False
        protected = order_book.symbol in self.protected_symbols
        ready_before = self._protected_execution_truth_ready()
        accepted = self._accept_order_book(
            order_book,
            notify=(
                self._execution_truth_active
                and protected
                and self._execution_consumer_seeded
            ),
            log_invalid=protected,
        )
        if accepted and self._execution_truth_active:
            if (
                not self._execution_consumer_seeded
                and not ready_before
                and self._protected_execution_truth_ready()
            ):
                accepted = self._seed_protected_execution_callbacks()
        if not accepted:
            if not protected:
                self._record_observe_only_rejection(order_book.symbol, "ORDER_BOOK_VALIDATION_REJECTED")
                return True
            await self._revoke_execution_consumer_truth()
            return False
        if accepted and self._execution_truth_active:
            await self._refresh_executable_transport_truth()
        return accepted

    async def _on_transport_trade(self, trade: Dict[str, Any], generation: int, provider_id: str) -> bool:
        symbol = str(trade.get("symbol") or "").strip().upper()
        if not self._transport_callback_current(generation, provider_id, symbol):
            return False
        if (
            self._execution_truth_active
            and symbol in self.protected_symbols
            and self._execution_consumer_seeded
        ):
            accepted = self._on_trade(trade)
            if not accepted:
                await self._revoke_execution_consumer_truth()
            return accepted
        return True

    async def _on_transport_quote(self, quote: Dict[str, Any], generation: int, provider_id: str) -> bool:
        symbol = str(quote.get("symbol") or "").strip().upper()
        if not self._transport_callback_current(generation, provider_id, symbol):
            return False
        if (
            self._execution_truth_active
            and symbol in self.protected_symbols
            and self._execution_consumer_seeded
        ):
            accepted = await self._notify_async_checked(self._quote_callbacks, dict(quote))
            if not accepted:
                await self._revoke_execution_consumer_truth()
            return accepted
        return True

    async def _revoke_execution_consumer_truth(self) -> None:
        self._execution_truth_active = False
        self._execution_consumer_seeded = False
        self._transport_truth = {
            **self._transport_truth,
            "status": "EXECUTION_CONSUMER_REJECTED",
            "active_provider_id": self._active_provider_id,
            "transport_state": self._transport_state,
            "executable_truth": False,
            "reason": "EXECUTION_CONSUMER_REJECTED",
            "timestamp_ns": now_ns(),
        }
        await self._notify_async(
            self._transport_truth_callbacks,
            dict(self._transport_truth),
        )

    def _record_observe_only_rejection(self, symbol: str, reason: str) -> None:
        self._observe_only_rejections.append(
            {
                "symbol": str(symbol or "").strip().upper(),
                "reason": reason,
                "activation_mode": MARKET_DATA_OBSERVE_ONLY,
                "execution_authorized": False,
                "timestamp_ns": now_ns(),
            }
        )

    def _transport_callback_current(self, generation: int, provider_id: str, symbol: str) -> bool:
        return bool(
            generation == self._active_transport_generation
            and provider_id == self._active_provider_id
            and (
                symbol in self.deep_symbols
                or self._pending_deep_symbols is not None
                and symbol in self._pending_deep_symbols
            )
        )

    @staticmethod
    async def _notify_async(callbacks: List[Callable], value: Any) -> None:
        await MarketFeeds._notify_async_checked(callbacks, value)

    @staticmethod
    async def _notify_async_checked(callbacks: List[Callable], value: Any) -> bool:
        accepted = True
        for callback in tuple(callbacks):
            try:
                result = callback(value)
                if asyncio.iscoroutine(result):
                    result = await result
                if result is False:
                    accepted = False
            except Exception as exc:
                logger.error("Market-data callback failed: %s", exc.__class__.__name__)
                accepted = False
        return accepted

    def _expected_ranking_roles(self) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
        return (
            tuple(sorted(set(self._ranking_held_symbols))),
            tuple(sorted(set(self._ranking_open_order_symbols))),
            tuple(sorted(set(self._ranking_lifecycle_symbols))),
        )

    def _validate_snapshot_scope(self, snapshot: MarketDataUniverseSnapshot) -> None:
        if not self._ranking_enabled:
            raise RuntimeError("market_data_ranking_context_required")
        if (
            snapshot.catalog_snapshot_id != self._ranking_catalog_snapshot_id
            or snapshot.broker_universe_snapshot_id != self._ranking_broker_universe_snapshot_id
        ):
            raise ValueError("market_data_universe_lineage_mismatch")
        expected_held, expected_open_orders, expected_lifecycle = self._expected_ranking_roles()
        if (
            snapshot.held_symbols != expected_held
            or snapshot.open_order_symbols != expected_open_orders
            or snapshot.lifecycle_symbols != expected_lifecycle
        ):
            raise ValueError("market_data_universe_role_lineage_mismatch")
        membership_symbols = {item.symbol for item in snapshot.memberships}
        snapshot_scope = membership_symbols | set(snapshot.unranked_symbols)
        if snapshot_scope != set(self._ranking_constraints) or not snapshot_scope.issubset(self.symbols):
            raise ValueError("market_data_universe_symbol_scope_mismatch")

    async def apply_universe_snapshot(self, snapshot: MarketDataUniverseSnapshot | Dict[str, Any]) -> tuple[str, ...]:
        normalized = snapshot if isinstance(snapshot, MarketDataUniverseSnapshot) else MarketDataUniverseSnapshot.from_dict(snapshot)
        self._validate_snapshot_scope(normalized)
        if normalized.activation_mode != MARKET_DATA_OBSERVE_ONLY or normalized.execution_authorized:
            raise ValueError("market_data_universe_observe_only_required")
        protected_order = tuple(
            dict.fromkeys((*normalized.held_symbols, *normalized.open_order_symbols, *normalized.lifecycle_symbols))
        )
        protected = frozenset(protected_order)
        if not protected.issubset(normalized.deep_symbols):
            raise ValueError("protected_symbols_missing_from_deep_snapshot")
        if len(protected) > normalized.deep_subscription_limit:
            raise ValueError("protected_deep_capacity_exceeded")
        if not set(normalized.deep_symbols).issubset(self.symbols):
            raise ValueError("market_data_universe_deep_symbol_outside_breadth")
        ordered = list(protected_order)
        for symbol in normalized.deep_symbols:
            if symbol not in ordered:
                ordered.append(symbol)
        previous_deep = set(self.deep_symbols)
        next_deep = tuple(ordered)
        self._pending_deep_symbols = frozenset(next_deep)
        try:
            if self.websocket_client is not None and hasattr(self.websocket_client, "update_symbols"):
                await self.websocket_client.update_symbols(list(next_deep))
            if self.polling_client is not None and hasattr(self.polling_client, "update_deep_symbols"):
                self.polling_client.update_deep_symbols(
                    list(next_deep),
                    protected_symbols=list(protected_order),
                    limit=normalized.deep_subscription_limit,
                )
        except Exception:
            for symbol in set(next_deep) - previous_deep:
                self.candles.clear_symbol(symbol)
                self.validator.reset_symbol(symbol)
                with self._lock:
                    self.order_books.pop(symbol, None)
                    self.depth_history.pop(symbol, None)
                    self.spread_history.pop(symbol, None)
            raise
        finally:
            self._pending_deep_symbols = None
        self.protected_symbols = protected
        self.deep_symbols = next_deep
        for symbol in previous_deep - set(next_deep):
            self.candles.clear_symbol(symbol)
            self.validator.reset_symbol(symbol)
            with self._lock:
                self.order_books.pop(symbol, None)
                self.depth_history.pop(symbol, None)
                self.spread_history.pop(symbol, None)
        return self.deep_symbols

    async def build_persist_and_apply_universe(
        self,
        observations: List[MarketBreadthObservation],
        *,
        catalog_snapshot_id: str,
        broker_universe_snapshot_id: str,
        as_of_ns: int,
        created_at_ns: int,
        state_store: Any,
        prior_snapshot: Optional[MarketDataUniverseSnapshot] = None,
        held_symbols: Optional[List[str]] = None,
        open_order_symbols: Optional[List[str]] = None,
        lifecycle_symbols: Optional[List[str]] = None,
        unranked_symbols: Optional[List[str]] = None,
    ) -> MarketDataUniverseSnapshot:
        if state_store is not self._ranking_state_store:
            raise ValueError("market_data_universe_state_owner_mismatch")
        if (
            catalog_snapshot_id != self._ranking_catalog_snapshot_id
            or broker_universe_snapshot_id != self._ranking_broker_universe_snapshot_id
        ):
            raise ValueError("market_data_universe_lineage_mismatch")
        expected_held, expected_open_orders, expected_lifecycle = self._expected_ranking_roles()
        resolved_held = expected_held if held_symbols is None else tuple(sorted(set(held_symbols)))
        resolved_open_orders = expected_open_orders if open_order_symbols is None else tuple(sorted(set(open_order_symbols)))
        resolved_lifecycle = expected_lifecycle if lifecycle_symbols is None else tuple(sorted(set(lifecycle_symbols)))
        if (
            resolved_held != expected_held
            or resolved_open_orders != expected_open_orders
            or resolved_lifecycle != expected_lifecycle
        ):
            raise ValueError("market_data_universe_role_lineage_mismatch")
        snapshot = build_market_data_universe_snapshot(
            observations,
            catalog_snapshot_id=catalog_snapshot_id,
            broker_universe_snapshot_id=broker_universe_snapshot_id,
            as_of_ns=as_of_ns,
            created_at_ns=created_at_ns,
            held_symbols=resolved_held,
            open_order_symbols=resolved_open_orders,
            lifecycle_symbols=resolved_lifecycle,
            prior_snapshot=prior_snapshot,
            deep_candidate_limit=int(getattr(self.config.data, "market_data_deep_candidate_limit", 12)),
            deep_subscription_limit=int(getattr(self.config.data, "market_data_deep_subscription_limit", 30)),
            min_residence_ns=int(getattr(self.config.data, "market_data_min_residence_seconds", 900)) * 1_000_000_000,
            unranked_symbols=tuple(unranked_symbols or ()),
        )
        persistence_result = state_store.persist_market_data_universe_snapshot(snapshot)
        if persistence_result not in {"persisted", "duplicate"}:
            raise RuntimeError("market_data_universe_persistence_not_confirmed")
        await self.apply_universe_snapshot(snapshot)
        return snapshot

    def _on_candle(self, candle: Candle) -> None:
        """
        Handle incoming candle data.

        Args:
            candle: Candle to process
        """
        self._accept_candle(candle, notify=True)

    def _accept_candle(self, candle: Candle, *, notify: bool, log_invalid: bool = True) -> bool:
        """Validate/store a candle and optionally expose it to execution consumers."""
        current_time_ns = now_ns()
        result = self.validator.validate_candle(candle, current_time_ns)
        if not result.is_valid:
            if log_invalid:
                logger.warning(f"Invalid candle for {candle.symbol}: {result.error}")
            return False

        # Add to rolling window
        self.candles.add_candle(candle)

        return self._notify_candle_callbacks(candle) if notify else True

    def _notify_candle_callbacks(self, candle: Candle) -> bool:
        callbacks_accepted = True
        with self._lock:
            for callback in self._candle_callbacks:
                try:
                    result = callback(candle)
                    if asyncio.iscoroutine(result):
                        result.close()
                        callbacks_accepted = False
                        logger.error("Async candle callback is unsupported in synchronous dispatch")
                    elif result is False:
                        callbacks_accepted = False
                except Exception as exc:
                    callbacks_accepted = False
                    logger.error("Candle callback error: %s", exc.__class__.__name__)
        return callbacks_accepted

    def _on_order_book(self, order_book: OrderBookSnapshot) -> None:
        """
        Handle incoming order book data.

        Args:
            order_book: Order book snapshot to process
        """
        self._accept_order_book(order_book, notify=True)

    def _accept_order_book(
        self,
        order_book: OrderBookSnapshot,
        *,
        notify: bool,
        log_invalid: bool = True,
    ) -> bool:
        """Validate/store a book and optionally expose it to execution consumers."""
        current_time_ns = now_ns()
        result = self.validator.validate_order_book(order_book, current_time_ns)
        if not result.is_valid:
            if log_invalid:
                logger.warning(f"Invalid order book for {order_book.symbol}: {result.error}")
            return False

        # Store current order book
        with self._lock:
            self.order_books[order_book.symbol] = order_book

            # Update depth history
            if order_book.symbol not in self.depth_history:
                self.depth_history[order_book.symbol] = []
            bid_depth, ask_depth = order_book.depth_at_levels(10)
            self.depth_history[order_book.symbol].append(bid_depth + ask_depth)
            if len(self.depth_history[order_book.symbol]) > 100:
                self.depth_history[order_book.symbol] = self.depth_history[order_book.symbol][-100:]

            # Update spread history
            if order_book.symbol not in self.spread_history:
                self.spread_history[order_book.symbol] = []
            self.spread_history[order_book.symbol].append(order_book.spread_bps)
            if len(self.spread_history[order_book.symbol]) > 100:
                self.spread_history[order_book.symbol] = self.spread_history[order_book.symbol][-100:]

        return self._notify_order_book_callbacks(order_book) if notify else True

    def _notify_order_book_callbacks(self, order_book: OrderBookSnapshot) -> bool:
        callbacks_accepted = True
        with self._lock:
            for callback in self._order_book_callbacks:
                try:
                    result = callback(order_book)
                    if asyncio.iscoroutine(result):
                        result.close()
                        callbacks_accepted = False
                        logger.error("Async order-book callback is unsupported in synchronous dispatch")
                    elif result is False:
                        callbacks_accepted = False
                except Exception as exc:
                    callbacks_accepted = False
                    logger.error("Order book callback error: %s", exc.__class__.__name__)
        return callbacks_accepted

    def _seed_protected_execution_callbacks(self) -> bool:
        """Seed complete protected truth before later trades can reach MainLoop."""
        self._execution_consumer_seeded = False
        ordered_symbols = tuple(sorted(self.protected_symbols))
        books = tuple(self.get_order_book(symbol) for symbol in ordered_symbols)
        candles = tuple(self.get_last_candle(symbol) for symbol in ordered_symbols)
        if any(book is None for book in books) or any(candle is None for candle in candles):
            return False
        books_accepted = all(
            self._notify_order_book_callbacks(book)
            for book in books
            if book is not None
        )
        if not books_accepted:
            return False
        candles_accepted = all(
            self._notify_candle_callbacks(candle)
            for candle in candles
            if candle is not None
        )
        self._execution_consumer_seeded = candles_accepted
        return candles_accepted

    def _on_trade(self, trade: Dict[str, Any]) -> bool:
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
            return False
        
        if exchange_ts_ns <= 0:
            logger.debug(f"Trade missing exchange_ts_ns: {trade}")
            return False
        
        # Notify trade callbacks
        callbacks_accepted = True
        with self._lock:
            for callback in self._trade_callbacks:
                try:
                    result = callback(trade)
                    if asyncio.iscoroutine(result):
                        result.close()
                        callbacks_accepted = False
                        logger.error("Async trade callback is unsupported in synchronous dispatch")
                    elif result is False:
                        callbacks_accepted = False
                except Exception as exc:
                    callbacks_accepted = False
                    logger.error("Trade callback error: %s", exc.__class__.__name__)
        return callbacks_accepted

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

    def register_quote_callback(self, callback: Callable) -> None:
        with self._lock:
            self._quote_callbacks.append(callback)

    def register_breadth_callback(self, callback: Callable) -> None:
        with self._lock:
            self._breadth_callbacks.append(callback)

    def register_transport_truth_callback(self, callback: Callable) -> None:
        with self._lock:
            self._transport_truth_callbacks.append(callback)

    def register_rest_latency_callback(self, callback: Callable) -> None:
        with self._lock:
            self._rest_latency_callbacks.append(callback)

    def register_websocket_health_callback(self, callback: Callable) -> None:
        with self._lock:
            self._websocket_health_callbacks.append(callback)

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
        
        age_ns = current_time_ns - self._candle_freshness_timestamp_ns(last_candle)
        if age_ns < 0:
            return True
        age_sec = age_ns / 1_000_000_000.0
        return age_sec > self.validator.stale_threshold_seconds

    def _order_book_is_stale(self, symbol: str, current_time_ns: Optional[int] = None) -> bool:
        checked_ns = int(current_time_ns if current_time_ns is not None else now_ns())
        book = self.get_order_book(symbol)
        if book is None:
            return True
        return self._truth_is_stale(
            int(book.exchange_ts_ns),
            current_ns=checked_ns,
            threshold_seconds=self._active_freshness_seconds("order_book_stale_seconds", 10.0),
        )

    def _protected_truth_blockers(self, current_time_ns: Optional[int] = None) -> tuple[str, ...]:
        if not self.protected_symbols:
            return ("NO_PROTECTED_EXECUTION_SYMBOLS_STAGE4",)
        blockers: list[str] = []
        for symbol in sorted(self.protected_symbols):
            if self.get_order_book(symbol) is None:
                blockers.append(f"MISSING_ORDER_BOOK_TRUTH:{symbol}")
            elif self._order_book_is_stale(symbol, current_time_ns):
                blockers.append(f"STALE_ORDER_BOOK_TRUTH:{symbol}")
            if self.get_last_candle(symbol) is None:
                blockers.append(f"MISSING_CANDLE_TRUTH:{symbol}")
            elif self.is_stale(symbol, current_time_ns):
                blockers.append(f"STALE_MARKET_TRUTH:{symbol}")
        return tuple(blockers)

    def _protected_execution_truth_ready(self, current_time_ns: Optional[int] = None) -> bool:
        return bool(
            self._execution_truth_active
            and self.protected_symbols
            and not self._protected_truth_blockers(current_time_ns)
        )

    async def _refresh_executable_transport_truth(self, *, force: bool = False) -> None:
        if (
            self._transport_state != "ACTIVE"
            or self._active_provider_id is None
            or not self._execution_truth_active
        ):
            return
        blockers = self._protected_truth_blockers()
        executable = bool(
            self._execution_truth_active
            and self._execution_consumer_seeded
            and not blockers
        )
        status = "EXECUTABLE_MARKET_TRUTH_ACTIVE" if executable else "TRANSPORT_ACTIVE"
        if (
            not force
            and self._transport_truth.get("executable_truth") is executable
            and tuple(self._transport_truth.get("missing_truth") or ()) == blockers
        ):
            return
        self._transport_truth = {
            **self._transport_truth,
            "status": status,
            "selected_provider_id": self._active_provider_id,
            "active_provider_id": self._active_provider_id,
            "generation": self._active_transport_generation,
            "transport_activated": True,
            "executable_truth": executable,
            "missing_truth": blockers,
            "reason": None if executable else blockers[0] if blockers else "TRANSPORT_NOT_EXECUTABLE",
            "timestamp_ns": now_ns(),
        }
        await self._notify_async(self._transport_truth_callbacks, dict(self._transport_truth))

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
        feed_truth = self.get_feed_truth_status()
        return {
            "symbols": len(self.symbols),
            "candles_per_symbol": {
                sym: self.candles.get_count(sym) for sym in self.symbols
            },
            "order_books_active": len(self.order_books),
            "stale_symbols": [s for s in self.symbols if self.is_stale(s)],
            "websocket_connected": bool(getattr(self.websocket_client, "_connected", False)),
            "polling_active": bool(getattr(self.polling_client, "is_running", False)),
            "feed_truth": feed_truth,
            "feed_truth_status": feed_truth["status"],
            "timestamp_ns": now_ns()
        }

    def get_feed_truth_status(self) -> Dict[str, Any]:
        """
        Return combined websocket/REST market-data truth.

        This does not substitute websocket data for missing REST truth. It marks
        partial truth explicitly so downstream components can degrade or fail
        closed according to their own contracts.
        """
        if (
            self._managed_transport_engaged
            or self._active_provider_id is not None
            or self._transport_state not in {"NOT_STARTED", "STOPPED"}
        ):
            missing_truth = list(self._protected_truth_blockers())
            websocket_truth = (
                self.websocket_client.get_feed_truth_status()
                if self.websocket_client is not None and hasattr(self.websocket_client, "get_feed_truth_status")
                else {"status": "WEBSOCKET_INACTIVE"}
            )
            polling_truth = self.polling_client.get_stats() if self.polling_client is not None else {}
            executable = bool(
                self._execution_truth_active
                and self._execution_consumer_seeded
                and self.protected_symbols
                and not missing_truth
            )
            transport_truth = {
                **dict(self._transport_truth),
                "active_provider_id": self._active_provider_id,
                "transport_state": self._transport_state,
                "execution_consumer_seeded": self._execution_consumer_seeded,
                "transport_activated": bool(
                    self._transport_state == "ACTIVE"
                    and self._active_provider_id is not None
                    and self._execution_truth_active
                ),
                "executable_truth": executable,
                "missing_truth": tuple(missing_truth),
            }
            if self._transport_state == "ACTIVE" and self._execution_truth_active:
                transport_truth["status"] = (
                    "EXECUTABLE_MARKET_TRUTH_ACTIVE" if executable else "TRANSPORT_ACTIVE"
                )
                transport_truth["reason"] = (
                    None if executable else missing_truth[0] if missing_truth else "TRANSPORT_NOT_EXECUTABLE"
                )
            return {
                "status": "EXECUTION_LOCATION_ACTIVE" if executable else self._transport_state,
                "market_truth": "MARKET_DATA_FULL_TRUTH" if executable else "MISSING_FEED_TRUTH",
                "execution_location": "alpaca",
                "executable_truth": executable,
                "active_provider_id": self._active_provider_id,
                "transport_generation": self._active_transport_generation,
                "transport_state": self._transport_state,
                "execution_consumer_seeded": self._execution_consumer_seeded,
                "transport_truth": transport_truth,
                "provider_selection": self._feed_provider_selection.to_telemetry(),
                "provider_runtime_status": {
                    provider_id: {
                        "health": status.health,
                        "reason_codes": status.reason_codes,
                        "last_error": status.last_error,
                    }
                    for provider_id, status in self._provider_runtime_status.items()
                },
                "websocket": websocket_truth,
                "rest": polling_truth,
                "breadth_symbol_count": len(self.symbols),
                "deep_symbols": self.deep_symbols,
                "protected_symbols": tuple(sorted(self.protected_symbols)),
                "dynamic_activation_mode": MARKET_DATA_OBSERVE_ONLY,
                "dynamic_execution_authorized": False,
                "universe_ranking": dict(self._ranking_status),
                "observe_only_rejections": tuple(dict(item) for item in self._observe_only_rejections),
                "missing_truth": tuple(missing_truth),
                "order_book_symbols": tuple(sorted(self.order_books)),
                "timestamp_ns": now_ns(),
            }

        ws_truth = (
            self.websocket_client.get_feed_truth_status()
            if self.websocket_client and hasattr(self.websocket_client, "get_feed_truth_status")
            else dict(self._websocket_truth)
        )
        polling_stats = self.polling_client.get_stats() if self.polling_client else {}
        rest_failures = polling_stats.get("failure_status_by_symbol_feed") or self._rest_truth_by_symbol_feed
        latest_rest_failure = polling_stats.get("last_failure_status") or {}
        latest_rest_success = polling_stats.get("last_success_status") or {}

        websocket_active = ws_truth.get("status") == "WEBSOCKET_ACTIVE"
        dns_failure = latest_rest_failure.get("status") == "DNS_FAILURE_RECORDED" or any(
            feed_status.get("status") == "DNS_FAILURE_RECORDED"
            for by_feed in rest_failures.values()
            for feed_status in by_feed.values()
        )
        rest_active = bool(latest_rest_success) and not dns_failure

        if websocket_active and dns_failure:
            status = "WEBSOCKET_ACTIVE_REST_DNS_FAILED"
            market_truth = "MARKET_DATA_PARTIAL_TRUTH"
        elif websocket_active and rest_active:
            status = "WEBSOCKET_ACTIVE"
            market_truth = "MARKET_DATA_FULL_TRUTH"
        elif dns_failure:
            status = "REST_POLLING_DEGRADED"
            market_truth = "MARKET_DATA_PARTIAL_TRUTH" if self.order_books else "FAILED_CLOSED"
        elif websocket_active:
            status = "WEBSOCKET_ACTIVE"
            market_truth = "MARKET_DATA_PARTIAL_TRUTH"
        else:
            status = "FAILED_CLOSED"
            market_truth = "MISSING_FEED_TRUTH"

        missing_truth = []
        if dns_failure or status in {"REST_POLLING_DEGRADED", "WEBSOCKET_ACTIVE_REST_DNS_FAILED"}:
            missing_truth.extend(["MISSING_CANDLE_TRUTH", "MISSING_ORDER_BOOK_TRUTH"])
        for symbol in self.symbols:
            if symbol not in self.order_books:
                missing_truth.append(f"MISSING_ORDER_BOOK_TRUTH:{symbol}")
            if self.candles.get_count(symbol) <= 0:
                missing_truth.append(f"MISSING_CANDLE_TRUTH:{symbol}")
            elif self.is_stale(symbol):
                missing_truth.append(f"STALE_MARKET_TRUTH:{symbol}")

        return {
            "status": status,
            "market_truth": market_truth,
            "websocket": ws_truth,
            "rest": {
                "active": rest_active,
                "latest_success": latest_rest_success,
                "latest_failure": latest_rest_failure,
                "failures_by_symbol_feed": rest_failures,
            },
            "provider_selection": self._feed_provider_selection.to_telemetry(),
            "universe_ranking": dict(self._ranking_status),
            "missing_truth": tuple(sorted(set(missing_truth))),
            "order_book_symbols": tuple(sorted(self.order_books.keys())),
            "timestamp_ns": now_ns(),
        }

    def get_breadth_observations(self, symbol: Optional[str] = None) -> Dict[str, tuple[Dict[str, Any], ...]]:
        symbols = (symbol,) if symbol is not None else tuple(self.symbols)
        return {
            item: tuple(dict(observation) for observation in self._breadth_observations.get(item, ()))
            for item in symbols
            if item in self._breadth_observations
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
