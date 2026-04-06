# ============================================
# SHAN'S CURVE v2 INTEGRATION SCRIPT
# Creates all necessary files and updates existing ones
# Run from: C:\Users\shahn\OneDrive\Desktop\poverty_killer
# ============================================

$projectRoot = "C:\Users\shahn\OneDrive\Desktop\poverty_killer"
Set-Location $projectRoot

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Shan's Curve v2 Integration" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# ============================================
# FILE 1: Update requirements.txt
# ============================================
Write-Host "Updating requirements.txt..." -ForegroundColor Yellow

# Check if scipy is already in requirements.txt
$reqContent = Get-Content "requirements.txt" -Raw
if ($reqContent -notmatch "scipy") {
    Add-Content "requirements.txt" "`n# Scientific computing (Shan's Curve v2)"
    Add-Content "requirements.txt" "scipy>=1.10.0"
    Add-Content "requirements.txt" "scikit-learn>=1.2.0"
    Write-Host "  ✓ Added scipy and scikit-learn to requirements.txt" -ForegroundColor Green
} else {
    Write-Host "  ✓ scipy already present" -ForegroundColor Gray
}

# ============================================
# FILE 2: CREATE app/brain/shans_curve.py
# ============================================
Write-Host ""
Write-Host "Creating app/brain/shans_curve.py..." -ForegroundColor Yellow

@'
"""
Shan's Curve v2 - Non-Linear Liquidity Reflexivity Strategy
Detects 'Superfluid' market states where price moves on near-zero volume.
Enhanced with polynomial fitting, adaptive thresholds, entropy integration.
Unique to Poverty Killer V1 - 2026 Institutional Grade.
"""

import numpy as np
import logging
from typing import Dict, Optional, Tuple, List
from dataclasses import dataclass
from collections import deque
from scipy.signal import savgol_filter

from app.models import OrderBookSnapshot, EntropyScore
from app.constants import RegimeType

logger = logging.getLogger(__name__)


@dataclass
class CurvatureSignal:
    """Signal from Shan's Curve analysis."""
    superfluid_score: float
    bias: str
    ask_curvature: float
    bid_curvature: float
    void_depth: float
    fill_rate: float
    curvature_velocity: float
    confidence: float


