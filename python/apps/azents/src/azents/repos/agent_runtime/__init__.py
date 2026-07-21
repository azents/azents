"""AgentRuntime repository."""

import datetime

import sqlalchemy as sa
from azcommon.uuid import uuid7
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    RuntimeDesiredState,
    RuntimeLifecycleCommandType,
    RuntimeProviderConnectionState,
    RuntimeProviderObservedState,
    RuntimeRunnerState,
)
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_runtime import RDBAgentRuntime

from .data import (
    AgentRuntime,
    AgentRuntimeCreate,
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
            provider_config=create.provider_config,
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

    async def ensure_for_agent(
        self,
        session: AsyncSession,
        agent_id: str,
        *,
        default_runtime_provider_id: str | None = None,
    ) -> AgentRuntime:
        """Ensure AgentRuntime for Agent.

        Return it if it already exists; otherwise create a new one using
        workspace_id from Agent row. Concurrent creation races are absorbed by
        unique constraint and refetch. If existing Runtime has no provider and
        default provider is specified, fill that default provider so existing
        Agents converge to runnable state before production cutover.

        :param session: Database session
        :param agent_id: Agent ID
        :param default_runtime_provider_id: Explicit default Provider ID to use
            when Runtime Provider is empty
        :return: AgentRuntime
        """
        existing = await self.get_by_agent_id(session, agent_id)
        if existing is not None:
            if (
                existing.runtime_provider_id is None
                and default_runtime_provider_id is not None
            ):
                updated = await self._set_runtime_provider_if_empty(
                    session,
                    existing.id,
                    default_runtime_provider_id,
                )
                if updated is not None:
                    return updated
            return existing

        agent = await session.get(RDBAgent, agent_id)
        if agent is None:
            raise ValueError("Agent not found")
        runtime_provider_id = agent.runtime_provider_id or default_runtime_provider_id

        insert_stmt = (
            insert(RDBAgentRuntime)
            .values(
                id=uuid7().hex,
                workspace_id=agent.workspace_id,
                agent_id=agent_id,
                runtime_provider_id=runtime_provider_id,
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
        if (
            raced.runtime_provider_id is None
            and default_runtime_provider_id is not None
        ):
            updated = await self._set_runtime_provider_if_empty(
                session,
                raced.id,
                default_runtime_provider_id,
            )
            if updated is not None:
                return updated
        return raced

    async def _set_runtime_provider_if_empty(
        self,
        session: AsyncSession,
        runtime_id: str,
        runtime_provider_id: str,
    ) -> AgentRuntime | None:
        """Fill provider ID only when Runtime Provider is empty."""
        result = await session.execute(
            sa.update(RDBAgentRuntime)
            .where(
                RDBAgentRuntime.id == runtime_id,
                RDBAgentRuntime.runtime_provider_id.is_(None),
            )
            .values(runtime_provider_id=runtime_provider_id)
            .returning(RDBAgentRuntime)
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            return None
        await session.flush()
        return self._build(rdb)

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

    async def mark_provider_observe_dispatched(
        self,
        session: AsyncSession,
        runtime_id: str,
    ) -> AgentRuntime | None:
        """Record Provider observe request send time."""
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
        failure: AgentRuntimeFailurePatch | None = None,
    ) -> AgentRuntime | None:
        """Store Runner state."""
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
                RDBAgentRuntime.desired_state == RuntimeDesiredState.RUNNING,
                RDBAgentRuntime.provider_connection_state
                == RuntimeProviderConnectionState.CONNECTED,
                RDBAgentRuntime.last_lifecycle_dispatch_generation
                >= RDBAgentRuntime.desired_generation,
                last_observe_at < observe_cutoff,
            )
            .order_by(last_observe_at.asc())
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
            provider_config=rdb.provider_config,
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
