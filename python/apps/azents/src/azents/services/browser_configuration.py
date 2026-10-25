"""Reconcile Agent browser intent with the exact current Runner, without allocation."""

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated

from azcommon.result import Failure, Result, Success
from azents_runtime_control.browser_configuration import (
    BROWSER_CONFIGURATION_CAPABILITY,
    BrowserConfigurationRequest,
    BrowserConfigurationStatus,
    BrowserImplementation,
)
from fastapi import Depends
from pydantic import BaseModel, ConfigDict, StrictStr, ValidationError

from azents.core.browser_configuration import (
    AgentBrowserConfiguration,
    BrowserApplicationClaim,
    BrowserConfigurationDenial,
)
from azents.core.enums import WorkspaceUserRole
from azents.repos.browser_configuration import BrowserConfigurationRepository
from azents.runtime.control_protocol.runner_operations import (
    RuntimeRunnerOperationClient,
    RuntimeRunnerOperationFailedError,
    RuntimeRunnerOperationGenerationError,
    RuntimeRunnerOperationUnavailable,
)
from azents.runtime.coordination.data import RuntimeConnectionKind
from azents.runtime.coordination.store import RuntimeCoordinationStore
from azents.runtime.deps import (
    get_runtime_coordination_store,
    get_runtime_runner_operation_client,
)
from azents.services.agent import AgentService
from azents.services.agent.data import PrivateAgentAccessDenied

logger = logging.getLogger(__name__)


class _RunnerBrowserCapabilities(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True, hide_input_in_errors=True)
    capabilities: list[StrictStr]


@dataclass
class BrowserConfigurationCoordinator:
    repository: Annotated[
        BrowserConfigurationRepository, Depends(BrowserConfigurationRepository)
    ]
    runner: Annotated[
        RuntimeRunnerOperationClient, Depends(get_runtime_runner_operation_client)
    ]
    coordination: Annotated[
        RuntimeCoordinationStore, Depends(get_runtime_coordination_store)
    ]

    async def reconcile_runtime(self, runtime_id: str, runner_generation: int) -> None:
        agent_id = await self.repository.agent_for_runtime(
            runtime_id, runner_generation
        )
        if agent_id is not None:
            await self.apply_once(agent_id)

    async def apply_once(self, agent_id: str | None) -> bool:
        now = datetime.now(UTC)
        claim = await self.repository.claim_due(
            agent_id=agent_id, now=now, lease_until=now + timedelta(minutes=2)
        )
        if claim is None:
            return False
        try:
            await self._apply(claim)
        except asyncio.CancelledError:
            raise
        except (
            RuntimeRunnerOperationUnavailable,
            RuntimeRunnerOperationGenerationError,
            RuntimeRunnerOperationFailedError,
            TimeoutError,
        ):
            # A lost result is reconciled by querying this same current intent;
            # no website action or already-correct browser is restarted.
            logger.warning(
                "Browser application will reconcile after control loss",
                exc_info=True,
                extra={"agent_id": claim.agent_id, "intent_id": claim.intent_id},
            )
            await self.repository.defer(claim, datetime.now(UTC))
        return True

    async def _apply(self, claim: BrowserApplicationClaim) -> None:
        connection = await self.coordination.get_connection(
            kind=RuntimeConnectionKind.RUNNER, subject_id=claim.runtime_id
        )
        if (
            connection is None
            or connection.generation != claim.runner_generation
            or connection.expires_at <= datetime.now(UTC)
        ):
            await self.repository.defer(claim, datetime.now(UTC))
            return
        try:
            capabilities = _RunnerBrowserCapabilities.model_validate(
                connection.metadata
            )
        except ValidationError:
            supported = False
        else:
            supported = BROWSER_CONFIGURATION_CAPABILITY in capabilities.capabilities
        if not supported:
            await self.repository.finish(
                claim,
                BrowserConfigurationStatus(
                    claim.intent_id,
                    claim.implementation,
                    "failed",
                    "browser_configuration_unsupported",
                ),
                datetime.now(UTC),
            )
            return
        status = await self.runner.browser_configuration_control(
            runtime_id=claim.runtime_id,
            runner_generation=claim.runner_generation,
            request=None,
            deadline_at=datetime.now(UTC) + timedelta(seconds=15),
        )
        if not await self.repository.claim_current(claim, datetime.now(UTC)):
            return
        if status.intent_id == claim.intent_id:
            if status.implementation != claim.implementation:
                status = BrowserConfigurationStatus(
                    claim.intent_id,
                    claim.implementation,
                    "failed",
                    "browser_configuration_conflict",
                )
            elif status.state == "applying":
                await self.repository.defer(claim, datetime.now(UTC))
                return
        else:
            status = await self.runner.browser_configuration_control(
                runtime_id=claim.runtime_id,
                runner_generation=claim.runner_generation,
                request=BrowserConfigurationRequest(
                    claim.intent_id, status.intent_id, claim.implementation
                ),
                deadline_at=datetime.now(UTC) + timedelta(seconds=60),
            )
        if not await self.repository.finish(claim, status, datetime.now(UTC)):
            await self.repository.defer(claim, datetime.now(UTC))

    async def reconcile_once(self, deadline: datetime) -> int:
        count = 0
        while count < 100 and datetime.now(UTC) + timedelta(seconds=75) < deadline:
            if not await self.apply_once(None):
                break
            count += 1
        return count


