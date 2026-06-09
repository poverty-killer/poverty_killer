#!/usr/bin/env python
"""
Poverty Killer - Sovereign Trading Engine
Main entry point for current paper-trading bring-up.

Authority posture:
- main.py owns bootstrap, assembly, feed callback registration, startup/shutdown,
  and monitoring shell behavior.
- app/main_loop.py owns the live market-data / brain / state / risk-ingress body.
- app/execution/engine.py owns live execution authority.
- app/execution/orchestrator.py is explicitly rejected and must not be wired.

BUNDLE F1 — TELEMETRY INTEGRATION
- Initializes TelemetryEventStore at bootstrap
- Passes telemetry_store to OrderRouter, ExecutionEngine, and MainLoop

WEBSOCKET HEALTH WIRING — PERMANENT FIX
- Wires KrakenWebSocketClient health callback to order_router.update_websocket_health()
- Removes diagnostic-only warnings (heartbeat detection now functional)
- WebSocket health now reflects actual heartbeat state

BUNDLE MULTI-SYMBOL RUNTIME — PER-SYMBOL OWNERSHIP EXPANSION
- Passes active_symbols set to create_main_loop
- Per-symbol engines now created inside MainLoop's SymbolRuntime containers
- _on_trade() now extracts symbol from trade_info and passes to MainLoop.on_trade()
- Removes primary-symbol hardcoding from trade/insider path

BUNDLE STRATEGY-GATING REPAIR — WHALE OVERLAY WIRING (2026-04-27)
- Adds call to MainLoop.on_trade_with_whale() with full trade details
- Preserves existing on_trade() call for backward compatibility
- Passes side and volume to enable per-symbol whale detection
"""

import argparse
import asyncio
import logging
import math
import os
import signal
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, Optional, Set

from dotenv import load_dotenv

from app.brain.data_validator import DataContinuityValidator
from app.brain.entropy_decoder import EntropyDecoder
from app.brain.insider_signal_engine import (
    InsiderObservation,
    InsiderSignalEngine,
    ObservationDirection,
    ObservationSourceType,
)
from app.brain.physical_validator import PhysicalValidator
from app.brain.recalibrator import Recalibrator
from app.brain.regime_detector import RegimeDetector
from app.brain.shans_curve import ShansCurve
from app.brain.signal_fusion import SignalFusion
from app.brain.whale_flow_engine import WhaleFlowEngine
from app.commander import Commander
from app.config import Config
from app.core.whole_bot_attribution import build_startup_attribution
from app.data.feed_provider_router import (
    FeedProviderHealth,
    FeedProviderLane,
    FeedProviderRequest,
    ProviderRuntimeStatus,
    build_feed_provider_router,
)
from app.data.polling_client import PollingClient
from app.data.websocket_client import KrakenWebSocketClient
from app.execution.alpaca_paper_adapter import AlpacaPaperBrokerAdapter
from app.execution.broker_gateway import BrokerCredentialStatus, BrokerEnvironment, BrokerGatewayError
from app.execution.broker_read_policy import broker_read_profile_from_env
from app.execution.engine import ExecutionEngine
from app.execution.masking_layer import MaskingLayer
from app.execution.order_router import OrderRouter
from app.instrument_registry import InstrumentRegistry
from app.market import (
    CapabilityAwareCandidate,
    PortalSelectionRequest,
    VenueCapabilityRegistry,
    build_default_capability_registry,
)
from app.main_loop import create_main_loop
from app.models import Candle, EventEnvelope
from app.models.enums import EventType, ExchangeType
from app.monitoring.logger import setup_logger
from app.operator_activation.paper_baseline import load_paper_baseline_runtime_context_from_env
from app.risk.exposure_manager import ExposureManager
from app.risk.guard import HybridRiskGuard
from app.risk.reservation_lifecycle_coordinator import ReservationLifecycleCoordinator
from app.risk.safety import SafetyGate
from app.state.state_store import StateStore
from app.telemetry.event_store import TelemetryEventStore
from app.utils.time_utils import now_ns

logger = logging.getLogger(__name__)


# ============================================
# VENUE + MARKET SEAM — symbol filter and fallback
# ============================================

_VENUE_SYMBOL_FILTER: dict = {
    "kraken": lambda s: InstrumentRegistry.get_exchange(s) == ExchangeType.KRAKEN,
}

_VENUE_PRIMARY_SYMBOL_FALLBACK: dict = {
    "kraken": "XBT/USD",
}

EXECUTION_BROKER_ENV_VAR = "POVERTY_KILLER_EXECUTION_BROKER"
INTERNAL_PAPER_EXECUTION_BROKER = "internal_paper"
ALPACA_PAPER_EXECUTION_BROKER = "alpaca_paper"
SUPPORTED_EXECUTION_BROKERS = frozenset(
    {
        INTERNAL_PAPER_EXECUTION_BROKER,
        ALPACA_PAPER_EXECUTION_BROKER,
    }
)

_FEED_PROVIDER_TO_VENUE = {
    "coinbase_public": "coinbase",
    "kraken_public": "kraken",
}

_REST_FEED_FAILURE_REASON_MAP = {
    "DNS_FAILURE_RECORDED": "DNS_FAILURE",
    "REST_POLLING_FAILED": "REST_UNAVAILABLE",
    "MISSING_CANDLE_TRUTH": "CANDLE_STALE",
    "MISSING_ORDER_BOOK_TRUTH": "ORDER_BOOK_STALE",
}


class ExecutionBrokerSelectionError(RuntimeError):
    """Fail-closed runtime broker selection error with sanitized reasons."""


@dataclass(frozen=True)
class RuntimeUniverseResolution:
    symbols: tuple[str, ...]
    source: str
    reason: str


def get_configured_execution_broker(config: Config) -> str:
    """
    Return the operator-selected execution broker.

    Market-data venue remains separate. Absence of the env selector preserves
    explicit local simulation rather than silently assuming any external broker.
    """
    raw = os.environ.get(EXECUTION_BROKER_ENV_VAR, INTERNAL_PAPER_EXECUTION_BROKER)
    broker = str(raw or "").strip().lower()
    if not broker:
        broker = INTERNAL_PAPER_EXECUTION_BROKER
    if broker not in SUPPORTED_EXECUTION_BROKERS:
        raise ExecutionBrokerSelectionError(f"unsupported_execution_broker:{broker}")
    if broker != INTERNAL_PAPER_EXECUTION_BROKER and config.broker_mode != "paper":
        raise ExecutionBrokerSelectionError("external_execution_broker_requires_paper_mode")
    return broker


