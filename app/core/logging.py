"""Structured logging configuration.

Supports two formats controlled by the LOG_FORMAT setting:
- "text" (default): Human-readable format for development
- "json": Structured JSON format for production log aggregation
"""
import logging
import sys
from datetime import datetime, timezone

from pythonjsonlogger import json as json_logger


class _JsonFormatter(json_logger.JsonFormatter):
    """Custom JSON formatter with standard field names."""

    def add_fields(self, log_record, record, message_dict):
        super().add_fields(log_record, record, message_dict)
        log_record["timestamp"] = datetime.now(timezone.utc).isoformat()
        log_record["level"] = record.levelname
        log_record["logger"] = record.name
        log_record["module"] = record.module
        log_record["function"] = record.funcName
        log_record["line"] = record.lineno


_TEXT_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"


def setup_logging(log_level: str = "INFO", log_format: str = "text") -> None:
    """Configure root logger with the specified format.

    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        log_format: "text" for human-readable, "json" for structured output.
    """
    root = logging.getLogger()
    root.setLevel(getattr(logging, log_level.upper(), logging.INFO))

    # Remove existing handlers (avoid duplicates on re-init)
    root.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)

    if log_format.lower() == "json":
        handler.setFormatter(_JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter(_TEXT_FORMAT))

    root.addHandler(handler)

    # Quiet down noisy libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("chromadb").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
