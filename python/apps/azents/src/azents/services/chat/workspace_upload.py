"""Agent Workspace direct-object upload service."""

from __future__ import annotations

import base64
import binascii
import dataclasses
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import PurePosixPath
from typing import Annotated, Protocol, assert_never

import grpc
from azcommon.result import Failure, Result, Success
from azcommon.uuid import uuid7
from azents_runtime_control.grpc_workspace_upload_client import (
    WorkspaceUploadCancelRequest,
    WorkspaceUploadCreateRequest,
    WorkspaceUploadIdentity,
    WorkspaceUploadRetryRequest,
    WorkspaceUploadStatus,
    WorkspaceUploadTicket,
)
from fastapi import Depends

from azents.repos.workspace_upload_authority.data import (
    WorkspaceUploadRequesterAccessDenied,
    WorkspaceUploadRequesterAgentUnavailable,
    WorkspaceUploadRequesterAuthority,
)
from azents.repos.workspace_upload_authority.operations import (
    WorkspaceUploadAuthorizationRepository,
)
from azents.runtime.control_protocol.runner_operations import (
    RuntimeFileStatResult,
    RuntimeRunnerOperationFailedError,
    RuntimeRunnerOperationGenerationError,
    RuntimeRunnerOperationUnavailable,
)
from azents.runtime.deps import (
    get_api_runtime_workspace_upload_coordinator_client,
    get_runtime_runner_operation_client,
)
from azents.services.agent_runtime.lifecycle_data import (
    RuntimeOperationTarget,
    RuntimeOperationTargetResolver,
)
from azents.services.agent_runtime.service import AgentRuntimeService
from azents.services.chat.workspace import (
    AgentWorkspacePathDenied,
    AgentWorkspacePathUnavailable,
    agent_workspace_root,
    normalize_agent_workspace_path,
)
from azents.services.runtime_storage_error import RuntimeStorageError

_UPLOAD_OPERATION_TTL = timedelta(hours=1)
_RUNNER_OPERATION_TIMEOUT = timedelta(minutes=2)


@dataclasses.dataclass(frozen=True)
class WorkspaceUploadAgentNotFound:
    """The requested Agent is not visible to the requester."""

    agent_id: str


@dataclasses.dataclass(frozen=True)
class WorkspaceUploadAccessDenied:
    """The requester cannot use the selected Agent Workspace."""

    agent_id: str


@dataclasses.dataclass(frozen=True)
class WorkspaceUploadRuntimeUnavailable:
    """The current Runner-backed Runtime cannot accept an upload."""

    detail: str


@dataclasses.dataclass(frozen=True)
class WorkspaceUploadPathUnavailable:
    """Runner has not reported a usable Workspace root."""


@dataclasses.dataclass(frozen=True)
class WorkspaceUploadInvalidRequest:
    """The upload metadata does not satisfy the public contract."""

    detail: str


@dataclasses.dataclass(frozen=True)
class WorkspaceUploadDestinationInvalid:
    """The selected destination is not an accessible directory."""

    detail: str


@dataclasses.dataclass(frozen=True)
class WorkspaceUploadCoordinatorUnavailable:
    """The API cannot reach the configured Runtime Control upload coordinator."""


@dataclasses.dataclass(frozen=True)
class WorkspaceUploadNotFound:
    """The upload is unavailable to the requester."""


@dataclasses.dataclass(frozen=True)
class WorkspaceUploadRevisionConflict:
    """The supplied upload or Runtime revision is stale."""

    detail: str


@dataclasses.dataclass(frozen=True)
class WorkspaceUploadAdmissionRejected:
    """Runtime Control rejected bounded upload admission."""

    detail: str


WorkspaceUploadError = (
    WorkspaceUploadAgentNotFound
    | WorkspaceUploadAccessDenied
    | WorkspaceUploadRuntimeUnavailable
    | WorkspaceUploadPathUnavailable
    | WorkspaceUploadInvalidRequest
    | WorkspaceUploadDestinationInvalid
    | WorkspaceUploadCoordinatorUnavailable
    | WorkspaceUploadNotFound
    | WorkspaceUploadRevisionConflict
    | WorkspaceUploadAdmissionRejected
)


@dataclasses.dataclass(frozen=True)
class WorkspaceUploadCreateOutput:
    """Public service result containing status and one direct PUT ticket."""

    status: WorkspaceUploadStatus
    ticket: WorkspaceUploadTicket


