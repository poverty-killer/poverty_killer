# Project Map: World Aware Bot / Poverty Killer

## File: .\aiohttp_test.py
``python
import asyncio
import aiohttp
``

## File: .\main.py
``python
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
def _feed_symbols_for_venue(venue: str, universe: list, active_markets: list) -> list:
class SovereignHeartbeat:
    def __init__(self, config: Config, attack_mode: bool = False):
    def _register_graceful_death(self) -> None:
        def death_handler(signum, frame):
    def _handle_termination_signal(self, signum: int) -> None:
    def start(self) -> None:
    def stop(self) -> None:
    def _start_background_threads(self) -> None:
    def _join_background_threads(self) -> None:
    def _on_trade(self, trade_info: dict) -> None:
    def _on_candle(self, candle: Candle) -> None:
    def _start_whale_websocket(self) -> None:
        def _thread_main() -> None:
    def _on_order_book(self, snapshot) -> None:
    def _start_polling_client(self) -> None:
        def _thread_main() -> None:
    def _seed_initial_equity(self) -> None:
    def _get_authoritative_equity(self) -> float | None:
    def _main_loop(self) -> None:
    def _health_check_loop(self) -> None:
    def _perform_health_check(self) -> None:
    def _log_health(self) -> None:
    def get_status(self) -> Dict[str, Any]:
def parse_arguments():
def main() -> int:
``

## File: .\paper_trading.py
``python
def main():
``

## File: .\app\commander.py
``python
import logging
import threading
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional
class AttackState:
class Commander:
    def __init__(self, initial_equity: float = 20000.0, target_equity: float = 40000.0):
    def _validate_positive_float(value: float, field_name: str) -> float:
    def _validate_non_negative_float(value: float, field_name: str) -> float:
    def _validate_probability_like(value: float, field_name: str) -> float:
    def _validate_timestamp_ns(timestamp_ns: int) -> int:
    def _validate_reason(reason: str) -> str:
    def update_equity(self, current_equity: float, timestamp_ns: int) -> None:
    def _set_attack_mode(self, enabled: bool, reason: str, timestamp_ns: int) -> None:
    def enable_attack_mode(self, reason: str, timestamp_ns: int) -> bool:
    def disable_attack_mode(self, reason: str, timestamp_ns: int) -> None:
    def is_attack_mode(self) -> bool:
    def get_kelly_multiplier(self) -> float:
    def get_vpin_threshold(self) -> float:
    def get_confidence_threshold(self) -> float:
    def get_aggression_multiplier(self) -> float:
    def can_trade(self, expected_net_profit_pct: float, confidence: float) -> bool:
    def register_mode_change_callback(self, callback) -> None:
    def get_status(self) -> Dict[str, Any]:
``

## File: .\app\config.py
``python
from typing import List, Optional, Dict, Literal
from pydantic import BaseModel, Field, field_validator, ConfigDict
from pydantic_settings import BaseSettings
import json
class RiskConfig(BaseModel):
    def class_limits(self) -> Dict[str, float]:
    def validate_class_limits_total(self) -> bool:
class AssetLeverageConfig(BaseModel):
    def get_leverage(self, asset_class: str) -> float:
class SigmaRiskConfig(BaseModel):
    def get_multipliers(self, regime: str) -> Dict[str, float]:
class StrategyConfig(BaseModel):
class DataConfig(BaseModel):
class ExecutionConfig(BaseModel):
class Config(BaseSettings):
    def validate_active_markets(cls, v):
    def parse_symbol_universe(cls, v):
    def from_env(cls) -> "Config":
    def get_class_limit(self, asset_class: str) -> float:
    def get_asset_leverage(self, asset_class: str) -> float:
    def get_available_capital(self) -> float:
    def is_strategy_enabled(self, strategy_name: str) -> bool:
    def get_sigma_multipliers(self, regime: str) -> Dict[str, float]:
    def validate_critical_values(self) -> List[str]:
``

