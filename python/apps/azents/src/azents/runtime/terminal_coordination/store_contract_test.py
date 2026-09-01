"""Parity contract tests for volatile Runtime Terminal coordination stores."""

import asyncio
import dataclasses
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from azents_runtime_control.runner_terminal import (
    RunnerTerminalIdentity,
    RunnerTerminalStreamRegistration,
    RunnerTerminalTerminationReason,
)
from redis.asyncio import Redis

from azents.runtime.terminal_coordination.data import (
    MAX_ACTIVE_TERMINALS_PER_RUNTIME,
    MAX_ACTIVE_TERMINALS_PER_USER,
    MAX_LIVE_OUTPUT_BYTES,
    MAX_TERMINAL_CHUNK_BYTES,
    RuntimeTerminalAdmission,
    RuntimeTerminalInvalidationSource,
    RuntimeTerminalLifecycle,
    RuntimeTerminalMutationStatus,
    RuntimeTerminalRecord,
    RuntimeTerminalTicket,
    RuntimeTerminalTicketBinding,
    RuntimeTerminalTicketIntent,
)
from azents.runtime.terminal_coordination.memory import (
    InMemoryRuntimeTerminalCoordinationStore,
)
from azents.runtime.terminal_coordination.redis import (
    RedisRuntimeTerminalCoordinationStore,
)
from azents.runtime.terminal_coordination.store import (
    RuntimeTerminalCoordinationStore,
)

_NOW = datetime.now(UTC)


@pytest_asyncio.fixture(params=["memory", "redis"])
async def store(
    request: pytest.FixtureRequest,
) -> AsyncGenerator[RuntimeTerminalCoordinationStore, None]:
    """Run each behavioral contract against both store backends."""
    if request.param == "memory":
        yield InMemoryRuntimeTerminalCoordinationStore()
        return
    client = Redis.from_url(str(request.getfixturevalue("redis_url")))
    await client.flushall()
    try:
        yield RedisRuntimeTerminalCoordinationStore(client)
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_admission_session_lookup_and_user_quota(
    store: RuntimeTerminalCoordinationStore,
) -> None:
    first = await store.admit_or_get(_admission(1), admitted_at=_NOW)
    same = await store.admit_or_get(
        _admission(2, session_id="session-1"),
        admitted_at=_NOW,
    )
    assert first.value is not None
    assert same.value == first.value
    assert (
        await store.get_session_terminal("session-1", current_time=_NOW) == first.value
    )

    for number in range(2, MAX_ACTIVE_TERMINALS_PER_USER + 1):
        result = await store.admit_or_get(_admission(number), admitted_at=_NOW)
        assert result.status is RuntimeTerminalMutationStatus.APPLIED
    denied = await store.admit_or_get(
        _admission(MAX_ACTIVE_TERMINALS_PER_USER + 1),
        admitted_at=_NOW,
    )
    assert denied.status is RuntimeTerminalMutationStatus.QUOTA_EXCEEDED


@pytest.mark.asyncio
async def test_ticket_is_binding_fenced_and_consumed_once(
    store: RuntimeTerminalCoordinationStore,
) -> None:
    binding = _ticket_binding()
    ticket = RuntimeTerminalTicket(
        ticket_id="ticket-1",
        binding=binding,
        issued_at=_NOW,
        expires_at=_NOW + timedelta(seconds=30),
    )
    await store.issue_ticket(ticket, ttl_seconds=30)
    wrong = dataclasses.replace(binding, authentication_session_id="other")

    mismatch = await store.consume_ticket(
        "ticket-1", expected_binding=wrong, consumed_at=_NOW
    )
    consumed = await store.consume_ticket(
        "ticket-1", expected_binding=binding, consumed_at=_NOW
    )
    repeated = await store.consume_ticket(
        "ticket-1", expected_binding=binding, consumed_at=_NOW
    )

    assert mismatch.status is RuntimeTerminalMutationStatus.TICKET_BINDING_MISMATCH
    assert consumed.value == ticket
    assert repeated.status is RuntimeTerminalMutationStatus.TICKET_MISSING


