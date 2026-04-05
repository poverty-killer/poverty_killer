"""
Sovereign Logger - Central Nervous System
Asynchronous logging with rotating file handlers.
JSON format for machine parsing, standard format for console.
Dynamically handles log level from configuration.
"""

import logging
import logging.handlers
import json
import sys
import os
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any
from logging import LogRecord


class JSONFormatter(logging.Formatter):
    """
    JSON formatter for machine-readable logs.
    Used for log files, enables automated parsing and alerting.
    """
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
    
    def format(self, record: LogRecord) -> str:
        """Format log record as JSON."""
        log_entry = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno
        }
        
        # Add exception info if present
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)
        
        # Add extra fields if present
        if hasattr(record, "extra_data"):
            log_entry["extra"] = record.extra_data
        
        return json.dumps(log_entry, default=str)


class PlainFormatter(logging.Formatter):
    """
    Plain text formatter for console output.
    Human-readable with colors for severity levels.
    """
    
    # ANSI color codes
    COLORS = {
        "DEBUG": "\033[36m",     # Cyan
        "INFO": "\033[32m",      # Green
        "WARNING": "\033[33m",   # Yellow
        "ERROR": "\033[31m",     # Red
        "CRITICAL": "\033[35m",  # Magenta
        "RESET": "\033[0m"
    }
    
    def format(self, record: LogRecord) -> str:
        """Format log record with colors."""
        timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        level = record.levelname
        color = self.COLORS.get(level, self.COLORS["RESET"])
        reset = self.COLORS["RESET"]
        
        # Format message
        message = record.getMessage()
        
        # Format with timestamp, level, logger, message
        log_line = f"{timestamp} | {color}{level:<8}{reset} | {record.name:<20} | {message}"
        
        # Add exception if present
        if record.exc_info:
            log_line += f"\n{self.formatException(record.exc_info)}"
        
        return log_line


class SovereignLogger:
    """
    Sovereign Logger - Central logging system.
    Features:
    - Asynchronous rotating file handlers (JSON format)
    - Console handler (plain text with colors)
    - Dynamic log level from configuration
    - Log rotation by size and time
    """
    
    def __init__(self):
        self._initialized = False
        self._root_logger = logging.getLogger()
        self._root_logger.setLevel(logging.DEBUG)
    
    def setup(
        self,
        log_level: str = "INFO",
        log_dir: str = "logs",
        max_bytes: int = 10 * 1024 * 1024,  # 10MB
        backup_count: int = 10,
        json_format: bool = True
    ) -> None:
        """
        Setup logging system.
        
        Args:
            log_level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
            log_dir: Directory for log files
            max_bytes: Maximum size per log file
            backup_count: Number of backup files to keep
            json_format: Use JSON format for files (always True for files)
        """
        if self._initialized:
            return
        
        # Create log directory
        log_path = Path(log_dir)
        log_path.mkdir(parents=True, exist_ok=True)
        
        # Convert log level string to int
        level = getattr(logging, log_level.upper(), logging.INFO)
        
        # Set root logger level
        self._root_logger.setLevel(level)
        
        # Remove existing handlers
        for handler in self._root_logger.handlers[:]:
            self._root_logger.removeHandler(handler)
        
        # ============================================
        # CONSOLE HANDLER (Plain text with colors)
        # ============================================
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(level)
        console_handler.setFormatter(PlainFormatter())
        self._root_logger.addHandler(console_handler)
        
        # ============================================
        # FILE HANDLER (JSON format - machine readable)
        # ============================================
        file_handler = logging.handlers.RotatingFileHandler(
            filename=log_path / "poverty_killer.log",
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8"
        )
        file_handler.setLevel(logging.DEBUG)  # Always log DEBUG to file
        file_handler.setFormatter(JSONFormatter())
        self._root_logger.addHandler(file_handler)
        
        # ============================================
        # ERROR FILE HANDLER (Separate error log)
        # ============================================
        error_handler = logging.handlers.RotatingFileHandler(
            filename=log_path / "errors.log",
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8"
        )
        error_handler.setLevel(logging.ERROR)
        error_handler.setFormatter(JSONFormatter())
        self._root_logger.addHandler(error_handler)
        
        # ============================================
        # PERFORMANCE FILE HANDLER (Specialized)
        # ============================================
        perf_handler = logging.handlers.RotatingFileHandler(
            filename=log_path / "performance.log",
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8"
        )
        perf_handler.setLevel(logging.INFO)
        perf_handler.addFilter(lambda record: record.name.startswith("app.performance"))
        perf_handler.setFormatter(JSONFormatter())
        self._root_logger.addHandler(perf_handler)
        
        self._initialized = True
        
        # Log startup
        self._root_logger.info(f"Logging initialized: level={log_level}, dir={log_dir}")
    
    def get_logger(self, name: str) -> logging.Logger:
        """
        Get a logger instance.
        
        Args:
            name: Logger name (typically __name__)
            
        Returns:
            Logger instance
        """
        return logging.getLogger(name)


# Global instance
_sovereign_logger = SovereignLogger()


