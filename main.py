#!/usr/bin/env python
"""
Poverty Killer - Sovereign Trading Engine
Main entry point for current paper-trading bring-up.

Responsibilities:
- Parse CLI arguments
- Load environment configuration
- Initialize top-level runtime components
- Start and stop the current runtime cleanly
"""

import argparse
import asyncio
import logging
import signal
import sys
import threading
import time
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict

from dotenv import load_dotenv

from app.instrument_registry import InstrumentRegistry
from app.models.enums import ExchangeType
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
from app.brain.topological_engine import TopologicalEngine
from app.brain.toxicity_engine import ToxicityEngine
from app.commander import Commander
from app.config import Config
from app.execution.engine import ExecutionEngine
from app.execution.masking_layer import MaskingLayer
from app.execution.order_router import OrderRouter
from app.brain.whale_flow_engine import WhaleFlowEngine
from app.data.polling_client import PollingClient
from app.data.websocket_client import KrakenWebSocketClient
from app.main_loop import MainLoop, create_main_loop
from app.models import Candle
from app.monitoring.logger import setup_logger
from app.risk.guard import HybridRiskGuard
from app.risk.safety import SafetyGate

logger = logging.getLogger(__name__)


# ============================================
# VENUE + MARKET SEAM — symbol filter and fallback
# ============================================
# Bot-controlled mapping: venue → registry-backed exchange predicate.
# User-controlled selection: Config.primary_feed_venue + Config.active_markets.
#
# Classification authority: InstrumentRegistry (app/instrument_registry.py).
# Symbols not registered are excluded and logged — not silently included.
#
# Extension point: to add a second venue/market, add one entry here and update:
#   - Config.primary_feed_venue Literal
#   - Config.active_markets validator valid set
#   - SovereignHeartbeat._start_whale_websocket() branch
#   - PollingClient._endpoints dict (app/data/polling_client.py)
#
# NAMED PARALLEL BRANCH — NOT MERGED, NOT DANGEROUS WHILE DISCONNECTED:
# models/unified_market.py defines its own AssetClass, Exchange, InstrumentSpec.
# These are NOT the canonical types and are NOT type-compatible with this spine.
# Consumers (aggregator.py, ghost_tick_detector.py, hydration_manager.py) are
# also disconnected. See unified_market.py docstring for exact wire-up preconditions.

_VENUE_SYMBOL_FILTER: dict = {
    # Predicate: symbol belongs to this venue's exchange per InstrumentRegistry.
    # Replace format heuristic ("/" in s) with authoritative registry lookup.
    "kraken": lambda s: InstrumentRegistry.get_exchange(s) == ExchangeType.KRAKEN,
}

_VENUE_PRIMARY_SYMBOL_FALLBACK: dict = {
    "kraken": "XBT/USD",
}


def _feed_symbols_for_venue(venue: str, universe: list, active_markets: list) -> list:
    """
    Return symbols from universe that satisfy ALL THREE conditions:
      1. Belong to the given venue (per InstrumentRegistry exchange)
      2. Have an asset class that is in active_markets
      3. Are present in symbol_universe

    Raises ValueError for unknown venue — fail-fast at startup, not silently.
    Logs a warning for symbols in universe but absent from InstrumentRegistry.
    """
    predicate = _VENUE_SYMBOL_FILTER.get(venue)
    if predicate is None:
        raise ValueError(
            f"Unknown feed venue: {venue!r}. "
            f"Supported: {list(_VENUE_SYMBOL_FILTER)}"
        )
    active_set = {m.lower() for m in active_markets}
    result = []
    for s in universe:
        if not predicate(s):
            continue
        asset_cls = InstrumentRegistry.get_asset_class(s)
        if asset_cls is None:
            logger.warning(
                "Symbol %r not found in InstrumentRegistry — excluded from feed", s
            )
            continue
        if asset_cls.value in active_set:
            result.append(s)
    return result


