"""Current public Session Browser admission without Runtime provisioning."""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import PurePosixPath
from typing import Protocol

from azents_runtime_control.browser_contract import (
    BrowserAuthority,
    BrowserObserveCommand,
    BrowserTarget,
)
from azents_runtime_control.browser_source_contract import BrowserScopeState
from azents_runtime_control.browser_viewer_contract import ViewerTarget
from azents_runtime_control.runtime_stream_session import BrowserStreamAuthority
from pydantic import BaseModel, ConfigDict, StrictStr, ValidationError

from azents.core.browser_configuration import BrowserConfigurationIntentReader
from azents.core.enums import (
    AgentRuntimeCapability,
    AgentSessionKind,
    RuntimeDesiredState,
    RuntimeProviderObservedState,
    RuntimeRunnerState,
)
from azents.repos.runtime_browser_authority_read import (
    RuntimeBrowserAuthorityReadRepository,
    RuntimeBrowserIdentityDenied,
)
from azents.runtime.control_protocol.runner_operations import (
    RuntimeRunnerOperationCanceledError,
    RuntimeRunnerOperationClient,
    RuntimeRunnerOperationFailedError,
    RuntimeRunnerOperationGenerationError,
    RuntimeRunnerOperationUnavailable,
)
from azents.runtime.coordination.data import RuntimeConnectionKind
from azents.runtime.coordination.store import RuntimeCoordinationStore
from azents.services.agent_runtime.lifecycle_data import RuntimeOperationTarget
from azents.services.runtime_browser.data import (
    RuntimeBrowserAdmission,
    RuntimeBrowserAuthority,
    RuntimeBrowserOperationError,
    RuntimeBrowserRequestError,
    RuntimeBrowserResource,
    RuntimeBrowserStreamUnavailable,
    RuntimeBrowserTargetUnavailable,
    RuntimeBrowserUnavailable,
)
from azents.services.session_working_folder_binding import (
    SessionWorkingFolderBindingError,
    SessionWorkingFolderBindingService,
)


class _RunnerWorkspaceObservation(BaseModel):
    """Project the interpreted registration field without narrowing extensions."""

    model_config = ConfigDict(
        extra="ignore", frozen=True, strict=True, hide_input_in_errors=True
    )

    workspace_path: StrictStr


class _RunnerCapabilitiesObservation(BaseModel):
    """Validate capability selection separately to retain failure classification."""

    model_config = ConfigDict(
        extra="ignore", frozen=True, strict=True, hide_input_in_errors=True
    )

    capabilities: list[StrictStr]


class RuntimeBrowserAuthorityResolver(Protocol):
    async def resolve(
        self,
        *,
        user_id: str,
        authentication_session_id: str,
        resource: RuntimeBrowserResource,
        resolved_at: datetime,
    ) -> RuntimeBrowserAdmission: ...


