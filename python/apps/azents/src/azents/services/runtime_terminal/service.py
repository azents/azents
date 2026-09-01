"""Public Runtime Terminal projection, ticket, and attachment service."""

from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol

from azents_runtime_control.runner_terminal import RunnerTerminalTerminationReason

from azents.runtime.terminal_coordination.data import (
    MAX_REPLAY_BYTES,
    RuntimeTerminalMutationStatus,
    RuntimeTerminalRecord,
    RuntimeTerminalTicket,
    RuntimeTerminalTicketBinding,
    RuntimeTerminalTicketIntent,
)
from azents.runtime.terminal_coordination.data import (
    RuntimeTerminalAdmission as CoordinationAdmission,
)
from azents.runtime.terminal_coordination.data import (
    RuntimeTerminalLifecycle as CoordinationLifecycle,
)
from azents.runtime.terminal_coordination.data import (
    RuntimeTerminalOutput as CoordinationOutput,
)
from azents.runtime.terminal_coordination.store import RuntimeTerminalCoordinationStore
from azents.services.runtime_terminal.data import (
    RuntimeTerminalAttachment,
    RuntimeTerminalAttachmentAccepted,
    RuntimeTerminalAttachRequest,
    RuntimeTerminalAuthority,
    RuntimeTerminalExited,
    RuntimeTerminalInputAcknowledged,
    RuntimeTerminalLifecycle,
    RuntimeTerminalOutput,
    RuntimeTerminalProjection,
    RuntimeTerminalProjectionState,
    RuntimeTerminalReasonCode,
    RuntimeTerminalResource,
    RuntimeTerminalRevoked,
    RuntimeTerminalServerEvent,
    RuntimeTerminalSocketAdmission,
    RuntimeTerminalStatusChanged,
    RuntimeTerminalSummary,
    RuntimeTerminalTicketClaims,
    RuntimeTerminalTicketResult,
    RuntimeTerminalTicketStatus,
)
from azents.services.runtime_terminal.ticket import (
    RuntimeTerminalTicketCodec,
    RuntimeTerminalTicketInvalid,
)

_TERMINAL_TICKET_LIFETIME = timedelta(seconds=30)
_TERMINAL_IDLE_LIFETIME = timedelta(minutes=30)
_TERMINAL_MAXIMUM_LIFETIME = timedelta(hours=8)
_TERMINAL_STREAM_GRACE = timedelta(minutes=2)
_TERMINAL_ATTACHMENT_LEASE_SECONDS = 45
_TERMINAL_BROWSER_GRACE_SECONDS = 120
_TERMINAL_METADATA_TTL_SECONDS = 9 * 60 * 60
_TERMINAL_EVENT_WAIT_SECONDS = 5.0
_IDENTITY_DENIAL_REASONS = {
    RuntimeTerminalReasonCode.ACCESS_DENIED,
    RuntimeTerminalReasonCode.AGENT_NOT_FOUND,
    RuntimeTerminalReasonCode.SESSION_NOT_FOUND,
    RuntimeTerminalReasonCode.SESSION_AGENT_MISMATCH,
}


class RuntimeTerminalAuthorityResolver(Protocol):
    """Resolve current access, policy, Runtime, Runner, and working-folder authority."""

    async def resolve(
        self,
        *,
        user_id: str,
        authentication_session_id: str,
        resource: RuntimeTerminalResource,
        resolved_at: datetime,
    ) -> RuntimeTerminalAuthority:
        """Return one fail-closed current authority projection."""
        ...


class RuntimeTerminalControlDispatcher(Protocol):
    """Dispatch metadata-only Runner Terminal intents through Runtime Control."""

    async def open_terminal(
        self,
        record: RuntimeTerminalRecord,
        *,
        columns: int,
        rows: int,
        requested_at: datetime,
    ) -> None:
        """Dispatch one idempotent open intent for an opening Terminal."""
        ...

    async def terminate_terminal(
        self,
        record: RuntimeTerminalRecord,
        *,
        reason: RunnerTerminalTerminationReason,
        requested_at: datetime,
    ) -> None:
        """Dispatch one best-effort terminate intent."""
        ...


class RuntimeTerminalAdmissionError(RuntimeError):
    """Bounded Public Terminal admission failure."""

    def __init__(self, reason_code: RuntimeTerminalReasonCode) -> None:
        super().__init__(reason_code.value)
        self.reason_code = reason_code


