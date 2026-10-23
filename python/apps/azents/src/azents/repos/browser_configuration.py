"""Atomic Agent browser intent, leased application work and admission evidence."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Annotated

import sqlalchemy as sa
from azcommon.result import Failure, Result, Success
from azcommon.uuid import uuid7
from azents_runtime_control.browser_configuration import (
    BrowserConfigurationStatus,
    BrowserImplementation,
)
from fastapi import Depends
from sqlalchemy.orm.attributes import flag_modified

from azents.core.browser_configuration import (
    AgentBrowserApplicationState,
    AgentBrowserConfiguration,
    BrowserApplicationClaim,
    BrowserConfigurationDenial,
)
from azents.core.enums import (
    AgentLifecycleStatus,
    AgentRuntimeCapability,
    RuntimeDesiredState,
    RuntimeProviderObservedState,
    RuntimeRunnerState,
    WorkspaceUserRole,
)
from azents.rdb.deps import get_read_only_session_manager, get_session_manager
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_admin import RDBAgentAdmin
from azents.rdb.models.agent_runtime import RDBAgentRuntime
from azents.rdb.models.workspace_user import RDBWorkspaceUser
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import ReadSession, WriteSession
from azents.repos.runtime_profile.repository import RuntimeProfileRepository


@dataclass
class BrowserConfigurationRepository:
    read_session_manager: Annotated[
        SessionManager[ReadSession], Depends(get_read_only_session_manager)
    ]
    session_manager: Annotated[
        SessionManager[WriteSession], Depends(get_session_manager)
    ]
    profile_repository: Annotated[
        RuntimeProfileRepository, Depends(RuntimeProfileRepository)
    ]

    async def _runtime_current(
        self, session: ReadSession, runtime: RDBAgentRuntime | None
    ) -> bool:
        if (
            runtime is None
            or runtime.desired_state is not RuntimeDesiredState.RUNNING
            or runtime.terminal_delete_requested_generation is not None
            or runtime.provider_observed_state
            is not RuntimeProviderObservedState.RUNNING
            or runtime.provider_observed_generation != runtime.desired_generation
            or runtime.runner_state is not RuntimeRunnerState.READY
            or runtime.runner_generation <= 0
        ):
            return False
        configuration = await self.profile_repository.get_configuration_state(
            session, runtime_id=runtime.id
        )
        return (
            configuration is not None
            and configuration.applied is not None
            and configuration.applied.target_generation == runtime.desired_generation
            and configuration.applied.sequence == runtime.configuration_sequence
        )

    async def _projection(
        self, session: ReadSession, agent: RDBAgent
    ) -> AgentBrowserConfiguration:
        runtime = (
            await session.read_session.execute(
                sa.select(RDBAgentRuntime).where(RDBAgentRuntime.agent_id == agent.id)
            )
        ).scalar_one_or_none()
        current = (
            agent.lifecycle_status is AgentLifecycleStatus.ACTIVE
            and agent.runtime_capability is AgentRuntimeCapability.MANAGED
            and await self._runtime_current(session, runtime)
        )
        if not current or runtime is None:
            state = "offline"
        elif (
            agent.browser_observed_runtime_id != runtime.id
            or agent.browser_observed_runner_generation != runtime.runner_generation
        ):
            state = "applying"
        else:
            state = agent.browser_application_state.value
        return AgentBrowserConfiguration(
            agent_id=agent.id,
            intent_id=agent.browser_configuration_intent_id,
            requested=agent.browser_implementation,
            applied=agent.browser_implementation if state == "ready" else None,
            state=state,
            reason_code=agent.browser_application_reason if state == "failed" else None,
            runtime_id=runtime.id if current and runtime is not None else None,
            runner_generation=runtime.runner_generation
            if current and runtime is not None
            else None,
        )

    async def read(self, agent_id: str) -> AgentBrowserConfiguration | None:
        async with self.read_session_manager() as session:
            agent = await session.read_session.get(RDBAgent, agent_id)
            return None if agent is None else await self._projection(session, agent)

    async def replace(
        self,
        *,
        agent_id: str,
        workspace_id: str,
        workspace_user_id: str,
        expected_intent_id: str,
        implementation: BrowserImplementation,
        retry: bool,
        now: datetime,
    ) -> Result[AgentBrowserConfiguration, BrowserConfigurationDenial]:
        async with self.session_manager() as session:
            agent = (
                await session.write_session.execute(
                    sa.select(RDBAgent).where(RDBAgent.id == agent_id).with_for_update()
                )
            ).scalar_one_or_none()
            if agent is None or agent.workspace_id != workspace_id:
                return Failure(BrowserConfigurationDenial.NOT_FOUND)
            member = (
                await session.write_session.execute(
                    sa.select(RDBWorkspaceUser)
                    .where(
                        RDBWorkspaceUser.id == workspace_user_id,
                        RDBWorkspaceUser.workspace_id == workspace_id,
                    )
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if member is None:
                return Failure(BrowserConfigurationDenial.ADMIN_REQUIRED)
            admin = (
                await session.write_session.execute(
                    sa.select(RDBAgentAdmin.id)
                    .where(
                        RDBAgentAdmin.agent_id == agent_id,
                        RDBAgentAdmin.workspace_user_id == workspace_user_id,
                    )
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if member.role is not WorkspaceUserRole.OWNER and admin is None:
                return Failure(BrowserConfigurationDenial.ADMIN_REQUIRED)
            if (
                agent.lifecycle_status is not AgentLifecycleStatus.ACTIVE
                or agent.runtime_capability is AgentRuntimeCapability.REMOVING
            ):
                return Failure(BrowserConfigurationDenial.AGENT_INACTIVE)
            if agent.browser_configuration_intent_id != expected_intent_id:
                return Failure(BrowserConfigurationDenial.STALE_INTENT)
            if agent.browser_implementation != implementation or (
                retry
                and agent.browser_application_state
                is AgentBrowserApplicationState.FAILED
            ):
                agent.browser_implementation = implementation
                agent.browser_configuration_intent_id = uuid7().hex
                agent.browser_application_state = AgentBrowserApplicationState.APPLYING
                agent.browser_observed_runtime_id = None
                agent.browser_observed_runner_generation = None
                agent.browser_application_reason = None
                agent.browser_application_claim_id = None
                agent.browser_application_lease_until = None
                agent.browser_application_next_at = now
            _retain_agent_policy_evidence(agent)
            await session.write_session.flush()
            projection = await self._projection(session, agent)
            await session.write_session.commit()
            return Success(projection)

    async def agent_for_runtime(
        self, runtime_id: str, runner_generation: int
    ) -> str | None:
        async with self.read_session_manager() as session:
            return await session.read_session.scalar(
                sa.select(RDBAgentRuntime.agent_id).where(
                    RDBAgentRuntime.id == runtime_id,
                    RDBAgentRuntime.runner_generation == runner_generation,
                )
            )

    async def current_intent(
        self, runtime_id: str, runner_generation: int, *, require_ready: bool
    ) -> str | None:
        async with self.read_session_manager() as session:
            row = (
                await session.read_session.execute(
                    sa.select(RDBAgent, RDBAgentRuntime)
                    .join(RDBAgentRuntime, RDBAgentRuntime.agent_id == RDBAgent.id)
                    .where(RDBAgentRuntime.id == runtime_id)
                )
            ).one_or_none()
            if row is None:
                return None
            agent, runtime = row
            if (
                agent.lifecycle_status is not AgentLifecycleStatus.ACTIVE
                or agent.runtime_capability is not AgentRuntimeCapability.MANAGED
                or runtime.runner_generation != runner_generation
                or not await self._runtime_current(session, runtime)
            ):
                return None
            if require_ready and (
                not agent.browser_enabled
                or agent.browser_application_state
                is not AgentBrowserApplicationState.READY
                or agent.browser_observed_runtime_id != runtime_id
                or agent.browser_observed_runner_generation != runner_generation
            ):
                return None
            return agent.browser_configuration_intent_id

    async def claim_due(
        self, *, agent_id: str | None, now: datetime, lease_until: datetime
    ) -> BrowserApplicationClaim | None:
        async with self.session_manager() as session:
            statement = (
                sa.select(RDBAgent, RDBAgentRuntime)
                .join(RDBAgentRuntime, RDBAgentRuntime.agent_id == RDBAgent.id)
                .where(
                    RDBAgent.lifecycle_status == AgentLifecycleStatus.ACTIVE,
                    RDBAgent.runtime_capability == AgentRuntimeCapability.MANAGED,
                    RDBAgentRuntime.desired_state == RuntimeDesiredState.RUNNING,
                    RDBAgentRuntime.runner_state == RuntimeRunnerState.READY,
                    RDBAgentRuntime.terminal_delete_requested_generation.is_(None),
                    RDBAgentRuntime.runner_generation > 0,
                    RDBAgent.browser_application_next_at <= now,
                    sa.or_(
                        RDBAgent.browser_application_lease_until.is_(None),
                        RDBAgent.browser_application_lease_until <= now,
                    ),
                    sa.or_(
                        RDBAgent.browser_application_state
                        == AgentBrowserApplicationState.APPLYING,
                        RDBAgent.browser_observed_runtime_id.is_distinct_from(
                            RDBAgentRuntime.id
                        ),
                        RDBAgent.browser_observed_runner_generation.is_distinct_from(
                            RDBAgentRuntime.runner_generation
                        ),
                    ),
                )
                .order_by(RDBAgent.browser_application_next_at, RDBAgent.id)
                .limit(100)
                .with_for_update(of=RDBAgent, skip_locked=True)
            )
            if agent_id is not None:
                statement = statement.where(RDBAgent.id == agent_id)
            rows = await session.write_session.execute(statement)
            for agent, runtime in rows:
                if not await self._runtime_current(session, runtime):
                    continue
                claim_id = uuid7().hex
                agent.browser_application_claim_id = claim_id
                agent.browser_application_lease_until = lease_until
                agent.browser_application_next_at = lease_until
                agent.browser_application_state = AgentBrowserApplicationState.APPLYING
                agent.browser_application_reason = None
                _retain_agent_policy_evidence(agent)
                claim = BrowserApplicationClaim(
                    agent.id,
                    agent.browser_configuration_intent_id,
                    agent.browser_implementation,
                    claim_id,
                    runtime.id,
                    runtime.runner_generation,
                    runtime.desired_generation,
                    runtime.configuration_sequence,
                    lease_until,
                )
                await session.write_session.commit()
                return claim
            return None

    async def claim_current(
        self, claim: BrowserApplicationClaim, now: datetime
    ) -> bool:
        async with self.read_session_manager() as session:
            return await self._claim_row(session, claim, now, lock=False) is not None

    async def _claim_row(
        self,
        session: ReadSession,
        claim: BrowserApplicationClaim,
        now: datetime,
        *,
        lock: bool,
    ) -> RDBAgent | None:
        statement = (
            sa.select(RDBAgent, RDBAgentRuntime)
            .join(RDBAgentRuntime, RDBAgentRuntime.agent_id == RDBAgent.id)
            .where(
                RDBAgent.id == claim.agent_id,
                RDBAgent.lifecycle_status == AgentLifecycleStatus.ACTIVE,
                RDBAgent.runtime_capability == AgentRuntimeCapability.MANAGED,
                RDBAgent.browser_configuration_intent_id == claim.intent_id,
                RDBAgent.browser_application_claim_id == claim.claim_id,
                RDBAgent.browser_application_lease_until > now,
                RDBAgentRuntime.id == claim.runtime_id,
                RDBAgentRuntime.runner_generation == claim.runner_generation,
                RDBAgentRuntime.desired_generation == claim.desired_generation,
                RDBAgentRuntime.configuration_sequence == claim.configuration_sequence,
            )
        )
        if lock:
            statement = statement.with_for_update(of=RDBAgent)
        row = (await session.read_session.execute(statement)).one_or_none()
        if row is None:
            return None
        agent, runtime = row
        return agent if await self._runtime_current(session, runtime) else None

    async def finish(
        self,
        claim: BrowserApplicationClaim,
        status: BrowserConfigurationStatus,
        now: datetime,
    ) -> bool:
        if (
            status.intent_id != claim.intent_id
            or status.implementation != claim.implementation
            or status.state not in {"ready", "failed"}
        ):
            return False
        async with self.session_manager() as session:
            agent = await self._claim_row(session, claim, now, lock=True)
            if agent is None:
                return False
            agent.browser_application_state = AgentBrowserApplicationState(status.state)
            agent.browser_observed_runtime_id = claim.runtime_id
            agent.browser_observed_runner_generation = claim.runner_generation
            agent.browser_application_reason = status.reason_code
            agent.browser_application_claim_id = None
            agent.browser_application_lease_until = None
            agent.browser_application_next_at = now
            _retain_agent_policy_evidence(agent)
            await session.write_session.commit()
            return True

    async def defer(self, claim: BrowserApplicationClaim, now: datetime) -> None:
        async with self.session_manager() as session:
            agent = await self._claim_row(session, claim, now, lock=True)
            if agent is None:
                return
            agent.browser_application_claim_id = None
            agent.browser_application_lease_until = None
            agent.browser_application_next_at = now + timedelta(seconds=5)
            _retain_agent_policy_evidence(agent)
            await session.write_session.commit()


def _retain_agent_policy_evidence(agent: RDBAgent) -> None:
    """Keep browser-only writes independent of general Agent policy revocation."""
    # Terminal authority binds Agent.updated_at. Browser state has its own exact
    # intent fence; explicitly retain the loaded timestamp instead of invoking
    # the generic ORM onupdate and revoking unrelated live Terminal attachments.
    flag_modified(agent, "updated_at")
