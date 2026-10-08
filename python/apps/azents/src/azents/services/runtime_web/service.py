"""Agent-scoped Runtime Web orchestration over completed repository operations."""

from typing import Annotated, assert_never

from azcommon.result import Failure, Result, Success
from fastapi import Depends

from azents.core.enums import WorkspaceUserRole
from azents.repos.runtime_web.operation_data import (
    RuntimeWebCommandIdentity,
    RuntimeWebObservedService,
    RuntimeWebOperationCode,
    RuntimeWebOperationError,
)
from azents.repos.runtime_web.operations import (
    RuntimeWebOperationsRepository,
    get_runtime_web_operations_repository,
)
from azents.services.runtime_web.data import (
    RuntimeWebAccessDenied,
    RuntimeWebActor,
    RuntimeWebCapabilityUnavailable,
    RuntimeWebConfigurationUnavailable,
    RuntimeWebConflict,
    RuntimeWebError,
    RuntimeWebNotFound,
    RuntimeWebOperation,
    RuntimeWebQuotaExceeded,
    RuntimeWebServicePage,
    RuntimeWebServiceProjection,
)
from azents.services.runtime_web.service_url import (
    RuntimeWebServiceUrlResolver,
    get_runtime_web_service_url_resolver,
)


class RuntimeWebService:
    """Project completed database decisions without retaining a live session."""

    def __init__(
        self,
        *,
        operations: RuntimeWebOperationsRepository,
        url_resolver: RuntimeWebServiceUrlResolver,
    ) -> None:
        self.operations = operations
        self.url_resolver = url_resolver

    async def create_service(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        user_id: str,
        workspace_user_id: str,
        role: WorkspaceUserRole,
        port: int,
        label: str | None,
        selected_duration_seconds: int,
        turn_on: bool,
        actor: RuntimeWebActor,
        operation: RuntimeWebOperation,
    ) -> Result[RuntimeWebServiceProjection, RuntimeWebError]:
        """Create one user-managed service."""
        result = await self.operations.create_service(
            workspace_id=workspace_id,
            agent_id=agent_id,
            user_id=user_id,
            workspace_user_id=workspace_user_id,
            role=role,
            port=port,
            label=label,
            selected_duration_seconds=selected_duration_seconds,
            turn_on=turn_on,
            operation=_command_identity(actor, operation),
        )
        if isinstance(result, Failure):
            return Failure(_service_error(result.error))
        return Success(self._projection(result.value))

    async def request_service(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        port: int,
        label: str | None,
        actor: RuntimeWebActor,
        operation: RuntimeWebOperation,
    ) -> Result[RuntimeWebServiceProjection, RuntimeWebError]:
        """Create a missing Off service or return the existing row unchanged."""
        result = await self.operations.request_service(
            workspace_id=workspace_id,
            agent_id=agent_id,
            port=port,
            label=label,
            operation=_command_identity(actor, operation),
        )
        if isinstance(result, Failure):
            return Failure(_service_error(result.error))
        return Success(self._projection(result.value))

    async def update_service(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        service_id: str,
        user_id: str,
        workspace_user_id: str,
        role: WorkspaceUserRole,
        expected_revision: int,
        label_present: bool,
        label: str | None,
        selected_duration_seconds: int | None,
        actor: RuntimeWebActor,
        operation: RuntimeWebOperation,
    ) -> Result[RuntimeWebServiceProjection, RuntimeWebError]:
        """Update service label or selected duration."""
        result = await self.operations.update_service(
            workspace_id=workspace_id,
            agent_id=agent_id,
            service_id=service_id,
            user_id=user_id,
            workspace_user_id=workspace_user_id,
            role=role,
            expected_revision=expected_revision,
            label_present=label_present,
            label=label,
            selected_duration_seconds=selected_duration_seconds,
            operation=_command_identity(actor, operation),
        )
        if isinstance(result, Failure):
            return Failure(_service_error(result.error))
        return Success(self._projection(result.value))

    async def turn_on(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        service_id: str,
        user_id: str,
        workspace_user_id: str,
        role: WorkspaceUserRole,
        expected_revision: int,
        selected_duration_seconds: int | None,
        actor: RuntimeWebActor,
        operation: RuntimeWebOperation,
    ) -> Result[RuntimeWebServiceProjection, RuntimeWebError]:
        """Turn an Off service On."""
        result = await self.operations.turn_on(
            workspace_id=workspace_id,
            agent_id=agent_id,
            service_id=service_id,
            user_id=user_id,
            workspace_user_id=workspace_user_id,
            role=role,
            expected_revision=expected_revision,
            selected_duration_seconds=selected_duration_seconds,
            operation=_command_identity(actor, operation),
        )
        if isinstance(result, Failure):
            return Failure(_service_error(result.error))
        return Success(self._projection(result.value))

    async def turn_off(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        service_id: str,
        user_id: str,
        workspace_user_id: str,
        role: WorkspaceUserRole,
        expected_revision: int,
        actor: RuntimeWebActor,
        operation: RuntimeWebOperation,
    ) -> Result[RuntimeWebServiceProjection, RuntimeWebError]:
        """Turn one exact service Off."""
        result = await self.operations.turn_off(
            workspace_id=workspace_id,
            agent_id=agent_id,
            service_id=service_id,
            user_id=user_id,
            workspace_user_id=workspace_user_id,
            role=role,
            expected_revision=expected_revision,
            operation=_command_identity(actor, operation),
        )
        if isinstance(result, Failure):
            return Failure(_service_error(result.error))
        return Success(self._projection(result.value))

    async def reset_expiration(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        service_id: str,
        user_id: str,
        workspace_user_id: str,
        role: WorkspaceUserRole,
        expected_revision: int,
        actor: RuntimeWebActor,
        operation: RuntimeWebOperation,
    ) -> Result[RuntimeWebServiceProjection, RuntimeWebError]:
        """Restart one current service exposure window."""
        result = await self.operations.reset_expiration(
            workspace_id=workspace_id,
            agent_id=agent_id,
            service_id=service_id,
            user_id=user_id,
            workspace_user_id=workspace_user_id,
            role=role,
            expected_revision=expected_revision,
            operation=_command_identity(actor, operation),
        )
        if isinstance(result, Failure):
            return Failure(_service_error(result.error))
        return Success(self._projection(result.value))

    async def delete_service(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        service_id: str,
        user_id: str,
        workspace_user_id: str,
        role: WorkspaceUserRole,
        expected_revision: int,
        actor: RuntimeWebActor,
        operation: RuntimeWebOperation,
    ) -> Result[bool, RuntimeWebError]:
        """Delete one exact service after Agent authorization."""
        result = await self.operations.delete_service(
            workspace_id=workspace_id,
            agent_id=agent_id,
            service_id=service_id,
            user_id=user_id,
            workspace_user_id=workspace_user_id,
            role=role,
            expected_revision=expected_revision,
            operation=_command_identity(actor, operation),
        )
        if isinstance(result, Failure):
            return Failure(_service_error(result.error))
        return Success(result.value)

    async def close_service(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        service_id: str,
        actor: RuntimeWebActor,
        operation: RuntimeWebOperation,
    ) -> Result[RuntimeWebServiceProjection, RuntimeWebError]:
        """Idempotently turn one exact service Off for an Agent caller."""
        result = await self.operations.close_service(
            workspace_id=workspace_id,
            agent_id=agent_id,
            service_id=service_id,
            operation=_command_identity(actor, operation),
        )
        if isinstance(result, Failure):
            return Failure(_service_error(result.error))
        return Success(self._projection(result.value))

    async def get_service(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        service_id: str,
        user_id: str,
        workspace_user_id: str,
        role: WorkspaceUserRole,
    ) -> Result[RuntimeWebServiceProjection, RuntimeWebError]:
        """Get one current service through an Agent-nested route."""
        result = await self.operations.get_service(
            workspace_id=workspace_id,
            agent_id=agent_id,
            service_id=service_id,
            user_id=user_id,
            workspace_user_id=workspace_user_id,
            role=role,
        )
        if isinstance(result, Failure):
            return Failure(_service_error(result.error))
        return Success(self._projection(result.value))

    async def get_service_by_id_for_user(
        self,
        *,
        service_id: str,
        user_id: str,
    ) -> Result[RuntimeWebServiceProjection, RuntimeWebError]:
        """Get one authorized service by opaque ID for trusted Main Web."""
        result = await self.operations.get_service_by_id_for_user(
            service_id=service_id,
            user_id=user_id,
        )
        if isinstance(result, Failure):
            return Failure(_service_error(result.error))
        return Success(self._projection(result.value))

    async def turn_on_by_id_for_user(
        self,
        *,
        service_id: str,
        user_id: str,
        expected_revision: int,
        selected_duration_seconds: int,
        actor: RuntimeWebActor,
        operation: RuntimeWebOperation,
    ) -> Result[RuntimeWebServiceProjection, RuntimeWebError]:
        """Turn On through the trusted service URL activation surface."""
        result = await self.operations.turn_on_by_id_for_user(
            service_id=service_id,
            user_id=user_id,
            expected_revision=expected_revision,
            selected_duration_seconds=selected_duration_seconds,
            operation=_command_identity(actor, operation),
        )
        if isinstance(result, Failure):
            return Failure(_service_error(result.error))
        return Success(self._projection(result.value))

    async def list_services(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        user_id: str | None,
        workspace_user_id: str | None,
        role: WorkspaceUserRole | None,
        offset: int,
        limit: int,
        actor: RuntimeWebActor | None,
    ) -> Result[RuntimeWebServicePage, RuntimeWebError]:
        """List current services for one Agent."""
        result = await self.operations.list_services(
            workspace_id=workspace_id,
            agent_id=agent_id,
            user_id=user_id,
            workspace_user_id=workspace_user_id,
            role=role,
            offset=offset,
            limit=limit,
            operation=(
                _command_identity(actor, RuntimeWebOperation(operation_key="list"))
                if actor is not None
                else None
            ),
        )
        if isinstance(result, Failure):
            return Failure(_service_error(result.error))
        return Success(
            RuntimeWebServicePage(
                items=[self._projection(item) for item in result.value.items],
                total_count=result.value.total_count,
            )
        )

    def _projection(
        self, observation: RuntimeWebObservedService
    ) -> RuntimeWebServiceProjection:
        return RuntimeWebServiceProjection.from_record(
            observation.record,
            url=self.url_resolver.resolve(observation.record.hostname_key),
            observed_at=observation.observed_at,
        )