class SovereignHeartbeat:
    """
    Current top-level runtime wrapper.

    This class preserves the live startup/runtime behavior already present in
    main.py while keeping startup/shutdown control explicit and bounded.
    """

    def __init__(self, config: Config, attack_mode: bool = False):
        self.config = config
        self.attack_mode = attack_mode

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

        self.order_router = OrderRouter(
            primary_exchange="kraken",
            secondary_exchange="coinbase",
            primary_api_key=config.kraken_api_key or "",
            primary_api_secret=config.kraken_api_secret or "",
            latency_threshold_ms=200.0,
            ghost_ratio_threshold=3.0,
            pcv_max_attempts=5,
            pcv_retry_delay_sec=0.5,
            rest_fallback_enabled=True,
            paper_mode=config.broker_mode == "paper",
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
        )

        # Venue and symbol selection — all three feed sites use self._feed_symbols.
        self._primary_feed_venue: str = config.primary_feed_venue
        self._feed_symbols: list = _feed_symbols_for_venue(
            self._primary_feed_venue, config.symbol_universe, config.active_markets
        )
        self._primary_symbol: str = (
            self._feed_symbols[0]
            if self._feed_symbols
            else _VENUE_PRIMARY_SYMBOL_FALLBACK.get(self._primary_feed_venue, "XBT/USD")
        )

        self.tpe_engine = TopologicalEngine(symbol=self._primary_symbol)

        self.regime_detector = RegimeDetector()
        self.physical_validator = PhysicalValidator()
        self.toxicity_engine = ToxicityEngine(symbol=self._primary_symbol)
        self.insider_engine = InsiderSignalEngine()

        self.main_loop = create_main_loop(
            config=config,
            commander=self.commander,
            risk_guard=self.risk_guard,
            signal_fusion=self.signal_fusion,
            data_validator=self.data_validator,
            recalibrator=self.recalibrator,
            shans_curve=self.shans_curve,
            tpe_engine=self.tpe_engine,
            regime_detector=self.regime_detector,
            physical_validator=self.physical_validator,
            toxicity_engine=self.toxicity_engine,
            entropy_decoder=self.entropy_decoder,
            insider_engine=self.insider_engine,
            execution_engine=self.execution_engine,
            symbol=self._primary_symbol,
            exchange=self._primary_feed_venue,
        )

        self._running = False
        self._stopping = False
        self._threads: list[threading.Thread] = []
        self._health_check_interval = 5.0
        self._signal_handlers_registered = False
        self._bootstrap_equity = float(config.initial_capital)
        # TEMPORARY diagnostic counters — remove after callback reachability confirmed
        self._candle_recv_count: int = 0
        self._book_recv_count: int = 0

        self._register_graceful_death()

        logger.info("SovereignHeartbeat initialized")
        logger.info("Attack Mode: %s", "ENABLED" if attack_mode else "DISABLED")
        logger.info("Broker Mode: %s", config.broker_mode)
        logger.info("Initial Capital: $%0.2f", config.initial_capital)
        logger.info("Primary symbol: %s", self._primary_symbol)

    # ============================================
    # GRACEFUL SHUTDOWN
    # ============================================

    def _register_graceful_death(self) -> None:
        """
        Register process signal handlers when lawful to do so.

        Signal registration is only valid in the main thread on CPython and may
        be unavailable in some environments.
        """
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
        """
        Best-effort emergency shutdown path for OS termination signals.
        """
        if self._stopping:
            logger.warning("Termination signal received during active shutdown: %s", signum)
            return

        self._stopping = True
        self._running = False

        try:
            self.execution_engine.stop()
        except Exception as exc:
            logger.exception("Failed stopping execution engine during signal shutdown: %s", exc)

        try:
            self.order_router.close_all_positions()
            logger.critical("PORTFOLIO FLATTENED - SAFE TO EXIT")
        except Exception as exc:
            logger.exception("Failed to flatten portfolio during signal shutdown: %s", exc)

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

        if self.attack_mode:
            self.commander.enable_attack_mode(
                reason="cli_flag",
                timestamp_ns=int(time.time() * 1_000_000_000),
            )
            logger.info("ATTACK MODE ENABLED")

        self.execution_engine.start()
        self._seed_initial_equity()
        self.main_loop.start()
        self._start_background_threads()
        self._main_loop()

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

        try:
            self.main_loop.stop()
        except Exception as exc:
            logger.exception("Error stopping main loop: %s", exc)

        try:
            self.execution_engine.stop()
        except Exception as exc:
            logger.exception("Error stopping execution engine: %s", exc)

        self._join_background_threads()
        logger.info("Sovereign heartbeat stopped")

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
        Callback from KrakenWebSocketClient on each trade tick.

        Converts a single trade into directional buy/sell volumes,
        calls WhaleFlowEngine.update(), and injects the resulting
        WhaleFlowAlert into signal_fusion as the whale_flow slot.

        Additionally routes the trade tick to MainLoop.on_trade() for
        data continuity tracking and price state.

        exchange_ts_ns authority: comes from trade_info["exchange_ts_ns"],
        which KrakenWebSocketClient derives from the Kraken message
        timestamp_ms (strict authoritative path — no wall-clock substitution).
        """
        try:
            volume = float(trade_info.get("volume", 0.0))
            price = float(trade_info.get("price", 0.0))
            side = int(trade_info.get("side", 0))
            ts_ns = int(trade_info.get("exchange_ts_ns", 0))

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
            self.main_loop.on_trade(volume, price, side, ts_ns)

            # Insider observation feed from public trade flow.
            # entity_id="": Kraken public API exposes no account IDs (truthful).
            # intensity: whale-confidence-normalized signal strength (0-1, real).
            # notional_weight: normalized average trade size from whale engine (0-1, real).
            # source_reliability: 0.35 — public exchange flow, not privileged (truthful constant).
            # event_proximity_weight: 0.0 — no event catalyst feed (truthful).
            # novelty_weight: 0.0 — no novelty baseline available (truthful).
            # corroboration_weight: 0.25 if whale direction agrees with trade side, else 0.0.
            # invalidation_weight: 1 - toxicity suppression factor (real regime proxy).
            if side == 1:
                obs_direction = ObservationDirection.BUY
            elif side == -1:
                obs_direction = ObservationDirection.SELL
            else:
                obs_direction = ObservationDirection.UNKNOWN

            whale_corr = (
                Decimal("0.25")
                if side != 0 and int(alert.direction.value) == side
                else Decimal("0.0")
            )
            tox_inv = Decimal(
                str(round(1.0 - self.toxicity_engine.get_suppression_factor(), 6))
            )
            intensity = Decimal(str(round(min(1.0, max(0.0, alert.confidence)), 6)))
            notional = Decimal(str(round(min(1.0, max(0.0, alert.avg_trade_size)), 6)))

            obs = InsiderObservation(
                observation_id=f"{self._primary_symbol}_{ts_ns}",
                timestamp_ns=ts_ns,
                symbol=self._primary_symbol,
                entity_id="",
                direction=obs_direction,
                intensity=intensity,
                notional_weight=notional,
                source_reliability=Decimal("0.35"),
                event_proximity_weight=Decimal("0.0"),
                novelty_weight=Decimal("0.0"),
                corroboration_weight=whale_corr,
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
        """
        Callback from KrakenWebSocketClient and PollingClient on each candle.

        Routes to MainLoop.on_candle() which drives:
          - signal_fusion whale/regime updates
          - fuse(exchange_ts_ns) with authoritative exchange timestamp
          - risk state assessment with real TPE coherence
          - recalibration state machine
          - execution engine event drain

        exchange_ts_ns authority: provided by the candle from the data layer.
        """
        self._candle_recv_count += 1
        if self._candle_recv_count <= 3 or self._candle_recv_count % 100 == 0:
            logger.info(
                "FEED_CANDLE #%d: symbol=%s exchange_ts_ns=%d",
                self._candle_recv_count, candle.symbol, candle.exchange_ts_ns,
            )
        try:
            self.main_loop.on_candle(candle)
        except Exception as exc:
            logger.exception("_on_candle error: %s", exc)

    def _start_whale_websocket(self) -> None:
        """
        Launch the venue WS client in a background asyncio daemon thread.

        Uses self._feed_symbols (derived from Config.primary_feed_venue at init).
        Extension point: add a branch here when a second venue is added.
        """
        ws_symbols = self._feed_symbols
        if not ws_symbols:
            logger.warning(
                "No feed symbols for venue %r — whale WebSocket not started",
                self._primary_feed_venue,
            )
            return

        running_ref = self  # captured by closure; avoids late-binding issues

        async def _ws_run() -> None:
            ws_client = KrakenWebSocketClient(
                symbols=ws_symbols,
                on_order_book=running_ref._on_order_book,
                on_trade=running_ref._on_trade,
                on_candle=running_ref._on_candle,
            )
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
        logger.info("Whale WebSocket thread started (%d symbols: %s)", len(ws_symbols), ws_symbols)

    def _on_order_book(self, snapshot) -> None:
        """
        Callback from PollingClient on each order book REST poll (~1s).

        Routes to MainLoop.on_order_book() which drives:
          - Data continuity (record_data + mark_good)
          - TPE analysis (real coherence score)
          - ShansCurve processing → signal_fusion shans slot (ShansCurveSignal payload)
          - Price update from mid_price

        timestamp authority: snapshot.exchange_ts_ns from PollingClient,
        which uses now_ns() as REST polling fallback (non-authoritative path
        — pre-existing behavior in polling_client.py, not introduced here).
        """
        self._book_recv_count += 1
        if self._book_recv_count <= 3 or self._book_recv_count % 100 == 0:
            logger.info(
                "FEED_BOOK #%d: symbol=%s exchange_ts_ns=%d",
                self._book_recv_count, snapshot.symbol, snapshot.exchange_ts_ns,
            )
        try:
            self.main_loop.on_order_book(snapshot)
        except Exception as exc:
            logger.exception("_on_order_book error: %s", exc)

    def _start_polling_client(self) -> None:
        """
        Launch PollingClient in a background asyncio daemon thread.

        Uses self._feed_symbols (derived from Config.primary_feed_venue at init).
        Passes exchange=self._primary_feed_venue so PollingClient selects correct endpoints.
        Polls order book at 1s interval; on_order_book feeds MainLoop.on_order_book().
        Polls candles; on_candle feeds MainLoop.on_candle() via _on_candle().
        Thread is daemon so it does not block clean process exit.
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
            client = PollingClient(
                symbols=poll_symbols,
                interval=1.0,
                on_order_book=running_ref._on_order_book,
                on_candle=running_ref._on_candle,
                exchange=running_ref._primary_feed_venue,
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

    def _seed_initial_equity(self) -> None:
        """
        Seed the execution engine with a deterministic bootstrap equity.

        This is a bounded bring-up fallback, not an authoritative market/equity
        simulation.
        """
        try:
            self.execution_engine.update_equity(self._bootstrap_equity)
        except Exception as exc:
            logger.exception("Failed to seed initial equity: %s", exc)

    def _get_authoritative_equity(self) -> float | None:
        """
        Best-effort equity read from an existing status surface.

        Returns None if no trustworthy numeric value is available.
        """
        try:
            risk_status = self.risk_guard.get_status()
        except Exception as exc:
            logger.debug("Unable to fetch risk status for equity refresh: %s", exc)
            return None

        current_equity = risk_status.get("current_equity")
        if isinstance(current_equity, (int, float)):
            return float(current_equity)
        return None

    # ============================================
    # MAIN LOOP
    # ============================================

    def _main_loop(self) -> None:
        """
        Sovereign heartbeat — event-drain and equity-refresh loop.

        Responsibilities after MainLoop wiring:
          - execution_engine.process_events() heartbeat drain
          - equity refresh from authoritative surface → main_loop.on_equity_update()
          - risk_guard.assess_state() warm-up (informational; tpe_coherence=0.8 fallback
            because _main_loop has no candle-derived TPE signal — real TPE coherence is
            driven per-order-book in MainLoop.on_order_book() then consumed by on_candle())
          - health logging at iteration boundary

        Removed (now owned by MainLoop):
          - signal_fusion.fuse() — MainLoop.on_candle() drives with authoritative exchange_ts_ns
          - recalibrator.evaluate_regime() + CRISIS_ABORT — MainLoop._advance_recalibration handles
        """
        logger.info("Entering main runtime loop")

        iteration_count = 0

        while self._running:
            try:
                iteration_start = time.time()

                # 1. Process execution/runtime queue work.
                self.execution_engine.process_events()

                # 2. Refresh equity only from an existing authoritative surface
                #    when available; otherwise retain the deterministic bootstrap.
                authoritative_equity = self._get_authoritative_equity()
                if authoritative_equity is not None:
                    self.execution_engine.update_equity(authoritative_equity)
                    self.main_loop.on_equity_update(authoritative_equity, int(time.time_ns()))

                # 3. Keep risk surface warm for health-check path.
                #    tpe_coherence=0.8 is a bounded fallback — real coherence is
                #    driven per-candle by MainLoop (order_book → TPE → on_candle).
                effective_equity = authoritative_equity
                if effective_equity is None:
                    effective_equity = self._bootstrap_equity

                tpe_coherence = 0.8
                risk_state = self.risk_guard.assess_state(effective_equity, tpe_coherence)

                if risk_state["action"] in ["EMERGENCY_HALT", "RECALIBRATE", "AGGRESSIVE_STAY"]:
                    logger.info(
                        "Risk state: %s - %s",
                        risk_state["action"],
                        risk_state["reason"],
                    )

                # 4. Bounded loop pacing.
                iteration_duration = time.time() - iteration_start
                if iteration_duration < 0.01:
                    time.sleep(0.01 - iteration_duration)

                iteration_count += 1
                if iteration_count % 600 == 0:
                    self._log_health()

            except KeyboardInterrupt:
                logger.info("Keyboard interrupt received in main loop")
                self._running = False
            except Exception as exc:
                logger.exception("Main loop error: %s", exc)
                time.sleep(1.0)

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
            "timestamp": datetime.utcnow().isoformat(),
            "heartbeat": self._running,
            "execution_engine": self.execution_engine.get_status(),
            "risk_guard": self.risk_guard.get_status(),
            "order_router": self.order_router.get_ghost_status(),
            "commander": self.commander.get_status(),
            "recalibrator": self.recalibrator.get_status(),
        }

        if status["risk_guard"]["physical_fuse_triggered"]:
            logger.critical("HEALTH ALERT: Physical fuse triggered!")

        if status["risk_guard"]["vol_fuse_triggered"]:
            logger.critical("HEALTH ALERT: VoL fuse triggered!")

        if not status["order_router"]["websocket_connected"]:
            logger.warning("HEALTH ALERT: WebSocket disconnected!")

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
    return parser.parse_args()


def main() -> int:
    """Main entry point."""
    args = parse_arguments()

    load_dotenv(args.config)
    config = Config.from_env()

    if args.paper:
        config.broker_mode = "paper"

    setup_logger(config, level=args.log_level)

    logger.info("=" * 60)
    logger.info("POVERTY KILLER - SOVEREIGN TRADING ENGINE")
    logger.info("=" * 60)
    logger.info("Version: 1.0.0")
    logger.info("Attack Mode: %s", "ENABLED" if args.attack else "DISABLED")
    logger.info("Broker Mode: %s", config.broker_mode)
    logger.info("Initial Capital: $%0.2f", config.initial_capital)
    logger.info("Target: $%0.2f", config.initial_capital * 2)
    if args.paper:
        logger.info("Paper mode forced via command line")
    logger.info("=" * 60)

    heartbeat = SovereignHeartbeat(config, attack_mode=args.attack)

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
