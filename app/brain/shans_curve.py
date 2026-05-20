"""
app/brain/shans_curve.py

Shan's Curve Engine - Asymptotic Liquidity Exhaustion Detector.
Hybrid rebuild: live intelligence (shape persistence proxy, denoising, bounded fill calibration)
+ doctrinal purity (OFI-centered asymptote, three-field separation).

Role: Pure alpha generator. NOT a direction engine.
Risk/safety gating is NOT performed here — delegated to caller (fusion/strategy router).

PRESERVE-FIRST HARDENING (Board-compliant, repo-aware correction pass):
- Preserves OFI-centered asymptotic exhaustion doctrine
- Preserves three-field doctrinal separation:
    - shans_superfluid_score
    - shans_bias
    - shans_confidence
- Preserves public ShansCurveSignal compatibility for legacy consumers
- Adds canonical internal computation artifact
- Clarifies internal confidence semantics:
    - raw_structural_confidence
    - stabilized_confidence
    - projected_confidence
- Keeps projection explicit without requiring private _last_* reads
- Softens prior "topological persistence" language honestly while preserving traceability
- Improves paper-trading observability with grouped stats
"""

import logging
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Deque, Dict, List, Optional, Tuple, Union

import numpy as np

try:
    import numba
    _NUMBA_AVAILABLE = True
except ImportError:
    _NUMBA_AVAILABLE = False
    logger_pre = __import__("logging").getLogger(__name__)
    logger_pre.warning("numba not installed — shans_curve JIT disabled, running pure Python fallback")

    class _NumbaStub:
        """No-op stub so @numba.njit decorators are syntactically valid without numba installed."""
        @staticmethod
        def njit(*args, **kwargs):
            def decorator(fn):
                return fn
            return decorator

    numba = _NumbaStub()  # type: ignore[assignment]

from app.brain.ring_buffer import RingBuffer
from app.brain.data_validator import DataContinuityValidator
from app.risk.guard import HybridRiskGuard
from app.risk.safety import SafetyGate
from app.brain.entropy_decoder import EntropyDecoder

logger = logging.getLogger(__name__)

EPS = np.finfo(float).eps


# =============================================================================
# INTERNAL STATE HELPERS
# =============================================================================

@dataclass
class _ConfidenceDecayState:
    """
    Tracks temporal stabilization of confidence via bounded exponential decay.
    This acts after structural computation.
    """
    last_confidence: float = 0.0
    last_timestamp_ns: int = 0
    decay_half_life_ns: int = 30_000_000_000  # 30 seconds

    def apply_decay(self, current_confidence: float, current_ts_ns: int) -> float:
        current_confidence = float(np.clip(current_confidence, 0.0, 1.0))

        if self.last_timestamp_ns == 0 or current_ts_ns <= self.last_timestamp_ns:
            self.last_confidence = current_confidence
            self.last_timestamp_ns = current_ts_ns
            return current_confidence

        elapsed_ns = current_ts_ns - self.last_timestamp_ns
        if elapsed_ns <= 0:
            return current_confidence

        decay_factor = 0.5 ** (elapsed_ns / max(self.decay_half_life_ns, 1))
        decayed_prior = self.last_confidence * decay_factor

        stabilized = max(current_confidence, decayed_prior) if current_confidence > self.last_confidence else decayed_prior
        stabilized = float(np.clip(stabilized, 0.0, 1.0))

        self.last_confidence = stabilized
        self.last_timestamp_ns = current_ts_ns
        return stabilized


@dataclass
class _BiasSmoother:
    """
    EMA smoother for doctrinal bias to reduce flip-flopping on noise.
    """
    last_bias_int: int = 0
    alpha: float = 0.3

    def update(self, raw_bias_int: int) -> int:
        raw_numeric = float(raw_bias_int)
        smoothed_numeric = (self.alpha * raw_numeric) + ((1.0 - self.alpha) * float(self.last_bias_int))

        if abs(smoothed_numeric) < 0.15:
            smoothed_int = 0
        elif smoothed_numeric > 0:
            smoothed_int = 1
        else:
            smoothed_int = -1

        self.last_bias_int = smoothed_int
        return smoothed_int