class ShansCurve:
    """
    Enhanced Shan's Curve detector.
    Uses polynomial fitting for robust curvature estimation.
    Integrates entropy decay for magnitude prediction.
    Adaptive thresholds based on historical volatility.
    """

    def __init__(
        self,
        base_sensitivity: float = 2.5,
        fit_degree: int = 2,
        smoothing_window: int = 5,
        velocity_window: int = 3
    ):
        """
        Initialize Shan's Curve detector.

        Args:
            base_sensitivity: Base threshold for curvature detection
            fit_degree: Polynomial degree for curvature fitting (2 = quadratic)
            smoothing_window: Window for Savitzky-Golay smoothing
            velocity_window: Window for curvature velocity calculation
        """
        self.base_sensitivity = base_sensitivity
        self.fit_degree = fit_degree
        self.smoothing_window = smoothing_window
        self.velocity_window = velocity_window

        # Historical tracking
        self._curvature_history: deque = deque(maxlen=100)
        self._void_depth_history: deque = deque(maxlen=100)
        self._fill_rate_history: deque = deque(maxlen=100)
        self._last_entropy_score: Optional[EntropyScore] = None

        # Adaptive threshold
        self._threshold_history: deque = deque(maxlen=50)
        self._current_threshold = base_sensitivity

        logger.info(f"ShansCurve v2 initialized: sensitivity={base_sensitivity}, degree={fit_degree}")

    def calculate_curvature_poly(self, levels: List[Tuple[float, float]]) -> float:
        """
        Calculate curvature using polynomial fitting.
        More robust than simple gradient.

        Args:
            levels: List of (price, size) tuples

        Returns:
            Curvature value (positive = convex, negative = concave/void)
        """
        if len(levels) < 5:
            return 0.0

        # Extract prices and cumulative sizes
        prices = np.array([p for p, _ in levels])
        sizes = np.array([s for _, s in levels])

        # Normalize prices to avoid numerical issues
        price_span = prices[-1] - prices[0]
        if price_span == 0:
            return 0.0
        norm_prices = (prices - prices[0]) / price_span

        # Cumulative depth (liquidity absorbed as you move into the book)
        cum_depth = np.cumsum(sizes)

        # Apply Savitzky-Golay smoothing if enough points
        if len(norm_prices) >= self.smoothing_window:
            cum_depth = savgol_filter(cum_depth, self.smoothing_window, 2)

        # Fit polynomial
        try:
            coeffs = np.polyfit(norm_prices, cum_depth, self.fit_degree)
            # Second derivative = curvature
            # For quadratic: 2 * coeffs[0]
            if self.fit_degree >= 2:
                curvature = 2 * coeffs[0]
            else:
                curvature = coeffs[0]
        except (np.linalg.LinAlgError, ValueError):
            return 0.0

        return curvature

    def calculate_curvature_velocity(self) -> float:
        """
        Calculate rate of change of curvature (acceleration).

        Returns:
            Curvature velocity (positive = becoming more convex)
        """
        if len(self._curvature_history) < self.velocity_window + 1:
            return 0.0

        recent = list(self._curvature_history)[-self.velocity_window - 1:]
        velocities = [recent[i] - recent[i-1] for i in range(1, len(recent))]
        return np.mean(velocities)

    def calculate_fill_rate(self, book: OrderBookSnapshot, side: str, levels: int = 3) -> float:
        """
        Calculate how fast orders are being consumed at the edge.

        Args:
            book: Current order book
            side: "bids" or "asks"
            levels: Number of levels to analyze

        Returns:
            Fill rate (negative = consumption)
        """
        if side == "bids":
            top_levels = book.bids[:levels]
            if not top_levels:
                return 0.0
            current_size = top_levels[0][1]

            if len(self._fill_rate_history) > 0:
                avg_size = np.mean(list(self._fill_rate_history)[-20:])
                if avg_size > 0:
                    return (current_size - avg_size) / avg_size

        else:  # asks
            top_levels = book.asks[:levels]
            if not top_levels:
                return 0.0
            current_size = top_levels[0][1]

            if len(self._fill_rate_history) > 0:
                avg_size = np.mean(list(self._fill_rate_history)[-20:])
                if avg_size > 0:
                    return (current_size - avg_size) / avg_size

        return 0.0

    def calculate_void_depth(self, book: OrderBookSnapshot, side: str, levels: int = 10) -> float:
        """
        Calculate the depth of the liquidity void.

        Args:
            book: Current order book
            side: "bids" or "asks"
            levels: Number of levels to analyze

        Returns:
            Void depth (0-1, higher = deeper void)
        """
        if side == "bids":
            levels_data = book.bids[:levels]
        else:
            levels_data = book.asks[:levels]

        if len(levels_data) < 3:
            return 0.0

        # Look for consecutive levels with decreasing size
        sizes = [s for _, s in levels_data]
        size_changes = [sizes[i+1] - sizes[i] for i in range(len(sizes)-1)]

        # Count negative changes (decreasing size as you move away)
        negative_changes = sum(1 for change in size_changes if change < 0)

        # Void depth = proportion of levels that are decreasing
        return negative_changes / max(len(size_changes), 1)

    def calculate_lri(
        self,
        book: OrderBookSnapshot,
        curvature: float,
        entropy: Optional[EntropyScore] = None
    ) -> float:
        """
        Calculate Liquidity Reflexivity Index (LRI).

        LRI = |curvature| * (1 - entropy_confidence) * (1 + fill_rate)

        Args:
            book: Current order book
            curvature: Current curvature value
            entropy: Entropy score for magnitude prediction

        Returns:
            LRI value (higher = more reflexivity)
        """
        # Base LRI from curvature
        lri = abs(curvature)

        # Weight by entropy if available
        if entropy and entropy.confidence > 0:
            # Low entropy = predictable flow = higher LRI
            entropy_weight = 1 - entropy.confidence
            lri *= (1 + entropy_weight)

        # Weight by fill rate (consumption accelerates reflexivity)
        fill_rate = self.calculate_fill_rate(book, "asks" if curvature < 0 else "bids")
        if fill_rate < 0:  # Negative fill rate = consumption
            lri *= (1 + abs(fill_rate))

        return lri

    def update_adaptive_threshold(self) -> None:
        """Update adaptive threshold based on historical curvature."""
        if len(self._curvature_history) < 20:
            return

        recent_curvature = list(self._curvature_history)[-20:]
        mean_curv = np.mean(recent_curvature)
        std_curv = np.std(recent_curvature)

        # Adaptive threshold: base_sensitivity * normalized volatility
        if std_curv > 0 and mean_curv != 0:
            self._current_threshold = self.base_sensitivity * (1 + std_curv / abs(mean_curv))
        else:
            self._current_threshold = self.base_sensitivity

        # Clamp to reasonable range
        self._current_threshold = max(1.0, min(10.0, self._current_threshold))

    def analyze(
        self,
        book: OrderBookSnapshot,
        regime: RegimeType,
        entropy: Optional[EntropyScore] = None
    ) -> CurvatureSignal:
        """
        Execute Shan's Curve Alpha logic.

        Args:
            book: Current order book snapshot
            regime: Current market regime
            entropy: Entropy score for magnitude prediction

        Returns:
            CurvatureSignal with superfluid score and bias
        """
        # 1. Calculate curvature for bids and asks
        ask_k = self.calculate_curvature_poly(book.asks)
        bid_k = self.calculate_curvature_poly(book.bids)

        # Store history
        self._curvature_history.append(ask_k)
        self._curvature_history.append(bid_k)

        # 2. Calculate curvature velocity
        curvature_velocity = self.calculate_curvature_velocity()

        # 3. Identify void side
        void_score = 0.0
        bias = "neutral"
        void_depth = 0.0
        fill_rate = 0.0

        # Negative curvature = concave (void)
        if ask_k < -self._current_threshold:
            void_score = abs(ask_k)
            bias = "long"
            void_depth = self.calculate_void_depth(book, "asks")
            fill_rate = self.calculate_fill_rate(book, "asks")

        elif bid_k < -self._current_threshold:
            void_score = abs(bid_k)
            bias = "short"
            void_depth = self.calculate_void_depth(book, "bids")
            fill_rate = self.calculate_fill_rate(book, "bids")

        # 4. Calculate Liquidity Reflexivity Index
        lri = self.calculate_lri(book, void_score if bias != "neutral" else 0, entropy)

        # 5. Regime scaling
        if regime == RegimeType.CRISIS:
            # Voids are traps in crisis - scale down aggressively
            void_score *= 0.1
            confidence = 0.2
        elif regime == RegimeType.TRENDING:
            # Voids are opportunities in trends
            void_score *= 1.2
            confidence = min(0.9, void_score / 5.0)
        else:  # RANGING
            # Voids can be false breaks
            void_score *= 0.7
            confidence = min(0.7, void_score / 5.0)

        # 6. Update adaptive threshold
        self.update_adaptive_threshold()

        # 7. Calculate final confidence with LRI boost
        if void_score > 0:
            confidence = min(0.95, (void_score / 10.0) * (1 + void_depth) * (1 + abs(fill_rate)) * (1 + lri / 5.0))
        else:
            confidence = 0.0

        return CurvatureSignal(
            superfluid_score=void_score,
            bias=bias,
            ask_curvature=ask_k,
            bid_curvature=bid_k,
            void_depth=void_depth,
            fill_rate=fill_rate,
            curvature_velocity=curvature_velocity,
            confidence=confidence
        )

    def get_metrics(self) -> Dict[str, float]:
        """Get current metrics for monitoring."""
        return {
            "current_threshold": self._current_threshold,
            "avg_curvature": np.mean(list(self._curvature_history)[-20:]) if self._curvature_history else 0,
            "curvature_volatility": np.std(list(self._curvature_history)[-20:]) if self._curvature_history else 0,
        }
