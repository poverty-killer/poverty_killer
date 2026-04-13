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
import logging
import signal
import sys
import threading
import time
from datetime import datetime
from typing import Any, Dict

from dotenv import load_dotenv

from app.brain.data_validator import DataContinuityValidator
from app.brain.recalibrator import Recalibrator
from app.brain.signal_fusion import SignalFusion
from app.commander import Commander
from app.config import Config
from app.execution.engine import ExecutionEngine
from app.execution.masking_layer import MaskingLayer
from app.execution.order_router import OrderRouter
from app.monitoring.logger import setup_logger
from app.risk.guard import HybridRiskGuard

logger = logging.getLogger(__name__)


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

        self._running = False
        self._stopping = False
        self._threads: list[threading.Thread] = []
        self._health_check_interval = 5.0
        self._signal_handlers_registered = False
        self._bootstrap_equity = float(config.initial_capital)

        self._register_graceful_death()

        logger.info("SovereignHeartbeat initialized")
        logger.info("Attack Mode: %s", "ENABLED" if attack_mode else "DISABLED")
        logger.info("Broker Mode: %s", config.broker_mode)
        logger.info("Initial Capital: $%0.2f", config.initial_capital)

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
        Current bounded runtime loop.

        This preserves the live repo launch path without pretending main.py owns
        a rich market-data simulation environment.
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

                # 3. Keep existing risk/recalibration surfaces warm without
                #    inventing fake market events.
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

                recalibration_decision = self.recalibrator.evaluate_regime(
                    price_drop_pct=risk_state["drawdown_from_peak"],
                    tpe_signal=None,
                    drop_duration_sec=0.0,
                )

                if recalibration_decision == "CRISIS_ABORT":
                    logger.critical("RECALIBRATOR: CRISIS ABORT - initiating liquidation")
                    self.execution_engine._emergency_liquidate_all()

                fusion_decision = self.signal_fusion.fuse()
                if fusion_decision.attack_mode and fusion_decision.preferred_sleeve:
                    logger.debug(
                        "Fusion preference active: attack_mode=%s preferred_sleeve=%s",
                        fusion_decision.attack_mode,
                        fusion_decision.preferred_sleeve,
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
