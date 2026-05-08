"""
Decision Recorder — captures DecisionRecord objects as telemetry events.

Seam: Called from DecisionCompiler.compile() after DecisionRecord creation.
"""

import logging
from typing import Optional, List, Dict, Any
from uuid import uuid4

from app.models.contracts import DecisionRecord, EventEnvelope
from app.models.enums import EventType
from app.telemetry.event_store import TelemetryEventStore
from app.utils.time_utils import now_ns

logger = logging.getLogger(__name__)


def _safe_decision_type(value: Any) -> str:
    """
    Safely convert decision_type to string.
    
    Handles both enum members and pre-stringified values.
    """
    if hasattr(value, "value"):
        return value.value
    return str(value)


class DecisionRecorder:
    """
    Records decisions to the telemetry event store.
    
    Usage:
        recorder = DecisionRecorder(event_store)
        recorder.record_decision(decision_record)
    """
    
    def __init__(self, event_store: TelemetryEventStore):
        self._store = event_store
        self._last_decision_uuid: Optional[str] = None
        logger.info("DecisionRecorder initialized")
    
    def record_decision(self, decision_record: DecisionRecord) -> str:
        """
        Record a decision as a telemetry event.
        
        Args:
            decision_record: DecisionRecord from DecisionCompiler
            
        Returns:
            event_id
        """
        payload = {
            "decision_uuid": decision_record.decision_uuid,
            "decision_type": _safe_decision_type(decision_record.decision_type),
            "timestamp_ns": decision_record.timestamp_ns,
            "inputs": decision_record.inputs,
            "outputs": decision_record.outputs,
            "metadata": decision_record.metadata,
        }
        
        event = EventEnvelope(
            event_id=str(uuid4()),
            decision_uuid=decision_record.decision_uuid,
            parent_uuid=None,
            event_type=EventType.DECISION_RECORD,
            source_module="decision_compiler",
            exchange_ts_ns=decision_record.timestamp_ns,
            receive_ts_ns=now_ns(),
            decision_ts_ns=decision_record.timestamp_ns,
            sequence=0,
            payload=payload,
            schema_version=1,
        )
        
        self._store.record_event(event)
        self._last_decision_uuid = decision_record.decision_uuid
        
        logger.debug(f"Decision recorded: {decision_record.decision_uuid}")
        return event.event_id
    
    def get_last_decision(self) -> Optional[Dict[str, Any]]:
        """Get the most recent decision event."""
        events = self._store.get_events_by_type("decision_record", limit=1)
        if events:
            return events[0]
        return None
    
    def get_decision_by_uuid(self, decision_uuid: str) -> Optional[Dict[str, Any]]:
        """Get a specific decision by UUID."""
        events = self._store.get_decision_chain(decision_uuid)
        for event in events:
            if event["event_type"] == "decision_record":
                return event
        return None