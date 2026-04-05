"""
Control Plane - Remote Management and Operator Mode Control
Manages operator modes, control commands, and remote configuration.
Acts as the secure interface between phone app and engine.
"""

import json
import time
import logging
import threading
import os
import tempfile
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any, List, Callable
from dataclasses import dataclass, asdict

from app.constants import ControlMode, RiskProfile, SleeveType
from app.models import ControlCommand, SystemStatus

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
    WATCHDOG_AVAILABLE = True
except ImportError:
    WATCHDOG_AVAILABLE = False
    logging.warning("watchdog not available, falling back to polling")

logger = logging.getLogger(__name__)


@dataclass
class ControlState:
    mode: ControlMode = ControlMode.NORMAL
    last_mode_change: datetime = None
    mode_change_reason: str = ""
    emergency_halt_active: bool = False
    kill_switch_triggered: bool = False
    manual_override_active: bool = False
    last_heartbeat: datetime = None

    def __post_init__(self):
        if self.last_mode_change is None:
            self.last_mode_change = datetime.utcnow()


class ModeFileHandler(FileSystemEventHandler):
    def __init__(self, control_plane, debounce_ms=100):
        self.control_plane = control_plane
        self.debounce_ms = debounce_ms
        self._last_event_time = 0
        self._pending = False
        self._timer = None
        super().__init__()

    def _process_change(self):
        self._pending = False
        self.control_plane._load_mode_from_file()

    def on_modified(self, event):
        if not event.src_path.endswith("mode.txt"):
            return
        current_time = time.time() * 1000
        if current_time - self._last_event_time < self.debounce_ms:
            return
        self._last_event_time = current_time
        if self._timer:
            self._timer.cancel()
        self._pending = True
        self._timer = threading.Timer(self.debounce_ms / 1000, self._process_change)
        self._timer.daemon = True
        self._timer.start()

    def on_created(self, event):
        if event.src_path.endswith("mode.txt"):
            time.sleep(0.05)
            self.control_plane._load_mode_from_file()


