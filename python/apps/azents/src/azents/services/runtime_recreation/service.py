"""Runtime recreation orchestration over completed database operations."""

import dataclasses
from typing import Annotated

from fastapi import Depends

from azents.core.runtime_profile import RuntimeInfrastructureProfileKind
from azents.core.runtime_recreation import (
    RuntimeRecreationItemProcessResult,
    RuntimeRecreationProjection,
    RuntimeRecreationReconcileResult,
)
from azents.repos.runtime_profile.data import (
    RuntimeRecreationOperation,
    RuntimeRecreationOperationItem,
)
from azents.repos.runtime_recreation_operations import (
    RuntimeRecreationOperationRepository,
    RuntimeRecreationReconcileOperationRepository,
)
from azents.services.runtime_terminal.invalidation import (
    RuntimeTerminalInvalidationPublisherDependency,
)


@dataclasses.dataclass
class RuntimeRecreationService:
    """Create and inspect recreation operations within authority boundaries."""

    operations: Annotated[
        RuntimeRecreationOperationRepository,
        Depends(RuntimeRecreationOperationRepository),
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
        return await self.operations.create_provider_operation(
            provider_logical_id,
            expected_admin_version=expected_admin_version,
            concurrency_limit=concurrency_limit,
            actor_user_id=actor_user_id,
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
        return await self.operations.create_infrastructure_profile_operation(
            provider_logical_id,
            profile_id,
            profile_kind=profile_kind,
            expected_version=expected_version,
            concurrency_limit=concurrency_limit,
            actor_user_id=actor_user_id,
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
        return await self.operations.create_workspace_profile_operation(
            workspace_id,
            profile_id,
            expected_version=expected_version,
            concurrency_limit=concurrency_limit,
            actor_workspace_user_id=actor_workspace_user_id,
        )

    async def get_platform_operation(
        self, operation_id: str, *, offset: int, limit: int
    ) -> RuntimeRecreationProjection:
        """Return one Platform-authority operation and bounded item details."""
        return await self.operations.get_platform_operation(
            operation_id, offset=offset, limit=limit
        )

    async def get_workspace_operation(
        self, workspace_id: str, operation_id: str, *, offset: int, limit: int
    ) -> RuntimeRecreationProjection:
        """Return an operation only when its target belongs to the Workspace."""
        return await self.operations.get_workspace_operation(
            workspace_id, operation_id, offset=offset, limit=limit
        )


@dataclasses.dataclass
class RuntimeRecreationReconciler:
    """Dispatch and observe durable generation-fenced recreation items."""

    operations: RuntimeRecreationReconcileOperationRepository
    terminal_invalidation_publisher: RuntimeTerminalInvalidationPublisherDependency
    operation_limit: int = 20
    item_limit: int = 100

    async def reconcile_once(self) -> RuntimeRecreationReconcileResult:
        """Advance one bounded batch of active recreation operations."""
        operation_ids = await self.operations.list_active(limit=self.operation_limit)
        processed = 0
        dispatched = 0
        completed = 0
        for operation_id in operation_ids:
            running = await self.operations.list_running(
                operation_id=operation_id, limit=self.item_limit
            )
            for item in running:
                item_result = await self._process_item(item)
                processed += 1
                dispatched += int(item_result.dispatched)
                completed += int(item_result.completed)
            claimed = await self.operations.claim(
                operation_id=operation_id, limit=self.item_limit
            )
            for item in claimed:
                item_result = await self._process_item(item)
                processed += 1
                dispatched += int(item_result.dispatched)
                completed += int(item_result.completed)
        return RuntimeRecreationReconcileResult(
            operations=len(operation_ids),
            processed_items=processed,
            dispatched_items=dispatched,
            completed_items=completed,
        )

    async def _process_item(
        self, item: RuntimeRecreationOperationItem
    ) -> RuntimeRecreationItemProcessResult:
        result = await self.operations.process_item(item)
        if result.invalidated_runtime_id is not None:
            publisher = self.terminal_invalidation_publisher
            await publisher.publish_runtime_terminal_invalidation(
                result.invalidated_runtime_id
            )
        return result
