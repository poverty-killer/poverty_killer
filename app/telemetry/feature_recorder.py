"""
Feature Recorder Ã¢â‚¬â€ captures FeatureVector objects as telemetry events.

HONEST STATUS: No active path creates FeatureVector objects in current codebase.
This recorder provides the API substrate for future feature generation wiring.
"""

import logging
from typing import Optional, List, Dict, Any

from app.models.contracts import FeatureVector, EventEnvelope
from app.models.enums import EventType
from app.telemetry.event_store import TelemetryEventStore
from app.utils.time_utils import now_ns

logger = logging.getLogger(__name__)


class FeatureRecorder:
    """
    Records feature vectors to the telemetry event store.
    
    HONEST NOTE: FeatureVector creation does NOT exist in active code paths.
    This recorder is structural readiness only Ã¢â‚¬â€ no active recording until
    upstream feature generation is implemented in a future bundle.
    
    Usage (future):
        recorder = FeatureRecorder(event_store)
        recorder.record_features(feature_vector)
    """
    
    def __init__(self, event_store: TelemetryEventStore):
        self._store = event_store
        logger.info("FeatureRecorder initialized (awaiting upstream feature generation)")
    
    def record_features(self, feature_vector: FeatureVector) -> str:
        """
        Record a feature vector as a telemetry event.
        
        Args:
            feature_vector: FeatureVector from feature generation
            
        Returns:
            event_id
        """
        payload = {
            "feature_vector_id": feature_vector.feature_vector_id,
            "decision_uuid": feature_vector.decision_uuid,
            "timestamp_ns": feature_vector.timestamp_ns,
            "symbol": feature_vector.symbol,
            "features": feature_vector.features.model_dump() if hasattr(feature_vector.features, 'model_dump') else feature_vector.features.dict() if hasattr(feature_vector.features, 'dict') else feature_vector.features,
        }
        
        event = EventEnvelope(
            event_id=feature_vector.feature_vector_id,
            decision_uuid=feature_vector.decision_uuid,
            parent_uuid=None,
            event_type=EventType.FEATURE_VECTOR,
            source_module="feature_generator",
            exchange_ts_ns=feature_vector.timestamp_ns,
            receive_ts_ns=now_ns(),
            decision_ts_ns=feature_vector.timestamp_ns,
            sequence=0,
            payload=payload,
            schema_version=1,
        )
        
        self._store.record_event(event)
        logger.debug(f"Feature vector recorded: {feature_vector.feature_vector_id}")
        return event.event_id
    
    def get_features_for_decision(self, decision_uuid: str) -> List[Dict[str, Any]]:
        """Get all feature vectors for a decision."""
        events = self._store.get_decision_chain(decision_uuid)
        return [e for e in events if e["event_type"] == "feature_vector"]