class RuntimeTerminalService:
    """Orchestrate Public Terminal authority without starting Runtimes."""

    def __init__(
        self,
        *,
        authority_resolver: RuntimeTerminalAuthorityResolver,
        coordination: RuntimeTerminalCoordinationStore,
        dispatcher: RuntimeTerminalControlDispatcher,
        ticket_codec: RuntimeTerminalTicketCodec,
        clock: Callable[[], datetime],
        ticket_id_factory: Callable[[], str],
        terminal_id_factory: Callable[[], str],
        stream_nonce_factory: Callable[[], str],
    ) -> None:
        """Initialize injected durable and volatile authority boundaries."""
        self.authority_resolver = authority_resolver
        self.coordination = coordination
        self.dispatcher = dispatcher
        self.ticket_codec = ticket_codec
        self.clock = clock
        self.ticket_id_factory = ticket_id_factory
        self.terminal_id_factory = terminal_id_factory
        self.stream_nonce_factory = stream_nonce_factory

    async def projection(
        self,
        *,
        user_id: str,
        authentication_session_id: str,
        resource: RuntimeTerminalResource,
    ) -> RuntimeTerminalProjection:
        """Return current Session Terminal availability without side effects."""
        now = self._now()
        authority = await self.authority_resolver.resolve(
            user_id=user_id,
            authentication_session_id=authentication_session_id,
            resource=resource,
            resolved_at=now,
        )
        terminal = None
        if authority.reason_code not in _IDENTITY_DENIAL_REASONS:
            terminal = await self.coordination.get_session_terminal(
                resource.session_id,
                current_time=now,
            )
        state = authority.projection_state
        reason = authority.reason_code
        summary = None if terminal is None else _summary(terminal)
        if terminal is not None and authority.can_open_or_attach:
            if terminal.lifecycle is CoordinationLifecycle.EXITED:
                state = RuntimeTerminalProjectionState.ENDED
                reason = RuntimeTerminalReasonCode.TERMINAL_ENDED
            else:
                state = RuntimeTerminalProjectionState.ACTIVE
                reason = None
        return RuntimeTerminalProjection(
            state=state,
            reason_code=reason,
            denied_scope=authority.denied_scope,
            can_start_runtime=authority.can_start_runtime,
            can_open_or_attach=(
                authority.can_open_or_attach
                and state
                in {
                    RuntimeTerminalProjectionState.READY,
                    RuntimeTerminalProjectionState.ACTIVE,
                    RuntimeTerminalProjectionState.ENDED,
                }
            ),
            terminal=summary,
        )

    async def issue_ticket(
        self,
        *,
        user_id: str,
        authentication_session_id: str,
        resource: RuntimeTerminalResource,
    ) -> RuntimeTerminalTicketResult:
        """Issue one 30-second open-or-attach ticket without Runtime auto-start."""
        now = self._now()
        authority = await self.authority_resolver.resolve(
            user_id=user_id,
            authentication_session_id=authentication_session_id,
            resource=resource,
            resolved_at=now,
        )
        if authority.projection_state is RuntimeTerminalProjectionState.STOPPED:
            return RuntimeTerminalTicketResult(
                status=RuntimeTerminalTicketStatus.RUNTIME_STOPPED,
                reason_code=RuntimeTerminalReasonCode.RUNTIME_STOPPED,
                denied_scope=authority.denied_scope,
                ticket=None,
                expires_at=None,
            )
        if not authority.can_open_or_attach:
            return RuntimeTerminalTicketResult(
                status=(
                    RuntimeTerminalTicketStatus.DENIED
                    if authority.denied_scope is not None
                    else RuntimeTerminalTicketStatus.UNAVAILABLE
                ),
                reason_code=authority.reason_code,
                denied_scope=authority.denied_scope,
                ticket=None,
                expires_at=None,
            )
        expires_at = now + _TERMINAL_TICKET_LIFETIME
        claims = RuntimeTerminalTicketClaims(
            ticket_id=self.ticket_id_factory(),
            user_id=user_id,
            authentication_session_id=authentication_session_id,
            workspace_id=authority.workspace_id,
            resource=resource,
            intent=RuntimeTerminalTicketIntent.OPEN_OR_ATTACH.value,
            issued_at=now,
            expires_at=expires_at,
        )
        await self.coordination.issue_ticket(
            RuntimeTerminalTicket(
                ticket_id=claims.ticket_id,
                binding=_ticket_binding(claims),
                issued_at=now,
                expires_at=expires_at,
            ),
            ttl_seconds=int(_TERMINAL_TICKET_LIFETIME.total_seconds()),
        )
        return RuntimeTerminalTicketResult(
            status=RuntimeTerminalTicketStatus.ISSUED,
            reason_code=None,
            denied_scope=None,
            ticket=self.ticket_codec.encode(claims),
            expires_at=expires_at,
        )

    async def consume_ticket(
        self,
        *,
        ticket: str,
        resource: RuntimeTerminalResource,
    ) -> RuntimeTerminalSocketAdmission:
        """Consume one exact resource-bound ticket and revalidate authority."""
        now = self._now()
        try:
            claims = self.ticket_codec.decode(ticket, now=now)
        except RuntimeTerminalTicketInvalid as error:
            raise RuntimeTerminalAdmissionError(
                RuntimeTerminalReasonCode.ACCESS_DENIED
            ) from error
        if claims.resource != resource:
            raise RuntimeTerminalAdmissionError(RuntimeTerminalReasonCode.ACCESS_DENIED)
        consumed = await self.coordination.consume_ticket(
            claims.ticket_id,
            expected_binding=_ticket_binding(claims),
            consumed_at=now,
        )
        if consumed.status is not RuntimeTerminalMutationStatus.APPLIED:
            raise RuntimeTerminalAdmissionError(RuntimeTerminalReasonCode.ACCESS_DENIED)
        authority = await self.authority_resolver.resolve(
            user_id=claims.user_id,
            authentication_session_id=claims.authentication_session_id,
            resource=resource,
            resolved_at=now,
        )
        if authority.workspace_id != claims.workspace_id:
            raise RuntimeTerminalAdmissionError(RuntimeTerminalReasonCode.ACCESS_DENIED)
        if not authority.can_open_or_attach:
            raise RuntimeTerminalAdmissionError(
                authority.reason_code or RuntimeTerminalReasonCode.RUNTIME_UNAVAILABLE
            )
        return RuntimeTerminalSocketAdmission(claims=claims, authority=authority)

    async def attach(
        self,
        admission: RuntimeTerminalSocketAdmission,
        request: RuntimeTerminalAttachRequest,
    ) -> RuntimeTerminalAttachment:
        """Create or attach the Session singleton through volatile coordination."""
        now = self._now()
        admitted = await self.coordination.admit_or_get(
            _coordination_admission(
                admission.authority,
                terminal_id=self.terminal_id_factory(),
                stream_nonce=self.stream_nonce_factory(),
                created_at=now,
            ),
            admitted_at=now,
        )
        if admitted.status is not RuntimeTerminalMutationStatus.APPLIED:
            raise RuntimeTerminalAdmissionError(_mutation_reason(admitted.status))
        record = admitted.value
        if record is None:
            raise RuntimeError("Terminal admission returned no record")
        stale_reason = _stale_admission_reason(
            record.admission,
            admission.authority,
        )
        if stale_reason is not None:
            terminated = await self.coordination.request_termination(
                record.admission.terminal_id,
                reason=stale_reason,
                requested_at=now,
            )
            if terminated.value is not None:
                await self.dispatcher.terminate_terminal(
                    terminated.value,
                    reason=stale_reason,
                    requested_at=now,
                )
            raise RuntimeTerminalAdmissionError(
                RuntimeTerminalReasonCode.TERMINAL_REVOKED
            )
        attached = await self.coordination.attach_browser(
            record.admission.terminal_id,
            user_id=admission.claims.user_id,
            attached_at=now,
            lease_seconds=_TERMINAL_ATTACHMENT_LEASE_SECONDS,
        )
        if attached.status is not RuntimeTerminalMutationStatus.APPLIED:
            raise RuntimeTerminalAdmissionError(_mutation_reason(attached.status))
        attachment = attached.value
        if attachment is None:
            raise RuntimeError("Terminal attachment returned no generation")
        requested_after = request.last_output_sequence or 0
        replay_result = await self.coordination.replay_output(
            record.admission.terminal_id,
            attachment_generation=attachment.generation,
            after_sequence=requested_after,
            maximum_bytes=MAX_REPLAY_BYTES,
            current_time=now,
        )
        if replay_result.status is not RuntimeTerminalMutationStatus.APPLIED:
            raise RuntimeTerminalAdmissionError(_mutation_reason(replay_result.status))
        replay = replay_result.value
        if replay is None:
            raise RuntimeError("Terminal replay returned no snapshot")
        current = await self.coordination.get_terminal(
            record.admission.terminal_id,
            current_time=now,
        )
        if (
            current is None
            or current.attachment is None
            or current.attachment.generation != attachment.generation
        ):
            raise RuntimeTerminalAdmissionError(
                RuntimeTerminalReasonCode.COORDINATION_UNAVAILABLE
            )
        if (
            record.lifecycle is CoordinationLifecycle.OPENING
            and record.runner_stream is None
        ):
            await self.dispatcher.open_terminal(
                record,
                columns=request.columns,
                rows=request.rows,
                requested_at=now,
            )
        return CoordinatedRuntimeTerminalAttachment(
            store=self.coordination,
            dispatcher=self.dispatcher,
            record=record,
            attachment_generation=attachment.generation,
            accepted=RuntimeTerminalAttachmentAccepted(
                terminal_id=record.admission.terminal_id,
                lifecycle=_lifecycle(record.lifecycle),
                attachment_generation=attachment.generation,
                desired_generation=record.admission.desired_generation,
                runner_generation=record.admission.runner_generation,
                shell_label=admission.authority.shell_label,
                working_directory_display=(
                    admission.authority.working_directory_display
                    or record.admission.working_directory
                ),
                next_input_sequence=current.highest_input_sequence + 1,
                replay_min_sequence=replay.minimum_sequence,
                replay_max_sequence=replay.maximum_sequence,
                replay_truncated=replay.truncated,
            ),
            replay=tuple(_output(item) for item in replay.outputs),
            revision=current.revision,
            highest_input_acknowledged_sequence=(
                current.highest_input_acknowledged_sequence
            ),
            output_sequence=replay.maximum_sequence,
            clock=self.clock,
        )

    async def revalidate(
        self,
        admission: RuntimeTerminalSocketAdmission,
    ) -> RuntimeTerminalReasonCode | None:
        """Return a bounded revocation reason when exact authority changed."""
        current = await self.authority_resolver.resolve(
            user_id=admission.claims.user_id,
            authentication_session_id=admission.claims.authentication_session_id,
            resource=admission.claims.resource,
            resolved_at=self._now(),
        )
        expected = admission.authority
        if not current.can_open_or_attach:
            return current.reason_code or RuntimeTerminalReasonCode.TERMINAL_REVOKED
        if (
            current.authentication_session_expires_at
            != expected.authentication_session_expires_at
            or current.workspace_id != expected.workspace_id
            or current.runtime_id != expected.runtime_id
            or current.desired_generation != expected.desired_generation
            or current.runner_generation != expected.runner_generation
            or current.workspace_profile_id != expected.workspace_profile_id
            or current.workspace_profile_version != expected.workspace_profile_version
            or current.provider_profile_id != expected.provider_profile_id
            or current.provider_profile_version != expected.provider_profile_version
            or current.agent_policy_version != expected.agent_policy_version
            or current.working_directory != expected.working_directory
        ):
            return RuntimeTerminalReasonCode.TERMINAL_REVOKED
        return None

    def _now(self) -> datetime:
        now = self.clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("Runtime Terminal service clock must be timezone-aware")
        return now.astimezone(UTC)


