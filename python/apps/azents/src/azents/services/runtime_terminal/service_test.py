"""Public Runtime Terminal service tests."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from azents_runtime_control.runner_terminal import RunnerTerminalTerminationReason

from azents.runtime.terminal_coordination.data import RuntimeTerminalRecord
from azents.runtime.terminal_coordination.memory import (
    InMemoryRuntimeTerminalCoordinationStore,
)
from azents.services.runtime_terminal.data import (
    RuntimeTerminalAttachRequest,
    RuntimeTerminalAuthority,
    RuntimeTerminalProjectionState,
    RuntimeTerminalReasonCode,
    RuntimeTerminalResource,
    RuntimeTerminalTicketStatus,
)
from azents.services.runtime_terminal.service import (
    RuntimeTerminalAdmissionError,
    RuntimeTerminalService,
)
from azents.services.runtime_terminal.ticket import HmacRuntimeTerminalTicketCodec

_NOW = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
_RESOURCE = RuntimeTerminalResource(
    workspace_handle="workspace",
    agent_id="agent-1",
    session_id="session-1",
)


class _Resolver:
    def __init__(self, authority: RuntimeTerminalAuthority) -> None:
        self.authority = authority
        self.calls = 0

    async def resolve(
        self,
        *,
        user_id: str,
        authentication_session_id: str,
        resource: RuntimeTerminalResource,
        resolved_at: datetime,
    ) -> RuntimeTerminalAuthority:
        assert user_id == self.authority.user_id
        assert authentication_session_id == self.authority.authentication_session_id
        assert resource == self.authority.resource
        assert resolved_at == _NOW
        self.calls += 1
        return self.authority


class _Dispatcher:
    def __init__(self) -> None:
        self.opened: list[tuple[str, int, int]] = []
        self.terminated: list[str] = []

    async def open_terminal(
        self,
        record: RuntimeTerminalRecord,
        *,
        columns: int,
        rows: int,
        requested_at: datetime,
    ) -> None:
        assert requested_at == _NOW
        self.opened.append((record.admission.terminal_id, columns, rows))

    async def terminate_terminal(
        self,
        record: RuntimeTerminalRecord,
        *,
        reason: RunnerTerminalTerminationReason,
        requested_at: datetime,
    ) -> None:
        del reason
        assert requested_at == _NOW
        self.terminated.append(record.admission.terminal_id)


@pytest.mark.asyncio
async def test_stopped_runtime_ticket_never_admits_or_starts() -> None:
    service, coordination, dispatcher, _resolver = _service(
        replace(
            _authority(),
            projection_state=RuntimeTerminalProjectionState.STOPPED,
            reason_code=RuntimeTerminalReasonCode.RUNTIME_STOPPED,
            can_start_runtime=True,
            can_open_or_attach=False,
        )
    )

    result = await service.issue_ticket(
        user_id="user-1",
        authentication_session_id="auth-session-1",
        resource=_RESOURCE,
    )

    assert result.status is RuntimeTerminalTicketStatus.RUNTIME_STOPPED
    assert result.ticket is None
    assert (
        await coordination.get_session_terminal("session-1", current_time=_NOW) is None
    )
    assert dispatcher.opened == []


@pytest.mark.asyncio
async def test_ticket_is_resource_bound_and_consumable_once() -> None:
    service, _coordination, _dispatcher, _resolver = _service(_authority())
    result = await service.issue_ticket(
        user_id="user-1",
        authentication_session_id="auth-session-1",
        resource=_RESOURCE,
    )
    assert result.ticket is not None

    admission = await service.consume_ticket(
        ticket=result.ticket,
        resource=_RESOURCE,
    )

    assert admission.claims.resource == _RESOURCE
    with pytest.raises(RuntimeTerminalAdmissionError):
        await service.consume_ticket(ticket=result.ticket, resource=_RESOURCE)

    other = replace(_RESOURCE, session_id="session-2")
    second = await service.issue_ticket(
        user_id="user-1",
        authentication_session_id="auth-session-1",
        resource=_RESOURCE,
    )
    assert second.ticket is not None
    with pytest.raises(RuntimeTerminalAdmissionError):
        await service.consume_ticket(ticket=second.ticket, resource=other)


@pytest.mark.asyncio
async def test_attach_admits_session_singleton_and_dispatches_open() -> None:
    service, coordination, dispatcher, _resolver = _service(_authority())
    ticket = await service.issue_ticket(
        user_id="user-1",
        authentication_session_id="auth-session-1",
        resource=_RESOURCE,
    )
    assert ticket.ticket is not None
    admission = await service.consume_ticket(ticket=ticket.ticket, resource=_RESOURCE)

    attachment = await service.attach(
        admission,
        RuntimeTerminalAttachRequest(
            columns=120,
            rows=40,
            last_output_sequence=None,
        ),
    )
    await attachment.input(sequence=1, data=b"pwd\n")
    await attachment.resize(sequence=1, columns=120, rows=40)
    await attachment.heartbeat(sequence=1)
    with pytest.raises(RuntimeTerminalAdmissionError):
        await attachment.resize(sequence=1, columns=100, rows=30)
    with pytest.raises(RuntimeTerminalAdmissionError):
        await attachment.heartbeat(sequence=1)

    record = await coordination.get_session_terminal(
        "session-1",
        current_time=_NOW,
    )
    assert record is not None
    assert record.pending_inputs[0].data == b"pwd\n"
    assert attachment.accepted.terminal_id == "terminal-1"
    assert attachment.accepted.next_input_sequence == 1
    assert dispatcher.opened == [("terminal-1", 120, 40)]
    with pytest.raises(RuntimeTerminalAdmissionError):
        await attachment.acknowledge_output(sequence=1)

    projection = await service.projection(
        user_id="user-1",
        authentication_session_id="auth-session-1",
        resource=_RESOURCE,
    )
    assert projection.state is RuntimeTerminalProjectionState.ACTIVE
    assert projection.terminal is not None
    await attachment.close()


@pytest.mark.asyncio
async def test_reattach_rejects_stale_runtime_generation_singleton() -> None:
    """Fresh authority cannot attach to an old-generation Session singleton."""
    service, coordination, dispatcher, resolver = _service(_authority())
    first_ticket = await service.issue_ticket(
        user_id="user-1",
        authentication_session_id="auth-session-1",
        resource=_RESOURCE,
    )
    assert first_ticket.ticket is not None
    first_admission = await service.consume_ticket(
        ticket=first_ticket.ticket,
        resource=_RESOURCE,
    )
    first = await service.attach(
        first_admission,
        RuntimeTerminalAttachRequest(
            columns=80,
            rows=24,
            last_output_sequence=None,
        ),
    )
    await first.close()
    resolver.authority = replace(
        resolver.authority,
        desired_generation=9,
    )
    second_ticket = await service.issue_ticket(
        user_id="user-1",
        authentication_session_id="auth-session-1",
        resource=_RESOURCE,
    )
    assert second_ticket.ticket is not None
    second_admission = await service.consume_ticket(
        ticket=second_ticket.ticket,
        resource=_RESOURCE,
    )

    with pytest.raises(RuntimeTerminalAdmissionError) as error:
        await service.attach(
            second_admission,
            RuntimeTerminalAttachRequest(
                columns=80,
                rows=24,
                last_output_sequence=None,
            ),
        )

    assert error.value.reason_code is RuntimeTerminalReasonCode.TERMINAL_REVOKED
    record = await coordination.get_terminal("terminal-1", current_time=_NOW)
    assert record is not None
    assert (
        record.termination_reason is RunnerTerminalTerminationReason.RUNTIME_INVALIDATED
    )
    assert dispatcher.terminated == ["terminal-1"]


@pytest.mark.asyncio
async def test_projection_never_exposes_terminal_summary_after_access_denial() -> None:
    """Identity denial cannot be overridden by a guessed Session Terminal record."""
    service, _coordination, _dispatcher, resolver = _service(_authority())
    ticket = await service.issue_ticket(
        user_id="user-1",
        authentication_session_id="auth-session-1",
        resource=_RESOURCE,
    )
    assert ticket.ticket is not None
    admission = await service.consume_ticket(ticket=ticket.ticket, resource=_RESOURCE)
    attachment = await service.attach(
        admission,
        RuntimeTerminalAttachRequest(
            columns=80,
            rows=24,
            last_output_sequence=None,
        ),
    )
    resolver.authority = replace(
        resolver.authority,
        projection_state=RuntimeTerminalProjectionState.ABSENT,
        reason_code=RuntimeTerminalReasonCode.ACCESS_DENIED,
        can_open_or_attach=False,
    )

    projection = await service.projection(
        user_id="user-1",
        authentication_session_id="auth-session-1",
        resource=_RESOURCE,
    )

    assert projection.state is RuntimeTerminalProjectionState.ABSENT
    assert projection.reason_code is RuntimeTerminalReasonCode.ACCESS_DENIED
    assert projection.terminal is None
    await attachment.close()


@pytest.mark.asyncio
async def test_projection_preserves_policy_denial_with_existing_terminal() -> None:
    """Existing metadata cannot turn a current policy denial back into ACTIVE."""
    service, _coordination, _dispatcher, resolver = _service(_authority())
    ticket = await service.issue_ticket(
        user_id="user-1",
        authentication_session_id="auth-session-1",
        resource=_RESOURCE,
    )
    assert ticket.ticket is not None
    admission = await service.consume_ticket(ticket=ticket.ticket, resource=_RESOURCE)
    attachment = await service.attach(
        admission,
        RuntimeTerminalAttachRequest(
            columns=80,
            rows=24,
            last_output_sequence=None,
        ),
    )
    resolver.authority = replace(
        resolver.authority,
        projection_state=RuntimeTerminalProjectionState.UNAVAILABLE,
        reason_code=RuntimeTerminalReasonCode.TERMINAL_DISABLED,
        can_open_or_attach=False,
    )

    projection = await service.projection(
        user_id="user-1",
        authentication_session_id="auth-session-1",
        resource=_RESOURCE,
    )

    assert projection.state is RuntimeTerminalProjectionState.UNAVAILABLE
    assert projection.reason_code is RuntimeTerminalReasonCode.TERMINAL_DISABLED
    assert projection.terminal is not None
    await attachment.close()


@pytest.mark.asyncio
async def test_revalidation_revokes_runtime_and_policy_authority_changes() -> None:
    service, _coordination, _dispatcher, resolver = _service(_authority())
    ticket = await service.issue_ticket(
        user_id="user-1",
        authentication_session_id="auth-session-1",
        resource=_RESOURCE,
    )
    assert ticket.ticket is not None
    admission = await service.consume_ticket(ticket=ticket.ticket, resource=_RESOURCE)

    changed_authorities = (
        replace(
            resolver.authority,
            authentication_session_expires_at=_NOW + timedelta(hours=2),
        ),
        replace(resolver.authority, desired_generation=8),
        replace(resolver.authority, runner_generation=8),
        replace(resolver.authority, workspace_profile_version=8),
        replace(resolver.authority, provider_profile_version=8),
        replace(
            resolver.authority,
            agent_policy_version="2026-09-01T12:01:00+00:00",
        ),
        replace(resolver.authority, working_directory="/workspace/other"),
    )
    for changed in changed_authorities:
        resolver.authority = changed
        assert (
            await service.revalidate(admission)
            is RuntimeTerminalReasonCode.TERMINAL_REVOKED
        )
    resolver.authority = replace(
        resolver.authority,
        can_open_or_attach=False,
        reason_code=RuntimeTerminalReasonCode.TERMINAL_DISABLED,
    )
    assert (
        await service.revalidate(admission)
        is RuntimeTerminalReasonCode.TERMINAL_DISABLED
    )


def _service(
    authority: RuntimeTerminalAuthority,
) -> tuple[
    RuntimeTerminalService,
    InMemoryRuntimeTerminalCoordinationStore,
    _Dispatcher,
    _Resolver,
]:
    coordination = InMemoryRuntimeTerminalCoordinationStore()
    dispatcher = _Dispatcher()
    resolver = _Resolver(authority)
    service = RuntimeTerminalService(
        authority_resolver=resolver,
        coordination=coordination,
        dispatcher=dispatcher,
        ticket_codec=HmacRuntimeTerminalTicketCodec(b"s" * 32),
        clock=lambda: _NOW,
        ticket_id_factory=lambda: "ticket-1",
        terminal_id_factory=lambda: "terminal-1",
        stream_nonce_factory=lambda: "nonce-1",
    )
    return service, coordination, dispatcher, resolver


def _authority() -> RuntimeTerminalAuthority:
    return RuntimeTerminalAuthority(
        user_id="user-1",
        authentication_session_id="auth-session-1",
        authentication_session_expires_at=_NOW + timedelta(days=1),
        workspace_id="workspace-1",
        resource=_RESOURCE,
        runtime_id="runtime-1",
        desired_generation=2,
        runner_generation=3,
        workspace_profile_id="workspace-profile-1",
        workspace_profile_version=4,
        provider_profile_id="provider-profile-1",
        provider_profile_version=5,
        agent_policy_version="2026-09-01T12:00:00+00:00",
        working_directory="/workspace/session",
        working_directory_display="~/session",
        shell_label="bash",
        projection_state=RuntimeTerminalProjectionState.READY,
        reason_code=None,
        denied_scope=None,
        can_start_runtime=False,
        can_open_or_attach=True,
    )
