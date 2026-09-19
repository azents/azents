"""Agent Workspace upload service tests."""

from __future__ import annotations

import dataclasses
import datetime
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import NamedTuple

import pytest
from azcommon.result import Failure, Result, Success
from azents_runtime_control.grpc_workspace_upload_client import (
    WorkspaceUploadCancelRequest,
    WorkspaceUploadCreateRequest,
    WorkspaceUploadIdentity,
    WorkspaceUploadPhase,
    WorkspaceUploadRetryRequest,
    WorkspaceUploadStatus,
    WorkspaceUploadTicket,
    WorkspaceUploadTicketResult,
)

from azents.core.enums import (
    AgentLifecycleStatus,
    AgentType,
    WorkspaceUserRole,
)
from azents.repos.agent.data import Agent
from azents.repos.workspace_upload_authority.data import (
    WorkspaceUploadRequesterAccessDenied,
    WorkspaceUploadRequesterAgentUnavailable,
    WorkspaceUploadRequesterAuthority,
)
from azents.repos.workspace_upload_authority.operations import (
    WorkspaceUploadAuthorizationRepository,
)
from azents.repos.workspace_user.data import WorkspaceUser
from azents.runtime.control_protocol.runner_operations import (
    RuntimeFileStatResult,
    RuntimeRunnerOperationFailedError,
)
from azents.services.agent_runtime.lifecycle_data import (
    AgentRuntimeLifecycleSnapshot,
    RuntimeOperationAuthority,
    RuntimeOperationTarget,
    RuntimeOperationTargetResolver,
)
from azents.services.chat.workspace_upload import (
    WorkspaceUploadAccessDenied,
    WorkspaceUploadDestinationInvalid,
    WorkspaceUploadInvalidRequest,
    WorkspaceUploadNotFound,
    WorkspaceUploadRevisionConflict,
    WorkspaceUploadRuntimeUnavailable,
    WorkspaceUploadService,
)
from azents.services.runtime_storage_error import RuntimeStorageError

_AGENT_ID = "0123456789abcdef0123456789abcdef"
_WORKSPACE_ID = "workspace-1"
_USER_ID = "user-1"
_OTHER_USER_ID = "user-2"
_RUNTIME_ID = "runtime-1"
_UPLOAD_ID = "abcdefabcdefabcdefabcdefabcdefab"
_NOW = datetime.datetime(2026, 9, 17, tzinfo=datetime.UTC)
_DIGEST = "a" * 64
_ROOT = PurePosixPath("/runtime/home")


class _AuthorizationRepository(WorkspaceUploadAuthorizationRepository):
    """Return one configurable upload authorization result."""

    def __init__(
        self,
        *,
        agent: Agent | None,
        membership: WorkspaceUser | None,
        admin: bool,
    ) -> None:
        self.agent = agent
        self.membership = membership
        self.admin = admin

    async def authorize(
        self,
        *,
        agent_id: str,
        user_id: str,
    ) -> Result[
        WorkspaceUploadRequesterAuthority,
        WorkspaceUploadRequesterAgentUnavailable | WorkspaceUploadRequesterAccessDenied,
    ]:
        """Return the authorization result represented by the fixture."""
        agent = self.agent
        if (
            agent is None
            or agent.id != agent_id
            or agent.lifecycle_status is not AgentLifecycleStatus.ACTIVE
        ):
            return Failure(WorkspaceUploadRequesterAgentUnavailable())
        membership = self.membership
        if (
            membership is None
            or membership.workspace_id != agent.workspace_id
            or membership.user_id != user_id
        ):
            return Failure(WorkspaceUploadRequesterAccessDenied())
        if (
            agent.type is AgentType.PRIVATE
            and membership.role is not WorkspaceUserRole.OWNER
            and not self.admin
        ):
            return Failure(WorkspaceUploadRequesterAccessDenied())
        return Success(
            WorkspaceUploadRequesterAuthority(
                agent=agent,
                workspace_user_id=membership.id,
                role=membership.role,
            )
        )


