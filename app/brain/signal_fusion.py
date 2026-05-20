"""
app/brain/signal_fusion.py

POVERTY_KILLER Supreme Board Implementation
Role: Central Doctrine-Preserving Quantitative Fusion Engine

This module executes deterministic, replay-safe, non-linear signal fusion across 
mixed-latency differentiators. It relies on strict contract adherence, continuous 
temporal discounting, kinematic hazard tracking, and dynamic topological routing hints.

Core Doctrinal Boundaries:
- Whale Flow: Directional Alpha Vector (Momentum & Continuous Temporal Decay)
- Shan's Curve: Exhaustion Asymptote (Superfluid), Orderbook Bias, Liquidity Density
- Entropy: Threshold Temperature, Structural Disorder, Velocity, and Acceleration
- Regime: Baseline Sleeve Authorization (Boolean flags) & Tie-breaker hints
- Toxicity: Exponential Suppression, Hazard Velocity, and Hard Veto (is_toxic)
- Insider: Urgency / Attack Escalation Catalyst (Gated by active/invalidated state)
- Physical Validator: Base Reality Impact Bounds

BUNDLE DIAGNOSTIC VISIBILITY — FUSION DECISION TRACE (2026-04-28)
    - Added INFO-level logging for veto reasons and regime decision
    - NO BEHAVIOR CHANGES. Read-only diagnostic only.

BUNDLE DIAGNOSTIC VISIBILITY — FUSION BREAKDOWN TRACE (PP7B, 2026-04-29)
    - Added [FUSION_BREAKDOWN] structured log before Phase 7 assembly
    - Added [FUSION_VETO_DETAIL] structured log in _issue_hard_veto()
    - Exposes: base_confidence, tox_penalty, entropy_penalty, resonance, direction_alignment
    - NO BEHAVIOR CHANGES. Read-only diagnostic only.

FUSION LANE REPAIR — KELLY REMOVED FROM FUSION (PP6D, 2026-04-29)
    - Removed kelly_calibration_curve() from Fusion confidence path
    - Toxicity: bounded piecewise modulation replaces exponential steepness=3.5
      [0,0.30]→1.0 | (0.30,0.60]→1.0..0.70 | (0.60,0.88]→0.70..0.40
    - Entropy: explicit entropy_neutralized flag; ent_multiplier=1.0 when dynamic_entropy<=0
      Positive branch: max(0.70, 1.0 - dynamic_entropy*0.30) — floor raised, slope reduced
    - Resonance bonus: non-resonant 0.85 → 1.0 (neutral, not penalty)
    - final_confidence = clamp(pre_kelly_value, 0.0, 1.0)
    - kelly_calibration_curve() preserved intact in QuantMath for downstream PositionSizing
    - [FUSION_BREAKDOWN] updated to expose all new fields + kelly_removed_from_fusion=True
"""

import math
import logging
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass

# Lawful contracts imported strictly from provided repo truth
from app.models.fusion import FusionDecision
from app.models.enums import RegimeType, SleeveType
from app.brain.toxicity_engine import ToxicityRegime
from app.core.whole_bot_attribution import make_signature

logger = logging.getLogger(__name__)

MISSING_PENALTY_PER_MISS = 0.95   # 5% reduction per missing/stale non-critical input
MISSING_PENALTY_FLOOR = 0.75      # do not penalize below 75%

# Backward-compatible export expected by callers/tests
MISSING_PENALTY_FACTOR: float = MISSING_PENALTY_FLOOR
# Backward-compatibility aliases for legacy callers/tests
missing_penalty_factor: float = MISSING_PENALTY_FACTOR
MISSING_DATA_PENALTY: float = MISSING_PENALTY_FACTOR
MISSING_DATA_PENALTY_FACTOR: float = MISSING_PENALTY_FACTOR

_ATTRIBUTION_NAMES = {
    "physical": ("PhysicalValidator", "risk_guardrails"),
    "toxicity": ("Toxicity", "intelligence_node"),
    "whale_flow": ("WhaleFlow", "intelligence_node"),
    "shans_curve": ("ShansCurve", "strategy_alpha"),
    "entropy": ("EntropyDecoder", "intelligence_node"),
    "insider": ("InsiderSignalEngine", "specialized_portal"),
    "regime": ("RegimeDetector", "intelligence_node"),
}


# =========================================================================
# MATHEMATICAL & QUANTITATIVE SUBSYSTEMS
# =========================================================================