def setup_logger(config: Any = None, level: str = "INFO") -> None:
    """
    Setup the sovereign logger.
    
    Args:
        config: Configuration object (optional)
        level: Log level override (optional)
    """
    log_level = level
    if config and hasattr(config, 'log_level'):
        log_level = config.log_level
    
    _sovereign_logger.setup(log_level=log_level)


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger instance.
    
    Args:
        name: Logger name (typically __name__)
        
    Returns:
        Logger instance
    """
    return _sovereign_logger.get_logger(name)


class PerformanceLogger:
    """
    Performance logger for tracking execution latency.
    """
    
    def __init__(self, name: str):
        self.logger = get_logger(f"app.performance.{name}")
    
    def log_latency(self, operation: str, latency_ms: float, metadata: Optional[Dict[str, Any]] = None) -> None:
        """
        Log latency for an operation.
        
        Args:
            operation: Operation name
            latency_ms: Latency in milliseconds
            metadata: Additional metadata
        """
        extra = {"extra_data": {"operation": operation, "latency_ms": latency_ms}}
        if metadata:
            extra["extra_data"].update(metadata)
        
        self.logger.info(f"LATENCY: {operation} took {latency_ms:.2f}ms", extra=extra)
    
    def log_order_execution(self, order_id: str, symbol: str, latency_ms: float, fill_price: float, fees: float) -> None:
        """
        Log order execution details.
        
        Args:
            order_id: Order ID
            symbol: Trading symbol
            latency_ms: Execution latency
            fill_price: Fill price
            fees: Fees paid
        """
        extra = {
            "extra_data": {
                "order_id": order_id,
                "symbol": symbol,
                "latency_ms": latency_ms,
                "fill_price": fill_price,
                "fees": fees
            }
        }
        self.logger.info(f"ORDER_EXECUTED: {order_id} {symbol} @ {fill_price:.2f} ({latency_ms:.2f}ms)", extra=extra)
    
    def log_signal(self, strategy: str, symbol: str, confidence: float, latency_ms: float) -> None:
        """
        Log signal generation.
        
        Args:
            strategy: Strategy name
            symbol: Trading symbol
            confidence: Signal confidence
            latency_ms: Generation latency
        """
        extra = {
            "extra_data": {
                "strategy": strategy,
                "symbol": symbol,
                "confidence": confidence,
                "latency_ms": latency_ms
            }
        }
        self.logger.info(f"SIGNAL: {strategy} {symbol} confidence={confidence:.2f} ({latency_ms:.2f}ms)", extra=extra)


class AuditLogger:
    """
    Audit logger for compliance and forensic analysis.
    Logs all critical operations in append-only style.
    """
    
    def __init__(self):
        self.logger = get_logger("app.audit")
    
    def log_order(self, order_id: str, symbol: str, side: str, quantity: float, price: float, strategy: str) -> None:
        """
        Log order submission.
        
        Args:
            order_id: Order ID
            symbol: Trading symbol
            side: Buy or sell
            quantity: Order quantity
            price: Order price
            strategy: Strategy name
        """
        extra = {
            "extra_data": {
                "event": "ORDER_SUBMITTED",
                "order_id": order_id,
                "symbol": symbol,
                "side": side,
                "quantity": quantity,
                "price": price,
                "strategy": strategy
            }
        }
        self.logger.info(f"AUDIT: ORDER {order_id} {side} {quantity} {symbol} @ {price}", extra=extra)
    
    def log_fill(self, order_id: str, fill_price: float, fill_quantity: float, fees: float) -> None:
        """
        Log order fill.
        
        Args:
            order_id: Order ID
            fill_price: Fill price
            fill_quantity: Fill quantity
            fees: Fees paid
        """
        extra = {
            "extra_data": {
                "event": "ORDER_FILLED",
                "order_id": order_id,
                "fill_price": fill_price,
                "fill_quantity": fill_quantity,
                "fees": fees
            }
        }
        self.logger.info(f"AUDIT: FILL {order_id} {fill_quantity} @ {fill_price} fees={fees}", extra=extra)
    
    def log_kill_switch(self, reason: str, equity: float, floor: float) -> None:
        """
        Log kill switch activation.
        
        Args:
            reason: Trigger reason
            equity: Current equity
            floor: Trigger floor
        """
        extra = {
            "extra_data": {
                "event": "KILL_SWITCH",
                "reason": reason,
                "equity": equity,
                "floor": floor
            }
        }
        self.logger.critical(f"AUDIT: KILL SWITCH ACTIVATED - {reason}", extra=extra)
    
    def log_config_change(self, key: str, old_value: Any, new_value: Any, source: str) -> None:
        """
        Log configuration change.
        
        Args:
            key: Configuration key
            old_value: Previous value
            new_value: New value
            source: Change source
        """
        extra = {
            "extra_data": {
                "event": "CONFIG_CHANGE",
                "key": key,
                "old_value": old_value,
                "new_value": new_value,
                "source": source
            }
        }
        self.logger.info(f"AUDIT: CONFIG {key} changed from {old_value} to {new_value}", extra=extra)