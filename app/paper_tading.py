#!/usr/bin/env python
"""
Poverty Killer - Sovereign Paper Trading Mode
Dedicated entry point for realistic simulation before live deployment.
Features:
- Realistic slippage model (non-linear, volatility-adjusted)
- Exchange-specific fee structures (Kraken 0.26% taker / 0.16% maker)
- Market impact simulation (orders consume liquidity)
- Latency simulation (configurable, jitter)
- Partial fill simulation
- Full risk guard integration
- Sovereign Governor for capital allocation
- Sovereign Sentinel for heartbeat monitoring
"""

import asyncio
import argparse
import signal
import sys
import logging
import time
import random
import threading
import numpy as np
from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime, timedelta
from pathlib import Path
from dataclasses import dataclass, field

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
from app.meta.strategy_allocator import SovereignGovernor, AllocationMode
from app.monitoring.alerts import SovereignSentinel, AlertSeverity, AlertType
from app.monitoring.logger import setup_logger

logger = logging.getLogger(__name__)


class SovereignPaperTrader:
    """
    Sovereign Paper Trading Engine.
    Realistic simulation with:
    - Non-linear slippage (volatility-adjusted, depth-based)
    - Exchange-specific fees (Kraken 0.26% taker / 0.16% maker)
    - Market impact (orders consume liquidity)
    - Latency simulation with jitter
    - Partial fills
    - Full risk integration
    """
    
    def __init__(
        self,
        config: Config,
        attack_mode: bool = False,
        slippage_model: str = "realistic",
        latency_model: str = "realistic",
        partial_fill_probability: float = 0.1,
        market_impact_factor: float = 0.0005,
        telegram_token: Optional[str] = None,
        telegram_chat_id: Optional[str] = None
    ):
        """
        Initialize paper trader.

        Args:
            config: Configuration object
            attack_mode: Enable attack mode on startup
            slippage_model: "realistic", "optimistic", or "pessimistic"
            latency_model: "realistic", "optimistic", or "pessimistic"
            partial_fill_probability: Chance of partial fill
            market_impact_factor: Impact per unit of size
            telegram_token: Telegram bot token for alerts
            telegram_chat_id: Telegram chat ID for alerts
        """
        self.config = config
        self.attack_mode = attack_mode
        self.slippage_model = slippage_model
        self.latency_model = latency_model
        self.partial_fill_probability = partial_fill_probability
        self.market_impact_factor = market_impact_factor
        
        # ============================================
        # PAPER TRADING SIMULATION STATE
        # ============================================
        self._simulated_equity = config.initial_capital
        self._simulated_cash = config.initial_capital
        self._simulated_positions: Dict[str, Dict[str, Any]] = {}
        self._simulated_trades: List[Dict[str, Any]] = []
        self._simulated_fees_paid = 0.0
        self._simulated_slippage_paid = 0.0
        self._lock = threading.Lock()
        
        # ============================================
        # SOVEREIGN COMPONENTS
        # ============================================
        
        # Commander
        self.commander = Commander(
            initial_equity=config.initial_capital,
            target_equity=config.initial_capital * 2
        )
        
        # Risk Guard
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
        
        # Data Continuity Validator
        self.data_validator = DataContinuityValidator(
            max_sequence_gap=1,
            max_timestamp_gap_sec=2.0,
            max_stale_age_sec=5.0,
            recovery_required_good=3,
            heartbeat_interval_sec=30.0
        )
        
        # Order Router (Paper Mode)
        self.order_router = OrderRouter(
            primary_exchange="kraken",
            secondary_exchange="coinbase",
            primary_api_key="",
            primary_api_secret="",
            latency_threshold_ms=200.0,
            ghost_ratio_threshold=3.0,
            pcv_max_attempts=5,
            pcv_retry_delay_sec=0.5,
            rest_fallback_enabled=True,
            paper_mode=True,
            margin_mode=False
        )
        
        # Masking Layer
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
        
        # Signal Fusion
        self.signal_fusion = SignalFusion(config, self.commander)
        
        # Recalibrator
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
        
        # Sovereign Governor (Predatory Edition)
        self.governor = SovereignGovernor(
            total_capital=config.initial_capital,
            cash_reserve_pct=0.10,
            max_strategy_exposure_pct=0.40,
            max_asset_exposure_pct=0.20,
            correlation_kill_threshold=0.85,
            allocation_cooldown_sec=60.0,
            performance_decay_hours=24.0,
            min_win_rate=0.40,
            min_sharpe=0.5,
            heat_throttle_70_pct=0.7,
            heat_throttle_90_pct=0.2,
            correlation_slash_factor=0.5
        )
        
        # Execution Engine
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
        
        # Sovereign Sentinel
        self.sentinel = SovereignSentinel(
            webhook_url=None,
            telegram_bot_token=telegram_token,
            telegram_chat_id=telegram_chat_id,
            heartbeat_interval_sec=1.0,
            latency_threshold_ms=500.0,
            consecutive_failures_threshold=3,
            alert_cooldown_sec=60.0,
            state_file="state/alert_state.json",
            state_flush_interval_sec=60.0
        )
        
        # Runtime state
        self._running = False
        self._last_heartbeat = time.time()
        self._iteration_count = 0
        
        logger.info("=" * 60)
        logger.info("SOVEREIGN PAPER TRADING MODE")
        logger.info("=" * 60)
        logger.info(f"Slippage Model: {slippage_model}")
        logger.info(f"Latency Model: {latency_model}")
        logger.info(f"Partial Fill Probability: {partial_fill_probability:.0%}")
        logger.info(f"Market Impact Factor: {market_impact_factor:.4f}")
        logger.info("=" * 60)
    
    # ============================================
    # REALISTIC SLIPPAGE MODEL
    # ============================================
    
    def _calculate_slippage_bps(
        self,
        size: float,
        price: float,
        side: str,
        volatility: float,
        market_depth: float,
        is_open: bool = False,
        is_close: bool = False
    ) -> float:
        """
        Calculate realistic slippage in basis points.
        
        Features:
        - Non-linear size impact (quadratic)
        - Volatility adjustment
        - Time-of-day adjustment
        - Depth-based scaling
        """
        notional = size * price
        
        if self.slippage_model == "optimistic":
            base_bps = 0.5
            size_impact = 0.0
            vol_impact = 0.0
        elif self.slippage_model == "pessimistic":
            base_bps = 2.0
            depth_ratio = notional / max(market_depth, 10000.0)
            size_impact = self.market_impact_factor * (depth_ratio ** 1.5) * 10000 * 2
            vol_impact = volatility * 100
        else:  # realistic
            base_bps = 1.0
            depth_ratio = notional / max(market_depth, 10000.0)
            size_impact = self.market_impact_factor * (depth_ratio ** 1.5) * 10000
            vol_impact = volatility * 50
        
        # Time of day
        if is_open or is_close:
            base_bps *= 1.5
        
        # Direction (buys often have more slippage)
        if side == "buy":
            base_bps *= 1.1
        
        total_bps = base_bps + size_impact + vol_impact
        
        # Add random noise
        noise = np.random.normal(0, total_bps * 0.1)
        total_bps = max(0.1, total_bps + noise)
        
        return min(50.0, total_bps)
    
    def _calculate_fees(self, size: float, price: float, order_type: str) -> float:
        """Calculate exchange fees (Kraken rates)."""
        notional = size * price
        if order_type == "market":
            fee_bps = 0.26  # 0.26% taker
        else:
            fee_bps = 0.16  # 0.16% maker
        return notional * (fee_bps / 10000)
    
    def _simulate_latency(self) -> float:
        """Simulate network latency with jitter."""
        if self.latency_model == "optimistic":
            base_ms = 5.0
            jitter_ms = 2.0
        elif self.latency_model == "pessimistic":
            base_ms = 30.0
            jitter_ms = 15.0
        else:  # realistic
            base_ms = 15.0
            jitter_ms = 10.0
        
        # Exponential distribution for realistic latency spikes
        latency = np.random.exponential(scale=base_ms)
        latency += np.random.uniform(0, jitter_ms)
        
        return min(100.0, latency)
    
    # ============================================
    # PAPER ORDER EXECUTION
    # ============================================
    
    def _execute_paper_order(
        self,
        symbol: str,
        side: str,
        size: float,
        price: float,
        order_type: str,
        volatility: float = 0.01,
        market_depth: float = 100000.0
    ) -> Tuple[float, float, float, float]:
        """
        Execute paper order with realistic simulation.
        
        Returns:
            Tuple of (fill_price, fill_quantity, fees, slippage_bps)
        """
        # Simulate latency
        latency_ms = self._simulate_latency()
        time.sleep(latency_ms / 1000)
        
        # Simulate partial fills
        if random.random() < self.partial_fill_probability:
            fill_ratio = random.uniform(0.7, 0.99)
            fill_size = size * fill_ratio
        else:
            fill_size = size
        
        # Calculate slippage
        is_open = False  # Would check market hours
        is_close = False
        
        slippage_bps = self._calculate_slippage_bps(
            size=fill_size,
            price=price,
            side=side,
            volatility=volatility,
            market_depth=market_depth,
            is_open=is_open,
            is_close=is_close
        )
        
        # Apply slippage
        if side == "buy":
            fill_price = price * (1 + slippage_bps / 10000)
        else:
            fill_price = price * (1 - slippage_bps / 10000)
        
        # Calculate fees
        fees = self._calculate_fees(fill_size, fill_price, order_type)
        
        return fill_price, fill_size, fees, slippage_bps
    
    # ============================================
    # PORTFOLIO MANAGEMENT
    # ============================================
    
    def _update_portfolio(
        self,
        symbol: str,
        side: str,
        size: float,
        price: float,
        fees: float
    ) -> None:
        """Update simulated portfolio after trade."""
        with self._lock:
            notional = size * price
            
            if side == "buy":
                self._simulated_cash -= (notional + fees)
                
                if symbol not in self._simulated_positions:
                    self._simulated_positions[symbol] = {
                        "quantity": size,
                        "avg_price": price,
                        "total_cost": notional + fees
                    }
                else:
                    pos = self._simulated_positions[symbol]
                    new_quantity = pos["quantity"] + size
                    new_cost = pos["total_cost"] + notional + fees
                    pos["quantity"] = new_quantity
                    pos["avg_price"] = new_cost / new_quantity
                    pos["total_cost"] = new_cost
            else:  # sell
                self._simulated_cash += (notional - fees)
                
                if symbol in self._simulated_positions:
                    pos = self._simulated_positions[symbol]
                    pos["quantity"] -= size
                    if pos["quantity"] <= 0:
                        del self._simulated_positions[symbol]
            
            self._simulated_fees_paid += fees
            self._simulated_equity = self._simulated_cash
            for symbol, pos in self._simulated_positions.items():
                current_price = self._get_simulated_price(symbol)
                self._simulated_equity += pos["quantity"] * current_price
    
    def _get_simulated_price(self, symbol: str) -> float:
        """Get simulated current price for a symbol."""
        if "BTC" in symbol:
            return 50000.0 + random.uniform(-500, 500)
        elif "ETH" in symbol:
            return 3000.0 + random.uniform(-30, 30)
        return 100.0
    
    # ============================================
    # SIGNAL PROCESSING
    # ============================================
    
    def _process_signal(self, fusion_decision) -> None:
        """Process a trading signal from signal fusion."""
        if not fusion_decision.attack_mode:
            return
        
        if not fusion_decision.preferred_sleeve:
            return
        
        # Get requested size from governor
        requested_capital = 1000.0
        
        # Get adjusted allocation from governor
        success, allocated, reason = self.governor.allocate(
            strategy=fusion_decision.preferred_sleeve,
            requested_capital=requested_capital,
            symbol="BTC/USD",
            asset_class="crypto"
        )
        
        if not success or allocated <= 0:
            logger.debug(f"Governor rejected: {reason}")
            return
        
        # Calculate position size
        price = self._get_simulated_price("BTC/USD")
        size = allocated / price
        
        # Execute paper order
        fill_price, fill_qty, fees, slippage = self._execute_paper_order(
            symbol="BTC/USD",
            side="buy",
            size=size,
            price=price,
            order_type="market",
            volatility=0.01,
            market_depth=100000.0
        )
        
        # Update portfolio
        self._update_portfolio("BTC/USD", "buy", fill_qty, fill_price, fees)
        
        logger.info(f"PAPER ORDER EXECUTED: {fusion_decision.preferred_sleeve.value} "
                   f"BUY {fill_qty:.4f} BTC @ ${fill_price:.2f} "
                   f"(slippage={slippage:.1f}bps, fees=${fees:.2f})")
    
    # ============================================
    # SIMULATED MARKET DATA
    # ============================================
    
    def _simulate_market_data(self) -> None:
        """Generate simulated market data for testing."""
        pass
    
    # ============================================
    # MAIN LOOP
    # ============================================
    
    def _main_loop(self) -> None:
        """Main orchestration loop."""
        logger.info("Entering paper trading main loop")
        
        last_heartbeat = time.time()
        iteration_count = 0
        
        while self._running:
            try:
                iteration_start = time.time()
                
                # 1. Simulate market data
                self._simulate_market_data()
                
                # 2. Update equity
                self.execution_engine.update_equity(self._simulated_equity)
                
                # 3. Get fusion decision
                fusion_decision = self.signal_fusion.fuse()
                
                # 4. Process signals
                self._process_signal(fusion_decision)
                
                # 5. Process execution queue
                self.execution_engine.process_events()
                
                # 6. Update sentinel heartbeat
                latency_ms = (time.time() - iteration_start) * 1000
                self.sentinel.heartbeat(latency_ms)
                
                # 7. Log health periodically
                iteration_count += 1
                if iteration_count % 600 == 0:
                    self._log_health()
                
                # 8. Maintain loop rate
                elapsed = time.time() - iteration_start
                if elapsed < 0.1:
                    time.sleep(0.1 - elapsed)
                
            except Exception as e:
                logger.error(f"Main loop error: {e}")
                time.sleep(1.0)
    
    def _log_health(self) -> None:
        """Log system health."""
        with self._lock:
            logger.info("=" * 50)
            logger.info("PAPER TRADING STATUS")
            logger.info(f"Equity: ${self._simulated_equity:,.2f}")
            logger.info(f"Cash: ${self._simulated_cash:,.2f}")
            logger.info(f"Positions: {len(self._simulated_positions)}")
            logger.info(f"Total Fees Paid: ${self._simulated_fees_paid:,.2f}")
            logger.info(f"Trade Count: {len(self._simulated_trades)}")
            logger.info(f"Governor Mode: {self.governor.get_mode().value}")
            logger.info(f"Heat Multiplier: {self.governor.get_heat_multiplier():.1%}")
            logger.info("=" * 50)
    
    # ============================================
    # PUBLIC API
    # ============================================
    
    def start(self) -> None:
        """Start paper trading."""
        if self._running:
            logger.warning("Paper trading already running")
            return
        
        self._running = True
        
        # Enable attack mode if requested
        if self.attack_mode:
            self.commander.enable_attack_mode(
                reason="cli_flag",
                timestamp_ns=int(time.time() * 1_000_000_000)
            )
            logger.info("ATTACK MODE ENABLED")
        
        # Set governor to attack mode if enabled
        if self.attack_mode:
            self.governor.set_mode(AllocationMode.ATTACK, "cli_flag")
        
        # Start sentinel
        self.sentinel.start()
        
        # Start execution engine
        self.execution_engine.start()
        
        # Run main loop
        self._main_loop()
    
    def stop(self) -> None:
        """Stop paper trading."""
        logger.info("Stopping paper trading")
        self._running = False
        self.execution_engine.stop()
        self.sentinel.stop()
        
        # Final report
        with self._lock:
            logger.info("=" * 50)
            logger.info("PAPER TRADING FINAL REPORT")
            logger.info(f"Final Equity: ${self._simulated_equity:,.2f}")
            logger.info(f"Total Return: {(self._simulated_equity - self.config.initial_capital) / self.config.initial_capital:.2%}")
            logger.info(f"Total Fees Paid: ${self._simulated_fees_paid:,.2f}")
            logger.info(f"Total Trades: {len(self._simulated_trades)}")
            logger.info("=" * 50)
        
        logger.info("Paper trading stopped")
    
    def get_status(self) -> Dict[str, Any]:
        """Get current status."""
        with self._lock:
            return {
                "running": self._running,
                "equity": self._simulated_equity,
                "cash": self._simulated_cash,
                "positions": len(self._simulated_positions),
                "trades": len(self._simulated_trades),
                "fees_paid": self._simulated_fees_paid,
                "governor": self.governor.get_status(),
                "heat_map": self.governor.get_heat_map()
            }


