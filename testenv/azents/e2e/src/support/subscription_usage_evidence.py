"""Pure serialization and log evidence utilities for subscription usage QA."""

import json
from dataclasses import dataclass

from pydantic import TypeAdapter

_JSON_OBJECT = TypeAdapter(dict[str, object])


@dataclass(frozen=True)
class _SubscriptionUsageLogRecord:
    """Typed log source and an opaque record retained only as QA evidence."""

    name: str | None
    wire: dict[str, object]

    @classmethod
    def decode(cls, line: str) -> "_SubscriptionUsageLogRecord":
        """Validate interpreted source fields without constraining log extras."""
        wire = _JSON_OBJECT.validate_python(json.loads(line))
        name = wire.get("name")
        # Missing and null source names are unrelated records; malformed names
        # are rejected at ingress and skipped with other malformed log lines.
        if name is not None and not isinstance(name, str):
            raise ValueError("Structured log source name must be a string or null.")
        return cls(name=name, wire=wire)


def json_object(value: dict[str, object]) -> dict[str, object]:
    """Convert generated-client dictionaries into JSON-compatible values."""
    return _JSON_OBJECT.validate_python(_JSON_OBJECT.dump_python(value, mode="json"))


def subscription_usage_log_records(logs: str) -> list[dict[str, object]]:
    """Return structured log records emitted by subscription usage services."""
    records: list[dict[str, object]] = []
    for line in logs.splitlines():
        try:
            record = _SubscriptionUsageLogRecord.decode(line)
        except ValueError:
            continue
        if record.name is not None and record.name.startswith(
            "azents.services.subscription_usage"
        ):
            records.append(record.wire)
    assert records
    return records
