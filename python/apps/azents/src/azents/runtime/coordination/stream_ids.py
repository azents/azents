"""Canonical Runtime coordination stream identities."""

from azents.core.runtime_connection_generation import (
    runtime_connection_generation_to_redis,
)
from azents.runtime.coordination.data import RuntimeCoordinationTarget


def operation_reply_stream_id(
    *,
    target: RuntimeCoordinationTarget,
    subject_id: str,
    generation: int,
    request_id: str,
) -> str:
    """Return one request-scoped reply stream identity."""
    value = runtime_connection_generation_to_redis(generation)
    return f"{target.value}:{subject_id}:generation:{value}:replies:{request_id}"