## File: .\app\constants.py
``python
from typing import Dict
from app.models.enums import (  # noqa: F401
class SigmaRiskConfig:
    def get_multipliers(cls, regime: RegimeType) -> Dict[str, float]:
``

## File: .\app\control_plane.py
``python
import json
import time
import logging
import threading
import os
import tempfile
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any, List, Callable
from dataclasses import dataclass, asdict
from app.constants import ControlMode, RiskProfile, SleeveType
from app.models import ControlCommand, SystemStatus
class ControlState:
    def __post_init__(self):
class ModeFileHandler(FileSystemEventHandler):
    def __init__(self, control_plane, debounce_ms=100):
    def _process_change(self):
    def on_modified(self, event):
    def on_created(self, event):
class ControlPlane:
    def __init__(self, control_dir="control", mode_file="mode.txt", config=None):
    def _verify_file_content(self, expected_mode):
    def _atomic_write_mode(self, content, max_retries=3):
    def _init_mode_file(self):
    def _load_mode_from_file(self):
    def _set_mode_internal(self, mode, reason):
    def start(self):
    def _start_polling_thread(self):
    def stop(self):
    def _monitor_loop(self):
    def set_mode(self, mode, reason=""):
    def get_mode(self):
    def get_state(self):
    def register_mode_change_callback(self, callback):
    def get_exposure_multiplier(self):
    def notify_kill_switch_triggered(self):
    def reset_kill_switch(self):
    def process_command(self, command):
    def get_status_response(self):
    def should_allow_trading(self, strategy=None):
    def should_allow_entry(self, strategy):
    def get_effective_risk_profile(self, base_profile):
    def get_aggression_scaling(self, base_scaling):
    def execute_emergency_halt(self, reason):
``

## File: .\app\instrument_registry.py
``python
import logging
import math
from datetime import datetime
from typing import Dict, Optional, List, Any, Tuple
from dataclasses import dataclass, field
from app.constants import AssetClass, MarketSession, ExchangeType
class InstrumentSpec:
    def __post_init__(self):
class InstrumentRegistry:
    def _init_crypto(cls):
    def _init_equities(cls):
    def _init_etfs(cls):
    def _init_futures(cls):
    def initialize(cls):
    def get_instrument(cls, symbol: str) -> Optional[InstrumentSpec]:
    def get_asset_class(cls, symbol: str) -> Optional[AssetClass]:
    def get_exchange(cls, symbol: str) -> Optional[ExchangeType]:
    def get_session(cls, symbol: str) -> MarketSession:
    def get_min_size(cls, symbol: str) -> float:
    def get_step_size(cls, symbol: str) -> float:
    def get_tick_size(cls, symbol: str) -> float:
    def round_quantity(cls, symbol: str, quantity: float) -> float:
    def round_price(cls, symbol: str, price: float, side: str) -> float:
    def is_tradable_now(cls, symbol: str, current_time: Optional[datetime] = None) -> bool:
    def _is_equity_hours(cls, dt: datetime) -> bool:
    def _is_futures_hours(cls, dt: datetime) -> bool:
    def get_risk_multiplier(cls, symbol: str) -> float:
    def get_liquidity_multiplier(cls, symbol: str) -> float:
    def get_all_symbols(cls, asset_class: Optional[AssetClass] = None) -> List[str]:
    def get_symbols_by_exchange(cls, exchange: ExchangeType) -> List[str]:
    def validate_order(cls, symbol: str, quantity: float, price: Optional[float] = None, side: Optional[str] = None) -> Tuple[bool, str]:
    def get_whale_threshold_usd(cls, symbol: str) -> float:
``

## File: .\app\main_loop.py
``python
import logging
import time
import threading
from datetime import datetime
from typing import Optional, Dict, Any
from dataclasses import dataclass
from app.config import Config
from app.commander import Commander
from app.risk.guard import HybridRiskGuard
from app.brain.signal_fusion import SignalFusion
from app.brain.data_validator import DataContinuityValidator
from app.brain.recalibrator import Recalibrator
from app.brain.shans_curve import ShansCurve
from app.brain.topological_engine import TopologicalEngine, TopologicalSignal
from app.brain.regime_detector import RegimeDetector
from app.brain.physical_validator import PhysicalValidator
from app.brain.toxicity_engine import ToxicityEngine, ToxicityAlert
from app.brain.entropy_decoder import EntropyDecoder
from app.brain.insider_signal_engine import InsiderSignalEngine, InsiderSignalSnapshot
from app.execution.engine import ExecutionEngine
from app.models import (
from app.models.enums import RegimeType
def _ns_to_datetime(ns: int) -> datetime:
class LoopMetrics:
class MainLoop:
    def __init__(
    def start(self) -> None:
    def stop(self) -> None:
    def on_order_book(self, order_book: OrderBookSnapshot) -> None:
    def on_candle(self, candle: Candle) -> None:
    def on_trade(self, size: float, price: float, side: int, exchange_ts_ns: int) -> None:
    def on_equity_update(self, current_equity: float, exchange_ts_ns: int) -> None:
    def _advance_recalibration(
    def _log_health(self) -> None:
    def get_status(self) -> Dict[str, Any]:
    def get_last_fusion(self) -> Optional[FusionDecision]:
    def get_last_tpe_signal(self) -> Optional[TopologicalSignal]:
    def get_metrics(self) -> LoopMetrics:
    def is_recalibrating(self) -> bool:
    def reset_metrics(self) -> None:
def create_main_loop(
``

## File: .\app\models.py
``python
``

## File: .\app\paper_tading.py
``python
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
class SovereignPaperTrader:
    def __init__(
    def _calculate_slippage_bps(
    def _calculate_fees(self, size: float, price: float, order_type: str) -> float:
    def _simulate_latency(self) -> float:
    def _execute_paper_order(
    def _update_portfolio(
    def _get_simulated_price(self, symbol: str) -> float:
    def _process_signal(self, fusion_decision) -> None:
    def _simulate_market_data(self) -> None:
    def _main_loop(self) -> None:
    def _log_health(self) -> None:
    def start(self) -> None:
    def stop(self) -> None:
    def get_status(self) -> Dict[str, Any]:
def register_graceful_death(paper_trader: SovereignPaperTrader) -> None:
    def death_handler(signum, frame):
def parse_arguments():
def main():
``

## File: .\app\session_manager.py
``python
import logging
from datetime import datetime, time, timedelta, date
from typing import Optional, Dict, List, Tuple
from enum import Enum
import pytz
from app.constants import MarketSession, AssetClass
class SessionManager:
    def __init__(self):
    def _get_us_holidays(self, year: int) -> List[date]:
    def _get_fallback_holidays(self, year: int) -> List[date]:
    def _get_nth_weekday_of_month(self, year: int, month: int, weekday: int, n: int) -> date:
    def _is_early_close_day(self, dt: datetime) -> Optional[int]:
    def _get_thanksgiving(self, year: int) -> Optional[date]:
    def is_holiday(self, dt: datetime) -> bool:
    def is_trading_day(self, dt: datetime) -> bool:
    def is_equity_hours(self, dt: Optional[datetime] = None, extended: bool = False) -> bool:
    def is_futures_hours(self, dt: Optional[datetime] = None) -> bool:
    def is_crypto_hours(self, dt: Optional[datetime] = None) -> bool:
    def is_session_open(self, session: MarketSession, dt: Optional[datetime] = None, extended: bool = False) -> bool:
    def get_next_open_time(self, session: MarketSession, from_time: Optional[datetime] = None, extended: bool = False) -> Optional[datetime]:
    def get_next_close_time(self, session: MarketSession, from_time: Optional[datetime] = None) -> Optional[datetime]:
    def get_remaining_session_time(self, session: MarketSession, dt: Optional[datetime] = None) -> float:
    def get_asset_class_session(self, asset_class: AssetClass) -> MarketSession:
    def is_tradable(self, asset_class: AssetClass, dt: Optional[datetime] = None, extended: bool = False) -> bool:
    def get_session_status(self, dt: Optional[datetime] = None) -> Dict[str, bool]:
    def is_extended_hours(self, dt: Optional[datetime] = None) -> bool:
``

## File: .\app\snapshot_exporter.py
``python
import json
import threading
import time
import logging
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, asdict
from app.models import (
from app.constants import ControlMode, SleeveType, RegimeType
class ExportSnapshot:
class SnapshotExporter:
    def __init__(
    def start(self):
    def stop(self):
    def update_state(
    def _export_loop(self):
    def _atomic_write(self, filepath: Path, content: str):
    def _export_snapshot(self):
    def _build_snapshot(self) -> Dict[str, Any]:
    def _cleanup_old_snapshots(self):
    def get_latest_snapshot(self) -> Optional[Dict[str, Any]]:
    def export_emergency_snapshot(self) -> bool:
    def get_snapshot_summary(self) -> Dict[str, Any]:
``

## File: .\app\__init__.py
``python
``

## File: .\app\api\dashboard_server.py
``python
import asyncio
import json
import logging
import threading
import time
import hashlib
from typing import Dict, Any, List, Optional, Set
from datetime import datetime
from dataclasses import dataclass, field, asdict
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
class ConnectionState:
class SovereignDashboard:
    def __init__(self, bot_instance: Any = None, api_key: str = "", use_delta_compression: bool = True):
    def _setup_routes(self) -> None:
    def _compute_hash(self, state: Dict[str, Any]) -> str:
    def _compute_delta(self, old_state: Dict[str, Any], new_state: Dict[str, Any]) -> Dict[str, Any]:
        def compare_dicts(old: Dict, new: Dict, path: str = ""):
    def _serialize_message(self, data: Dict[str, Any], is_delta: bool = False) -> str:
    def _add_connection(self, connection: ConnectionState) -> None:
    def _remove_connection(self, client_id: str) -> None:
    def _get_bot_status(self) -> Dict[str, Any]:
    def _build_full_state_packet(self) -> Dict[str, Any]:
    def start(self, host: str = "0.0.0.0", port: int = 8080) -> None:
    def stop(self) -> None:
    def get_connections(self) -> int:
    def get_stats(self) -> Dict[str, Any]:
def create_dashboard(bot_instance: Any = None, api_key: str = "", use_delta_compression: bool = True) -> SovereignDashboard:
``

## File: .\app\api\__init__.py
``python
``

## File: .\app\api\templates\__init__.py
``python
``

## File: .\app\brain\convexity_switch.py
``python
import logging
import numpy as np
from typing import Optional, Dict, List, Tuple, Any
from datetime import datetime, timedelta
from collections import deque
class ConvexitySwitch:
    def __init__(
    def update(self, symbol: str, returns: float, benchmark_returns: Optional[float] = None) -> str:
    def _init_symbol_history(self, symbol: str) -> None:
    def _determine_regime(self, symbol: str) -> str:
    def _calculate_confidence(self, symbol: str, regime: str) -> float:
    def get_current_regime(self, symbol: str) -> str:
    def get_confidence(self, symbol: str) -> float:
    def get_correlation_history(self, symbol: str, window: int = 50) -> List[float]:
    def get_volatility_history(self, symbol: str, window: int = 50) -> List[float]:
    def get_regime_history(self, symbol: str, window: int = 20) -> List[str]:
    def get_smoothed_regime(self, symbol: str) -> str:
    def get_strategy_weight(self, symbol: str) -> Dict[str, float]:
    def update_benchmark(self, returns: float) -> None:
    def get_market_regime(self) -> str:
    def reset(self, symbol: str) -> None:
    def get_stats(self, symbol: str) -> Dict[str, Any]:
``

## File: .\app\brain\data_validator.py
``python
import logging
import math
import re
from typing import Optional, Tuple, Dict, Any
from datetime import datetime, timezone
from dataclasses import dataclass
from app.utils.time_utils import now_ns
def _datetime_to_ns(dt: datetime) -> int:
def _ns_to_datetime(ns: int) -> datetime:
class ContinuityState:
class DataContinuityValidator:
    def __init__(
    def validate_numeric(
    def validate_price_volume(
    def _validate_symbol(self, symbol: str) -> Tuple[bool, str]:
    def _get_state(self, symbol: str) -> ContinuityState:
    def validate_sequence(
    def validate_timestamp(
    def validate_staleness(
    def record_websocket_heartbeat(self, symbol: str) -> None:
    def is_websocket_alive(self, symbol: str) -> bool:
    def record_data(self, symbol: str, timestamp: datetime) -> None:
    def mark_good(self, symbol: str) -> None:
    def is_data_healthy(self, symbol: str) -> bool:
    def validate(
    def get_continuity_status(self, symbol: str) -> Dict[str, Any]:
    def reset(self, symbol: str) -> None:
    def reset_all(self) -> None:
``

## File: .\app\brain\entropy_decoder.py
``python
from collections import deque
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Deque, List, Optional, Tuple
import numpy as np
from app.models.entropy_score import EntropyScore
from app.models.enums import CollapseQuality
class EntropyState:
class EntropyDecoder:
    def __init__(self):
    def update(
    def _velocity(self) -> float:
    def _curvature(self) -> float:
    def _structural_score(
    def _dead_score(
    def _fake_calm_score(
    def _reorg_score(
    def _chaos_score(
    def _exhausted_score(self, velocity: float, curvature: float) -> float:
    def _coherence(self) -> float:
    def _coherence_trend(self) -> float:
    def _stabilization(self) -> float:
    def _instability(self, velocity: float, curvature: float) -> float:
    def _is_sustained_dead(self, entropy: float, velocity: float) -> bool:
    def _classify(
    def _hysteresis(self, new: CollapseQuality) -> CollapseQuality:
    def _rank(q: CollapseQuality) -> int:
    def _confidence(
    def _magnitude(
    def reset(self) -> None:
``

## File: .\app\brain\insider_signal_engine.py
``python
from __future__ import annotations
import logging
from dataclasses import dataclass, field
from decimal import Decimal, getcontext
from enum import Enum, auto
from typing import Dict, List, Optional, Sequence, Tuple, Mapping, Any, Set
from collections import deque
class ObservationDirection(Enum):
class ObservationSourceType(Enum):
class DirectionalBias(Enum):
class SymbolTier(Enum):
class InsiderObservation:
class InsiderSignalSnapshot:
    def urgency(self) -> Decimal:
    def to_float(self) -> float:
    def to_dict(self) -> Dict[str, Any]:
class _EntityActivity:
    def net_contribution(self) -> Decimal:
class _SymbolState:
    def add_observation_id(self, obs_id: str, timestamp_ns: int) -> bool:
    def has_observation_id(self, obs_id: str) -> bool:
    def collapse_dead_zone(self, thresholds: Dict[str, Decimal]) -> None:
    def _has_state_changed(self, old_active: bool, old_degraded: bool, old_invalidated: bool) -> bool:
    def _recompute_derived(self, thresholds: Dict[str, Decimal]) -> None:
class InsiderSignalEngine:
    def __init__(
    def _clamp_decimal(value: Decimal, min_val: Decimal = MIN_SCORE, max_val: Decimal = MAX_SCORE) -> Decimal:
    def _get_tier_thresholds(self, tier: SymbolTier) -> Dict[str, Decimal]:
    def _validate_observation(obs: InsiderObservation) -> None:
    def _validate_modifier(modifier: Optional[Decimal], name: str, max_val: Decimal = DECIMAL_ONE) -> Optional[Decimal]:
    def _compute_base_contribution(self, obs: InsiderObservation, entity_reputation: Decimal) -> Tuple[Decimal, Decimal]:
    def _apply_context_modifiers(
    def _compute_cluster_strength(self, state: _SymbolState, current_ts_ns: int) -> Decimal:
    def _compute_cross_entity_alignment(self, state: _SymbolState, current_ts_ns: int) -> Decimal:
    def _update_contradiction_pressure(self, state: _SymbolState, new_bullish: Decimal, new_bearish: Decimal) -> Decimal:
    def _update_invalidation_pressure(self, state: _SymbolState, obs_invalidation: Decimal) -> Decimal:
    def _apply_decay_to_state(self, state: _SymbolState, current_ts_ns: int) -> None:
    def set_symbol_tier(self, symbol: str, tier: SymbolTier) -> None:
    def ingest_observation(
    def ingest_batch(
    def apply_decay(self, timestamp_ns: int) -> None:
    def invalidate(
    def snapshot_for_symbol(self, symbol: str) -> Optional[InsiderSignalSnapshot]:
    def get_or_default_snapshot(self, symbol: str, timestamp_ns: int) -> "InsiderSignalSnapshot":
    def reset_symbol(self, symbol: str) -> None:
    def prune(self, timestamp_ns: int) -> None:
    def export_state(self) -> Dict[str, InsiderSignalSnapshot]:
    def export_state_payload(self) -> Dict[str, Any]:
    def load_state_payload(self, payload: Mapping[str, Any]) -> None:
    def reset(self) -> None:
``

## File: .\app\brain\physical_validator.py
``python
import logging
from typing import Optional, Dict, List, Any
from datetime import datetime
from collections import deque
import numpy as np
from app.models import PhysicalVerification
from app.utils.time_utils import now_ns
class PhysicalValidator:
    def __init__(
    def record_latency(
    def _record_latency_original(
    def _record_latency_deterministic(
    def _init_exchange_history(self, exchange: str) -> None:
    def _calculate_expected_impact(self, exchange: str, order_size: float) -> float:
    def _detect_toxicity(self, exchange: str, latency_ms: float, price_impact_bps: float) -> bool:
    def _get_deterministic_physical_data(self, exchange: str) -> Dict[str, Any]:
    def to_fusion_dict(self, exchange: str) -> Dict[str, float]:
    def get_fusion_health_score(self, exchange: str) -> float:
    def get_current(self, exchange: str) -> Optional[PhysicalVerification]:
    def get_latency_stats(self, exchange: str) -> Dict[str, float]:
    def get_toxicity_rate(self, exchange: str, window: int = 100) -> float:
    def get_impact_analysis(self, exchange: str) -> Dict[str, float]:
    def get_exchange_health(self, exchange: str) -> Dict[str, Any]:
    def get_best_exchange(self, symbols: List[str]) -> str:
    def reset(self, exchange: str) -> None:
    def get_stats(self, exchange: str) -> Dict[str, Any]:
``

## File: .\app\brain\recalibrator.py
``python
import logging
import math
import threading
from typing import Dict, Any, Optional
from datetime import datetime
from dataclasses import dataclass
from app.brain.topological_engine import TopologicalSignal
from app.utils.time_utils import now_ns
class RecalibrationState:
class Recalibrator:
    def __init__(
    def evaluate_regime(
    def start_recalibration(self, reason: str, duration_seconds: float) -> None:
    def end_recalibration(self) -> None:
    def is_in_recalibration(self) -> bool:
    def get_recalibration_remaining(self) -> float:
    def get_recovery_strategy(self) -> Dict[str, Any]:
    def should_recover(self) -> bool:
    def reset_recovery_count(self) -> None:
    def get_last_topological_metrics(self) -> Dict[str, Any]:
    def _ns_to_iso(self, ns: Optional[int]) -> Optional[str]:
    def get_status(self) -> Dict[str, Any]:
    def reset(self) -> None:
``

## File: .\app\brain\regime_detector.py
``python
import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Deque, Union, Any
from collections import deque
import numpy as np
from app.models.enums import RegimeType
class RegimeEvidence:
class CachedRegimeState:
class RegimeDetector:
    def __init__(self, config: Optional[Union[Dict[str, Any], Any]] = None):
    def update(
    def update_candles(
    def get_current_regime(self) -> RegimeType:
    def get_current_confidence(self) -> float:
    def get_regime_state(self) -> Optional[CachedRegimeState]:
    def should_authorize_sleeve(self, sleeve_name: str, regime: Optional[RegimeType] = None) -> bool:
    def get_risk_modifier(self, regime: Optional[RegimeType] = None) -> float:
    def _calc_safe_slope(self, data: List[float]) -> float:
    def _calc_market_efficiency(self, data: List[float]) -> float:
    def _compute_evidence(self, current_volatility: float) -> RegimeEvidence:
    def _classify_from_evidence(self, evidence: RegimeEvidence) -> Tuple[RegimeType, float]:
    def _apply_transition_discipline(self, new_regime: RegimeType, new_confidence: float) -> Tuple[RegimeType, float]:
    def reset(self) -> None:
``

## File: .\app\brain\ring_buffer.py
``python
import numpy as np
from typing import Optional, Tuple, Any, List
from dataclasses import dataclass
from app.utils.time_utils import now_ns
class RingBuffer:
    def __init__(self, max_size: int, dtype: type = np.float64, track_timestamps: bool = False):
    def enable_timestamp_tracking(self) -> None:
    def append(self, value: float, timestamp_ns: Optional[int] = None) -> None:
    def append_batch(self, values: List[float], timestamps_ns: Optional[List[int]] = None) -> None:
    def get(self) -> np.ndarray:
    def get_with_timestamps(self) -> Tuple[np.ndarray, np.ndarray]:
    def get_window(self, window_size: int) -> np.ndarray:
    def get_window_with_timestamps(self, window_size: int) -> Tuple[np.ndarray, np.ndarray]:
    def get_recent(self, count: int) -> np.ndarray:
    def get_all(self) -> np.ndarray:
    def last(self) -> float:
    def last_with_timestamp(self) -> Tuple[float, int]:
    def first(self) -> float:
    def first_with_timestamp(self) -> Tuple[float, int]:
    def __len__(self) -> int:
    def is_full(self) -> bool:
    def is_empty(self) -> bool:
    def clear(self) -> None:
    def get_stats(self) -> dict:
class MultiRingBuffer:
    def __init__(self, max_size: int = 1000, dtype: type = np.float64):
    def get_buffer(self, symbol: str, track_timestamps: bool = False) -> RingBuffer:
    def append(self, symbol: str, value: float, timestamp_ns: Optional[int] = None) -> None:
    def get(self, symbol: str) -> np.ndarray:
    def get_window(self, symbol: str, window: int) -> np.ndarray:
    def evict_expired(self, current_ts_ns: int, ttl_seconds: float = 60.0) -> int:
    def clear(self, symbol: str) -> None:
    def clear_all(self) -> None:
class RollingStatistics:
    def __init__(self, window_size: int = 100):
    def update(self, value: float) -> None:
    def mean(self) -> float:
    def variance(self) -> float:
    def std(self) -> float:
    def zscore(self, value: float) -> float:
    def reset(self) -> None:
``

## File: .\app\brain\rolling_stats.py
``python
import numpy as np
from typing import Optional, Tuple
from app.brain.ring_buffer import RingBuffer
class RollingStats:
    def __init__(self, window_size: int = 100, track_timestamps: bool = False):
    def update(self, value: float, timestamp_ns: Optional[int] = None) -> None:
    def _add(self, x: float) -> None:
    def _remove(self, x: float) -> None:
    def mean(self) -> float:
    def variance(self) -> float:
    def sample_variance(self) -> float:
    def std(self) -> float:
    def sample_std(self) -> float:
    def skew(self) -> float:
    def kurtosis(self) -> float:
    def zscore(self, value: float) -> float:
    def quantile(self, q: float) -> float:
    def percentile(self, p: float) -> float:
    def sum(self) -> float:
    def count(self) -> int:
    def is_full(self) -> bool:
    def get_buffer(self) -> RingBuffer:
    def get_values(self) -> np.ndarray:
    def get_values_with_timestamps(self) -> Tuple[np.ndarray, np.ndarray]:
    def reset(self) -> None:
    def get_stats(self) -> dict:
class RollingCorrelation:
    def __init__(self, window_size: int = 100):
    def update(self, x: float, y: float) -> None:
    def _add(self, x: float, y: float) -> None:
    def _remove(self, x: float, y: float) -> None:
    def correlation(self) -> float:
    def covariance(self) -> float:
    def count(self) -> int:
    def reset(self) -> None:
``

## File: .\app\brain\sentiment_engine.py
``python
import numpy as np
import logging
from typing import Dict, Optional, List, Any, Tuple
from dataclasses import dataclass, field
from collections import deque
class SourceSentiment:
class AggregateSentiment:
class SentimentEngine:
    def __init__(
    def _init_symbol_sources(self, symbol: str) -> None:
    def _get_source_weight(self, source: str) -> float:
    def _freshness_weight(self, age_ns: int) -> float:
    def _compute_agreement(self, values: List[float], weights: List[float]) -> Tuple[float, float]:
    def update_source(
    def aggregate(self, symbol: str, current_ts_ns: int) -> Optional[AggregateSentiment]:
    def get_sentiment_level(self, symbol: str, current_ts_ns: int) -> Optional[float]:
    def get_aggregate(self, symbol: str) -> Optional[AggregateSentiment]:
    def get_source_count(self, symbol: str) -> int:
    def get_source_recent(self, symbol: str, source: str, count: int = 5) -> List[SourceSentiment]:
    def get_stats(self, symbol: str, current_ts_ns: int) -> Dict[str, Any]:
    def reset(self, symbol: Optional[str] = None) -> None:
``

## File: .\app\brain\sentiment_velocity.py
``python
import numpy as np
import logging
from typing import Dict, Optional, Tuple, Any
from dataclasses import dataclass
from collections import deque
class SentimentPoint:
class SentimentVector:
class MacroSignal:
class SentimentVelocityEngine:
    def __init__(
    def update_sentiment(self, value: float, timestamp_ns: int) -> Optional[SentimentVector]:
    def _compute_current_level(self) -> float:
    def _compute_velocity(self) -> float:
    def _compute_acceleration(self) -> float:
    def _compute_impulse(self) -> float:
    def _compute_divergence(self, level: float, velocity: float) -> float:
    def _compute_reversion_pressure(self, level: float) -> float:
    def _compute_stability(self) -> float:
    def _compute_confidence(self, current_ts_ns: int) -> float:
    def _compute_velocity_z_score(self) -> float:
    def analyze(
    def get_current_vector(self) -> Optional[SentimentVector]:
    def get_macro_signal(self) -> Optional[MacroSignal]:
    def get_stats(self) -> Dict[str, Any]:
    def reset(self) -> None:
``

## File: .\app\brain\shadow_front_state.py
``python
import logging
import struct
import hashlib
from typing import Optional, Dict, Any, Tuple, Callable
from enum import IntEnum
from dataclasses import dataclass
class ShadowFrontState(IntEnum):
class StateTransition:
class WhaleContext:
class SentimentContext:
class RegimeContext:
class FusionContext:
class ShadowFrontStateMachine:
    def __init__(
    def _is_context_fresh(self, timestamp_ns: int, current_ts_ns: int, max_age_ns: int) -> bool:
    def _is_whale_fresh(self, current_ts_ns: int) -> bool:
    def _is_sentiment_fresh(self, current_ts_ns: int) -> bool:
    def _is_regime_fresh(self, current_ts_ns: int) -> bool:
    def _is_fusion_fresh(self, current_ts_ns: int) -> bool:
    def _validate_context_timestamp(self, context_ts_ns: int, current_ts_ns: int, context_name: str) -> bool:
    def _check_channel_monotonicity(self, channel_name: str, new_ts_ns: int, last_ts_ns: Optional[int]) -> bool:
    def update_whale_context(self, context: WhaleContext, current_ts_ns: int) -> None:
    def update_sentiment_context(self, context: SentimentContext, current_ts_ns: int) -> None:
    def update_regime_context(self, context: RegimeContext, current_ts_ns: int) -> None:
    def update_fusion_context(self, context: FusionContext, current_ts_ns: int) -> None:
    def _calculate_conflict_penalty(self, current_ts_ns: int) -> float:
    def _calculate_alignment_bonus(self, current_ts_ns: int) -> float:
    def _calculate_armed_confidence(self, current_ts_ns: int) -> float:
    def _should_advance_to_armed(self, current_ts_ns: int) -> bool:
    def _should_enter_position(self, current_price: float, current_ts_ns: int) -> bool:
    def _should_exit_position(self, current_price: float, current_ts_ns: int) -> Tuple[bool, str]:
    def _should_cooldown_expire(self, current_ts_ns: int) -> bool:
    def _should_macro_kill_expire(self, current_ts_ns: int) -> bool:
    def _transition_to(self, new_state: ShadowFrontState, timestamp_ns: int, reason: str) -> None:
    def serialize_state(self) -> bytes:
    def deserialize_state(self, data: bytes) -> None:
    def compute_state_hash(self) -> bytes:
    def state_hash_hex(self) -> str:
    def _broadcast_serialized_state(self) -> None:
    def publish_state(self) -> None:
    def update(self, current_price: float, current_ts_ns: int) -> Optional[str]:
    def record_entry(self, price: float, size: float, timestamp_ns: int) -> None:
    def record_exit(self, price: float, pnl: float, timestamp_ns: int) -> None:
    def get_current_state(self) -> ShadowFrontState:
    def get_state_name(self) -> str:
    def is_ready_for_entry(self) -> bool:
    def is_in_position(self) -> bool:
    def get_entry_price(self) -> Optional[float]:
    def get_position_size(self) -> float:
    def get_pnl(self) -> float:
    def get_whale_zone(self) -> Tuple[Optional[float], Optional[float]]:
    def get_whale_confidence(self) -> float:
    def get_armed_confidence(self, current_ts_ns: int) -> float:
    def get_conflict_penalty(self, current_ts_ns: int) -> float:
    def get_alignment_bonus(self, current_ts_ns: int) -> float:
    def get_transition_history(self, count: int = 10) -> list:
    def get_status(self, current_ts_ns: int) -> Dict[str, Any]:
    def reset(self, current_ts_ns: int) -> None:
``

## File: .\app\brain\shans_curve.py
``python
import logging
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Deque, Dict, List, Optional, Tuple, Union
import numpy as np
        def njit(*args, **kwargs):
            def decorator(fn):
from app.brain.ring_buffer import RingBuffer
from app.brain.data_validator import DataContinuityValidator
from app.risk.guard import HybridRiskGuard
from app.risk.safety import SafetyGate
from app.brain.entropy_decoder import EntropyDecoder
class _ConfidenceDecayState:
    def apply_decay(self, current_confidence: float, current_ts_ns: int) -> float:
class _BiasSmoother:
    def update(self, raw_bias_int: int) -> int:
class ShansCurveSignal:
    def __post_init__(self):
class ShansCurveComputation:
def solve_asymptotic_kinematics(
def _betti_1_persistence(points: np.ndarray, threshold: float = 0.01) -> float:
def _savitzky_golay(y: np.ndarray, window_size: int, poly_order: int) -> np.ndarray:
class ShansCurve:
    def __init__(
    def _to_nanoseconds(ts: Union[int, datetime]) -> int:
    def _datetime_from_ns(ns: int) -> datetime:
    def _extract_entropy_value(self, symbol: str) -> float:
    def _compute_shape_persistence_proxy(self, p_arr: np.ndarray, ofi_arr: np.ndarray) -> float:
    def _apply_denoising(self, arr: np.ndarray) -> np.ndarray:
    def _compute_support_density(
    def _compute_air_gap_penalty(self, symbol: str, timestamp_ns: int) -> float:
    def record_fill(self, symbol: str, fill_price: float, fill_size: float, timestamp_ns: int) -> None:
    def _build_neutral_computation(self, symbol: str, ts_ns: int, reason: str) -> ShansCurveComputation:
    def _compute_signal_artifact(
    def update_order_book(
    def get_last_computation(self) -> Optional[ShansCurveComputation]:
    def to_fusion_fields(
    def get_stats(self) -> Dict[str, Any]:
    def reset(self) -> None:
``

## File: .\app\brain\signal_fusion.py
``python
import math
import logging
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
from app.models.fusion import FusionDecision
from app.models.enums import RegimeType, SleeveType
from app.brain.toxicity_engine import ToxicityRegime
class QuantMath:
    def exponential_decay(value: float, steepness: float = 3.0) -> float:
    def temperature_threshold(base_threshold: float, entropy: float, max_penalty: float = 0.3) -> float:
    def temporal_discount(age_ns: int, half_life_ns: int) -> float:
    def vector_resonance(direction_a: int, confidence_a: float, bias_b: float) -> float:
    def kelly_calibration_curve(raw_confidence: float) -> float:
class HysteresisState:
    def update_kinematics(self, current_entropy: float, current_toxicity: float, current_ts_ns: int) -> None:
    def register_decision(self, is_attack_mode: bool) -> None:
class SignalFusion:
    def __init__(self, config: Any, commander: Any = None):
    def _ingest(self, key: str, payload: Any, timestamp_ns: int) -> None:
    def update_whale(self, payload: Any, timestamp_ns: int) -> None:
    def update_shans(self, payload: Any, timestamp_ns: int) -> None:
    def update_regime(self, payload: Any, timestamp_ns: int) -> None:
    def update_entropy(self, payload: Any, timestamp_ns: int) -> None:
    def update_insider(self, payload: Any, timestamp_ns: int) -> None:
    def update_toxicity(self, payload: Any, timestamp_ns: int) -> None:
    def update_physical(self, payload: Any, timestamp_ns: int) -> None:
    def get_last_fusion(self) -> Optional[FusionDecision]:
    def get_fusion_telemetry(self) -> Dict[str, Any]:
    def _bridge_shans_bias(self, raw_bias: float) -> str:
    def fuse(self, current_ts_ns: int) -> FusionDecision:
    def _issue_hard_veto(self, current_ts_ns: int, reason: str) -> FusionDecision:
``

## File: .\app\brain\topological_engine.py
``python
import numpy as np
import logging
from typing import Dict, Optional, List, Tuple, Any
from dataclasses import dataclass
from collections import deque
from scipy.spatial.distance import pdist, squareform
from scipy.cluster.hierarchy import fcluster, linkage
from app.brain.ring_buffer import RingBuffer
from app.models import OrderBookSnapshot
class TopologicalSignal:
class TopologicalEngine:
    def __init__(
    def _generate_point_cloud(self, order_book: OrderBookSnapshot) -> np.ndarray:
    def _normalize_points(self, points: np.ndarray) -> np.ndarray:
    def _compute_betti_numbers(self, adj_matrix: np.ndarray) -> Tuple[int, int]:
        def bfs(start: int) -> None:
    def _compute_persistence(self, points: np.ndarray) -> Tuple[List[float], List[int], List[int]]:
    def _calculate_liquidity_usd(self, order_book: OrderBookSnapshot) -> float:
    def _detect_super_void(self, order_book: OrderBookSnapshot, points: np.ndarray, betti_1_history: List[int]) -> bool:
    def _detect_structural_collapse(self, points: np.ndarray, betti_0_history: List[int]) -> bool:
    def analyze(self, order_book: OrderBookSnapshot) -> TopologicalSignal:
    def get_last_signal(self) -> Optional[TopologicalSignal]:
    def is_coherent(self) -> bool:
    def is_fragmented(self) -> bool:
    def get_stats(self) -> Dict[str, Any]:
    def reset(self) -> None:
``

## File: .\app\brain\toxicity_engine.py
``python
import logging
import numpy as np
import struct
import hashlib
from typing import Optional, Dict, List, Tuple, Any
from dataclasses import dataclass
from collections import deque
from enum import IntEnum
class ToxicityRegime(IntEnum):
class ToxicityAlert:
class L2Snapshot:
class VenueSnapshot:
class RealizedOutcome:
class ToxicityEngine:
    def __init__(
    def _validate_timestamp(self, timestamp_ns: int, context: str) -> bool:
    def _check_channel_monotonicity(self, channel: str, new_ts_ns: int, per_venue_key: Optional[str] = None, commit: bool = True) -> bool:
    def update_trade(self, size: float, price: float, side: int, timestamp_ns: int) -> None:
    def _finalize_bucket(self, timestamp_ns: int) -> None:
    def update_candle(self, volume: float, high: float, low: float, close: float, timestamp_ns: int) -> None:
    def update_order_book(self, snapshot: L2Snapshot) -> None:
    def update_venue_snapshot(self, snapshot: VenueSnapshot) -> None:
    def _calculate_fragmentation_score(self) -> float:
    def update_outcome(self, outcome: RealizedOutcome) -> None:
    def _update_calibration_weights(self, error: float, realized_score: float) -> None:
    def _calculate_vpin_score(self) -> float:
    def _calculate_burst_pressure(self, current_ts_ns: int) -> float:
    def _calculate_instability_score(self) -> float:
    def _calculate_volume_anomaly_score(self) -> float:
    def _calculate_l2_toxicity(self) -> float:
    def _calculate_fragmentation_toxicity(self) -> float:
    def _get_dynamic_weights(self) -> Dict[str, float]:
    def _calculate_persistence(self, current_toxicity: float, current_ts_ns: int) -> float:
    def _calculate_direction_bias(self) -> str:
    def update_toxicity(self, current_ts_ns: int) -> ToxicityAlert:
    def get_last_alert(self) -> Optional[ToxicityAlert]:
    def is_toxic(self) -> bool:
    def get_suppression_factor(self) -> float:
    def get_calibration_weights(self) -> Dict[str, float]:
    def get_calibration_stats(self) -> Dict[str, Any]:
    def get_stats(self) -> Dict[str, Any]:
    def serialize_state(self) -> bytes:
    def deserialize_state(self, data: bytes) -> None:
    def compute_state_hash(self) -> bytes:
    def state_hash_hex(self) -> str:
    def reset(self) -> None:
``

## File: .\app\brain\whale_flow_engine.py
``python
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Deque, Union, Any
from collections import deque
from enum import IntEnum
import numpy as np
class WhaleDirection(IntEnum):
class AbnormalityLevel(IntEnum):
class WhaleFlowAlert:
class WhaleEvidence:
class CachedWhaleState:
class WhaleFlowEngine:
    def __init__(self, config: Optional[Union[Dict[str, Any], Any]] = None):
    def update(
    def get_current_alert(self) -> Optional[WhaleFlowAlert]:
    def get_current_direction(self) -> WhaleDirection:
    def get_current_confidence(self) -> float:
    def get_age_ns(self, current_ts_ns: int) -> int:
    def get_time_since_refresh(self, current_ts_ns: int) -> int:
    def get_directional_bias(self) -> float:
    def get_conviction_multiplier(self) -> float:
    def _update_rolling_baseline(self) -> None:
    def _get_latest_timestamp(self) -> int:
    def _get_staleness_ratio(self, timestamp_ns: int, latest_ts: int) -> float:
    def _compute_recency_weighted_persistence(self) -> float:
    def _compute_recency_weighted_concentration(self) -> float:
    def _compute_acceleration(self) -> float:
    def _determine_tier(self, normalized_avg: float, concentration: float) -> int:
    def _compute_absorption_score(self, flow_imbalance: float, concentration: float, volume_zscore: float) -> float:
    def _compute_abnormality(
    def _apply_gap_aware_decay(self, persistence: float) -> float:
    def _apply_freshness_gating(self, confidence: float, timestamp_ns: int, latest_ts: int, staleness_ratio: float) -> float:
    def _classify_from_evidence(self, evidence: WhaleEvidence, tier: int) -> Tuple[WhaleDirection, float]:
    def _apply_persistence_decay(self, raw_direction: WhaleDirection, raw_confidence: float) -> Tuple[WhaleDirection, float]:
    def reset(self) -> None:
``

## File: .\app\brain\whale_zone_engine.py
``python
import math
import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Deque, Union, Any
from collections import deque
from enum import IntEnum
import numpy as np
class ZoneBias(IntEnum):
class WhalePresenceZone:
class CandleEvidence:
class CachedZoneState:
class WhaleZoneEngine:
    def __init__(self, config: Optional[Union[Dict[str, Any], Any]] = None):
    def update(
    def get_zone(self, symbol: str) -> Optional[WhalePresenceZone]:
    def get_age_ns(self, symbol: str, current_ts_ns: int) -> int:
    def get_time_since_refresh(self, symbol: str, current_ts_ns: int) -> int:
    def is_in_zone(self, symbol: str, price: float) -> Tuple[bool, float]:
    def get_zone_bias(self, symbol: str) -> ZoneBias:
    def get_zone_confidence(self, symbol: str) -> float:
    def get_zone_bounds(self, symbol: str) -> Tuple[Optional[float], Optional[float]]:
    def reset(self, symbol: Optional[str] = None) -> None:
    def _get_state(self, symbol: str) -> CachedZoneState:
    def _update_volume_baseline(self, symbol: str, volume: float) -> None:
    def _compute_accumulation_score(self, evidence: CandleEvidence) -> float:
    def _detect_zone_clusters(self, state: CachedZoneState) -> Optional[Tuple[float, float, float, int, ZoneBias]]:
    def _apply_confidence_decay(self, zone: WhalePresenceZone, exchange_ts_ns: int) -> Optional[WhalePresenceZone]:
    def _detect_or_update_zone(
    def _update_zone_proximity(
``

## File: .\app\brain\__init__.py
``python
from app.brain.regime_detector import RegimeDetector
from app.brain.whale_flow_engine import WhaleFlowEngine
from app.brain.whale_zone_engine import WhaleZoneEngine, WhalePresenceZone, ZoneBias
from app.brain.sentiment_engine import SentimentEngine
from app.brain.signal_fusion import SignalFusion
from app.brain.shadow_front_state import ShadowFrontStateMachine
from app.brain.entropy_decoder import EntropyDecoder
from app.brain.physical_validator import PhysicalValidator
from app.brain.convexity_switch import ConvexitySwitch
from app.brain.shans_curve import ShansCurve, ShansCurveSignal
from app.brain.ring_buffer import RingBuffer, MultiRingBuffer
from app.brain.rolling_stats import RollingStats, RollingCorrelation
from app.brain.recalibrator import Recalibrator
from app.brain.topological_engine import TopologicalEngine, TopologicalSignal
from app.brain.sentiment_velocity import SentimentVelocityEngine, MacroSignal
from app.brain.insider_signal_engine import InsiderSignalEngine, InsiderSignalSnapshot
from app.brain.toxicity_engine import ToxicityEngine, ToxicityAlert
``

## File: .\app\core\decision_compiler.py
``python
from feature outputs, strategy votes, risk overlays, execution constraints,
import logging
from typing import Optional, Dict, Any, List
from uuid import uuid4
from app.models.contracts import (
from app.models.enums import DecisionType, RiskMode
from app.utils.time_utils import now_ns
class DecisionCompilerError(Exception):
class DecisionCompilerStateError(DecisionCompilerError):
def _safe_str(value: Any) -> str:
class DecisionCompiler:
    def __init__(self):
    def compile(
    def _build_outputs(
    def _determine_decision_type(
    def get_last_decision_uuid(self) -> Optional[str]:
    def reset(self) -> None:
def create_decision_compiler() -> DecisionCompiler:
``

## File: .\app\core\truth_kernel.py
``python
import logging
import threading
from typing import Optional, Dict, Any, Callable, Tuple
from dataclasses import dataclass
from app.models.contracts import (
from app.models.enums import TruthStatus
from app.utils.time_utils import now_ns
class TruthKernelError(Exception):
class TruthKernelStateError(TruthKernelError):
def _safe_str(value: Any) -> str:
class TruthKernelState:
    def has_all_truths(self) -> bool:
class TruthKernel:
    def __init__(self):
    def update_exchange_truth(self, exchange_truth: ExchangeTruth) -> None:
    def update_execution_truth(self, execution_truth: ExecutionTruth) -> None:
    def update_portfolio_truth(self, portfolio_truth: PortfolioTruth) -> None:
    def update_strategy_truth(self, strategy_truth: StrategyTruth) -> None:
    def update_risk_truth(self, risk_truth: RiskTruth) -> None:
    def get_current_truths(self) -> Dict[str, Any]:
    def create_truth_frame(
    def create_truth_frame_from_reconciler(
    def has_all_truths(self) -> bool:
    def get_last_truth_frame_id(self) -> Optional[str]:
    def get_last_frame_timestamp_ns(self) -> int:
    def get_frame_count(self) -> int:
    def get_current_exchange_truth(self) -> Optional[ExchangeTruth]:
    def get_current_execution_truth(self) -> Optional[ExecutionTruth]:
    def get_current_portfolio_truth(self) -> Optional[PortfolioTruth]:
    def get_current_strategy_truth(self) -> Optional[StrategyTruth]:
    def get_current_risk_truth(self) -> Optional[RiskTruth]:
    def register_frame_callback(self, callback: Callable[[TruthFrame], None]) -> None:
    def reset(self) -> None:
    def reset_truth(self, truth_name: str) -> None:
def create_truth_kernel() -> TruthKernel:
``

## File: .\app\core\truth_reconciler.py
``python
import logging
from typing import Optional, Tuple, List, Dict, Any
from dataclasses import dataclass
from app.models.contracts import (
from app.models.enums import TruthStatus
class TruthReconcilerError(Exception):
def _safe_str(value: Any) -> str:
class DivergenceInfo:
    def to_reason(self) -> str:
class TruthReconciler:
    def __init__(self):
    def reconcile(
    def get_truth_status(
    def _compare_exchange_execution(
    def _compare_exchange_portfolio(
    def _compare_portfolio_strategy(
    def _compare_strategy_risk(
    def _determine_status(
    def is_reconciled(self, status: TruthStatus) -> bool:
    def is_drifting(self, status: TruthStatus) -> bool:
    def is_broken(self, status: TruthStatus) -> bool:
def create_truth_reconciler() -> TruthReconciler:
``

## File: .\app\data\aggregator.py
``python
import numpy as np
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
from collections import deque
import threading
import time
import logging
from enum import Enum
from app.models.unified_market import UnifiedMarketData, InstrumentSpec, AssetClass, Exchange, now_ns
from app.execution.shared_memory import SharedMemoryManager
class FeedSource(Enum):
class Tick:
class LockFreeRingBuffer:
    def __init__(self, size: int = 10000):
    def write(self, item: Any) -> None:
    def read_all(self) -> List[Any]:
    def latest(self) -> Optional[Any]:
    def clear(self) -> None:
class VolatilityScaledThreshold:
    def __init__(self, base_threshold: float = 3.0, window: int = 50):
    def update(self, value: float) -> None:
    def get_threshold(self) -> float:
class MultiMarketAggregator:
    def __init__(
    def _register_instruments(self) -> None:
    def _get_instrument_id(self, symbol: str) -> Optional[int]:
    def _update_velocity(self, instrument_id: int, price: float, timestamp_ns: int) -> float:
    def _calculate_tape_pulse(self) -> Dict[str, float]:
    def _detect_ghost_tick(self, tick: Tick) -> Tuple[bool, float]:
    def ingest_tick(self, tick: Tick) -> bool:
    def ingest_kraken_tick(self, symbol: str, price: float, volume: float, timestamp_ns: int, bid: float = None, ask: float = None) -> bool:
    def ingest_alpaca_tick(self, symbol: str, price: float, volume: float, timestamp_ns: int) -> bool:
    def ingest_ibkr_tick(self, symbol: str, price: float, volume: float, timestamp_ns: int) -> bool:
    def get_stats(self) -> Dict[str, Any]:
    def start(self) -> None:
    def stop(self) -> None:
def create_aggregator(
``

## File: .\app\data\depth_book.py
``python
import logging
import numpy as np
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime
from collections import deque
from app.models import OrderBookSnapshot, LiquidityMetrics
class DepthBook:
    def __init__(self, symbol: str, max_depth_levels: int = 50):
    def update(self, snapshot: OrderBookSnapshot) -> None:
    def _update_micro_price(self) -> None:
    def best_bid(self) -> Optional[float]:
    def best_ask(self) -> Optional[float]:
    def mid_price(self) -> float:
    def micro_price(self) -> float:
    def spread(self) -> float:
    def spread_bps(self) -> float:
    def market_depth(self) -> float:
    def bid_depth(self) -> float:
    def ask_depth(self) -> float:
    def imbalance(self) -> float:
    def is_liquid(self) -> bool:
    def max_safe_position_size(self) -> float:
    def get_depth_at_levels(self, levels: int) -> Tuple[float, float]:
    def get_price_at_depth(self, side: str, target_volume: float) -> Optional[float]:
    def get_volume_weighted_price(self, side: str, volume: float) -> Optional[float]:
    def get_price_impact(self, side: str, volume: float) -> Optional[float]:
    def get_liquidity_void_score(self) -> float:
    def detect_liquidity_void(self) -> Tuple[bool, Dict[str, Any]]:
    def calculate_refill_velocity(self) -> float:
    def get_liquidity_metrics(self) -> LiquidityMetrics:
    def get_snapshot(self) -> Dict[str, Any]:
    def clear(self) -> None:
``

## File: .\app\data\feature_builder.py
``python
import logging
import numpy as np
from typing import List, Dict, Optional, Tuple, Any
from datetime import datetime
from collections import deque
from app.models import Candle, OrderBookSnapshot, LiquidityMetrics
class FeatureBuilder:
    def __init__(self, slow_window: int = 50, fast_window: int = 10):
    def calculate_volatility_zscore(self, candles: List[Candle], current_idx: int) -> float:
    def calculate_atr_normalized(self, candles: List[Candle], current_idx: int) -> float:
    def calculate_volume_anomaly_zscore(self, candles: List[Candle], current_idx: int) -> float:
    def calculate_return_burst(self, candles: List[Candle], current_idx: int) -> float:
    def calculate_spread_expansion(self, order_book: OrderBookSnapshot, historical_spreads: List[float]) -> float:
    def calculate_depth_contraction(self, order_book: OrderBookSnapshot, historical_depths: List[float]) -> float:
    def calculate_refill_velocity(self, depth_history: List[float], time_delta: float) -> float:
    def calculate_whale_zone_proximity(self, current_price: float, whale_zone_low: float, whale_zone_high: float) -> float:
    def build_all_features(self, candles: List[Candle], current_idx: int,
    def build_features_batch(self, candles: List[Candle], start_idx: int, end_idx: int,
``

## File: .\app\data\ghost_tick_detector.py
``python
import numpy as np
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
from collections import deque
import time
import logging
from app.models.unified_market import UnifiedMarketData, AssetClass, now_ns
from app.execution.shared_memory import SharedMemoryManager
class GhostTickResult:
class GhostTickDetector:
    def __init__(
    def _get_correlation_matrix(self) -> np.ndarray:
    def _get_price_vector(self, instrument_ids: List[int]) -> Optional[np.ndarray]:
    def _update_covariance(self, instrument_ids: List[int]) -> None:
    def _mahalanobis_distance(self, point: np.ndarray, mean: np.ndarray, cov: np.ndarray) -> float:
    def _get_adaptive_threshold(self, regime: str) -> float:
    def _get_correlated_assets(self, symbol: str) -> List[str]:
    def detect(self, symbol: str, price: float, volume: float, timestamp_ns: int) -> GhostTickResult:
    def detect_batch(self, ticks: List[Tuple[str, float, float, int]]) -> List[GhostTickResult]:
    def get_stats(self) -> Dict[str, Any]:
    def reset(self) -> None:
class FastGhostTickDetector:
    def __init__(self, window: int = 100, threshold: float = 3.5):
    def update(self, instrument_id: int, price: float) -> None:
    def detect_vector(self, instrument_ids: List[int], current_prices: np.ndarray) -> np.ndarray:
def create_ghost_tick_detector(
``

## File: .\app\data\market_feeds.py
``python
import asyncio
import logging
from typing import Dict, List, Optional, Callable, Any
from datetime import datetime
from threading import RLock
from app.models import Candle, OrderBookSnapshot
from app.data.rolling_window import RollingWindow
from app.data.validators import DataValidator
from app.data.websocket_client import KrakenWebSocketClient
from app.data.polling_client import PollingClient
from app.utils.time_utils import now_ns
class MarketFeeds:
    def __init__(self, config: Any):
    def _on_candle(self, candle: Candle) -> None:
    def _on_order_book(self, order_book: OrderBookSnapshot) -> None:
    def _on_trade(self, trade: Dict[str, Any]) -> None:
    def register_candle_callback(self, callback: Callable) -> None:
    def register_order_book_callback(self, callback: Callable) -> None:
    def register_trade_callback(self, callback: Callable) -> None:
    def get_candles(self, symbol: str, count: Optional[int] = None) -> List[Candle]:
    def get_last_candle(self, symbol: str) -> Optional[Candle]:
    def get_order_book(self, symbol: str) -> Optional[OrderBookSnapshot]:
    def get_depth_history(self, symbol: str, count: int = 50) -> List[float]:
    def get_spread_history(self, symbol: str, count: int = 50) -> List[float]:
    def is_stale(self, symbol: str, current_time_ns: Optional[int] = None) -> bool:
    def get_stale_status(self, current_time_ns: Optional[int] = None) -> Dict[str, bool]:
    def get_latest_price(self, symbol: str) -> Optional[float]:
    def get_latest_volume(self, symbol: str) -> Optional[float]:
    def get_market_status(self) -> Dict[str, Any]:
    def get_symbol_stats(self, symbol: str) -> Dict[str, Any]:
``

## File: .\app\data\polling_client.py
``python
import asyncio
import logging
import time
from typing import Dict, List, Optional, Callable, Any
from datetime import datetime, timedelta
import aiohttp
from app.models import Candle, OrderBookSnapshot
from app.utils.time_utils import now_ns
class PollingClient:
    def __init__(
    def is_running(self) -> bool:
    def _format_symbol(self, symbol: str) -> str:
    def _parse_candles(self, data: Dict, symbol: str) -> List[Candle]:
    def _parse_order_book(self, data: Dict, symbol: str) -> Optional[OrderBookSnapshot]:
    def get_stats(self) -> Dict[str, Any]:
``

## File: .\app\data\regime_detector.py
``python
import logging
from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass
from collections import deque
from app.models.contracts import FeatureVector
from app.models.enums import RegimeType
from app.utils.time_utils import is_monotonic
class RegimeDetectorError(Exception):
def _safe_str(value: Any) -> str:
class RegimeState:
    def to_dict(self) -> Dict[str, Any]:
class RegimeHistoryEntry:
class RegimeDetector:
    def __init__(
    def update(
    def _detect_regime(
    def _calculate_stability(self) -> float:
    def get_current_regime(self) -> RegimeType:
    def get_current_confidence(self) -> float:
    def get_candidate_regime(self) -> Optional[RegimeType]:
    def get_candidate_confidence(self) -> float:
    def get_regime_history(self, count: int = 100) -> List[Dict[str, Any]]:
    def get_regime_stability(self) -> float:
    def get_stats(self) -> Dict[str, Any]:
    def reset(self) -> None:
def create_regime_detector(
``

## File: .\app\data\rolling_window.py
``python
import logging
from collections import deque
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime
from threading import RLock
from app.models import Candle
class RollingWindow:
    def __init__(self, max_candles: int = 1000):
    def _get_or_create_window(self, symbol: str) -> deque:
    def add_candle(self, candle: Candle) -> None:
    def add_candles(self, candles: List[Candle]) -> None:
    def get_candles(self, symbol: str, count: Optional[int] = None) -> List[Candle]:
    def get_candles_by_ns(self, symbol: str, before_ns: Optional[int] = None, count: int = 100) -> List[Candle]:
    def get_last_candle(self, symbol: str) -> Optional[Candle]:
    def get_last_candle_by_ns(self, symbol: str) -> Optional[Candle]:
    def get_candle_at_index(self, symbol: str, index: int) -> Optional[Candle]:
    def get_candle_by_time(self, symbol: str, timestamp: datetime) -> Optional[Candle]:
    def get_candle_by_ns(self, symbol: str, exchange_ts_ns: int) -> Optional[Candle]:
    def get_candles_since(self, symbol: str, since: datetime) -> List[Candle]:
    def get_candles_since_ns(self, symbol: str, since_ns: int) -> List[Candle]:
    def get_candles_range(self, symbol: str, start: datetime, end: datetime) -> List[Candle]:
    def get_candles_range_ns(self, symbol: str, start_ns: int, end_ns: int) -> List[Candle]:
    def get_count(self, symbol: str) -> int:
    def clear_symbol(self, symbol: str) -> None:
    def clear_all(self) -> None:
    def get_symbols(self) -> List[str]:
    def is_full(self, symbol: str) -> bool:
    def get_oldest_timestamp(self, symbol: str) -> Optional[datetime]:
    def get_oldest_timestamp_ns(self, symbol: str) -> Optional[int]:
    def get_newest_timestamp(self, symbol: str) -> Optional[datetime]:
    def get_newest_timestamp_ns(self, symbol: str) -> Optional[int]:
    def get_time_range(self, symbol: str) -> Tuple[Optional[datetime], Optional[datetime]]:
    def get_time_range_ns(self, symbol: str) -> Tuple[Optional[int], Optional[int]]:
    def to_dict(self, symbol: str) -> List[Dict[str, Any]]:
``

## File: .\app\data\validators.py
``python
import logging
from datetime import datetime
from typing import List, Optional, Tuple, Dict, Any
from dataclasses import dataclass, field
from app.models import Candle, OrderBookSnapshot
from app.constants import STALE_DATA_THRESHOLD_SECONDS
from app.utils.time_utils import now_ns
class ValidationResult:
class DataValidator:
    def __init__(self, stale_threshold_seconds: int = STALE_DATA_THRESHOLD_SECONDS):
    def _is_stale_ns(self, timestamp_ns: int, current_time_ns: int) -> bool:
    def validate_candle(
    def validate_candles(
    def validate_order_book(
    def is_stale(self, timestamp: datetime, current_time: Optional[datetime] = None) -> bool:
    def get_stale_status(self, symbol: str, current_time_ns: Optional[int] = None) -> Tuple[bool, float]:
    def reset_symbol(self, symbol: str) -> None:
    def reset_all(self) -> None:
    def validate_price(self, price: float, symbol: str) -> ValidationResult:
    def validate_quantity(self, quantity: float, symbol: str) -> ValidationResult:
    def validate_ohlcv_consistency(self, candle: Candle) -> ValidationResult:
``

## File: .\app\data\websocket_client.py
``python
import asyncio
import json
import logging
import time
from datetime import datetime
from typing import Dict, List, Optional, Callable, Any, Tuple
from collections import deque
import websockets
from websockets.exceptions import ConnectionClosed, WebSocketException
from app.models import Candle, OrderBookSnapshot
from app.utils.time_utils import now_ns
class KrakenWebSocketClient:
    def __init__(
    def _parse_rfc3339_to_ns(self, timestamp_value: Any, channel_type: str) -> Optional[int]:
    def _get_nested_payload_objects(self, data: Dict) -> List[Dict]:
    def _extract_nested_symbol(self, payload_obj: Dict) -> str:
    def _extract_nested_exchange_timestamp_ns(self, payload_obj: Dict, channel_type: str, candidate_keys: List[str]) -> Optional[int]:
    def _calculate_lag_ms(self) -> float:
    def get_stats(self) -> Dict[str, Any]:
def create_kraken_websocket(
``

## File: .\app\data\__init__.py
``python
def main():
``

## File: .\app\execution\engine.py
``python
import concurrent.futures
import logging
import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from app.brain.data_validator import DataContinuityValidator
from app.commander import Commander
from app.execution.masking_layer import MaskingLayer
from app.execution.order_router import OrderRouter
from app.models import OrderFill, OrderRequest, StrategySignal
from app.risk.guard import HybridRiskGuard
from app.utils.time_utils import now_ns
class ExecutionState:
class QueuedSignal:
class ExecutionEngine:
    def __init__(
    def start(self) -> None:
    def stop(self) -> None:
    def process_events(self) -> None:
    def update_equity(self, current_equity: float) -> None:
    def update_regime(self, regime: str) -> None:
    def submit_signal(self, signal: StrategySignal, current_price: float, is_attack: bool) -> bool:
    def get_status(self) -> Dict[str, Any]:
    def _calculate_signal_net_profit(self, signal: StrategySignal) -> float:
    def _validate_signal_before_execution(self, queued: QueuedSignal, current_price: float) -> Tuple[bool, str]:
    def _execute_signal(self, queued: QueuedSignal) -> None:
    def _cancel_pending_order_with_pcv(self, order_id: str) -> bool:
    def _emergency_liquidate_all(self) -> None:
    def _emergency_cancel_order(self, order_id: str) -> None:
    def _normal_cancel_all_orders(self) -> None:
    def _on_recalibration(self) -> None:
    def _on_emergency(self) -> None:
    def _on_zombie_detected(self) -> None:
    def _on_lag_detected(self) -> None:
    def _on_vol_fuse(self) -> None:
    def _zombie_sweeper_loop(self) -> None:
    def _extract_order_timestamp_ns(self, order: OrderRequest) -> int:
    def _sweep_zombie_orders(self) -> None:
    def _monitor_loop(self) -> None:
    def _executor_loop(self) -> None:
``

## File: .\app\execution\fee_model.py
``python
from __future__ import annotations
import logging
from dataclasses import asdict, dataclass, field
from decimal import Decimal, InvalidOperation, ROUND_DOWN, getcontext
from enum import Enum, unique
from typing import Any, Dict, List, Optional
from app.utils.enums import FillLiquidity, OrderType
from app.utils.ids import generate_correlation_id, generate_request_id
def _d(value: Any, *, field_name: str) -> Decimal:
def _ensure_non_negative(value: Decimal, field_name: str) -> Decimal:
def _ensure_positive(value: Decimal, field_name: str) -> Decimal:
def _quantize_money(value: Decimal) -> Decimal:
def _quantize_bps(value: Decimal) -> Decimal:
class FeeQuality(str, Enum):
class FeePolicyConfig:
    def __post_init__(self) -> None:
class FeeEstimate:
    def to_dict(self) -> Dict[str, Any]:
class FeeRealization:
    def to_dict(self) -> Dict[str, Any]:
class FeeScheduleSnapshot:
class FeeAggregateSnapshot:
class FeeJournalRecord:
class FeeModel:
    def __init__(
    def calculate_expected_fee(
    def decompose_fill_fee(
    def update_volume_tier(self, rolling_30d_volume: Decimal):
    def estimate_fees(
    def decompose_fill_fee_detailed(
    def update_volume_tier_detailed(self, *, rolling_30d_volume: Decimal) -> Decimal:
    def set_symbol_surcharge(self, symbol: str, surcharge_bps: Decimal) -> None:
    def clear_symbol_surcharge(self, symbol: str) -> None:
    def get_schedule_snapshot(self) -> FeeScheduleSnapshot:
    def get_aggregate_snapshot(self) -> FeeAggregateSnapshot:
    def journal(self, limit: Optional[int] = None) -> List[FeeJournalRecord]:
    def _infer_liquidity_role_from_order_type(self, order_type: OrderType) -> FillLiquidity:
    def _append_journal(self, *, event: str, payload: Dict[str, Any]) -> None:
``

## File: .\app\execution\latency_model.py
``python
from __future__ import annotations
import logging
import random
from dataclasses import asdict, dataclass, field
from decimal import Decimal, InvalidOperation, getcontext
from enum import Enum, unique
from typing import Any, Dict, List, Optional
def _d(value: Any, *, field_name: str) -> Decimal:
def _ensure_non_negative(value: Decimal, field_name: str) -> Decimal:
class LatencyQuality(str, Enum):
class LatencyMode(str, Enum):
class CongestionState(str, Enum):
class LatencyEventType(str, Enum):
class LatencyPolicyConfig:
    def __post_init__(self) -> None:
class LatencySample:
    def to_dict(self) -> Dict[str, Any]:
class LatencyStatsSnapshot:
class LatencyJournalRecord:
class LatencyModel:
    def __init__(
    def get_current_latency_ns(self) -> int:
    def model_packet_loss(self, loss_rate: float = 0.0001) -> bool:
    def get_stats(self) -> Dict[str, float]:
    def sample_latency(self) -> LatencySample:
    def telemetry_snapshot(self) -> LatencyStatsSnapshot:
    def journal(self, limit: Optional[int] = None) -> List[LatencyJournalRecord]:
    def _maybe_transition_congestion(self) -> None:
    def _state_multiplier(self, state: CongestionState) -> Decimal:
    def _loss_multiplier(self, state: CongestionState) -> Decimal:
    def _timeout_multiplier(self, state: CongestionState) -> Decimal:
    def _append_journal(
``

## File: .\app\execution\live_broker.py
``python
def main():
``

## File: .\app\execution\masking_layer.py
``python
import numpy as np
import logging
import random
from typing import Dict, Optional, Tuple, Any
from dataclasses import dataclass
from collections import deque
from app.brain.ring_buffer import RingBuffer
from app.brain.rolling_stats import RollingStats
class MaskedOrder:
class MaskingLayer:
    def __init__(
    def update_volatility(self, volatility: float) -> None:
    def _calculate_adaptive_jitter_ms(self, base_jitter_ms: float) -> float:
    def _generate_delay_jitter(self) -> float:
    def _generate_size_jitter(self, size: float) -> float:
    def _detect_pattern_risk(self) -> float:
    def mask_order(self, size: float, current_volatility: Optional[float] = None) -> MaskedOrder:
    def simulate_false_signal(self, exchange: str, symbol: str) -> Dict[str, Any]:
    def get_stats(self) -> Dict[str, Any]:
``

## File: .\app\execution\orchestrator.py
``python
import logging
import time
import threading
import queue
from decimal import Decimal, getcontext
from typing import Dict, Optional, Any, List, Tuple
from dataclasses import dataclass
from collections import deque
from datetime import datetime
from app.models import (
from app.models.enums import RegimeType, SleeveType
from app.models.contracts import StaleDataBlock, DivergenceBlock
from app.models.entropy_score import EntropyScore
from app.brain.signal_fusion import SignalFusion
from app.brain.toxicity_engine import ToxicityEngine, ToxicityAlert
from app.brain.topological_engine import TopologicalEngine
from app.brain.insider_signal_engine import (
from app.brain.entropy_decoder import EntropyDecoder
from app.brain.whale_zone_engine import WhaleZoneEngine, WhalePresenceZone
from app.strategies.liquidity_void import LiquidityVoidStrategy
from app.strategies.shadow_front import ShadowFrontStrategy
from app.risk.safety import SafetyGate
from app.risk.kill_switch import KillSwitch, KillSwitchState
from app.risk.unified_risk import UnifiedRiskAuthority, UnifiedRiskResult, UnifiedRiskDecision
from app.risk.position_sizing import PositionSizingEngine, PositionSizeResult
from app.execution.masking_layer import MaskingLayer, MaskedOrder
from app.instrument_registry import InstrumentRegistry
class EventPacket:
class PaperBroker:
    def __init__(self, config: Any):
    def calculate_slippage(
    def calculate_fees(self, size: float, price: float, side: str, order_type: str) -> float:
    def execute(self, order: OrderRequest, market_data: Dict[str, Any]) -> Tuple[float, float, float, float]:
    def get_stats(self) -> Dict[str, Any]:
class HeartbeatMonitor:
    def __init__(self, max_latency_ms: int = 10, alert_callback: Optional[callable] = None):
    def start(self) -> None:
    def stop(self) -> None:
    def heartbeat(self, timestamp_ns: int) -> None:
    def _monitor_loop(self) -> None:
    def get_stats(self) -> Dict[str, Any]:
class CachedRiskState:
    def __init__(self):
    def update(self, result: UnifiedRiskResult, timestamp_ns: int, symbol: str) -> None:
    def get_for_display(self, symbol: str) -> Optional[UnifiedRiskResult]:
class MasterOrchestrator:
    def __init__(self, config: Any, symbol: str, kill_switch: KillSwitch):
    def start(self) -> None:
    def stop(self) -> None:
    def update_risk_state(
    def process_order_book(self, order_book: OrderBookSnapshot) -> None:
    def process_candle(self, candle: Candle) -> None:
    def process_trade(self, size: float, price: float, side: int, timestamp_ns: int) -> None:
    def _enqueue_packet(self, packet: EventPacket) -> None:
    def process_events(self) -> None:
    def _process_packet(self, packet: EventPacket) -> None:
    def _process_order_book_packet(self, packet: EventPacket) -> None:
    def _process_candle_packet(self, packet: EventPacket) -> None:
    def _process_trade_packet(self, packet: EventPacket) -> None:
    def _calculate_liquidity_usd(self) -> float:
    def _calculate_volatility(self) -> Decimal:
    def _calculate_exposure_pct(self) -> Decimal:
    def _get_current_capital(self) -> float:
    def _get_kelly_multiplier(self) -> Decimal:
    def _get_toxicity_score(self) -> Decimal:
    def _get_min_order_size(self, symbol: str) -> float:
    def _generate_order_with_risk_gating(self, fusion: Any, price: float, timestamp_ns: int) -> None:
    def close_position(self, symbol: str, price: float, timestamp_ns: int) -> None:
    def update_portfolio(self, portfolio: PortfolioSnapshot) -> None:
    def get_status(self) -> Dict[str, Any]:
    def reset(self) -> None:
``

## File: .\app\execution\order_router.py
``python
import base64
import hashlib
import hmac
import logging
import threading
import time
import urllib.parse
from dataclasses import dataclass
from decimal import Decimal as _Decimal
from typing import Any, Dict, List, Optional, Tuple
import requests
from app.execution.fee_model import FeeModel as _FeeModel
from app.execution.latency_model import LatencyModel as _LatencyModel
from app.execution.paper_broker import PaperBroker as _SovereignPaperBroker
from app.execution.slippage_model import SlippageModel as _SlippageModel
from app.models import OrderFill, OrderRequest
from app.models.enums import InternalOrderStatus, SleeveType
from app.utils.time_utils import now_ns
import app.utils.enums as _pb_enums
class OrderStatus:
class OrderRouter:
    def __init__(
    def measure_latency(self) -> float:
    def _measure_exchange_latency(self, exchange: str) -> float:
    def _measure_baseline_latency(self) -> float:
    def is_websocket_connected(self) -> bool:
    def update_websocket_ping(self) -> None:
    def update_websocket_pong(self) -> None:
    def get_websocket_rtt_ms(self) -> float:
    def _kraken_sign(self, urlpath: str, data: Dict[str, str]) -> Dict[str, str]:
    def _paper_side(self, order: OrderRequest):
    def _paper_order_type(self, order: OrderRequest):
    def _sync_paper_reports(self) -> None:
    def _paper_mark_price(self, symbol: str) -> _Decimal:
    def _drive_paper_matching(self, order: OrderRequest, ts_ns: int) -> None:
    def submit_order(self, order: OrderRequest) -> Optional[OrderFill]:
    def _submit_order_paper(self, order: OrderRequest) -> Optional[OrderFill]:
    def _submit_order_kraken(self, order: OrderRequest) -> Optional[OrderFill]:
    def _submit_order_alpaca(self, order: OrderRequest) -> Optional[OrderFill]:
    def _submit_order_rest(self, order: OrderRequest) -> Optional[OrderFill]:
    def _get_order_fill(self, order_id: str, order: OrderRequest) -> Optional[OrderFill]:
    def _get_kraken_order_fill(self, order_id: str, order: OrderRequest) -> Optional[OrderFill]:
    def _get_alpaca_order_fill(self, order_id: str, order: OrderRequest) -> Optional[OrderFill]:
    def _get_simulated_price(self, symbol: str) -> float:
    def cancel_order(self, order_id: str) -> bool:
    def _cancel_order_paper(self, order_id: str) -> bool:
    def _cancel_order_kraken(self, order_id: str) -> bool:
    def _cancel_order_alpaca(self, order_id: str) -> bool:
    def _cancel_order_rest(self, order_id: str) -> bool:
    def get_order_status(self, order_id: str) -> str:
    def _query_order_status(self, order_id: str) -> str:
    def _query_kraken_order_status(self, order_id: str) -> str:
    def _query_alpaca_order_status(self, order_id: str) -> str:
    def verify_cancellation(self, order_id: str) -> bool:
    def close_all_positions(self) -> bool:
    def _get_open_positions(self) -> List[Dict[str, Any]]:
    def _get_kraken_open_positions(self) -> List[Dict[str, Any]]:
    def _get_alpaca_open_positions(self) -> List[Dict[str, Any]]:
    def get_mid_price(self, symbol: str) -> float:
    def get_actual_positions(self) -> List[Dict[str, Any]]:
    def get_ghost_status(self) -> Dict[str, Any]:
``

## File: .\app\execution\paper_broker.py
``python
from __future__ import annotations
import heapq
import logging
from dataclasses import asdict, dataclass, field, replace
from decimal import Decimal, InvalidOperation, getcontext
from enum import Enum, unique
from typing import Any, Dict, List, Optional, Tuple
from app.utils.enums import (
from app.utils.ids import generate_correlation_id, generate_id
from app.execution.fee_model import FeeModel
from app.execution.slippage_model import (
from app.execution.latency_model import LatencyModel
def _d(value: Any, *, field_name: str) -> Decimal:
def _ensure_positive(value: Decimal, field_name: str) -> Decimal:
def _ensure_non_negative(value: Decimal, field_name: str) -> Decimal:
class PaperBrokerQuality(str, Enum):
class BrokerEventType(str, Enum):
class RejectReason(str, Enum):
class PaperBrokerConfig:
    def __post_init__(self) -> None:
class BrokerPosition:
    def __post_init__(self) -> None:
class PaperOrder:
    def __post_init__(self) -> None:
class ExecutionReport:
class PriceLevel:
    def __post_init__(self) -> None:
class PaperMarketContext:
    def __post_init__(self) -> None:
class BrokerSnapshot:
class BrokerJournalRecord:
class PaperBroker:
    def __init__(
    def submit_order(
    def process_matching(
    def submit_order_detailed(
    def replace_order(
    def cancel_order(self, client_id: str, ts_ns: int) -> Optional[ExecutionReport]:
    def process_matching_detailed(
    def _attempt_match(
    def _determine_fill_from_market(
    def _passive_queue_fill(
    def _book_walk_fill(
    def _execute_fill(
    def _expire_or_cancel(
    def _reject_and_remove(
    def _reject_report(
    def _apply_fill_to_position(self, position: BrokerPosition, signed_fill: Decimal, fill_price: Decimal) -> BrokerPosition:
    def _validate_submit_inputs(
    def _validate_reservation(
    def _reserve_for_order(self, order: PaperOrder) -> None:
    def _release_reservation(self, order: PaperOrder) -> None:
    def _expire_orders_if_needed(self, current_ts_ns: int) -> List[ExecutionReport]:
    def get_equity(self, current_prices: Dict[str, Decimal]) -> Decimal:
    def get_snapshot(self, current_prices: Dict[str, Decimal], ts_ns: int) -> BrokerSnapshot:
    def restore_from_snapshot(self, snapshot: BrokerSnapshot) -> None:
    def replay_from_journal(self, journal: List[BrokerJournalRecord]) -> None:
    def validate_invariants(self) -> Dict[str, Any]:
    def journal(self, limit: Optional[int] = None) -> List[BrokerJournalRecord]:
    def _append_journal(
``

## File: .\app\execution\shared_memory.py
``python
import numpy as np
from multiprocessing import shared_memory, Manager
import mmap
import time
import os
import sys
import atexit
import signal
from typing import Dict, Any, Optional, Tuple
from dataclasses import dataclass
import threading
import logging
class SharedMemoryBlock:
class SharedMemoryManager:
    def __init__(self, max_instruments: int = 256, cleanup_stale: bool = True):
    def _cleanup_stale_blocks(self) -> None:
    def _register_signal_handlers(self) -> None:
        def signal_handler(signum, frame):
    def _create_blocks(self) -> None:
    def _create_block(self, name: str, shape: Tuple[int, ...], dtype: np.dtype) -> None:
    def _update_heartbeat(self) -> None:
    def get_reader(self, name: str) -> Optional[np.ndarray]:
    def get_writer(self, name: str, timestamp_ns: int) -> Tuple[Optional[np.ndarray], int]:
    def write_correlation_matrix(self, matrix: np.ndarray, timestamp_ns: int) -> int:
    def write_price_history(
    def write_feature_vector(self, features: np.ndarray, timestamp_ns: int) -> int:
    def get_feature_vector(self) -> Tuple[Optional[np.ndarray], int, int]:
    def get_correlation_row(self, instrument_id: int) -> Optional[np.ndarray]:
    def get_latest_price(self, instrument_id: int, index: int) -> Optional[float]:
    def get_price_window(
    def get_version(self, name: str) -> int:
    def has_updated(self, name: str, last_version: int) -> bool:
    def is_alive(self) -> bool:
    def cleanup(self) -> None:
    def get_stats(self) -> Dict[str, Any]:
def now_ns() -> int:
def seconds_to_ns(seconds: float) -> int:
def ns_to_seconds(ns: int) -> float:
def create_shared_memory_manager(max_instruments: int = 256, cleanup_stale: bool = True) -> SharedMemoryManager:
class SharedMemoryContext:
    def __init__(self, max_instruments: int = 256, cleanup_stale: bool = True):
    def __enter__(self) -> SharedMemoryManager:
    def __exit__(self, exc_type, exc_val, exc_tb):
def cleanup_all_poverty_killer_blocks() -> int:
``

## File: .\app\execution\slippage_model.py
``python
from __future__ import annotations
import logging
from dataclasses import asdict, dataclass, field, replace
from decimal import Decimal, InvalidOperation, ROUND_DOWN, getcontext
from enum import Enum, unique
from typing import Any, Dict, List, Optional, Tuple
from app.utils.enums import (
from app.utils.ids import generate_correlation_id, generate_request_id
def _d(value: Any, *, field_name: str) -> Decimal:
def _ensure_non_negative(value: Decimal, field_name: str) -> Decimal:
def _ensure_positive(value: Decimal, field_name: str) -> Decimal:
def _quantize_price(value: Decimal) -> Decimal:
def _quantize_bps(value: Decimal) -> Decimal:
class SlippageQuality(str, Enum):
class ExecutionStyle(str, Enum):
class SlippagePolicyConfig:
    def __post_init__(self) -> None:
class DepthProfile:
    def __post_init__(self) -> None:
class MarketImpactContext:
    def __post_init__(self) -> None:
class SlippageEstimate:
    def to_dict(self) -> Dict[str, Any]:
class CalibrationFeedback:
class SlippageJournalRecord:
class SlippageTelemetrySnapshot:
class SlippageModel:
    def __init__(
    def estimate_slippage(
    def get_max_executable_size(self, target_slippage_bps: Decimal, current_price: Decimal) -> Decimal:
    def estimate_slippage_detailed(
    def estimate_max_executable_size(
    def calibrate_from_realized_fill(
    def telemetry_snapshot(self) -> SlippageTelemetrySnapshot:
    def journal(self, limit: Optional[int] = None) -> List[SlippageJournalRecord]:
    def _depth_or_none(self, value: Optional[Decimal]) -> Optional[Decimal]:
    def _side_depth_l1(self, market: MarketImpactContext) -> Optional[Decimal]:
    def _side_depth_n(self, market: MarketImpactContext) -> Optional[Decimal]:
    def _regime_multiplier(self, regime: RegimeType) -> Decimal:
    def _toxicity_multiplier(self, toxicity_score: Decimal, toxicity_level: ToxicityLevel) -> Decimal:
    def _imbalance_multiplier(self, *, side: OrderSide, imbalance: Decimal) -> Decimal:
    def _liquidity_multiplier(self, regime: LiquidityRegime) -> Decimal:
    def _calibration_multiplier(self, symbol: str, venue: Optional[str]) -> Decimal:
    def _spread_cost_bps(self, market: MarketImpactContext) -> Decimal:
    def _impact_cost_bps(
    def _adverse_selection_bps(self, market: MarketImpactContext) -> Decimal:
    def _classify_slippage(self, total_slippage_bps: Decimal) -> SlippageClass:
    def _append_journal(self, estimate: SlippageEstimate) -> None:
``

## File: .\app\execution\throttler.py
``python
import asyncio
import logging
import time
import random
from enum import Enum, auto
from typing import Dict, Any, Optional, Callable, Awaitable, Tuple
from dataclasses import dataclass, field
from collections import deque
class RequestPriority(Enum):
class EndpointCategory(Enum):
class RateLimitConfig:
class CircuitBreakerState(Enum):
class EndpointStats:
class AdaptiveTokenBucket:
    def __init__(self, category: EndpointCategory, config: RateLimitConfig):
    def _refill(self) -> None:
    def record_response(self, success: bool, response_time_ms: float, rate_limited: bool = False) -> None:
    def _adjust_rate_down(self) -> None:
    def _adjust_rate_up(self) -> None:
    def _adjust_rate_predictive(self) -> None:
    def _update_circuit_breaker(self) -> None:
    def is_circuit_open(self) -> bool:
    def reset_circuit(self) -> None:
    def get_stats(self) -> Dict[str, Any]:
class SovereignThrottler:
    def __init__(self):
    def get_stats(self) -> Dict[str, Any]:
    def reset_circuit(self, category: Optional[EndpointCategory] = None) -> None:
def create_throttler() -> SovereignThrottler:
``

## File: .\app\execution\__init__.py
``python
``

## File: .\app\meta\market_allocator.py
``python
from __future__ import annotations
import logging
import time
from dataclasses import asdict, dataclass, field
from decimal import Decimal, InvalidOperation, ROUND_DOWN, getcontext
from enum import Enum, unique
from typing import Any, Dict, List, Optional
from app.utils.enums import RegimeType, SleeveType
from app.utils.ids import generate_correlation_id, generate_request_id
def _d(value: Any, *, field_name: str) -> Decimal:
def _ensure_non_negative(value: Decimal, field_name: str) -> Decimal:
def _ensure_positive(value: Decimal, field_name: str) -> Decimal:
def _quantize_money(value: Decimal) -> Decimal:
def _now_ns() -> int:
class AllocationQuality(str, Enum):
class TimestampSource(str, Enum):
class AllocationPolicyConfig:
    def __post_init__(self) -> None:
class AllocationContext:
    def __post_init__(self) -> None:
class AllocationDecision:
    def to_dict(self) -> Dict[str, Any]:
class AllocationReport:
class AllocationJournalRecord:
class MarketAllocator:
    def __init__(
    def calculate_trade_capacity(
    def get_allocation_report(self, total_equity: Decimal) -> Dict[str, Any]:
    def calculate_trade_capacity_detailed(
    def build_allocation_report(
    def journal(self, limit: Optional[int] = None) -> List[AllocationJournalRecord]:
    def _append_journal(self, record: AllocationJournalRecord) -> None:
``

## File: .\app\meta\strategy_allocator.py
``python
import logging
import threading
import numpy as np
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from collections import deque
from enum import Enum
from app.constants import SleeveType, AssetClass, ControlMode
class AllocationMode(Enum):
class StrategyAllocation:
class AssetExposure:
class SovereignGovernor:
    def __init__(
    def _init_strategy_allocations(self) -> None:
    def get_heat_multiplier(self) -> float:
    def get_heat_metrics(self) -> Dict[str, Any]:
    def get_correlation_slash_factor(self, symbol: str, existing_exposures: List[str]) -> float:
    def calculate_adjusted_allocation(
    def allocate(
    def deallocate(self, strategy: SleeveType, capital: float, symbol: str) -> None:
    def set_mode(self, mode: AllocationMode, reason: str = "") -> None:
    def get_mode(self) -> AllocationMode:
    def get_exposure_multiplier(self) -> float:
    def update_strategy_performance(
    def _decay_performance(self, strategy: SleeveType) -> None:
    def update_correlation(
    def get_correlation(self, asset1: str, asset2: str) -> float:
    def update_asset_exposure(
    def get_asset_exposure(self, symbol: str) -> Optional[AssetExposure]:
    def get_total_exposure(self) -> float:
    def get_exposure_by_class(self, asset_class: AssetClass) -> float:
    def _get_class_limit(self, asset_class: AssetClass) -> float:
    def get_heat_map(self) -> Dict[str, Any]:
    def _get_health_color(self, usage_pct: float, win_rate: float, sharpe: float) -> str:
    def _get_asset_health_color(self, usage_pct: float, pnl: float) -> str:
    def _get_overall_health(self, total_usage_pct: float) -> str:
    def get_status(self) -> Dict[str, Any]:
    def get_strategy_allocation(self, strategy: SleeveType) -> Optional[Dict[str, Any]]:
    def reset(self) -> None:
``

## File: .\app\meta\__init__.py
``python
def main():
``

## File: .\app\models\contracts.py
``python
from decimal import Decimal
from typing import Any, Dict, List, Optional
from uuid import uuid4
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from app.models.enums import (
from app.utils.decimal_utils import (
from app.utils.time_utils import now_ns
def _base_model_config(*, use_enum_values: bool = False) -> ConfigDict:
def _require_non_blank(value: str, field_name: str) -> str:
def _quantize_ratio(value: Any, field_name: str, allow_zero: bool = True) -> Decimal:
class ExchangePosition(BaseModel):
    def validate_required_strings(cls, v, info):
    def validate_quantity(cls, v):
    def validate_price(cls, v):
class ExchangeOpenOrder(BaseModel):
    def validate_required_strings(cls, v, info):
    def validate_quantity(cls, v):
    def validate_limit_price(cls, v):
class ExchangeFill(BaseModel):
    def validate_required_strings(cls, v, info):
    def validate_price(cls, v):
    def validate_quantity(cls, v):
    def validate_fee(cls, v):
class SubmittedOrder(BaseModel):
    def validate_client_order_id(cls, v):
    def validate_venue_order_id(cls, v):
    def validate_timestamp(cls, v):
class PendingCancel(BaseModel):
    def validate_client_order_id(cls, v):
    def validate_timestamp(cls, v):
class Acknowledgement(BaseModel):
    def validate_required_strings(cls, v, info):
    def validate_timestamp(cls, v):
class Rejection(BaseModel):
    def validate_required_strings(cls, v, info):
    def validate_timestamp(cls, v):
class PortfolioPosition(BaseModel):
    def validate_symbol(cls, v):
    def validate_quantity(cls, v):
    def validate_price(cls, v):
    def validate_pnl(cls, v):
class KillSwitchRecord(BaseModel):
    def validate_switch(cls, v):
    def validate_timestamp(cls, v):
class DivergenceBlock(BaseModel):
    def validate_symbol(cls, v):
    def validate_timestamp(cls, v):
class StaleDataBlock(BaseModel):
    def validate_symbol(cls, v):
    def validate_timestamp(cls, v):
class ReplayPosition(BaseModel):
    def validate_source(cls, v):
    def validate_sequence(cls, v):
    def validate_timestamp(cls, v):
class FeaturePayload(BaseModel):
    def validate_score(cls, v):
    def validate_continuous(cls, v):
    def validate_betti(cls, v):
class EventEnvelope(BaseModel):
    def validate_event_id(cls, v):
    def validate_optional_strings(cls, v, info):
    def validate_timestamp_non_negative(cls, v):
    def validate_sequence(cls, v):
    def validate_version(cls, v):
    def validate_payload(cls, v):
    def validate_causality_and_ordering(self):
class DecisionRecord(BaseModel):
    def validate_decision_uuid(cls, v):
    def validate_timestamp(cls, v):
    def validate_version(cls, v):
    def validate_mapping_not_none(cls, v):
class ExchangeTruth(BaseModel):
    def validate_venue(cls, v):
    def validate_timestamp(cls, v):
    def validate_balances(cls, v):
class ExecutionTruth(BaseModel):
    def validate_timestamp(cls, v):
class PortfolioTruth(BaseModel):
    def validate_timestamp(cls, v):
    def validate_cash(cls, v):
    def validate_equity(cls, v, info):
class StrategyTruthEntry(BaseModel):
    def validate_required_strings(cls, v, info):
    def validate_optional_uuid(cls, v):
    def validate_entry_price(cls, v):
    def validate_exposure(cls, v):
    def validate_ttl(cls, v):
class StrategyTruth(BaseModel):
    def validate_timestamp(cls, v):
class RiskTruth(BaseModel):
    def validate_leverage(cls, v):
    def validate_hard_flat_reason(cls, v):
    def validate_marketability_limits(cls, v):
    def validate_hard_flat_fields(self):
class TruthFrame(BaseModel):
    def validate_truth_frame_id(cls, v):
    def validate_timestamp(cls, v):
    def validate_divergence(cls, v):
    def validate_version(cls, v):
    def validate_divergence_reasons(cls, v):
    def validate_truth_consistency(self):
class OrderIntent(BaseModel):
    def validate_required_strings(cls, v, info):
    def validate_risk_approval_uuid(cls, v):
    def validate_quantity(cls, v):
    def validate_limit_price(cls, v):
    def validate_confidence(cls, v):
    def validate_cost(cls, v):
    def validate_ttl(cls, v):
    def validate_order_shape(self):
class ExecutionEvent(BaseModel):
    def validate_required_strings(cls, v, info):
    def validate_optional_strings(cls, v, info):
    def validate_timestamp(cls, v):
    def validate_retry(cls, v):
    def validate_execution_semantics(self):
class FillEvent(BaseModel):
    def validate_required_strings(cls, v, info):
    def validate_quantity(cls, v):
    def validate_price(cls, v):
    def validate_fee(cls, v):
    def validate_timestamp_positive(cls, v):
    def validate_receive_after_exchange(self):
class CancelEvent(BaseModel):
    def validate_required_strings(cls, v, info):
    def validate_timestamp(cls, v):
    def validate_ordering(self):
class PortfolioSnapshot(BaseModel):
    def validate_snapshot_id(cls, v):
    def validate_timestamp(cls, v):
    def validate_cash(cls, v):
    def validate_equity(cls, v, info):
    def validate_leverage(cls, v):
class RiskDecision(BaseModel):
    def validate_required_strings(cls, v, info):
    def validate_timestamp(cls, v):
    def validate_positive(cls, v, info):
    def validate_violations(cls, v):
    def validate_strategy_sets(self):
class StrategyVote(BaseModel):
    def validate_required_strings(cls, v, info):
    def validate_positive(cls, v):
    def validate_confidence(cls, v):
    def validate_move(cls, v):
    def validate_invalidation_conditions(cls, v):
    def validate_metadata(cls, v):
class FeatureVector(BaseModel):
    def validate_required_strings(cls, v, info):
    def validate_timestamp(cls, v):
class RecoveryCheckpoint(BaseModel):
    def validate_required_strings(cls, v, info):
    def validate_optional_strings(cls, v, info):
    def validate_timestamp(cls, v):
    def validate_wal_seq(cls, v):
    def validate_checkpoint_semantics(self):
class DivergenceEvent(BaseModel):
    def validate_required_strings(cls, v, info):
    def validate_optional_resolution_action(cls, v):
    def validate_timestamp(cls, v):
    def validate_duration(cls, v):
    def validate_magnitude(cls, v):
    def validate_maps(cls, v):
``

## File: .\app\models\entropy_score.py
``python
from decimal import Decimal
from pydantic import BaseModel, Field, ConfigDict, field_validator
class EntropyScore(BaseModel):
    def validate_symbol(cls, v: str) -> str:
    def validate_timestamp(cls, v: int) -> int:
    def validate_samples_used(cls, v: int) -> int:
    def validate_decimal_bounds(cls, v: Decimal) -> Decimal:
    def validate_predicted_magnitude(cls, v: Decimal) -> Decimal:
``

## File: .\app\models\enums.py
``python
from __future__ import annotations
from enum import Enum, IntEnum, unique
from typing import Final, FrozenSet
class RegimeType(str, Enum):
class LiquidityRegime(str, Enum):
class ToxicityLevel(str, Enum):
class BookIntegrity(str, Enum):
class Marketability(str, Enum):
class SlippageClass(str, Enum):
class SignalDirection(str, Enum):
class TradeIntent(str, Enum):
class PositionSide(str, Enum):
class ExposureState(str, Enum):
class OrderSide(str, Enum):
class OrderType(str, Enum):
class TimeInForce(str, Enum):
class ExecutionConstraint(str, Enum):
class SelfTradePreventionMode(str, Enum):
class VenueCapability(str, Enum):
class OrderStatus(str, Enum):
class InternalOrderStatus(str, Enum):
class ExecutionReportType(str, Enum):
class FillLiquidity(str, Enum):
class FillStatus(str, Enum):
class CancelStatus(str, Enum):
class RecoveryState(str, Enum):
class PersistenceState(str, Enum):
class RiskLevel(IntEnum):
class RiskAction(str, Enum):
class InvariantViolationSeverity(str, Enum):
class HazardVelocity(str, Enum):
class RiskVetoReason(str, Enum):
class RejectReason(str, Enum):
class CancelReason(str, Enum):
class InfraFaultType(str, Enum):
class SleeveType(str, Enum):
class ExecutionMode(str, Enum):
class LatencyTier(str, Enum):
class DegradationMode(str, Enum):
class AuthorityTier(str, Enum):
class ControlMode(str, Enum):
class RiskProfile(str, Enum):
class AssetClass(str, Enum):
class MarketSession(str, Enum):
class ExchangeType(str, Enum):
class PositionStatus(str, Enum):
class EventType(str, Enum):
class EventSource(str, Enum):
class PriorityClass(str, Enum):
class ReplayMode(str, Enum):
class TruthStatus(str, Enum):
class RiskMode(str, Enum):
class AlertSeverity(str, Enum):
class DivergenceType(str, Enum):
class ShadowFrontState(str, Enum):
class LiquidityVoidState(str, Enum):
class SourceType(str, Enum):
class CheckpointType(str, Enum):
class DecisionType(str, Enum):
class ExecutionEventType(str, Enum):
class SignalType(str, Enum):
class StrategyID(str, Enum):
class ResolutionType(str, Enum):
class CollapseQuality(str, Enum):
def is_crisis_regime(regime: RegimeType) -> bool:
``

## File: .\app\models\events.py
``python
from decimal import Decimal
from typing import Optional, Dict, List, Any
from uuid import uuid4
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from app.models.enums import (
from app.utils.decimal_utils import (
from app.utils.time_utils import now_ns
class BaseEvent(BaseModel):
    def validate_timestamp_non_negative(cls, v):
    def validate_version(cls, v):
    def validate_receive_after_exchange(self):
class TradeEvent(BaseEvent):
    def validate_price(cls, v):
    def validate_quantity(cls, v):
class QuoteEvent(BaseEvent):
    def validate_price(cls, v):
    def validate_size(cls, v):
class OrderBookLevel(BaseModel):
    def validate_price(cls, v):
    def validate_size(cls, v):
class OrderBookSnapshotEvent(BaseEvent):
    def validate_sequence(cls, v):
class OrderBookDeltaEvent(BaseEvent):
    def validate_sequence(cls, v):
    def validate_removal_prices(cls, v):
class ClockTickEvent(BaseEvent):
    def validate_tick(cls, v):
    def validate_elapsed(cls, v):
class AuditEvent(BaseEvent):
    def validate_decision_uuid(cls, v):
class HeartbeatEvent(BaseEvent):
    def validate_latency(cls, v):
    def validate_queue_sizes(cls, v):
class ReplayStartEvent(BaseEvent):
    def validate_timestamp(cls, v):
    def validate_seed(cls, v):
    def validate_timestamp_ordering(self):
class ReplayEndEvent(BaseEvent):
    def validate_positive(cls, v):
``

## File: .\app\models\fusion.py
``python
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field
class FusionDecision(BaseModel):
      def exchange_ts_sec(self) -> float:
      def has_valid_sleeve(self) -> bool:
``

## File: .\app\models\invariants.py
``python
from decimal import Decimal
from typing import Optional, List, Dict, Any
from uuid import uuid4
from pydantic import BaseModel, Field, validator, root_validator
from app.models.enums import (
from app.utils.time_utils import now_ns
class NormalInvariant(BaseModel):
    def validate_id_format(cls, v):
    def validate_version(cls, v):
class KillSwitchInvariant(BaseModel):
    def validate_id_format(cls, v):
    def validate_threshold_ns(cls, v):
    def validate_threshold_value(cls, v):
    def validate_threshold_count(cls, v):
    def validate_auto_recover(cls, v):
    def validate_version(cls, v):
    def validate_auto_recover_consistency(cls, values):
class RecoveryInvariant(BaseModel):
    def validate_id_format(cls, v):
    def validate_version(cls, v):
class ReplayPurityInvariant(BaseModel):
    def validate_id_format(cls, v):
    def validate_version(cls, v):
class InvariantViolationEvent(BaseModel):
    def validate_timestamp(cls, v):
    def validate_duration(cls, v):
    def validate_resolved_after_timestamp(cls, values):
class InvariantCheckResult(BaseModel):
    def validate_timestamp(cls, v):
    def validate_violation_consistency(cls, values):
class InvariantBatchCheckResult(BaseModel):
    def validate_timestamp(cls, v):
    def compute_from_results(cls, values):
``

## File: .\app\models\market_data.py
``python
from typing import List, Optional, Tuple
import numpy as np
from pydantic import BaseModel, ConfigDict, Field, validator
class Candle(BaseModel):
    def exchange_ts_sec(self) -> float:
    def typical_price(self) -> float:
    def range(self) -> float:
    def validate_prices(cls, v: float) -> float:
    def validate_high_low(cls, v: float, values) -> float:
class OrderBookSnapshot(BaseModel):
    def exchange_ts_sec(self) -> float:
    def best_bid(self) -> Optional[float]:
    def best_ask(self) -> Optional[float]:
    def spread(self) -> float:
    def spread_bps(self) -> float:
    def mid_price(self) -> float:
    def depth_at_levels(self, levels: int = 10) -> Tuple[float, float]:
    def imbalance(self) -> float:
class LiquidityMetrics(BaseModel):
    def exchange_ts_sec(self) -> float:
class PhysicalVerification(BaseModel):
    def exchange_ts_sec(self) -> float:
class WhaleFlowScore(BaseModel):
    def exchange_ts_sec(self) -> float:
    def is_expired(self, current_ts_ns: int) -> bool:
class EntropyScore(BaseModel):
    def exchange_ts_sec(self) -> float:
``

## File: .\app\models\orders.py
``python
from decimal import Decimal
from typing import Dict, Any, Optional
from uuid import uuid4
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from app.models.enums import OrderSide, OrderType, InternalOrderStatus, SleeveType
from app.utils.decimal_utils import crypto, price, fee, usd
def _require_non_blank(value: str, field_name: str) -> str:
def _base_model_config() -> ConfigDict:
class OrderRequest(BaseModel):
    def validate_required_strings(cls, v, info):
    def validate_quantity(cls, v):
    def validate_limit_price(cls, v):
    def validate_timestamp(cls, v):
    def validate_order_shape(self):
    def exchange_ts_sec(self) -> float:
    def notional_usd(self) -> Decimal:
class OrderFill(BaseModel):
    def validate_required_strings(cls, v, info):
    def validate_quantity(cls, v):
    def validate_price(cls, v):
    def validate_fee(cls, v):
    def validate_timestamp(cls, v):
    def validate_latency(cls, v):
    def validate_venue_order_id(cls, v):
    def exchange_ts_sec(self) -> float:
    def notional_usd(self) -> Decimal:
    def net_amount_usd(self) -> Decimal:
``

## File: .\app\models\signals.py
``python
from typing import Any, Dict, Optional
import numpy as np
from pydantic import BaseModel, ConfigDict, Field
class DarkPoolPrint(BaseModel):
    def exchange_ts_sec(self) -> float:
    def dollar_value(self) -> float:
class OptionsFlow(BaseModel):
    def exchange_ts_sec(self) -> float:
    def volume_oi_ratio(self) -> float:
class StrategySignal(BaseModel):
    def exchange_ts_sec(self) -> float:
    def is_actionable(self) -> bool:
``

## File: .\app\models\unified_market.py
``python
from app.models.enums and are NOT type-compatible with the live spine.
import numpy as np
from typing import Optional, Dict, Any, List, Tuple, Union
from enum import Enum
from dataclasses import dataclass, field
from collections import deque
import threading
import time
class AssetClass(Enum):
class Exchange(Enum):
class TradingStatus(Enum):
class MacroRegime(Enum):
class InstrumentSpec:
    def get_precision_metadata(self) -> Dict[str, Any]:
    def update_regime(self, regime: MacroRegime, confidence: float, current_ns: int) -> None:
    def update_price(self, price: float, volume: float, timestamp_ns: int) -> None:
class CrossAssetCorrelationMatrix:
    def __init__(self, max_instruments: int = 256):
    def update(self, instrument_id: int, price: float, timestamp_ns: int) -> None:
    def compute_correlations(self, window: int = 100) -> None:
    def get_correlation(self, id1: int, id2: int) -> float:
    def get_row(self, instrument_id: int) -> np.ndarray:
    def get_shared_memory_buffer(self) -> np.ndarray:
    def get_version(self) -> int:
class UnifiedMarketData:
    def __init__(self, max_instruments: int = 256):
    def register_instrument(self, spec: InstrumentSpec) -> int:
    def get_instrument_by_id(self, instrument_id: int) -> Optional[InstrumentSpec]:
    def get_instrument(self, symbol: str) -> Optional[InstrumentSpec]:
    def update_price(self, symbol: str, price: float, volume: float, timestamp_ns: int) -> None:
    def get_price(self, symbol: str) -> Optional[float]:
    def get_market_status(self, symbol: str, current_ns: int) -> TradingStatus:
    def is_tradable(self, symbol: str, current_ns: int) -> bool:
    def get_all_symbols(self, asset_class: Optional[AssetClass] = None) -> List[str]:
    def update_macro_regime(self, symbol: str, regime: MacroRegime, confidence: float, current_ns: int) -> None:
    def get_macro_regime(self, symbol: str) -> MacroRegime:
    def get_correlation(self, symbol1: str, symbol2: str) -> float:
    def get_correlation_by_id(self, id1: int, id2: int) -> float:
    def get_correlation_row(self, symbol: str) -> Optional[np.ndarray]:
    def get_shared_memory_buffer(self) -> np.ndarray:
    def get_correlation_version(self) -> int:
    def compute_correlations(self, window: int = 100) -> None:
def datetime_to_ns(dt) -> int:
def ns_to_datetime(ns: int):
def now_ns() -> int:
def time_to_ns(hour: int, minute: int = 0, second: int = 0) -> int:
def create_unified_market_data(max_instruments: int = 256) -> UnifiedMarketData:
def create_correlation_matrix(max_instruments: int = 256) -> CrossAssetCorrelationMatrix:
def get_predefined_instruments() -> List[InstrumentSpec]:
``

## File: .\app\models\__init__.py
``python
from app.models.enums import (
from app.models.contracts import (
from app.models.fusion import FusionDecision
from app.models.signals import DarkPoolPrint, OptionsFlow, StrategySignal
from app.models.orders import OrderRequest, OrderFill
from app.models.market_data import (
from app.models.events import (
from app.models.invariants import (
``

## File: .\app\monitoring\alerts.py
``python
import logging
import threading
import time
import queue
import requests
from typing import Optional, Dict, Any, Callable, List
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
import json
class AlertSeverity(Enum):
class AlertType(Enum):
class Alert:
class SovereignSentinel:
    def __init__(
    def heartbeat(self, latency_ms: float = 0.0) -> None:
    def _check_heartbeat(self) -> None:
    def _can_send_alert(self, alert_type: AlertType) -> bool:
    def _record_alert_sent(self, alert_type: AlertType) -> None:
    def _queue_alert(
    def send_alert(
    def _dispatch_webhook(self, payload: Dict[str, Any]) -> None:
    def _dispatch_telegram(self, payload: Dict[str, Any]) -> None:
    def _dispatch_alert(self, alert: Alert) -> None:
    def _flush_state_if_needed(self, force: bool = False) -> None:
    def _save_state(self) -> None:
    def _force_save_state(self) -> None:
    def alert_kill_switch_triggered(self, equity: float, floor: float) -> None:
    def alert_vol_fuse_triggered(self, drop_pct: float, oldest_equity: float, newest_equity: float) -> None:
    def alert_latency_spike(self, latency_ms: float, threshold_ms: float) -> None:
    def alert_exchange_outage(self, exchange: str, age_sec: float) -> None:
    def alert_zombie_orders(self, count: int, value: float, oldest_age_sec: float) -> None:
    def alert_drawdown_limit(self, drawdown_pct: float, limit_pct: float) -> None:
    def alert_position_limit(self, symbol: str, exposure: float, limit: float) -> None:
    def alert_strategy_error(self, strategy: str, error: str) -> None:
    def _load_state(self) -> None:
    def start(self) -> None:
    def stop(self) -> None:
    def _monitor_loop(self) -> None:
    def _alert_loop(self) -> None:
    def _state_flusher_loop(self) -> None:
    def get_status(self) -> Dict[str, Any]:
    def get_recent_alerts(self, count: int = 10) -> List[Dict[str, Any]]:
``

## File: .\app\monitoring\health.py
``python
from __future__ import annotations
import logging
import time
from dataclasses import asdict, dataclass, field, replace
from decimal import Decimal
from enum import Enum, unique
from typing import Any, Dict, List, Optional, Tuple
from app.utils.enums import (
def _now_ns() -> int:
class ComponentHealthState(str, Enum):
class ComponentCriticality(str, Enum):
class TimestampSource(str, Enum):
class HealthReasonCode(str, Enum):
class HealthTransitionType(str, Enum):
class ComponentStatus:
class HealthPolicyConfig:
    def __post_init__(self) -> None:
class RegisteredComponent:
class ComponentHealthRecord:
class HealthViolation:
    def to_legacy_dict(self) -> Dict[str, Any]:
class HealthSnapshot:
class HealthJournalRecord:
class HealthMonitor:
    def __init__(self, stale_threshold_ms: int = 2000):
    def register_component(
    def set_component_enabled(self, component_name: str, enabled: bool, *, ts_ns: Optional[int] = None) -> None:
    def quarantine_component(self, component_name: str, *, ts_ns: Optional[int] = None, reason: str = "QUARANTINED") -> None:
    def pulse(self, component_name: str, ts_ns: int, metadata: Optional[Dict[str, Any]] = None):
    def pulse_canonical(
    def record_error(
    def evaluate_system_health(self, current_ts_ns: int) -> List[Dict[str, Any]]:
    def evaluate_system_health_canonical(self, *, current_ts_ns: int) -> List[HealthViolation]:
    def get_snapshot(self) -> Dict[str, Any]:
    def get_snapshot_canonical(
    def journal(self, limit: Optional[int] = None) -> List[HealthJournalRecord]:
    def _build_violation(
    def _append_journal(
    def _bump_version(self) -> None:
``

## File: .\app\monitoring\logger.py
``python
import logging
import logging.handlers
import json
import sys
import os
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any
from logging import LogRecord
class JSONFormatter(logging.Formatter):
    def __init__(self, **kwargs):
    def format(self, record: LogRecord) -> str:
class PlainFormatter(logging.Formatter):
    def format(self, record: LogRecord) -> str:
class SovereignLogger:
    def __init__(self):
    def setup(
    def get_logger(self, name: str) -> logging.Logger:
def setup_logger(config: Any = None, level: str = "INFO") -> None:
def get_logger(name: str) -> logging.Logger:
class PerformanceLogger:
    def __init__(self, name: str):
    def log_latency(self, operation: str, latency_ms: float, metadata: Optional[Dict[str, Any]] = None) -> None:
    def log_order_execution(self, order_id: str, symbol: str, latency_ms: float, fill_price: float, fees: float) -> None:
    def log_signal(self, strategy: str, symbol: str, confidence: float, latency_ms: float) -> None:
class AuditLogger:
    def __init__(self):
    def log_order(self, order_id: str, symbol: str, side: str, quantity: float, price: float, strategy: str) -> None:
    def log_fill(self, order_id: str, fill_price: float, fill_quantity: float, fees: float) -> None:
    def log_kill_switch(self, reason: str, equity: float, floor: float) -> None:
    def log_config_change(self, key: str, old_value: Any, new_value: Any, source: str) -> None:
``

## File: .\app\monitoring\performance_attribution.py
``python
from __future__ import annotations
import logging
import time
from dataclasses import asdict, dataclass, field
from decimal import Decimal, InvalidOperation, getcontext
from enum import Enum, unique
from typing import Any, Dict, List, Optional
from app.utils.ids import generate_correlation_id, generate_request_id
from app.utils.enums import SleeveType
def _d(value: Any, *, field_name: str) -> Decimal:
def _ensure_positive(value: Decimal, field_name: str) -> Decimal:
def _ensure_non_negative(value: Decimal, field_name: str) -> Decimal:
def _now_ns() -> int:
class AttributionQuality(str, Enum):
class TimestampSource(str, Enum):
class AttributionPolicyConfig:
    def __post_init__(self) -> None:
class AttributionRecord:
    def to_dict(self) -> Dict[str, Any]:
class AttributionAggregateSnapshot:
class AttributionJournalRecord:
class PerformanceAttributor:
    def __init__(self):
    def attribute_trade(
    def get_aggregate_stats(self) -> Dict[str, Decimal]:
    def attribute_trade_detailed(
    def get_aggregate_snapshot(self, *, timestamp_ns: int) -> AttributionAggregateSnapshot:
    def journal(self, limit: Optional[int] = None) -> List[AttributionJournalRecord]:
    def reset(self) -> None:
    def _append_journal(self, record: AttributionRecord) -> None:
``

## File: .\app\monitoring\reports.py
``python
from __future__ import annotations
import hashlib
import json
import logging
import os
import tempfile
import time
from dataclasses import asdict, dataclass, field, is_dataclass
from decimal import Decimal, InvalidOperation
from enum import Enum, unique
from typing import Any, Dict, List, Optional, Sequence
from app.utils.ids import generate_correlation_id, generate_request_id
def _d(value: Any, *, field_name: str) -> Decimal:
def _canonical_json_default(obj: Any) -> Any:
def _canonical_json_dumps(payload: Any, *, pretty: bool = True) -> str:
def _sha256_hex(text: str) -> str:
def _now_ns() -> int:
class ReportType(str, Enum):
class ReportQuality(str, Enum):
class TimestampSource(str, Enum):
class ReportConfig:
class ReportMetadata:
class PerformanceSummary:
class ReportPacket:
class ReportGenerationResult:
class ReportJournalRecord:
class ReportGenerator:
    def __init__(self, output_path: str = "./reports/"):
    def build_packet(
    def serialize_packet(self, packet: ReportPacket) -> str:
    def write_packet(
    def generate_packet(
    def report_journal(self, limit: Optional[int] = None) -> List[ReportJournalRecord]:
    def generate_daily_packet(
    def _normalize_mapping(self, payload: Dict[str, Any]) -> Dict[str, Any]:
    def _normalize_value(self, value: Any) -> Any:
    def _atomic_write(self, path: str, payload: str) -> None:
    def _append_journal(
def replace_digest(packet: ReportPacket, digest: Optional[str]) -> ReportPacket:
``

## File: .\app\monitoring\__init__.py
``python
``

## File: .\app\replay\checkpoint.py
``python
import logging
import hashlib
import json
import os
from pathlib import Path
from typing import Optional, Dict, Any, List, Union
from uuid import uuid4
from app.models.contracts import RecoveryCheckpoint, ReplayPosition
from app.models.enums import CheckpointType
class ReplayCheckpointError(Exception):
class ReplayCheckpointNotFoundError(ReplayCheckpointError):
class ReplayCheckpointCorruptedError(ReplayCheckpointError):
def _serialize_checkpoint_type(checkpoint_type: CheckpointType) -> str:
def _canonical_representation(
class ReplayCheckpointManager:
    def __init__(
    def _get_checkpoint_path(self, checkpoint_id: str) -> Path:
    def _calculate_checksum(self, checkpoint: RecoveryCheckpoint) -> str:
    def _serialize_checkpoint(self, checkpoint: RecoveryCheckpoint) -> Dict[str, Any]:
    def _deserialize_checkpoint(self, data: Dict[str, Any]) -> RecoveryCheckpoint:
    def save_checkpoint(self, checkpoint: RecoveryCheckpoint) -> str:
    def load_checkpoint(
    def list_checkpoints(
    def get_latest_checkpoint(
    def delete_checkpoint(self, checkpoint_id: str) -> bool:
    def _cleanup_old_checkpoints(self) -> None:
    def create_checkpoint(
def create_checkpoint_manager(
``

## File: .\app\replay\engine.py
``python
import logging
from pathlib import Path
from typing import Optional, Dict, Any, Union, Callable
from app.replay.source import open_replay_source
from app.replay.replay_session import ReplaySession, replay_session, verify_replay_session
from app.replay.verifier import VerificationResult
from app.replay.checkpoint import ReplayCheckpointManager, create_checkpoint_manager
from app.models.contracts import EventEnvelope, ReplayPosition
from app.models.enums import ReplayMode, CheckpointType
from app.utils.time_utils import set_replay_time_ns, clear_replay_time, ReplayTimeContext
class ReplayEngineError(Exception):
class ReplayEngine:
    def __init__(
    def _get_session_start_time(self) -> int:
    def _restore_from_checkpoint(self, session: ReplaySession) -> None:
    def _create_checkpoint(self, session: ReplaySession) -> None:
    def run(
    def get_progress(self) -> Dict[str, Any]:
    def get_stats(self) -> Dict[str, Any]:
def run_replay(
def run_replay_with_verification(
``

## File: .\app\replay\normalizer.py
``python
import logging
from typing import Optional, Iterator, Dict, Any, List, Union
from app.models.enums import EventType
from app.models.contracts import EventEnvelope
from app.utils.time_utils import is_monotonic
class EventNormalizerError(Exception):
class EventNormalizerValidationError(EventNormalizerError):
class NormalizerStats:
    def __init__(self):
    def reset(self) -> None:
class EventNormalizer:
    def __init__(
    def normalize(self, envelope: EventEnvelope) -> Optional[EventEnvelope]:
    def normalize_stream(
    def reset_stats(self) -> None:
    def get_stats(self) -> Dict[str, Any]:
def normalize_event(
def normalize_events(
def create_market_data_normalizer(fail_fast: bool = True) -> EventNormalizer:
def create_system_event_normalizer(fail_fast: bool = True) -> EventNormalizer:
``

## File: .\app\replay\replay_cursor.py
``python
import logging
from typing import Optional, Iterator, Dict, Any, List, Tuple
from dataclasses import dataclass
from app.models.contracts import EventEnvelope, ReplayPosition
from app.models.enums import ReplayMode
from app.utils.time_utils import is_monotonic
class ReplayCursorError(Exception):
class ReplayCursorSeekError(ReplayCursorError):
class ReplayCursorStateError(ReplayCursorError):
class CursorState:
    def to_dict(self) -> Dict[str, Any]:
    def from_dict(cls, data: Dict[str, Any]) -> 'CursorState':
class ReplayCursor:
    def __init__(
    def _validate_event_ordering(self) -> None:
    def _initialize_cursor(self) -> None:
    def _seek_to_position(self, position: ReplayPosition) -> None:
    def __iter__(self) -> Iterator[EventEnvelope]:
    def __next__(self) -> EventEnvelope:
    def seek_to_timestamp(self, timestamp_ns: int) -> None:
    def seek_to_index(self, index: int) -> None:
    def get_current_position(self) -> Optional[ReplayPosition]:
    def get_cursor_state(self) -> Optional[CursorState]:
    def get_progress(self) -> Dict[str, Any]:
    def has_next(self) -> bool:
    def get_remaining_count(self) -> int:
    def reset(self) -> None:
    def snapshot_state(self) -> Dict[str, Any]:
    def restore_state(self, state: Dict[str, Any]) -> None:
def create_replay_cursor(
``

## File: .\app\replay\replay_session.py
``python
import logging
import hashlib
import json
from typing import Optional, Iterator, Dict, Any, List, Union
from pathlib import Path
from app.replay.source import ReplaySource, ReplaySourceError
from app.replay.normalizer import EventNormalizer, EventNormalizerError, create_market_data_normalizer
from app.replay.replay_cursor import ReplayCursor, ReplayCursorError, create_replay_cursor
from app.models.contracts import EventEnvelope, ReplayPosition
from app.models.enums import ReplayMode, EventType, SourceType
from app.models.events import ReplayStartEvent, ReplayEndEvent
from app.utils.time_utils import now_ns
class ReplaySessionError(Exception):
class ReplaySessionLoadError(ReplaySessionError):
class ReplaySessionVerificationError(ReplaySessionError):
def _deterministic_serialize_payload(payload: Any) -> str:
def _calculate_event_hash(event: EventEnvelope) -> str:
class ReplaySession:
    def __init__(
    def __enter__(self):
    def __exit__(self, exc_type, exc_val, exc_tb):
    def start(self) -> None:
    def _load_and_normalize_events(self) -> None:
    def _initialize_cursor(self) -> None:
    def end(self) -> None:
    def _calculate_session_checksum(self) -> str:
    def iterate_events(self) -> Iterator[EventEnvelope]:
    def _verify_event(self, index: int, event: EventEnvelope) -> None:
    def get_current_position(self) -> Optional[ReplayPosition]:
    def get_progress(self) -> Dict[str, Any]:
    def get_stats(self) -> Dict[str, Any]:
    def seek_to_timestamp(self, timestamp_ns: int) -> None:
    def seek_to_index(self, index: int) -> None:
    def reset(self) -> None:
    def snapshot_state(self) -> Dict[str, Any]:
    def restore_state(self, state: Dict[str, Any]) -> None:
def replay_session(
def verify_replay_session(
``

## File: .\app\replay\source.py
``python
import json
import os
import tempfile
import logging
from pathlib import Path
from typing import Optional, Iterator, Dict, Any, Union, List, Tuple
from app.models.enums import EventType, SourceType
from app.models.events import (
from app.models.contracts import EventEnvelope
from app.utils.time_utils import is_monotonic
class ReplaySourceError(Exception):
class ReplaySourceFormatError(ReplaySourceError):
class ReplaySourceConsistencyError(ReplaySourceError):
class ReplaySource:
    def __init__(
    def __enter__(self):
    def __exit__(self, exc_type, exc_val, exc_tb):
    def __iter__(self) -> Iterator[EventEnvelope]:
    def _parse_payload(
    def get_event_count(self) -> int:
    def get_source_info(self) -> Dict[str, Any]:
    def create_test_source(events: List[Tuple[Union[EventType, str], int, Dict[str, Any]]]) -> 'ReplaySource':
def open_replay_source(
``

## File: .\app\replay\verifier.py
``python
import logging
import hashlib
import json
from typing import Optional, Iterator, Dict, Any, List, Tuple, Union
from dataclasses import dataclass, field
from enum import Enum
from app.models.contracts import EventEnvelope
from app.models.enums import EventType
from app.replay.replay_session import ReplaySession, ReplaySessionVerificationError
class VerificationMode(str, Enum):
class VerificationFailure:
    def to_dict(self) -> Dict[str, Any]:
class VerificationResult:
    def failure_count(self) -> int:
    def to_dict(self) -> Dict[str, Any]:
def _deterministic_serialize(value: Any) -> str:
def _calculate_event_checksum(event: EventEnvelope) -> str:
def _compare_payloads_exact(expected: Any, actual: Any) -> bool:
class ReplayVerifier:
    def __init__(
    def _verify_timestamp(
    def _verify_payload(
    def verify_event(
    def verify_session(
    def verify_session_with_checksum(
    def reset(self) -> None:
    def get_summary(self) -> Dict[str, Any]:
def create_strict_verifier(
def create_tolerant_verifier(
def create_audit_verifier(
``

## File: .\app\replay\__init__.py
``python
from app.replay.source import (
from app.replay.normalizer import (
from app.replay.replay_cursor import (
from app.replay.replay_session import (
``

## File: .\app\risk\drawdown_guard.py
``python
from __future__ import annotations
import logging
from dataclasses import dataclass, field, replace
from decimal import Decimal, InvalidOperation, ROUND_DOWN, getcontext
from enum import Enum, IntEnum, unique
from typing import Any, Dict, List, Optional, Tuple
import numpy as np
from app.utils.enums import (
def _d(value: Any, *, field_name: str) -> Decimal:
def _ensure_non_negative(value: Decimal, field_name: str) -> Decimal:
def _ensure_positive(value: Decimal, field_name: str) -> Decimal:
def _quantize_ratio(value: Decimal) -> Decimal:
class DrawdownQuality(str, Enum):
class DrawdownTransitionType(str, Enum):
class DrawdownReasonCode(str, Enum):
class DrawdownPrecedence(IntEnum):
class EquityKinematics:
class DrawdownAdvisory:
class DrawdownPolicyConfig:
    def __post_init__(self) -> None:
class CanonicalEquityKinematics:
class CanonicalDrawdownAdvisory:
    def __post_init__(self) -> None:
    def to_legacy(self) -> DrawdownAdvisory:
class DrawdownMutationRecord:
class DrawdownInvariantReport:
class DrawdownGuard:
    def __init__(
    def update(self, current_equity: Decimal, ts_ns: int) -> DrawdownAdvisory:
    def update_canonical(self, current_equity: Decimal, ts_ns: int) -> CanonicalDrawdownAdvisory:
    def _resolve_advisory(
    def _build_stream_failure_advisory(
    def _get_recent_history(self, n: int) -> np.ndarray:
    def _active_history(self) -> np.ndarray:
    def _classify_hazard_velocity(
    def _derive_transition(
    def get_forensic_state(self) -> Dict[str, Any]:
    def reset_authority(
    def mutation_journal(self, limit: Optional[int] = None) -> List[DrawdownMutationRecord]:
    def validate_invariants(self) -> DrawdownInvariantReport:
    def _append_mutation(
    def _bump_version(self) -> None:
``

## File: .\app\risk\exposure_manager.py
``python
from __future__ import annotations
import logging
import threading
import time
from dataclasses import dataclass, field, replace
from decimal import Decimal, InvalidOperation, ROUND_DOWN, getcontext
from enum import Enum, unique
from typing import Any, Dict, Iterable, List, Optional, Tuple
from app.utils.enums import (
def _d(value: Any, *, field_name: str) -> Decimal:
def _ensure_non_negative(value: Decimal, field_name: str) -> Decimal:
def _ensure_positive(value: Decimal, field_name: str) -> Decimal:
def _safe_div(n: Decimal, d: Decimal) -> Decimal:
def _abs(value: Decimal) -> Decimal:
def _quantize_down(value: Decimal, step: Decimal) -> Decimal:
def _now_ns() -> int:
def _signed_qty_for_side(side: OrderSide, qty: Decimal) -> Decimal:
def _position_side_from_qty(qty: Decimal) -> PositionSide:
class ReservationStatus(str, Enum):
class ExposureSnapshotQuality(str, Enum):
class MutationType(str, Enum):
class ExposurePolicyConfig:
    def __post_init__(self) -> None:
class PositionState:
    def notional_book(self) -> Decimal:
    def notional_mark(self) -> Decimal:
    def signed_mark_exposure(self) -> Decimal:
    def position_side(self) -> PositionSide:
class PendingReservation:
    def __post_init__(self) -> None:
    def open_qty(self) -> Decimal:
    def signed_open_qty(self) -> Decimal:
    def open_notional(self) -> Decimal:
    def weighted_open_notional(self) -> Decimal:
class MutationRecord:
class ExposureSurface:
class ExposureIntentValidation:
class FillResult:
class SleeveExposureSnapshot:
class GlobalExposureSnapshot:
class ExposureRiskSnapshot:
class ReconciliationResult:
class ExposureInvariantReport:
class ExposureManager:
    def __init__(
    def validate_intent(
    def validate_intent_detailed(
    def reserve_intent(
    def update_reservation_status(
    def release_reservation(
    def apply_fill_to_reservation(
    def age_stale_reservations(self, now_ns: Optional[int] = None) -> List[str]:
    def handle_fill(
    def handle_fill_detailed(
    def update_unrealized_pnl(self, symbol: str, current_mid_price: Decimal) -> None:
    def update_unrealized_pnl_detailed(self, symbol: str, current_mid_price: Decimal) -> Dict[SleeveType, Decimal]:
    def update_equity(self, new_equity: Decimal) -> None:
    def get_risk_snapshot(self, current_prices: Dict[str, Decimal]) -> Dict[str, Any]:
    def get_risk_snapshot_typed(self, current_prices: Dict[str, Decimal]) -> ExposureRiskSnapshot:
    def exposure_surface(self) -> ExposureSurface:
    def mutation_journal(self, *, limit: Optional[int] = None) -> List[MutationRecord]:
    def validate_invariants(self) -> ExposureInvariantReport:
    def _calculate_current_hazard(
    def force_inventory_sync(
    def force_inventory_sync_detailed(
    def current_utilization(self) -> Decimal:
    def sleeve_utilization(self, sleeve: SleeveType) -> Decimal:
    def asset_concentration(self, symbol: str) -> Decimal:
    def position_for(self, sleeve: SleeveType, symbol: str) -> Optional[PositionState]:
    def reservations_for(self, sleeve: Optional[SleeveType] = None, symbol: Optional[str] = None) -> List[PendingReservation]:
    def iter_positions(self) -> Iterable[PositionState]:
    def recompute_aggregates(self) -> None:
    def _default_confidence_weight(self, status: ReservationStatus) -> Decimal:
    def _reject_validation(
    def _classify_directional_effect(
    def _asset_total_mark_notional(self, symbol: str) -> Decimal:
    def _asset_reserved_notional(self, symbol: str) -> Decimal:
    def _pending_signed_qty_for(
    def _remove_reservation(
    def _derive_snapshot_quality(self) -> ExposureSnapshotQuality:
    def _append_mutation(
    def _bump_version(self) -> None:
``

## File: .\app\risk\guard.py
``python
import logging
import threading
import time
import json
import os
import tempfile
import shutil
from typing import Optional, Dict, Any, List, Callable, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import deque
from pathlib import Path
class RiskState:
class HybridRiskGuard:
    def __init__(
    def _fsync_file(self, filepath: Path) -> None:
    def _atomic_write_json(self, data: Dict[str, Any], filepath: Path) -> bool:
    def _json_serializer(self, obj):
    def _load_state(self, initial_equity: float) -> RiskState:
    def _save_state(self) -> None:
    def _prune_equity_history(self) -> None:
    def update_equity_history(self, current_equity: float) -> None:
    def check_velocity_of_loss(self, current_equity: float) -> Tuple[bool, Dict[str, Any]]:
    def is_vol_fuse_triggered(self) -> bool:
    def _trigger_vol_fuse(self) -> None:
    def _update_tradeable_equity(self) -> None:
    def record_fees(self, fees: float, withdrawal_fees: float = 0.0) -> None:
    def get_total_cost_to_pocket(self) -> Dict[str, float]:
    def update_pending_orders(self, count: int, total_value: float, oldest_timestamp: Optional[datetime] = None) -> bool:
    def _trigger_zombie_alert(self) -> None:
    def update_latency(self, latency_ms: float) -> bool:
    def _trigger_lag_alert(self) -> None:
    def update_websocket_heartbeat(self) -> None:
    def check_websocket_health(self) -> bool:
    def get_adaptive_floor(self) -> float:
    def get_physical_fuse(self) -> float:
    def get_distance_to_floor(self) -> float:
    def update_high_water_mark(self, current_equity: float) -> bool:
    def check_adaptive_floor(self, current_equity: float, tpe_coherence: float = 0.5) -> Tuple[bool, str]:
    def check_physical_fuse(self, current_equity: float) -> bool:
    def check_lag_abort(self) -> bool:
    def check_exchange_outage(self) -> bool:
    def assess_state(self, current_equity: float, tpe_coherence: float = 0.5) -> Dict[str, Any]:
    def _trigger_recalibration(self) -> None:
    def _trigger_emergency(self) -> None:
    def register_recalibrate_callback(self, callback: Callable) -> None:
    def register_emergency_callback(self, callback: Callable) -> None:
    def register_zombie_callback(self, callback: Callable) -> None:
    def register_lag_callback(self, callback: Callable) -> None:
    def register_vol_fuse_callback(self, callback: Callable) -> None:
    def can_trade(self) -> bool:
    def reset_fuse(self) -> None:
    def get_status(self) -> Dict[str, Any]:
``

## File: .\app\risk\kill_switch.py
``python
import logging
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Dict, Any, Optional, List
from enum import Enum
from app.utils.time_utils import now_ns
class KillSwitchType(Enum):
class KillSwitchState(Enum):
class KillSwitchRecord:
    def to_dict(self) -> Dict[str, Any]:
    def from_dict(cls, data: Dict[str, Any]) -> "KillSwitchRecord":
class KillSwitch:
    def __init__(self):
    def trigger(
    def trigger_drawdown(
    def trigger_emergency(self, reason: str, timestamp_ns: int) -> bool:
    def trigger_manual(self, reason: str, timestamp_ns: int) -> bool:
    def advance_state(self, timestamp_ns: int) -> bool:
    def reset(self, timestamp_ns: int, reason: str = "manual_reset") -> bool:
    def is_killed(self, timestamp_ns: int) -> bool:
    def can_trade(self, timestamp_ns: int) -> bool:
    def get_state(self) -> KillSwitchState:
    def get_active_record(self) -> Optional[KillSwitchRecord]:
    def get_trigger_history(self, limit: int = 100) -> List[KillSwitchRecord]:
    def get_last_state_change_ns(self) -> int:
    def get_cooldown_remaining_ns(self, timestamp_ns: int) -> int:
    def get_cooldown_until_ns(self) -> int:
    def export_state(self) -> Dict[str, Any]:
    def import_state(self, state: Dict[str, Any], timestamp_ns: int) -> None:
    def reset_all(self, timestamp_ns: int) -> None:
    def get_status(self, timestamp_ns: int) -> Dict[str, Any]:
def create_kill_switch() -> KillSwitch:
``

## File: .\app\risk\position_sizing.py
``python
import logging
from decimal import Decimal
from typing import Optional, Dict, Any, Union
from dataclasses import dataclass
from app.constants import (
from app.utils.decimal_utils import (
class PositionSizeResult:
    def to_dict(self) -> Dict[str, Any]:
class PositionSizingError(Exception):
class PositionSizingEngine:
    def __init__(self, config: Any):
    def _get_regime_multiplier(self, regime: RegimeType) -> Decimal:
    def _get_volatility_multiplier(self, volatility: Decimal) -> Decimal:
    def _get_strategy_cap_pct(self, strategy: Union[SleeveType, str]) -> Decimal:
    def _compute_fractional_stop_distance(
    def _apply_caps(
    def calculate_risk_based_size(
    def calculate_notional_based_size(
    def calculate_position_size(
    def get_strategy_cap_percent(self, strategy: Union[SleeveType, str]) -> Decimal:
    def get_hard_cap_percent(self) -> Decimal:
    def get_risk_per_trade_percent(self) -> Decimal:
def create_position_sizing_engine(config: Any) -> PositionSizingEngine:
``

## File: .\app\risk\position_unwind.py
``python
from __future__ import annotations
import logging
import time
from dataclasses import dataclass, field, replace
from decimal import Decimal, InvalidOperation, ROUND_DOWN
from enum import Enum, unique
from typing import Any, Dict, Iterable, List, Optional, Tuple
from app.utils.enums import (
from app.utils.ids import (
def _d(value: Any, *, field_name: str) -> Decimal:
def _ensure_non_negative(value: Decimal, field_name: str) -> Decimal:
def _ensure_positive(value: Decimal, field_name: str) -> Decimal:
def _quantize_down(value: Decimal, step: Decimal) -> Decimal:
def _now_ms() -> int:
def _sign_side(quantity: Decimal) -> Optional[OrderSide]:
class UnwindCampaignStatus(str, Enum):
class UnwindAttemptStatus(str, Enum):
class UnwindEscalationLevel(str, Enum):
class UnwindProgressState(str, Enum):
class UnwindPolicyConfig:
    def __post_init__(self) -> None:
class PositionSnapshot:
    def __post_init__(self) -> None:
class UnwindMarketContext:
class UnwindRiskContext:
class UnwindOrderFeedback:
    def __post_init__(self) -> None:
class UnwindAssessment:
class UnwindAttempt:
    def __post_init__(self) -> None:
class SymbolUnwindState:
    def side(self) -> Optional[OrderSide]:
    def abs_remaining_qty(self) -> Decimal:
class UnwindRecommendation:
    def to_legacy_dict(self) -> Dict[str, Any]:
class UnwindProgressSnapshot:
class UnwindCampaign:
    def symbol_state_map(self) -> Dict[str, SymbolUnwindState]:
    def market_context_map(self) -> Dict[str, UnwindMarketContext]:
class PositionUnwindManager:
    def __init__(self, max_retries: int = 3):
    def start_campaign(
    def plan_next_actions(
    def ingest_feedback(
    def evaluate_campaign_progress(self, campaign: UnwindCampaign) -> UnwindProgressSnapshot:
    def generate_unwind_intents(self, active_positions: Dict[str, Decimal]) -> List[Dict]:
    def evaluate_unwind_progress(self, remaining_positions: Dict[str, Decimal]) -> bool:
    def _assess_position(
    def _prioritize_positions(self, positions: Iterable[PositionSnapshot]) -> List[PositionSnapshot]:
        def sort_key(p: PositionSnapshot) -> tuple[int, Decimal, str]:
    def _ordered_symbol_keys(self, symbol_map: Dict[str, SymbolUnwindState]) -> List[str]:
    def _build_next_attempts(
    def _attempt_to_recommendation(
    def _refresh_campaign_status(self, campaign: UnwindCampaign) -> UnwindCampaign:
    def _map_order_status_to_attempt_status(self, status: OrderStatus) -> UnwindAttemptStatus:
    def _apply_fill_to_remaining(
    def _estimate_remaining_notional(self, state: SymbolUnwindState) -> Optional[Decimal]:
    def _is_economically_flat(
    def _has_open_attempt(self, state: SymbolUnwindState) -> bool:
    def _split_quantity_into_tranches(
    def _derive_campaign_escalation_level(self, risk: UnwindRiskContext) -> UnwindEscalationLevel:
    def _derive_symbol_escalation(
    def _classify_unwind_style(
    def _select_execution_style(
``

## File: .\app\risk\safety.py
``python
import logging
import numpy as np
from typing import Optional, Tuple, List, Dict, Any
from datetime import datetime, timedelta
from collections import deque
from app.models import OrderIntent, PortfolioSnapshot, PhysicalVerification
from app.brain.sentiment_velocity import MacroSignal
from app.constants import ControlMode, RiskProfile
class SafetyGate:
    def __init__(self, config: Any):
    def update_macro_signal(self, macro_signal: MacroSignal) -> None:
    def _get_macro_adjusted_confidence(self, base_confidence: float) -> float:
    def _update_ewma(self, new_value: float) -> float:
    def adjust_confidence_threshold(self, latency_impact_ratio: float) -> float:
    def get_adverse_selection_score(self) -> float:
    def record_trade(self, verification: PhysicalVerification) -> None:
    def approve_order(
    def _is_stale_data(self, portfolio: PortfolioSnapshot) -> bool:
    def _exceeds_drawdown_limit(self, portfolio: PortfolioSnapshot) -> bool:
    def _check_exposure_caps(self, order: OrderIntent, portfolio: PortfolioSnapshot) -> bool:
    def _has_sufficient_liquidity(self, order: OrderIntent) -> bool:
    def trigger_kill_switch(self, reason: str) -> None:
    def reset_kill_switch(self) -> None:
    def get_min_confidence(self) -> float:
    def get_macro_status(self) -> Dict[str, Any]:
    def get_stats(self) -> Dict[str, Any]:
``

## File: .\app\risk\sovereign_execution_guard.py
``python
from enum import Enum
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_DOWN, getcontext
from typing import List, Dict, Optional, Set, Any
from collections import deque
from datetime import datetime, timezone
class AggressionState(Enum):
class HaltState(Enum):
class ConvictionLevel(Enum):
class SleeveTier(Enum):
class SovereignGovernancePolicy:
class SleeveMetadata:
class TradeSetup:
    def __post_init__(self):
class AuthorizationReceipt:
class AuditRecord:
class DynamicRiskState:
class SovereignExecutionGuard:
    def __init__(self, initial_capital: float = 20000.0, absolute_survival_floor: float = 17500.0):
    def register_sleeve(self, metadata: SleeveMetadata) -> None:
    def start_new_session(self, current_live_equity: float) -> None:
    def manual_rearm(self, current_live_equity: float, rearm_reason: str) -> None:
    def _log_audit(self, event_type: str, old_val: str, new_val: str, reason: str, meta: Dict[str, Any]) -> None:
    def register_trade_result(self, realized_pnl_usd: float) -> None:
    def update_live_equity(self, current_live_equity: float) -> DynamicRiskState:
    def _set_aggression_state(self, new_state: AggressionState, reason: str) -> None:
    def _evaluate_halt_ladder(self) -> None:
    def _get_authorized_sleeves(self) -> Set[str]:
    def request_authorization(self, setup: TradeSetup) -> AuthorizationReceipt:
    def _deny(self, setup: TradeSetup, reason: str, stack: Dict[str, str]) -> AuthorizationReceipt:
    def get_state(self) -> DynamicRiskState:
    def export_audit_trail(self, count: int = 50) -> List[Dict[str, Any]]:
``

## File: .\app\risk\stale_data_guard.py
``python
from __future__ import annotations
import logging
import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Dict, Final, Optional, Tuple
import numpy as np
from app.utils.enums import (
class TemporalGuardConfig:
    def __post_init__(self) -> None:
class TemporalInput:
    def __post_init__(self) -> None:
class TemporalKinematics:
class TemporalInvariantStatus:
class TemporalRiskAssessment:
class StaleDataGuard:
    def __init__(self, symbol: str, max_drift_ms: int = 500):
    def assess(self, observation: TemporalInput) -> TemporalRiskAssessment:
    def evaluate(
    def validate_continuity_invariant(self, incoming_exchange_ts_ns: int) -> bool:
    def get_forensic_snapshot(self) -> Dict[str, Any]:
    def _push_sample(
    def _active_view(self) -> np.ndarray:
    def _compute_statistics(self, active: np.ndarray) -> Dict[str, float]:
    def _resolve_hazard(
    def _classify_hazard_velocity(
    def _validate_invariant_status(
    def _calculate_shannon_entropy(self, deltas: np.ndarray) -> float:
    def _calculate_skewness(self, data: np.ndarray) -> float:
``

## File: .\app\risk\unified_risk.py
``python
from __future__ import annotations
import logging
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation, ROUND_DOWN, getcontext
from enum import Enum, IntEnum, unique
from typing import Any, Dict, List, Optional, Sequence, Tuple
from app.models.enums import RiskMode, RegimeType
from app.models.contracts import DivergenceBlock, StaleDataBlock
from app.risk.kill_switch import KillSwitch
def _d(value: Any, *, field_name: str) -> Decimal:
def _ensure_unit_interval(value: Decimal, field_name: str) -> Decimal:
def _quantize_ratio(value: Decimal) -> Decimal:
def _enum_value(x: Any) -> str:
def _min_nonzero(a: int, b: int) -> int:
class UnifiedRiskDecision(str, Enum):
class UnifiedRiskResult:
    def __post_init__(self):
    def to_dict(self) -> Dict[str, Any]:
class UnifiedRiskDirective(str, Enum):
class UnifiedRiskScope(str, Enum):
class UnifiedRiskFactor(str, Enum):
class UnifiedRiskReasonCode(str, Enum):
class EvaluationCompleteness(str, Enum):
class SourceHealth(str, Enum):
class RiskOverrideAction(str, Enum):
class RiskTransitionType(str, Enum):
class UnifiedRiskPrecedence(IntEnum):
class UnifiedRiskPolicyConfig:
    def __post_init__(self) -> None:
class UnifiedRiskSourceStatus:
class UnifiedExposureContext:
    def __post_init__(self) -> None:
class UnifiedSleeveContext:
    def __post_init__(self) -> None:
class UnifiedRecoveryContext:
class UnifiedSystemHealthContext:
class UnifiedRiskOverride:
    def is_active(self, timestamp_ns: int) -> bool:
class UnifiedRiskContext:
    def __post_init__(self) -> None:
class UnifiedRiskEvidence:
class CanonicalUnifiedRiskResult:
    def __post_init__(self) -> None:
    def to_dict(self) -> Dict[str, Any]:
class UnifiedRiskScopeDecision:
class SovereignRiskConstitutionResult:
class UnifiedRiskDecisionRecord:
class UnifiedRiskAuthority:
    def __init__(
    def evaluate(
    def evaluate_for_symbol(
    def quick_check(
    def evaluate_constitution(
    def decision_journal(self, limit: Optional[int] = None) -> List[UnifiedRiskDecisionRecord]:
    def _evaluate_single_scope(
    def _select_legacy_projection_result(
    def _collect_degraded_sources(self, context: UnifiedRiskContext) -> List[SourceHealth]:
    def _is_crisis_regime(self, regime: RegimeType) -> bool:
    def _apply_override(
    def _apply_hysteresis_confidence(
    def _derive_transition_type(self, result: CanonicalUnifiedRiskResult) -> RiskTransitionType:
    def _finalize(
def create_unified_risk_authority(
``

## File: .\app\risk\__init__.py
``python
``

## File: .\app\state\hydration_manager.py
``python
import hashlib
import json
import logging
import time
import numpy as np
from typing import Dict, List, Optional, Any, Callable, Tuple
from dataclasses import dataclass, field
from pathlib import Path
import pickle
from app.state.state_store import StateStore
from app.execution.shared_memory import SharedMemoryContext, SharedMemoryManager
from app.models.unified_market import UnifiedMarketData, now_ns, MacroRegime
class BinarySnapshot:
class HydratableModule:
    def get_binary_snapshot(self) -> bytes:
    def hydrate_from_binary(self, data: bytes) -> None:
class HydrationManager:
    def __init__(
    def register_module(self, name: str, module: HydratableModule) -> None:
    def unregister_module(self, name: str) -> None:
    def _compute_checksum(self, data: bytes) -> str:
    def _collect_module_binary_states(self) -> Dict[str, bytes]:
    def _capture_shared_memory_buffer(self) -> bytes:
    def _capture_unified_market_buffer(self) -> bytes:
    def create_snapshot(self, timestamp_ns: int) -> BinarySnapshot:
    def create_snapshot_if_needed(self, timestamp_ns: int) -> Optional[BinarySnapshot]:
    def _verify_checksum(self, snapshot: BinarySnapshot) -> bool:
    def _restore_shared_memory_from_binary(self, buffer: bytes) -> bool:
    def _restore_unified_market_from_binary(self, buffer: bytes) -> bool:
    def _restore_modules_from_binary(self, module_data: Dict[str, bytes]) -> bool:
    def recover_from_wal(self) -> Tuple[bool, Optional[BinarySnapshot]]:
    def emergency_snapshot(self, reason: str) -> Optional[BinarySnapshot]:
    def validate_state_integrity(self) -> Tuple[bool, List[str]]:
    def get_stats(self) -> Dict[str, Any]:
class HydratableMixin:
    def __init__(self, hydration_manager: HydrationManager, name: str):
    def __del__(self):
    def get_binary_snapshot(self) -> bytes:
    def hydrate_from_binary(self, data: bytes) -> None:
def create_hydration_manager(
``

## File: .\app\state\invariant_checker.py
``python
import logging
from typing import Optional, Dict, List, Any, Tuple, Deque
from dataclasses import dataclass, field
from collections import deque
from app.models.contracts import TruthFrame, PortfolioTruth, RiskTruth
from app.models.enums import (
from app.models.invariants import (
from app.utils.time_utils import now_ns
class InvariantCheckerError(Exception):
def _safe_str(value: Any) -> str:
class ViolationTracker:
    def add_violation(self, event: InvariantViolationEvent) -> None:
    def clear(self) -> None:
class InvariantChecker:
    def __init__(self):
    def evaluate(self, truth_frame: TruthFrame) -> InvariantBatchCheckResult:
    def _evaluate_normal_invariant(
    def _check_truth_status_per_action(self, truth_frame: TruthFrame) -> Tuple[bool, str]:
    def _check_risk_approval_required(self, truth_frame: TruthFrame) -> Tuple[bool, str]:
    def _check_fill_idempotence(self, truth_frame: TruthFrame) -> Tuple[bool, str]:
    def _check_no_conflicting_order_intents(self, truth_frame: TruthFrame) -> Tuple[bool, str]:
    def _check_portfolio_equity_consistency(self, truth_frame: TruthFrame) -> Tuple[bool, str]:
    def _check_no_stale_market_data(self, truth_frame: TruthFrame) -> Tuple[bool, str]:
    def _check_monotonic_timestamps(self, truth_frame: TruthFrame) -> Tuple[bool, str]:
    def _check_decimal_precision(self, truth_frame: TruthFrame) -> Tuple[bool, str]:
    def _check_unique_decision_uuid(self, truth_frame: TruthFrame) -> Tuple[bool, str]:
    def _evaluate_kill_switch_invariant(
    def _check_truth_divergence_duration(
    def _check_unmatched_fill_count(
    def _check_repeated_rejections(
    def _check_clock_skew(
    def _check_stale_market_data(
    def _check_portfolio_reconciliation_mismatch(
    def _check_duplicate_sequence_detection(
    def _check_wal_corruption(
    def _check_recovery_checksum_failure(
    def _check_hard_flat_override(
    def _get_tracker(self, invariant_id: str) -> ViolationTracker:
    def _track_violation(self, invariant_id: str, violation: InvariantViolationEvent) -> None:
    def _cleanup_history(self, current_ns: int) -> None:
    def reset(self) -> None:
def create_invariant_checker() -> InvariantChecker:
``

## File: .\app\state\state_store.py
``python
import sqlite3
import json
import threading
import logging
import shutil
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple
from contextlib import contextmanager
from pathlib import Path
from app.constants import DB_WAL_AUTOCHECKPOINT, DB_TIMEOUT_SECONDS, DB_JOURNAL_MODE, DB_SYNC_MODE
class StateStore:
    def __init__(self, db_path: str):
    def _get_connection(self):
    def _init_database(self):
    def integrity_check(self) -> bool:
    def backup(self, backup_path: Optional[str] = None) -> bool:
    def _recover_uncommitted(self):
    def atomic_insert(self, table: str, data: Dict[str, Any]) -> bool:
    def begin_transaction(self, tx_id: str, intent: Dict[str, Any]) -> bool:
    def commit_transaction(self, tx_id: str, result: Dict[str, Any]) -> bool:
    def rollback_transaction(self, tx_id: str, error: str) -> bool:
    def insert_position(self, position: Dict[str, Any]) -> bool:
    def update_position(self, position_id: str, updates: Dict[str, Any]) -> bool:
    def delete_position(self, position_id: str) -> bool:
    def get_positions(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
    def insert_order(self, order: Dict[str, Any]) -> bool:
    def update_order(self, order_id: str, updates: Dict[str, Any]) -> bool:
    def insert_fill(self, fill: Dict[str, Any]) -> bool:
    def save_strategy_state(
    def get_last_strategy_state(self, strategy: str, symbol: str) -> Optional[Dict[str, Any]]:
    def save_portfolio_snapshot(self, snapshot: Dict[str, Any]) -> bool:
    def save_risk_snapshot(self, snapshot: Dict[str, Any]) -> bool:
    def save_physical_verification(self, verification: Dict[str, Any]) -> bool:
    def log_event(self, event_type: str, source: str, data: Dict[str, Any]) -> bool:
    def get_control_state(self, key: str) -> Optional[str]:
    def set_control_state(self, key: str, value: str) -> bool:
    def checkpoint(self) -> bool:
    def vacuum(self) -> bool:
    def close(self):
``

## File: .\app\state\__init__.py
``python
``

## File: .\app\strategies\adaptive_dc.py
``python
from __future__ import annotations
import logging
import time
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from enum import Enum, unique
from typing import Any, Dict, List, Optional
from app.utils.enums import (
from app.utils.ids import generate_correlation_id, generate_event_id, generate_signal_id
def _d(value: Any, *, field_name: str) -> Decimal:
def _ensure_positive(value: Decimal, field_name: str) -> Decimal:
def _ensure_non_negative(value: Decimal, field_name: str) -> Decimal:
def _clamp(value: Decimal, lower: Decimal, upper: Decimal) -> Decimal:
def _now_ms() -> int:
class DCDirection(str, Enum):
class DCPhase(str, Enum):
class DCEventType(str, Enum):
class DCSignalQuality(str, Enum):
class DCPolicyConfig:
    def __post_init__(self) -> None:
class DCMarketTick:
    def __post_init__(self) -> None:
class DCRiskContext:
class ThetaUpdate:
class DCEngineState:
class DCEvent:
class DCSignalAssessment:
class DCSignalRecommendation:
    def to_legacy_order_side(self) -> Optional[OrderSide]:
class AdaptiveDC:
    def __init__(self, initial_theta: Decimal = Decimal("0.005")) -> None:
    def snapshot_state(self) -> DCEngineState:
    def restore_state(self, state: DCEngineState) -> None:
    def update_theta(self, volatility_score: float) -> None:
    def apply_theta_update(self, raw_volatility_score: Decimal) -> ThetaUpdate:
    def process_tick(
    def detect_event(self, tick: DCMarketTick) -> Optional[DCEvent]:
    def assess_event(
    def recommend(
    def on_tick(self, price: Decimal, ts_ns: int) -> Optional[OrderSide]:
    def _validate_tick_ordering(self, tick: DCMarketTick) -> None:
    def _suppressed_event(
    def _score_confidence(
    def _classify_quality(self, confidence: Decimal) -> DCSignalQuality:
    def _classify_priority(
    def _risk_suppress_reason(
    def _is_cooldown_active(self, now_ms: int) -> bool:
``

## File: .\app\strategies\gamma_front.py
``python
import logging
from decimal import Decimal
from typing import Any, Dict, Optional
from app.models import DarkPoolPrint, OptionsFlow, StrategySignal
from app.brain.toxicity_engine import ToxicityAlert, ToxicityRegime
from app.brain.sentiment_velocity import MacroSignal
from app.brain.rolling_stats import RollingStats
from app.constants import SleeveType, DARK_POOL_TTL_SECONDS
class GammaFrontStrategy:
    def __init__(self, config: Any, symbol: str) -> None:
    def update_macro_state(self, macro_signal: Optional[MacroSignal]) -> None:
    def update_toxicity(self, toxicity_alert: Optional[ToxicityAlert]) -> None:
    def update_options_flow(self, flow: Optional[OptionsFlow]) -> Optional[StrategySignal]:
    def update_dark_pool(self, dp: DarkPoolPrint) -> Optional[StrategySignal]:
    def _generate_entry_signal(
    def update_price(self, price: float, timestamp_ns: int) -> Optional[StrategySignal]:
    def _evaluate_stale_position_ttl(
    def _generate_exit_signal(
    def _generate_stale_cleanup_signal(
    def _compute_confidence(self, dp: DarkPoolPrint, print_ratio: float) -> float:
    def _options_confirms_direction(self, direction: str, current_ts_ns: int) -> bool:
    def _calculate_provisional_risk_fraction(self, confidence: float) -> float:
    def get_performance(self) -> Dict[str, Any]:
    def reset(self) -> None:
``

## File: .\app\strategies\hedging_flow.py
``python
from __future__ import annotations
import logging
import time
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation, ROUND_DOWN
from typing import Any, Dict, List, Optional, Sequence
from app.utils.enums import (
from app.utils.ids import generate_correlation_id, generate_request_id
def _d(value: Any, *, field_name: str) -> Decimal:
def _ensure_non_negative(value: Decimal, field_name: str) -> Decimal:
def _ensure_positive(value: Decimal, field_name: str) -> Decimal:
def _clamp(value: Decimal, lower: Decimal, upper: Decimal) -> Decimal:
def _quantize_down(value: Decimal, step: Decimal) -> Decimal:
def _now_ms() -> int:
def _safe_str(obj: Any) -> str:
class HedgePolicyConfig:
    def __post_init__(self) -> None:
class HedgeMarketContext:
    def __post_init__(self) -> None:
class HedgeRiskContext:
class PortfolioExposureSnapshot:
    def __post_init__(self) -> None:
class HedgeUrgencyProfile:
class HedgeAssessment:
class HedgeRecommendation:
    def to_legacy_dict(self) -> Dict[str, Any]:
class HedgingFlow:
    def __init__(
    def assess(
    def recommend(
    def evaluate_hedging_need(
    def _blocked_assessment(
    def _is_cooldown_active(self, now_ms: int, urgency: str) -> bool:
    def _is_risk_blocked(self, risk: HedgeRiskContext) -> bool:
    def _risk_block_reason(self, risk: HedgeRiskContext) -> str:
    def _classify_urgency(
    def _profile_from_assessment(
``

## File: .\app\strategies\liquidity_void.py
``python
IMPORT CORRECTIONS (verified from repo this session):
import logging
import numpy as np
from typing import Optional, Dict, Any
from app.models import OrderBookSnapshot, StrategySignal
from app.brain.toxicity_engine import ToxicityAlert, ToxicityRegime
from app.brain.sentiment_velocity import MacroSignal
from app.brain.topological_engine import TopologicalSignal
from app.constants import SleeveType, LiquidityVoidStatus
class LiquidityVoidStrategy:
    def __init__(self, config: Any, symbol: str):
    def update_macro_state(self, macro_signal: Optional[MacroSignal]) -> None:
    def update_toxicity(self, toxicity_alert: Optional[ToxicityAlert]) -> None:
    def update_topology(self, topology: Optional[TopologicalSignal]) -> None:
    def update_order_book(self, order_book: OrderBookSnapshot) -> Optional[StrategySignal]:
    def _should_enter(self, order_book: OrderBookSnapshot) -> bool:
    def _should_exit(self, order_book: OrderBookSnapshot) -> bool:
    def _generate_entry_signal(self, order_book: OrderBookSnapshot) -> StrategySignal:
    def _generate_exit_signal(
    def _force_exit(self) -> None:
    def _calculate_position_size(self, price: float) -> float:
    def get_performance(self) -> Dict[str, Any]:
    def reset(self) -> None:
``

## File: .\app\strategies\sector_rotation.py
``python
import logging
from typing import Any, Dict, Optional
from app.models import StrategySignal
from app.brain.toxicity_engine import ToxicityAlert, ToxicityRegime
from app.brain.sentiment_velocity import MacroSignal
from app.brain.rolling_stats import RollingStats
from app.constants import SleeveType
class SectorRotationStrategy:
    def __init__(self, config: Any, symbol: str) -> None:
    def update_macro_state(self, macro_signal: Optional[MacroSignal]) -> None:
    def update_toxicity(self, toxicity_alert: Optional[ToxicityAlert]) -> None:
    def update_candle(
    def _generate_entry_signal(
    def update_price(self, price: float, timestamp_ns: int) -> Optional[StrategySignal]:
    def _generate_exit_signal(
    def _compute_confidence(self, volume_zscore: float) -> float:
    def _calculate_position_size(self, price: float, confidence: float) -> float:
    def get_performance(self) -> Dict[str, Any]:
    def reset(self) -> None:
``

## File: .\app\strategies\shadow_front.py
``python
import logging
from typing import Optional, Dict, Any
from app.models import StrategySignal, WhaleFlowScore
from app.constants import SleeveType
from app.models.enums import RegimeType
from app.brain.toxicity_engine import ToxicityAlert, ToxicityRegime
from app.brain.sentiment_velocity import MacroSignal
from app.brain.insider_signal_engine import InsiderSignalSnapshot
from app.brain.whale_zone_engine import WhalePresenceZone
class ShadowFrontStrategy:
    def __init__(self, config: Any, symbol: str):
    def update_macro_state(self, macro_signal: Optional[MacroSignal]) -> None:
    def update_insider_state(self, insider_snapshot: Optional[InsiderSignalSnapshot]) -> None:
    def update_toxicity_state(self, toxicity_alert: Optional[ToxicityAlert]) -> None:
    def update_whale(self, whale_score: WhaleFlowScore) -> None:
    def update_whale_zone(self, zone: Optional[WhalePresenceZone]) -> None:
    def update_sentiment(self, sentiment_velocity: float, timestamp_ns: int) -> None:
    def update_price(
    def _check_entry_conditions(
    def _check_exit_conditions(
    def _generate_entry_signal(
    def _generate_exit_signal(
    def _calculate_base_confidence(self) -> float:
    def _calculate_position_size(
    def _reset_position(self) -> None:
    def get_performance(self) -> Dict[str, Any]:
    def is_in_position(self) -> bool:
    def get_entry_price(self) -> Optional[float]:
    def get_position_size(self) -> float:
    def reset(self) -> None:
``

## File: .\app\strategies\strategy_router.py
``python
import logging
from collections import deque
from typing import Any, Dict, List, Optional, Set, Tuple
from app.constants import ControlMode, SleeveType
from app.models.fusion import FusionDecision
class StrategyRouter:
    def __init__(
    def update_macro_state(self) -> None:
    def get_eligible_strategies(self, fusion: FusionDecision) -> List[SleeveType]:
    def get_preferred_strategy(self, fusion: FusionDecision) -> Optional[SleeveType]:
    def _collect_fusion_eligible(self, fusion: FusionDecision) -> List[SleeveType]:
    def _filter_by_control_mode(self, strategies: List[SleeveType]) -> List[SleeveType]:
    def _topological_sort(self, candidates: List[SleeveType]) -> List[SleeveType]:
    def _apply_dependency_constraints(
    def _detect_cycle(self) -> Optional[List[str]]:
        def dfs(node: SleeveType) -> Optional[List[str]]:
    def _apply_correlation_constraints(
    def _resolve_correlated_suppression(
``

## File: .\app\strategies\__init__.py
``python
``

## File: .\app\utils\decimal_utils.py
``python
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from typing import Union, Optional
import warnings
import math
def _to_decimal(value: Union[Decimal, int, str]) -> Decimal:
def decimal_from_float(value: float, context: str = "") -> Decimal:
def crypto(amount: Union[Decimal, int, str]) -> Decimal:
def usd(amount: Union[Decimal, int, str]) -> Decimal:
def price(amount: Union[Decimal, int, str]) -> Decimal:
def fee(amount: Union[Decimal, int, str]) -> Decimal:
def confidence(score: Union[Decimal, int, str]) -> Decimal:
def percent(pct: Union[Decimal, int, str]) -> Decimal:
def bps(basis_points: Union[Decimal, int, str]) -> Decimal:
def bps_to_percent(basis_points: Union[Decimal, int, str]) -> Decimal:
def percent_to_bps(percentage: Union[Decimal, int, str]) -> Decimal:
def safe_add(
def safe_subtract(
def safe_multiply(
def safe_divide(
def zero(precision: Decimal) -> Decimal:
def is_zero(
def to_canonical_string(value: Decimal, precision: Decimal) -> str:
def to_display_string(value: Decimal, precision: Optional[Decimal] = None) -> str:
``

## File: .\app\utils\enums.py
``python
from __future__ import annotations
from typing import Final, FrozenSet
from app.models.enums import (  # noqa: F401
def is_terminal_order_status(status: OrderStatus) -> bool:
def is_active_order_status(status: OrderStatus) -> bool:
def is_fill_eligible_order_status(status: OrderStatus) -> bool:
def is_cancelable_order_status(status: OrderStatus) -> bool:
def is_replaceable_order_status(status: OrderStatus) -> bool:
def is_high_risk_level(level: RiskLevel) -> bool:
def is_blocking_risk_action(action: RiskAction) -> bool:
def is_valid_order_status_transition(
``

## File: .\app\utils\ids.py
``python
from __future__ import annotations
import logging
import os
import socket
import threading
import time
import hashlib
from dataclasses import dataclass
from enum import Enum, unique
from typing import Final, Optional
class IDGenerationError(RuntimeError):
class ClockRollbackError(IDGenerationError):
class SequenceOverflowError(IDGenerationError):
class InvalidNodeIDError(IDGenerationError):
class ClockRollbackPolicy(str, Enum):
class IDComponents:
    def unix_timestamp_ms(self) -> int:
    def created_at_iso(self) -> str:
class IDGeneratorConfig:
class IDGenerator:
    def __init__(self, config: IDGeneratorConfig):
    def generate(self) -> int:
    def generate_str(self) -> str:
    def generate_event_id(self) -> int:
    def generate_signal_id(self) -> int:
    def generate_order_id(self) -> int:
    def generate_fill_id(self) -> int:
    def generate_correlation_id(self) -> int:
    def generate_request_id(self) -> int:
    def generate_client_order_id(
    def decode(self, id_value: int) -> IDComponents:
    def peek_state(self) -> dict[str, int]:
    def _now_ms(self) -> int:
    def _resolve_timestamp(self, now_ms: int) -> int:
    def _wait_for_next_ms(self, floor_ms: int) -> int:
def _stable_host_fingerprint() -> str:
def derive_node_id(
def build_default_config(*, explicit_node_id: Optional[int] = None) -> IDGeneratorConfig:
def get_id_authority() -> IDGenerator:
def configure_id_authority(config: IDGeneratorConfig) -> IDGenerator:
def reset_id_authority() -> None:
def generate_id() -> int:
def generate_string_id() -> str:
def generate_event_id() -> int:
def generate_signal_id() -> int:
def generate_order_id() -> int:
def generate_fill_id() -> int:
def generate_correlation_id() -> int:
def generate_request_id() -> int:
def generate_order_cid(
def decode_id(id_value: int) -> IDComponents:
def _to_base36(value: int) -> str:
def _sanitize_tag(
``

## File: .\app\utils\math_utils.py
``python
import numpy as np
from typing import List, Tuple, Optional, Union, Dict
from numba import jit, prange, vectorize
import math
from collections import deque
def power_law_weights(n: int, alpha: float) -> np.ndarray:
def adaptive_fractal_entropy(
def distance_matrix_limited(points: np.ndarray, max_points: int = 150) -> np.ndarray:
def betti_1_void_score(
def spectral_decomposition(
def stealth_accumulation_score(trade_signs: np.ndarray, window: int = 100) -> float:
def hawkes_intensity(
def online_hawkes_update(
def cascade_risk_score(
def lz77_complexity(sequence: np.ndarray) -> float:
def algorithmic_randomness(sequence: np.ndarray, window: int = 100) -> np.ndarray:
def adaptive_threshold(
def rolling_adaptive_threshold(
def extract_elite_features(
def rolling_volatility(data: np.ndarray, window: int = 20) -> np.ndarray:
def regime_adaptive_zscore(
def ghost_tick_detector(
def to_shared_memory_buffer(data: np.ndarray) -> np.ndarray:
def get_buffer_shape(data: np.ndarray) -> Tuple[int, ...]:
def serialize_for_shared_memory(data: np.ndarray) -> bytes:
def deserialize_from_shared_memory(buffer: bytes, shape: Tuple[int, ...]) -> np.ndarray:
def compute_fractal_entropy(sequence: List[float], window: int = 50, alpha: float = 1.5) -> List[float]:
def compute_betti_void(prices: List[float], volumes: List[float]) -> float:
def compute_stealth_accumulation(trade_signs: List[float]) -> float:
def compute_cascade_risk(event_times: List[float]) -> float:
``

## File: .\app\utils\time_utils.py
``python
import time
from typing import Optional, Tuple, Type
from types import TracebackType
def now_ns() -> int:
def set_replay_time_ns(timestamp_ns: int) -> None:
def advance_replay_time_ns(delta_ns: int) -> int:
def clear_replay_time() -> None:
def is_replay_mode() -> bool:
def seconds_to_ns(seconds: int) -> int:
def ms_to_ns(ms: int) -> int:
def us_to_ns(us: int) -> int:
def ns_to_seconds(ns: int) -> float:
def ns_to_ms(ns: int) -> float:
def ns_to_us(ns: int) -> float:
def is_monotonic(previous_ts_ns: Optional[int], current_ts_ns: int) -> Tuple[bool, str]:
def age_ns(timestamp_ns: int) -> int:
def is_stale(timestamp_ns: int, max_age_ns: int) -> Tuple[bool, str]:
class ReplayTimeContext:
    def __init__(self, timestamp_ns: int):
    def __enter__(self) -> None:
    def __exit__(
``

## File: .\app\utils\__init__.py
``python
``

## File: .\tests\test_adaptive_dc.py
``python
import pytest
from unittest.mock import Mock, AsyncMock, patch
class TestAdaptive_dc:
    def mock_config(self):
    def mock_state_store(self):
    def mock_risk_manager(self):
    def test_initialization(self, mock_config, mock_state_store, mock_risk_manager):
    def test_generate_signal(self):
    def test_risk_checks(self):
    def test_state_persistence(self):
    def test_exit_conditions(self):
    def test_position_sizing(self):
    def test_edge_cases(self):
``

## File: .\tests\test_config.py
``python
def main():
``

## File: .\tests\test_convexity_switch.py
``python
import pytest
from unittest.mock import Mock, AsyncMock, patch
class TestConvexity_switch:
    def mock_config(self):
    def mock_state_store(self):
    def mock_risk_manager(self):
    def test_initialization(self, mock_config, mock_state_store, mock_risk_manager):
    def test_generate_signal(self):
    def test_risk_checks(self):
    def test_state_persistence(self):
    def test_exit_conditions(self):
    def test_position_sizing(self):
    def test_edge_cases(self):
``

## File: .\tests\test_entropy_decoder.py
``python
import pytest
from unittest.mock import Mock, AsyncMock, patch
class TestEntropy_decoder:
    def mock_config(self):
    def mock_state_store(self):
    def mock_risk_manager(self):
    def test_initialization(self, mock_config, mock_state_store, mock_risk_manager):
    def test_generate_signal(self):
    def test_risk_checks(self):
    def test_state_persistence(self):
    def test_exit_conditions(self):
    def test_position_sizing(self):
    def test_edge_cases(self):
``

## File: .\tests\test_gamma_front.py
``python
import pytest
from unittest.mock import Mock
from app.strategies.gamma_front import GammaFrontStrategy
from app.models import DarkPoolPrint
from app.brain.toxicity_engine import ToxicityAlert, ToxicityRegime
from app.brain.sentiment_velocity import MacroSignal
def _make_config(
def _make_strategy(
def _make_dp(
def _warm_baseline(strategy: GammaFrontStrategy, n: int = 4) -> None:
def _make_big_print(ts_ns: int = 5_000_000_000, is_buy: bool = True) -> DarkPoolPrint:
def _make_toxic_alert() -> ToxicityAlert:
def _make_macro_kill() -> MacroSignal:
def _make_macro_pause() -> MacroSignal:
class TestInit:
    def test_not_in_position(self):
    def test_print_count_zero(self):
    def test_no_cooldown(self):
    def test_symbol_stored(self):
    def test_no_position_state(self):
class TestColdStartGuard:
    def test_first_four_prints_always_suppressed(self):
    def test_fifth_print_can_trigger(self):
    def test_baseline_always_updates_even_when_suppressed(self):
class TestEntryThreshold:
    def test_below_threshold_no_signal(self):
    def test_above_threshold_generates_signal(self):
    def test_disabled_no_signal_regardless_of_threshold(self):
class TestEntryOverlays:
    def test_in_position_no_second_entry(self):
    def test_macro_kill_suppresses_entry(self):
    def test_toxicity_suppresses_entry(self):
    def test_cooldown_suppresses_entry(self):
    def test_update_macro_state_none_is_noop(self):
    def test_update_toxicity_none_clears_flag(self):
    def test_toxicity_normal_regime_does_not_suppress(self):
class TestEntrySignalContract:
    def _trigger_entry(self, is_buy: bool = True):
    def test_exchange_ts_ns_matches_print(self):
    def test_side_buy_for_is_buy_true(self):
    def test_side_sell_for_is_buy_false(self):
    def test_symbol_matches(self):
    def test_quantity_positive(self):
    def test_confidence_within_governed_range(self):
    def test_entry_latches_in_position(self):
    def test_entry_latches_entry_price(self):
    def test_entry_latches_entry_ts_ns(self):
class TestExitConditions:
    def _enter(self, s: GammaFrontStrategy) -> None:
    def test_ttl_expiry_exit(self):
    def test_take_profit_exit(self):
    def test_stop_loss_exit(self):
    def test_toxicity_spike_exit(self):
    def test_macro_kill_exit(self):
    def test_no_exit_within_ttl_no_conditions(self):
    def test_exit_clears_position_state(self):
    def test_exit_signal_exchange_ts_ns_matches_tick(self):
    def test_exit_sets_cooldown(self):
    def test_update_price_not_in_position_returns_none(self):
    def test_sell_side_stop_loss(self):
class TestPerformanceAndReset:
    def test_get_performance_initial_state(self):
    def test_get_performance_after_winning_trade(self):
    def test_get_performance_after_losing_trade(self):
    def test_reset_clears_all_state(self):
``

## File: .\tests\test_hedging_flow.py
``python
import pytest
from unittest.mock import Mock, AsyncMock, patch
class TestHedging_flow:
    def mock_config(self):
    def mock_state_store(self):
    def mock_risk_manager(self):
    def test_initialization(self, mock_config, mock_state_store, mock_risk_manager):
    def test_generate_signal(self):
    def test_risk_checks(self):
    def test_state_persistence(self):
    def test_exit_conditions(self):
    def test_position_sizing(self):
    def test_edge_cases(self):
``

## File: .\tests\test_kill_switch.py
``python
def main():
``

## File: .\tests\test_liquidity_void.py
``python
def main():
``

## File: .\tests\test_models.py
``python
import pytest
from pydantic import ValidationError
from app.models.signals import StrategySignal
class TestStrategySignalTimestampContract:
    def test_valid_construction_with_ts(self):
    def test_missing_exchange_ts_ns_raises(self):
    def test_exchange_ts_sec_property(self):
    def test_zero_ts_ns_accepted(self):
    def test_negative_ts_ns_accepted(self):
``

## File: .\tests\test_paper_broker.py
``python
def main():
``

## File: .\tests\test_physical_validator.py
``python
import pytest
from unittest.mock import Mock, AsyncMock, patch
class TestPhysical_validator:
    def mock_config(self):
    def mock_state_store(self):
    def mock_risk_manager(self):
    def test_initialization(self, mock_config, mock_state_store, mock_risk_manager):
    def test_generate_signal(self):
    def test_risk_checks(self):
    def test_state_persistence(self):
    def test_exit_conditions(self):
    def test_position_sizing(self):
    def test_edge_cases(self):
``

## File: .\tests\test_position_sizing.py
``python
def main():
``

## File: .\tests\test_regime_detector.py
``python
def main():
``

## File: .\tests\test_sector_rotation.py
``python
import pytest
from unittest.mock import Mock
from app.strategies.sector_rotation import SectorRotationStrategy
from app.brain.toxicity_engine import ToxicityAlert, ToxicityRegime
from app.brain.sentiment_velocity import MacroSignal
def _make_config(
def _make_strategy(
def _warm_baseline(
def _make_big_buy(ts_ns: int = 10_000_000_000):
def _make_big_sell(ts_ns: int = 10_000_000_000):
def _make_toxic_alert() -> ToxicityAlert:
def _make_macro_kill() -> MacroSignal:
class TestInit:
    def test_not_in_position(self):
    def test_candle_count_zero(self):
    def test_prev_close_none_initially(self):
    def test_symbol_stored(self):
class TestColdStartGuard:
    def test_below_min_candles_no_signal(self):
    def test_at_min_candles_can_trigger(self):
    def test_first_candle_sets_prev_close(self):
    def test_baseline_accumulates_even_when_suppressed(self):
class TestEntryThreshold:
    def test_below_threshold_no_signal(self):
    def test_above_threshold_buy_signal(self):
    def test_above_threshold_sell_signal(self):
    def test_price_unchanged_no_directional_signal(self):
    def test_disabled_no_signal_regardless_of_volume(self):
class TestEntryOverlays:
    def test_in_position_no_second_entry(self):
    def test_macro_kill_suppresses_entry(self):
    def test_toxicity_suppresses_entry(self):
    def test_cooldown_suppresses_entry(self):
    def test_update_macro_state_none_is_noop(self):
    def test_update_toxicity_none_clears_flag(self):
class TestEntrySignalContract:
    def _trigger_buy(self):
    def test_exchange_ts_ns_explicit(self):
    def test_symbol_matches(self):
    def test_quantity_positive(self):
    def test_confidence_within_governed_range(self):
    def test_buy_side(self):
    def test_entry_latches_in_position(self):
    def test_entry_price_latched(self):
    def test_entry_ts_ns_latched(self):
class TestExitConditions:
    def _enter(self, s: SectorRotationStrategy) -> None:
    def test_ttl_expiry_exit(self):
    def test_take_profit_exit(self):
    def test_stop_loss_exit(self):
    def test_toxicity_spike_exit(self):
    def test_macro_kill_exit(self):
    def test_no_exit_within_ttl_no_conditions(self):
    def test_exit_clears_position_state(self):
    def test_exit_signal_exchange_ts_ns_matches_tick(self):
    def test_exit_sets_cooldown(self):
    def test_update_price_not_in_position_returns_none(self):
    def test_sell_side_stop_loss(self):
class TestPerformanceAndReset:
    def test_get_performance_initial(self):
    def test_get_performance_after_winning_trade(self):
    def test_get_performance_after_losing_trade(self):
    def test_reset_clears_all_state(self):
``

## File: .\tests\test_shadow_front_state.py
``python
def main():
``

## File: .\tests\test_signal_fusion.py
``python
def main():
``

## File: .\tests\test_state_store.py
``python
def main():
``

## File: .\tests\test_strategy_router.py
``python
import pytest
from unittest.mock import Mock
from app.strategies.strategy_router import StrategyRouter
from app.models.fusion import FusionDecision
from app.constants import SleeveType, ControlMode
def _make_config(mode: str = ControlMode.NORMAL.value) -> Mock:
def _make_safety_gate(macro_kill: bool = False) -> Mock:
def _make_router(
def _make_fusion(
class TestInit:
    def test_default_construction(self):
    def test_cycle_detection_raises(self):
    def test_acyclic_dependency_graph_ok(self):
class TestMacroKill:
    def test_macro_kill_returns_empty(self):
    def test_macro_kill_preferred_returns_none(self):
    def test_update_macro_state_reads_live_from_gate(self):
class TestFusionEligibility:
    def test_gamma_front_eligible(self):
    def test_sector_rotation_eligible(self):
    def test_all_five_eligible_order_matches_fusion_declaration(self):
    def test_none_eligible_returns_empty(self):
    def test_only_shadow_front_eligible(self):
    def test_only_flv_eligible(self):
class TestControlModeFilter:
    def test_safe_mode_only_shadow_front(self):
    def test_safe_mode_shadow_not_eligible_returns_empty(self):
    def test_crisis_opportunistic_only_flv(self):
    def test_capital_secure_returns_empty(self):
    def test_normal_mode_passes_through_all_eligible(self):
class TestDependencyConstraints:
    def test_empty_deps_preserves_input_order(self):
    def test_met_dependency_both_pass(self):
    def test_dependency_ordering_enforced(self):
    def test_dep_not_in_eligible_set_treated_as_no_in_scope_dep(self):
class TestCorrelatedPairSuppression:
    def test_rule1_preferred_sleeve_kept(self):
    def test_rule1_other_preferred_kept(self):
    def test_rule2_deprioritized_suppressed(self):
    def test_rule3_routing_order_earlier_survives(self):
    def test_single_eligible_skips_suppression(self):
    def test_no_corr_pairs_passthrough(self):
    def test_pair_not_both_eligible_no_suppression(self):
class TestGetPreferredStrategy:
    def test_preferred_sleeve_returned_when_eligible(self):
    def test_preferred_sleeve_not_eligible_uses_fallback(self):
    def test_fallback_priority_flv_over_others(self):
    def test_fallback_priority_shadow_front_over_new_sleeves(self):
    def test_fallback_first_eligible_when_no_priority_match(self):
    def test_empty_eligible_returns_none(self):
    def test_macro_kill_preferred_returns_none(self):
``

## File: .\tests\__init__.py
``python
``