def resolve_execution_broker_gateway(config: Config) -> tuple[str, str, Any | None, str]:
    """
    Resolve active execution broker and optional BrokerGateway adapter.

    Returns:
        execution_broker, order_router_primary_exchange, gateway_adapter, adapter_id
    """
    execution_broker = get_configured_execution_broker(config)
    if execution_broker == INTERNAL_PAPER_EXECUTION_BROKER:
        return execution_broker, "kraken", None, "internal_sovereign_paper_broker"

    if execution_broker == ALPACA_PAPER_EXECUTION_BROKER:
        try:
            adapter = AlpacaPaperBrokerAdapter.from_env()
        except BrokerGatewayError as exc:
            detail = str(exc.reason_code)
            message = str(getattr(exc, "message", "") or "").strip().lower()
            if message and message != detail:
                detail = f"{detail}:{message}"
            if "live_endpoint_blocked" in message and "live_or_nonpaper_endpoint_blocked" not in detail:
                detail = f"{detail}:live_or_nonpaper_endpoint_blocked"
            raise ExecutionBrokerSelectionError(f"alpaca_paper_adapter_blocked:{detail}") from exc

        identity = adapter.identity
        reasons: list[str] = []
        if identity.environment != BrokerEnvironment.PAPER.value:
            reasons.append("adapter_environment_not_paper")
        if identity.credential_status != BrokerCredentialStatus.CONFIGURED.value:
            reasons.append("adapter_credentials_missing")
        if identity.live_blocked is not True:
            reasons.append("adapter_live_endpoint_not_blocked")
        if identity.venue_id != "alpaca":
            reasons.append("adapter_venue_mismatch")
        if reasons:
            raise ExecutionBrokerSelectionError("alpaca_paper_adapter_blocked:" + ",".join(reasons))
        return execution_broker, identity.venue_id, adapter, identity.adapter_id

    raise ExecutionBrokerSelectionError(f"unsupported_execution_broker:{execution_broker}")


def _feed_symbols_for_venue(venue: str, universe: list, active_markets: list) -> list:
    """
    Return symbols from universe that satisfy all of:
      1. belong to the given venue per InstrumentRegistry exchange authority
      2. have an asset class that is in active_markets
      3. are present in symbol_universe

    Raises ValueError for unknown venue.
    Logs and excludes symbols absent from InstrumentRegistry.
    """
    predicate = _VENUE_SYMBOL_FILTER.get(venue)
    if predicate is None:
        raise ValueError(
            f"Unknown feed venue: {venue!r}. "
            f"Supported: {list(_VENUE_SYMBOL_FILTER)}"
        )

    active_set = {m.lower() for m in active_markets}
    result = []

    for symbol in universe:
        if not predicate(symbol):
            continue

        asset_cls = InstrumentRegistry.get_asset_class(symbol)
        if asset_cls is None:
            logger.warning(
                "Symbol %r not found in InstrumentRegistry — excluded from feed",
                symbol,
            )
            continue

        if asset_cls.value in active_set:
            result.append(symbol)

    return result


def get_active_symbols(config: Config) -> Set[str]:
    """
    Get explicit runtime universe symbols.

    This compatibility surface intentionally returns plain symbols because
    MainLoop still consumes symbol strings. It no longer injects a hidden
    venue-filtered symbol list.
    """
    return set(resolve_runtime_universe(config).symbols)


def _active_market_values(config: Config) -> set[str] | None:
    active_markets = getattr(config, "active_markets", None)
    if active_markets is None:
        return None
    return {str(market).strip().lower() for market in active_markets if str(market).strip()}


def resolve_runtime_universe(config: Config) -> RuntimeUniverseResolution:
    watchlist = tuple(str(symbol).strip().upper() for symbol in getattr(config, "runtime_watchlist", ()) if str(symbol).strip())
    if watchlist:
        source = "CONFIG_EXPLICIT_ALLOWED:runtime_watchlist"
        symbols = watchlist
    else:
        symbols = tuple(str(symbol).strip().upper() for symbol in getattr(config, "symbol_universe", ()) if str(symbol).strip())
        source = "CONFIG_EXPLICIT_ALLOWED:symbol_universe" if symbols else "MISSING_UNIVERSE_TRUTH"

    if not symbols:
        return RuntimeUniverseResolution((), source, "MISSING_UNIVERSE_TRUTH")

    unknown = tuple(symbol for symbol in symbols if InstrumentRegistry.get_asset_class(symbol) is None)
    if unknown:
        return RuntimeUniverseResolution((), source, "UNKNOWN_SYMBOLS:" + ",".join(unknown))
    active_markets = _active_market_values(config)
    if active_markets is None:
        return RuntimeUniverseResolution(tuple(dict.fromkeys(symbols)), source, "UNIVERSE_READY")
    allowed_symbols = tuple(
        symbol
        for symbol in symbols
        if (asset_class := InstrumentRegistry.get_asset_class(symbol)) is not None
        and asset_class.value in active_markets
    )
    if not allowed_symbols:
        blocked_assets = tuple(
            dict.fromkeys(
                str(InstrumentRegistry.get_asset_class(symbol).value)
                for symbol in symbols
                if InstrumentRegistry.get_asset_class(symbol) is not None
            )
        )
        suffix = ":" + ",".join(blocked_assets) if blocked_assets else ""
        return RuntimeUniverseResolution((), source, "NO_ACTIVE_MARKET_SYMBOLS" + suffix)
    return RuntimeUniverseResolution(tuple(dict.fromkeys(allowed_symbols)), source, "UNIVERSE_READY")


def get_active_capability_candidates(
    config: Config,
    registry: VenueCapabilityRegistry | None = None,
    symbols: tuple[str, ...] | None = None,
) -> tuple[CapabilityAwareCandidate, ...]:
    """
    Return capability-aware runtime candidates for the configured universe.

    Venue, asset class, environment, quote source, execution adapter, and
    reconciliation adapter travel with each candidate. This is selection
    metadata only; it does not authorize broker mutation.
    """
    capability_registry = registry or build_default_capability_registry()
    environment = "paper" if config.broker_mode == "paper" else "live"
    discovery_mode = getattr(config, "capability_discovery_mode", "active_markets")
    discovery_markets = (
        getattr(config, "capability_discovery_asset_classes", config.active_markets)
        if discovery_mode == "registry"
        else config.active_markets
    )
    candidates = capability_registry.build_candidate_identities(
        symbols=symbols if symbols is not None else resolve_runtime_universe(config).symbols,
        active_markets=discovery_markets,
        environment=environment,
        discovery_mode=discovery_mode,
    )
    enabled_portals = {str(portal) for portal in getattr(config, "enabled_trading_portals", ())}
    if not enabled_portals:
        return candidates
    return tuple(
        candidate
        for candidate in candidates
        if candidate.portal_name in enabled_portals or f"{candidate.venue_id}_{candidate.environment}" in enabled_portals
    )


def get_configured_market_data_providers(config: Config, asset_class: str) -> tuple[str, ...]:
    normalized = str(asset_class or "").strip().lower()
    if normalized == "crypto":
        return tuple(getattr(config, "crypto_market_data_providers", ()) or getattr(config, "market_data_providers", ()))
    if normalized in {"equity", "us_equity", "etf"}:
        return tuple(getattr(config, "equity_market_data_providers", ()) or getattr(config, "market_data_providers", ()))
    if normalized == "options":
        return tuple(getattr(config, "options_market_data_providers", ()) or getattr(config, "market_data_providers", ()))
    return tuple(getattr(config, "market_data_providers", ()))


