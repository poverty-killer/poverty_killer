"""
test_risk_guard_reentrant_lock.py

RISK GUARD REENTRANT LOCK CONTRACT — CITADEL GRADE

Tests that HybridRiskGuard can be called reentrantly on the same thread
without deadlock. This is a regression guard for the deadlock fix:
    threading.Lock() → threading.RLock()

The accepted repair was a same-thread self-deadlock fix caused by nested
lock acquisition in assess_state() when callbacks re-enter the guard.

The truthful regression seam is callback-triggered reentry:
    assess_state() → triggers callback → callback calls assess_state()

Contracts tested:
1. Recalibration callback triggered during assess_state() can safely call back
2. Emergency callback triggered during assess_state() can safely call back

Regression guard for:
- Risk guard self-deadlock fix (guard.py)
- Reentrant lock behavior preservation
"""

import os
import tempfile
import time
from unittest.mock import patch

import pytest

from app.risk.guard import HybridRiskGuard


def _fresh_guard(initial_equity: float = 20000.0) -> HybridRiskGuard:
    """Return a guard backed by a non-existent temp file so it starts from clean state."""
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    os.unlink(path)  # Remove so _load_state falls through to fresh RiskState
    return HybridRiskGuard(
        initial_equity=initial_equity,
        state_file=path,
        backup_file=path + ".bak",
    )


class TestCallbackReentrancy:
    """
    Tests that real callbacks triggered during assess_state() can safely
    call back into the risk guard on the same thread.

    This is the accepted regression seam: the exact deadlock pattern
    that was fixed by Lock() → RLock().
    """

    def test_recalibrate_callback_reentrant(self):
        """
        Recalibration callback triggered by adaptive floor breach must be able
        to call assess_state() reentrantly without deadlock.

        This exercises the exact deadlock pattern:
            1. assess_state() acquires lock
            2. floor breach triggers _trigger_recalibration()
            3. callback calls assess_state() again on same thread
            4. Without RLock, this deadlocks. With RLock, it succeeds.
        """
        guard = _fresh_guard()

        callback_called = False
        reentrant_success = False

        def reentrant_callback():
            nonlocal callback_called, reentrant_success
            callback_called = True
            # Call back into assess_state() from within the callback
            # This is the exact deadlock pattern that was fixed
            try:
                guard.assess_state(19000.0, 0.5)
                reentrant_success = True
            except Exception:
                reentrant_success = False

        guard.register_recalibrate_callback(reentrant_callback)

        # Trigger adaptive floor breach (15% from 20000 = 17000; 16000 < 17000)
        guard.assess_state(16000.0, 0.5)
        
        # Give time for callback to execute
        time.sleep(0.01)
        
        assert callback_called, "Recalibration callback was not triggered"
        assert reentrant_success, "Reentrant assess_state() call in callback deadlocked"

    def test_emergency_callback_reentrant(self):
        """
        Emergency callback triggered by physical fuse breach must be able
        to call assess_state() reentrantly without deadlock.

        This exercises the same deadlock pattern for emergency callbacks.
        """
        guard = _fresh_guard()

        callback_called = False
        reentrant_success = False

        def reentrant_callback():
            nonlocal callback_called, reentrant_success
            callback_called = True
            try:
                guard.assess_state(14000.0, 0.5)
                reentrant_success = True
            except Exception:
                reentrant_success = False

        guard.register_emergency_callback(reentrant_callback)

        # Trigger physical fuse breach (25% from 20000 = 15000; 14000 < 15000)
        guard.assess_state(14000.0, 0.5)
        
        assert callback_called, "Emergency callback was not triggered"
        assert reentrant_success, "Reentrant assess_state() call in emergency callback deadlocked"