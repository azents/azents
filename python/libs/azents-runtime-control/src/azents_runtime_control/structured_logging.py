"""Structured logging helpers for Runtime processes."""

import json
import logging
from datetime import UTC, datetime

_STANDARD_LOG_RECORD_FIELDS = frozenset(logging.makeLogRecord({}).__dict__) | {
    "asctime",
    "message",
}


class StructuredLogFormatter(logging.Formatter):
    """Serialize Runtime logs and structured extras as one JSON object."""

    def format(self, record: logging.LogRecord) -> str:
        """Format one log record as compact JSON."""
        payload: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        payload.update(
            {
                key: value
                for key, value in record.__dict__.items()
                if key not in _STANDARD_LOG_RECORD_FIELDS
            }
        )
        if record.exc_info is not None:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, separators=(",", ":"))