class CoordinatedRuntimeTerminalAttachment:
    """Browser attachment adapter over exact coordination generations."""

    def __init__(
        self,
        *,
        store: RuntimeTerminalCoordinationStore,
        dispatcher: RuntimeTerminalControlDispatcher,
        record: RuntimeTerminalRecord,
        attachment_generation: int,
        accepted: RuntimeTerminalAttachmentAccepted,
        replay: tuple[RuntimeTerminalOutput, ...],
        revision: int,
        highest_input_acknowledged_sequence: int,
        output_sequence: int,
        clock: Callable[[], datetime],
    ) -> None:
        self.store = store
        self.dispatcher = dispatcher
        self.record = record
        self.attachment_generation = attachment_generation
        self._accepted = accepted
        self._replay = replay
        self.revision = revision
        self.highest_input_acknowledged_sequence = highest_input_acknowledged_sequence
        self.output_sequence = output_sequence
        self.highest_resize_sequence = 0
        self.highest_heartbeat_sequence = 0
        self.clock = clock
        self.closed = False

    @property
    def accepted(self) -> RuntimeTerminalAttachmentAccepted:
        """Return current attachment and replay evidence."""
        return self._accepted

    def replay(self) -> tuple[RuntimeTerminalOutput, ...]:
        """Return the immutable retained replay snapshot."""
        return self._replay

    async def input(self, *, sequence: int, data: bytes) -> None:
        result = await self.store.enqueue_input(
            self.record.admission.terminal_id,
            attachment_generation=self.attachment_generation,
            sequence=sequence,
            data=data,
            accepted_at=self._now(),
        )
        _require_applied(result.status)

    async def resize(self, *, sequence: int, columns: int, rows: int) -> None:
        if sequence <= self.highest_resize_sequence:
            raise RuntimeTerminalAdmissionError(
                RuntimeTerminalReasonCode.COORDINATION_UNAVAILABLE
            )
        result = await self.store.update_resize(
            self.record.admission.terminal_id,
            attachment_generation=self.attachment_generation,
            columns=columns,
            rows=rows,
            updated_at=self._now(),
        )
        _require_applied(result.status)
        self.highest_resize_sequence = sequence

    async def acknowledge_output(self, *, sequence: int) -> None:
        if sequence > self.output_sequence:
            raise RuntimeTerminalAdmissionError(
                RuntimeTerminalReasonCode.COORDINATION_UNAVAILABLE
            )
        result = await self.store.acknowledge_output(
            self.record.admission.terminal_id,
            attachment_generation=self.attachment_generation,
            sequence=sequence,
            acknowledged_at=self._now(),
        )
        _require_applied(result.status)

    async def heartbeat(self, *, sequence: int) -> None:
        if sequence <= self.highest_heartbeat_sequence:
            raise RuntimeTerminalAdmissionError(
                RuntimeTerminalReasonCode.COORDINATION_UNAVAILABLE
            )
        result = await self.store.heartbeat_browser(
            self.record.admission.terminal_id,
            attachment_generation=self.attachment_generation,
            heartbeat_at=self._now(),
            lease_seconds=_TERMINAL_ATTACHMENT_LEASE_SECONDS,
        )
        _require_applied(result.status)
        self.highest_heartbeat_sequence = sequence

    async def terminate(self) -> None:
        now = self._now()
        await self._request_termination(
            reason=RunnerTerminalTerminationReason.CALLER,
            requested_at=now,
        )

    async def revoke(self, reason_code: RuntimeTerminalReasonCode) -> None:
        """Terminate the PTY after active authority is revoked."""
        await self._request_termination(
            reason=_revocation_termination_reason(reason_code),
            requested_at=self._now(),
        )

    async def events(self) -> AsyncIterator[RuntimeTerminalServerEvent]:
        terminal_id = self.record.admission.terminal_id
        while not self.closed:
            record = await self.store.wait_for_change(
                terminal_id,
                after_revision=self.revision,
                timeout_seconds=_TERMINAL_EVENT_WAIT_SECONDS,
            )
            if record is None:
                continue
            if record.revision <= self.revision:
                continue
            self.revision = record.revision
            if (
                record.highest_input_acknowledged_sequence
                > self.highest_input_acknowledged_sequence
            ):
                self.highest_input_acknowledged_sequence = (
                    record.highest_input_acknowledged_sequence
                )
                yield RuntimeTerminalInputAcknowledged(
                    sequence=self.highest_input_acknowledged_sequence
                )
            outputs = await self.store.read_output(
                terminal_id,
                attachment_generation=self.attachment_generation,
                after_sequence=self.output_sequence,
                maximum_bytes=MAX_REPLAY_BYTES,
                current_time=self._now(),
            )
            if outputs.status is RuntimeTerminalMutationStatus.APPLIED:
                batch = outputs.value
                if batch is not None:
                    for item in batch.outputs:
                        self.output_sequence = item.sequence
                        yield _output(item)
            revocation_reason = _revocation_reason_code(record.termination_reason)
            if revocation_reason is not None:
                yield RuntimeTerminalRevoked(reason_code=revocation_reason)
                return
            if record.lifecycle is CoordinationLifecycle.EXITED:
                yield RuntimeTerminalExited(
                    reason=(
                        record.termination_reason.value
                        if record.termination_reason is not None
                        else RunnerTerminalTerminationReason.PROCESS_EXIT.value
                    ),
                    exit_code=record.exit_code,
                )
                return
            if record.lifecycle is CoordinationLifecycle.TERMINATING:
                yield RuntimeTerminalStatusChanged(
                    lifecycle=RuntimeTerminalLifecycle.TERMINATING,
                    reason=(
                        record.termination_reason.value
                        if record.termination_reason is not None
                        else None
                    ),
                )

    async def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        result = await self.store.detach_browser(
            self.record.admission.terminal_id,
            attachment_generation=self.attachment_generation,
            detached_at=self._now(),
            grace_seconds=_TERMINAL_BROWSER_GRACE_SECONDS,
        )
        if result.status not in {
            RuntimeTerminalMutationStatus.APPLIED,
            RuntimeTerminalMutationStatus.TERMINAL_FINAL,
            RuntimeTerminalMutationStatus.NOT_FOUND,
            RuntimeTerminalMutationStatus.STALE_ATTACHMENT_GENERATION,
            RuntimeTerminalMutationStatus.STALE_LIFECYCLE,
        }:
            _require_applied(result.status)

    async def _request_termination(
        self,
        *,
        reason: RunnerTerminalTerminationReason,
        requested_at: datetime,
    ) -> None:
        result = await self.store.request_termination(
            self.record.admission.terminal_id,
            reason=reason,
            requested_at=requested_at,
        )
        _require_applied(result.status)
        record = result.value
        if record is not None:
            await self.dispatcher.terminate_terminal(
                record,
                reason=reason,
                requested_at=requested_at,
            )

    def _now(self) -> datetime:
        now = self.clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("Runtime Terminal attachment clock must be timezone-aware")
        return now.astimezone(UTC)