'@ | Set-Content -Path "app/brain/shans_curve.py" -Encoding utf8

Write-Host "  ✓ Created app/brain/shans_curve.py" -ForegroundColor Green

# ============================================
# FILE 3: Update app/brain/__init__.py
# ============================================
Write-Host ""
Write-Host "Updating app/brain/__init__.py..." -ForegroundColor Yellow

@'
"""
Brain - Intelligence Layer
Market regime detection, whale flow, sentiment, entropy, and Shan's Curve.
"""

from app.brain.regime_detector import RegimeDetector
from app.brain.whale_flow_engine import WhaleFlowEngine
from app.brain.sentiment_engine import SentimentEngine
from app.brain.signal_fusion import SignalFusion
from app.brain.shadow_front_state import ShadowFrontState
from app.brain.entropy_decoder import EntropyDecoder
from app.brain.physical_validator import PhysicalValidator
from app.brain.convexity_switch import ConvexitySwitch
from app.brain.shans_curve import ShansCurve, CurvatureSignal

__all__ = [
    "RegimeDetector",
    "WhaleFlowEngine",
    "SentimentEngine",
    "SignalFusion",
    "ShadowFrontState",
    "EntropyDecoder",
    "PhysicalValidator",
    "ConvexitySwitch",
    "ShansCurve",
    "CurvatureSignal",
]
'@ | Set-Content -Path "app/brain/__init__.py" -Encoding utf8