@dataclass
class DatabaseRuntimeBrowserAuthorityResolver:
    authority_repository: RuntimeBrowserAuthorityReadRepository
    runtime_coordination: RuntimeCoordinationStore
    working_folder_service: SessionWorkingFolderBindingService
    browser_configuration: BrowserConfigurationIntentReader

    async def resolve(
        self,
        *,
        user_id: str,
        authentication_session_id: str,
        resource: RuntimeBrowserResource,
        resolved_at: datetime,
    ) -> RuntimeBrowserAdmission:
        if resolved_at.tzinfo is None or resolved_at.utcoffset() is None:
            raise ValueError("Browser admission time must be timezone-aware")
        snapshot = await self.authority_repository.read_snapshot(
            user_id=user_id,
            authentication_session_id=authentication_session_id,
            workspace_handle=resource.workspace_handle,
            agent_id=resource.agent_id,
            session_id=resource.session_id,
            resolved_at=resolved_at,
        )
        if isinstance(snapshot, RuntimeBrowserIdentityDenied):
            match snapshot.reason:
                case "unauthenticated":
                    raise RuntimeBrowserRequestError(401, "Not authenticated")
                case "access_denied":
                    raise RuntimeBrowserRequestError(403, "Browser access is denied.")
                case "not_found":
                    raise RuntimeBrowserRequestError(404, "Session not found.")
        if not snapshot.agent.browser_enabled:
            return RuntimeBrowserUnavailable("browser_disabled")
        runtime = snapshot.runtime
        applied = snapshot.applied_configuration
        if (
            snapshot.agent.runtime_capability is not AgentRuntimeCapability.MANAGED
            or runtime is None
            or applied is None
            or runtime.agent_id != resource.agent_id
            or runtime.workspace_id != snapshot.agent.workspace_id
            or runtime.desired_state is not RuntimeDesiredState.RUNNING
            or runtime.terminal_delete_requested_generation is not None
            or runtime.provider_observed_state
            is not RuntimeProviderObservedState.RUNNING
            or runtime.provider_observed_generation != runtime.desired_generation
            or applied.target_generation != runtime.desired_generation
            or runtime.runner_state is not RuntimeRunnerState.READY
            or runtime.runner_generation <= 0
        ):
            return RuntimeBrowserUnavailable("runtime_unavailable")
        runner = await self.runtime_coordination.get_connection(
            kind=RuntimeConnectionKind.RUNNER, subject_id=runtime.id
        )
        if (
            runner is None
            or runner.generation != runtime.runner_generation
            or runner.expires_at <= resolved_at
        ):
            return RuntimeBrowserUnavailable("runtime_unavailable")
        try:
            workspace = _RunnerWorkspaceObservation.model_validate(
                runner.metadata
            ).workspace_path
        except ValidationError:
            return RuntimeBrowserUnavailable("runtime_unavailable")
        if (
            not PurePosixPath(workspace).is_absolute()
            or ".." in PurePosixPath(workspace).parts
            or workspace != runtime.workspace_path
        ):
            return RuntimeBrowserUnavailable("runtime_unavailable")
        try:
            capabilities = _RunnerCapabilitiesObservation.model_validate(
                runner.metadata
            ).capabilities
        except ValidationError:
            return RuntimeBrowserUnavailable("browser_unavailable")
        if "browser.v1" not in capabilities:
            return RuntimeBrowserUnavailable("browser_unavailable")
        if (
            await self.browser_configuration.current_intent(
                runtime.id, runtime.runner_generation, require_ready=True
            )
            is None
        ):
            return RuntimeBrowserUnavailable("browser_unavailable")
        target = RuntimeOperationTarget(
            id=runtime.id,
            runtime_capability_version=snapshot.agent.runtime_capability_version,
            desired_generation=runtime.desired_generation,
            runner_generation=runtime.runner_generation,
            configuration_sequence=applied.sequence,
            configuration_digest=applied.digest,
            workspace_path=workspace,
        )
        try:
            folder = (
                await self.working_folder_service.resolve_bound_authority_for_target(
                    agent_id=resource.agent_id,
                    session_id=resource.session_id,
                    runtime_target=target,
                )
            )
        except SessionWorkingFolderBindingError:
            return RuntimeBrowserUnavailable("working_folder_unavailable")
        path = PurePosixPath(folder.working_folder_path)
        if (
            folder.agent_id != resource.agent_id
            or folder.agent_runtime_id != runtime.id
            or folder.runtime_capability_version != target.runtime_capability_version
            or not path.is_absolute()
            or ".." in path.parts
            or not path.is_relative_to(PurePosixPath(workspace))
        ):
            return RuntimeBrowserUnavailable("working_folder_unavailable")
        return RuntimeBrowserAuthority(
            resource=resource,
            user_id=user_id,
            authentication_session_id=authentication_session_id,
            authentication_session_expires_at=(
                snapshot.authentication_session_expires_at
            ),
            target=target,
            working_directory=folder.working_folder_path,
            allow_input=snapshot.agent_session.session_kind is AgentSessionKind.ROOT,
        )