def _ticket_binding(
    claims: RuntimeTerminalTicketClaims,
) -> RuntimeTerminalTicketBinding:
    return RuntimeTerminalTicketBinding(
        user_id=claims.user_id,
        authentication_session_id=claims.authentication_session_id,
        workspace_id=claims.workspace_id,
        agent_id=claims.resource.agent_id,
        session_id=claims.resource.session_id,
        intent=RuntimeTerminalTicketIntent.OPEN_OR_ATTACH,
    )


def _coordination_admission(
    authority: RuntimeTerminalAuthority,
    *,
    terminal_id: str,
    stream_nonce: str,
    created_at: datetime,
) -> CoordinationAdmission:
    if (
        authority.runtime_id is None
        or authority.provider_profile_id is None
        or authority.provider_profile_version is None
        or authority.workspace_profile_id is None
        or authority.workspace_profile_version is None
        or authority.agent_policy_version is None
        or authority.authentication_session_expires_at is None
        or authority.desired_generation is None
        or authority.runner_generation is None
        or authority.working_directory is None
    ):
        raise RuntimeTerminalAdmissionError(
            RuntimeTerminalReasonCode.RUNTIME_UNAVAILABLE
        )
    return CoordinationAdmission(
        terminal_id=terminal_id,
        workspace_id=authority.workspace_id,
        agent_id=authority.resource.agent_id,
        session_id=authority.resource.session_id,
        user_id=authority.user_id,
        authentication_session_id=authority.authentication_session_id,
        authentication_session_expires_at=(authority.authentication_session_expires_at),
        runtime_id=authority.runtime_id,
        provider_profile_id=authority.provider_profile_id,
        provider_profile_version=authority.provider_profile_version,
        workspace_profile_id=authority.workspace_profile_id,
        workspace_profile_version=authority.workspace_profile_version,
        agent_policy_version=authority.agent_policy_version,
        desired_generation=authority.desired_generation,
        runner_generation=authority.runner_generation,
        working_directory=authority.working_directory,
        stream_nonce=stream_nonce,
        created_at=created_at,
        idle_deadline_at=created_at + _TERMINAL_IDLE_LIFETIME,
        maximum_deadline_at=created_at + _TERMINAL_MAXIMUM_LIFETIME,
        data_stream_grace_deadline_at=created_at + _TERMINAL_STREAM_GRACE,
        metadata_ttl_seconds=_TERMINAL_METADATA_TTL_SECONDS,
    )


