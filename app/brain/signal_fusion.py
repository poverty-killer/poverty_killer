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
"""

import math
import logging
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass

# Lawful contracts imported strictly from provided repo truth
from app.models.fusion import FusionDecision
from app.models.enums import RegimeType
from app.constants import SleeveType

logger = logging.getLogger(__name__)


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

        # ---------------------------------------------------------
        # PHASE 1: TEMPORAL VETO (Staleness Enforcement)
        # ---------------------------------------------------------
        for sig, ttl in self._ttl_ns.items():
            if sig not in self._cache:
                return self._issue_hard_veto(current_ts_ns, f"Missing requisite signal [{sig}]")
            
            _, ts = self._cache[sig]
            age_ns = current_ts_ns - ts
            if age_ns > ttl:
                return self._issue_hard_veto(current_ts_ns, f"Stale signal [{sig}] (Age: {age_ns / 1e9:.2f}s)")

        # ---------------------------------------------------------
        # PHASE 2: STRICT CONTRACT EXTRACTION
        # ---------------------------------------------------------
        
        # ToxicityAlert
        tox_payload, _ = self._cache["toxicity"]
        tox_score = float(tox_payload.toxicity_score)
        tox_is_toxic = bool(tox_payload.is_toxic)
        
        # EntropyScore
        ent_payload, _ = self._cache["entropy"]
        ent_score = float(ent_payload.entropy)
        
        # Kinematic Tracking
        self._state.update_kinematics(ent_score, tox_score, current_ts_ns)
        self._telemetry["entropy_velocity"] = self._state.entropy_velocity
        self._telemetry["toxicity_velocity"] = self._state.toxicity_velocity
        
        # Physical Validator (Dict contract proven)
        phys_dict, _ = self._cache["physical"]
        phys_score = float(phys_dict.get("health_score", 0.0))
        
        # WhaleFlowAlert (direction is WhaleDirection Enum)
        whale_payload, whale_ts = self._cache["whale_flow"]
        whale_dir = int(whale_payload.direction.value)
        whale_conf_raw = float(whale_payload.confidence)
        
        whale_age = current_ts_ns - whale_ts
        whale_discount = QuantMath.temporal_discount(whale_age, self._half_life_ns["whale_flow"])
        whale_conf_decayed = whale_conf_raw * whale_discount
        
        # ShansCurveSignal
        shans_payload, shans_ts = self._cache["shans_curve"]
        shans_superfluid = float(shans_payload.shans_superfluid_score)
        shans_bias_raw = float(shans_payload.shans_bias)
        shans_conf_raw = float(shans_payload.shans_confidence)
        
        shans_age = current_ts_ns - shans_ts
        shans_discount = QuantMath.temporal_discount(shans_age, self._half_life_ns["shans_curve"])
        shans_conf_decayed = shans_conf_raw * shans_discount
        shans_bias_str = self._bridge_shans_bias(shans_bias_raw)
        
        # InsiderSignalSnapshot (Gated extraction)
        insider_payload, insider_ts = self._cache["insider"]
        if bool(insider_payload.active) and not bool(insider_payload.invalidated):
            insider_urgency_raw = float(insider_payload.urgency) 
        else:
            insider_urgency_raw = 0.0
            
        insider_age = current_ts_ns - insider_ts
        insider_urgency = insider_urgency_raw * QuantMath.temporal_discount(insider_age, self._half_life_ns["insider"])
        
        # RegimeDetector (Returns exactly Tuple[RegimeType, float])
        regime_payload, _ = self._cache["regime"]
        regime_type = regime_payload[0]

        # ---------------------------------------------------------
        # PHASE 3: CRITICAL HAZARD GATING (Absolute Boundaries)
        # ---------------------------------------------------------
        if whale_dir == 0:
            return self._issue_hard_veto(current_ts_ns, "Whale Vector Neutral")
            
        if tox_is_toxic or tox_score >= 0.88:
            return self._issue_hard_veto(current_ts_ns, f"Toxicity Critical (Score:{tox_score:.2f})")
            
        # Kinematic Veto: Toxicity rocketing upward
        if tox_score > 0.60 and self._state.toxicity_velocity > 0.15:
             return self._issue_hard_veto(current_ts_ns, f"Toxicity Spike (+{self._state.toxicity_velocity:.2f}/s)")
             
        if ent_score >= 0.95:
            return self._issue_hard_veto(current_ts_ns, f"Entropy Disintegration ({ent_score:.2f})")
            
        if phys_score <= 0.15:
            return self._issue_hard_veto(current_ts_ns, f"Physical Validator Collapse ({phys_score:.2f})")

        # ---------------------------------------------------------
        # PHASE 4: VECTOR RESONANCE & NON-LINEAR MODULATION
        # ---------------------------------------------------------
        resonance = QuantMath.vector_resonance(whale_dir, whale_conf_decayed, shans_bias_raw)
        self._telemetry["vector_resonance"] = resonance
        
        is_resonant = resonance > 0.10
        is_dissonant = resonance < -0.20

        if is_dissonant:
            return self._issue_hard_veto(current_ts_ns, f"Vector Dissonance (Resonance: {resonance:.2f})")

        # Base Alpha Synthesis
        base_conviction = (whale_conf_decayed * 0.40) + (shans_conf_decayed * 0.35) + (phys_score * 0.25)

        # Exponential hazard suppression
        tox_multiplier = QuantMath.exponential_decay(tox_score, steepness=3.5)
        
        # Entropy suppresses confidence, but rising entropy (velocity) suppresses it harder
        dynamic_entropy = min(1.0, ent_score + max(0.0, self._state.entropy_velocity * 2.0))
        ent_multiplier = max(0.1, 1.0 - (dynamic_entropy * 0.65))
        
        resonance_bonus = 1.15 if is_resonant else 0.85

        final_confidence = base_conviction * tox_multiplier * ent_multiplier * resonance_bonus
        final_confidence = QuantMath.kelly_calibration_curve(final_confidence)
        final_confidence = max(0.0, min(1.0, final_confidence))
        
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
        flv_eligible = True             # Universal baseline scavenger
        liquidity_void_eligible = False # Default restrictive state
        
        preferred_sleeve = None
        deprioritized_sleeves = []
        regime_str = regime_type.value

        if regime_type in (RegimeType.TRENDING_BULL, RegimeType.TRENDING_BEAR):
            sector_rotation_eligible = True
            preferred_sleeve = SleeveType.SECTOR_ROTATION.value
            deprioritized_sleeves = [SleeveType.SHADOW_FRONT.value, SleeveType.GAMMA_FRONT.value]
            
        elif regime_type == RegimeType.RANGING:
            shadow_front_eligible = True
            preferred_sleeve = SleeveType.SHADOW_FRONT.value
            deprioritized_sleeves = [SleeveType.GAMMA_FRONT.value, SleeveType.SECTOR_ROTATION.value]
            
        elif regime_type == RegimeType.CRISIS:
            gamma_front_eligible = True
            preferred_sleeve = SleeveType.GAMMA_FRONT.value
            deprioritized_sleeves = [SleeveType.SECTOR_ROTATION.value, SleeveType.SHADOW_FRONT.value]
            
        elif regime_type == RegimeType.UNKNOWN:
            preferred_sleeve = SleeveType.FLV.value

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
            flv_eligible=flv_eligible,
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
            flv_eligible=False,
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