class WorkspaceUploadRunnerOperations(Protocol):
    """Runner operation boundary required for destination validation."""

    async def stat_file(
        self,
        *,
        runtime_id: str,
        runner_generation: int,
        owner_session_id: str | None,
        path: str,
        deadline_at: datetime,
    ) -> RuntimeFileStatResult:
        """Stat one Runner-reported Workspace path."""
        ...


class WorkspaceUploadCoordinator(Protocol):
    """Runtime Control boundary required by the public upload service."""

    async def create(
        self,
        request: WorkspaceUploadCreateRequest,
    ) -> WorkspaceUploadStatus:
        """Create one upload admission."""
        ...

    async def issue_ticket(
        self,
        *,
        identity: WorkspaceUploadIdentity,
        expected_revision: int,
    ) -> tuple[WorkspaceUploadStatus, WorkspaceUploadTicket]:
        """Issue one transient browser PUT ticket."""
        ...

    async def get(self, identity: WorkspaceUploadIdentity) -> WorkspaceUploadStatus:
        """Read one requester-scoped upload status."""
        ...

    async def finalize(
        self,
        *,
        identity: WorkspaceUploadIdentity,
        expected_revision: int,
    ) -> WorkspaceUploadStatus:
        """Finalize one exact upload revision."""
        ...

    async def cancel(
        self,
        request: WorkspaceUploadCancelRequest,
    ) -> WorkspaceUploadStatus:
        """Cancel one exact upload revision."""
        ...

    async def retry(
        self,
        request: WorkspaceUploadRetryRequest,
    ) -> WorkspaceUploadStatus:
        """Retry one exact delivery attempt."""
        ...