class _RuntimeResolver(RuntimeOperationTargetResolver):
    """Return deterministic Runtime target and lifecycle evidence."""

    def __init__(
        self,
        *,
        target: RuntimeOperationTarget | None,
        snapshot_runtime_id: str | None = _RUNTIME_ID,
        snapshot_error: RuntimeStorageError | None = None,
    ) -> None:
        self.target = target
        self.snapshot_runtime_id = snapshot_runtime_id
        self.snapshot_error = snapshot_error
        self.resolve_calls: list[tuple[float, bool]] = []

    async def resolve_operation_target(
        self,
        agent_id: str,
        *,
        wait_timeout_seconds: float = 120.0,
        poll_interval_seconds: float = 1.0,
        expected_authority: RuntimeOperationAuthority | None = None,
        start_if_stopped: bool = True,
    ) -> RuntimeOperationTarget:
        """Return the configured target or its Runtime error."""
        del agent_id, poll_interval_seconds, expected_authority
        self.resolve_calls.append((wait_timeout_seconds, start_if_stopped))
        if self.target is None:
            raise RuntimeStorageError("Runtime runner is not ready.")
        return self.target

    async def get_lifecycle_snapshot(
        self,
        agent_id: str,
    ) -> AgentRuntimeLifecycleSnapshot:
        """Return the current lookup Runtime evidence."""
        del agent_id
        if self.snapshot_error is not None:
            raise self.snapshot_error
        runtime = None
        if self.snapshot_runtime_id is not None:
            runtime = type(
                "_Runtime",
                (),
                {
                    "id": self.snapshot_runtime_id,
                    "desired_generation": 1,
                },
            )()
        return AgentRuntimeLifecycleSnapshot.model_construct(
            runtime=runtime,
            lifecycle=None,
            actions=None,
        )


class _RunnerOperations:
    """Return one deterministic directory stat result."""

    def __init__(
        self,
        *,
        result: RuntimeFileStatResult | None = None,
        error: RuntimeError | None = None,
    ) -> None:
        self.result = result or RuntimeFileStatResult(
            path=_ROOT.as_posix(),
            kind="directory",
            size_bytes=None,
            symlink=False,
            real_path=None,
            resolved_kind=None,
            modified_at=None,
            final_cursor="0-1",
        )
        self.error = error
        self.calls: list[dict[str, object]] = []

    async def stat_file(
        self,
        *,
        runtime_id: str,
        runner_generation: int,
        owner_session_id: str | None,
        path: str,
        deadline_at: datetime.datetime,
    ) -> RuntimeFileStatResult:
        """Record exact Runner stat authority and return the fixture."""
        self.calls.append(
            {
                "runtime_id": runtime_id,
                "runner_generation": runner_generation,
                "owner_session_id": owner_session_id,
                "path": path,
                "deadline_at": deadline_at,
            }
        )
        if self.error is not None:
            raise self.error
        return self.result