def _summary(record: RuntimeTerminalRecord) -> RuntimeTerminalSummary:
    return RuntimeTerminalSummary(
        terminal_id=record.admission.terminal_id,
        lifecycle=_lifecycle(record.lifecycle),
        attached=record.attachment is not None,
        started_at=record.admission.created_at,
        ended_at=record.finalized_at,
        final_reason=(
            record.termination_reason.value
            if record.termination_reason is not None
            else None
        ),
        input_bytes=record.input_bytes,
        output_bytes=record.output_bytes,
        replay_truncated=record.replay_truncated,
    )


def _stale_admission_reason(
    current: CoordinationAdmission,
    authority: RuntimeTerminalAuthority,
) -> RunnerTerminalTerminationReason | None:
    if (
        current.workspace_id != authority.workspace_id
        or current.agent_id != authority.resource.agent_id
        or current.session_id != authority.resource.session_id
        or current.user_id != authority.user_id
        or current.authentication_session_id != authority.authentication_session_id
        or current.authentication_session_expires_at
        != authority.authentication_session_expires_at
    ):
        return RunnerTerminalTerminationReason.ACCESS_REVOKED
    if (
        current.provider_profile_id != authority.provider_profile_id
        or current.provider_profile_version != authority.provider_profile_version
        or current.workspace_profile_id != authority.workspace_profile_id
        or current.workspace_profile_version != authority.workspace_profile_version
        or current.agent_policy_version != authority.agent_policy_version
    ):
        return RunnerTerminalTerminationReason.POLICY_REVOKED
    if (
        current.runtime_id != authority.runtime_id
        or current.desired_generation != authority.desired_generation
        or current.runner_generation != authority.runner_generation
        or current.working_directory != authority.working_directory
    ):
        return RunnerTerminalTerminationReason.RUNTIME_INVALIDATED
    return None


