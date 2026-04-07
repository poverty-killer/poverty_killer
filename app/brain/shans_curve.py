"""
app/brain/shans_curve.py

Shan's Curve Engine - Asymptotic Liquidity Exhaustion Detector.
Hybrid rebuild: live intelligence (topological persistence, denoising, fill calibration)
+ doctrinal purity (OFI-centered asymptote, three-field separation).

Role: Pure alpha generator. NOT a direction engine.
Risk/safety gating is NOT performed here — delegated to caller (fusion/strategy router).
"""

import logging
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Deque, Dict, List, Optional, Tuple, Union

import numpy as np
import numba

from app.brain.ring_buffer import RingBuffer
from app.brain.data_validator import DataContinuityValidator
from app.risk.guard import HybridRiskGuard
from app.risk.safety import SafetyGate
from app.brain.entropy_decoder import EntropyDecoder

logger = logging.getLogger(__name__)

EPS = np.finfo(float).eps


# =============================================================================
# FILE-LOCAL SIGNAL CONTRACT
# =============================================================================
# This is the output contract of this file. It is not claimed to be the
# authoritative package-wide contract. Callers must consume these fields.

@dataclass
class ShansCurveSignal:
    """
    Signal contract for Shan's Curve output.
    
    Doctrinal fields (operational, strictly separated):
    - shans_superfluid_score: exhaustion / asymptote proximity [0,1]
    - shans_bias: directional sign [-1,0,1]
    - shans_confidence: support / structural density [0,1]
    
    Legacy compatibility bridge:
    - predicted_action: derived from shans_bias, preserved as int (-1/0/1)
      for downstream consumers that expect this field.
    """
    symbol: str
    timestamp_ns: int
    
    # Doctrinal fields
    shans_superfluid_score: float
    shans_bias: int
    shans_confidence: float
    
    # Traceability
    fit_r_squared: float
    inflection_distance: float
    decision_uuid: str = field(default_factory=lambda: str(uuid.uuid4()))
    
    # Legacy compatibility bridge (partial semantic preservation)
    predicted_action: int = 0
    
    def __post_init__(self):
        """Derive legacy field from doctrinal bias."""
        self.predicted_action = self.shans_bias


# =============================================================================
# DETERMINISTIC MATHEMATICAL CORE (NUMBA JIT)
# =============================================================================

@numba.njit(fastmath=True, cache=True)
def solve_asymptotic_kinematics(
    p: np.ndarray,
    ofi: np.ndarray,
    v: np.ndarray,
    reg_lambda: float = 1e-5
) -> Tuple[float, float, float, float, float]:
    """
    Solves limit order book exhaustion manifold via rational function approximation.
    
    Returns:
        r_squared: fit quality [0,1]
        slope: instantaneous directional derivative
        asymptote_proximity: normalized distance to singularity [0,1]
        support_density: volume concentration [0,1]
        delta_ofi: instantaneous OFI change
    """
    n = p.shape[0]
    if n < 5:
        return 0.0, 0.0, 0.0, 0.0, 0.0
    
    # Z-score normalization (scale invariance)
    p_mean, p_std = np.mean(p), np.std(p) + 1e-8
    ofi_mean, ofi_std = np.mean(ofi), np.std(ofi) + 1e-8
    v_mean, v_std = np.mean(v), np.std(v) + 1e-8
    
    p_n = (p - p_mean) / p_std
    ofi_n = (ofi - ofi_mean) / ofi_std
    v_n = (v - v_mean) / v_std
    
    # Linearized rational function: P*OFI = b0 + b1*P + b2*OFI + b3*V
    target = p_n * ofi_n
    A = np.zeros((n, 4), dtype=np.float64)
    A[:, 0] = p_n
    A[:, 1] = ofi_n
    A[:, 2] = v_n
    A[:, 3] = 1.0
    
    # Ridge regression
    ATA = A.T @ A
    ATy = A.T @ target
    for j in range(4):
        ATA[j, j] += reg_lambda
    coeffs = np.linalg.solve(ATA, ATy)
    b1, b2, b3, b0 = coeffs[0], coeffs[1], coeffs[2], coeffs[3]
    
    # Kinematics at leading edge
    ofi_last = ofi_n[-1]
    denominator = ofi_last - b1
    if abs(denominator) < 1e-5:
        slope = np.sign(b2) * 999.0
        distance_to_asymptote = 0.0
    else:
        numerator_c = b3 * v_n[-1] + b0
        slope = -(b1 * b2 + numerator_c) / (denominator**2 + 1e-8)
        distance_to_asymptote = abs(denominator)
    
    delta_ofi = ofi_n[-1] - ofi_n[-2] if n >= 2 else 0.0
    asymptote_proximity = np.exp(-distance_to_asymptote)
    
    # R-squared
    p_pred = (b2 * ofi_n + b3 * v_n + b0) / ((ofi_n - b1) + 1e-8)
    ss_res = np.sum((p_n - p_pred)**2)
    ss_tot = np.sum((p_n - np.mean(p_n))**2)
    r_squared = max(0.0, 1.0 - (ss_res / (ss_tot + 1e-12)))
    
    # Support density
    v_ratio = v[-1] / (np.mean(v) + 1e-8)
    support_density = min(1.0, v_ratio)
    
    return r_squared, slope, asymptote_proximity, support_density, delta_ofi