Write-Host "  ✓ Updated app/brain/__init__.py" -ForegroundColor Green

# ============================================
# FILE 4: Update app/constants.py (add Shan's Curve constants)
# ============================================
Write-Host ""
Write-Host "Updating app/constants.py..." -ForegroundColor Yellow

# Check if Shan's Curve constants already exist
$constantsContent = Get-Content "app/constants.py" -Raw
if ($constantsContent -notmatch "SHANS_CURVE_SENSITIVITY") {
    Add-Content "app/constants.py" "`n# ===== Shan's Curve ====="
    Add-Content "app/constants.py" "SHANS_CURVE_SENSITIVITY: float = 2.5"
    Add-Content "app/constants.py" "SHANS_CURVE_MIN_CONFIDENCE: float = 0.4"
    Add-Content "app/constants.py" "SHANS_CURVE_FIT_DEGREE: int = 2"
    Add-Content "app/constants.py" "SHANS_CURVE_SMOOTHING_WINDOW: int = 5"
    Write-Host "  ✓ Added Shan's Curve constants to constants.py" -ForegroundColor Green
} else {
    Write-Host "  ✓ Shan's Curve constants already present" -ForegroundColor Gray
}

# ============================================
# FILE 5: Update app/models.py (add CurvatureSignal)
# ============================================
Write-Host ""
Write-Host "Updating app/models.py..." -ForegroundColor Yellow

# Check if CurvatureSignal already exists
$modelsContent = Get-Content "app/models.py" -Raw
if ($modelsContent -notmatch "class CurvatureSignal") {
    Add-Content "app/models.py" "`n# ============================================"
    Add-Content "app/models.py" "# SHAN'S CURVE MODELS"
    Add-Content "app/models.py" "# ============================================"
    Add-Content "app/models.py" "`n"
    Add-Content "app/models.py" "class CurvatureSignal(BaseModel):"
    Add-Content "app/models.py" "    \"\"\""
    Add-Content "app/models.py" "    Signal from Shan's Curve liquidity reflexivity analysis."
    Add-Content "app/models.py" "    Detects 'superfluid' market states where price moves on near-zero volume."
    Add-Content "app/models.py" "    \"\"\""
    Add-Content "app/models.py" "    superfluid_score: float = Field(default=0.0, ge=0, le=10, description=\"0-10 score of liquidity void strength\")"
    Add-Content "app/models.py" "    bias: str = Field(default=\"neutral\", pattern=\"^(long|short|neutral)$\", description=\"Predicted direction\")"
    Add-Content "app/models.py" "    ask_curvature: float = Field(default=0.0, description=\"Curvature of ask side (negative = void)\")"
    Add-Content "app/models.py" "    bid_curvature: float = Field(default=0.0, description=\"Curvature of bid side (negative = void)\")"
    Add-Content "app/models.py" "    void_depth: float = Field(default=0.0, ge=0, le=1, description=\"Depth of liquidity void (0-1)\")"
    Add-Content "app/models.py" "    fill_rate: float = Field(default=0.0, description=\"Rate of order consumption (negative = fast consumption)\")"
    Add-Content "app/models.py" "    curvature_velocity: float = Field(default=0.0, description=\"Rate of change of curvature\")"
    Add-Content "app/models.py" "    confidence: float = Field(default=0.0, ge=0, le=1, description=\"Signal confidence\")"
    Add-Content "app/models.py" "`n"
    Add-Content "app/models.py" "    model_config = ConfigDict(extra=\"forbid\")"
    Write-Host "  ✓ Added CurvatureSignal to models.py" -ForegroundColor Green
} else {
    Write-Host "  ✓ CurvatureSignal already present" -ForegroundColor Gray
}

# Also add Shan's Curve fields to FusionDecision if not present
if ($modelsContent -notmatch "shans_superfluid_score") {
    # Find FusionDecision class and add fields before its model_config
    Write-Host "  ⚠ Need to manually add Shan's Curve fields to FusionDecision class" -ForegroundColor Yellow
    Write-Host "  Please add these fields to FusionDecision in models.py:" -ForegroundColor White
    Write-Host "    shans_superfluid_score: float = Field(default=0.0, ge=0, le=10)" -ForegroundColor Cyan
    Write-Host "    shans_bias: str = Field(default=\"neutral\")" -ForegroundColor Cyan
    Write-Host "    shans_confidence: float = Field(default=0.0, ge=0, le=1)" -ForegroundColor Cyan
}

