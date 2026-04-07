"""
app/brain/signal_fusion.py

Deterministic, replay-safe fusion engine for Poverty Killer (reboot architecture).
Consumes directional, confidence, and veto signals from:
- EntropyDecoder (structural confidence / collapse)
- RegimeDetector (regime classification)
- ShansCurve (doctrinal fields: bias, confidence, superfluid)
- ToxicityEngine (hostility suppression)
- WhaleFlowEngine (directional edge)
- InsiderSignalEngine (urgency/escalation)

Output: FusionDecision with attack_mode, confidence, sleeve eligibility.
"""

from typing import Dict, Optional, Any, Union
from dataclasses import dataclass
from decimal import Decimal

import numpy as np

from app.models.enums import CollapseQuality, RegimeType
from app.models.fusion import FusionDecision
from app.models.entropy_score import EntropyScore
from app.brain.entropy_decoder import EntropyDecoder
from app.brain.shans_curve import ShansCurveSignal


@dataclass
class CachedRegimeState:
    """Cached regime state with timestamp for staleness detection."""
    regime: RegimeType
    exchange_ts_ns: int
    instrument_id: str
    liquidity_usd: float


@dataclass
class CachedShansState:
    """Cached Shan's Curve state."""
    superfluid_score: float
    bias: int
    confidence: float
    exchange_ts_ns: int


@dataclass
class CachedWhaleState:
    """Cached Whale directional state."""
    direction: int
    score: float
    exchange_ts_ns: int


@dataclass
class CachedEntropyState:
    """Cached Entropy state per symbol/side."""
    entropy_score: EntropyScore
    collapse_quality: CollapseQuality
    exchange_ts_ns: int


@dataclass
class CachedInsiderState:
    """Cached Insider urgency state."""
    urgency: float
    exchange_ts_ns: int