# =============================================================================
# TOPOLOGICAL PERSISTENCE (BETTI-1) - REDESIGNED (substance preserved)
# =============================================================================

@numba.njit(cache=True)
def _betti_1_persistence(points: np.ndarray, threshold: float = 0.01) -> float:
    """
    Simplified Betti-1 topological persistence.
    Substance preserved (persistence measure), implementation redesigned for Numba.
    """
    n = len(points)
    if n < 4:
        return 0.0
    persistence = 0.0
    for i in range(n - 2):
        for j in range(i + 1, n - 1):
            d = abs(points[i] - points[j])
            if d > threshold:
                persistence += min(1.0, d / threshold)
    return min(1.0, persistence / (n * (n - 1) / 2))


# =============================================================================
# ADAPTIVE DENOISING (SAVITZKY-GOLAY) - REDESIGNED (substance preserved)
# =============================================================================

@numba.njit(cache=True)
def _savitzky_golay(y: np.ndarray, window_size: int, poly_order: int) -> np.ndarray:
    """Savitzky-Golay filter. Substance preserved, implementation redesigned."""
    if len(y) < window_size:
        return y.copy()
    half_window = window_size // 2
    result = np.zeros_like(y)
    x = np.arange(-half_window, half_window + 1, dtype=np.float64)
    A = np.zeros((window_size, poly_order + 1))
    for i in range(poly_order + 1):
        A[:, i] = x**i
    try:
        pinv = np.linalg.pinv(A)
    except np.linalg.LinAlgError:
        return y.copy()
    for i in range(half_window, len(y) - half_window):
        window = y[i - half_window:i + half_window + 1]
        coeffs = pinv @ window
        result[i] = coeffs[0]
    result[:half_window] = y[:half_window]
    result[-half_window:] = y[-half_window:]
    return result


# =============================================================================
# ENGINE CLASS
# =============================================================================