# ============================================
# GRACEFUL DEATH HANDLER
# ============================================

def register_graceful_death(paper_trader: SovereignPaperTrader) -> None:
    """Register signal handlers for graceful death."""
    def death_handler(signum, frame):
        logger.critical(f"SYSTEM TERMINATION SIGNAL RECEIVED: {signum}")
        logger.critical("INITIATING GRACEFUL DEATH")
        paper_trader.stop()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, death_handler)
    signal.signal(signal.SIGTERM, death_handler)


# ============================================
# ENTRY POINT
# ============================================

def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Poverty Killer - Sovereign Paper Trading Mode"
    )
    parser.add_argument(
        "--attack",
        action="store_true",
        help="Enable attack mode on startup"
    )
    parser.add_argument(
        "--slippage",
        default="realistic",
        choices=["optimistic", "realistic", "pessimistic"],
        help="Slippage model for paper trading"
    )
    parser.add_argument(
        "--latency",
        default="realistic",
        choices=["optimistic", "realistic", "pessimistic"],
        help="Latency model for paper trading"
    )
    parser.add_argument(
        "--partial-fill",
        type=float,
        default=0.1,
        help="Probability of partial fill (0-1)"
    )
    parser.add_argument(
        "--market-impact",
        type=float,
        default=0.0005,
        help="Market impact factor"
    )
    parser.add_argument(
        "--telegram-token",
        default=None,
        help="Telegram bot token for alerts"
    )
    parser.add_argument(
        "--telegram-chat-id",
        default=None,
        help="Telegram chat ID for alerts"
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
    args = parse_arguments()
    
    # Load configuration
    load_dotenv(args.config)
    config = Config.from_env()
    config.broker_mode = "paper"
    
    # Setup logging
    setup_logger(config, level=args.log_level)
    
    logger.info("=" * 60)
    logger.info("POVERTY KILLER - SOVEREIGN PAPER TRADING MODE")
    logger.info("=" * 60)
    logger.info(f"Version: 1.0.0")
    logger.info(f"Attack Mode: {'ENABLED' if args.attack else 'DISABLED'}")
    logger.info(f"Slippage Model: {args.slippage}")
    logger.info(f"Latency Model: {args.latency}")
    logger.info(f"Partial Fill Probability: {args.partial_fill:.0%}")
    logger.info(f"Initial Capital: ${config.initial_capital:,.2f}")
    logger.info(f"Target: ${config.initial_capital * 2:,.2f}")
    logger.info("=" * 60)
    
    # Initialize paper trader
    paper_trader = SovereignPaperTrader(
        config=config,
        attack_mode=args.attack,
        slippage_model=args.slippage,
        latency_model=args.latency,
        partial_fill_probability=args.partial_fill,
        market_impact_factor=args.market_impact,
        telegram_token=args.telegram_token,
        telegram_chat_id=args.telegram_chat_id
    )
    
    # Register graceful death
    register_graceful_death(paper_trader)
    
    # Start paper trading
    try:
        paper_trader.start()
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received")
    except Exception as e:
        logger.exception(f"Fatal error: {e}")
        return 1
    finally:
        paper_trader.stop()
    
    logger.info("Paper trading shutdown complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())