class ControlPlane:
    def __init__(self, control_dir="control", mode_file="mode.txt", config=None):
        self.control_dir = Path(control_dir)
        self.control_dir.mkdir(parents=True, exist_ok=True)
        self.mode_path = self.control_dir / mode_file
        self._state = ControlState()
        self._config = config or {}
        self._running = False
        self._thread = None
        self._lock = threading.Lock()
        self._mode_change_callbacks = []
        self._observer = None
        self._init_mode_file()
        self._load_mode_from_file()
        logger.info(f"ControlPlane initialized: mode={self._state.mode.value}")

    def _verify_file_content(self, expected_mode):
        try:
            if not self.mode_path.exists():
                return False
            content = self.mode_path.read_text().strip().upper()
            expected = expected_mode.value.upper()
            return content == expected
        except Exception as e:
            logger.error(f"File verification failed: {e}")
            return False

    def _atomic_write_mode(self, content, max_retries=3):
        expected_mode = None
        try:
            expected_mode = ControlMode(content.lower())
        except ValueError:
            pass
        for attempt in range(max_retries):
            try:
                with tempfile.NamedTemporaryFile(
                    mode='w', dir=str(self.control_dir), prefix='.mode_', suffix='.tmp', delete=False
                ) as tmp_file:
                    tmp_file.write(content)
                    tmp_path = Path(tmp_file.name)
                os.replace(tmp_path, self.mode_path)
                time.sleep(0.05)
                if expected_mode:
                    if self._verify_file_content(expected_mode):
                        return True
                    else:
                        logger.warning(f"Write verification failed (attempt {attempt + 1})")
                else:
                    return True
            except Exception as e:
                logger.error(f"Atomic write attempt {attempt + 1} failed: {e}")
                if attempt < max_retries - 1:
                    time.sleep(0.1)
        logger.error(f"Atomic write failed after {max_retries} attempts")
        return False

    def _init_mode_file(self):
        if not self.mode_path.exists():
            default_mode = ControlMode.NORMAL.value.upper()
            if self._atomic_write_mode(default_mode):
                logger.info(f"Created default mode file: {self.mode_path}")

    def _load_mode_from_file(self):
        try:
            if not self.mode_path.exists():
                return
            content = self.mode_path.read_text().strip().upper()
            for mode in ControlMode:
                if mode.value.upper() == content:
                    self._set_mode_internal(mode, "control_file_update")
                    break
        except Exception as e:
            logger.error(f"Failed to read mode file: {e}")

    def _set_mode_internal(self, mode, reason):
        with self._lock:
            old_mode = self._state.mode
            if self._state.kill_switch_triggered and mode != ControlMode.EMERGENCY_HALT:
                logger.warning(f"Cannot change mode to {mode.value}: kill switch active")
                return False
            if mode == ControlMode.EMERGENCY_HALT:
                self._state.emergency_halt_active = True
                logger.warning(f"EMERGENCY HALT ACTIVATED: {reason}")
            self._state.mode = mode
            self._state.last_mode_change = datetime.utcnow()
            self._state.mode_change_reason = reason
            logger.info(f"Control mode changed: {old_mode.value} -> {mode.value} ({reason})")
            for callback in self._mode_change_callbacks:
                try:
                    callback(old_mode, mode, reason)
                except Exception as e:
                    logger.error(f"Mode change callback error: {e}")
            return True

    def start(self):
        if self._running:
            return
        self._running = True
        if WATCHDOG_AVAILABLE:
            try:
                self._observer = Observer()
                handler = ModeFileHandler(self, debounce_ms=100)
                self._observer.schedule(handler, str(self.control_dir), recursive=False)
                self._observer.start()
                logger.info("ControlPlane watchdog started")
            except Exception as e:
                logger.error(f"Failed to start watchdog: {e}")
                self._start_polling_thread()
        else:
            self._start_polling_thread()
        logger.info("ControlPlane monitoring started")

    def _start_polling_thread(self):
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()
        logger.info("ControlPlane polling started")

    def stop(self):
        self._running = False
        if self._observer:
            self._observer.stop()
            self._observer.join(timeout=2.0)
            self._observer = None
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None
        logger.info("ControlPlane stopped")

    def _monitor_loop(self):
        last_modified = None
        while self._running:
            try:
                if self.mode_path.exists():
                    mod_time = self.mode_path.stat().st_mtime
                    if last_modified is None or mod_time != last_modified:
                        last_modified = mod_time
                        time.sleep(0.1)
                        self._load_mode_from_file()
                with self._lock:
                    self._state.last_heartbeat = datetime.utcnow()
                time.sleep(0.5)
            except Exception as e:
                logger.error(f"Control plane monitor error: {e}")
                time.sleep(5.0)

    def set_mode(self, mode, reason=""):
        if not self._atomic_write_mode(mode.value.upper()):
            logger.error(f"Failed to write mode file for {mode.value}")
            return False
        return self._set_mode_internal(mode, reason)

    def get_mode(self):
        with self._lock:
            return self._state.mode

    def get_state(self):
        with self._lock:
            return ControlState(
                mode=self._state.mode,
                last_mode_change=self._state.last_mode_change,
                mode_change_reason=self._state.mode_change_reason,
                emergency_halt_active=self._state.emergency_halt_active,
                kill_switch_triggered=self._state.kill_switch_triggered,
                manual_override_active=self._state.manual_override_active,
                last_heartbeat=self._state.last_heartbeat,
            )

    def register_mode_change_callback(self, callback):
        self._mode_change_callbacks.append(callback)

    def get_exposure_multiplier(self):
        from app.constants import CONTROL_MODE_EXPOSURE
        with self._lock:
            if self._state.kill_switch_triggered:
                return 0.0
            if self._state.emergency_halt_active:
                return 0.0
            return CONTROL_MODE_EXPOSURE.get(self._state.mode, 0.40)

    def notify_kill_switch_triggered(self):
        with self._lock:
            self._state.kill_switch_triggered = True
            self._state.mode = ControlMode.EMERGENCY_HALT
            logger.critical("Kill switch triggered")
        if not self._atomic_write_mode(ControlMode.EMERGENCY_HALT.value.upper()):
            logger.critical("FAILED TO WRITE EMERGENCY MODE")

    def reset_kill_switch(self):
        with self._lock:
            if not self._state.kill_switch_triggered:
                return False
            self._state.kill_switch_triggered = False
            self._state.emergency_halt_active = False
            logger.info("Kill switch reset")
            return self.set_mode(ControlMode.SAFE, "kill_switch_reset")

    def process_command(self, command):
        logger.info(f"Processing command: {command.command} from {command.source}")
        if command.command == "SET_MODE":
            if command.mode:
                try:
                    mode = ControlMode(command.mode.lower())
                    if self.set_mode(mode, f"api_command from {command.source}"):
                        return {"status": "success", "mode": mode.value}
                    return {"status": "error", "message": "Failed to write mode file"}
                except ValueError:
                    return {"status": "error", "message": f"Invalid mode: {command.mode}"}
            return {"status": "error", "message": "mode required"}
        elif command.command == "HALT":
            if self.set_mode(ControlMode.EMERGENCY_HALT, f"halt_command"):
                return {"status": "success", "message": "Emergency halt activated"}
            return {"status": "error", "message": "Failed"}
        elif command.command == "RESUME":
            if self._state.kill_switch_triggered:
                return {"status": "error", "message": "Cannot resume: kill switch active"}
            if self.set_mode(ControlMode.SAFE, f"resume_command"):
                return {"status": "success", "message": "System resumed"}
            return {"status": "error", "message": "Failed"}
        elif command.command == "STATUS":
            return self.get_status_response()
        else:
            return {"status": "error", "message": f"Unknown command: {command.command}"}

    def get_status_response(self):
        with self._lock:
            return {
                "status": "RUNNING" if not self._state.emergency_halt_active else "HALTED",
                "mode": self._state.mode.value,
                "kill_switch_triggered": self._state.kill_switch_triggered,
                "available_modes": [m.value for m in ControlMode],
                "exposure_multiplier": self.get_exposure_multiplier(),
            }

    def should_allow_trading(self, strategy=None):
        with self._lock:
            if self._state.kill_switch_triggered:
                return False
            if self._state.emergency_halt_active:
                return False
            if self._state.mode == ControlMode.CAPITAL_SECURE:
                return False
            if self._state.mode == ControlMode.EMERGENCY_HALT:
                return False
            return True

    def should_allow_entry(self, strategy):
        with self._lock:
            if not self.should_allow_trading(strategy):
                return False
            if self._state.mode == ControlMode.CAPITAL_SECURE:
                return False
            if self._state.mode == ControlMode.CRISIS_OPPORTUNISTIC:
                return strategy == SleeveType.FLV
            return True

    def get_effective_risk_profile(self, base_profile):
        with self._lock:
            mode_to_risk = {
                ControlMode.SAFE: RiskProfile.SAFE,
                ControlMode.NORMAL: RiskProfile.NORMAL,
                ControlMode.MODERATE: RiskProfile.MODERATE,
                ControlMode.AGGRESSIVE: RiskProfile.AGGRESSIVE,
                ControlMode.CRISIS_OPPORTUNISTIC: RiskProfile.CRISIS_OPPORTUNISTIC,
                ControlMode.CAPITAL_SECURE: RiskProfile.SAFE,
                ControlMode.EMERGENCY_HALT: RiskProfile.SAFE,
            }
            control_risk = mode_to_risk.get(self._state.mode, RiskProfile.SAFE)
            risk_levels = [RiskProfile.SAFE, RiskProfile.NORMAL, RiskProfile.MODERATE, RiskProfile.AGGRESSIVE, RiskProfile.CRISIS_OPPORTUNISTIC]
            base_index = risk_levels.index(base_profile)
            control_index = risk_levels.index(control_risk)
            return control_risk if control_index < base_index else base_profile

    def get_aggression_scaling(self, base_scaling):
        return base_scaling * self.get_exposure_multiplier()

    def execute_emergency_halt(self, reason):
        logger.critical(f"EMERGENCY HALT: {reason}")
        return self.set_mode(ControlMode.EMERGENCY_HALT, reason)