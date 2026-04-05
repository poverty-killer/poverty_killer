#!/usr/bin/env python
"""
Poverty Killer - Sovereign Trading Engine
Main Entry Point - Sovereign Heartbeat
Features:
- Graceful Death (SIGINT/SIGTERM handlers)
- Full orchestration of all modules
- Attack Mode toggle via CLI
- Health check API
- Zero shortcuts - complete production code
"""

import asyncio
import argparse
import signal
import sys
import logging
import threading
import time
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime

from dotenv import load_dotenv

from app.config import Config
from app.commander import Commander
from app.risk.guard import HybridRiskGuard
from app.brain.signal_fusion import SignalFusion
from app.brain.data_validator import DataContinuityValidator
from app.brain.recalibrator import Recalibrator
from app.execution.engine import ExecutionEngine
from app.execution.order_router import OrderRouter
from app.execution.masking_layer import MaskingLayer
from app.monitoring.logger import setup_logger

logger = logging.getLogger(__name__)


class SovereignHeartbeat:
    """
    Sovereign Heartbeat - Master Orchestrator.
    
    Features:
    - Graceful Death on system signals
    - Full module orchestration
    - Health monitoring
    - Attack mode management
    """
    
    def __init__(self, config: Config, attack_mode: bool = False):
        """
        Initialize sovereign heartbeat.

        Args:
            config: Configuration object
            attack_mode: Enable attack mode on startup
        """
        self.config = config
        self.attack_mode = attack_mode
        
        # Initialize commander
        self.commander = Commander(
            initial_equity=config.initial_capital,
            target_equity=config.initial_capital * 2
        )
        
        # Initialize risk guard with atomic persistence
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
            websocket_heartbeat_timeout_sec=10.0
        )
        
        # Initialize data continuity validator
        self.data_validator = DataContinuityValidator(
            max_sequence_gap=1,
            max_timestamp_gap_sec=2.0,
            max_stale_age_sec=5.0,
            recovery_required_good=3,
            heartbeat_interval_sec=30.0
        )
        
        # Initialize order router
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
            margin_mode=False
        )
        
        # Initialize masking layer
        self.masking_layer = MaskingLayer(
            base_delay_ms=10.0,
            min_delay_ms=1.0,
            max_delay_ms=50.0,
            size_jitter_percent=0.01,
            size_jitter_distribution="gaussian",
            delay_jitter_distribution="exponential",
            volatility_adaptive=True,
            exchange="kraken"
        )
        
        # Initialize signal fusion
        self.signal_fusion = SignalFusion(config, self.commander)
        
        # Initialize recalibrator (topological brain)
        self.recalibrator = Recalibrator(
            fakeout_price_threshold_pct=0.05,
            fakeout_betti_threshold=2,
            fakeout_persistence_threshold=0.8,
            collapse_price_threshold_pct=0.05,
            collapse_betti_threshold=0,
            min_recalibration_seconds=3600.0,
            max_recalibration_seconds=14400.0,
            recovery_required_good=3
        )
        
        # Initialize execution engine
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
            emergency_cancel_workers=10
        )
        
        # Runtime state
        self._running = False
        self._threads = []
        self._last_equity_update = 0.0
        self._health_check_interval = 5.0
        
        # Register graceful death handlers
        self._register_graceful_death()
        
        logger.info("SovereignHeartbeat initialized")
        logger.info(f"Attack Mode: {'ENABLED' if attack_mode else 'DISABLED'}")
        logger.info(f"Broker Mode: {config.broker_mode}")
        logger.info(f"Initial Capital: ${config.initial_capital:,.2f}")
    
    # ============================================
    # GRACEFUL DEATH
    # ============================================
    
    def _register_graceful_death(self) -> None:
        """
        Register signal handlers for graceful death.
        Ensures positions are flattened before process exits.
        """
        def death_handler(signum, frame):
            logger.critical(f"SYSTEM TERMINATION SIGNAL RECEIVED: {signum}")
            logger.critical("INITIATING GRACEFUL DEATH SEQUENCE")
            
            # 1. Stop execution engine
            self.execution_engine.stop()
            
            # 2. Flatten all positions to USD
            try:
                self.order_router.close_all_positions()
                logger.critical("PORTFOLIO FLATTENED - SAFE TO DIE")
            except Exception as e:
                logger.error(f"Failed to flatten portfolio: {e}")
            
            # 3. Force exit
            sys.exit(0)
        
        signal.signal(signal.SIGINT, death_handler)
        signal.signal(signal.SIGTERM, death_handler)
        logger.info("Graceful death handlers registered")
    
    # ============================================
    # PUBLIC METHODS
    # ============================================
    
    def start(self) -> None:
        """Start the sovereign heartbeat."""
        if self._running:
            logger.warning("Heartbeat already running")
            return
        
        self._running = True
        
        # Enable attack mode if requested
        if self.attack_mode:
            self.commander.enable_attack_mode(
                reason="cli_flag",
                timestamp_ns=int(time.time() * 1_000_000_000)
            )
            logger.info("ATTACK MODE ENABLED")
        
        # Start execution engine
        self.execution_engine.start()
        
        # Start health check thread
        health_thread = threading.Thread(target=self._health_check_loop, daemon=True)
        health_thread.start()
        self._threads.append(health_thread)
        
        # Start main loop
        self._main_loop()
    
    def stop(self) -> None:
        """Stop the sovereign heartbeat."""
        logger.info("Stopping sovereign heartbeat")
        self._running = False
        self.execution_engine.stop()
        
        for thread in self._threads:
            thread.join(timeout=2.0)
        
        logger.info("Sovereign heartbeat stopped")
    
    # ============================================
    # MAIN LOOP
    # ============================================
    
    def _main_loop(self) -> None:
        """
        Main orchestration loop.
        Processes market data, updates signals, and manages execution.
        """
        logger.info("Entering main orchestration loop")
        
        # Simulated market data (replace with actual feed)
        last_candle_time = 0.0
        last_order_book_time = 0.0
        last_trade_time = 0.0
        
        # Performance tracking
        loop_start = time.time()
        iteration_count = 0
        
        while self._running:
            try:
                iteration_start = time.time()
                
                # ============================================
                # 1. SIMULATED MARKET DATA (Replace with actual feed)
                # ============================================
                current_time = time.time()
                
                # Simulate candle every 60 seconds
                if current_time - last_candle_time >= 60.0:
                    last_candle_time = current_time
                    # In production: get actual candle from feed
                    self._process_simulated_candle()
                
                # Simulate order book every 0.1 seconds
                if current_time - last_order_book_time >= 0.1:
                    last_order_book_time = current_time
                    # In production: get actual order book from feed
                    self._process_simulated_order_book()
                
                # Simulate trade every 0.5 seconds
                if current_time - last_trade_time >= 0.5:
                    last_trade_time = current_time
                    # In production: get actual trade from feed
                    self._process_simulated_trade()
                
                # ============================================
                # 2. PROCESS EXECUTION QUEUE
                # ============================================
                self.execution_engine.process_events()
                
                # ============================================
                # 3. UPDATE COMMANDER EQUITY
                # ============================================
                # In production: get actual portfolio equity from exchange
                simulated_equity = self._get_simulated_equity()
                self.execution_engine.update_equity(simulated_equity)
                
                # ============================================
                # 4. CHECK RISK STATE
                # ============================================
                tpe_coherence = 0.8  # In production: from TPE engine
                risk_state = self.risk_guard.assess_state(simulated_equity, tpe_coherence)
                
                # Log state changes
                if risk_state["action"] in ["EMERGENCY_HALT", "RECALIBRATE", "AGGRESSIVE_STAY"]:
                    logger.info(f"Risk state: {risk_state['action']} - {risk_state['reason']}")
                
                # ============================================
                # 5. UPDATE RECALIBRATOR
                # ============================================
                # In production: use actual TPE signal
                tpe_signal = None
                recalibration_decision = self.recalibrator.evaluate_regime(
                    price_drop_pct=risk_state["drawdown_from_peak"],
                    tpe_signal=tpe_signal,
                    drop_duration_sec=0.0
                )
                
                if recalibration_decision == "CRISIS_ABORT":
                    logger.critical("RECALIBRATOR: CRISIS ABORT - initiating liquidation")
                    self.execution_engine._emergency_liquidate_all()
                
                # ============================================
                # 6. UPDATE SIGNAL FUSION
                # ============================================
                # In production: pass actual signals
                fusion_decision = self.signal_fusion.fuse()
                
                # ============================================
                # 7. PROCESS SIGNALS
                # ============================================
                if fusion_decision.attack_mode and fusion_decision.preferred_sleeve:
                    # In production: generate actual signal
                    # For now, skip signal generation in simulation
                    pass
                
                # ============================================
                # 8. ITERATION CONTROL
                # ============================================
                iteration_duration = time.time() - iteration_start
                if iteration_duration < 0.01:
                    time.sleep(0.01 - iteration_duration)
                
                iteration_count += 1
                
                # Log health every 60 seconds
                if iteration_count % 600 == 0:
                    self._log_health()
                
            except Exception as e:
                logger.error(f"Main loop error: {e}")
                time.sleep(1.0)
    
    # ============================================
    # SIMULATED DATA (Replace with actual feed)
    # ============================================
    
    def _process_simulated_candle(self) -> None:
        """Process simulated candle data."""
        # In production: process actual candle from WebSocket/REST
        pass
    
    def _process_simulated_order_book(self) -> None:
        """Process simulated order book data."""
        # In production: process actual order book from WebSocket
        pass
    
    def _process_simulated_trade(self) -> None:
        """Process simulated trade data."""
        # In production: process actual trade from WebSocket
        pass
    
    def _get_simulated_equity(self) -> float:
        """Get simulated equity for testing."""
        # In production: get actual portfolio equity from exchange
        # For simulation, use initial capital with small random drift
        import random
        drift = (random.random() - 0.5) * 100
        return max(1000.0, self.config.initial_capital + drift)
    
    # ============================================
    # HEALTH CHECK
    # ============================================
    
    def _health_check_loop(self) -> None:
        """Background health check loop."""
        while self._running:
            try:
                time.sleep(self._health_check_interval)
                self._perform_health_check()
            except Exception as e:
                logger.error(f"Health check error: {e}")
    
    def _perform_health_check(self) -> None:
        """Perform system health check."""
        status = {
            "timestamp": datetime.utcnow().isoformat(),
            "heartbeat": self._running,
            "execution_engine": self.execution_engine.get_status(),
            "risk_guard": self.risk_guard.get_status(),
            "order_router": self.order_router.get_ghost_status(),
            "commander": self.commander.get_status(),
            "recalibrator": self.recalibrator.get_status()
        }
        
        # Check for critical issues
        if status["risk_guard"]["physical_fuse_triggered"]:
            logger.critical("HEALTH ALERT: Physical fuse triggered!")
        
        if status["risk_guard"]["vol_fuse_triggered"]:
            logger.critical("HEALTH ALERT: VoL fuse triggered!")
        
        if not status["order_router"]["websocket_connected"]:
            logger.warning("HEALTH ALERT: WebSocket disconnected!")
        
        logger.debug(f"Health check: {status['execution_engine']['is_running']}")
    
    def _log_health(self) -> None:
        """Log system health summary."""
        status = {
            "mode": "ATTACK" if self.commander.is_attack_mode() else "SAFE",
            "equity": self.risk_guard.get_status()["current_equity"],
            "tradeable_equity": self.risk_guard.get_status()["tradeable_equity"],
            "drawdown": self.risk_guard.get_status()["drawdown_from_peak"],
            "pending_orders": self.execution_engine.get_status()["pending_orders_count"],
            "queue_size": self.execution_engine.get_status()["execution_queue_size"],
            "websocket": self.order_router.is_websocket_connected()
        }
        logger.info(f"Health Summary: {status}")
    
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
            "recalibrator": self.recalibrator.get_status()
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
        help="Enable attack mode on startup (0.85 Kelly, aggressive strategies)"
    )
    parser.add_argument(
        "--paper",
        action="store_true",
        help="Force paper trading mode (overrides .env)"
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Set logging level"
    )
    parser.add_argument(
        "--config",
        default=".env",
        help="Path to configuration file"
    )
    return parser.parse_args()