# =============================================================================
# FILE-LOCAL SIGNAL CONTRACT (PRESERVED)
# =============================================================================

@dataclass
class ShansCurveSignal:
    """
    Signal contract for Shan's Curve output.

    Doctrinal fields:
    - shans_superfluid_score: exhaustion / asymptote proximity [0,1]
    - shans_bias: directional sign [-1,0,1]
    - shans_confidence: emitted confidence [0,1]

    Legacy compatibility:
    - predicted_action derived from shans_bias
    """
    symbol: str
    timestamp_ns: int

    shans_superfluid_score: float
    shans_bias: int
    shans_confidence: float

    fit_r_squared: float
    inflection_distance: float
    decision_uuid: str = field(default_factory=lambda: str(uuid.uuid4()))

    predicted_action: int = 0

    def __post_init__(self):
        self.predicted_action = self.shans_bias


# =============================================================================
# CANONICAL INTERNAL COMPUTATION ARTIFACT
# =============================================================================

@dataclass
class ShansCurveComputation:
    """
    Canonical internal computation artifact.

    This is the internal authority for computed meaning.
    It separates structural, stabilized, and projected semantics
    while preserving public caller compatibility.
    """
    signal: ShansCurveSignal

    # Structural
    raw_structural_confidence: float
    support_density: float
    support_components: Dict[str, float]
    asymptote_proximity: float
    raw_bias: int
    fit_r_squared: float
    slope: float
    delta_ofi: float
    entropy_multiplier: float
    shape_persistence_proxy: float
    topological_persistence_trace: float
    air_gap_penalty: float

    # Stabilized
    stabilized_confidence: float
    stabilized_bias: int

    # Projection
    projected_confidence: float

    # Runtime
    is_neutral: bool
    reason: str