@pytest.mark.asyncio
async def test_generations_sequences_io_and_backpressure(
    store: RuntimeTerminalCoordinationStore,
) -> None:
    record, attachment_generation, stream_generation = await _connected(store)
    first_input = await store.enqueue_input(
        record.admission.terminal_id,
        attachment_generation=attachment_generation,
        sequence=1,
        data=b"echo ready\n",
        accepted_at=_NOW,
    )
    gap = await store.enqueue_input(
        record.admission.terminal_id,
        attachment_generation=attachment_generation,
        sequence=3,
        data=b"gap",
        accepted_at=_NOW,
    )
    inputs = await store.read_inputs(
        record.admission.terminal_id,
        runner_stream_generation=stream_generation,
        after_sequence=0,
        maximum_bytes=MAX_TERMINAL_CHUNK_BYTES,
        current_time=_NOW,
    )
    await store.acknowledge_input(
        record.admission.terminal_id,
        runner_stream_generation=stream_generation,
        sequence=1,
        acknowledged_at=_NOW,
    )
    resize = await store.update_resize(
        record.admission.terminal_id,
        attachment_generation=attachment_generation,
        columns=120,
        rows=40,
        updated_at=_NOW,
    )
    chunk = b"x" * MAX_TERMINAL_CHUNK_BYTES
    count = MAX_LIVE_OUTPUT_BYTES // len(chunk)
    for sequence in range(1, count + 1):
        result = await store.append_output(
            record.admission.terminal_id,
            runner_stream_generation=stream_generation,
            sequence=sequence,
            data=chunk,
            accepted_at=_NOW,
        )
        assert result.status is RuntimeTerminalMutationStatus.APPLIED
    blocked = await store.append_output(
        record.admission.terminal_id,
        runner_stream_generation=stream_generation,
        sequence=count + 1,
        data=b"x",
        accepted_at=_NOW,
    )
    browser = await store.read_output(
        record.admission.terminal_id,
        attachment_generation=attachment_generation,
        after_sequence=0,
        maximum_bytes=MAX_TERMINAL_CHUNK_BYTES,
        current_time=_NOW,
    )
    replay = await store.replay_output(
        record.admission.terminal_id,
        attachment_generation=attachment_generation,
        after_sequence=0,
        maximum_bytes=MAX_TERMINAL_CHUNK_BYTES,
        current_time=_NOW,
    )

    assert first_input.status is RuntimeTerminalMutationStatus.APPLIED
    assert gap.status is RuntimeTerminalMutationStatus.SEQUENCE_REJECTED
    assert inputs.value is not None and inputs.value.inputs[0].sequence == 1
    assert resize.value is not None and resize.value.columns == 120
    assert blocked.status is RuntimeTerminalMutationStatus.CAPACITY_EXCEEDED
    assert browser.value is not None and browser.value.outputs[0].sequence == 1
    assert replay.value is not None and replay.value.outputs[0].sequence == 1


@pytest.mark.asyncio
async def test_stream_detach_and_source_invalidation_are_fenced(
    store: RuntimeTerminalCoordinationStore,
) -> None:
    record, _attachment_generation, stream_generation = await _connected(store)
    stale = await store.detach_runner_stream(
        record.admission.terminal_id,
        runner_stream_generation=stream_generation + 1,
        detached_at=_NOW,
        grace_seconds=120,
    )
    detached = await store.detach_runner_stream(
        record.admission.terminal_id,
        runner_stream_generation=stream_generation,
        detached_at=_NOW,
        grace_seconds=120,
    )
    invalidated = await store.invalidate(
        source=RuntimeTerminalInvalidationSource.AGENT,
        source_id=record.admission.agent_id,
        reason=RunnerTerminalTerminationReason.POLICY_REVOKED,
        invalidated_at=_NOW,
    )
    latest = await store.get_terminal(record.admission.terminal_id, current_time=_NOW)

    assert stale.status is RuntimeTerminalMutationStatus.STALE_RUNNER_STREAM_GENERATION
    assert detached.value is not None
    assert detached.value.runner_stream_grace_expires_at == _NOW + timedelta(
        seconds=120
    )
    assert invalidated.terminal_ids == (record.admission.terminal_id,)
    assert (
        latest is not None and latest.lifecycle is RuntimeTerminalLifecycle.TERMINATING
    )