@dataclasses.dataclass
class WorkspaceUploadService:
    """Authorize Workspace uploads and adapt them to Runtime Control."""

    authorization_repository: Annotated[
        WorkspaceUploadAuthorizationRepository,
        Depends(WorkspaceUploadAuthorizationRepository),
    ]
    runtime_target_resolver: Annotated[
        RuntimeOperationTargetResolver,
        Depends(AgentRuntimeService),
    ]
    runner_operations: Annotated[
        WorkspaceUploadRunnerOperations,
        Depends(get_runtime_runner_operation_client),
    ]
    coordinator: Annotated[
        WorkspaceUploadCoordinator | None,
        Depends(get_api_runtime_workspace_upload_coordinator_client),
    ]
    clock: Callable[[], datetime] = dataclasses.field(
        default_factory=lambda: _utc_now,
        init=False,
    )

    async def create(
        self,
        *,
        agent_id: str,
        user_id: str,
        destination_directory: str,
        filename: str,
        expected_size: int,
        expected_sha256: str,
        media_type: str | None,
        session_id: str | None,
    ) -> Result[WorkspaceUploadCreateOutput, WorkspaceUploadError]:
        """Authorize, resolve, and create one direct browser upload."""
        authorized = await self._authorize(agent_id, user_id)
        if isinstance(authorized, Failure):
            return authorized
        if expected_size < 0:
            return Failure(
                WorkspaceUploadInvalidRequest(
                    detail="expected_size must not be negative.",
                )
            )
        if not _is_sha256(expected_sha256):
            return Failure(
                WorkspaceUploadInvalidRequest(
                    detail="expected_sha256 must be a lower-case SHA-256 digest.",
                )
            )
        media_type_result = _validate_media_type(media_type)
        if isinstance(media_type_result, Failure):
            return Failure(media_type_result.error)
        filename_result = _validate_filename(filename)
        if isinstance(filename_result, Failure):
            return Failure(filename_result.error)
        if self.coordinator is None:
            return Failure(WorkspaceUploadCoordinatorUnavailable())
        target_result = await self._resolve_destination(
            agent_id=agent_id,
            destination_directory=destination_directory,
            filename=filename,
        )
        if isinstance(target_result, Failure):
            return target_result
        target, normalized_directory, destination_path = target_result.value
        now = self._now()
        identity = WorkspaceUploadIdentity(
            upload_id=uuid7().hex,
            requester_user_id=user_id,
            workspace_id=authorized.value.agent.workspace_id,
            agent_id=agent_id,
            runtime_id=target.id,
            desired_generation=target.desired_generation,
            session_id=session_id,
        )
        request = WorkspaceUploadCreateRequest(
            identity=identity,
            destination_directory=normalized_directory.as_posix(),
            filename=filename,
            destination_path=destination_path.as_posix(),
            expected_size=expected_size,
            expected_sha256=expected_sha256,
            media_type=media_type,
            deadline_at=now + _UPLOAD_OPERATION_TTL,
        )
        try:
            status = await self.coordinator.create(request)
            scoped = _validate_status_scope(
                status,
                authorized.value,
                user_id,
                agent_id,
                upload_id=identity.upload_id,
                expected_identity=identity,
            )
            if isinstance(scoped, Failure):
                return scoped
            status, ticket = await self.coordinator.issue_ticket(
                identity=identity,
                expected_revision=status.revision,
            )
        except grpc.aio.AioRpcError as error:
            return Failure(_map_rpc_error(error))
        scoped = _validate_status_scope(
            status,
            authorized.value,
            user_id,
            agent_id,
            upload_id=identity.upload_id,
            expected_identity=identity,
        )
        if isinstance(scoped, Failure):
            return scoped
        return Success(WorkspaceUploadCreateOutput(status=status, ticket=ticket))

    async def get(
        self,
        *,
        agent_id: str,
        user_id: str,
        upload_id: str,
    ) -> Result[WorkspaceUploadStatus, WorkspaceUploadError]:
        """Read one requester-bound upload status."""
        authorized = await self._authorize(agent_id, user_id)
        if isinstance(authorized, Failure):
            return authorized
        if self.coordinator is None:
            return Failure(WorkspaceUploadCoordinatorUnavailable())
        try:
            identity = await self._lookup_identity(
                authorized.value,
                agent_id=agent_id,
                user_id=user_id,
                upload_id=upload_id,
            )
        except RuntimeStorageError as error:
            return Failure(WorkspaceUploadRuntimeUnavailable(detail=error.detail))
        try:
            status = await self.coordinator.get(identity)
        except grpc.aio.AioRpcError as error:
            return Failure(_map_rpc_error(error))
        return _validate_status_scope(
            status,
            authorized.value,
            user_id,
            agent_id,
            upload_id=upload_id,
        )

    async def finalize(
        self,
        *,
        agent_id: str,
        user_id: str,
        upload_id: str,
        expected_revision: int,
    ) -> Result[WorkspaceUploadStatus, WorkspaceUploadError]:
        """Finalize one exact ingress revision after current Runtime validation."""
        if expected_revision <= 0:
            return Failure(
                WorkspaceUploadInvalidRequest(
                    detail="expected_revision must be positive.",
                )
            )
        authorized = await self._authorize(agent_id, user_id)
        if isinstance(authorized, Failure):
            return authorized
        if self.coordinator is None:
            return Failure(WorkspaceUploadCoordinatorUnavailable())
        try:
            lookup_identity = await self._lookup_identity(
                authorized.value,
                agent_id=agent_id,
                user_id=user_id,
                upload_id=upload_id,
            )
        except RuntimeStorageError as error:
            return Failure(WorkspaceUploadRuntimeUnavailable(detail=error.detail))
        try:
            current = await self.coordinator.get(lookup_identity)
        except grpc.aio.AioRpcError as error:
            return Failure(_map_rpc_error(error))
        scoped = _validate_status_scope(
            current,
            authorized.value,
            user_id,
            agent_id,
            upload_id=upload_id,
        )
        if isinstance(scoped, Failure):
            return scoped
        target_result = await self._resolve_current_target(agent_id)
        if isinstance(target_result, Failure):
            return target_result
        if (
            scoped.value.identity.runtime_id != target_result.value.id
            or scoped.value.identity.desired_generation
            != target_result.value.desired_generation
        ):
            return Failure(
                WorkspaceUploadRevisionConflict(
                    detail="Runtime changed since the upload was created.",
                )
            )
        try:
            status = await self.coordinator.finalize(
                identity=scoped.value.identity,
                expected_revision=expected_revision,
            )
        except grpc.aio.AioRpcError as error:
            return Failure(_map_rpc_error(error))
        return _validate_status_scope(
            status,
            authorized.value,
            user_id,
            agent_id,
            upload_id=upload_id,
        )

    async def cancel(
        self,
        *,
        agent_id: str,
        user_id: str,
        upload_id: str,
        expected_revision: int,
        current_delivery_number: int | None,
    ) -> Result[WorkspaceUploadStatus, WorkspaceUploadError]:
        """Request cancellation of one exact upload revision."""
        if expected_revision <= 0:
            return Failure(
                WorkspaceUploadInvalidRequest(
                    detail="expected_revision must be positive.",
                )
            )
        if current_delivery_number is not None and current_delivery_number <= 0:
            return Failure(
                WorkspaceUploadInvalidRequest(
                    detail="current_delivery_number must be positive.",
                )
            )
        authorized = await self._authorize(agent_id, user_id)
        if isinstance(authorized, Failure):
            return authorized
        if self.coordinator is None:
            return Failure(WorkspaceUploadCoordinatorUnavailable())
        current_result = await self._get_scoped_status(
            authorized.value,
            agent_id=agent_id,
            user_id=user_id,
            upload_id=upload_id,
        )
        if isinstance(current_result, Failure):
            return current_result
        try:
            status = await self.coordinator.cancel(
                WorkspaceUploadCancelRequest(
                    identity=current_result.value.identity,
                    expected_revision=expected_revision,
                    current_delivery_number=current_delivery_number,
                )
            )
        except grpc.aio.AioRpcError as error:
            return Failure(_map_rpc_error(error))
        return _validate_status_scope(
            status,
            authorized.value,
            user_id,
            agent_id,
            upload_id=upload_id,
        )

    async def retry(
        self,
        *,
        agent_id: str,
        user_id: str,
        upload_id: str,
        expected_revision: int,
        current_delivery_number: int,
        overwrite: bool,
        conflict_precondition: str | None,
    ) -> Result[WorkspaceUploadStatus, WorkspaceUploadError]:
        """Append one immutable delivery retry over the retained source."""
        if expected_revision <= 0 or current_delivery_number <= 0:
            return Failure(
                WorkspaceUploadInvalidRequest(
                    detail=(
                        "expected_revision and current_delivery_number must be "
                        "positive."
                    ),
                )
            )
        token_result = _decode_conflict_precondition(conflict_precondition)
        if isinstance(token_result, Failure):
            return Failure(token_result.error)
        if not overwrite and conflict_precondition is not None:
            return Failure(
                WorkspaceUploadInvalidRequest(
                    detail=(
                        "conflict_precondition is only valid for an overwrite retry."
                    ),
                )
            )
        authorized = await self._authorize(agent_id, user_id)
        if isinstance(authorized, Failure):
            return authorized
        if self.coordinator is None:
            return Failure(WorkspaceUploadCoordinatorUnavailable())
        current_result = await self._get_scoped_status(
            authorized.value,
            agent_id=agent_id,
            user_id=user_id,
            upload_id=upload_id,
        )
        if isinstance(current_result, Failure):
            return current_result
        try:
            status = await self.coordinator.retry(
                WorkspaceUploadRetryRequest(
                    identity=current_result.value.identity,
                    expected_revision=expected_revision,
                    current_delivery_number=current_delivery_number,
                    overwrite=overwrite,
                    conflict_precondition=token_result.value,
                )
            )
        except grpc.aio.AioRpcError as error:
            return Failure(_map_rpc_error(error))
        return _validate_status_scope(
            status,
            authorized.value,
            user_id,
            agent_id,
            upload_id=upload_id,
        )

    async def _authorize(
        self,
        agent_id: str,
        user_id: str,
    ) -> Result[WorkspaceUploadRequesterAuthority, WorkspaceUploadError]:
        """Resolve Agent visibility and Workspace membership."""
        result = await self.authorization_repository.authorize(
            agent_id=agent_id,
            user_id=user_id,
        )
        if isinstance(result, Success):
            return Success(result.value)
        match result.error:
            case WorkspaceUploadRequesterAgentUnavailable():
                return Failure(WorkspaceUploadAgentNotFound(agent_id=agent_id))
            case WorkspaceUploadRequesterAccessDenied():
                return Failure(WorkspaceUploadAccessDenied(agent_id=agent_id))
            case _:
                assert_never(result.error)

    async def _resolve_destination(
        self,
        *,
        agent_id: str,
        destination_directory: str,
        filename: str,
    ) -> Result[
        tuple[RuntimeOperationTarget, PurePosixPath, PurePosixPath],
        WorkspaceUploadError,
    ]:
        """Resolve and validate the exact Runner-backed destination."""
        target_result = await self._resolve_current_target(agent_id)
        if isinstance(target_result, Failure):
            return target_result
        target = target_result.value
        try:
            root = agent_workspace_root(target.workspace_path)
            directory = normalize_agent_workspace_path(
                destination_directory,
                workspace_root=root,
            )
        except AgentWorkspacePathUnavailable:
            return Failure(WorkspaceUploadPathUnavailable())
        except AgentWorkspacePathDenied:
            return Failure(
                WorkspaceUploadDestinationInvalid(
                    detail="Destination directory is outside Agent Workspace.",
                )
            )
        try:
            stat = await self.runner_operations.stat_file(
                runtime_id=target.id,
                runner_generation=target.runner_generation,
                owner_session_id=None,
                path=directory.as_posix(),
                deadline_at=self._now() + _RUNNER_OPERATION_TIMEOUT,
            )
        except (
            RuntimeRunnerOperationUnavailable,
            RuntimeRunnerOperationGenerationError,
        ) as error:
            return Failure(WorkspaceUploadRuntimeUnavailable(detail=str(error)))
        except RuntimeRunnerOperationFailedError as error:
            return Failure(WorkspaceUploadDestinationInvalid(detail=str(error)))
        if stat.kind == "symlink":
            return Failure(
                WorkspaceUploadDestinationInvalid(
                    detail="Destination directory must not be a symlink.",
                )
            )
        if stat.kind != "directory":
            return Failure(
                WorkspaceUploadDestinationInvalid(
                    detail="Destination path is not an existing directory.",
                )
            )
        return Success((target, directory, directory / filename))

    async def _resolve_current_target(
        self,
        agent_id: str,
    ) -> Result[RuntimeOperationTarget, WorkspaceUploadError]:
        """Resolve a ready Runtime without starting a stopped Runtime."""
        try:
            return Success(
                await self.runtime_target_resolver.resolve_operation_target(
                    agent_id,
                    wait_timeout_seconds=0.0,
                    start_if_stopped=False,
                )
            )
        except RuntimeStorageError as error:
            return Failure(WorkspaceUploadRuntimeUnavailable(detail=str(error)))

    async def _get_scoped_status(
        self,
        authorized: WorkspaceUploadRequesterAuthority,
        *,
        agent_id: str,
        user_id: str,
        upload_id: str,
    ) -> Result[WorkspaceUploadStatus, WorkspaceUploadError]:
        """Load status and verify its immutable requester scope."""
        if self.coordinator is None:
            return Failure(WorkspaceUploadCoordinatorUnavailable())
        try:
            identity = await self._lookup_identity(
                authorized,
                agent_id=agent_id,
                user_id=user_id,
                upload_id=upload_id,
            )
        except RuntimeStorageError as error:
            return Failure(WorkspaceUploadRuntimeUnavailable(detail=error.detail))
        try:
            status = await self.coordinator.get(identity)
        except grpc.aio.AioRpcError as error:
            return Failure(_map_rpc_error(error))
        return _validate_status_scope(
            status,
            authorized,
            user_id,
            agent_id,
            upload_id=upload_id,
        )

    async def _lookup_identity(
        self,
        authorized: WorkspaceUploadRequesterAuthority,
        *,
        agent_id: str,
        user_id: str,
        upload_id: str,
    ) -> WorkspaceUploadIdentity:
        """Build a non-authoritative lookup envelope for Runtime Control."""
        runtime_id = "workspace-upload-lookup"
        desired_generation = 1
        snapshot = await self.runtime_target_resolver.get_lifecycle_snapshot(agent_id)
        if snapshot.runtime is not None:
            runtime_id = snapshot.runtime.id
            desired_generation = max(snapshot.runtime.desired_generation, 1)
        return WorkspaceUploadIdentity(
            upload_id=upload_id,
            requester_user_id=user_id,
            workspace_id=authorized.agent.workspace_id,
            agent_id=agent_id,
            runtime_id=runtime_id,
            desired_generation=desired_generation,
        )

    def _now(self) -> datetime:
        """Return one timezone-aware service clock value."""
        now = self.clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("Workspace upload service clock must be timezone-aware")
        return now.astimezone(UTC)