@dataclass
class _Coordinator:
    """Record typed Runtime Control calls."""

    status: WorkspaceUploadStatus
    echo_create_identity: bool = True
    ticket_status: WorkspaceUploadStatus | None = None
    ticket: WorkspaceUploadTicket = field(
        default_factory=lambda: WorkspaceUploadTicket(
            method="PUT",
            url="https://objects.example/upload?signature=secret",
            expires_at=_NOW + datetime.timedelta(minutes=10),
            headers=(("content-type", "text/plain"),),
        )
    )
    get_status: WorkspaceUploadStatus | None = None
    finalize_status: WorkspaceUploadStatus | None = None
    cancel_status: WorkspaceUploadStatus | None = None
    retry_status: WorkspaceUploadStatus | None = None
    create_requests: list[WorkspaceUploadCreateRequest] = field(default_factory=list)
    issue_calls: list[tuple[WorkspaceUploadIdentity, int]] = field(default_factory=list)
    get_calls: list[WorkspaceUploadIdentity] = field(default_factory=list)
    finalize_calls: list[tuple[WorkspaceUploadIdentity, int]] = field(
        default_factory=list
    )
    cancel_calls: list[WorkspaceUploadCancelRequest] = field(default_factory=list)
    retry_calls: list[WorkspaceUploadRetryRequest] = field(default_factory=list)

    async def create(
        self,
        request: WorkspaceUploadCreateRequest,
    ) -> WorkspaceUploadStatus:
        """Record create metadata and return the admission status."""
        self.create_requests.append(request)
        if self.echo_create_identity:
            self.status = dataclasses.replace(self.status, identity=request.identity)
        return self.status

    async def issue_ticket(
        self,
        *,
        identity: WorkspaceUploadIdentity,
        expected_revision: int,
    ) -> WorkspaceUploadTicketResult:
        """Record ticket issuance and return status plus transient ticket."""
        self.issue_calls.append((identity, expected_revision))
        return WorkspaceUploadTicketResult(
            status=self.ticket_status or self.status,
            ticket=self.ticket,
        )

    async def get(self, identity: WorkspaceUploadIdentity) -> WorkspaceUploadStatus:
        """Record status lookup and return its configured result."""
        self.get_calls.append(identity)
        return self.get_status or self.status

    async def finalize(
        self,
        *,
        identity: WorkspaceUploadIdentity,
        expected_revision: int,
    ) -> WorkspaceUploadStatus:
        """Record finalization preconditions."""
        self.finalize_calls.append((identity, expected_revision))
        return self.finalize_status or self.status

    async def cancel(
        self,
        request: WorkspaceUploadCancelRequest,
    ) -> WorkspaceUploadStatus:
        """Record cancellation preconditions."""
        self.cancel_calls.append(request)
        return self.cancel_status or self.status

    async def retry(
        self,
        request: WorkspaceUploadRetryRequest,
    ) -> WorkspaceUploadStatus:
        """Record retry preconditions."""
        self.retry_calls.append(request)
        return self.retry_status or self.status


def _agent(*, agent_type: AgentType = AgentType.PUBLIC) -> Agent:
    """Build the minimum active Agent authorization projection."""
    return Agent.model_construct(
        id=_AGENT_ID,
        workspace_id=_WORKSPACE_ID,
        lifecycle_status=AgentLifecycleStatus.ACTIVE,
        type=agent_type,
    )


def _membership(
    *,
    user_id: str = _USER_ID,
    role: WorkspaceUserRole = WorkspaceUserRole.MEMBER,
) -> WorkspaceUser:
    """Build one Workspace membership projection."""
    return WorkspaceUser.model_construct(
        id="workspace-user-1",
        workspace_id=_WORKSPACE_ID,
        user_id=user_id,
        role=role,
    )


def _target(
    *,
    runtime_id: str = _RUNTIME_ID,
    desired_generation: int = 1,
    workspace_path: str | None = _ROOT.as_posix(),
) -> RuntimeOperationTarget:
    """Build one exact Runtime operation target."""
    return RuntimeOperationTarget(
        id=runtime_id,
        runtime_capability_version=1,
        desired_generation=desired_generation,
        runner_generation=7,
        configuration_sequence=2,
        configuration_digest=_DIGEST,
        workspace_path=workspace_path or "",
    )


def _status(
    *,
    identity: WorkspaceUploadIdentity | None = None,
    revision: int = 1,
    runtime_id: str = _RUNTIME_ID,
    desired_generation: int = 1,
) -> WorkspaceUploadStatus:
    """Build one public-safe Runtime Control status."""
    return WorkspaceUploadStatus(
        identity=identity
        or WorkspaceUploadIdentity(
            upload_id=_UPLOAD_ID,
            requester_user_id=_USER_ID,
            workspace_id=_WORKSPACE_ID,
            agent_id=_AGENT_ID,
            runtime_id=runtime_id,
            desired_generation=desired_generation,
        ),
        revision=revision,
        destination_directory=_ROOT.as_posix(),
        filename="report.txt",
        destination_path=(_ROOT / "report.txt").as_posix(),
        expected_size=12,
        received_size=0,
        actual_size=None,
        sha256=None,
        media_type="text/plain",
        phase=WorkspaceUploadPhase.UPLOADING,
        current_delivery_number=0,
        outcome=None,
        failure=None,
        retry_available=False,
        cancel_available=True,
        overwrite_available=False,
        destination_evidence=None,
    )


