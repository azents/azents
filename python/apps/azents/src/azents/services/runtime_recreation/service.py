"""Authority-scoped Runtime recreation operations and reconciliation."""

import dataclasses
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    AgentRuntimeCapability,
    RuntimeDesiredState,
    RuntimeLifecycleCommandType,
    RuntimeProviderKind,
)
from azents.core.runtime_profile import (
    RuntimeConfigurationResolutionStatus,
    RuntimeInfrastructureProfileKind,
    RuntimeRecreationItemStatus,
    RuntimeRecreationTargetKind,
)
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.agent import AgentRepository
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.agent_runtime.data import AgentRuntime
from azents.repos.runtime_profile.data import (
    RuntimeRecreationOperation,
    RuntimeRecreationOperationItem,
)
from azents.repos.runtime_profile.repository import RuntimeProfileRepository
from azents.repos.runtime_provider.repository import RuntimeProviderRepository

_DEFAULT_OPERATION_LIMIT = 20
_DEFAULT_ITEM_LIMIT = 100
_DEFAULT_MAXIMUM_ATTEMPTS = 3


@dataclasses.dataclass(frozen=True)
class RuntimeRecreationProjection:
    """One operation and its bounded non-success item details."""

    operation: RuntimeRecreationOperation
    items: tuple[RuntimeRecreationOperationItem, ...]


@dataclasses.dataclass
class RuntimeRecreationUnavailable(Exception):
    """One bounded recreation operation failure."""

    code: str
    message: str
    current_version: int | None = None

    def __post_init__(self) -> None:
        Exception.__init__(self, self.message)


