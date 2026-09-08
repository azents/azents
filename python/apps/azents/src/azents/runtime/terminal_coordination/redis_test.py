"""Redis Runtime Terminal coordination codec tests."""

import inspect
import json
from datetime import UTC, datetime, timedelta

import pytest

from azents.core.runtime_connection_generation import (
    MAX_RUNTIME_CONNECTION_GENERATION,
)
from azents.runtime.terminal_coordination.data import RuntimeTerminalAdmission
from azents.runtime.terminal_coordination.redis import (
    RedisRuntimeTerminalCoordinationStore,
    _initial_record,  # Private test seam.
    _record_from_json,  # Private test seam.
    _record_to_json,  # Private test seam.
)

_NOW = datetime(2026, 9, 8, tzinfo=UTC)


def _admission() -> RuntimeTerminalAdmission:
    """Create one complete Terminal admission for codec verification."""
    return RuntimeTerminalAdmission(
        terminal_id="terminal-1",
        workspace_id="workspace-1",
        agent_id="agent-1",
        session_id="session-1",
        user_id="user-1",
        authentication_session_id="authentication-session-1",
        authentication_session_expires_at=_NOW + timedelta(days=1),
        runtime_id="runtime-1",
        provider_profile_id="provider-profile-1",
        provider_profile_version=1,
        workspace_profile_id="workspace-profile-1",
        workspace_profile_version=1,
        agent_policy_version="2026-09-08T00:00:00+00:00",
        desired_generation=1,
        runner_generation=MAX_RUNTIME_CONNECTION_GENERATION,
        working_directory="/workspace/session",
        stream_nonce="stream-nonce",
        created_at=_NOW,
        idle_deadline_at=_NOW + timedelta(minutes=30),
        maximum_deadline_at=_NOW + timedelta(hours=8),
        data_stream_grace_deadline_at=_NOW + timedelta(minutes=2),
        metadata_ttl_seconds=9 * 60 * 60,
    )


def test_default_terminal_namespace_is_v2() -> None:
    """Fresh Runtime Terminal state abandons every legacy volatile namespace."""
    default = (
        inspect.signature(RedisRuntimeTerminalCoordinationStore)
        .parameters["key_prefix"]
        .default
    )

    assert default == "runtime-terminal:v2"


def test_terminal_record_preserves_maximum_runner_generation_as_string() -> None:
    """Terminal Redis JSON preserves exact connection generations as strings."""
    record = _initial_record(_admission(), _NOW)

    encoded = _record_to_json(record)
    payload = json.loads(encoded)

    assert payload["admission"]["runner_generation"] == "9223372036854775807"
    assert _record_from_json(encoded) == record


@pytest.mark.parametrize("value", [0, 1, "1", "0000000000000000000"])
def test_terminal_record_rejects_noncanonical_runner_generation(
    value: object,
) -> None:
    """Terminal Redis records reject numeric and malformed generation values."""
    record = _initial_record(_admission(), _NOW)
    payload = json.loads(_record_to_json(record))
    payload["admission"]["runner_generation"] = value

    with pytest.raises(ValueError, match="connection-generation string"):
        _record_from_json(json.dumps(payload))