class QuantMath:
    """
    Continuous mathematical functions for shaping raw signals into actionable 
    probability spaces. Prevents linear scaling errors at boundary conditions.
    """
    @staticmethod
    def exponential_decay(value: float, steepness: float = 3.0) -> float:
        clamped = max(0.0, min(1.0, value))
        return math.exp(-steepness * clamped)

    @staticmethod
    def temperature_threshold(base_threshold: float, entropy: float, max_penalty: float = 0.3) -> float:
        clamped_entropy = max(0.0, min(1.0, entropy))
        return min(0.95, base_threshold + (clamped_entropy * max_penalty))

    @staticmethod
    def temporal_discount(age_ns: int, half_life_ns: int) -> float:
        if age_ns <= 0:
            return 1.0
        return math.pow(0.5, age_ns / half_life_ns)

    @staticmethod
    def vector_resonance(direction_a: int, confidence_a: float, bias_b: float) -> float:
        clamped_conf = max(0.0, min(1.0, confidence_a))
        clamped_bias = max(-1.0, min(1.0, bias_b))
        return float(direction_a) * clamped_conf * clamped_bias

    @staticmethod
    def kelly_calibration_curve(raw_confidence: float) -> float:
        clamped = max(0.0, min(1.0, raw_confidence))
        return math.pow(clamped, 3)

    @staticmethod
    def bounded_tox_modulation(tox_score: float) -> float:
        """
        Piecewise linear toxicity modulation for Fusion conviction lane.
        Low tox: neutral. Moderate: mild suppression. High: meaningful suppression.
        Hard veto gates tox>=0.88 upstream; upper segment never executes above that.
        Segments: [0,0.30]->1.0 | (0.30,0.60]->1.0..0.70 | (0.60,0.88]->0.70..0.40
        """
        tox = max(0.0, min(1.0, tox_score))
        if tox <= 0.30:
            return 1.0
        elif tox <= 0.60:
            return 1.0 - 0.30 * (tox - 0.30) / 0.30
        else:
            return 0.70 - 0.30 * (tox - 0.60) / 0.28


# =========================================================================
# STATE, KINEMATICS & TELEMETRY
# =========================================================================

@dataclass
class HysteresisState:
    """
    Tracks temporal derivatives (velocity and acceleration) and state persistence.
    Essential for front-running market collapses before absolute thresholds are breached.
    """
    was_attack_mode: bool = False
    consecutive_attack_ticks: int = 0
    
    # Entropy Kinematics
    last_entropy: float = 0.0
    entropy_velocity: float = 0.0      # ds/dt
    entropy_acceleration: float = 0.0  # d2s/dt2
    
    # Toxicity Kinematics
    last_toxicity: float = 0.0
    toxicity_velocity: float = 0.0     # ds/dt
    toxicity_acceleration: float = 0.0 # d2s/dt2
    
    last_eval_ns: int = 0

    def update_kinematics(self, current_entropy: float, current_toxicity: float, current_ts_ns: int) -> None:
        """Calculates 1st (Velocity) and 2nd (Acceleration) derivatives of hazard signals."""
        if self.last_eval_ns > 0 and current_ts_ns > self.last_eval_ns:
            dt_sec = (current_ts_ns - self.last_eval_ns) / 1e9
            
            # Velocity
            new_ent_vel = (current_entropy - self.last_entropy) / dt_sec
            new_tox_vel = (current_toxicity - self.last_toxicity) / dt_sec
            
            # Acceleration
            self.entropy_acceleration = (new_ent_vel - self.entropy_velocity) / dt_sec
            self.toxicity_acceleration = (new_tox_vel - self.toxicity_velocity) / dt_sec
            
            self.entropy_velocity = new_ent_vel
            self.toxicity_velocity = new_tox_vel
        else:
            self.entropy_velocity = 0.0
            self.toxicity_velocity = 0.0
            self.entropy_acceleration = 0.0
            self.toxicity_acceleration = 0.0

        self.last_entropy = current_entropy
        self.last_toxicity = current_toxicity
        self.last_eval_ns = current_ts_ns

    def register_decision(self, is_attack_mode: bool) -> None:
        """Updates persistence counters to dampen micro-oscillations."""
        if is_attack_mode:
            self.consecutive_attack_ticks += 1
        else:
            self.consecutive_attack_ticks = 0
        self.was_attack_mode = is_attack_mode


# =========================================================================
# THE FUSION ENGINE
# =========================================================================