def provider_lane_for_asset_class(asset_class: str) -> str:
    normalized = str(asset_class or "").strip().lower()
    if normalized == "crypto":
        return FeedProviderLane.CRYPTO_MARKET_DATA.value
    if normalized in {"equity", "us_equity", "etf"}:
        return FeedProviderLane.EQUITY_ETF_MARKET_DATA.value
    if normalized == "options":
        return FeedProviderLane.OPTIONS_MARKET_DATA.value
    return FeedProviderLane.REFERENCE_MARKET_DATA.value


def resolve_runtime_portal(
    config: Config,
    *,
    symbol: str,
    asset_class: str | None = None,
    registry: VenueCapabilityRegistry | None = None,
):
    capability_registry = registry or build_default_capability_registry()
    environment = "paper" if config.broker_mode == "paper" else "live"
    return capability_registry.resolve(
        PortalSelectionRequest(
            symbol=symbol,
            asset_class=asset_class,
            environment=environment,
            policy_mode=config.portal_selection_policy,
            preferred_venue=config.preferred_trading_portal,
            allow_fallback=config.allow_portal_fallback,
        )
    )


class SovereignHeartbeat:
    """
    Top-level runtime wrapper.

    Owns:
    - assembly of runtime components
    - feed callback registration
    - process lifecycle start/stop
    - signal handler registration
    - health monitoring shell

    Does NOT own:
    - live market-data / brain / state processing
    - execution authority
    
    BUNDLE F1: Added telemetry_store initialization and injection.
    
    BUNDLE MULTI-SYMBOL RUNTIME: Per-symbol engines now created inside MainLoop.
    Trades now extract symbol from trade_info and route to MainLoop.on_trade().
    
    BUNDLE STRATEGY-GATING REPAIR: Also routes to MainLoop.on_trade_with_whale()
    with full trade details for per-symbol whale detection.
    """

    def __init__(
        self,
        config: Config,
        attack_mode: bool = False,
        bounded_duration_seconds: Optional[int] = None,
    ):
        self.config = config
        self.attack_mode = attack_mode
        self.bounded_duration_seconds = (
            int(bounded_duration_seconds)
            if bounded_duration_seconds is not None and int(bounded_duration_seconds) > 0
            else None
        )

        # BUNDLE F1: Initialize telemetry store
        self.telemetry_store = TelemetryEventStore(db_path="data/telemetry.db")
        logger.info("TelemetryEventStore initialized at data/telemetry.db")
        self.state_store = StateStore(db_path="data/state.db")
        logger.info("StateStore initialized at data/state.db")
        self._bootstrap_reservation_lifecycle_disabled(config)

        self.commander = Commander(
            initial_equity=config.initial_capital,
            target_equity=config.initial_capital * 2,
        )

        self.risk_guard = HybridRiskGuard(
            initial_equity=config.initial_capital,
            state_file="state/risk_state.json",
            backup_file="state/risk_state.backup",
            adaptive_floor_pct=0.15,
            physical_fuse_pct=0.25,
            vol_fuse_threshold_pct=0.04,
            vol_fuse_window_sec=60.0,
            tax_rate=0.25,
            max_latency_ms=200.0,
            zombie_order_timeout_sec=5.0,
            websocket_heartbeat_timeout_sec=10.0,
        )

        self.data_validator = DataContinuityValidator(
            max_sequence_gap=1,
            max_timestamp_gap_sec=2.0,
            max_stale_age_sec=5.0,
            recovery_required_good=3,
            websocket_heartbeat_timeout_sec=30.0,
        )

        (
            self._execution_broker,
            self._execution_primary_exchange,
            self._broker_gateway_adapter,
            self._execution_adapter_id,
        ) = resolve_execution_broker_gateway(config)
        logger.info(
            "Execution broker resolved: market_data_venue=%s execution_broker=%s execution_primary_exchange=%s execution_adapter=%s shadow_read_only=%s broker_mode=%s",
            config.primary_feed_venue,
            self._execution_broker,
            self._execution_primary_exchange,
            self._execution_adapter_id,
            bool(config.shadow_read_only),
            config.broker_mode,
        )

        # BUNDLE F1: Pass telemetry_store to OrderRouter
        self.order_router = OrderRouter(
            primary_exchange=self._execution_primary_exchange,
            secondary_exchange="coinbase",
            primary_api_key=config.kraken_api_key or "",
            primary_api_secret=config.kraken_api_secret or "",
            latency_threshold_ms=200.0,
            ghost_ratio_threshold=3.0,
            pcv_max_attempts=5,
            pcv_retry_delay_sec=0.5,
            rest_fallback_enabled=True,
            paper_mode=config.broker_mode == "paper",
            telemetry_store=self.telemetry_store,
            state_store=self.state_store,
            reservation_lifecycle_coordinator=self.reservation_lifecycle_coordinator,
            reservation_lifecycle_enabled=self.reservation_lifecycle_enabled,
            execution_broker=self._execution_broker,
            broker_gateway_adapter=self._broker_gateway_adapter,
            broker_read_profile=config.broker_read_permission_profile,
        )

        self.masking_layer = MaskingLayer(
            base_delay_ms=10.0,
            min_delay_ms=1.0,
            max_delay_ms=50.0,
            size_jitter_percent=0.01,
            size_jitter_distribution="gaussian",
            delay_jitter_distribution="exponential",
            volatility_adaptive=True,
            exchange="kraken",
        )

        self.signal_fusion = SignalFusion(config)
        self.whale_engine = WhaleFlowEngine()
        self.entropy_decoder = EntropyDecoder()
        self.safety_gate = SafetyGate(config)

        self.shans_curve = ShansCurve(
            risk_guard=self.risk_guard,
            safety_gate=self.safety_gate,
            data_validator=self.data_validator,
            entropy_decoder=self.entropy_decoder,
        )

        self.recalibrator = Recalibrator(
            fakeout_price_threshold_pct=0.05,
            fakeout_betti_threshold=2,
            fakeout_persistence_threshold=0.8,
            collapse_price_threshold_pct=0.05,
            collapse_betti_threshold=0,
            min_recalibration_seconds=3600.0,
            max_recalibration_seconds=14400.0,
            recovery_required_good=3,
        )

        # BUNDLE F1: Pass telemetry_store to ExecutionEngine
        self.execution_engine = ExecutionEngine(
            commander=self.commander,
            risk_guard=self.risk_guard,
            order_router=self.order_router,
            masking_layer=self.masking_layer,
            data_validator=self.data_validator,
            signal_ttl_ms=500.0,
            price_sanity_threshold_pct=0.02,
            zombie_sweep_interval_sec=5.0,
            max_pending_age_sec=5.0,
            lag_threshold_ms=200.0,
            recalibration_pause_sec=14400.0,
            maker_offset_pct=0.001,
            emergency_cancel_workers=10,
            telemetry_store=self.telemetry_store,
            shadow_read_only=config.shadow_read_only,
        )

        self._universe_resolution = resolve_runtime_universe(config)
        if not self._universe_resolution.symbols:
            raise RuntimeError(self._universe_resolution.reason)
        self._runtime_universe_symbols = self._universe_resolution.symbols
        self._primary_symbol = self._runtime_universe_symbols[0]
        primary_asset_class = InstrumentRegistry.get_asset_class(self._primary_symbol)
        primary_asset_class_value = primary_asset_class.value if primary_asset_class else "crypto"
        self._configured_market_data_providers = get_configured_market_data_providers(
            config,
            primary_asset_class_value,
        )
        self._feed_provider_router = build_feed_provider_router(
            configured_provider_ids=self._configured_market_data_providers,
            env=os.environ,
        )
        self._market_data_provider_selection = self._feed_provider_router.select_provider(
            FeedProviderRequest(
                symbol=self._primary_symbol,
                asset_class=primary_asset_class_value,
                required_data_type="order_book",
                provider_lane=provider_lane_for_asset_class(primary_asset_class_value),
                execution_required=True,
            )
        )
        selected_market_data_provider = self._market_data_provider_selection.selected_provider_id
        if selected_market_data_provider is None:
            raise RuntimeError(self._market_data_provider_selection.reason)
        selected_feed_venue = _FEED_PROVIDER_TO_VENUE.get(str(selected_market_data_provider or ""))
        if not selected_feed_venue:
            raise RuntimeError(f"MISSING_TRANSPORT:{selected_market_data_provider}")
        if config.primary_feed_venue and selected_feed_venue != config.primary_feed_venue:
            raise RuntimeError(
                "selected_market_data_provider_venue_mismatch:"
                f"{selected_market_data_provider}:{selected_feed_venue}!={config.primary_feed_venue}"
            )
        self._primary_feed_venue = selected_feed_venue
        self._selected_market_data_provider_id = selected_market_data_provider
        if hasattr(self.order_router, "set_market_data_latency_source"):
            latency_source = "websocket" if self._primary_feed_venue == "kraken" else "rest_polling"
            self.order_router.set_market_data_latency_source(latency_source)
            logger.info(
                "Market-data latency source selected: provider=%s venue=%s source=%s",
                self._selected_market_data_provider_id,
                self._primary_feed_venue,
                latency_source,
            )
        logger.info(
            "Market-data provider resolved: %s",
            self._market_data_provider_selection.to_telemetry(),
        )
        logger.info(
            "Runtime universe resolved: source=%s count=%d symbols=%s",
            self._universe_resolution.source,
            len(self._runtime_universe_symbols),
            self._runtime_universe_symbols,
        )
        self._capability_candidates = get_active_capability_candidates(
            config,
            symbols=self._runtime_universe_symbols,
        )
        selected_provider_asset_classes = set(self._market_data_provider_selection.selected_provider.asset_classes)
        self._feed_symbols = sorted(
            symbol
            for symbol in self._runtime_universe_symbols
            if (
                (asset_class := InstrumentRegistry.get_asset_class(symbol))
                and asset_class.value in selected_provider_asset_classes
            )
        )
        if not self._feed_symbols:
            raise RuntimeError("MISSING_MARKET_DATA_COVERAGE_FOR_UNIVERSE")

        # Get active symbols set for multi-symbol support
        self._active_symbols = set(self._feed_symbols)
        logger.info("Active symbols for paper trading: %s", self._active_symbols)
        logger.info(
            "Capability-aware runtime candidates: %s",
            [
                {
                    "symbol": candidate.raw_symbol,
                    "venue": candidate.venue_id,
                    "asset_class": candidate.asset_class,
                    "environment": candidate.environment,
                    "execution_adapter": candidate.execution_adapter,
                    "tradable": candidate.tradable,
                    "mutation_authorized": candidate.mutation_authorized,
                    "fail_closed_reason": candidate.fail_closed_reason_code,
                }
                for candidate in self._capability_candidates
            ],
        )

        # BUNDLE MULTI-SYMBOL RUNTIME: Per-symbol engines are now created
        # inside MainLoop's SymbolRuntime containers. Legacy single-symbol
        # instances are no longer created here.
        self.regime_detector = RegimeDetector()  # Global, used per-symbol
        self.physical_validator = PhysicalValidator()  # Global, used per-symbol
        self.insider_engine = InsiderSignalEngine()  # Global, used per-symbol

        # BUNDLE F1: Pass telemetry_store to MainLoop via create_main_loop
        self.main_loop = create_main_loop(
            config=config,
            commander=self.commander,
            risk_guard=self.risk_guard,
            signal_fusion=self.signal_fusion,
            data_validator=self.data_validator,
            recalibrator=self.recalibrator,
            shans_curve=self.shans_curve,
            tpe_engine=None,  # Created per-symbol in MainLoop
            regime_detector=self.regime_detector,
            physical_validator=self.physical_validator,
            toxicity_engine=None,  # Created per-symbol in MainLoop
            entropy_decoder=self.entropy_decoder,
            insider_engine=self.insider_engine,
            execution_engine=self.execution_engine,
            symbol=self._primary_symbol,
            exchange=self._primary_feed_venue,
            safety_gate=self.safety_gate,
            telemetry_store=self.telemetry_store,
            active_symbols=self._active_symbols,
        )
        self._record_whole_bot_startup_attribution()

        self._running = False
        self._stopping = False
        self._threads: list[threading.Thread] = []
        self._health_check_interval = 5.0
        self._signal_handlers_registered = False
        self._stop_event = threading.Event()

        # Temporary diagnostics preserved
        self._candle_recv_count = 0
        self._book_recv_count = 0

        self._register_graceful_death()

        logger.info("SovereignHeartbeat initialized")
        logger.info("Attack Mode: %s", "ENABLED" if attack_mode else "DISABLED")
        logger.info("Broker Mode: %s", config.broker_mode)
        logger.info("Shadow Read Only: %s", "ENABLED" if config.shadow_read_only else "DISABLED")
        logger.info("Initial Capital: $%0.2f", config.initial_capital)
        logger.info("Primary symbol: %s", self._primary_symbol)
        logger.info("Active symbols: %s", self._active_symbols)

    def _record_whole_bot_startup_attribution(self) -> None:
        ts_ns = now_ns()
        attribution = build_startup_attribution(
            timestamp_ns=ts_ns,
            broker_mode=str(getattr(self.config, "broker_mode", "unknown")),
            shadow_read_only=bool(getattr(self.config, "shadow_read_only", False)),
            active_symbols=self._active_symbols,
            capability_candidates=self._capability_candidates,
        )
        self.telemetry_store.record_event(
            EventEnvelope(
                event_type=EventType.AUDIT_EVENT,
                source_module="main.whole_bot_startup_attribution",
                exchange_ts_ns=ts_ns,
                receive_ts_ns=ts_ns,
                decision_ts_ns=0,
                payload={
                    "edge_attribution": attribution,
                    "shadow_read_only": bool(getattr(self.config, "shadow_read_only", False)),
                    "broker_mutation_counts": self.execution_engine.get_shadow_broker_mutation_counts(),
                    "live_mode": False,
                },
            )
        )

    def _bootstrap_reservation_lifecycle_disabled(self, config: Config) -> None:
        """
        Root-owned reservation runtime bootstrap.

        This creates and hydrates objects only. It does not wire lifecycle call
        sites, does not issue broker commands, and keeps activation disabled.
        """
        reservation_lifecycle_paper_requested = bool(
            getattr(config, "reservation_lifecycle_paper_enabled", False)
        )
        reservation_lifecycle_is_paper = str(getattr(config, "broker_mode", "")).lower() == "paper"
        self.reservation_lifecycle_enabled = bool(
            reservation_lifecycle_paper_requested and reservation_lifecycle_is_paper
        )
        self.exposure_manager = ExposureManager(
            initial_equity=Decimal(str(config.initial_capital)),
        )

        active_rows = []
        release_tombstones = []
        fill_progress = []
        hydrate_result: Dict[str, Any] = {
            "hydrated": (),
            "skipped": (),
            "valid": True,
            "violations": (),
            "warnings": (),
        }
        hydrate_failed = False
        failed_reason = None

        try:
            active_rows = self.state_store.list_reservation_ledger(
                active_only=True,
                include_terminal=False,
            )
            for row in active_rows:
                reservation_id = row.get("reservation_id")
                if not reservation_id:
                    continue
                tombstone = self.state_store.get_reservation_release_tombstone(
                    reservation_id=reservation_id,
                )
                if tombstone is not None:
                    release_tombstones.append(tombstone)
                fill_progress.extend(
                    self.state_store.list_reservation_fill_progress(reservation_id)
                )

            hydrate_result = self.exposure_manager.hydrate_reservations_from_ledger(
                active_rows,
                release_tombstones=release_tombstones,
                fill_progress=fill_progress,
            )
            if not hydrate_result.get("valid", False):
                hydrate_failed = True
                failed_reason = "exposure_manager_hydrate_invariant_failed"
        except Exception as exc:
            hydrate_failed = True
            failed_reason = f"exposure_manager_hydrate_failed:{exc}"
            logger.exception("Reservation lifecycle disabled after hydrate failure: %s", exc)

        self.reservation_lifecycle_coordinator = ReservationLifecycleCoordinator(
            exposure_manager=self.exposure_manager,
            state_store=self.state_store,
        )
        self.reservation_lifecycle_bootstrap_status = {
            "exposure_manager_created": self.exposure_manager is not None,
            "coordinator_created": self.reservation_lifecycle_coordinator is not None,
            "reservation_lifecycle_paper_requested": reservation_lifecycle_paper_requested,
            "reservation_lifecycle_enabled": self.reservation_lifecycle_enabled,
            "reservation_lifecycle_scope": "paper" if self.reservation_lifecycle_enabled else "disabled",
            "reservation_lifecycle_live_blocked": bool(
                reservation_lifecycle_paper_requested and not reservation_lifecycle_is_paper
            ),
            "active_ledger_row_count": len(active_rows),
            "release_tombstone_count": len(release_tombstones),
            "fill_progress_row_count": len(fill_progress),
            "hydrated_reservation_count": len(hydrate_result.get("hydrated") or ()),
            "skipped_reservation_count": len(hydrate_result.get("skipped") or ()),
            "hydrate_failed": hydrate_failed,
            "failed_reason": failed_reason,
            "hydrate_result": hydrate_result,
            "runtime_lifecycle_wired": False,
            "telemetry_authority_used": False,
            "broker_command_performed": False,
        }

    # ============================================
    # GRACEFUL SHUTDOWN
    # ============================================

    def _register_graceful_death(self) -> None:
        if threading.current_thread() is not threading.main_thread():
            logger.debug("Skipping signal handler registration outside main thread")
            return

        def death_handler(signum, frame):
            del frame
            logger.critical("SYSTEM TERMINATION SIGNAL RECEIVED: %s", signum)
            logger.critical("INITIATING GRACEFUL SHUTDOWN SEQUENCE")
            self._handle_termination_signal(signum)

        try:
            signal.signal(signal.SIGINT, death_handler)
            signal.signal(signal.SIGTERM, death_handler)
            self._signal_handlers_registered = True
            logger.info("Graceful shutdown handlers registered")
        except (ValueError, RuntimeError, AttributeError) as exc:
            logger.warning("Could not register signal handlers: %s", exc)

    def _handle_termination_signal(self, signum: int) -> None:
        if self._stopping:
            logger.warning(
                "Termination signal received during active shutdown: %s",
                signum,
            )
            return

        self._stopping = True
        self._running = False
        self._stop_event.set()

        try:
            self.execution_engine.stop()
        except Exception as exc:
            logger.exception(
                "Failed stopping execution engine during signal shutdown: %s",
                exc,
            )

        try:
            self.order_router.close_all_positions()
            logger.critical("PORTFOLIO FLATTENED - SAFE TO EXIT")
        except Exception as exc:
            logger.exception(
                "Failed to flatten portfolio during signal shutdown: %s",
                exc,
            )

    # ============================================
    # PUBLIC METHODS
    # ============================================

    def start(self) -> None:
        """Start the runtime."""
        if self._running:
            logger.warning("Heartbeat already running")
            return

        self._stopping = False
        self._running = True
        self._stop_event.clear()

        if self.attack_mode:
            self.commander.enable_attack_mode(
                reason="cli_flag",
                timestamp_ns=time.time_ns(),
            )
            logger.info("ATTACK MODE ENABLED")

        self.execution_engine.start()
        self.main_loop.start()
        self._start_background_threads()
        self._start_bounded_duration_timer()

        logger.info(
            "Runtime started: main.py owns lifecycle/feed shell; MainLoop owns live runtime body"
        )

        self._wait_until_stopped()

    def stop(self) -> None:
        """Stop the runtime."""
        if self._stopping:
            logger.debug("Heartbeat stop already in progress")

        self._stopping = True

        if not self._running:
            logger.info("Sovereign heartbeat already stopped or stopping")
        else:
            logger.info("Stopping sovereign heartbeat")

        self._running = False
        self._stop_event.set()

        try:
            self.main_loop.stop()
        except Exception as exc:
            logger.exception("Error stopping main loop: %s", exc)

        try:
            self.execution_engine.stop()
        except Exception as exc:
            logger.exception("Error stopping execution engine: %s", exc)

        try:
            self._emit_oms_shutdown_accounting()
        except Exception as exc:
            logger.exception("Error emitting OMS shutdown accounting: %s", exc)

        try:
            self.state_store.close()
        except Exception as exc:
            logger.exception("Error closing state store: %s", exc)

        self._join_background_threads()
        logger.info("Sovereign heartbeat stopped")

    def _emit_oms_shutdown_accounting(self) -> None:
        getter = getattr(self.execution_engine, "get_oms_shutdown_accounting", None)
        accounting = getter() if callable(getter) else {}
        logger.info("[OMS_DIAG] SHUTDOWN_ACCOUNTING fields=%s", accounting)

    def _wait_until_stopped(self) -> None:
        """
        Block the main thread while the event-driven runtime is alive.

        This is lifecycle waiting only. It does not perform market-data,
        fusion, risk, or execution ownership work.
        """
        logger.info("Entering runtime wait state")
        try:
            while self._running and not self._stop_event.wait(timeout=1.0):
                pass
        except KeyboardInterrupt:
            logger.info("Keyboard interrupt received in runtime wait state")
            self._running = False
            self._stop_event.set()

    def _start_background_threads(self) -> None:
        health_thread = threading.Thread(
            target=self._health_check_loop,
            name="pk-health-check",
            daemon=True,
        )
        health_thread.start()
        self._threads.append(health_thread)

        self._start_whale_websocket()
        self._start_polling_client()

    def _start_bounded_duration_timer(self) -> None:
        if self.bounded_duration_seconds is None:
            return

        duration = int(self.bounded_duration_seconds)

        def bounded_timer() -> None:
            logger.info(
                "[OMS_DIAG] BOUNDED_RUNTIME_TIMER_STARTED fields=%s",
                {
                    "duration_seconds": duration,
                    "shutdown_mode": "graceful_self_stop",
                    "broker_post": False,
                },
            )
            if self._stop_event.wait(timeout=float(duration)):
                return
            logger.info(
                "[OMS_DIAG] BOUNDED_RUNTIME_DURATION_ELAPSED fields=%s",
                {
                    "duration_seconds": duration,
                    "shutdown_mode": "graceful_self_stop",
                    "broker_post": False,
                },
            )
            self._running = False
            self._stop_event.set()

        timer_thread = threading.Thread(
            target=bounded_timer,
            name="pk-bounded-duration",
            daemon=True,
        )
        timer_thread.start()
        self._threads.append(timer_thread)

    def _join_background_threads(self) -> None:
        current = threading.current_thread()
        live_threads: list[threading.Thread] = []

        for thread in self._threads:
            if thread is current:
                continue
            if thread.is_alive():
                thread.join(timeout=2.0)
            if thread.is_alive():
                live_threads.append(thread)

        self._threads = live_threads

    def _on_trade(self, trade_info: dict) -> None:
        """
        Feed callback from KrakenWebSocketClient.

        Transport/callback ownership lives here.
        Semantic market-data processing remains in MainLoop.
        
        BUNDLE MULTI-SYMBOL RUNTIME: Extracts symbol from trade_info
        and passes to MainLoop.on_trade() with the real symbol.
        No longer assumes primary symbol only.
        
        BUNDLE STRATEGY-GATING REPAIR: Also passes full trade details
        to MainLoop.on_trade_with_whale() for per-symbol whale detection.
        """
        try:
            volume = float(trade_info.get("volume", 0.0))
            price = float(trade_info.get("price", 0.0))
            side = int(trade_info.get("side", 0))
            ts_ns = int(trade_info.get("exchange_ts_ns", 0))
            symbol = trade_info.get("symbol", self._primary_symbol)

            if ts_ns <= 0 or volume <= 0:
                return

            buy_vol = volume if side == 1 else 0.0
            sell_vol = volume if side == -1 else 0.0

            alert = self.whale_engine.update(
                buy_volume=buy_vol,
                sell_volume=sell_vol,
                trade_sizes=[volume],
                exchange_ts_ns=ts_ns,
            )

            self.signal_fusion.update_whale(alert, ts_ns)
            
            # Pass symbol to MainLoop.on_trade() (basic price update)
            self.main_loop.on_trade(symbol, price, ts_ns)
            
            # Pass full trade details to MainLoop.on_trade_with_whale() (whale detection)
            self.main_loop.on_trade_with_whale(symbol, price, side, volume, ts_ns)

            # Insider observation uses the real symbol from trade_info
            if side == 1:
                obs_direction = ObservationDirection.BUY
            elif side == -1:
                obs_direction = ObservationDirection.SELL
            else:
                obs_direction = ObservationDirection.UNKNOWN

            # Get per-symbol suppression factor from runtime if available
            runtime = self.main_loop.get_runtime(symbol)
            if runtime and runtime.toxicity_engine:
                tox_suppression = runtime.toxicity_engine.get_suppression_factor()
            else:
                # Fallback to primary symbol's toxicity engine
                primary_runtime = self.main_loop.get_runtime(self._primary_symbol)
                tox_suppression = primary_runtime.toxicity_engine.get_suppression_factor() if primary_runtime and primary_runtime.toxicity_engine else 1.0

            tox_inv = Decimal(str(round(1.0 - tox_suppression, 6)))
            intensity = Decimal(str(round(min(1.0, max(0.0, alert.confidence)), 6)))
            notional = Decimal(str(round(min(1.0, max(0.0, alert.avg_trade_size)), 6)))

            obs = InsiderObservation(
                observation_id=f"{symbol}_{ts_ns}",
                timestamp_ns=ts_ns,
                symbol=symbol,
                entity_id="",
                direction=obs_direction,
                intensity=intensity,
                notional_weight=notional,
                source_reliability=Decimal("0.35"),
                event_proximity_weight=Decimal("0.0"),
                novelty_weight=Decimal("0.0"),
                corroboration_weight=Decimal("0.25") if side != 0 and int(alert.direction.value) == side else Decimal("0.0"),
                invalidation_weight=tox_inv,
                source_type=ObservationSourceType.FLOW,
            )
            try:
                self.insider_engine.ingest_observation(obs)
            except Exception as exc_inner:
                logger.debug("insider ingest_observation error: %s", exc_inner)

        except Exception as exc:
            logger.exception("_on_trade error: %s", exc)

    def _on_candle(self, candle: Candle) -> None:
        """Feed callback routing authoritative candles into MainLoop."""
        self._candle_recv_count += 1
        if self._candle_recv_count <= 3 or self._candle_recv_count % 100 == 0:
            logger.info(
                "FEED_CANDLE #%d: symbol=%s exchange_ts_ns=%d",
                self._candle_recv_count,
                candle.symbol,
                candle.exchange_ts_ns,
            )
        try:
            self.main_loop.on_candle(candle)
        except Exception as exc:
            logger.exception("_on_candle error: %s", exc)

    def _on_feed_truth(self, feed_truth: dict) -> None:
        """
        Feed-truth callback for provider-router telemetry only.

        This records deterministic failover selection metadata without treating
        an unstarted fallback provider as market truth.
        """
        status = str(feed_truth.get("status", ""))
        reason_code = _REST_FEED_FAILURE_REASON_MAP.get(status, status or "REST_UNAVAILABLE")
        provider_status = ProviderRuntimeStatus(
            provider_id=self._selected_market_data_provider_id,
            health=FeedProviderHealth.FAILED.value if reason_code == "DNS_FAILURE" else FeedProviderHealth.DEGRADED.value,
            reason_codes=(reason_code,),
            last_error=str(feed_truth.get("exception_type", "")) or None,
        )
        selection = self._feed_provider_router.select_provider(
            FeedProviderRequest(
                symbol=str(feed_truth.get("symbol") or self._primary_symbol),
                asset_class="crypto",
                required_data_type=str(feed_truth.get("feed_type") or "order_book"),
                provider_lane=FeedProviderLane.CRYPTO_MARKET_DATA.value,
                execution_required=True,
            ),
            provider_status={self._selected_market_data_provider_id: provider_status},
        )
        logger.info(
            "Market-data provider failover telemetry: %s",
            selection.to_telemetry(),
        )
        if (
            selection.selected_provider_id
            and selection.selected_provider_id != self._selected_market_data_provider_id
        ):
            logger.warning(
                "Market-data fallback candidate selected but active transport remains %s: candidate=%s",
                self._selected_market_data_provider_id,
                selection.selected_provider_id,
            )

    def _on_rest_latency(self, latency_truth: dict) -> None:
        """Route REST polling latency truth into the execution latency authority."""
        try:
            self.order_router.update_rest_market_data_latency(
                request_start_ns=int(latency_truth.get("request_start_ns") or 0),
                response_received_ns=int(latency_truth.get("response_received_ns") or 0),
                exchange=str(latency_truth.get("exchange") or self._primary_feed_venue),
                provider_id=self._selected_market_data_provider_id,
                symbol=str(latency_truth.get("symbol") or ""),
                feed_type=str(latency_truth.get("feed_type") or ""),
            )
        except Exception as exc:
            logger.exception("REST latency truth routing error: %s", exc)

    def _start_whale_websocket(self) -> None:
        """
        Launch venue WebSocket client in a background asyncio daemon thread.

        This is transport startup and callback registration ownership only.
        
        WEBSOCKET HEALTH WIRING: Registers health callback to order_router.
        """
        ws_symbols = self._feed_symbols
        if not ws_symbols:
            logger.warning(
                "No feed symbols for venue %r — whale WebSocket not started",
                self._primary_feed_venue,
            )
            return
        if self._primary_feed_venue != "kraken":
            logger.info(
                "No WebSocket transport active for market-data venue %r; "
                "using REST polling transport for supported data types",
                self._primary_feed_venue,
            )
            return

        running_ref = self

        async def _ws_run() -> None:
            ws_client = KrakenWebSocketClient(
                symbols=ws_symbols,
                on_order_book=running_ref._on_order_book,
                on_trade=running_ref._on_trade,
                on_candle=running_ref._on_candle,
                sentinel=running_ref.safety_gate,
                on_health=running_ref.order_router.update_websocket_health,
            )
            
            logger.info("WebSocket health callback wired to order_router.update_websocket_health")
            
            try:
                await ws_client.start()
                while running_ref._running:
                    await asyncio.sleep(1.0)
            except Exception as exc:
                logger.exception("Whale WebSocket run error: %s", exc)
            finally:
                try:
                    await ws_client.stop()
                except Exception:
                    pass

        def _thread_main() -> None:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(_ws_run())
            except Exception as exc:
                logger.exception("Whale WebSocket thread error: %s", exc)
            finally:
                loop.close()

        whale_ws_thread = threading.Thread(
            target=_thread_main,
            name="pk-whale-ws",
            daemon=True,
        )
        whale_ws_thread.start()
        self._threads.append(whale_ws_thread)
        logger.info(
            "Whale WebSocket thread started (%d symbols: %s)",
            len(ws_symbols),
            ws_symbols,
        )

    def _on_order_book(self, snapshot) -> None:
        """Feed callback routing order books into MainLoop."""
        self._book_recv_count += 1
        if self._book_recv_count <= 3 or self._book_recv_count % 100 == 0:
            logger.info(
                "FEED_BOOK #%d: symbol=%s exchange_ts_ns=%d",
                self._book_recv_count,
                snapshot.symbol,
                snapshot.exchange_ts_ns,
            )
        try:
            self.main_loop.on_order_book(snapshot)
        except Exception as exc:
            logger.exception("_on_order_book error: %s", exc)

    def _start_polling_client(self) -> None:
        """
        Launch PollingClient in a background asyncio daemon thread.

        This is transport startup and callback registration ownership only.
        """
        poll_symbols = self._feed_symbols
        if not poll_symbols:
            logger.warning(
                "No feed symbols for venue %r — PollingClient not started",
                self._primary_feed_venue,
            )
            return

        running_ref = self

        async def _poll_run() -> None:
            selected_provider = running_ref._market_data_provider_selection.selected_provider
            client = PollingClient(
                symbols=poll_symbols,
                interval=1.0,
                on_order_book=running_ref._on_order_book,
                on_candle=running_ref._on_candle,
                on_feed_truth=running_ref._on_feed_truth,
                on_rest_latency=running_ref._on_rest_latency,
                exchange=running_ref._primary_feed_venue,
                provider_id=running_ref._selected_market_data_provider_id,
                freshness_policy=(
                    selected_provider.freshness_policy
                    if selected_provider is not None
                    else None
                ),
            )
            try:
                await client.start()
                while running_ref._running:
                    await asyncio.sleep(1.0)
            except Exception as exc:
                logger.exception("PollingClient run error: %s", exc)
            finally:
                try:
                    await client.stop()
                except Exception:
                    pass

        def _thread_main() -> None:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(_poll_run())
            except Exception as exc:
                logger.exception("PollingClient thread error: %s", exc)
            finally:
                loop.close()

        polling_thread = threading.Thread(
            target=_thread_main,
            name="pk-polling",
            daemon=True,
        )
        polling_thread.start()
        self._threads.append(polling_thread)
        logger.info("PollingClient thread started (%d symbols)", len(poll_symbols))

    # ============================================
    # HEALTH CHECK
    # ============================================

    def _health_check_loop(self) -> None:
        """Background health check loop."""
        while self._running:
            try:
                time.sleep(self._health_check_interval)
                if not self._running:
                    break
                self._perform_health_check()
            except Exception as exc:
                logger.exception("Health check error: %s", exc)

    def _perform_health_check(self) -> None:
        """Perform system health check."""
        status = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "heartbeat": self._running,
            "execution_engine": self.execution_engine.get_status(),
            "risk_guard": self.risk_guard.get_status(),
            "order_router": self.order_router.get_ghost_status(),
            "commander": self.commander.get_status(),
            "recalibrator": self.recalibrator.get_status(),
            "main_loop": self.main_loop.get_status(),
        }

        if status["risk_guard"]["physical_fuse_triggered"]:
            logger.critical("HEALTH ALERT: Physical fuse triggered!")

        if status["risk_guard"]["vol_fuse_triggered"]:
            logger.critical("HEALTH ALERT: VoL fuse triggered!")

        ws_connected = status["order_router"]["websocket_connected"]
        latency_source = status["order_router"].get("market_data_latency_source")
        if self._primary_feed_venue == "kraken" and not ws_connected:
            logger.warning("HEALTH ALERT: WebSocket disconnected!")
        elif latency_source == "rest_polling" and not math.isfinite(
            float(status["order_router"].get("rest_market_data_rtt_ms", float("inf")))
        ):
            logger.warning("HEALTH ALERT: REST feed latency not ready!")

        logger.debug("Health check: %s", status["execution_engine"]["is_running"])

    def _log_health(self) -> None:
        """Log system health summary."""
        risk_status = self.risk_guard.get_status()
        execution_status = self.execution_engine.get_status()

        status = {
            "mode": "ATTACK" if self.commander.is_attack_mode() else "SAFE",
            "equity": risk_status["current_equity"],
            "tradeable_equity": risk_status["tradeable_equity"],
            "drawdown": risk_status["drawdown_from_peak"],
            "pending_orders": execution_status["pending_orders_count"],
            "queue_size": execution_status["execution_queue_size"],
            "websocket": self.order_router.is_websocket_connected(),
        }
        logger.info("Health Summary: %s", status)

    # ============================================
    # DIAGNOSTICS
    # ============================================

    def get_status(self) -> Dict[str, Any]:
        """Get system status."""
        return {
            "running": self._running,
            "attack_mode": self.commander.is_attack_mode(),
            "execution": self.execution_engine.get_status(),
            "risk": self.risk_guard.get_status(),
            "commander": self.commander.get_status(),
            "recalibrator": self.recalibrator.get_status(),
            "shans_curve": self.shans_curve.get_stats(),
            "main_loop": self.main_loop.get_status(),
            "active_symbols": list(self._active_symbols),
            "capability_candidates": [
                {
                    "symbol": candidate.raw_symbol,
                    "venue": candidate.venue_id,
                    "asset_class": candidate.asset_class,
                    "environment": candidate.environment,
                    "execution_adapter": candidate.execution_adapter,
                    "reconciliation_adapter": candidate.reconciliation_adapter,
                    "tradable": candidate.tradable,
                    "mutation_authorized": candidate.mutation_authorized,
                }
                for candidate in self._capability_candidates
            ],
            "primary_symbol": self._primary_symbol,
            "market_data_venue": self._primary_feed_venue,
            "universe_source": self._universe_resolution.source,
            "candidate_count": len(self._runtime_universe_symbols),
            "market_data_provider_selection": self._market_data_provider_selection.to_telemetry(),
            "provider_priority_list": self._configured_market_data_providers,
            "fallback_used": self._market_data_provider_selection.reason == "FALLBACK_SELECTED",
            "missing_universe_feed_truth_reason": (
                None
                if self._universe_resolution.reason == "UNIVERSE_READY"
                else self._universe_resolution.reason
            ),
            "execution_broker": self._execution_broker,
            "execution_primary_exchange": self._execution_primary_exchange,
            "execution_adapter": self._execution_adapter_id,
            "order_router": self.order_router.get_ghost_status(),
        }


