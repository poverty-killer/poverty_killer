"""
FusionDecision — Routing-Stage Decision Contract                                                                      
  Migrated from the unreachable app/models.py (old file) into the governed                                                app/models/ package to resolve the Python package-shadowing issue.

  Root cause: when app/models.py and app/models/ (package) coexist in the
  same directory, CPython always binds 'app.models' to the package. The old
  app/models.py becomes unreachable via any standard import path. FusionDecision
  was defined there and was therefore inaccessible via:
      from app.models import FusionDecision

  This file re-establishes that export within the governed package.

  Pydantic version: v2 native (ConfigDict, Field) — consistent with the
  original definition in app/models.py.

  Float fields: all analytical confidence scores, not monetary values.
  Decimal is not required here (no financial computation occurs in this contract).
  """

from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class FusionDecision(BaseModel):
      """
      Routing-stage fusion decision.

      Produced by the fusion layer, consumed by StrategyRouter.
      Governs which strategy sleeves are eligible for capital allocation
      in a given routing cycle.

      All float fields are analytical confidence/score values in [0, 1]
      (or [0, 10] for shans_superfluid_score). No monetary computation occurs
      in this contract — Decimal is not required.

      Timing: exchange_ts_ns carries the authoritative cycle timestamp.
      No wall-clock dependence.
      """

      model_config = ConfigDict(extra="forbid")

      # ---- Timing ----
      exchange_ts_ns: int

      # ---- Fusion decision ----
      attack_mode: bool
      confidence: float = Field(ge=0.0, le=1.0)

      # ---- Strategy sleeve eligibility flags ----
      shadow_front_eligible: bool
      liquidity_void_eligible: bool
      entropy_decoder_eligible: bool
      gamma_front_eligible: bool
      sector_rotation_eligible: bool

      # ---- Routing preferences ----
      preferred_sleeve: Optional[str] = None
      # Field(default_factory=list) is required for mutable defaults in pydantic v2.
      # The original app/models.py had 'List[str] = []' which raises PydanticUserError
      # in strict pydantic v2. This is the correct form.
      deprioritized_sleeves: List[str] = Field(default_factory=list)

      # ---- Context fields ----
      reason: str = ""
      regime: str = "unknown"

      # ---- Signal quality scores ----
      physical_verification_score: float = Field(default=1.0, ge=0.0, le=1.0)
      shans_superfluid_score: float = Field(default=0.0, ge=0.0, le=10.0)
      shans_bias: str = Field(default="neutral")
      shans_confidence: float = Field(default=0.0, ge=0.0, le=1.0)

      # ---- Convenience properties ----

      @property
      def exchange_ts_sec(self) -> float:
          """Nanoseconds to seconds. Read-only — no mutation."""
          return self.exchange_ts_ns / 1_000_000_000.0

      @property
      def has_valid_sleeve(self) -> bool:
          """True if at least one strategy sleeve is marked eligible."""
          return any([
              self.shadow_front_eligible,
              self.liquidity_void_eligible,
              self.entropy_decoder_eligible,
              self.gamma_front_eligible,
              self.sector_rotation_eligible,
          ])


__all__ = ["FusionDecision"]