class SignalFusion:
    """
    Apex quantitative decision nexus for POVERTY_KILLER.
    Maintains mixed-latency temporal caches, applies non-linear discounts,
    manages state hysteresis, and provides tie-breaker routing hints.
    """

    def __init__(self, config: Any, commander: Any = None):
        self.config = config
        self.commander = commander
        
        # Temporal Cache: key -> (payload_object, timestamp_nanoseconds)
        self._cache: Dict[str, Tuple[Any, int]] = {}
        
        # Core State Tracking
        self._state = HysteresisState()
        self._last_fusion: Optional[FusionDecision] = None
        self._telemetry: Dict[str, Any] = {}
        
        # Strict Mixed-Latency TTL Doctrine (Nanoseconds)
        self._ttl_ns = {
            "whale_flow": 15_000_000_000,
            "shans_curve": 15_000_000_000,
            "physical": 30_000_000_000,
            "toxicity": 30_000_000_000,
            "entropy": 60_000_000_000,
            "insider": 120_000_000_000,
            "regime": 300_000_000_000
        }

        # Half-lives for Continuous Temporal Discounting (Nanoseconds)
        self._half_life_ns = {
            "whale_flow": 5_000_000_000,
            "shans_curve": 7_000_000_000,
            "insider": 60_000_000_000
        }
        
        logger.info("SignalFusion initialized. Replay-safety enforced. Router logic strictly delegated.")

    # =========================================================================
    # STRICT INGESTION (REPLAY-SAFE)
    # =========================================================================

    def _ingest(self, key: str, payload: Any, timestamp_ns: int) -> None:
        """Secure ingestion portal enforcing explicit timestamp tracking."""
        if payload is not None:
            self._cache[key] = (payload, timestamp_ns)

    def update_whale(self, payload: Any, timestamp_ns: int) -> None:
        self._ingest("whale_flow", payload, timestamp_ns)

    def update_shans(self, payload: Any, timestamp_ns: int) -> None:
        self._ingest("shans_curve", payload, timestamp_ns)

    def update_regime(self, payload: Any, timestamp_ns: int) -> None:
        self._ingest("regime", payload, timestamp_ns)

    def update_entropy(self, payload: Any, timestamp_ns: int) -> None:
        self._ingest("entropy", payload, timestamp_ns)

    def update_insider(self, payload: Any, timestamp_ns: int) -> None:
        self._ingest("insider", payload, timestamp_ns)

    def update_toxicity(self, payload: Any, timestamp_ns: int) -> None:
        self._ingest("toxicity", payload, timestamp_ns)

    def update_physical(self, payload: Any, timestamp_ns: int) -> None:
        self._ingest("physical", payload, timestamp_ns)

    # =========================================================================
    # STATE EXPORT & OBSERVABILITY
    # =========================================================================

    def get_last_fusion(self) -> Optional[FusionDecision]:
        """Provides the last computed deterministic state to the Orchestrator/Router."""
        return self._last_fusion

    def get_fusion_telemetry(self) -> Dict[str, Any]:
        """Exposes internal mathematical weights and kinematic states."""
        return self._telemetry

    def _record_fusion_attribution(
        self,
        key: str,
        *,
        status: str,
        input_source: str,
        output_summary: str,
        effect: str,
        reason: str,
        timestamp_ns: int,
    ) -> None:
        module_name, category = _ATTRIBUTION_NAMES.get(key, (key, "signal_decision_path"))
        edge_attribution = self._telemetry.setdefault("edge_attribution", {})
        edge_attribution[module_name] = make_signature(
            module_name=module_name,
            category=category,
            status=status,
            input_source=input_source,
            output_summary=output_summary,
            effect=effect,
            reason=reason,
            timestamp=timestamp_ns,
        )

    def _bridge_shans_bias(self, raw_bias: float) -> str:
        """
        Contract Bridge: Transforms the continuous numerical bias from shans_curve.py 
        into the explicit string literal required by FusionDecision.shans_bias.
        """
        if raw_bias > 0.15:
            return "bullish"
        elif raw_bias < -0.15:
            return "bearish"
        return "neutral"

    # =========================================================================
    # THE APEX ALGORITHM: CORE FUSION DOCTRINE
    # =========================================================================

    def fuse(self, current_ts_ns: int) -> FusionDecision:
        """
        The mathematical heart of the system.
        Executes staleness vetting, precise property extraction, temporal discounting,
        kinematic derivative tracking, vector resonance, hysteresis modulation, 
        and strict boundary alignment for the Strategy Router.

        Args:
            current_ts_ns: The authoritative orchestration tick timestamp.
                           NO WALL-CLOCK FALLBACKS ARE PERMITTED.
        """
        self._telemetry.clear()
        self._telemetry["execution_ts"] = current_ts_ns
        self._telemetry["missing_inputs"] = []
        self._telemetry["edge_attribution"] = {}
        self._telemetry["missing_penalty_factor"] = 1.0
        missing_penalty_factor: float = MISSING_PENALTY_FACTOR  # default; refined after non-critical staleness scan
        self._telemetry["missing_penalty_factor"] = missing_penalty_factor

        # ---------------------------------------------------------
        # PHASE 1: TEMPORAL SAFETY GATE (Critical-Only Staleness Enforcement)
        # ---------------------------------------------------------
        critical_signals = ("physical", "toxicity")
        noncritical_signals = ("whale_flow", "shans_curve", "entropy", "insider", "regime")

        missing_or_stale_noncrit: Dict[str, bool] = {}
        # Enforce presence and freshness only for critical signals
        for sig in critical_signals:
            ttl = self._ttl_ns[sig]
            if sig not in self._cache:
                self._record_fusion_attribution(
                    sig,
                    status="MISSING_FEED_TRUTH",
                    input_source="fusion_cache",
                    output_summary="Critical signal missing; fusion fails closed.",
                    effect="VETO",
                    reason=f"MISSING_CRITICAL_SIGNAL:{sig}",
                    timestamp_ns=current_ts_ns,
                )
                logger.info("[FUSION_DIAG] Missing CRITICAL signal: %s → veto", sig)
                return self._issue_hard_veto(current_ts_ns, f"Missing critical signal [{sig}]")
            _, ts = self._cache[sig]
            age_ns = current_ts_ns - ts
            if age_ns > ttl:
                self._record_fusion_attribution(
                    sig,
                    status="MISSING_FEED_TRUTH",
                    input_source="fusion_cache",
                    output_summary=f"Critical signal stale: age_ns={age_ns} ttl_ns={ttl}.",
                    effect="VETO",
                    reason=f"STALE_CRITICAL_SIGNAL:{sig}",
                    timestamp_ns=current_ts_ns,
                )
                logger.info("[FUSION_DIAG] Stale CRITICAL signal: %s age=%.1fs ttl=%.1fs → veto",
                            sig, age_ns/1e9, ttl/1e9)
                return self._issue_hard_veto(current_ts_ns, f"Stale critical signal [{sig}] (Age: {age_ns/1e9:.2f}s)")
            self._record_fusion_attribution(
                sig,
                status="ACTIVE_TRUTH_CHECK",
                input_source="fusion_cache",
                output_summary=f"Critical signal present and fresh: age_ns={age_ns} ttl_ns={ttl}.",
                effect="APPROVED",
                reason="CRITICAL_SIGNAL_FRESH",
                timestamp_ns=current_ts_ns,
            )

        # Record missing/stale for non-critical signals but do not veto
        for sig in noncritical_signals:
            ttl = self._ttl_ns[sig]
            st = self._cache.get(sig)
            if st is None:
                missing_or_stale_noncrit[sig] = True
                self._record_fusion_attribution(
                    sig,
                    status="MISSING_FEED_TRUTH",
                    input_source="fusion_cache",
                    output_summary="Native feed missing; neutral default plus explicit missing-truth penalty.",
                    effect="ADVISORY",
                    reason=f"MISSING_NONCRITICAL_SIGNAL:{sig}",
                    timestamp_ns=current_ts_ns,
                )
                logger.info("[FUSION_DIAG] Missing non-critical signal: %s → neutral default with penalty", sig)
                continue
            _, ts = st
            age_ns = current_ts_ns - ts
            if age_ns > ttl:
                missing_or_stale_noncrit[sig] = True
                self._record_fusion_attribution(
                    sig,
                    status="MISSING_FEED_TRUTH",
                    input_source="fusion_cache",
                    output_summary=f"Native feed stale; neutral default plus explicit missing-truth penalty: age_ns={age_ns} ttl_ns={ttl}.",
                    effect="ADVISORY",
                    reason=f"STALE_NONCRITICAL_SIGNAL:{sig}",
                    timestamp_ns=current_ts_ns,
                )
                logger.info("[FUSION_DIAG] Stale non-critical signal: %s age=%.1fs ttl=%.1fs → neutral default with penalty",
                            sig, age_ns/1e9, ttl/1e9)
            else:
                missing_or_stale_noncrit[sig] = False
                self._record_fusion_attribution(
                    sig,
                    status="ACTIVE_NATIVE_SIGNAL",
                    input_source="fusion_cache",
                    output_summary=f"Native signal present and fresh: age_ns={age_ns} ttl_ns={ttl}.",
                    effect="ADVISORY",
                    reason="NATIVE_SIGNAL_FRESH",
                    timestamp_ns=current_ts_ns,
                )

        self._telemetry["missing_inputs"] = [k for k, v in missing_or_stale_noncrit.items() if v]

        missing_count = len(self._telemetry.get("missing_inputs", []))
        missing_penalty_factor = max(MISSING_PENALTY_FLOOR, 1.0 - (0.05 * missing_count))

        # Update telemetry with missing penalty factor

        # ---------------------------------------------------------
        # PHASE 2: STRICT CONTRACT EXTRACTION
        # ---------------------------------------------------------
        
        # ToxicityAlert
        tox_payload, _ = self._cache["toxicity"]
        tox_score = float(tox_payload.toxicity_score)
        tox_is_toxic = bool(tox_payload.regime.value >= ToxicityRegime.TOXIC.value)
        
        # EntropyScore (neutral default when missing/stale)
        if missing_or_stale_noncrit.get("entropy", True):
            ent_score = 0.45
        else:
            ent_payload, _ = self._cache["entropy"]
            ent_score = float(ent_payload.entropy)

        # Kinematic Tracking
        self._state.update_kinematics(ent_score, tox_score, current_ts_ns)
        self._telemetry["entropy_velocity"] = self._state.entropy_velocity
        self._telemetry["toxicity_velocity"] = self._state.toxicity_velocity
        
        # Physical Validator (Dict contract proven)
        phys_dict, _ = self._cache["physical"]
        phys_score = float(phys_dict.get("health_score", 0.0))
        
        # ==========================================================
        # WHALE FLOW — STRICT CONTRACT VALIDATION (neutral defaults allowed)
        # ==========================================================
        whale_missing = missing_or_stale_noncrit.get("whale_flow", True)
        if whale_missing:
            whale_dir = 0
            whale_conf_raw = 0.0
            whale_ts = current_ts_ns
            whale_conf_decayed = 0.0
        else:
            whale_payload, whale_ts = self._cache["whale_flow"]
            if not hasattr(whale_payload, "direction") or not hasattr(whale_payload, "confidence"):
                logger.error(
                    "[FUSION_ERROR] INVALID_WHALE_PAYLOAD type=%s missing required fields direction/confidence → veto",
                    type(whale_payload).__name__,
                )
                return self._issue_hard_veto(current_ts_ns, "Invalid Whale Payload Type")
            try:
                whale_dir = int(whale_payload.direction.value)
                whale_conf_raw = float(whale_payload.confidence)
            except Exception as exc:
                logger.error(
                    "[FUSION_ERROR] WHALE_PAYLOAD_PARSE_FAILED type=%s error=%s → veto",
                    type(whale_payload).__name__,
                    str(exc),
                )
                return self._issue_hard_veto(current_ts_ns, "Corrupted Whale Payload")
            whale_age = current_ts_ns - whale_ts
            whale_discount = QuantMath.temporal_discount(whale_age, self._half_life_ns["whale_flow"])
            whale_conf_decayed = whale_conf_raw * whale_discount

        # ShansCurveSignal (neutral defaults when missing/stale)
        shans_missing = missing_or_stale_noncrit.get("shans_curve", True)
        if shans_missing:
            shans_superfluid = 0.0
            shans_bias_raw = 0.0
            shans_conf_decayed = 0.0
            shans_bias_str = self._bridge_shans_bias(shans_bias_raw)
        else:
            shans_payload, shans_ts = self._cache["shans_curve"]
            shans_superfluid = float(shans_payload.shans_superfluid_score)
            shans_bias_raw = float(shans_payload.shans_bias)
            shans_conf_raw = float(shans_payload.shans_confidence)
            shans_age = current_ts_ns - shans_ts
            shans_discount = QuantMath.temporal_discount(shans_age, self._half_life_ns["shans_curve"])
            shans_conf_decayed = shans_conf_raw * shans_discount
            shans_bias_str = self._bridge_shans_bias(shans_bias_raw)
        
        # InsiderSignalSnapshot (neutral default when missing/stale)
        insider_missing = missing_or_stale_noncrit.get("insider", True)
        if insider_missing:
            insider_urgency_raw = 0.0
            insider_ts = current_ts_ns
        else:
            insider_payload, insider_ts = self._cache["insider"]
            if bool(insider_payload.active) and not bool(insider_payload.invalidated):
                insider_urgency_raw = float(insider_payload.urgency)
            else:
                insider_urgency_raw = 0.0
        insider_age = current_ts_ns - insider_ts
        insider_urgency = insider_urgency_raw * QuantMath.temporal_discount(insider_age, self._half_life_ns["insider"])

        # RegimeDetector (neutral default when missing/stale)
        regime_missing = missing_or_stale_noncrit.get("regime", True)
        if regime_missing:
            regime_type = RegimeType.RANGING
            regime_confidence = 0.0
        else:
            regime_payload, _ = self._cache["regime"]
            regime_type = regime_payload[0]
            regime_confidence = regime_payload[1]

        # DIAGNOSTIC: Log key input values before veto checks
        logger.info(
            "[FUSION_DIAG] Inputs: regime=%s (conf=%.2f), whale_dir=%d, tox_score=%.3f, tox_toxic=%s, "
            "ent_score=%.3f, phys_score=%.3f, shans_superfluid=%.3f, shans_bias=%.3f",
            regime_type.value, regime_confidence, whale_dir, tox_score, tox_is_toxic,
            ent_score, phys_score, shans_superfluid, shans_bias_raw
        )

        # ---------------------------------------------------------
        # PHASE 3: CRITICAL HAZARD GATING (Absolute Boundaries)
        # ---------------------------------------------------------
        if whale_dir == 0:
            logger.info("[FUSION_DIAG] whale_dir=0 (NEUTRAL) → continuing with neutral whale contribution")
            
        if tox_is_toxic or tox_score >= 0.88:
            logger.info("[FUSION_DIAG] veto: tox_is_toxic=%s or tox_score=%.3f >= 0.88", tox_is_toxic, tox_score)
            return self._issue_hard_veto(current_ts_ns, f"Toxicity Critical (Score:{tox_score:.2f})")
            
        # Kinematic Veto: Toxicity rocketing upward
        if tox_score > 0.60 and self._state.toxicity_velocity > 0.15:
            logger.info("[FUSION_DIAG] veto: toxicity_velocity=%.3f > 0.15 with tox_score=%.3f > 0.60", 
                       self._state.toxicity_velocity, tox_score)
            return self._issue_hard_veto(current_ts_ns, f"Toxicity Spike (+{self._state.toxicity_velocity:.2f}/s)")
             
        if ent_score >= 0.95:
            logger.info("[FUSION_DIAG] veto: ent_score=%.3f >= 0.95", ent_score)
            return self._issue_hard_veto(current_ts_ns, f"Entropy Disintegration ({ent_score:.2f})")
            
        if phys_score <= 0.15:
            logger.info("[FUSION_DIAG] veto: phys_score=%.3f <= 0.15", phys_score)
            return self._issue_hard_veto(current_ts_ns, f"Physical Validator Collapse ({phys_score:.2f})")

        # ---------------------------------------------------------
        # PHASE 4: VECTOR RESONANCE & NON-LINEAR MODULATION
        # ---------------------------------------------------------
        resonance = QuantMath.vector_resonance(whale_dir, whale_conf_decayed, shans_bias_raw)
        self._telemetry["vector_resonance"] = resonance
        
        is_resonant = resonance > 0.10
        is_dissonant = resonance < -0.20

        # Dissonance now applies a confidence penalty instead of hard veto
        dissonance_penalty = 0.85 if is_dissonant else 1.0
        if is_dissonant:
            logger.info("[FUSION_DIAG] penalty: resonance=%.3f < -0.20 (dissonant) dissonance_penalty=%.2f",
                        resonance, dissonance_penalty)

        # Base Alpha Synthesis
        base_conviction = (whale_conf_decayed * 0.40) + (shans_conf_decayed * 0.35) + (phys_score * 0.25)

        # Toxicity: bounded piecewise modulation. Low tox neutral; moderate mild; high meaningful.
        # Hard veto gates tox>=0.88 upstream. exponential_decay preserved for other uses.
        tox_multiplier = QuantMath.bounded_tox_modulation(tox_score)

        # Entropy: zero or unproven entropy is explicit neutral — no false suppression.
        # Positive branch: slope=0.30, floor=0.70 — max entropy suppresses to 30%, not 90%.
        dynamic_entropy = min(1.0, ent_score + max(0.0, self._state.entropy_velocity * 2.0))
        if dynamic_entropy <= 0.0:
            ent_multiplier = 1.0
            entropy_neutralized = True
        else:
            ent_multiplier = max(0.70, 1.0 - (dynamic_entropy * 0.30))
            entropy_neutralized = False

        # Resonance: resonant modestly boosts conviction; non-resonant is neutral (not a penalty).
        resonance_bonus = 1.15 if is_resonant else 1.0

        # Kelly removed from Fusion — PositionSizing is the downstream Kelly sizing authority.
        pre_kelly_value = (
            base_conviction
            * tox_multiplier
            * ent_multiplier
            * resonance_bonus
            * dissonance_penalty
            * missing_penalty_factor
        )
        final_confidence = max(0.0, min(1.0, pre_kelly_value))

        self._telemetry["base_conviction"] = base_conviction
        self._telemetry["base_confidence"] = base_conviction
        self._telemetry["tox_score"] = tox_score
        self._telemetry["tox_multiplier"] = tox_multiplier
        self._telemetry["dynamic_entropy"] = dynamic_entropy
        self._telemetry["ent_multiplier"] = ent_multiplier
        self._telemetry["entropy_neutralized"] = entropy_neutralized
        self._telemetry["resonance_bonus"] = resonance_bonus
        self._telemetry["dissonance_penalty"] = dissonance_penalty
        self._telemetry["missing_penalty_factor"] = missing_penalty_factor
        self._telemetry["pre_kelly_value"] = pre_kelly_value
        self._telemetry["kelly_removed_from_fusion"] = True
        self._telemetry["final_confidence"] = final_confidence

        # ---------------------------------------------------------
        # PHASE 5: HYSTERESIS-DRIVEN ATTACK MODE
        # ---------------------------------------------------------
        attack_mode = False
        reason_flags = []

        is_exhausted = shans_superfluid >= 0.80

        if is_exhausted:
            final_confidence *= 0.35
            reason_flags.append(f"EXHAUSTION({shans_superfluid:.2f})")
            self._state.register_decision(False)
        else:
            base_attack_thresh = 0.72
            sustain_attack_thresh = 0.55
            
            dynamic_thresh = QuantMath.temperature_threshold(
                base_threshold=base_attack_thresh if not self._state.was_attack_mode else sustain_attack_thresh,
                entropy=ent_score,
                max_penalty=0.25
            )

            is_urgent = insider_urgency >= 0.60
            if final_confidence >= dynamic_thresh and is_urgent:
                attack_mode = True
                reason_flags.append(f"ATTACK_ENGAGED(Urgency:{insider_urgency:.2f})")
                
            self._state.register_decision(attack_mode)

        # ---------------------------------------------------------
        # PHASE 6: REGIME AUTHORIZATION (Strict Boolean Mapping)
        # ---------------------------------------------------------
        gamma_front_eligible = False
        sector_rotation_eligible = False
        shadow_front_eligible = False
        entropy_decoder_eligible = False  # Regime-gated; not universally on
        liquidity_void_eligible = False   # Default restrictive state
        
        preferred_sleeve = None
        deprioritized_sleeves = []
        regime_str = regime_type.value

        # DIAGNOSTIC: Log regime type before decision
        logger.info("[FUSION_DIAG] Regime type: %s", regime_type)

        if regime_type in (RegimeType.TRENDING_BULL, RegimeType.TRENDING_BEAR):
            sector_rotation_eligible = True
            preferred_sleeve = SleeveType.SECTOR_ROTATION.value
            deprioritized_sleeves = [SleeveType.SHADOW_FRONT.value, SleeveType.GAMMA_FRONT.value]
            logger.info("[FUSION_DIAG] Regime TRENDING → preferred_sleeve=SECTOR_ROTATION")
            
        elif regime_type == RegimeType.RANGING:
            shadow_front_eligible = True
            preferred_sleeve = SleeveType.SHADOW_FRONT.value
            sr_ranging = getattr(getattr(self.config, 'strategies', None), 'sector_rotation_ranging_eligible', False)
            if sr_ranging:
                sector_rotation_eligible = True
                deprioritized_sleeves = [SleeveType.GAMMA_FRONT.value]
                logger.info("[FUSION_DIAG] Regime RANGING (sr_ranging=True) → preferred_sleeve=SHADOW_FRONT, SR=secondary")
            else:
                deprioritized_sleeves = [SleeveType.GAMMA_FRONT.value, SleeveType.SECTOR_ROTATION.value]
                logger.info("[FUSION_DIAG] Regime RANGING → preferred_sleeve=SHADOW_FRONT")
            
        elif regime_type == RegimeType.CRISIS:
            gamma_front_eligible = True
            preferred_sleeve = SleeveType.GAMMA_FRONT.value
            deprioritized_sleeves = [SleeveType.SECTOR_ROTATION.value, SleeveType.SHADOW_FRONT.value]
            logger.info("[FUSION_DIAG] Regime CRISIS → preferred_sleeve=GAMMA_FRONT")
            
        elif regime_type == RegimeType.UNKNOWN:
            preferred_sleeve = SleeveType.FLV.value
            liquidity_void_eligible = True   # STAGE 2-D2: align eligibility with preferred_sleeve=FLV
            logger.info("[FUSION_DIAG] Regime UNKNOWN → preferred_sleeve=FLV")
        else:
            logger.info("[FUSION_DIAG] Regime UNHANDLED: %s → preferred_sleeve=None", regime_type)

        # DIAGNOSTIC: Log final preferred_sleeve
        logger.info("[FUSION_DIAG] Final: attack_mode=%s, preferred_sleeve=%s, confidence=%.4f",
                   attack_mode, preferred_sleeve, final_confidence)

        logger.info(
            "[FUSION_BREAKDOWN]\nsymbol=%s\nregime=%s\nwhale_dir=%d\n"
            "shans_bias=%s\nshans_superfluid=%.4f\n"
            "tox_score=%.4f\ntox_multiplier=%.4f\n"
            "dynamic_entropy=%.4f\nent_multiplier=%.4f\nentropy_neutralized=%s\n"
            "resonance=%.4f\nresonance_bonus=%.4f\n"
            "base_confidence=%.4f\npre_kelly=%.4f\n"
            "final_confidence=%.4f\nattack_mode=%s\npreferred_sleeve=%s\n"
            "kelly_removed_from_fusion=True",
            getattr(self.config, 'symbol', 'UNKNOWN'),
            regime_str,
            whale_dir,
            shans_bias_str,
            shans_superfluid,
            tox_score,
            tox_multiplier,
            dynamic_entropy,
            ent_multiplier,
            entropy_neutralized,
            resonance,
            resonance_bonus,
            base_conviction,
            pre_kelly_value,
            final_confidence,
            attack_mode,
            preferred_sleeve,
        )

        # ---------------------------------------------------------
        # PHASE 7: DETERMINISTIC ASSEMBLY
        # ---------------------------------------------------------
        base_reason = f"DIR:{whale_dir} | CONF:{final_confidence:.2f} | REG:{regime_str} | TOX:{tox_score:.2f}"
        if reason_flags:
            base_reason += f" | [{' | '.join(reason_flags)}]"

        decision = FusionDecision(
            exchange_ts_ns=current_ts_ns,
            attack_mode=attack_mode,
            confidence=final_confidence,
            
            # Strict Boolean Eligibility Flags
            gamma_front_eligible=gamma_front_eligible,
            shadow_front_eligible=shadow_front_eligible,
            sector_rotation_eligible=sector_rotation_eligible,
            entropy_decoder_eligible=entropy_decoder_eligible,
            liquidity_void_eligible=liquidity_void_eligible,
            
            # Router Hints
            preferred_sleeve=preferred_sleeve,
            deprioritized_sleeves=deprioritized_sleeves,
            
            # Context
            regime=regime_str,
            reason=base_reason,
            
            # Analytical Scores
            shans_superfluid_score=shans_superfluid,
            shans_bias=shans_bias_str,
            shans_confidence=shans_conf_decayed,
            physical_verification_score=phys_score
        )

        logger.info(
            "[FUSION_DIAG] DECISION: attack_mode=%s confidence=%.4f preferred_sleeve=%s regime=%s reason=%s",
            attack_mode,
            final_confidence,
            preferred_sleeve,
            regime_str,
            base_reason,
        )
        self._last_fusion = decision
        return decision

    # =========================================================================
    # VETO ARCHITECTURE
    # =========================================================================

    def _issue_hard_veto(self, current_ts_ns: int, reason: str) -> FusionDecision:
        """
        Constructs a deterministic dead-state decision.
        Preserves observable metrics for dashboard analytics while completely 
        severing operational execution downstream.
        """
        self._telemetry["vetoed"] = True
        self._telemetry["veto_reason"] = reason

        # DIAGNOSTIC: Log veto reason
        logger.info("[FUSION_DIAG] VETO: %s", reason)
        _resonance_val = self._telemetry.get("vector_resonance", "N/A")
        logger.info(
            "[FUSION_VETO_DETAIL]\nreason=%s\nresonance=%s\nthreshold=N/A",
            reason,
            f"{_resonance_val:.4f}" if isinstance(_resonance_val, float) else _resonance_val,
        )

        shans_superfluid = 0.0
        shans_bias_str = "neutral"
        shans_conf = 0.0
        phys_score = 0.0
        regime_str = RegimeType.UNKNOWN.value

        if "shans_curve" in self._cache:
            p, _ = self._cache["shans_curve"]
            shans_superfluid = max(0.0, min(1.0, float(p.shans_superfluid_score)))
            shans_bias_str = self._bridge_shans_bias(float(p.shans_bias))
            shans_conf = max(0.0, min(1.0, float(p.shans_confidence)))
            
        if "physical" in self._cache:
            p, _ = self._cache["physical"]
            phys_score = max(0.0, min(1.0, float(p.get("health_score", 0.0))))
            
        if "regime" in self._cache:
            r_tuple, _ = self._cache["regime"]
            regime_str = r_tuple[0].value

        self._state.register_decision(False)

        decision = FusionDecision(
            exchange_ts_ns=current_ts_ns,
            attack_mode=False,
            confidence=0.0,
            
            gamma_front_eligible=False,
            shadow_front_eligible=False,
            sector_rotation_eligible=False,
            entropy_decoder_eligible=False,
            liquidity_void_eligible=False,
            
            preferred_sleeve=None,
            deprioritized_sleeves=[],
            
            regime=regime_str,
            reason=f"VETO: {reason}",
            
            shans_superfluid_score=shans_superfluid,
            shans_bias=shans_bias_str,
            shans_confidence=shans_conf,
            physical_verification_score=phys_score
        )
        
        self._last_fusion = decision
        return decision