@dataclasses.dataclass
class RuntimeRecreationService:
    """Create and inspect recreation operations within authority boundaries."""

    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]
    profile_repository: Annotated[
        RuntimeProfileRepository, Depends(RuntimeProfileRepository)
    ]
    provider_repository: Annotated[
        RuntimeProviderRepository, Depends(RuntimeProviderRepository)
    ]

    async def create_provider_operation(
        self,
        provider_logical_id: str,
        *,
        expected_admin_version: int,
        concurrency_limit: int,
        actor_user_id: str,
    ) -> RuntimeRecreationOperation:
        """Create one exact Provider-scoped recreation operation."""
        async with self.session_manager() as session:
            provider = await self.provider_repository.get_by_provider_id(
                session,
                provider_logical_id=provider_logical_id,
                for_update=True,
            )
            if provider is None:
                raise RuntimeRecreationUnavailable(
                    code="provider_not_found",
                    message="Runtime Provider was not found.",
                )
            if provider.admin_version != expected_admin_version:
                raise RuntimeRecreationUnavailable(
                    code="target_version_conflict",
                    message="Runtime Provider version is stale.",
                    current_version=provider.admin_version,
                )
            return await self._create_operation(
                session,
                target_kind=RuntimeRecreationTargetKind.PROVIDER,
                target_id=provider.id,
                concurrency_limit=concurrency_limit,
                actor_user_id=actor_user_id,
                actor_workspace_user_id=None,
            )

    async def create_infrastructure_profile_operation(
        self,
        provider_logical_id: str,
        profile_id: str,
        *,
        profile_kind: RuntimeInfrastructureProfileKind,
        expected_version: int,
        concurrency_limit: int,
        actor_user_id: str,
    ) -> RuntimeRecreationOperation:
        """Create one exact infrastructure-Profile-scoped operation."""
        async with self.session_manager() as session:
            provider = await self.provider_repository.get_by_provider_id(
                session,
                provider_logical_id=provider_logical_id,
                for_update=False,
            )
            if provider is None:
                raise RuntimeRecreationUnavailable(
                    code="provider_not_found",
                    message="Runtime Provider was not found.",
                )
            expected_kind = {
                RuntimeProviderKind.KUBERNETES: (
                    RuntimeInfrastructureProfileKind.KUBERNETES_POD
                ),
                RuntimeProviderKind.DOCKER: (
                    RuntimeInfrastructureProfileKind.DOCKER_CONTAINER
                ),
            }.get(provider.kind)
            if expected_kind is not profile_kind:
                raise RuntimeRecreationUnavailable(
                    code="profile_kind_mismatch",
                    message="Profile kind does not match the owning Provider.",
                )
            profile = await self.profile_repository.get_infrastructure_profile(
                session,
                profile_id=profile_id,
                for_update=True,
            )
            if profile is None or profile.provider_id != provider.id:
                raise RuntimeRecreationUnavailable(
                    code="profile_not_found",
                    message="Runtime infrastructure Profile was not found.",
                )
            if profile.profile_kind is not profile_kind:
                raise RuntimeRecreationUnavailable(
                    code="profile_kind_mismatch",
                    message="Profile kind does not match the requested operation.",
                )
            if profile.version != expected_version:
                raise RuntimeRecreationUnavailable(
                    code="target_version_conflict",
                    message="Runtime infrastructure Profile version is stale.",
                    current_version=profile.version,
                )
            return await self._create_operation(
                session,
                target_kind=RuntimeRecreationTargetKind.INFRASTRUCTURE_PROFILE,
                target_id=profile.id,
                concurrency_limit=concurrency_limit,
                actor_user_id=actor_user_id,
                actor_workspace_user_id=None,
            )

    async def create_workspace_profile_operation(
        self,
        workspace_id: str,
        profile_id: str,
        *,
        expected_version: int,
        concurrency_limit: int,
        actor_workspace_user_id: str,
    ) -> RuntimeRecreationOperation:
        """Create one Workspace-Runtime-Profile-scoped operation."""
        async with self.session_manager() as session:
            profile = await self.profile_repository.get_workspace_runtime_profile(
                session,
                workspace_id=workspace_id,
                profile_id=profile_id,
                for_update=True,
            )
            if profile is None:
                raise RuntimeRecreationUnavailable(
                    code="profile_not_found",
                    message="Workspace Runtime Profile was not found.",
                )
            if profile.version != expected_version:
                raise RuntimeRecreationUnavailable(
                    code="target_version_conflict",
                    message="Workspace Runtime Profile version is stale.",
                    current_version=profile.version,
                )
            return await self._create_operation(
                session,
                target_kind=RuntimeRecreationTargetKind.WORKSPACE_RUNTIME_PROFILE,
                target_id=profile.id,
                concurrency_limit=concurrency_limit,
                actor_user_id=None,
                actor_workspace_user_id=actor_workspace_user_id,
            )

    async def get_platform_operation(
        self,
        operation_id: str,
        *,
        offset: int,
        limit: int,
    ) -> RuntimeRecreationProjection:
        """Return one Platform-authority operation and bounded item details."""
        async with self.session_manager() as session:
            operation = await self.profile_repository.get_recreation_operation(
                session,
                operation_id=operation_id,
            )
            if operation is None or operation.actor_workspace_user_id is not None:
                raise RuntimeRecreationUnavailable(
                    code="operation_not_found",
                    message="Runtime recreation operation was not found.",
                )
            return await self._project_operation(
                session,
                operation=operation,
                offset=offset,
                limit=limit,
            )

    async def get_workspace_operation(
        self,
        workspace_id: str,
        operation_id: str,
        *,
        offset: int,
        limit: int,
    ) -> RuntimeRecreationProjection:
        """Return an operation only when its target belongs to the Workspace."""
        async with self.session_manager() as session:
            operation = await self.profile_repository.get_recreation_operation(
                session,
                operation_id=operation_id,
            )
            if (
                operation is None
                or operation.target_kind
                is not RuntimeRecreationTargetKind.WORKSPACE_RUNTIME_PROFILE
            ):
                raise RuntimeRecreationUnavailable(
                    code="operation_not_found",
                    message="Runtime recreation operation was not found.",
                )
            profile = await self.profile_repository.get_workspace_runtime_profile(
                session,
                workspace_id=workspace_id,
                profile_id=operation.target_id,
                for_update=False,
            )
            if profile is None:
                raise RuntimeRecreationUnavailable(
                    code="operation_not_found",
                    message="Runtime recreation operation was not found.",
                )
            return await self._project_operation(
                session,
                operation=operation,
                offset=offset,
                limit=limit,
            )

    async def _create_operation(
        self,
        session: AsyncSession,
        *,
        target_kind: RuntimeRecreationTargetKind,
        target_id: str,
        concurrency_limit: int,
        actor_user_id: str | None,
        actor_workspace_user_id: str | None,
    ) -> RuntimeRecreationOperation:
        target_version = await self.profile_repository.get_recreation_target_version(
            session,
            target_kind=target_kind,
            target_id=target_id,
            for_share=False,
        )
        if target_version is None:
            raise AssertionError("Locked Runtime recreation target disappeared.")
        operation = await self.profile_repository.create_recreation_operation(
            session,
            target_kind=target_kind,
            target_id=target_id,
            target_version=target_version,
            concurrency_limit=concurrency_limit,
            actor_user_id=actor_user_id,
            actor_workspace_user_id=actor_workspace_user_id,
        )
        items = await self.profile_repository.list_recreation_target_items(
            session,
            target_kind=target_kind,
            target_id=target_id,
        )
        if items:
            await self.profile_repository.add_recreation_items(
                session,
                operation_id=operation.id,
                items=items,
            )
        else:
            await self.profile_repository.complete_empty_recreation_operation(
                session,
                operation_id=operation.id,
            )
        persisted = await self.profile_repository.get_recreation_operation(
            session,
            operation_id=operation.id,
        )
        if persisted is None:
            raise AssertionError("Created Runtime recreation operation disappeared.")
        return persisted

    async def _project_operation(
        self,
        session: AsyncSession,
        *,
        operation: RuntimeRecreationOperation,
        offset: int,
        limit: int,
    ) -> RuntimeRecreationProjection:
        items = await self.profile_repository.list_recreation_items(
            session,
            operation_id=operation.id,
            offset=offset,
            limit=limit,
            statuses=(
                RuntimeRecreationItemStatus.SKIPPED,
                RuntimeRecreationItemStatus.FAILED,
            ),
        )
        return RuntimeRecreationProjection(
            operation=operation,
            items=tuple(items),
        )