@pytest.mark.asyncio
async def test_access_invalidation_is_authentication_session_scoped(
    store: RuntimeTerminalCoordinationStore,
) -> None:
    first = await store.admit_or_get(_admission(1), admitted_at=_NOW)
    second_admission = dataclasses.replace(
        _admission(2),
        authentication_session_id="auth-session-2",
    )
    second = await store.admit_or_get(second_admission, admitted_at=_NOW)
    invalidated = await store.invalidate(
        source=RuntimeTerminalInvalidationSource.ACCESS,
        source_id="auth-session-1",
        reason=RunnerTerminalTerminationReason.ACCESS_REVOKED,
        invalidated_at=_NOW,
    )

    assert first.value is not None and second.value is not None
    assert invalidated.terminal_ids == (first.value.admission.terminal_id,)
    current_first = await store.get_terminal(
        first.value.admission.terminal_id,
        current_time=_NOW,
    )
    current_second = await store.get_terminal(
        second.value.admission.terminal_id,
        current_time=_NOW,
    )
    assert current_first is not None
    assert current_first.lifecycle is RuntimeTerminalLifecycle.TERMINATING
    assert current_second is not None
    assert current_second.lifecycle is RuntimeTerminalLifecycle.OPENING


@pytest.mark.asyncio
async def test_no_runner_invalidation_gets_bounded_finalization_grace(
    store: RuntimeTerminalCoordinationStore,
) -> None:
    record = await _admit(store)
    invalidated = await store.invalidate(
        source=RuntimeTerminalInvalidationSource.USER,
        source_id=record.admission.user_id,
        reason=RunnerTerminalTerminationReason.ACCESS_REVOKED,
        invalidated_at=_NOW,
    )
    terminating = await store.get_terminal(
        record.admission.terminal_id,
        current_time=_NOW,
    )

    assert invalidated.terminal_ids == (record.admission.terminal_id,)
    assert terminating is not None
    assert terminating.runner_stream_grace_expires_at == _NOW + timedelta(seconds=120)

    await store.repair_expired(
        current_time=_NOW + timedelta(seconds=121),
        limit=10,
    )
    finalized = await store.get_terminal(
        record.admission.terminal_id,
        current_time=_NOW + timedelta(seconds=121),
    )
    assert finalized is not None
    assert finalized.lifecycle is RuntimeTerminalLifecycle.EXITED


@pytest.mark.asyncio
async def test_authentication_session_expiry_requests_access_revocation(
    store: RuntimeTerminalCoordinationStore,
) -> None:
    admission = dataclasses.replace(
        _admission(1),
        authentication_session_expires_at=_NOW + timedelta(seconds=5),
    )
    created = await store.admit_or_get(admission, admitted_at=_NOW)
    assert created.value is not None

    repaired = await store.repair_expired(
        current_time=_NOW + timedelta(seconds=6),
        limit=10,
    )
    current = await store.get_terminal(
        admission.terminal_id,
        current_time=_NOW + timedelta(seconds=6),
    )

    assert repaired.terminal_ids == (admission.terminal_id,)
    assert current is not None
    assert current.lifecycle is RuntimeTerminalLifecycle.TERMINATING
    assert current.termination_reason is RunnerTerminalTerminationReason.ACCESS_REVOKED
    assert current.runner_stream_grace_expires_at == _NOW + timedelta(seconds=126)