class _ServiceDependencies(NamedTuple):
    """Service and observable dependency doubles."""

    service: WorkspaceUploadService
    resolver: _RuntimeResolver
    runner: _RunnerOperations
    coordinator: _Coordinator


def _service(
    *,
    agent: Agent | None = None,
    membership: WorkspaceUser | None = None,
    admin: bool = False,
    target: RuntimeOperationTarget | None = None,
    snapshot_runtime_id: str | None = _RUNTIME_ID,
    snapshot_error: RuntimeStorageError | None = None,
    runner: _RunnerOperations | None = None,
    coordinator: _Coordinator | None = None,
) -> _ServiceDependencies:
    """Build the service and all observable dependency doubles."""
    resolved_runner = runner or _RunnerOperations()
    resolved_coordinator = coordinator or _Coordinator(status=_status())
    resolver = _RuntimeResolver(
        target=target or _target(),
        snapshot_runtime_id=snapshot_runtime_id,
        snapshot_error=snapshot_error,
    )
    return _ServiceDependencies(
        service=WorkspaceUploadService(
            authorization_repository=_AuthorizationRepository(
                agent=agent,
                membership=membership,
                admin=admin,
            ),
            runtime_target_resolver=resolver,
            runner_operations=resolved_runner,
            coordinator=resolved_coordinator,
        ),
        resolver=resolver,
        runner=resolved_runner,
        coordinator=resolved_coordinator,
    )


@pytest.mark.asyncio
async def test_create_uses_runner_authority_and_issues_direct_ticket() -> None:
    """Create binds the request to the current Runtime and Runner path."""
    service, resolver, runner, coordinator = _service(
        agent=_agent(),
        membership=_membership(),
    )

    result = await service.create(
        agent_id=_AGENT_ID,
        user_id=_USER_ID,
        destination_directory="reports",
        filename="report.txt",
        expected_size=12,
        expected_sha256=_DIGEST,
        media_type="text/plain",
        session_id=None,
    )

    assert isinstance(result, Success)
    assert result.value.ticket.url.endswith("signature=secret")
    request = coordinator.create_requests[0]
    assert request.destination_directory == (_ROOT / "reports").as_posix()
    assert request.destination_path == (_ROOT / "reports/report.txt").as_posix()
    assert request.identity.runtime_id == _RUNTIME_ID
    assert request.identity.desired_generation == 1
    assert coordinator.issue_calls == [(request.identity, 1)]
    assert resolver.resolve_calls == [(0.0, False)]
    assert runner.calls[0]["path"] == (_ROOT / "reports").as_posix()


@pytest.mark.asyncio
async def test_create_rejects_traversal_and_never_calls_coordinator() -> None:
    """Path and basename validation precede Runtime Control admission."""
    service, _, runner, coordinator = _service(
        agent=_agent(),
        membership=_membership(),
    )

    result = await service.create(
        agent_id=_AGENT_ID,
        user_id=_USER_ID,
        destination_directory="../outside",
        filename="report.txt",
        expected_size=12,
        expected_sha256=_DIGEST,
        media_type=None,
        session_id=None,
    )

    assert isinstance(result, Failure)
    assert isinstance(result.error, WorkspaceUploadDestinationInvalid)
    assert not coordinator.create_requests
    assert not runner.calls


@pytest.mark.asyncio
async def test_create_rejects_invalid_metadata_before_coordinator_availability() -> (
    None
):
    """Malformed metadata remains a client error when the coordinator is absent."""
    service, _, _, _ = _service(
        agent=_agent(),
        membership=_membership(),
    )
    service.coordinator = None

    result = await service.create(
        agent_id=_AGENT_ID,
        user_id=_USER_ID,
        destination_directory=".",
        filename="report.txt",
        expected_size=12,
        expected_sha256="not-a-digest",
        media_type=None,
        session_id=None,
    )

    assert isinstance(result, Failure)
    assert isinstance(result.error, WorkspaceUploadInvalidRequest)