def _utc_now() -> datetime:
    """Return the current timezone-aware UTC timestamp."""
    return datetime.now(UTC)


def _validate_filename(
    filename: str,
) -> Result[str, WorkspaceUploadInvalidRequest]:
    """Validate one local basename before Runtime admission."""
    if not filename or len(filename.encode("utf-8")) > 255:
        return Failure(
            WorkspaceUploadInvalidRequest(
                detail="filename must be between one and 255 bytes.",
            )
        )
    if filename in {".", ".."} or any(
        separator in filename for separator in ("/", "\\", "\x00")
    ):
        return Failure(
            WorkspaceUploadInvalidRequest(
                detail="filename must be one basename.",
            )
        )
    return Success(filename)


def _validate_media_type(
    media_type: str | None,
) -> Result[str | None, WorkspaceUploadInvalidRequest]:
    """Validate one optional MIME type before Runtime admission."""
    if media_type is None:
        return Success(None)
    if not media_type or len(media_type.encode("utf-8")) > 255:
        return Failure(
            WorkspaceUploadInvalidRequest(
                detail="media_type must be between one and 255 bytes.",
            )
        )
    return Success(media_type)


def _is_sha256(value: str) -> bool:
    """Return whether one value is a lower-case SHA-256 digest."""
    return len(value) == 64 and all(
        character in "0123456789abcdef" for character in value
    )