def _lifecycle(value: CoordinationLifecycle) -> RuntimeTerminalLifecycle:
    return RuntimeTerminalLifecycle(value.value)


def _output(value: CoordinationOutput) -> RuntimeTerminalOutput:
    return RuntimeTerminalOutput(sequence=value.sequence, data=value.data)


def _mutation_reason(
    status: RuntimeTerminalMutationStatus,
) -> RuntimeTerminalReasonCode:
    return {
        RuntimeTerminalMutationStatus.QUOTA_EXCEEDED: (
            RuntimeTerminalReasonCode.RUNTIME_LIMIT
        ),
        RuntimeTerminalMutationStatus.CAPACITY_EXCEEDED: (
            RuntimeTerminalReasonCode.COORDINATION_UNAVAILABLE
        ),
        RuntimeTerminalMutationStatus.STALE_RUNTIME_AUTHORITY: (
            RuntimeTerminalReasonCode.TERMINAL_REVOKED
        ),
        RuntimeTerminalMutationStatus.TERMINAL_FINAL: (
            RuntimeTerminalReasonCode.TERMINAL_ENDED
        ),
    }.get(status, RuntimeTerminalReasonCode.COORDINATION_UNAVAILABLE)


def _revocation_termination_reason(
    reason_code: RuntimeTerminalReasonCode,
) -> RunnerTerminalTerminationReason:
    if reason_code in {
        RuntimeTerminalReasonCode.ACCESS_DENIED,
        RuntimeTerminalReasonCode.AGENT_NOT_FOUND,
        RuntimeTerminalReasonCode.SESSION_NOT_FOUND,
        RuntimeTerminalReasonCode.SESSION_AGENT_MISMATCH,
    }:
        return RunnerTerminalTerminationReason.ACCESS_REVOKED
    if reason_code in {
        RuntimeTerminalReasonCode.TERMINAL_DISABLED,
        RuntimeTerminalReasonCode.PROFILE_UNAVAILABLE,
    }:
        return RunnerTerminalTerminationReason.POLICY_REVOKED
    return RunnerTerminalTerminationReason.RUNTIME_INVALIDATED


def _revocation_reason_code(
    reason: RunnerTerminalTerminationReason | None,
) -> RuntimeTerminalReasonCode | None:
    if reason is RunnerTerminalTerminationReason.ACCESS_REVOKED:
        return RuntimeTerminalReasonCode.ACCESS_DENIED
    if reason is RunnerTerminalTerminationReason.POLICY_REVOKED:
        return RuntimeTerminalReasonCode.TERMINAL_DISABLED
    return None


def _require_applied(status: RuntimeTerminalMutationStatus) -> None:
    if status is not RuntimeTerminalMutationStatus.APPLIED:
        raise RuntimeTerminalAdmissionError(_mutation_reason(status))