class ShansCurve:
    """
    Shan's Curve Engine - Asymptotic Liquidity Exhaustion Detector.
    
    Ownership notes:
    - risk_guard and safety_gate are injected for interface continuity only.
      This engine does NOT perform risk/safety gating. Caller's responsibility.
    - Topological persistence and denoising are redesigned but preserve substance.
    - Fill calibration via record_fill() affects confidence (shadow air-gap).
    """
    
    def __init__(
        self,
        risk_guard: HybridRiskGuard,
        safety_gate: SafetyGate,
        data_validator: DataContinuityValidator,
        entropy_decoder: EntropyDecoder,
        curvature_window: int = 60,
        min_volatility: float = 1e-6,
        enable_topological: bool = True,
        enable_denoising: bool = True,
    ):
        # Interface continuity only — not used for gating in this file
        self.risk_guard = risk_guard
        self.safety_gate = safety_gate
        self.data_validator = data_validator
        self.entropy_decoder = entropy_decoder
        
        self.curvature_window = curvature_window
        self.min_volatility = min_volatility
        self.enable_topological = enable_topological
        self.enable_denoising = enable_denoising
        
        self._p = RingBuffer(max_size=1000)
        self._ofi = RingBuffer(max_size=1000)
        self._v = RingBuffer(max_size=1000)
        
        # Fill calibration (preserved from live file)
        self._fill_history: Deque[Dict[str, Any]] = deque(maxlen=100)
        self._shadow_air_gap: float = 0.0
        
        logger.info("ShansCurve initialized: hybrid mode")
    
    @staticmethod
    def _to_nanoseconds(ts: Union[int, datetime]) -> int:
        """
        Integer-safe nanosecond conversion. No float multiplication or timestamp().
        
        For datetime: computes total nanoseconds since epoch using integer arithmetic
        from datetime components. For int: returns as-is.
        """
        if isinstance(ts, int):
            return ts
        
        # Convert to UTC if naive
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        
        # Integer arithmetic: days -> seconds -> nanoseconds
        epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
        delta = ts - epoch
        
        total_ns = delta.days * 86_400 * 1_000_000_000
        total_ns += delta.seconds * 1_000_000_000
        total_ns += delta.microseconds * 1_000
        
        return total_ns
    
    @staticmethod
    def _datetime_from_ns(ns: int) -> datetime:
        """
        Reconstruct datetime from integer nanoseconds without float division.
        Used only for validator compatibility.
        """
        seconds = ns // 1_000_000_000
        microseconds = (ns % 1_000_000_000) // 1_000
        return datetime.fromtimestamp(seconds, tz=timezone.utc).replace(microsecond=microseconds)
    
    def _compute_topological_persistence(self, p_arr: np.ndarray, ofi_arr: np.ndarray) -> float:
        """Betti-1 persistence from price-OFI manifold."""
        if not self.enable_topological:
            return 0.0
        p_persist = _betti_1_persistence(p_arr, threshold=0.01)
        ofi_persist = _betti_1_persistence(ofi_arr, threshold=0.01)
        return (p_persist + ofi_persist) / 2.0
    
    def _apply_denoising(self, arr: np.ndarray) -> np.ndarray:
        """Savitzky-Golay denoising if enabled."""
        if not self.enable_denoising or len(arr) < 7:
            return arr
        window = min(7, len(arr) - (len(arr) % 2) + 1)
        if window % 2 == 0:
            window -= 1
        if window < 3:
            return arr
        return _savitzky_golay(arr, window_size=window, poly_order=2)
    
    def record_fill(self, symbol: str, fill_price: float, fill_size: float, timestamp_ns: int) -> None:
        """Record execution fill for shadow air-gap calibration."""
        self._fill_history.append({
            "symbol": symbol,
            "fill_price": fill_price,
            "fill_size": fill_size,
            "timestamp_ns": timestamp_ns,
        })
        if len(self._fill_history) >= 10:
            recent_sizes = [f["fill_size"] for f in list(self._fill_history)[-10:]]
            avg_size = np.mean(recent_sizes)
            self._shadow_air_gap = min(1.0, avg_size / 1000.0)
    
    def update_order_book(
        self,
        symbol: str,
        mid_price: float,
        cum_bid_vol: float,
        cum_ask_vol: float,
        depth_velocity: float,  # Kept for interface continuity; not used in current implementation
        timestamp: Union[int, datetime],
        sequence_id: Optional[int] = None,
        regime_id: Optional[str] = None,  # Kept for interface continuity; not used in current implementation
    ) -> Optional[ShansCurveSignal]:
        """
        Process L2/L3 data, emit doctrinal signal.
        No risk/safety gating applied here.
        
        Note: depth_velocity and regime_id are accepted for API continuity
        with callers but are not currently used in computations.
        """
        ts_ns = self._to_nanoseconds(timestamp)
        
        # Data validation - reconstruct datetime from integer nanoseconds
        dt_for_val = self._datetime_from_ns(ts_ns)
        is_healthy, _ = self.data_validator.validate(
            symbol=symbol, timestamp=dt_for_val, sequence_id=sequence_id
        )
        if not is_healthy:
            return None
        
        # State update
        ofi = cum_bid_vol - cum_ask_vol
        tot_vol = cum_bid_vol + cum_ask_vol
        self._p.append(mid_price)
        self._ofi.append(ofi)
        self._v.append(tot_vol)
        
        if len(self._p) < self.curvature_window:
            return None
        
        # Extract and denoise
        p_raw = self._p.get_window(self.curvature_window)
        ofi_raw = self._ofi.get_window(self.curvature_window)
        v_raw = self._v.get_window(self.curvature_window)
        p_arr = self._apply_denoising(p_raw)
        ofi_arr = self._apply_denoising(ofi_raw)
        v_arr = v_raw
        
        # Degeneracy guard
        if np.std(p_arr) < self.min_volatility or np.std(ofi_arr) < self.min_volatility:
            return self._neutral_signal(symbol, ts_ns)
        
        # Asymptotic kinematics
        r2, slope, proximity, support, dx = solve_asymptotic_kinematics(p_arr, ofi_arr, v_arr)
        
        # Topological boost (redesigned but preserves substance)
        topo_score = self._compute_topological_persistence(p_arr, ofi_arr)
        
        # Doctrinal fields
        shans_superfluid_score = float(np.clip(proximity, 0.0, 1.0))
        shans_bias = int(np.sign(slope * dx)) if not np.isnan(slope * dx) else 0
        
        # Confidence: fit quality * support * entropy modulation + topological boost
        entropy_obj = self.entropy_decoder.get_current(symbol)
        ent_val = float(entropy_obj.entropy) if entropy_obj else 0.5
        ent_mult = max(0.3, 1.0 - ent_val)
        base_conf = r2 * support * ent_mult
        conf_raw = base_conf + (topo_score * 0.3)
        air_gap_penalty = 1.0 - self._shadow_air_gap
        shans_confidence = float(np.clip(conf_raw * air_gap_penalty, 0.0, 1.0))
        
        return ShansCurveSignal(
            symbol=symbol,
            timestamp_ns=ts_ns,
            shans_superfluid_score=shans_superfluid_score,
            shans_bias=shans_bias,
            shans_confidence=shans_confidence,
            fit_r_squared=float(r2),
            inflection_distance=float(1.0 - proximity),
        )
    
    def _neutral_signal(self, symbol: str, ts_ns: int) -> ShansCurveSignal:
        """Zeroed signal for degenerate conditions."""
        return ShansCurveSignal(
            symbol=symbol,
            timestamp_ns=ts_ns,
            shans_superfluid_score=0.0,
            shans_bias=0,
            shans_confidence=0.0,
            fit_r_squared=0.0,
            inflection_distance=1.0,
        )
    
    def get_stats(self) -> Dict[str, Any]:
        """Observability metadata."""
        return {
            "curvature_window": self.curvature_window,
            "min_volatility": self.min_volatility,
            "enable_topological": self.enable_topological,
            "enable_denoising": self.enable_denoising,
            "buffered_samples": len(self._p),
            "fill_history_length": len(self._fill_history),
            "shadow_air_gap": self._shadow_air_gap,
        }
    
    def reset(self) -> None:
        """Reset all internal state. Deterministic replay safety."""
        self._p.clear()
        self._ofi.clear()
        self._v.clear()
        self._fill_history.clear()
        self._shadow_air_gap = 0.0