@pytest.mark.asyncio
async def test_session_lookup_prefers_active_then_bounded_latest_final(
    store: RuntimeTerminalCoordinationStore,
) -> None:
    first, _attachment_generation, stream_generation = await _connected(store)
    await store.request_termination(
        first.admission.terminal_id,
        reason=RunnerTerminalTerminationReason.CALLER,
        requested_at=_NOW,
    )
    finalized = await store.finalize_terminal(
        first.admission.terminal_id,
        runner_stream_generation=stream_generation,
        reason=RunnerTerminalTerminationReason.CALLER,
        exit_code=0,
        finalized_at=_NOW,
        final_ttl_seconds=300,
    )
    latest_final = await store.get_session_terminal(
        first.admission.session_id,
        current_time=_NOW,
    )
    second = await store.admit_or_get(
        _admission(2, session_id=first.admission.session_id),
        admitted_at=_NOW,
    )
    active = await store.get_session_terminal(
        first.admission.session_id,
        current_time=_NOW,
    )

    assert finalized.value is not None
    assert latest_final == finalized.value
    assert second.value is not None
    assert active == second.value
    assert (
        await store.get_terminal(
            first.admission.terminal_id,
            current_time=_NOW,
        )
        == finalized.value
    )


@pytest.mark.asyncio
async def test_stale_runner_stream_cannot_finalize_replacement(
    store: RuntimeTerminalCoordinationStore,
) -> None:
    """A replaced stream cannot finalize the Terminal owned by its successor."""
    record, _attachment_generation, stream_generation = await _connected(store)
    replacement = dataclasses.replace(
        _registration(record),
        stream_generation=stream_generation + 1,
    )
    registered = await store.register_runner_stream(
        replacement,
        desired_generation=record.admission.desired_generation,
        connected_at=_NOW,
        lease_seconds=30,
    )
    assert registered.status is RuntimeTerminalMutationStatus.APPLIED

    stale = await store.finalize_terminal(
        record.admission.terminal_id,
        runner_stream_generation=stream_generation,
        reason=RunnerTerminalTerminationReason.PROCESS_EXIT,
        exit_code=0,
        finalized_at=_NOW,
        final_ttl_seconds=300,
    )
    latest = await store.get_terminal(record.admission.terminal_id, current_time=_NOW)

    assert stale.status is RuntimeTerminalMutationStatus.STALE_RUNNER_STREAM_GENERATION
    assert latest is not None
    assert latest.lifecycle is not RuntimeTerminalLifecycle.EXITED
    assert latest.runner_stream is not None
    assert latest.runner_stream.generation == stream_generation + 1


@pytest.mark.asyncio
async def test_terminating_terminal_accepts_reconnect_and_exact_finalization(
    store: RuntimeTerminalCoordinationStore,
) -> None:
    """A terminating PTY may reconnect during grace but only its owner finalizes it."""
    record, _attachment_generation, stream_generation = await _connected(store)
    requested = await store.request_termination(
        record.admission.terminal_id,
        reason=RunnerTerminalTerminationReason.CALLER,
        requested_at=_NOW,
    )
    assert requested.value is not None
    assert requested.value.runner_stream is not None

    detached = await store.detach_runner_stream(
        record.admission.terminal_id,
        runner_stream_generation=stream_generation,
        detached_at=_NOW,
        grace_seconds=120,
    )
    assert detached.value is not None
    assert detached.value.lifecycle is RuntimeTerminalLifecycle.TERMINATING
    replacement_generation = stream_generation + 1
    replacement = await store.register_runner_stream(
        dataclasses.replace(
            _registration(record),
            stream_generation=replacement_generation,
        ),
        desired_generation=record.admission.desired_generation,
        connected_at=_NOW + timedelta(seconds=1),
        lease_seconds=30,
    )
    assert replacement.status is RuntimeTerminalMutationStatus.APPLIED

    stale = await store.finalize_terminal(
        record.admission.terminal_id,
        runner_stream_generation=stream_generation,
        reason=RunnerTerminalTerminationReason.PROCESS_EXIT,
        exit_code=0,
        finalized_at=_NOW + timedelta(seconds=2),
        final_ttl_seconds=300,
    )
    finalized = await store.finalize_terminal(
        record.admission.terminal_id,
        runner_stream_generation=replacement_generation,
        reason=RunnerTerminalTerminationReason.PROCESS_EXIT,
        exit_code=0,
        finalized_at=_NOW + timedelta(seconds=2),
        final_ttl_seconds=300,
    )

    assert stale.status is RuntimeTerminalMutationStatus.STALE_RUNNER_STREAM_GENERATION
    assert finalized.value is not None
    assert finalized.value.lifecycle is RuntimeTerminalLifecycle.EXITED