@dataclass
class AgentBrowserConfigurationService:
    agents: Annotated[AgentService, Depends(AgentService)]
    repository: Annotated[
        BrowserConfigurationRepository, Depends(BrowserConfigurationRepository)
    ]
    coordinator: Annotated[
        BrowserConfigurationCoordinator, Depends(BrowserConfigurationCoordinator)
    ]
    coordination: Annotated[
        RuntimeCoordinationStore, Depends(get_runtime_coordination_store)
    ]

    async def read(
        self,
        *,
        agent_id: str,
        workspace_id: str,
        workspace_user_id: str,
        role: WorkspaceUserRole,
    ) -> Result[AgentBrowserConfiguration, BrowserConfigurationDenial]:
        admitted = await self.agents.get_by_id(
            agent_id,
            workspace_id=workspace_id,
            workspace_user_id=workspace_user_id,
            role=role,
        )
        if not admitted.success:
            return Failure(
                BrowserConfigurationDenial.ADMIN_REQUIRED
                if isinstance(admitted.error, PrivateAgentAccessDenied)
                else BrowserConfigurationDenial.NOT_FOUND
            )
        configuration = await self.repository.read(agent_id)
        if configuration is None:
            return Failure(BrowserConfigurationDenial.NOT_FOUND)
        return Success(await self._live(configuration))

    async def replace(
        self,
        *,
        agent_id: str,
        workspace_id: str,
        workspace_user_id: str,
        expected_intent_id: str,
        implementation: BrowserImplementation,
        retry: bool,
    ) -> Result[AgentBrowserConfiguration, BrowserConfigurationDenial]:
        result = await self.repository.replace(
            agent_id=agent_id,
            workspace_id=workspace_id,
            workspace_user_id=workspace_user_id,
            expected_intent_id=expected_intent_id,
            implementation=implementation,
            retry=retry,
            now=datetime.now(UTC),
        )
        if not result.success:
            return result
        await self.coordinator.apply_once(agent_id)
        current = await self.repository.read(agent_id)
        return (
            Success(await self._live(current))
            if current is not None
            else Failure(BrowserConfigurationDenial.NOT_FOUND)
        )

    async def _live(
        self, configuration: AgentBrowserConfiguration
    ) -> AgentBrowserConfiguration:
        if configuration.runtime_id is None:
            return configuration
        connection = await self.coordination.get_connection(
            kind=RuntimeConnectionKind.RUNNER, subject_id=configuration.runtime_id
        )
        if (
            connection is None
            or connection.generation != configuration.runner_generation
            or connection.expires_at <= datetime.now(UTC)
        ):
            return configuration.model_copy(
                update={"state": "offline", "applied": None, "reason_code": None}
            )
        return configuration
