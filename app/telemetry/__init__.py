"""
Telemetry Subsystem for Poverty Killer F1

Provides:
- EventStore: SQLite-backed event persistence
- DecisionRecorder: DecisionRecord capture and retrieval
- FeatureRecorder: FeatureVector storage (future seam)
- FillRecorder: FillEvent and rejection capture

All recorders share a single EventStore instance.
"""

from .event_store import TelemetryEventStore
from .feature_recorder import FeatureRecorder
from .decision_recorder import DecisionRecorder
from .fill_recorder import FillRecorder

__all__ = [
    'TelemetryEventStore',
    'FeatureRecorder',
    'DecisionRecorder',
    'FillRecorder',
]