@dataclasses.dataclass(frozen=True)
class RuntimeRecreationReconcileResult:
    """One bounded recreation reconciliation result."""

    operations: int
    processed_items: int
    dispatched_items: int
    completed_items: int


@dataclasses.dataclass
class RuntimeRecreationReconciler:
    """Dispatch and observe durable generation-fenced recreation items."""

    session_manager: SessionManager[AsyncSession]
    profile_repository: RuntimeProfileRepository
    runtime_repository: AgentRuntimeRepository
    agent_repository: AgentRepository
    operation_limit: int = _DEFAULT_OPERATION_LIMIT
    item_limit: int = _DEFAULT_ITEM_LIMIT
    maximum_attempts: int = _DEFAULT_MAXIMUM_ATTEMPTS

    async def reconcile_once(self) -> RuntimeRecreationReconcileResult:
        """Advance one bounded batch of active recreation operations."""
        async with self.session_manager() as session:
            operation_ids = (
                await self.profile_repository.list_active_recreation_operation_ids(
                    session,
                    limit=self.operation_limit,
                )
            )
        processed = 0
        dispatched = 0
        completed = 0
        for operation_id in operation_ids:
            async with self.session_manager() as session:
                running = await self.profile_repository.list_recreation_items(
                    session,
                    operation_id=operation_id,
                    offset=0,
                    limit=self.item_limit,
                    statuses=(RuntimeRecreationItemStatus.RUNNING,),
                )
            for item in running:
                item_dispatched, item_completed = await self._process_item(item)
                processed += 1
                dispatched += int(item_dispatched)
                completed += int(item_completed)
            async with self.session_manager() as session:
                claimed = await self.profile_repository.claim_recreation_items(
                    session,
                    operation_id=operation_id,
                    limit=self.item_limit,
                )
            for item in claimed:
                item_dispatched, item_completed = await self._process_item(item)
                processed += 1
                dispatched += int(item_dispatched)
                completed += int(item_completed)
        return RuntimeRecreationReconcileResult(
            operations=len(operation_ids),
            processed_items=processed,
            dispatched_items=dispatched,
            completed_items=completed,
        )

    async def _process_item(
        self,
        item: RuntimeRecreationOperationItem,
    ) -> tuple[bool, bool]:
        async with self.session_manager() as session:
            locked_item = await self.profile_repository.lock_recreation_item(
                session,
                item_id=item.id,
                expected_attempt=item.attempt,
            )
            if locked_item is None:
                return False, False
            item = locked_item
            operation = await self.profile_repository.get_recreation_operation(
                session,
                operation_id=item.operation_id,
            )
            runtime = await self.runtime_repository.get_by_id(session, item.runtime_id)
            if operation is None or runtime is None:
                return False, await self.profile_repository.finish_recreation_item(
                    session,
                    item_id=item.id,
                    expected_attempt=item.attempt,
                    status=RuntimeRecreationItemStatus.FAILED,
                    failure_code="runtime_not_found",
                    failure_message="The Runtime recreation target no longer exists.",
                )
            if not _runtime_matches_target(runtime, operation):
                return False, await self.profile_repository.finish_recreation_item(
                    session,
                    item_id=item.id,
                    expected_attempt=item.attempt,
                    status=RuntimeRecreationItemStatus.SKIPPED,
                    failure_code="target_no_longer_matches",
                    failure_message="The Runtime no longer belongs to this target.",
                )
            if runtime.terminal_delete_requested_generation is not None:
                return False, await self.profile_repository.finish_recreation_item(
                    session,
                    item_id=item.id,
                    expected_attempt=item.attempt,
                    status=RuntimeRecreationItemStatus.SKIPPED,
                    failure_code="terminal_delete_requested",
                    failure_message="The Runtime is being terminally deleted.",
                )
            if runtime.desired_state is not RuntimeDesiredState.RUNNING:
                return False, await self.profile_repository.finish_recreation_item(
                    session,
                    item_id=item.id,
                    expected_attempt=item.attempt,
                    status=RuntimeRecreationItemStatus.SKIPPED,
                    failure_code="runtime_not_running",
                    failure_message=(
                        "A stopped Runtime adopts the latest Profile on start."
                    ),
                )
            desired_revision_id = runtime.desired_runtime_configuration_revision_id
            if desired_revision_id is None:
                return False, await self.profile_repository.finish_recreation_item(
                    session,
                    item_id=item.id,
                    expected_attempt=item.attempt,
                    status=RuntimeRecreationItemStatus.FAILED,
                    failure_code="configuration_missing",
                    failure_message=(
                        "The Runtime has no desired configuration revision."
                    ),
                )
            if item.dispatched_generation is not None:
                if (
                    runtime.applied_runtime_configuration_revision_id
                    == item.expected_configuration_revision_id
                ):
                    return (
                        False,
                        await self.profile_repository.finish_recreation_item(
                            session,
                            item_id=item.id,
                            expected_attempt=item.attempt,
                            status=RuntimeRecreationItemStatus.SUCCEEDED,
                            failure_code=None,
                            failure_message=None,
                        ),
                    )
                if runtime.failure_generation == item.dispatched_generation:
                    retried = await self.profile_repository.retry_recreation_item(
                        session,
                        item_id=item.id,
                        expected_attempt=item.attempt,
                        maximum_attempts=self.maximum_attempts,
                        failure_code=runtime.failure_code or "recreation_failed",
                        failure_message=(
                            runtime.failure_message or "Runtime recreation failed."
                        ),
                    )
                    return False, retried and item.attempt >= self.maximum_attempts
                if (
                    runtime.desired_generation == item.dispatched_generation
                    and desired_revision_id == item.expected_configuration_revision_id
                ):
                    return False, False
                return False, await self.profile_repository.finish_recreation_item(
                    session,
                    item_id=item.id,
                    expected_attempt=item.attempt,
                    status=RuntimeRecreationItemStatus.SKIPPED,
                    failure_code="recreation_dispatch_superseded",
                    failure_message=(
                        "The Runtime target changed after recreation dispatch."
                    ),
                )
            agent = await self.agent_repository.lock_by_id(session, runtime.agent_id)
            if (
                agent is None
                or agent.runtime_capability is not AgentRuntimeCapability.MANAGED
            ):
                return False, await self.profile_repository.finish_recreation_item(
                    session,
                    item_id=item.id,
                    expected_attempt=item.attempt,
                    status=RuntimeRecreationItemStatus.SKIPPED,
                    failure_code="runtime_capability_unavailable",
                    failure_message=("The Agent no longer permits Runtime recreation."),
                )
            target_version = (
                await self.profile_repository.get_recreation_target_version(
                    session,
                    target_kind=operation.target_kind,
                    target_id=operation.target_id,
                    for_share=True,
                )
            )
            if target_version != operation.target_version:
                return False, await self.profile_repository.finish_recreation_item(
                    session,
                    item_id=item.id,
                    expected_attempt=item.attempt,
                    status=RuntimeRecreationItemStatus.SKIPPED,
                    failure_code="target_version_changed",
                    failure_message=(
                        "The recreation target changed after operation creation."
                    ),
                )
            if desired_revision_id != item.expected_configuration_revision_id:
                return False, await self.profile_repository.finish_recreation_item(
                    session,
                    item_id=item.id,
                    expected_attempt=item.attempt,
                    status=RuntimeRecreationItemStatus.SKIPPED,
                    failure_code="configuration_target_changed",
                    failure_message=(
                        "The Runtime configuration changed after target snapshot."
                    ),
                )
            desired = await self.profile_repository.get_configuration_revision(
                session,
                revision_id=desired_revision_id,
            )
            if (
                desired is None
                or desired.resolution_status
                is not RuntimeConfigurationResolutionStatus.READY
                or desired.resolved_configuration is None
            ):
                return False, await self.profile_repository.finish_recreation_item(
                    session,
                    item_id=item.id,
                    expected_attempt=item.attempt,
                    status=RuntimeRecreationItemStatus.SKIPPED,
                    failure_code="configuration_blocked",
                    failure_message="The latest Runtime configuration is not ready.",
                )
            command = await self.runtime_repository.set_desired_state_if_ready(
                session,
                runtime.id,
                RuntimeLifecycleCommandType.RESTART,
                RuntimeDesiredState.RUNNING,
                expected_configuration_revision_id=desired_revision_id,
            )
            if command is None:
                retried = await self.profile_repository.retry_recreation_item(
                    session,
                    item_id=item.id,
                    expected_attempt=item.attempt,
                    maximum_attempts=self.maximum_attempts,
                    failure_code="runtime_configuration_changed",
                    failure_message=(
                        "Runtime configuration changed before recreation dispatch."
                    ),
                )
                return False, retried and item.attempt >= self.maximum_attempts
            next_revision_id = command.runtime.desired_runtime_configuration_revision_id
            if next_revision_id is None:
                raise AssertionError("Recreation dispatch lost desired configuration.")
            updated = await self.profile_repository.update_recreation_item_dispatch(
                session,
                item_id=item.id,
                expected_attempt=item.attempt,
                configuration_revision_id=next_revision_id,
                dispatched_generation=command.desired_generation,
            )
            return updated, False


def _runtime_matches_target(
    runtime: AgentRuntime,
    operation: RuntimeRecreationOperation,
) -> bool:
    if operation.target_kind is RuntimeRecreationTargetKind.PROVIDER:
        return runtime.runtime_provider_resource_id == operation.target_id
    if operation.target_kind is RuntimeRecreationTargetKind.INFRASTRUCTURE_PROFILE:
        return runtime.infrastructure_profile_id == operation.target_id
    if operation.target_kind is RuntimeRecreationTargetKind.WORKSPACE_RUNTIME_PROFILE:
        return runtime.workspace_runtime_profile_id == operation.target_id
    raise AssertionError(f"Unsupported recreation target kind: {operation.target_kind}")