@pytest.mark.asyncio
async def test_private_agent_requires_owner_or_explicit_agent_admin() -> None:
    """Private-Agent membership access is restricted to owner or Agent admin."""
    service, _, _, _ = _service(
        agent=_agent(agent_type=AgentType.PRIVATE),
        membership=_membership(role=WorkspaceUserRole.MEMBER),
        admin=False,
    )

    result = await service.get(
        agent_id=_AGENT_ID,
        user_id=_USER_ID,
        upload_id=_UPLOAD_ID,
    )

    assert isinstance(result, Failure)
    assert isinstance(result.error, WorkspaceUploadAccessDenied)

    service, _, _, _ = _service(
        agent=_agent(agent_type=AgentType.PRIVATE),
        membership=_membership(role=WorkspaceUserRole.MEMBER),
        admin=True,
    )
    result = await service.get(
        agent_id=_AGENT_ID,
        user_id=_USER_ID,
        upload_id=_UPLOAD_ID,
    )
    assert isinstance(result, Success)


@pytest.mark.asyncio
async def test_get_rejects_runtime_lookup_failure_without_exposing_status() -> None:
    """A failed current Runtime lookup fails closed as a bounded domain result."""
    service, _, _, _ = _service(
        agent=_agent(),
        membership=_membership(),
        snapshot_error=RuntimeStorageError("Runtime control is unavailable."),
    )

    result = await service.get(
        agent_id=_AGENT_ID,
        user_id=_USER_ID,
        upload_id=_UPLOAD_ID,
    )

    assert isinstance(result, Failure)
    assert isinstance(result.error, WorkspaceUploadRuntimeUnavailable)


@pytest.mark.asyncio
async def test_finalize_rejects_runtime_generation_change_before_mutation() -> None:
    """Finalize never sends a stale upload identity to Runtime Control."""
    coordinator = _Coordinator(
        status=_status(runtime_id=_RUNTIME_ID, desired_generation=1),
    )
    service, _, _, coordinator = _service(
        agent=_agent(),
        membership=_membership(),
        target=_target(runtime_id="runtime-new", desired_generation=2),
        coordinator=coordinator,
    )

    result = await service.finalize(
        agent_id=_AGENT_ID,
        user_id=_USER_ID,
        upload_id=_UPLOAD_ID,
        expected_revision=1,
    )

    assert isinstance(result, Failure)
    assert isinstance(result.error, WorkspaceUploadRevisionConflict)
    assert not coordinator.finalize_calls


@pytest.mark.asyncio
async def test_cancel_and_retry_forward_exact_preconditions_and_opaque_token() -> None:
    """Cancel and retry preserve revision, attempt, and decoded fencing bytes."""
    service, _, _, coordinator = _service(
        agent=_agent(),
        membership=_membership(),
    )
    token = "AQID"

    cancel_result = await service.cancel(
        agent_id=_AGENT_ID,
        user_id=_USER_ID,
        upload_id=_UPLOAD_ID,
        expected_revision=1,
        current_delivery_number=None,
    )
    retry_result = await service.retry(
        agent_id=_AGENT_ID,
        user_id=_USER_ID,
        upload_id=_UPLOAD_ID,
        expected_revision=2,
        current_delivery_number=3,
        overwrite=True,
        conflict_precondition=token,
    )

    assert isinstance(cancel_result, Success)
    assert isinstance(retry_result, Success)
    assert coordinator.cancel_calls[0].expected_revision == 1
    assert coordinator.cancel_calls[0].current_delivery_number is None
    assert coordinator.retry_calls[0].expected_revision == 2
    assert coordinator.retry_calls[0].current_delivery_number == 3
    assert coordinator.retry_calls[0].overwrite is True
    assert coordinator.retry_calls[0].conflict_precondition == b"\x01\x02\x03"


