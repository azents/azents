"""AgentRuntime repository."""

import datetime

import sqlalchemy as sa
from azcommon.uuid import uuid7
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    RuntimeDesiredState,
    RuntimeLifecycleCommandType,
    RuntimeProviderBindingOrigin,
    RuntimeProviderConnectionState,
    RuntimeProviderObservedState,
    RuntimeRunnerState,
)
from azents.core.runtime_profile import RuntimeConfigurationResolutionStatus
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_runtime import RDBAgentRuntime
from azents.rdb.models.runtime_profile import RDBRuntimeConfigurationRevision
from azents.rdb.models.runtime_provider import RDBRuntimeProvider

from .data import (
    AgentRuntime,
    AgentRuntimeCreate,
    AgentRuntimeEnsureResult,
    AgentRuntimeFailurePatch,
    AgentRuntimeLifecycleCommand,
)


class AgentRuntimeRepository:
    """AgentRuntime CRUD repository."""

    async def create(
        self,
        session: AsyncSession,
        create: AgentRuntimeCreate,
    ) -> AgentRuntime:
        """Create AgentRuntime.

        :param session: Database session
        :param create: Create data
        :return: Created AgentRuntime
        """
        rdb = RDBAgentRuntime(
            workspace_id=create.workspace_id,
            agent_id=create.agent_id,
            runtime_provider_id=create.runtime_provider_id,
            runtime_provider_resource_id=create.runtime_provider_resource_id,
            provider_binding_origin=create.provider_binding_origin,
            provider_binding_evidence=create.provider_binding_evidence,
            infrastructure_profile_id=create.infrastructure_profile_id,
            workspace_runtime_profile_id=create.workspace_runtime_profile_id,
            desired_runtime_configuration_revision_id=(
                create.desired_runtime_configuration_revision_id
            ),
            applied_runtime_configuration_revision_id=(
                create.applied_runtime_configuration_revision_id
            ),
        )
        session.add(rdb)
        await session.flush()
        return self._build(rdb)

    async def get_by_id(
        self,
        session: AsyncSession,
        runtime_id: str,
    ) -> AgentRuntime | None:
        """Fetch AgentRuntime by ID."""
        rdb = await session.get(RDBAgentRuntime, runtime_id)
        if rdb is None:
            return None
        return self._build(rdb)

    async def get_by_id_for_update(
        self,
        session: AsyncSession,
        runtime_id: str,
    ) -> AgentRuntime | None:
        """Fetch and lock one Agent Runtime."""
        result = await session.execute(
            sa.select(RDBAgentRuntime)
            .where(RDBAgentRuntime.id == runtime_id)
            .with_for_update()
        )
        rdb = result.scalar_one_or_none()
        return self._build(rdb) if rdb is not None else None

    async def list_policy_convergence_candidates(
        self,
        session: AsyncSession,
        *,
        after_runtime_id: str | None,
        limit: int,
    ) -> list[AgentRuntime]:
        """List bound Runtimes for one bounded policy convergence page."""
        statement = (
            sa.select(RDBAgentRuntime)
            .where(
                RDBAgentRuntime.runtime_provider_resource_id.is_not(None),
                RDBAgentRuntime.terminal_delete_requested_generation.is_(None),
            )
            .order_by(RDBAgentRuntime.id)
            .limit(limit)
        )
        if after_runtime_id is not None:
            statement = statement.where(RDBAgentRuntime.id > after_runtime_id)
        result = await session.execute(statement)
        return [self._build(rdb) for rdb in result.scalars().all()]

    async def get_by_agent_id(
        self,
        session: AsyncSession,
        agent_id: str,
    ) -> AgentRuntime | None:
        """Agent Fetch AgentRuntime by ID."""
        result = await session.execute(
            sa.select(RDBAgentRuntime).where(RDBAgentRuntime.agent_id == agent_id)
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            return None
        return self._build(rdb)

    async def get_by_agent_id_for_update(
        self,
        session: AsyncSession,
        agent_id: str,
    ) -> AgentRuntime | None:
        """Fetch one Agent Runtime while serializing its binding transaction."""
        result = await session.execute(
            sa.select(RDBAgentRuntime)
            .where(RDBAgentRuntime.agent_id == agent_id)
            .with_for_update()
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            return None
        return self._build(rdb)

    async def attach_provider_binding(
        self,
        session: AsyncSession,
        *,
        runtime_id: str,
        provider_logical_id: str,
        provider_resource_id: str,
        binding_origin: RuntimeProviderBindingOrigin,
        binding_evidence: dict[str, object],
    ) -> AgentRuntime | None:
        """Attach or confirm one exact durable Provider binding."""
        result = await session.execute(
            sa.update(RDBAgentRuntime)
            .where(
                RDBAgentRuntime.id == runtime_id,
                sa.or_(
                    RDBAgentRuntime.runtime_provider_id.is_(None),
                    RDBAgentRuntime.runtime_provider_id == provider_logical_id,
                ),
                sa.or_(
                    RDBAgentRuntime.runtime_provider_resource_id.is_(None),
                    RDBAgentRuntime.runtime_provider_resource_id
                    == provider_resource_id,
                ),
            )
            .values(
                runtime_provider_id=provider_logical_id,
                runtime_provider_resource_id=provider_resource_id,
                provider_binding_origin=binding_origin,
                provider_binding_evidence=binding_evidence,
            )
            .returning(RDBAgentRuntime)
        )
        rdb = result.scalar_one_or_none()
        await session.flush()
        return self._build(rdb) if rdb is not None else None

    async def attach_desired_configuration_revision(
        self,
        session: AsyncSession,
        *,
        runtime_id: str,
        expected_revision_id: str | None,
        provider_logical_id: str,
        provider_resource_id: str,
        binding_origin: RuntimeProviderBindingOrigin,
        binding_evidence: dict[str, object],
        infrastructure_profile_id: str,
        workspace_runtime_profile_id: str,
        configuration_revision_id: str,
    ) -> AgentRuntime | None:
        """Attach one desired revision using the prior pointer as a stale fence."""
        prior_matches = (
            RDBAgentRuntime.desired_runtime_configuration_revision_id.is_(None)
            if expected_revision_id is None
            else RDBAgentRuntime.desired_runtime_configuration_revision_id
            == expected_revision_id
        )
        result = await session.execute(
            sa.update(RDBAgentRuntime)
            .where(
                RDBAgentRuntime.id == runtime_id,
                prior_matches,
            )
            .values(
                runtime_provider_id=provider_logical_id,
                runtime_provider_resource_id=provider_resource_id,
                provider_binding_origin=binding_origin,
                provider_binding_evidence=binding_evidence,
                infrastructure_profile_id=infrastructure_profile_id,
                workspace_runtime_profile_id=workspace_runtime_profile_id,
                desired_runtime_configuration_revision_id=(configuration_revision_id),
                updated_at=sa.func.now(),
            )
            .returning(RDBAgentRuntime)
        )
        rdb = result.scalar_one_or_none()
        await session.flush()
        return self._build(rdb) if rdb is not None else None

    async def provider_report_matches_binding(
        self,
        session: AsyncSession,
        *,
        runtime_id: str,
        provider_logical_id: str,
    ) -> bool:
        """Validate a Provider report against the Runtime's durable binding."""
        result = await session.execute(
            sa.select(
                RDBAgentRuntime.runtime_provider_id,
                RDBRuntimeProvider.provider_id,
            )
            .outerjoin(
                RDBRuntimeProvider,
                RDBRuntimeProvider.id == RDBAgentRuntime.runtime_provider_resource_id,
            )
            .where(RDBAgentRuntime.id == runtime_id)
        )
        row = result.one_or_none()
        if row is None:
            return False
        logical_id, bound_resource_logical_id = row
        if bound_resource_logical_id is not None:
            return bound_resource_logical_id == provider_logical_id and logical_id in (
                None,
                bound_resource_logical_id,
            )
        return logical_id is None or logical_id == provider_logical_id

    async def ensure_with_create(
        self,
        session: AsyncSession,
        *,
        create: AgentRuntimeCreate,
    ) -> AgentRuntimeEnsureResult:
        """Create a Runtime once or return the winner of a creation race."""
        existing = await self.get_by_agent_id_for_update(session, create.agent_id)
        if existing is not None:
            return AgentRuntimeEnsureResult(runtime=existing, created=False)

        insert_stmt = (
            insert(RDBAgentRuntime)
            .values(
                id=uuid7().hex,
                workspace_id=create.workspace_id,
                agent_id=create.agent_id,
                runtime_provider_id=create.runtime_provider_id,
                runtime_provider_resource_id=create.runtime_provider_resource_id,
                provider_binding_origin=create.provider_binding_origin,
                provider_binding_evidence=create.provider_binding_evidence,
                infrastructure_profile_id=create.infrastructure_profile_id,
                workspace_runtime_profile_id=create.workspace_runtime_profile_id,
                desired_runtime_configuration_revision_id=(
                    create.desired_runtime_configuration_revision_id
                ),
                applied_runtime_configuration_revision_id=(
                    create.applied_runtime_configuration_revision_id
                ),
            )
            .on_conflict_do_nothing(index_elements=["agent_id"])
            .returning(RDBAgentRuntime)
        )
        result = await session.execute(insert_stmt)
        rdb = result.scalar_one_or_none()
        if rdb is not None:
            await session.flush()
            return AgentRuntimeEnsureResult(runtime=self._build(rdb), created=True)

        raced = await self.get_by_agent_id_for_update(session, create.agent_id)
        if raced is None:
            raise RuntimeError("AgentRuntime ensure failed")
        return AgentRuntimeEnsureResult(runtime=raced, created=False)

    async def ensure_for_agent(
        self,
        session: AsyncSession,
        agent_id: str,
    ) -> AgentRuntime:
        """Ensure an unbound logical AgentRuntime row for one Agent.

        :param session: Database session
        :param agent_id: Agent ID
        :return: AgentRuntime
        """
        existing = await self.get_by_agent_id(session, agent_id)
        if existing is not None:
            return existing

        agent = await session.get(RDBAgent, agent_id)
        if agent is None:
            raise ValueError("Agent not found")

        insert_stmt = (
            insert(RDBAgentRuntime)
            .values(
                id=uuid7().hex,
                workspace_id=agent.workspace_id,
                agent_id=agent_id,
            )
            .on_conflict_do_nothing(index_elements=["agent_id"])
            .returning(RDBAgentRuntime)
        )
        result = await session.execute(insert_stmt)
        rdb = result.scalar_one_or_none()
        if rdb is not None:
            await session.flush()
            return self._build(rdb)

        raced = await self.get_by_agent_id(session, agent_id)
        if raced is None:
            raise RuntimeError("AgentRuntime ensure failed")
        return raced

    async def set_desired_state(
        self,
        session: AsyncSession,
        runtime_id: str,
        command_type: RuntimeLifecycleCommandType,
        desired_state: RuntimeDesiredState,
        *,
        reset_final_desired_state: RuntimeDesiredState | None = None,
    ) -> AgentRuntimeLifecycleCommand | None:
        """Update Runtime desired state and generation."""
        result = await session.execute(
            sa.update(RDBAgentRuntime)
            .where(
                RDBAgentRuntime.id == runtime_id,
                RDBAgentRuntime.terminal_delete_requested_generation.is_(None),
            )
            .values(
                desired_state=desired_state,
                desired_generation=RDBAgentRuntime.desired_generation + 1,
                last_lifecycle_command=command_type,
                reset_final_desired_state=reset_final_desired_state,
                last_state_change_at=sa.func.now(),
            )
            .returning(RDBAgentRuntime)
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            return None
        await session.flush()
        runtime = self._build(rdb)
        return AgentRuntimeLifecycleCommand(
            runtime=runtime,
            command_type=command_type,
            desired_generation=runtime.desired_generation,
        )

    async def set_desired_state_if_ready(
        self,
        session: AsyncSession,
        runtime_id: str,
        command_type: RuntimeLifecycleCommandType,
        desired_state: RuntimeDesiredState,
        *,
        expected_configuration_revision_id: str,
        reset_final_desired_state: RuntimeDesiredState | None = None,
    ) -> AgentRuntimeLifecycleCommand | None:
        """Advance lifecycle state and exact ready evidence atomically."""
        result = await session.execute(
            sa.select(RDBAgentRuntime, RDBRuntimeConfigurationRevision)
            .join(
                RDBRuntimeConfigurationRevision,
                RDBRuntimeConfigurationRevision.id
                == RDBAgentRuntime.desired_runtime_configuration_revision_id,
            )
            .where(
                RDBAgentRuntime.id == runtime_id,
                RDBAgentRuntime.terminal_delete_requested_generation.is_(None),
                RDBAgentRuntime.desired_runtime_configuration_revision_id
                == expected_configuration_revision_id,
                RDBRuntimeConfigurationRevision.id
                == expected_configuration_revision_id,
                RDBRuntimeConfigurationRevision.runtime_id == RDBAgentRuntime.id,
                RDBRuntimeConfigurationRevision.provider_id
                == RDBAgentRuntime.runtime_provider_resource_id,
                RDBRuntimeConfigurationRevision.target_desired_generation
                == RDBAgentRuntime.desired_generation,
                RDBRuntimeConfigurationRevision.resolution_status
                == RuntimeConfigurationResolutionStatus.READY,
                RDBRuntimeConfigurationRevision.resolved_configuration.is_not(None),
            )
            .with_for_update()
        )
        row = result.one_or_none()
        if row is None:
            return None
        rdb = row[0]
        revision = row[1]
        next_generation = rdb.desired_generation + 1
        next_revision = RDBRuntimeConfigurationRevision(
            runtime_id=revision.runtime_id,
            provider_id=revision.provider_id,
            provider_capability_revision_id=(revision.provider_capability_revision_id),
            infrastructure_profile_id=revision.infrastructure_profile_id,
            infrastructure_profile_version=revision.infrastructure_profile_version,
            workspace_runtime_profile_id=revision.workspace_runtime_profile_id,
            workspace_runtime_profile_version=(
                revision.workspace_runtime_profile_version
            ),
            agent_selection_version=revision.agent_selection_version,
            resolution_status=revision.resolution_status,
            required_capabilities=revision.required_capabilities,
            missing_capabilities=revision.missing_capabilities,
            source_trace=revision.source_trace,
            digest=revision.digest,
            target_desired_generation=next_generation,
            reason_code=None,
            resolved_configuration=revision.resolved_configuration,
            provider_reported_digest=None,
            runner_reported_digest=None,
            provider_acknowledged_at=None,
            runtime_observed_at=None,
        )
        session.add(next_revision)
        await session.flush()
        rdb.desired_state = desired_state
        rdb.desired_generation = next_generation
        rdb.desired_runtime_configuration_revision_id = next_revision.id
        rdb.last_lifecycle_command = command_type
        rdb.reset_final_desired_state = reset_final_desired_state
        rdb.last_state_change_at = datetime.datetime.now(datetime.UTC)
        await session.flush()
        await session.refresh(rdb)
        runtime = self._build(rdb)
        return AgentRuntimeLifecycleCommand(
            runtime=runtime,
            command_type=command_type,
            desired_generation=runtime.desired_generation,
        )

    async def request_terminal_delete(
        self,
        session: AsyncSession,
        runtime_id: str,
    ) -> AgentRuntime | None:
        """Request idempotent terminal Provider deletion for the Runtime."""
        result = await session.execute(
            sa.update(RDBAgentRuntime)
            .where(
                RDBAgentRuntime.id == runtime_id,
                RDBAgentRuntime.terminal_delete_requested_generation.is_(None),
            )
            .values(
                desired_state=RuntimeDesiredState.STOPPED,
                desired_generation=RDBAgentRuntime.desired_generation + 1,
                last_lifecycle_command=RuntimeLifecycleCommandType.STOP,
                reset_final_desired_state=None,
                terminal_delete_requested_generation=(
                    RDBAgentRuntime.desired_generation + 1
                ),
                terminal_delete_acknowledged_generation=None,
                terminal_delete_acknowledged_at=None,
                last_state_change_at=sa.func.now(),
            )
            .returning(RDBAgentRuntime)
        )
        rdb = result.scalar_one_or_none()
        if rdb is not None:
            await session.flush()
            return self._build(rdb)
        return await self.get_by_id(session, runtime_id)

    async def record_terminal_delete_acknowledgement(
        self,
        session: AsyncSession,
        runtime_id: str,
        *,
        provider_generation: int,
        acknowledged_generation: int,
    ) -> AgentRuntime | None:
        """Persist a fenced Provider acknowledgement of terminal deletion."""
        result = await session.execute(
            sa.update(RDBAgentRuntime)
            .where(
                RDBAgentRuntime.id == runtime_id,
                RDBAgentRuntime.desired_generation == acknowledged_generation,
                RDBAgentRuntime.terminal_delete_requested_generation
                == acknowledged_generation,
                RDBAgentRuntime.provider_generation <= provider_generation,
                RDBAgentRuntime.provider_observed_generation <= acknowledged_generation,
            )
            .values(
                provider_observed_state=RuntimeProviderObservedState.STOPPED,
                provider_generation=provider_generation,
                provider_observed_generation=acknowledged_generation,
                provider_observed_at=sa.func.now(),
                workspace_path=None,
                runner_state=RuntimeRunnerState.DISCONNECTED,
                terminal_delete_acknowledged_generation=acknowledged_generation,
                terminal_delete_acknowledged_at=sa.func.now(),
                failure_generation=None,
                failure_code=None,
                failure_message=None,
                last_state_change_at=sa.func.now(),
            )
            .returning(RDBAgentRuntime)
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            return None
        await session.flush()
        return self._build(rdb)

    async def get_terminal_delete_acknowledged(
        self,
        session: AsyncSession,
        runtime_id: str,
    ) -> AgentRuntime | None:
        """Return Runtime only after its current terminal deletion is acknowledged."""
        result = await session.execute(
            sa.select(RDBAgentRuntime).where(
                RDBAgentRuntime.id == runtime_id,
                RDBAgentRuntime.terminal_delete_requested_generation
                == RDBAgentRuntime.desired_generation,
                RDBAgentRuntime.terminal_delete_acknowledged_generation
                == RDBAgentRuntime.desired_generation,
            )
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            return None
        return self._build(rdb)

    async def record_provider_observed_state(
        self,
        session: AsyncSession,
        runtime_id: str,
        observed_state: RuntimeProviderObservedState,
        provider_generation: int,
        observed_generation: int,
        *,
        workspace_path: str | None = None,
        failure: AgentRuntimeFailurePatch | None = None,
        clear_failure: bool = False,
    ) -> AgentRuntime | None:
        """Store Provider observed state when report generations are current."""
        changed = sa.or_(
            RDBAgentRuntime.provider_observed_state != observed_state,
            RDBAgentRuntime.provider_generation != provider_generation,
            RDBAgentRuntime.provider_observed_generation != observed_generation,
        )
        if observed_state == RuntimeProviderObservedState.STOPPED:
            changed = sa.or_(
                changed,
                RDBAgentRuntime.runner_state != RuntimeRunnerState.DISCONNECTED,
            )
        if workspace_path is not None:
            changed = sa.or_(
                changed,
                RDBAgentRuntime.workspace_path.is_distinct_from(workspace_path),
            )
        if failure is not None:
            changed = sa.or_(
                changed,
                RDBAgentRuntime.failure_generation.is_distinct_from(failure.generation),
                RDBAgentRuntime.failure_code.is_distinct_from(failure.code),
                RDBAgentRuntime.failure_message.is_distinct_from(failure.message),
            )
        elif clear_failure:
            changed = sa.or_(
                changed,
                RDBAgentRuntime.failure_generation.is_not(None),
                RDBAgentRuntime.failure_code.is_not(None),
                RDBAgentRuntime.failure_message.is_not(None),
            )
        values: dict[str, object | None] = {
            "provider_observed_state": observed_state,
            "provider_generation": provider_generation,
            "provider_observed_generation": observed_generation,
            "provider_observed_at": sa.func.now(),
            "last_state_change_at": sa.case(
                (changed, sa.func.now()),
                else_=RDBAgentRuntime.last_state_change_at,
            ),
        }
        if observed_state == RuntimeProviderObservedState.STOPPED:
            values["runner_state"] = RuntimeRunnerState.DISCONNECTED
        if workspace_path is not None:
            values["workspace_path"] = workspace_path
        if failure is not None:
            values["failure_generation"] = failure.generation
            values["failure_code"] = failure.code
            values["failure_message"] = failure.message
        elif clear_failure:
            values["failure_generation"] = None
            values["failure_code"] = None
            values["failure_message"] = None
        result = await session.execute(
            sa.update(RDBAgentRuntime)
            .where(
                RDBAgentRuntime.id == runtime_id,
                RDBAgentRuntime.provider_generation <= provider_generation,
                RDBAgentRuntime.provider_observed_generation <= observed_generation,
                RDBAgentRuntime.desired_generation <= observed_generation,
                RDBAgentRuntime.terminal_delete_acknowledged_generation.is_distinct_from(
                    RDBAgentRuntime.desired_generation
                ),
            )
            .values(**values)
            .returning(RDBAgentRuntime)
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            return None
        await session.flush()
        return self._build(rdb)

    async def mark_provider_observe_requested(
        self,
        session: AsyncSession,
        runtime_id: str,
    ) -> AgentRuntime | None:
        """Record Provider observe request time."""
        result = await session.execute(
            sa.update(RDBAgentRuntime)
            .where(RDBAgentRuntime.id == runtime_id)
            .values(provider_observe_requested_at=sa.func.now())
            .returning(RDBAgentRuntime)
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            return None
        await session.flush()
        return self._build(rdb)

    async def record_provider_connection_state(
        self,
        session: AsyncSession,
        runtime_id: str,
        connection_state: RuntimeProviderConnectionState,
    ) -> AgentRuntime | None:
        """Store Provider connection state."""
        result = await session.execute(
            sa.update(RDBAgentRuntime)
            .where(RDBAgentRuntime.id == runtime_id)
            .values(
                provider_connection_state=connection_state,
                last_state_change_at=sa.case(
                    (
                        RDBAgentRuntime.provider_connection_state != connection_state,
                        sa.func.now(),
                    ),
                    else_=RDBAgentRuntime.last_state_change_at,
                ),
            )
            .returning(RDBAgentRuntime)
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            return None
        await session.flush()
        return self._build(rdb)

    async def record_runtime_failure(
        self,
        session: AsyncSession,
        runtime_id: str,
        failure: AgentRuntimeFailurePatch,
    ) -> AgentRuntime | None:
        """Store Runtime current-generation failure."""
        result = await session.execute(
            sa.update(RDBAgentRuntime)
            .where(RDBAgentRuntime.id == runtime_id)
            .values(
                failure_generation=failure.generation,
                failure_code=failure.code,
                failure_message=failure.message,
                last_state_change_at=sa.func.now(),
            )
            .returning(RDBAgentRuntime)
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            return None
        await session.flush()
        return self._build(rdb)

    async def mark_start_timeouts(
        self,
        session: AsyncSession,
        *,
        stale_threshold: datetime.timedelta,
        limit: int,
    ) -> list[AgentRuntime]:
        """Mark Runtime as failed after long RUNNING desired non-convergence."""
        timeout_candidates = (
            sa.select(RDBAgentRuntime.id)
            .where(
                RDBAgentRuntime.desired_state == RuntimeDesiredState.RUNNING,
                RDBAgentRuntime.provider_connection_state
                == RuntimeProviderConnectionState.CONNECTED,
                RDBAgentRuntime.last_lifecycle_dispatch_generation
                == RDBAgentRuntime.desired_generation,
                RDBAgentRuntime.last_state_change_at
                < sa.func.clock_timestamp() - stale_threshold,
                sa.not_(
                    sa.and_(
                        RDBAgentRuntime.provider_observed_state
                        == RuntimeProviderObservedState.RUNNING,
                        RDBAgentRuntime.runner_state.in_(
                            [RuntimeRunnerState.READY, RuntimeRunnerState.DEGRADED]
                        ),
                    )
                ),
                sa.or_(
                    RDBAgentRuntime.failure_generation.is_(None),
                    RDBAgentRuntime.failure_generation
                    != RDBAgentRuntime.desired_generation,
                    RDBAgentRuntime.failure_code != "START_TIMEOUT",
                ),
            )
            .order_by(RDBAgentRuntime.last_state_change_at.asc())
            .limit(limit)
            .subquery()
        )
        result = await session.execute(
            sa.update(RDBAgentRuntime)
            .where(RDBAgentRuntime.id.in_(sa.select(timeout_candidates.c.id)))
            .values(
                provider_observed_state=RuntimeProviderObservedState.FAILED,
                failure_generation=RDBAgentRuntime.desired_generation,
                failure_code="START_TIMEOUT",
                failure_message=(
                    "Runtime did not become running before the configured "
                    "Control timeout."
                ),
                last_state_change_at=sa.func.now(),
            )
            .returning(RDBAgentRuntime)
        )
        rows = list(result.scalars())
        await session.flush()
        return [self._build(rdb) for rdb in rows]

    async def mark_lifecycle_dispatched(
        self,
        session: AsyncSession,
        runtime_id: str,
        desired_generation: int,
    ) -> AgentRuntime | None:
        """Record desired generation dispatched as Provider command."""
        result = await session.execute(
            sa.update(RDBAgentRuntime)
            .where(
                RDBAgentRuntime.id == runtime_id,
                RDBAgentRuntime.desired_generation == desired_generation,
            )
            .values(
                last_lifecycle_dispatch_generation=desired_generation,
                last_state_change_at=sa.func.now(),
            )
            .returning(RDBAgentRuntime)
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            return None
        await session.flush()
        return self._build(rdb)

    async def claim_lifecycle_dispatch(
        self,
        session: AsyncSession,
        runtime_id: str,
        desired_generation: int,
        *,
        retry_delay: datetime.timedelta = datetime.timedelta(seconds=60),
    ) -> AgentRuntime | None:
        """Atomically acquire Provider lifecycle command dispatch permission."""
        undispatched_generation = (
            RDBAgentRuntime.desired_generation
            > RDBAgentRuntime.last_lifecycle_dispatch_generation
        )
        retry_cutoff = sa.func.clock_timestamp() - retry_delay
        unready_start_retry = sa.and_(
            RDBAgentRuntime.last_lifecycle_command == RuntimeLifecycleCommandType.START,
            RDBAgentRuntime.desired_state == RuntimeDesiredState.RUNNING,
            RDBAgentRuntime.provider_connection_state
            == RuntimeProviderConnectionState.CONNECTED,
            RDBAgentRuntime.provider_observed_state.in_(
                [
                    RuntimeProviderObservedState.FAILED,
                    RuntimeProviderObservedState.STARTING,
                    RuntimeProviderObservedState.STOPPING,
                    RuntimeProviderObservedState.STOPPED,
                    RuntimeProviderObservedState.UNKNOWN,
                ]
            ),
            sa.or_(
                RDBAgentRuntime.last_state_change_at.is_(None),
                RDBAgentRuntime.last_state_change_at < retry_cutoff,
            ),
            sa.or_(
                RDBAgentRuntime.failure_generation.is_(None),
                RDBAgentRuntime.failure_generation
                != RDBAgentRuntime.desired_generation,
                RDBAgentRuntime.failure_code != "START_TIMEOUT",
            ),
        )
        terminal_delete_retry = sa.and_(
            RDBAgentRuntime.terminal_delete_requested_generation
            == RDBAgentRuntime.desired_generation,
            RDBAgentRuntime.terminal_delete_acknowledged_generation.is_distinct_from(
                RDBAgentRuntime.desired_generation
            ),
            RDBAgentRuntime.provider_connection_state
            == RuntimeProviderConnectionState.CONNECTED,
            sa.or_(
                RDBAgentRuntime.last_state_change_at.is_(None),
                RDBAgentRuntime.last_state_change_at < retry_cutoff,
            ),
        )
        result = await session.execute(
            sa.update(RDBAgentRuntime)
            .where(
                RDBAgentRuntime.id == runtime_id,
                RDBAgentRuntime.desired_generation == desired_generation,
                RDBAgentRuntime.last_lifecycle_command.is_not(None),
                sa.or_(
                    undispatched_generation,
                    unready_start_retry,
                    terminal_delete_retry,
                ),
            )
            .values(
                last_lifecycle_dispatch_generation=sa.case(
                    (
                        undispatched_generation,
                        RDBAgentRuntime.desired_generation,
                    ),
                    else_=RDBAgentRuntime.last_lifecycle_dispatch_generation,
                ),
                last_state_change_at=sa.func.now(),
            )
            .returning(RDBAgentRuntime)
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            return None
        await session.flush()
        return self._build(rdb)

    async def record_runner_state(
        self,
        session: AsyncSession,
        runtime_id: str,
        runner_state: RuntimeRunnerState,
        runner_generation: int,
        *,
        expected_desired_generation: int,
        failure: AgentRuntimeFailurePatch | None = None,
    ) -> AgentRuntime | None:
        """Store Runner state only for the expected desired generation."""
        changed = sa.or_(
            RDBAgentRuntime.runner_state != runner_state,
            RDBAgentRuntime.runner_generation != runner_generation,
        )
        if failure is not None:
            changed = sa.or_(
                changed,
                RDBAgentRuntime.failure_generation.is_distinct_from(failure.generation),
                RDBAgentRuntime.failure_code.is_distinct_from(failure.code),
                RDBAgentRuntime.failure_message.is_distinct_from(failure.message),
            )
        values: dict[str, object | None] = {
            "runner_state": runner_state,
            "runner_generation": runner_generation,
            "last_state_change_at": sa.case(
                (changed, sa.func.now()),
                else_=RDBAgentRuntime.last_state_change_at,
            ),
        }
        if failure is not None:
            values["failure_generation"] = failure.generation
            values["failure_code"] = failure.code
            values["failure_message"] = failure.message
        result = await session.execute(
            sa.update(RDBAgentRuntime)
            .where(
                RDBAgentRuntime.id == runtime_id,
                RDBAgentRuntime.desired_generation == expected_desired_generation,
                RDBAgentRuntime.runner_generation <= runner_generation,
                RDBAgentRuntime.terminal_delete_acknowledged_generation.is_distinct_from(
                    RDBAgentRuntime.desired_generation
                ),
            )
            .values(**values)
            .returning(RDBAgentRuntime)
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            return None
        await session.flush()
        return self._build(rdb)

    async def clear_current_generation_failure(
        self,
        session: AsyncSession,
        runtime_id: str,
    ) -> AgentRuntime | None:
        """Remove failure for current desired generation."""
        result = await session.execute(
            sa.update(RDBAgentRuntime)
            .where(
                RDBAgentRuntime.id == runtime_id,
                RDBAgentRuntime.failure_generation
                == RDBAgentRuntime.desired_generation,
            )
            .values(
                failure_generation=None,
                failure_code=None,
                failure_message=None,
            )
            .returning(RDBAgentRuntime)
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            return await self.get_by_id(session, runtime_id)
        await session.flush()
        return self._build(rdb)

    async def find_lifecycle_dispatch_candidates(
        self,
        session: AsyncSession,
        *,
        limit: int,
        retry_delay: datetime.timedelta = datetime.timedelta(seconds=60),
    ) -> list[AgentRuntime]:
        """Runtime list requiring Provider lifecycle command dispatch."""
        undispatched_generation = (
            RDBAgentRuntime.desired_generation
            > RDBAgentRuntime.last_lifecycle_dispatch_generation
        )
        retry_cutoff = sa.func.clock_timestamp() - retry_delay
        unready_start_retry = sa.and_(
            RDBAgentRuntime.last_lifecycle_command == RuntimeLifecycleCommandType.START,
            RDBAgentRuntime.desired_state == RuntimeDesiredState.RUNNING,
            RDBAgentRuntime.provider_connection_state
            == RuntimeProviderConnectionState.CONNECTED,
            RDBAgentRuntime.provider_observed_state.in_(
                [
                    RuntimeProviderObservedState.FAILED,
                    RuntimeProviderObservedState.STARTING,
                    RuntimeProviderObservedState.STOPPING,
                    RuntimeProviderObservedState.STOPPED,
                    RuntimeProviderObservedState.UNKNOWN,
                ]
            ),
            sa.or_(
                RDBAgentRuntime.last_state_change_at.is_(None),
                RDBAgentRuntime.last_state_change_at < retry_cutoff,
            ),
            sa.or_(
                RDBAgentRuntime.failure_generation.is_(None),
                RDBAgentRuntime.failure_generation
                != RDBAgentRuntime.desired_generation,
                RDBAgentRuntime.failure_code != "START_TIMEOUT",
            ),
        )
        terminal_delete_retry = sa.and_(
            RDBAgentRuntime.terminal_delete_requested_generation
            == RDBAgentRuntime.desired_generation,
            RDBAgentRuntime.terminal_delete_acknowledged_generation.is_distinct_from(
                RDBAgentRuntime.desired_generation
            ),
            RDBAgentRuntime.provider_connection_state
            == RuntimeProviderConnectionState.CONNECTED,
            sa.or_(
                RDBAgentRuntime.last_state_change_at.is_(None),
                RDBAgentRuntime.last_state_change_at < retry_cutoff,
            ),
        )
        result = await session.execute(
            sa.select(RDBAgentRuntime)
            .where(
                RDBAgentRuntime.last_lifecycle_command.is_not(None),
                sa.or_(
                    undispatched_generation,
                    unready_start_retry,
                    terminal_delete_retry,
                ),
            )
            .order_by(RDBAgentRuntime.last_state_change_at.nulls_first())
            .limit(limit)
        )
        return [self._build(rdb) for rdb in result.scalars()]

    async def find_provider_observe_candidates(
        self,
        session: AsyncSession,
        *,
        limit: int,
        observe_interval: datetime.timedelta,
    ) -> list[AgentRuntime]:
        """Runtime list requiring Provider observe command."""
        observe_cutoff = sa.func.clock_timestamp() - observe_interval
        last_observe_at = sa.func.greatest(
            sa.func.coalesce(
                RDBAgentRuntime.provider_observed_at,
                RDBAgentRuntime.created_at,
            ),
            sa.func.coalesce(
                RDBAgentRuntime.provider_observe_requested_at,
                RDBAgentRuntime.created_at,
            ),
        )
        result = await session.execute(
            sa.select(RDBAgentRuntime)
            .where(
                RDBAgentRuntime.runtime_provider_id.is_not(None),
                sa.or_(
                    RDBAgentRuntime.desired_state == RuntimeDesiredState.RUNNING,
                    sa.and_(
                        RDBAgentRuntime.desired_state == RuntimeDesiredState.STOPPED,
                        RDBAgentRuntime.provider_observed_state
                        != RuntimeProviderObservedState.STOPPED,
                    ),
                ),
                RDBAgentRuntime.last_lifecycle_dispatch_generation
                >= RDBAgentRuntime.desired_generation,
                last_observe_at < observe_cutoff,
            )
            .order_by(last_observe_at.asc())
            .limit(limit)
        )
        return [self._build(rdb) for rdb in result.scalars()]

    async def find_configuration_adoption_candidates(
        self,
        session: AsyncSession,
        *,
        limit: int,
    ) -> list[AgentRuntime]:
        """List running Runtimes whose exact desired revision is not applied."""
        result = await session.execute(
            sa.select(RDBAgentRuntime)
            .where(
                RDBAgentRuntime.desired_state == RuntimeDesiredState.RUNNING,
                RDBAgentRuntime.provider_observed_state
                == RuntimeProviderObservedState.RUNNING,
                RDBAgentRuntime.desired_runtime_configuration_revision_id.is_not(None),
                RDBAgentRuntime.applied_runtime_configuration_revision_id.is_not(None),
                RDBAgentRuntime.desired_runtime_configuration_revision_id
                != RDBAgentRuntime.applied_runtime_configuration_revision_id,
                RDBAgentRuntime.terminal_delete_requested_generation.is_(None),
            )
            .order_by(RDBAgentRuntime.last_state_change_at.nulls_first())
            .limit(limit)
        )
        return [self._build(rdb) for rdb in result.scalars()]

    def _build(self, rdb: RDBAgentRuntime) -> AgentRuntime:
        """Convert RDB model to domain model."""
        return AgentRuntime(
            id=rdb.id,
            workspace_id=rdb.workspace_id,
            agent_id=rdb.agent_id,
            runtime_provider_id=rdb.runtime_provider_id,
            runtime_provider_resource_id=rdb.runtime_provider_resource_id,
            provider_binding_origin=rdb.provider_binding_origin,
            provider_binding_evidence=rdb.provider_binding_evidence,
            infrastructure_profile_id=rdb.infrastructure_profile_id,
            workspace_runtime_profile_id=rdb.workspace_runtime_profile_id,
            desired_runtime_configuration_revision_id=(
                rdb.desired_runtime_configuration_revision_id
            ),
            applied_runtime_configuration_revision_id=(
                rdb.applied_runtime_configuration_revision_id
            ),
            desired_state=rdb.desired_state,
            desired_generation=rdb.desired_generation,
            last_lifecycle_command=rdb.last_lifecycle_command,
            reset_final_desired_state=rdb.reset_final_desired_state,
            terminal_delete_requested_generation=(
                rdb.terminal_delete_requested_generation
            ),
            terminal_delete_acknowledged_generation=(
                rdb.terminal_delete_acknowledged_generation
            ),
            terminal_delete_acknowledged_at=rdb.terminal_delete_acknowledged_at,
            provider_observed_state=rdb.provider_observed_state,
            provider_generation=rdb.provider_generation,
            provider_observed_generation=rdb.provider_observed_generation,
            provider_observed_at=rdb.provider_observed_at,
            provider_observe_requested_at=rdb.provider_observe_requested_at,
            last_lifecycle_dispatch_generation=(rdb.last_lifecycle_dispatch_generation),
            provider_connection_state=rdb.provider_connection_state,
            runner_state=rdb.runner_state,
            runner_generation=rdb.runner_generation,
            workspace_path=rdb.workspace_path,
            failure_generation=rdb.failure_generation,
            failure_code=rdb.failure_code,
            failure_message=rdb.failure_message,
            last_state_change_at=rdb.last_state_change_at,
            created_at=rdb.created_at,
            updated_at=rdb.updated_at,
        )