@pytest.mark.asyncio
async def test_redis_admission_prunes_stale_session_and_user_indexes(
    store: RuntimeTerminalCoordinationStore,
) -> None:
    """Expired Redis records do not retain Session ownership or user quota."""
    if not isinstance(store, RedisRuntimeTerminalCoordinationStore):
        pytest.skip("Redis-specific stale-index contract")
    first = await _admit(store)
    await store._redis.delete(store._record_key(first.admission.terminal_id))

    replacement = await store.admit_or_get(
        _admission(2, session_id=first.admission.session_id),
        admitted_at=_NOW,
    )

    assert replacement.status is RuntimeTerminalMutationStatus.APPLIED
    assert replacement.value is not None
    assert replacement.value.admission.terminal_id == "terminal-2"


@pytest.mark.asyncio
async def test_redis_admission_prunes_stale_runtime_quota_members(
    store: RuntimeTerminalCoordinationStore,
) -> None:
    """Expired Redis records cannot permanently consume Runtime quota."""
    if not isinstance(store, RedisRuntimeTerminalCoordinationStore):
        pytest.skip("Redis-specific stale-index contract")
    terminal_ids: list[str] = []
    for number in range(1, MAX_ACTIVE_TERMINALS_PER_RUNTIME + 1):
        admission = dataclasses.replace(
            _admission(number),
            user_id=f"user-{number}",
            runtime_id="runtime-shared",
        )
        created = await store.admit_or_get(admission, admitted_at=_NOW)
        assert created.status is RuntimeTerminalMutationStatus.APPLIED
        terminal_ids.append(admission.terminal_id)
    await store._redis.delete(*(store._record_key(item) for item in terminal_ids))

    replacement = await store.admit_or_get(
        dataclasses.replace(
            _admission(99),
            user_id="user-99",
            runtime_id="runtime-shared",
        ),
        admitted_at=_NOW,
    )

    assert replacement.status is RuntimeTerminalMutationStatus.APPLIED


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("kind", "reason"),
    [
        ("initial", RunnerTerminalTerminationReason.DATA_STREAM_GRACE_EXPIRED),
        ("runner", RunnerTerminalTerminationReason.DATA_STREAM_GRACE_EXPIRED),
        ("browser", RunnerTerminalTerminationReason.DATA_STREAM_GRACE_EXPIRED),
        ("idle", RunnerTerminalTerminationReason.IDLE),
        ("maximum", RunnerTerminalTerminationReason.MAXIMUM_LIFETIME),
    ],
)
async def test_repair_expired_covers_independent_deadlines(
    store: RuntimeTerminalCoordinationStore,
    kind: str,
    reason: RunnerTerminalTerminationReason,
) -> None:
    record = await _admit(store)
    current_time = _NOW + timedelta(minutes=3)
    if kind == "runner":
        registered = await store.register_runner_stream(
            _registration(record),
            desired_generation=record.admission.desired_generation,
            connected_at=_NOW,
            lease_seconds=30,
        )
        assert registered.value is not None
        await store.detach_runner_stream(
            record.admission.terminal_id,
            runner_stream_generation=registered.value.accepted.stream_generation,
            detached_at=_NOW,
            grace_seconds=1,
        )
        current_time = _NOW + timedelta(seconds=2)
    elif kind == "browser":
        attachment = await store.attach_browser(
            record.admission.terminal_id,
            user_id=record.admission.user_id,
            attached_at=_NOW,
            lease_seconds=45,
        )
        assert attachment.value is not None
        await store.detach_browser(
            record.admission.terminal_id,
            attachment_generation=attachment.value.generation,
            detached_at=_NOW,
            grace_seconds=1,
        )
        current_time = _NOW + timedelta(seconds=2)
    elif kind == "idle":
        current_time = _NOW + timedelta(minutes=31)
    elif kind == "maximum":
        current_time = _NOW + timedelta(hours=8, seconds=1)

    repaired = await store.repair_expired(current_time=current_time, limit=10)
    latest = await store.get_terminal(
        record.admission.terminal_id, current_time=current_time
    )
    assert repaired.terminal_ids == (record.admission.terminal_id,)
    assert latest is not None and latest.termination_reason is reason