# =============================================================================
# DETERMINISTIC MATHEMATICAL CORE
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
        support_density_legacy: legacy placeholder support [0,1]
        delta_ofi: instantaneous OFI change

    Note:
    - support_density_legacy is retained in the return shape for baseline compatibility.
    - authoritative support density is upgraded outside this solver using buffered local data.
    """
    n = p.shape[0]
    if n < 5:
        return 0.0, 0.0, 0.0, 0.0, 0.0

    p_mean, p_std = np.mean(p), np.std(p) + 1e-8
    ofi_mean, ofi_std = np.mean(ofi), np.std(ofi) + 1e-8
    v_mean, v_std = np.mean(v), np.std(v) + 1e-8

    p_n = (p - p_mean) / p_std
    ofi_n = (ofi - ofi_mean) / ofi_std
    v_n = (v - v_mean) / v_std

    target = p_n * ofi_n
    A = np.zeros((n, 4), dtype=np.float64)
    A[:, 0] = p_n
    A[:, 1] = ofi_n
    A[:, 2] = v_n
    A[:, 3] = 1.0

    ATA = A.T @ A
    ATy = A.T @ target
    for j in range(4):
        ATA[j, j] += reg_lambda
    coeffs = np.linalg.solve(ATA, ATy)
    b1, b2, b3, b0 = coeffs[0], coeffs[1], coeffs[2], coeffs[3]

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

    p_pred = (b2 * ofi_n + b3 * v_n + b0) / ((ofi_n - b1) + 1e-8)
    ss_res = np.sum((p_n - p_pred) ** 2)
    ss_tot = np.sum((p_n - np.mean(p_n)) ** 2)
    r_squared = max(0.0, 1.0 - (ss_res / (ss_tot + 1e-12)))

    v_ratio = v[-1] / (np.mean(v) + 1e-8)
    support_density_legacy = min(1.0, v_ratio)

    return r_squared, slope, asymptote_proximity, support_density_legacy, delta_ofi


# =============================================================================
# SHAPE PERSISTENCE PROXY (TRACEABLE SOFTENING OF PRIOR TOPOLOGY LANGUAGE)
# =============================================================================

@numba.njit(cache=True)
def _betti_1_persistence(points: np.ndarray, threshold: float = 0.01) -> float:
    """
    Simplified persistence proxy retained for traceability.

    IMPORTANT:
    - This is not rigorous persistent homology.
    - It is used as a shape-persistence / trajectory-dispersion proxy.
    - Function name is preserved for traceability to prior 'topological persistence' references.
    """
    n = len(points)
    if n < 4:
        return 0.0

    persistence = 0.0
    threshold_safe = max(threshold, 1e-8)

    for i in range(n - 2):
        for j in range(i + 1, n - 1):
            d = abs(points[i] - points[j])
            if d > threshold:
                persistence += min(1.0, d / threshold_safe)

    return min(1.0, persistence / max((n * (n - 1) / 2), 1.0))


# =============================================================================
# DENOISING
# =============================================================================

@numba.njit(cache=True)
def _savitzky_golay(y: np.ndarray, window_size: int, poly_order: int) -> np.ndarray:
    """Savitzky-Golay filter."""
    if len(y) < window_size:
        return y.copy()
    if window_size < 3 or poly_order < 0 or poly_order >= window_size:
        return y.copy()

    half_window = window_size // 2
    result = np.zeros_like(y)
    x = np.arange(-half_window, half_window + 1, dtype=np.float64)
    n_coeff = poly_order + 1
    A = np.zeros((window_size, n_coeff), dtype=np.float64)
    for row in range(window_size):
        value = 1.0
        for col in range(n_coeff):
            A[row, col] = value
            value *= x[row]

    normal = A.T @ A
    rhs = A.T
    smoothing_rows = np.linalg.solve(normal, rhs)
    center_weights = smoothing_rows[0]

    for i in range(half_window, len(y) - half_window):
        window = y[i - half_window:i + half_window + 1]
        smoothed = 0.0
        for j in range(window_size):
            smoothed += center_weights[j] * window[j]
        result[i] = smoothed

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
    - Prior 'topological persistence' wording is softened to shape-persistence proxy,
      while traceability is preserved in names/comments/observability.
    - Fill calibration remains bounded and heuristic; no execution-calibration overclaim is made.
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
        # Interface continuity only
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

        # Fill calibration
        self._fill_history: Deque[Dict[str, Any]] = deque(maxlen=100)
        self._shadow_air_gap: float = 0.0

        # Stabilization state
        self._confidence_decay_state = _ConfidenceDecayState()
        self._bias_smoother = _BiasSmoother(alpha=0.3)

        # Canonical internal artifact
        self._last_computation: Optional[ShansCurveComputation] = None

        logger.info("ShansCurve initialized: bounded hardening mode")

    @staticmethod
    def _to_nanoseconds(ts: Union[int, datetime]) -> int:
        """
        Integer-safe nanosecond conversion. No float timestamp math.
        """
        if isinstance(ts, int):
            return ts

        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)

        epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
        delta = ts - epoch

        total_ns = delta.days * 86_400 * 1_000_000_000
        total_ns += delta.seconds * 1_000_000_000
        total_ns += delta.microseconds * 1_000
        return total_ns

    @staticmethod
    def _datetime_from_ns(ns: int) -> datetime:
        """
        Reconstruct datetime from integer nanoseconds.
        """
        seconds = ns // 1_000_000_000
        microseconds = (ns % 1_000_000_000) // 1_000
        return datetime.fromtimestamp(seconds, tz=timezone.utc).replace(microsecond=microseconds)

    def _extract_entropy_value(self, symbol: str) -> float:
        """
        Repo-aware entropy access.

        Live repo truth:
        - EntropyDecoder exposes update(...)
        - attached entropy_decoder does not expose get_current(...)
        - baseline shans_curve currently calls get_current(...)

        To stay paste-safe without widening repo rewrites:
        - if get_current exists, use it
        - else fall back to current internal entropy history if available
        - else use neutral default 0.5
        """
        get_current = getattr(self.entropy_decoder, "get_current", None)
        if callable(get_current):
            try:
                entropy_obj = get_current(symbol)
                if entropy_obj is None:
                    return 0.5
                return float(entropy_obj.entropy)
            except Exception:
                return 0.5

        # Repo-aware fallback for current EntropyDecoder implementation
        state = getattr(self.entropy_decoder, "state", None)
        if state is not None:
            entropy_history = getattr(state, "entropy_history", None)
            if entropy_history:
                try:
                    return float(entropy_history[-1])
                except Exception:
                    return 0.5

        return 0.5

    def _compute_shape_persistence_proxy(self, p_arr: np.ndarray, ofi_arr: np.ndarray) -> float:
        """
        Shape-persistence proxy from price-OFI trajectories.

        Traceability note:
        - replaces overclaimed public semantics of 'topological persistence'
        - preserves compatibility trace via topological_persistence_trace fields
        """
        if not self.enable_topological:
            return 0.0

        p_persist = _betti_1_persistence(p_arr, threshold=0.01)
        ofi_persist = _betti_1_persistence(ofi_arr, threshold=0.01)
        return float(np.clip((p_persist + ofi_persist) / 2.0, 0.0, 1.0))

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

    def _compute_support_density(
        self,
        p_arr: np.ndarray,
        ofi_arr: np.ndarray,
        v_arr: np.ndarray,
        asymptote_proximity: float,
    ) -> Tuple[float, Dict[str, float]]:
        """
        Support density derived only from buffered local trajectories.

        Components:
        - ofi_persistence:
          measures whether recent OFI moves keep a coherent sign instead of rapidly reversing
        - volume_participation:
          measures whether current total volume is meaningfully supported versus local history
        - price_ofi_stability:
          rewards lower price jerk relative to OFI jerk near the current structural state
        """
        n = len(p_arr)
        if n < 5:
            return 0.0, {
                "ofi_persistence": 0.0,
                "volume_participation": 0.0,
                "price_ofi_stability": 0.0,
            }

        recent_ofi = ofi_arr[-min(8, n):]
        ofi_diff = np.diff(recent_ofi)
        if len(ofi_diff) == 0:
            ofi_persistence = 0.0
        else:
            signs = np.sign(ofi_diff)
            nonzero = signs[np.abs(signs) > 0]
            if len(nonzero) == 0:
                ofi_persistence = 0.5
            else:
                ofi_persistence = float(np.clip(abs(np.sum(nonzero)) / len(nonzero), 0.0, 1.0))

        recent_v = v_arr[-min(12, n):]
        v_mean = float(np.mean(recent_v)) + 1e-8
        v_last = float(recent_v[-1])
        v_q75 = float(np.percentile(recent_v, 75))
        mean_ratio = min(1.0, v_last / v_mean)
        q75_ratio = min(1.0, v_last / max(v_q75, 1e-8))
        volume_participation = float(np.clip((0.6 * mean_ratio) + (0.4 * q75_ratio), 0.0, 1.0))

        p_slice = p_arr[-min(8, n):]
        ofi_slice = ofi_arr[-min(8, n):]
        p_diff = np.diff(p_slice)
        ofi_diff2 = np.diff(ofi_slice)

        if len(p_diff) < 2 or len(ofi_diff2) < 2:
            price_ofi_stability = 0.0
        else:
            price_jerk = float(np.mean(np.abs(np.diff(p_diff))))
            ofi_jerk = float(np.mean(np.abs(np.diff(ofi_diff2))))
            normalized_noise = price_jerk / (price_jerk + ofi_jerk + 1e-8)
            base_stability = 1.0 - normalized_noise
            price_ofi_stability = float(np.clip((0.8 * base_stability) + (0.2 * asymptote_proximity), 0.0, 1.0))

        support_density = float(np.clip(
            (0.40 * ofi_persistence) +
            (0.35 * volume_participation) +
            (0.25 * price_ofi_stability),
            0.0,
            1.0
        ))

        return support_density, {
            "ofi_persistence": ofi_persistence,
            "volume_participation": volume_participation,
            "price_ofi_stability": price_ofi_stability,
        }

    def _compute_air_gap_penalty(self, symbol: str, timestamp_ns: int) -> float:
        """
        Bounded fill-calibration penalty.

        Uses only current local fill history:
        - symbol-matched recent fills
        - age decay
        - modest size weighting

        This remains heuristic and intentionally bounded.
        """
        if not self._fill_history:
            self._shadow_air_gap = 0.0
            return 1.0

        weighted_pressure = 0.0
        total_weight = 0.0

        recent = list(self._fill_history)[-20:]
        for fill in recent:
            if fill.get("symbol") != symbol:
                continue

            age_ns = max(0, timestamp_ns - int(fill.get("timestamp_ns", 0)))
            age_factor = np.exp(-age_ns / 60_000_000_000.0)
            size = max(float(fill.get("fill_size", 0.0)), 0.0)
            size_factor = min(1.0, np.sqrt(size) / np.sqrt(1000.0))

            weight = age_factor * (0.5 + 0.5 * size_factor)
            weighted_pressure += weight * size_factor
            total_weight += weight

        if total_weight <= 0.0:
            self._shadow_air_gap = 0.0
            return 1.0

        self._shadow_air_gap = float(np.clip(weighted_pressure / total_weight, 0.0, 1.0))
        return float(np.clip(1.0 - self._shadow_air_gap, 0.0, 1.0))

    def record_fill(self, symbol: str, fill_price: float, fill_size: float, timestamp_ns: int) -> None:
        """Record execution fill for bounded shadow air-gap calibration."""
        self._fill_history.append({
            "symbol": symbol,
            "fill_price": float(fill_price),
            "fill_size": float(fill_size),
            "timestamp_ns": int(timestamp_ns),
        })

    def _build_neutral_computation(self, symbol: str, ts_ns: int, reason: str) -> ShansCurveComputation:
        """
        Build a valid neutral computation artifact.
        Projection must work on this without special external handling.
        """
        signal = ShansCurveSignal(
            symbol=symbol,
            timestamp_ns=ts_ns,
            shans_superfluid_score=0.0,
            shans_bias=0,
            shans_confidence=0.0,
            fit_r_squared=0.0,
            inflection_distance=1.0,
        )

        computation = ShansCurveComputation(
            signal=signal,
            raw_structural_confidence=0.0,
            support_density=0.0,
            support_components={
                "ofi_persistence": 0.0,
                "volume_participation": 0.0,
                "price_ofi_stability": 0.0,
            },
            asymptote_proximity=0.0,
            raw_bias=0,
            fit_r_squared=0.0,
            slope=0.0,
            delta_ofi=0.0,
            entropy_multiplier=0.0,
            shape_persistence_proxy=0.0,
            topological_persistence_trace=0.0,
            air_gap_penalty=1.0,
            stabilized_confidence=0.0,
            stabilized_bias=0,
            projected_confidence=0.0,
            is_neutral=True,
            reason=reason,
        )
        self._last_computation = computation
        return computation

    def _compute_signal_artifact(
        self,
        symbol: str,
        ts_ns: int,
        p_arr: np.ndarray,
        ofi_arr: np.ndarray,
        v_arr: np.ndarray,
    ) -> ShansCurveComputation:
        """
        Canonical internal computation path.
        This is the internal authority for current engine meaning.
        """
        if np.std(p_arr) < self.min_volatility or np.std(ofi_arr) < self.min_volatility:
            return self._build_neutral_computation(symbol, ts_ns, reason="degenerate_low_variance")

        r2, slope, proximity, _support_legacy_unused, dx = solve_asymptotic_kinematics(p_arr, ofi_arr, v_arr)
        proximity = float(np.clip(proximity, 0.0, 1.0))

        shape_persistence_proxy = self._compute_shape_persistence_proxy(p_arr, ofi_arr)
        support_density, support_components = self._compute_support_density(
            p_arr=p_arr,
            ofi_arr=ofi_arr,
            v_arr=v_arr,
            asymptote_proximity=proximity,
        )

        shans_superfluid_score = proximity
        raw_bias = int(np.sign(slope * dx)) if not np.isnan(slope * dx) else 0

        ent_val = self._extract_entropy_value(symbol)
        ent_mult = max(0.3, 1.0 - ent_val)

        base_confidence = float(np.clip(r2 * support_density * ent_mult, 0.0, 1.0))
        raw_structural_confidence = float(np.clip(base_confidence + (shape_persistence_proxy * 0.3), 0.0, 1.0))

        air_gap_penalty = self._compute_air_gap_penalty(symbol=symbol, timestamp_ns=ts_ns)
        confidence_after_fill = float(np.clip(raw_structural_confidence * air_gap_penalty, 0.0, 1.0))

        stabilized_confidence = self._confidence_decay_state.apply_decay(confidence_after_fill, ts_ns)
        stabilized_bias = self._bias_smoother.update(raw_bias)
        projected_confidence = float(np.clip(stabilized_confidence, 0.0, 1.0))

        signal = ShansCurveSignal(
            symbol=symbol,
            timestamp_ns=ts_ns,
            shans_superfluid_score=shans_superfluid_score,
            shans_bias=raw_bias,
            shans_confidence=stabilized_confidence,
            fit_r_squared=float(r2),
            inflection_distance=float(1.0 - proximity),
        )

        computation = ShansCurveComputation(
            signal=signal,
            raw_structural_confidence=raw_structural_confidence,
            support_density=support_density,
            support_components=support_components,
            asymptote_proximity=proximity,
            raw_bias=raw_bias,
            fit_r_squared=float(r2),
            slope=float(slope),
            delta_ofi=float(dx),
            entropy_multiplier=float(ent_mult),
            shape_persistence_proxy=float(shape_persistence_proxy),
            topological_persistence_trace=float(shape_persistence_proxy),
            air_gap_penalty=float(air_gap_penalty),
            stabilized_confidence=stabilized_confidence,
            stabilized_bias=stabilized_bias,
            projected_confidence=projected_confidence,
            is_neutral=False,
            reason="ok",
        )
        self._last_computation = computation
        return computation

    def update_order_book(
        self,
        symbol: str,
        mid_price: float,
        cum_bid_vol: float,
        cum_ask_vol: float,
        depth_velocity: float,  # preserved for interface continuity
        timestamp: Union[int, datetime],
        sequence_id: Optional[int] = None,
        regime_id: Optional[str] = None,  # preserved for interface continuity
    ) -> Optional[ShansCurveSignal]:
        """
        Process order-book state and emit doctrinal signal.
        No risk/safety gating is applied here.

        depth_velocity and regime_id are accepted for API continuity
        but are not used in current computations.
        """
        ts_ns = self._to_nanoseconds(timestamp)

        dt_for_val = self._datetime_from_ns(ts_ns)
        is_healthy, _ = self.data_validator.validate(
            symbol=symbol,
            timestamp=dt_for_val,
            sequence_id=sequence_id,
        )
        if not is_healthy:
            return None

        ofi = float(cum_bid_vol - cum_ask_vol)
        tot_vol = float(cum_bid_vol + cum_ask_vol)

        self._p.append(float(mid_price))
        self._ofi.append(ofi)
        self._v.append(tot_vol)

        if len(self._p) < self.curvature_window:
            return None

        p_raw = self._p.get_window(self.curvature_window)
        ofi_raw = self._ofi.get_window(self.curvature_window)
        v_raw = self._v.get_window(self.curvature_window)

        p_arr = self._apply_denoising(p_raw)
        ofi_arr = self._apply_denoising(ofi_raw)
        v_arr = v_raw

        computation = self._compute_signal_artifact(
            symbol=symbol,
            ts_ns=ts_ns,
            p_arr=p_arr,
            ofi_arr=ofi_arr,
            v_arr=v_arr,
        )
        return computation.signal

    def is_ready(self) -> bool:
        """
        True when the ring buffer has accumulated enough samples for
        update_order_book() to produce a valid signal.

        Reflects the SAME internal gate (current_buffer_len < curvature_window)
        that causes update_order_book() to return None after validator passes.
        No logic duplicated — both reference self._p and self.curvature_window.

        Pure: no side effects.
        Deterministic: same buffer state always returns same result.
        Derived from internal state only.
        """
        return len(self._p) >= self.curvature_window

    def get_last_computation(self) -> Optional[ShansCurveComputation]:
        """
        Return the canonical internal computation artifact for observability
        or explicit projection.
        """
        return self._last_computation

    def to_fusion_fields(
        self,
        signal: ShansCurveSignal,
        computation: Optional[ShansCurveComputation] = None,
    ) -> Dict[str, Any]:
        """
        Convert ShansCurveSignal to FusionDecision-compatible fields.

        Projection purity:
        - callers do not need private _last_* access
        - explicit computation artifact is preferred
        - compatibility fallback remains safe
        - neutral outputs are supported without special casing
        """
        if computation is not None:
            smoothed_bias_int = computation.stabilized_bias
            projected_confidence = computation.projected_confidence
        else:
            smoothed_bias_int = int(np.sign(signal.shans_bias))
            projected_confidence = float(np.clip(signal.shans_confidence, 0.0, 1.0))

        shans_superfluid_scaled = float(np.clip(signal.shans_superfluid_score * 10.0, 0.0, 10.0))

        if smoothed_bias_int > 0:
            bias_str = "bullish"
        elif smoothed_bias_int < 0:
            bias_str = "bearish"
        else:
            bias_str = "neutral"

        return {
            "shans_superfluid_score": shans_superfluid_scaled,
            "shans_bias": bias_str,
            "shans_confidence": float(np.clip(projected_confidence, 0.0, 1.0)),
        }

    def get_stats(self) -> Dict[str, Any]:
        """
        Grouped observability for paper-trading inspection.
        """
        stats: Dict[str, Any] = {
            "runtime_state": {
                "curvature_window": self.curvature_window,
                "min_volatility": self.min_volatility,
                "enable_topological": self.enable_topological,
                "enable_denoising": self.enable_denoising,
                "buffered_samples": len(self._p),
                "numba_available": _NUMBA_AVAILABLE,
                "has_last_computation": self._last_computation is not None,
            },
            "fill_calibration": {
                "fill_history_length": len(self._fill_history),
                "shadow_air_gap": self._shadow_air_gap,
            },
            "structural": {
                "raw_structural_confidence": 0.0,
                "support_density": 0.0,
                "support_components": {
                    "ofi_persistence": 0.0,
                    "volume_participation": 0.0,
                    "price_ofi_stability": 0.0,
                },
                "fit_r_squared": 0.0,
                "asymptote_proximity": 0.0,
                "raw_bias": 0,
                "delta_ofi": 0.0,
                "shape_persistence_proxy": 0.0,
                "topological_persistence_trace": 0.0,
                "entropy_multiplier": 0.0,
                "air_gap_penalty": 1.0,
            },
            "stabilized": {
                "stabilized_confidence": 0.0,
                "stabilized_bias": 0,
                "confidence_decay_half_life_ns": self._confidence_decay_state.decay_half_life_ns,
                "bias_smoothing_alpha": self._bias_smoother.alpha,
            },
            "projection": {
                "projected_confidence": 0.0,
                "last_fusion_fields": None,
            },
        }

        comp = self._last_computation
        if comp is None:
            return stats

        stats["structural"] = {
            "raw_structural_confidence": comp.raw_structural_confidence,
            "support_density": comp.support_density,
            "support_components": comp.support_components,
            "fit_r_squared": comp.fit_r_squared,
            "asymptote_proximity": comp.asymptote_proximity,
            "raw_bias": comp.raw_bias,
            "delta_ofi": comp.delta_ofi,
            "shape_persistence_proxy": comp.shape_persistence_proxy,
            "topological_persistence_trace": comp.topological_persistence_trace,
            "entropy_multiplier": comp.entropy_multiplier,
            "air_gap_penalty": comp.air_gap_penalty,
        }
        stats["stabilized"] = {
            "stabilized_confidence": comp.stabilized_confidence,
            "stabilized_bias": comp.stabilized_bias,
            "confidence_decay_half_life_ns": self._confidence_decay_state.decay_half_life_ns,
            "bias_smoothing_alpha": self._bias_smoother.alpha,
        }
        stats["projection"] = {
            "projected_confidence": comp.projected_confidence,
            "last_fusion_fields": self.to_fusion_fields(comp.signal, computation=comp),
        }
        stats["runtime_state"]["last_reason"] = comp.reason
        stats["runtime_state"]["last_is_neutral"] = comp.is_neutral

        return stats

    def reset(self) -> None:
        """
        Reset all internal state. Deterministic replay safety.
        """
        self._p.clear()
        self._ofi.clear()
        self._v.clear()
        self._fill_history.clear()
        self._shadow_air_gap = 0.0
        self._confidence_decay_state = _ConfidenceDecayState()
        self._bias_smoother = _BiasSmoother(alpha=0.3)
        self._last_computation = None
