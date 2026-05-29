"""Operator-facing provider readiness models.

This package is read-only/advisory. It inspects provider configuration shape
and environment-variable presence only. It does not call brokers, market data
providers, AI providers, or external systems.
"""

from app.operator_providers.readiness import (
    build_provider_readiness,
    provider_readiness_summary,
    validate_provider_readonly,
)
from app.operator_providers.registry import list_provider_profiles

__all__ = [
    "build_provider_readiness",
    "list_provider_profiles",
    "provider_readiness_summary",
    "validate_provider_readonly",
]
