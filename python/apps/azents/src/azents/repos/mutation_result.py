"""Native SQLAlchemy mutation-result narrowing."""

from typing import Any

from sqlalchemy.engine import CursorResult


def mutation_result(value: object) -> CursorResult[Any]:
    """Validate the native DML result before reading its affected row count."""
    if not isinstance(value, CursorResult):
        raise RuntimeError("SQLAlchemy mutation did not return CursorResult")
    return value