@pytest.mark.asyncio
async def test_wait_for_change_uses_notification_not_poll_sleep(
    store: RuntimeTerminalCoordinationStore,
) -> None:
    record = await _admit(store)
    waiting = asyncio.create_task(
        store.wait_for_change(
            record.admission.terminal_id,
            after_revision=record.revision,
            timeout_seconds=1,
        )
    )
    await store.request_termination(
        record.admission.terminal_id,
        reason=RunnerTerminalTerminationReason.CALLER,
        requested_at=_NOW,
    )
    changed = await asyncio.wait_for(waiting, timeout=1)
    assert changed is not None and changed.revision > record.revision


async def _admit(
    store: RuntimeTerminalCoordinationStore,
) -> RuntimeTerminalRecord:
    result = await store.admit_or_get(_admission(1), admitted_at=_NOW)
    assert result.value is not None
    return result.value


async def _connected(
    store: RuntimeTerminalCoordinationStore,
) -> tuple[RuntimeTerminalRecord, int, int]:
    record = await _admit(store)
    attachment = await store.attach_browser(
        record.admission.terminal_id,
        user_id=record.admission.user_id,
        attached_at=_NOW,
        lease_seconds=45,
    )
    registered = await store.register_runner_stream(
        _registration(record),
        desired_generation=record.admission.desired_generation,
        connected_at=_NOW,
        lease_seconds=30,
    )
    assert attachment.value is not None and registered.value is not None
    return (
        record,
        attachment.value.generation,
        registered.value.accepted.stream_generation,
    )


def _admission(
    number: int,
    *,
    session_id: str | None = None,
) -> RuntimeTerminalAdmission:
    return RuntimeTerminalAdmission(
        terminal_id=f"terminal-{number}",
        workspace_id="workspace-1",
        agent_id=f"agent-{number}",
        session_id=session_id or f"session-{number}",
        user_id="user-1",
        authentication_session_id="auth-session-1",
        authentication_session_expires_at=_NOW + timedelta(days=1),
        runtime_id=f"runtime-{number}",
        provider_profile_id="provider-profile-1",
        provider_profile_version=1,
        workspace_profile_id="workspace-profile-1",
        workspace_profile_version=1,
        agent_policy_version="2026-09-01T12:00:00+00:00",
        desired_generation=5,
        runner_generation=7,
        working_directory="/workspace/session",
        stream_nonce=f"nonce-{number}",
        created_at=_NOW,
        idle_deadline_at=_NOW + timedelta(minutes=30),
        maximum_deadline_at=_NOW + timedelta(hours=8),
        data_stream_grace_deadline_at=_NOW + timedelta(minutes=2),
        metadata_ttl_seconds=9 * 60 * 60,
    )


def _registration(record: RuntimeTerminalRecord) -> RunnerTerminalStreamRegistration:
    return RunnerTerminalStreamRegistration(
        identity=RunnerTerminalIdentity(
            terminal_id=record.admission.terminal_id,
            runtime_id=record.admission.runtime_id,
            runner_generation=record.admission.runner_generation,
        ),
        stream_generation=1,
        stream_nonce=record.admission.stream_nonce,
        last_control_acknowledged_output_sequence=0,
        highest_completely_applied_input_sequence=0,
        partial_input_sequence=None,
        partial_input_bytes_written=None,
    )


def _ticket_binding() -> RuntimeTerminalTicketBinding:
    return RuntimeTerminalTicketBinding(
        user_id="user-1",
        authentication_session_id="auth-session-1",
        workspace_id="workspace-1",
        agent_id="agent-1",
        session_id="session-1",
        intent=RuntimeTerminalTicketIntent.OPEN_OR_ATTACH,
    )