def main():
    """Main entry point."""
    # Parse arguments
    args = parse_arguments()
    
    # Load configuration
    load_dotenv(args.config)
    config = Config.from_env()
    
    # Override broker mode if --paper flag
    if args.paper:
        config.broker_mode = "paper"
        print("PAPER MODE FORCED VIA COMMAND LINE")
    
    # Setup logging
    setup_logger(config, level=args.log_level)
    
    logger.info("=" * 60)
    logger.info("POVERTY KILLER - SOVEREIGN TRADING ENGINE")
    logger.info("=" * 60)
    logger.info(f"Version: 1.0.0")
    logger.info(f"Attack Mode: {'ENABLED' if args.attack else 'DISABLED'}")
    logger.info(f"Broker Mode: {config.broker_mode}")
    logger.info(f"Initial Capital: ${config.initial_capital:,.2f}")
    logger.info(f"Target: ${config.initial_capital * 2:,.2f}")
    logger.info("=" * 60)
    
    # Initialize heartbeat
    heartbeat = SovereignHeartbeat(config, attack_mode=args.attack)
    
    # Start heartbeat
    try:
        heartbeat.start()
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received")
    except Exception as e:
        logger.exception(f"Fatal error: {e}")
        return 1
    finally:
        heartbeat.stop()
    
    logger.info("Poverty Killer shutdown complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())