@dataclass
class DatabaseRuntimeBrowserStreamScopeValidator:
    """Shared API and Control validation of one immutable public Browser scope."""

    authority_repository: RuntimeBrowserAuthorityReadRepository
    authority_resolver: RuntimeBrowserAuthorityResolver
    runner_operations: RuntimeRunnerOperationClient
    clock: Callable[[], datetime]

    async def admit(
        self,
        *,
        resource: RuntimeBrowserResource,
        user_id: str,
        authentication_session_id: str,
        target: ViewerTarget,
    ) -> RuntimeBrowserAuthority:
        """Authorize current identities before querying any selected page status."""
        current = await self.authority_resolver.resolve(
            user_id=user_id,
            authentication_session_id=authentication_session_id,
            resource=resource,
            resolved_at=self.clock(),
        )
        if isinstance(current, RuntimeBrowserUnavailable):
            raise RuntimeBrowserStreamUnavailable()
        try:
            result = await self.runner_operations.run_browser_command(
                runtime_id=current.target.id,
                runner_generation=current.target.runner_generation,
                owner_session_id=resource.session_id,
                command=BrowserObserveCommand(
                    BrowserAuthority(resource.session_id, current.working_directory),
                    BrowserTarget(
                        target.task_id,
                        target.page_id,
                        target.resource_incarnation,
                        None,
                    ),
                    "status",
                    False,
                    1,
                ),
                deadline_at=self.clock() + timedelta(seconds=5),
            )
        except asyncio.CancelledError:
            raise
        except (
            RuntimeRunnerOperationGenerationError,
            RuntimeRunnerOperationUnavailable,
            RuntimeRunnerOperationCanceledError,
        ):
            raise RuntimeBrowserStreamUnavailable() from None
        except RuntimeRunnerOperationFailedError as error:
            if error.code == "browser_stale_generation":
                raise RuntimeBrowserStreamUnavailable() from None
            if error.code in {
                "browser_stale_target",
                "browser_invalid_target",
                "browser_stale_generation",
                "browser_invalid_authority",
            }:
                raise RuntimeBrowserTargetUnavailable() from None
            raise RuntimeBrowserOperationError(
                "Browser status validation failed."
            ) from None
        page = result.page
        if (
            page is None
            or page.task_id != target.task_id
            or page.id != target.page_id
            or page.resource_incarnation != target.resource_incarnation
        ):
            raise RuntimeBrowserTargetUnavailable()
        refreshed = await self.authority_resolver.resolve(
            user_id=user_id,
            authentication_session_id=authentication_session_id,
            resource=resource,
            resolved_at=self.clock(),
        )
        if isinstance(refreshed, RuntimeBrowserAuthority):
            if refreshed.allow_input != current.allow_input:
                raise RuntimeBrowserRequestError(403, "Browser input access changed.")
            if (
                refreshed.authentication_session_expires_at
                < current.authentication_session_expires_at
            ):
                raise RuntimeBrowserRequestError(401, "Browser authentication changed.")
        if refreshed != current:
            raise RuntimeBrowserStreamUnavailable()
        return current

    async def __call__(self, authority: BrowserStreamAuthority) -> BrowserScopeState:
        now = self.clock()
        if (
            authority.transport_deadline_at <= now
            or authority.transport_deadline_at > now + timedelta(hours=1)
            or not isinstance(authority.allow_input, bool)
        ):
            return BrowserScopeState.EXPIRED
        handle = await self.authority_repository.read_stream_workspace_handle(
            agent_id=authority.agent_id, session_id=authority.session_id
        )
        if handle is None:
            return BrowserScopeState.REVOKED
        try:
            # Native page admission belongs to admit(); live frames already reach
            # Runner's exact binding/target/source fence before any SDK effect.
            # Re-entering Browser operations here serializes every key behind
            # Control RPCs, including while Control is forwarding that input.
            current = await self.authority_resolver.resolve(
                resource=RuntimeBrowserResource(
                    handle, authority.agent_id, authority.session_id
                ),
                user_id=authority.user_id,
                authentication_session_id=authority.authentication_session_id,
                resolved_at=now,
            )
        except RuntimeBrowserRequestError:
            return BrowserScopeState.REVOKED
        if isinstance(current, RuntimeBrowserUnavailable):
            if current.reason_code == "browser_disabled":
                return BrowserScopeState.REVOKED
            return BrowserScopeState.UNAVAILABLE
        if current.authentication_session_expires_at < authority.transport_deadline_at:
            return BrowserScopeState.EXPIRED
        if current.allow_input != authority.allow_input:
            return BrowserScopeState.REVOKED
        if (
            current.target.id != authority.runtime_id
            or current.target.desired_generation != authority.desired_generation
            or current.target.runner_generation != authority.runner_generation
        ):
            return BrowserScopeState.UNAVAILABLE
        return BrowserScopeState.CURRENT
