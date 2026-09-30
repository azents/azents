"""Redis Runtime Terminal coordination codec tests."""

import asyncio
import dataclasses
import inspect
import json
from datetime import UTC, datetime, timedelta

import pytest
from azents_runtime_control.runner_terminal import RunnerTerminalTerminationReason
from redis.asyncio import Redis

from azents.core.runtime_connection_generation import (
    MAX_RUNTIME_CONNECTION_GENERATION,
)
from azents.runtime.terminal_coordination.data import (
    RuntimeTerminalAdmission,
    RuntimeTerminalMutationStatus,
)
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


@pytest.mark.parametrize("pointer_kind", ["session", "session-final"])
async def test_stale_session_pointer_cleanup_preserves_concurrent_replacement(
    redis_url: str, monkeypatch: pytest.MonkeyPatch, pointer_kind: str
) -> None:
    """Real Redis cleanup cannot delete a replacement after an old record expires."""
    prefix = f"terminal-pointer-race:{pointer_kind}"
    async with Redis.from_url(redis_url) as client:
        store = RedisRuntimeTerminalCoordinationStore(client, key_prefix=prefix)
        original = await store.admit_or_get(_admission(), admitted_at=_NOW)
        assert original.status is RuntimeTerminalMutationStatus.APPLIED
        pointer = f"{prefix}:{pointer_kind}:session-1"
        active_pointer = f"{prefix}:session:session-1"
        old_record = f"{prefix}:terminal:terminal-1"
        if pointer_kind == "session-final":
            await client.delete(active_pointer)
            await client.set(pointer, "terminal-1", ex=60)
        # Redis expiration is deterministic; no shortened wall-clock sleep is needed.
        await client.pexpire(old_record, 0)
        observed_missing = asyncio.Event()
        resume_cleanup = asyncio.Event()
        real_exists = client.exists

        async def paused_exists(*names: str) -> int:
            result = await real_exists(*names)
            if names == (old_record,):
                assert result == 0
                observed_missing.set()
                await resume_cleanup.wait()
            return result

        monkeypatch.setattr(client, "exists", paused_exists)
        lookup = asyncio.create_task(
            store.get_session_terminal("session-1", current_time=_NOW)
        )
        try:
            await asyncio.wait_for(observed_missing.wait(), timeout=5)
            replacement = await store.admit_or_get(
                dataclasses.replace(_admission(), terminal_id="terminal-2"),
                admitted_at=_NOW,
            )
            assert replacement.value is not None
            assert replacement.value.admission.terminal_id == "terminal-2"
            if pointer_kind == "session-final":
                await store.request_termination(
                    "terminal-2",
                    reason=RunnerTerminalTerminationReason.PROCESS_EXIT,
                    requested_at=_NOW,
                )
                finalized = await store.finalize_terminal(
                    "terminal-2",
                    reason=RunnerTerminalTerminationReason.PROCESS_EXIT,
                    exit_code=0,
                    finalized_at=_NOW,
                    runner_stream_generation=None,
                    final_ttl_seconds=60,
                )
                assert finalized.status is RuntimeTerminalMutationStatus.APPLIED
            resume_cleanup.set()
            result = await asyncio.wait_for(lookup, timeout=5)
            assert result is not None
            assert result.admission.terminal_id == "terminal-2"
            assert await client.get(pointer) == b"terminal-2"
            latest = await store.get_session_terminal("session-1", current_time=_NOW)
            assert latest is not None and latest.admission.terminal_id == "terminal-2"
            if pointer_kind == "session":
                subsequent = await store.admit_or_get(
                    dataclasses.replace(_admission(), terminal_id="terminal-3"),
                    admitted_at=_NOW,
                )
                assert subsequent.value is not None
                assert subsequent.value.admission.terminal_id == "terminal-2"
                assert not await client.exists(f"{prefix}:terminal:terminal-3")
        finally:
            resume_cleanup.set()
            if not lookup.done():
                lookup.cancel()
            await asyncio.gather(lookup, return_exceptions=True)
            keys = [key async for key in client.scan_iter(match=f"{prefix}:*")]
            if keys:
                await client.delete(*keys)