def _service_error(error: RuntimeWebOperationError) -> RuntimeWebError:
    match error.code:
        case RuntimeWebOperationCode.NOT_FOUND:
            return RuntimeWebNotFound()
        case RuntimeWebOperationCode.ACCESS_DENIED:
            return RuntimeWebAccessDenied()
        case RuntimeWebOperationCode.CONFLICT:
            return RuntimeWebConflict()
        case RuntimeWebOperationCode.QUOTA_EXCEEDED:
            assert error.scope is not None
            return RuntimeWebQuotaExceeded(scope=error.scope)
        case RuntimeWebOperationCode.CONFIGURATION_UNAVAILABLE:
            return RuntimeWebConfigurationUnavailable()
        case RuntimeWebOperationCode.CAPABILITY_UNAVAILABLE:
            return RuntimeWebCapabilityUnavailable()
        case _ as unreachable:
            assert_never(unreachable)


def get_runtime_web_service(
    operations: Annotated[
        RuntimeWebOperationsRepository,
        Depends(get_runtime_web_operations_repository),
    ],
    url_resolver: Annotated[
        RuntimeWebServiceUrlResolver,
        Depends(get_runtime_web_service_url_resolver),
    ],
) -> RuntimeWebService:
    """Create the Runtime Web domain service."""
    return RuntimeWebService(
        operations=operations,
        url_resolver=url_resolver,
    )


def _command_identity(
    actor: RuntimeWebActor, operation: RuntimeWebOperation
) -> RuntimeWebCommandIdentity:
    return RuntimeWebCommandIdentity(
        actor_kind=actor.kind,
        actor_id=actor.actor_id,
        execution_id=actor.execution_id,
        operation_key=operation.operation_key,
    )