# ============================================
# ENTRY POINT
# ============================================


def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Poverty Killer - Sovereign Trading Engine"
    )
    parser.add_argument(
        "--attack",
        action="store_true",
        help="Enable attack mode on startup (0.85 Kelly, aggressive strategies)",
    )
    parser.add_argument(
        "--paper",
        action="store_true",
        help="Force paper trading mode (overrides .env)",
    )
    parser.add_argument(
        "--shadow-read-only",
        action="store_true",
        help="Run full runtime read-only: compile decisions and telemetry, block broker mutation.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Set logging level",
    )
    parser.add_argument(
        "--config",
        default=".env",
        help="Path to configuration file",
    )
    parser.add_argument(
        "--duration-seconds",
        type=int,
        default=None,
        help="Optional bounded runtime duration before graceful self-shutdown.",
    )
    args = parser.parse_args()
    if args.duration_seconds is not None and not (1 <= args.duration_seconds <= 432000):
        parser.error("--duration-seconds must be between 1 and 432000")
    return args


def main() -> int:
    """Main entry point."""
    args = parse_arguments()

    load_dotenv(args.config)
    config = Config.from_env()

    if args.paper:
        config.broker_mode = "paper"
    if args.shadow_read_only:
        config.shadow_read_only = True
        config.broker_mode = "paper"

    setup_logger(config, level=args.log_level)

    paper_baseline_context = load_paper_baseline_runtime_context_from_env(os.environ)
    if paper_baseline_context.baseline_required and not paper_baseline_context.baseline_loaded:
        logger.critical(
            "PAPER_BASELINE_RUNTIME_CONTEXT_REQUIRED fields=%s",
            paper_baseline_context.to_dict(),
        )
        return 1
    config.paper_baseline_runtime_context = paper_baseline_context.to_dict()
    broker_read_profile = broker_read_profile_from_env(os.environ)
    config.broker_read_permission_profile = broker_read_profile.to_dict()

    logger.info("=" * 60)
    logger.info("POVERTY KILLER - SOVEREIGN TRADING ENGINE")
    logger.info("=" * 60)
    logger.info("Version: 1.0.0")
    logger.info("Attack Mode: %s", "ENABLED" if args.attack else "DISABLED")
    logger.info("Broker Mode: %s", config.broker_mode)
    logger.info("Shadow Read Only: %s", "ENABLED" if config.shadow_read_only else "DISABLED")
    logger.info("Initial Capital: $%0.2f", config.initial_capital)
    logger.info("Target: $%0.2f", config.initial_capital * 2)
    if args.paper:
        logger.info("Paper mode forced via command line")
    if args.shadow_read_only:
        logger.info("Shadow read-only mode forced via command line")
    if paper_baseline_context.baseline_required:
        logger.info(
            "PAPER baseline runtime context loaded: snapshot=%s protected_symbols=%s guard_active=%s",
            paper_baseline_context.baseline_snapshot_id,
            paper_baseline_context.protected_symbols_count,
            paper_baseline_context.same_symbol_baseline_guard_active,
        )
    logger.info(
        "Broker read profile loaded: profile=%s allowed=%s account_activities=%s fee_hydration=%s",
        broker_read_profile.name,
        ",".join(sorted(broker_read_profile.allowed_families)),
        broker_read_profile.account_activity_reads_allowed,
        broker_read_profile.fee_hydration_allowed,
    )
    logger.info("=" * 60)

    heartbeat = SovereignHeartbeat(
        config,
        attack_mode=args.attack,
        bounded_duration_seconds=args.duration_seconds,
    )

    try:
        heartbeat.start()
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received")
    except Exception as exc:
        logger.exception("Fatal error: %s", exc)
        return 1
    finally:
        heartbeat.stop()

    logger.info("Poverty Killer shutdown complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