def _decode_conflict_precondition(
    value: str | None,
) -> Result[bytes | None, WorkspaceUploadInvalidRequest]:
    """Decode one public opaque conflict token without interpreting it."""
    if value is None:
        return Success(None)
    if not value or len(value) > 684:
        return Failure(
            WorkspaceUploadInvalidRequest(
                detail="conflict_precondition is invalid.",
            )
        )
    if any(
        character
        not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
        for character in value
    ):
        return Failure(
            WorkspaceUploadInvalidRequest(
                detail="conflict_precondition is invalid.",
            )
        )
    try:
        token = base64.b64decode(
            value + "=" * (-len(value) % 4),
            altchars=b"-_",
            validate=True,
        )
    except ValueError, binascii.Error:
        return Failure(
            WorkspaceUploadInvalidRequest(
                detail="conflict_precondition is invalid.",
            )
        )
    if base64.urlsafe_b64encode(token).decode("ascii").rstrip("=") != value:
        return Failure(
            WorkspaceUploadInvalidRequest(
                detail="conflict_precondition is invalid.",
            )
        )
    if not 1 <= len(token) <= 512:
        return Failure(
            WorkspaceUploadInvalidRequest(
                detail="conflict_precondition is invalid.",
            )
        )
    return Success(token)


def _validate_status_scope(
    status: WorkspaceUploadStatus,
    authorized: WorkspaceUploadRequesterAuthority,
    user_id: str,
    agent_id: str,
    *,
    upload_id: str,
    expected_identity: WorkspaceUploadIdentity | None = None,
) -> Result[WorkspaceUploadStatus, WorkspaceUploadError]:
    """Reject a Runtime Control result outside the current requester scope."""
    identity = status.identity
    if (
        identity.upload_id != upload_id
        or identity.requester_user_id != user_id
        or identity.workspace_id != authorized.agent.workspace_id
        or identity.agent_id != agent_id
    ):
        return Failure(WorkspaceUploadNotFound())
    if expected_identity is not None and identity != expected_identity:
        return Failure(WorkspaceUploadNotFound())
    return Success(status)


def _map_rpc_error(
    error: grpc.aio.AioRpcError,
) -> WorkspaceUploadError:
    """Map stable Runtime Control client errors to actionable 4xx outcomes."""
    details = error.details() or "Runtime Control rejected the upload request."
    match error.code():
        case grpc.StatusCode.NOT_FOUND:
            return WorkspaceUploadNotFound()
        case grpc.StatusCode.INVALID_ARGUMENT:
            return WorkspaceUploadInvalidRequest(detail=details)
        case grpc.StatusCode.FAILED_PRECONDITION:
            return WorkspaceUploadRevisionConflict(detail=details)
        case grpc.StatusCode.RESOURCE_EXHAUSTED:
            return WorkspaceUploadAdmissionRejected(detail=details)
        case _:
            raise error