# ============================================
# FILE 6: Update app/brain/signal_fusion.py
# ============================================
Write-Host ""
Write-Host "Updating app/brain/signal_fusion.py..." -ForegroundColor Yellow

# Create backup
Copy-Item "app/brain/signal_fusion.py" "app/brain/signal_fusion.py.bak" -ErrorAction SilentlyContinue

# Read current content
$fusionContent = Get-Content "app/brain/signal_fusion.py" -Raw

# Add import if not present
if ($fusionContent -notmatch "from app.brain.shans_curve import") {
    $fusionContent = $fusionContent -replace "from app.brain.entropy_decoder import EntropyDecoder", "from app.brain.entropy_decoder import EntropyDecoder`nfrom app.brain.shans_curve import ShansCurve, CurvatureSignal"
}

# Add shans_curve initialization in __init__
if ($fusionContent -notmatch "self.shans_curve = ShansCurve") {
    $fusionContent = $fusionContent -replace "self.entropy_decoder = EntropyDecoder\(config\)", "self.entropy_decoder = EntropyDecoder(config)`n        self.shans_curve = ShansCurve("
    $fusionContent = $fusionContent -replace "self.shans_curve = ShansCurve\(", "self.shans_curve = ShansCurve(`n            base_sensitivity=getattr(config, 'SHANS_CURVE_SENSITIVITY', 2.5),`n            fit_degree=getattr(config, 'SHANS_CURVE_FIT_DEGREE', 2),`n            smoothing_window=getattr(config, 'SHANS_CURVE_SMOOTHING_WINDOW', 5)`n        )"
}

# Add Shan's Curve integration in fuse method
if ($fusionContent -notmatch "Shan's Curve analysis") {
    # Find where to add - after entropy processing
    $fusionContent = $fusionContent -replace "(# Process entropy decoder.*?confidence\s*=\s*max\(confidence, entropy_score.confidence\)?)", "`$1`n`n        # Shan's Curve analysis (if order book available)`n        shans_signal = None`n        if order_book:`n            shans_signal = self.shans_curve.analyze(`n                book=order_book,`n                regime=regime,`n                entropy=entropy_score`n            )`n            `n            if shans_signal.superfluid_score > 0:`n                confidence *= (1 + min(0.5, shans_signal.superfluid_score / 10.0))`n                `n                if shans_signal.bias == \"long\" and shans_signal.confidence > 0.6:`n                    shadow_front_eligible = True`n                elif shans_signal.bias == \"short\" and shans_signal.confidence > 0.6:`n                    liquidity_void_eligible = True"
}

# Add Shan's Curve fields to FusionDecision output
if ($fusionContent -notmatch "fusion.shans_superfluid_score") {
    $fusionContent = $fusionContent -replace "(fusion = FusionDecision\(.*?\)\s*# .*?)", "`$1`n        `n        # Add Shan's Curve data`n        fusion.shans_superfluid_score = shans_signal.superfluid_score if shans_signal else 0.0`n        fusion.shans_bias = shans_signal.bias if shans_signal else \"neutral\"`n        fusion.shans_confidence = shans_signal.confidence if shans_signal else 0.0"
}

Set-Content "app/brain/signal_fusion.py" $fusionContent -Encoding utf8
Write-Host "  ✓ Updated app/brain/signal_fusion.py" -ForegroundColor Green

# ============================================
# SUMMARY
# ============================================
Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Shan's Curve v2 Integration Complete!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Files Created/Updated:" -ForegroundColor Yellow
Write-Host "  ✅ requirements.txt (added scipy, scikit-learn)" -ForegroundColor White
Write-Host "  ✅ app/brain/shans_curve.py (NEW)" -ForegroundColor White
Write-Host "  ✅ app/brain/__init__.py (updated)" -ForegroundColor White
Write-Host "  ✅ app/constants.py (added constants)" -ForegroundColor White
Write-Host "  ✅ app/models.py (added CurvatureSignal)" -ForegroundColor White
Write-Host "  ✅ app/brain/signal_fusion.py (updated)" -ForegroundColor White
Write-Host ""
Write-Host "Next Steps:" -ForegroundColor Yellow
Write-Host "  1. Install new dependencies:" -ForegroundColor White
Write-Host "     pip install scipy scikit-learn" -ForegroundColor Cyan
Write-Host "  2. Manually add Shan's Curve fields to FusionDecision in models.py" -ForegroundColor White
Write-Host "  3. Test the integration with: python -c \"from app.brain import ShansCurve; print('OK')\"" -ForegroundColor Cyan
Write-Host ""