class SignalFusion:
    """
    Role-pure fusion engine for reboot architecture.
    Directional inputs → directional output.
    Confidence/veto inputs → confidence/suppression.
    No conflation.
    """

    STALENESS_THRESHOLD_NS = 5 * 1_000_000_000

    def __init__(self, config: Optional[Union[Dict[str, Any], Any]] = None, _legacy_compat: bool = False):
        """
        Initialize fusion engine with optional configuration.
        
        Args:
            config: Either a dict with configuration keys or an object with
                    attribute-style configuration. Supports both calling patterns
                    for caller family compatibility.
            _legacy_compat: Legacy compatibility parameter for caller family.
        """
        self.config = config
        self.staleness_threshold_ns = self.STALENESS_THRESHOLD_NS
        self.shans_weight = 0.7
        self.attack_mode_persistence_required = 2
        
        if config is not None:
            if isinstance(config, dict):
                self.staleness_threshold_ns = config.get('staleness_threshold_ns', self.STALENESS_THRESHOLD_NS)
                self.shans_weight = float(config.get('shans_weight', 0.7))
                self.attack_mode_persistence_required = int(config.get('attack_mode_persistence_required', 2))
            else:
                if hasattr(config, 'staleness_threshold_ns'):
                    self.staleness_threshold_ns = getattr(config, 'staleness_threshold_ns', self.STALENESS_THRESHOLD_NS)
                if hasattr(config, 'shans_weight'):
                    self.shans_weight = float(getattr(config, 'shans_weight', 0.7))
                if hasattr(config, 'attack_mode_persistence_required'):
                    self.attack_mode_persistence_required = int(getattr(config, 'attack_mode_persistence_required', 2))
        
        self._cached_regime: Optional[CachedRegimeState] = None
        self._cached_shans: Optional[CachedShansState] = None
        self._cached_whale: Optional[CachedWhaleState] = None
        self._cached_entropy: Dict[str, CachedEntropyState] = {}
        self._cached_insider: Optional[CachedInsiderState] = None
        
        self._last_decision: Optional[FusionDecision] = None
        self._attack_mode_consecutive: int = 0

    def _is_stale(self, timestamp_ns: int, current_ts_ns: int) -> bool:
        return (current_ts_ns - timestamp_ns) > self.staleness_threshold_ns

    def _get_current_timestamp_from_cache(self) -> int:
        """Derive the maximum lawful cached timestamp for freshness checks."""
        max_ts = 0
        if self._cached_regime is not None:
            max_ts = max(max_ts, self._cached_regime.exchange_ts_ns)
        if self._cached_shans is not None:
            max_ts = max(max_ts, self._cached_shans.exchange_ts_ns)
        if self._cached_whale is not None:
            max_ts = max(max_ts, self._cached_whale.exchange_ts_ns)
        if self._cached_insider is not None:
            max_ts = max(max_ts, self._cached_insider.exchange_ts_ns)
        for cached in self._cached_entropy.values():
            max_ts = max(max_ts, cached.exchange_ts_ns)
        return max_ts

    def _bridge_shans_bias(self, bias_int: int) -> str:
        if bias_int == 1:
            return "bullish"
        elif bias_int == -1:
            return "bearish"
        return "neutral"

    def _bridge_regime(self, regime: RegimeType) -> str:
        return regime.value if hasattr(regime, 'value') else str(regime)

    def get_current_regime(self) -> RegimeType:
        """Returns cached regime without freshness guarantee. Caller must check staleness."""
        if self._cached_regime is None:
            return RegimeType.UNKNOWN
        return self._cached_regime.regime

    def update_shans(self, order_book: Any, regime: RegimeType, physical_verification: Optional[Any] = None) -> None:
        superfluid_score = getattr(order_book, 'shans_superfluid_score', 0.0)
        bias = getattr(order_book, 'shans_bias', 0)
        confidence = getattr(order_book, 'shans_confidence', 0.0)
        exchange_ts_ns = getattr(order_book, 'exchange_ts_ns', 0)
        
        verification_score = 1.0
        if physical_verification is not None:
            verification_score = getattr(physical_verification, 'score', 1.0)
            if hasattr(physical_verification, 'is_severe_failure'):
                if physical_verification.is_severe_failure():
                    verification_score = 0.0
        
        final_confidence = float(np.clip(confidence * verification_score, 0.0, 1.0))
        
        self._cached_shans = CachedShansState(
            superfluid_score=float(np.clip(superfluid_score, 0.0, 1.0)),
            bias=int(np.clip(bias, -1, 1)),
            confidence=final_confidence,
            exchange_ts_ns=exchange_ts_ns,
        )

    def update_whale(self, candle: Any) -> None:
        direction = getattr(candle, 'whale_direction', 0)
        score = getattr(candle, 'whale_confidence', 0.0)
        exchange_ts_ns = getattr(candle, 'exchange_ts_ns', 0)
        
        self._cached_whale = CachedWhaleState(
            direction=int(np.clip(direction, -1, 1)),
            score=float(np.clip(score, 0.0, 1.0)),
            exchange_ts_ns=exchange_ts_ns,
        )

    def update_regime(self, candles: Any, instrument_id: str, liquidity_usd: float, exchange_ts_ns: int) -> None:
        if hasattr(candles, 'regime') and candles.regime is not None:
            regime = candles.regime
        elif hasattr(candles, 'get_regime'):
            regime = candles.get_regime()
        else:
            regime = RegimeType.UNKNOWN
        
        self._cached_regime = CachedRegimeState(
            regime=regime,
            exchange_ts_ns=exchange_ts_ns,
            instrument_id=instrument_id,
            liquidity_usd=liquidity_usd,
        )

    def get_macro_signal(self, exchange_ts_ns: int, whale_score: float) -> float:
        effective_whale_score = whale_score
        
        if self._cached_whale is not None:
            if not self._is_stale(self._cached_whale.exchange_ts_ns, exchange_ts_ns):
                effective_whale_score = max(effective_whale_score, self._cached_whale.score)
        
        base_suppression = 1.0
        
        if self._cached_regime is not None:
            if self._is_stale(self._cached_regime.exchange_ts_ns, exchange_ts_ns):
                base_suppression = 0.5
            elif self._cached_regime.regime == RegimeType.CRISIS:
                base_suppression = 0.3
            elif self._cached_regime.regime == RegimeType.RANGING:
                base_suppression = 0.7
        else:
            base_suppression = 0.5
        
        suppression = base_suppression * (0.5 + 0.5 * effective_whale_score)
        return float(np.clip(suppression, 0.0, 1.0))

    def get_insider_signal(self) -> float:
        """Returns cached insider urgency only if fresh, otherwise 0.0."""
        if self._cached_insider is None:
            return 0.0
        
        current_ts = self._get_current_timestamp_from_cache()
        if current_ts == 0:
            return 0.0
        
        if self._is_stale(self._cached_insider.exchange_ts_ns, current_ts):
            return 0.0
        
        return self._cached_insider.urgency

    def update_insider(self, urgency: float, exchange_ts_ns: int) -> None:
        self._cached_insider = CachedInsiderState(
            urgency=float(np.clip(urgency, 0.0, 2.0)),
            exchange_ts_ns=exchange_ts_ns,
        )

    def update_entropy(self, symbol: str, side: str, exchange_ts_ns: int, regime: RegimeType, entropy_decoder: Optional[EntropyDecoder] = None) -> None:
        key = f"{symbol}_{side}"
        
        entropy_score = None
        collapse_quality = CollapseQuality.NONE
        
        if entropy_decoder is not None:
            entropy_score = entropy_decoder.get_current(symbol)
            if entropy_score is not None and hasattr(entropy_score, 'collapse_quality'):
                collapse_quality = entropy_score.collapse_quality
        
        if entropy_score is None:
            from app.models.entropy_score import EntropyScore
            entropy_score = EntropyScore(
                symbol=symbol,
                timestamp=exchange_ts_ns,
                entropy=Decimal('0.5'),
                is_collapsed=False,
                predicted_magnitude=Decimal('1.0'),
                confidence=Decimal('0.5'),
                samples_used=0,
            )
        
        self._cached_entropy[key] = CachedEntropyState(
            entropy_score=entropy_score,
            collapse_quality=collapse_quality,
            exchange_ts_ns=exchange_ts_ns,
        )

    def fuse(
        self,
        regime: Optional[RegimeType] = None,
        whale_score: Optional[float] = None,
        macro_signal: Optional[float] = None,
        insider_signal: Optional[float] = None,
        order_book: Optional[Any] = None
    ) -> FusionDecision:
        """
        Fuse all signals into a lawful FusionDecision.
        
        Supports two calling patterns:
        1. Explicit arguments (legacy direct call)
        2. Cached state (orchestrator reboot path)
        
        When arguments are None, values are taken from cached state.
        """
        exchange_ts_ns = 0
        if order_book is not None:
            exchange_ts_ns = getattr(order_book, 'exchange_ts_ns', 0)
        else:
            exchange_ts_ns = self._get_current_timestamp_from_cache()
        
        effective_regime = regime
        if effective_regime is None and self._cached_regime is not None:
            if exchange_ts_ns > 0 and not self._is_stale(self._cached_regime.exchange_ts_ns, exchange_ts_ns):
                effective_regime = self._cached_regime.regime
        if effective_regime is None:
            effective_regime = RegimeType.UNKNOWN
        
        shans_superfluid = 0.0
        shans_bias_int = 0
        shans_confidence = 0.0
        
        if order_book is not None:
            shans_superfluid = getattr(order_book, 'shans_superfluid_score', 0.0)
            shans_bias_int = getattr(order_book, 'shans_bias', 0)
            shans_confidence = getattr(order_book, 'shans_confidence', 0.0)
        
        if self._cached_shans is not None:
            if exchange_ts_ns > 0 and not self._is_stale(self._cached_shans.exchange_ts_ns, exchange_ts_ns):
                shans_superfluid = max(shans_superfluid, self._cached_shans.superfluid_score)
                if shans_bias_int == 0:
                    shans_bias_int = self._cached_shans.bias
                shans_confidence = max(shans_confidence, self._cached_shans.confidence)
        
        shans_bias_str = self._bridge_shans_bias(shans_bias_int)
        
        entropy_score = None
        entropy_conf = 0.5
        entropy_collapsed = False
        entropy_collapse_quality = CollapseQuality.NONE
        
        if order_book is not None:
            entropy_score = getattr(order_book, 'entropy_score', None)
        
        if entropy_score is not None:
            entropy_conf = float(entropy_score.confidence) if entropy_score.confidence else 0.5
            entropy_collapsed = entropy_score.is_collapsed
            if hasattr(entropy_score, 'collapse_quality'):
                entropy_collapse_quality = entropy_score.collapse_quality
        else:
            for cached in self._cached_entropy.values():
                if exchange_ts_ns > 0 and not self._is_stale(cached.exchange_ts_ns, exchange_ts_ns):
                    entropy_score = cached.entropy_score
                    entropy_conf = float(entropy_score.confidence) if entropy_score.confidence else 0.5
                    entropy_collapsed = entropy_score.is_collapsed
                    entropy_collapse_quality = cached.collapse_quality
                    break
        
        toxicity_score = getattr(order_book, 'toxicity_score', 0.0) if order_book is not None else 0.0
        
        whale_direction = 0
        whale_conf = whale_score if whale_score is not None else 0.0
        
        if self._cached_whale is not None:
            if exchange_ts_ns > 0 and not self._is_stale(self._cached_whale.exchange_ts_ns, exchange_ts_ns):
                whale_direction = self._cached_whale.direction
                whale_conf = max(whale_conf, self._cached_whale.score)
        
        effective_insider = insider_signal if insider_signal is not None else 0.0
        if self._cached_insider is not None:
            if exchange_ts_ns > 0 and not self._is_stale(self._cached_insider.exchange_ts_ns, exchange_ts_ns):
                effective_insider = max(effective_insider, self._cached_insider.urgency)
        
        effective_macro = macro_signal if macro_signal is not None else 1.0
        if effective_macro is None:
            effective_macro = 1.0
        
        directions = []
        weights = []
        
        if whale_direction != 0:
            directions.append(whale_direction)
            weights.append(whale_conf)
        
        if shans_bias_int != 0:
            directions.append(shans_bias_int)
            weights.append(self.shans_weight)
        
        insider_mult = 1.0 + min(1.0, effective_insider)
        
        if not directions:
            consensus_direction = 0
        else:
            weighted_sum = sum(d * w * (insider_mult if i == 0 else 1.0) for i, (d, w) in enumerate(zip(directions, weights)))
            total_weight = sum(w * (insider_mult if i == 0 else 1.0) for i, w in enumerate(weights))
            raw_consensus = weighted_sum / (total_weight + 1e-8)
            consensus_direction = int(np.sign(raw_consensus)) if abs(raw_consensus) > 0.2 else 0
        
        base_confidence = 0.5
        entropy_factor = 0.4 + 0.6 * entropy_conf
        shans_factor = 0.4 + 0.6 * shans_confidence
        whale_factor = 0.7 + 0.3 * whale_conf
        macro_factor = effective_macro
        insider_factor = 1.0 + min(0.5, effective_insider * 0.25)
        toxicity_penalty = 1.0 - min(1.0, toxicity_score / 100.0)
        
        confidence = base_confidence * entropy_factor * shans_factor * whale_factor * macro_factor * insider_factor * toxicity_penalty
        confidence = float(np.clip(confidence, 0.0, 1.0))
        
        attack_mode = False
        if shans_superfluid > 0.8 and effective_insider > 0.5:
            self._attack_mode_consecutive += 1
            if self._attack_mode_consecutive >= self.attack_mode_persistence_required:
                attack_mode = True
        else:
            self._attack_mode_consecutive = 0
        
        veto_active = False
        veto_reason = None
        
        if entropy_collapsed and entropy_collapse_quality == CollapseQuality.EXTREME:
            veto_active = True
            veto_reason = "entropy_extreme_collapse"
        
        if not veto_active and toxicity_score >= 80.0:
            veto_active = True
            veto_reason = f"toxicity_{toxicity_score:.0f}"
        
        shadow_front_eligible = False
        liquidity_void_eligible = False
        gamma_front_eligible = False
        sector_rotation_eligible = False
        entropy_decoder_eligible = False
        
        if entropy_conf > 0.6 and shans_confidence > 0.4:
            shadow_front_eligible = True
            entropy_decoder_eligible = True
        
        if entropy_collapsed and entropy_collapse_quality in (CollapseQuality.EXTREME, CollapseQuality.WEAK):
            shadow_front_eligible = False
        
        if entropy_conf > 0.5 and effective_regime in (RegimeType.RANGING, RegimeType.CRISIS):
            liquidity_void_eligible = True
        
        if toxicity_score > 60.0:
            liquidity_void_eligible = False
        
        if entropy_conf > 0.7 and shans_confidence > 0.5:
            gamma_front_eligible = True
        
        if effective_regime in (RegimeType.TRENDING_BULL, RegimeType.TRENDING_BEAR):
            sector_rotation_eligible = True
        
        physical_verification_score = 0.5
        if entropy_score is not None and hasattr(entropy_score, 'physical_verification_score'):
            physical_verification_score = float(entropy_score.physical_verification_score)
        
        if veto_active:
            shadow_front_eligible = False
            liquidity_void_eligible = False
            gamma_front_eligible = False
            sector_rotation_eligible = False
            entropy_decoder_eligible = False
            confidence = 0.0
            attack_mode = False
        
        preferred_sleeve = None
        if not veto_active:
            if shadow_front_eligible and shans_confidence > 0.7:
                preferred_sleeve = "shadow_front"
            elif gamma_front_eligible and entropy_conf > 0.7:
                preferred_sleeve = "gamma_front"
            elif liquidity_void_eligible:
                preferred_sleeve = "liquidity_void"
            elif sector_rotation_eligible:
                preferred_sleeve = "sector_rotation"
        
        deprioritized_sleeves = []
        if liquidity_void_eligible and not veto_active:
            deprioritized_sleeves.append("liquidity_void")
        if sector_rotation_eligible and not veto_active:
            deprioritized_sleeves.append("sector_rotation")
        
        decision = FusionDecision(
            exchange_ts_ns=exchange_ts_ns,
            attack_mode=attack_mode,
            confidence=confidence,
            shadow_front_eligible=shadow_front_eligible,
            liquidity_void_eligible=liquidity_void_eligible,
            entropy_decoder_eligible=entropy_decoder_eligible,
            gamma_front_eligible=gamma_front_eligible,
            sector_rotation_eligible=sector_rotation_eligible,
            preferred_sleeve=preferred_sleeve,
            deprioritized_sleeves=deprioritized_sleeves,
            reason=self._build_reason(consensus_direction, veto_active, veto_reason, attack_mode),
            regime=self._bridge_regime(effective_regime),
            physical_verification_score=physical_verification_score,
            shans_superfluid_score=shans_superfluid,
            shans_bias=shans_bias_str,
            shans_confidence=shans_confidence,
        )
        
        self._last_decision = decision
        return decision

    def _build_reason(self, direction: int, veto_active: bool, veto_reason: Optional[str], attack_mode: bool) -> str:
        parts = []
        if direction == 1:
            parts.append("bullish")
        elif direction == -1:
            parts.append("bearish")
        else:
            parts.append("neutral")
        
        if veto_active and veto_reason:
            parts.append(f"veto({veto_reason})")
        
        if attack_mode:
            parts.append("attack_mode")
        
        return ";".join(parts) if parts else "neutral"

    def get_last_decision(self) -> Optional[FusionDecision]:
        return self._last_decision

    def reset(self) -> None:
        self._cached_regime = None
        self._cached_shans = None
        self._cached_whale = None
        self._cached_entropy.clear()
        self._cached_insider = None
        self._last_decision = None
        self._attack_mode_consecutive = 0