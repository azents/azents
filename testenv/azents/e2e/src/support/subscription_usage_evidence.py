"""Pure serialization and log evidence utilities for subscription usage QA."""

import json

from pydantic import TypeAdapter

_JSON_OBJECT = TypeAdapter(dict[str, object])


def json_object(value: dict[str, object]) -> dict[str, object]:
    """Convert generated-client dictionaries into JSON-compatible values."""
    return _JSON_OBJECT.validate_python(_JSON_OBJECT.dump_python(value, mode="json"))


def subscription_usage_log_records(logs: str) -> list[dict[str, object]]:
    """Return structured log records emitted by subscription usage services."""
    records: list[dict[str, object]] = []
    for line in logs.splitlines():
        try:
            record = _JSON_OBJECT.validate_python(json.loads(line))
        except ValueError:
            continue
        name = record.get("name")
        if isinstance(name, str) and name.startswith(
            "azents.services.subscription_usage"
        ):
            records.append(record)
    assert records
    return records