@pytest.mark.asyncio
async def test_retry_rejects_malformed_or_unrequested_conflict_token() -> None:
    """Opaque overwrite fencing is accepted only as canonical base64url."""
    service, _, _, coordinator = _service(
        agent=_agent(),
        membership=_membership(),
    )

    malformed = await service.retry(
        agent_id=_AGENT_ID,
        user_id=_USER_ID,
        upload_id=_UPLOAD_ID,
        expected_revision=1,
        current_delivery_number=1,
        overwrite=True,
        conflict_precondition="not base64!",
    )
    unrequested = await service.retry(
        agent_id=_AGENT_ID,
        user_id=_USER_ID,
        upload_id=_UPLOAD_ID,
        expected_revision=1,
        current_delivery_number=1,
        overwrite=False,
        conflict_precondition="AQID",
    )

    assert isinstance(malformed, Failure)
    assert isinstance(malformed.error, WorkspaceUploadInvalidRequest)
    assert isinstance(unrequested, Failure)
    assert isinstance(unrequested.error, WorkspaceUploadInvalidRequest)
    assert not coordinator.retry_calls


@pytest.mark.asyncio
async def test_status_identity_mismatch_is_concealed_as_not_found() -> None:
    """Runtime Control cannot make another requester's upload visible."""
    other_identity = WorkspaceUploadIdentity(
        upload_id=_UPLOAD_ID,
        requester_user_id=_OTHER_USER_ID,
        workspace_id=_WORKSPACE_ID,
        agent_id=_AGENT_ID,
        runtime_id=_RUNTIME_ID,
        desired_generation=1,
    )
    coordinator = _Coordinator(
        status=_status(),
        get_status=_status(identity=other_identity),
    )
    service, _, _, _ = _service(
        agent=_agent(),
        membership=_membership(),
        coordinator=coordinator,
    )

    result = await service.get(
        agent_id=_AGENT_ID,
        user_id=_USER_ID,
        upload_id=_UPLOAD_ID,
    )

    assert isinstance(result, Failure)
    assert isinstance(result.error, WorkspaceUploadNotFound)


@pytest.mark.asyncio
async def test_create_conceals_mismatched_runtime_control_identity() -> None:
    """Create does not return a ticket for a mismatched coordinator identity."""
    mismatched = WorkspaceUploadIdentity(
        upload_id=_UPLOAD_ID,
        requester_user_id=_USER_ID,
        workspace_id=_WORKSPACE_ID,
        agent_id=_AGENT_ID,
        runtime_id="runtime-other",
        desired_generation=1,
    )
    coordinator = _Coordinator(
        status=_status(identity=mismatched),
        echo_create_identity=False,
    )
    service, _, _, coordinator = _service(
        agent=_agent(),
        membership=_membership(),
        coordinator=coordinator,
    )

    result = await service.create(
        agent_id=_AGENT_ID,
        user_id=_USER_ID,
        destination_directory=".",
        filename="report.txt",
        expected_size=12,
        expected_sha256=_DIGEST,
        media_type=None,
        session_id=None,
    )

    assert isinstance(result, Failure)
    assert isinstance(result.error, WorkspaceUploadNotFound)
    assert not coordinator.issue_calls


@pytest.mark.asyncio
async def test_destination_runner_failure_is_a_bounded_destination_error() -> None:
    """Runner destination failures do not reach Runtime Control."""
    runner = _RunnerOperations(
        error=RuntimeRunnerOperationFailedError("destination is not a directory")
    )
    service, _, _, coordinator = _service(
        agent=_agent(),
        membership=_membership(),
        runner=runner,
    )

    result = await service.create(
        agent_id=_AGENT_ID,
        user_id=_USER_ID,
        destination_directory=".",
        filename="report.txt",
        expected_size=12,
        expected_sha256=_DIGEST,
        media_type=None,
        session_id=None,
    )

    assert isinstance(result, Failure)
    assert isinstance(result.error, WorkspaceUploadDestinationInvalid)
    assert not coordinator.create_requests
