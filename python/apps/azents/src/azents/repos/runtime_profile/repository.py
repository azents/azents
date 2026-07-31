"""Runtime Profile, reconciliation, and recreation persistence."""

import datetime

import sqlalchemy as sa
from azcommon.datetime import tznow
from azcommon.uuid import uuid7
from azents_runtime_control.execution_policy import RuntimeExecutionPolicyEvidence
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.runtime_execution_policy import (
    digest_runtime_execution_policy,
    standard_runtime_execution_policy,
)
from azents.core.runtime_profile import (
    RuntimeConfigurationResolutionStatus,
    RuntimeProfileLifecycle,
    RuntimeReconcileSourceKind,
    RuntimeReconcileTaskStatus,
    RuntimeRecreationItemStatus,
    RuntimeRecreationOperationStatus,
    RuntimeRecreationTargetKind,
)
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_runtime import RDBAgentRuntime
from azents.rdb.models.runtime_profile import (
    RDBRuntimeConfigurationReconcileTask,
    RDBRuntimeConfigurationRevision,
    RDBRuntimeInfrastructureProfile,
    RDBRuntimeRecreationOperation,
    RDBRuntimeRecreationOperationItem,
    RDBWorkspaceRuntimeProfile,
)
from azents.rdb.models.runtime_provider import RDBRuntimeProvider

from .data import (
    RuntimeConfigurationReconcileTask,
    RuntimeConfigurationRevision,
    RuntimeConfigurationRevisionCreate,
    RuntimeInfrastructureProfile,
    RuntimeInfrastructureProfileCreate,
    RuntimeInfrastructureProfileReplace,
    RuntimeRecreationOperation,
    RuntimeRecreationOperationItem,
    WorkspaceRuntimeProfile,
    WorkspaceRuntimeProfileCreate,
    WorkspaceRuntimeProfileReplace,
)


class RuntimeProfileRepository:
    """Persist Profile aggregates and immutable configuration evidence."""

    async def create_infrastructure_profile(
        self,
        session: AsyncSession,
        *,
        create: RuntimeInfrastructureProfileCreate,
    ) -> RuntimeInfrastructureProfile:
        """Create one Provider-owned infrastructure Profile at version one."""
        rdb = RDBRuntimeInfrastructureProfile(
            provider_id=create.provider_id,
            profile_kind=create.profile_kind,
            display_name=create.display_name,
            description=create.description,
            lifecycle=create.lifecycle,
            contract_family=create.contract_family,
            schema_version=create.schema_version,
            spec=create.spec,
            required_capabilities=list(create.required_capabilities),
            version=1,
            digest=create.digest,
            created_by_user_id=create.actor_user_id,
            updated_by_user_id=create.actor_user_id,
        )
        session.add(rdb)
        await session.flush()
        return self._build_infrastructure_profile(rdb)

    async def get_infrastructure_profile(
        self,
        session: AsyncSession,
        *,
        profile_id: str,
        for_update: bool,
    ) -> RuntimeInfrastructureProfile | None:
        """Fetch one infrastructure Profile by globally unique row ID."""
        statement = sa.select(RDBRuntimeInfrastructureProfile).where(
            RDBRuntimeInfrastructureProfile.id == profile_id
        )
        if for_update:
            statement = statement.with_for_update()
        result = await session.execute(statement)
        rdb = result.scalar_one_or_none()
        return self._build_infrastructure_profile(rdb) if rdb is not None else None

    async def list_infrastructure_profiles(
        self,
        session: AsyncSession,
        *,
        provider_id: str,
        include_disabled: bool,
    ) -> list[RuntimeInfrastructureProfile]:
        """List infrastructure Profiles owned by one exact Provider."""
        statement = (
            sa.select(RDBRuntimeInfrastructureProfile)
            .where(RDBRuntimeInfrastructureProfile.provider_id == provider_id)
            .order_by(
                RDBRuntimeInfrastructureProfile.display_name,
                RDBRuntimeInfrastructureProfile.id,
            )
        )
        if not include_disabled:
            statement = statement.where(
                RDBRuntimeInfrastructureProfile.lifecycle
                == RuntimeProfileLifecycle.ACTIVE
            )
        result = await session.execute(statement)
        return [
            self._build_infrastructure_profile(rdb) for rdb in result.scalars().all()
        ]

    async def replace_infrastructure_profile(
        self,
        session: AsyncSession,
        *,
        provider_id: str,
        profile_id: str,
        expected_version: int,
        replacement: RuntimeInfrastructureProfileReplace,
    ) -> RuntimeInfrastructureProfile | None:
        """Replace Profile content using Provider ownership and version fencing."""
        result = await session.execute(
            sa.update(RDBRuntimeInfrastructureProfile)
            .where(
                RDBRuntimeInfrastructureProfile.id == profile_id,
                RDBRuntimeInfrastructureProfile.provider_id == provider_id,
                RDBRuntimeInfrastructureProfile.version == expected_version,
            )
            .values(
                display_name=replacement.display_name,
                description=replacement.description,
                lifecycle=replacement.lifecycle,
                contract_family=replacement.contract_family,
                schema_version=replacement.schema_version,
                spec=replacement.spec,
                required_capabilities=list(replacement.required_capabilities),
                version=RDBRuntimeInfrastructureProfile.version + 1,
                digest=replacement.digest,
                updated_by_user_id=replacement.actor_user_id,
                updated_at=tznow(),
            )
            .returning(RDBRuntimeInfrastructureProfile)
        )
        rdb = result.scalar_one_or_none()
        await session.flush()
        return self._build_infrastructure_profile(rdb) if rdb is not None else None

    async def create_workspace_runtime_profile(
        self,
        session: AsyncSession,
        *,
        create: WorkspaceRuntimeProfileCreate,
    ) -> WorkspaceRuntimeProfile:
        """Create one Workspace Profile bound to the exact Provider Profile."""
        infrastructure_provider_id = await session.scalar(
            sa.select(RDBRuntimeInfrastructureProfile.provider_id).where(
                RDBRuntimeInfrastructureProfile.id == create.infrastructure_profile_id
            )
        )
        if infrastructure_provider_id != create.provider_id:
            raise ValueError(
                "Infrastructure Profile does not belong to the selected Provider."
            )
        rdb = RDBWorkspaceRuntimeProfile(
            workspace_id=create.workspace_id,
            provider_id=create.provider_id,
            infrastructure_profile_id=create.infrastructure_profile_id,
            display_name=create.display_name,
            description=create.description,
            lifecycle=create.lifecycle,
            policy=create.policy,
            version=1,
            digest=create.digest,
            created_by_workspace_user_id=create.actor_workspace_user_id,
            updated_by_workspace_user_id=create.actor_workspace_user_id,
        )
        session.add(rdb)
        await session.flush()
        return self._build_workspace_profile(rdb)

    async def get_workspace_runtime_profile(
        self,
        session: AsyncSession,
        *,
        workspace_id: str,
        profile_id: str,
        for_update: bool,
    ) -> WorkspaceRuntimeProfile | None:
        """Fetch one Workspace-owned Profile with its ownership boundary."""
        statement = sa.select(RDBWorkspaceRuntimeProfile).where(
            RDBWorkspaceRuntimeProfile.id == profile_id,
            RDBWorkspaceRuntimeProfile.workspace_id == workspace_id,
        )
        if for_update:
            statement = statement.with_for_update()
        result = await session.execute(statement)
        rdb = result.scalar_one_or_none()
        return self._build_workspace_profile(rdb) if rdb is not None else None

    async def list_workspace_runtime_profiles(
        self,
        session: AsyncSession,
        *,
        workspace_id: str,
        include_disabled: bool,
    ) -> list[WorkspaceRuntimeProfile]:
        """List Runtime Profiles owned by one exact Workspace."""
        statement = (
            sa.select(RDBWorkspaceRuntimeProfile)
            .where(RDBWorkspaceRuntimeProfile.workspace_id == workspace_id)
            .order_by(
                RDBWorkspaceRuntimeProfile.display_name,
                RDBWorkspaceRuntimeProfile.id,
            )
        )
        if not include_disabled:
            statement = statement.where(
                RDBWorkspaceRuntimeProfile.lifecycle == RuntimeProfileLifecycle.ACTIVE
            )
        result = await session.execute(statement)
        return [self._build_workspace_profile(rdb) for rdb in result.scalars().all()]

    async def replace_workspace_runtime_profile(
        self,
        session: AsyncSession,
        *,
        workspace_id: str,
        profile_id: str,
        expected_version: int,
        replacement: WorkspaceRuntimeProfileReplace,
    ) -> WorkspaceRuntimeProfile | None:
        """Replace a Workspace Profile using ownership and version fencing."""
        infrastructure_provider_id = await session.scalar(
            sa.select(RDBRuntimeInfrastructureProfile.provider_id).where(
                RDBRuntimeInfrastructureProfile.id
                == replacement.infrastructure_profile_id
            )
        )
        if infrastructure_provider_id != replacement.provider_id:
            raise ValueError(
                "Infrastructure Profile does not belong to the selected Provider."
            )
        result = await session.execute(
            sa.update(RDBWorkspaceRuntimeProfile)
            .where(
                RDBWorkspaceRuntimeProfile.id == profile_id,
                RDBWorkspaceRuntimeProfile.workspace_id == workspace_id,
                RDBWorkspaceRuntimeProfile.version == expected_version,
            )
            .values(
                provider_id=replacement.provider_id,
                infrastructure_profile_id=replacement.infrastructure_profile_id,
                display_name=replacement.display_name,
                description=replacement.description,
                lifecycle=replacement.lifecycle,
                policy=replacement.policy,
                version=RDBWorkspaceRuntimeProfile.version + 1,
                digest=replacement.digest,
                updated_by_workspace_user_id=(replacement.actor_workspace_user_id),
                updated_at=tznow(),
            )
            .returning(RDBWorkspaceRuntimeProfile)
        )
        rdb = result.scalar_one_or_none()
        await session.flush()
        return self._build_workspace_profile(rdb) if rdb is not None else None

    async def create_configuration_revision(
        self,
        session: AsyncSession,
        *,
        create: RuntimeConfigurationRevisionCreate,
    ) -> RuntimeConfigurationRevision:
        """Append immutable ready or blocked desired configuration evidence."""
        rdb = RDBRuntimeConfigurationRevision(
            runtime_id=create.runtime_id,
            provider_id=create.provider_id,
            provider_capability_revision_id=create.provider_capability_revision_id,
            infrastructure_profile_id=create.infrastructure_profile_id,
            infrastructure_profile_version=create.infrastructure_profile_version,
            workspace_runtime_profile_id=create.workspace_runtime_profile_id,
            workspace_runtime_profile_version=create.workspace_runtime_profile_version,
            agent_selection_version=create.agent_selection_version,
            resolution_status=create.resolution_status,
            required_capabilities=list(create.required_capabilities),
            missing_capabilities=list(create.missing_capabilities),
            source_trace=create.source_trace,
            digest=create.digest,
            target_desired_generation=create.target_desired_generation,
            reason_code=create.reason_code,
            resolved_configuration=create.resolved_configuration,
            provider_reported_digest=None,
            runner_reported_digest=None,
            provider_acknowledged_at=None,
            runtime_observed_at=None,
        )
        session.add(rdb)
        await session.flush()
        return self._build_configuration_revision(rdb)

    async def create_or_get_configuration_revision(
        self,
        session: AsyncSession,
        *,
        create: RuntimeConfigurationRevisionCreate,
    ) -> RuntimeConfigurationRevision:
        """Append immutable evidence or reuse the equivalent Runtime revision."""
        revision_id = uuid7().hex
        result = await session.execute(
            insert(RDBRuntimeConfigurationRevision)
            .values(
                id=revision_id,
                runtime_id=create.runtime_id,
                provider_id=create.provider_id,
                provider_capability_revision_id=(
                    create.provider_capability_revision_id
                ),
                infrastructure_profile_id=create.infrastructure_profile_id,
                infrastructure_profile_version=create.infrastructure_profile_version,
                workspace_runtime_profile_id=create.workspace_runtime_profile_id,
                workspace_runtime_profile_version=(
                    create.workspace_runtime_profile_version
                ),
                agent_selection_version=create.agent_selection_version,
                resolution_status=create.resolution_status,
                required_capabilities=list(create.required_capabilities),
                missing_capabilities=list(create.missing_capabilities),
                source_trace=create.source_trace,
                digest=create.digest,
                target_desired_generation=create.target_desired_generation,
                reason_code=create.reason_code,
                resolved_configuration=create.resolved_configuration,
                provider_reported_digest=None,
                runner_reported_digest=None,
                provider_acknowledged_at=None,
                runtime_observed_at=None,
            )
            .on_conflict_do_nothing(
                constraint="uq_runtime_configuration_revisions_runtime_digest_generation"
            )
            .returning(RDBRuntimeConfigurationRevision)
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            existing = await session.execute(
                sa.select(RDBRuntimeConfigurationRevision).where(
                    RDBRuntimeConfigurationRevision.runtime_id == create.runtime_id,
                    RDBRuntimeConfigurationRevision.digest == create.digest,
                    RDBRuntimeConfigurationRevision.target_desired_generation
                    == create.target_desired_generation,
                )
            )
            rdb = existing.scalar_one()
        await session.flush()
        return self._build_configuration_revision(rdb)

    async def get_configuration_revision(
        self,
        session: AsyncSession,
        *,
        revision_id: str,
    ) -> RuntimeConfigurationRevision | None:
        """Fetch one immutable Runtime configuration revision."""
        rdb = await session.get(RDBRuntimeConfigurationRevision, revision_id)
        return self._build_configuration_revision(rdb) if rdb is not None else None

    async def configuration_transport_evidence_matches_current(
        self,
        session: AsyncSession,
        *,
        runtime_id: str,
        provider_id: str,
        evidence: RuntimeExecutionPolicyEvidence,
    ) -> bool:
        """Validate the Phase-2 transport envelope without claiming adoption."""
        revision = await self._current_configuration_evidence(
            session,
            runtime_id=runtime_id,
            provider_id=provider_id,
            evidence=evidence,
        )
        return revision is not None

    async def _current_configuration_evidence(
        self,
        session: AsyncSession,
        *,
        runtime_id: str,
        provider_id: str,
        evidence: RuntimeExecutionPolicyEvidence,
    ) -> RuntimeConfigurationRevision | None:
        runtime_statement = sa.select(RDBAgentRuntime).where(
            RDBAgentRuntime.id == runtime_id,
            RDBAgentRuntime.runtime_provider_resource_id == provider_id,
            RDBAgentRuntime.desired_runtime_configuration_revision_id
            == evidence.snapshot_id,
            RDBAgentRuntime.desired_generation == evidence.desired_generation,
        )
        runtime = (await session.execute(runtime_statement)).scalar_one_or_none()
        if runtime is None:
            return None
        revision_statement = sa.select(RDBRuntimeConfigurationRevision).where(
            RDBRuntimeConfigurationRevision.id == evidence.snapshot_id,
            RDBRuntimeConfigurationRevision.runtime_id == runtime_id,
            RDBRuntimeConfigurationRevision.provider_id == provider_id,
        )
        revision = (await session.execute(revision_statement)).scalar_one_or_none()
        if revision is None or not _configuration_evidence_matches(revision, evidence):
            return None
        return self._build_configuration_revision(revision)

    async def enqueue_reconcile_task(
        self,
        session: AsyncSession,
        *,
        source_type: RuntimeReconcileSourceKind,
        source_id: str,
        source_version: str,
        available_at: datetime.datetime,
    ) -> RuntimeConfigurationReconcileTask:
        """Idempotently enqueue one authoritative source version."""
        task_id = uuid7().hex
        result = await session.execute(
            insert(RDBRuntimeConfigurationReconcileTask)
            .values(
                id=task_id,
                source_type=source_type,
                source_id=source_id,
                source_version=source_version,
                status=RuntimeReconcileTaskStatus.PENDING,
                available_at=available_at,
                cursor=None,
                attempt=0,
                failure_code=None,
            )
            .on_conflict_do_nothing(
                constraint="uq_runtime_configuration_reconcile_tasks_source_version"
            )
            .returning(RDBRuntimeConfigurationReconcileTask)
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            existing = await session.execute(
                sa.select(RDBRuntimeConfigurationReconcileTask).where(
                    RDBRuntimeConfigurationReconcileTask.source_type == source_type,
                    RDBRuntimeConfigurationReconcileTask.source_id == source_id,
                    RDBRuntimeConfigurationReconcileTask.source_version
                    == source_version,
                )
            )
            rdb = existing.scalar_one()
        await session.flush()
        return self._build_reconcile_task(rdb)

    async def claim_reconcile_tasks(
        self,
        session: AsyncSession,
        *,
        available_before: datetime.datetime,
        reclaim_running_before: datetime.datetime,
        limit: int,
    ) -> list[RuntimeConfigurationReconcileTask]:
        """Claim available or abandoned tasks with PostgreSQL ``SKIP LOCKED``."""
        if limit < 1:
            raise ValueError("Reconcile claim limit must be positive.")
        result = await session.execute(
            sa.select(RDBRuntimeConfigurationReconcileTask)
            .where(
                sa.or_(
                    sa.and_(
                        RDBRuntimeConfigurationReconcileTask.status.in_(
                            (
                                RuntimeReconcileTaskStatus.PENDING,
                                RuntimeReconcileTaskStatus.RETRY_WAIT,
                            )
                        ),
                        RDBRuntimeConfigurationReconcileTask.available_at
                        <= available_before,
                    ),
                    sa.and_(
                        RDBRuntimeConfigurationReconcileTask.status
                        == RuntimeReconcileTaskStatus.RUNNING,
                        RDBRuntimeConfigurationReconcileTask.updated_at
                        <= reclaim_running_before,
                    ),
                ),
            )
            .order_by(
                RDBRuntimeConfigurationReconcileTask.available_at,
                RDBRuntimeConfigurationReconcileTask.id,
            )
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        tasks = list(result.scalars())
        claimed_at = tznow()
        for task in tasks:
            task.status = RuntimeReconcileTaskStatus.RUNNING
            task.attempt += 1
            task.failure_code = None
            task.updated_at = claimed_at
        await session.flush()
        return [self._build_reconcile_task(task) for task in tasks]

    async def complete_reconcile_task(
        self,
        session: AsyncSession,
        *,
        task_id: str,
        expected_attempt: int,
        cursor: str | None,
    ) -> bool:
        """Complete one currently owned reconcile-task attempt."""
        result = await session.execute(
            sa.update(RDBRuntimeConfigurationReconcileTask)
            .where(
                RDBRuntimeConfigurationReconcileTask.id == task_id,
                RDBRuntimeConfigurationReconcileTask.status
                == RuntimeReconcileTaskStatus.RUNNING,
                RDBRuntimeConfigurationReconcileTask.attempt == expected_attempt,
            )
            .values(
                status=RuntimeReconcileTaskStatus.COMPLETED,
                cursor=cursor,
                failure_code=None,
                updated_at=sa.func.now(),
            )
            .returning(RDBRuntimeConfigurationReconcileTask.id)
        )
        return result.scalar_one_or_none() is not None

    async def continue_reconcile_task(
        self,
        session: AsyncSession,
        *,
        task_id: str,
        expected_attempt: int,
        cursor: str,
        available_at: datetime.datetime,
    ) -> bool:
        """Persist one page only while its reconcile-task attempt is owned."""
        result = await session.execute(
            sa.update(RDBRuntimeConfigurationReconcileTask)
            .where(
                RDBRuntimeConfigurationReconcileTask.id == task_id,
                RDBRuntimeConfigurationReconcileTask.status
                == RuntimeReconcileTaskStatus.RUNNING,
                RDBRuntimeConfigurationReconcileTask.attempt == expected_attempt,
            )
            .values(
                status=RuntimeReconcileTaskStatus.PENDING,
                cursor=cursor,
                available_at=available_at,
                failure_code=None,
                updated_at=sa.func.now(),
            )
            .returning(RDBRuntimeConfigurationReconcileTask.id)
        )
        return result.scalar_one_or_none() is not None

    async def retry_reconcile_task(
        self,
        session: AsyncSession,
        *,
        task_id: str,
        expected_attempt: int,
        cursor: str | None,
        available_at: datetime.datetime,
        failure_code: str,
    ) -> bool:
        """Retry one task only while its claimed attempt is still owned."""
        result = await session.execute(
            sa.update(RDBRuntimeConfigurationReconcileTask)
            .where(
                RDBRuntimeConfigurationReconcileTask.id == task_id,
                RDBRuntimeConfigurationReconcileTask.status
                == RuntimeReconcileTaskStatus.RUNNING,
                RDBRuntimeConfigurationReconcileTask.attempt == expected_attempt,
            )
            .values(
                status=RuntimeReconcileTaskStatus.RETRY_WAIT,
                cursor=cursor,
                available_at=available_at,
                failure_code=failure_code,
                updated_at=sa.func.now(),
            )
            .returning(RDBRuntimeConfigurationReconcileTask.id)
        )
        return result.scalar_one_or_none() is not None

    async def get_reconcile_source_version(
        self,
        session: AsyncSession,
        *,
        source_type: RuntimeReconcileSourceKind,
        source_id: str,
    ) -> str | None:
        """Return the current monotonic version for one reconcile source."""
        if source_type is RuntimeReconcileSourceKind.AGENT_SELECTION:
            version = await session.scalar(
                sa.select(RDBAgent.runtime_profile_selection_version).where(
                    RDBAgent.id == source_id
                )
            )
            return str(version) if version is not None else None
        if source_type is RuntimeReconcileSourceKind.WORKSPACE_RUNTIME_PROFILE:
            version = await session.scalar(
                sa.select(RDBWorkspaceRuntimeProfile.version).where(
                    RDBWorkspaceRuntimeProfile.id == source_id
                )
            )
            return str(version) if version is not None else None
        if source_type is RuntimeReconcileSourceKind.INFRASTRUCTURE_PROFILE:
            version = await session.scalar(
                sa.select(RDBRuntimeInfrastructureProfile.version).where(
                    RDBRuntimeInfrastructureProfile.id == source_id
                )
            )
            return str(version) if version is not None else None
        if source_type is RuntimeReconcileSourceKind.PROVIDER:
            version = await session.scalar(
                sa.select(RDBRuntimeProvider.admin_version).where(
                    RDBRuntimeProvider.id == source_id
                )
            )
            return str(version) if version is not None else None
        if source_type is RuntimeReconcileSourceKind.PROVIDER_CAPABILITY:
            revision_id = await session.scalar(
                sa.select(RDBRuntimeProvider.current_contract_revision_id).where(
                    RDBRuntimeProvider.id == source_id
                )
            )
            return str(revision_id) if revision_id is not None else None
        raise AssertionError(f"Unsupported reconcile source type: {source_type}")

    async def list_affected_agent_ids(
        self,
        session: AsyncSession,
        *,
        source_type: RuntimeReconcileSourceKind,
        source_id: str,
        after_agent_id: str | None,
        limit: int,
    ) -> list[str]:
        """List one bounded page of Agents affected by an authoritative source."""
        if limit < 1:
            raise ValueError("Reconcile page limit must be positive.")
        statement = sa.select(RDBAgent.id).order_by(RDBAgent.id).limit(limit)
        if source_type is RuntimeReconcileSourceKind.AGENT_SELECTION:
            statement = statement.where(RDBAgent.id == source_id)
        elif source_type is RuntimeReconcileSourceKind.WORKSPACE_RUNTIME_PROFILE:
            statement = statement.where(RDBAgent.runtime_profile_id == source_id)
        else:
            statement = statement.join(
                RDBWorkspaceRuntimeProfile,
                RDBWorkspaceRuntimeProfile.id == RDBAgent.runtime_profile_id,
            )
            if source_type is RuntimeReconcileSourceKind.INFRASTRUCTURE_PROFILE:
                statement = statement.where(
                    RDBWorkspaceRuntimeProfile.infrastructure_profile_id == source_id
                )
            elif source_type in {
                RuntimeReconcileSourceKind.PROVIDER,
                RuntimeReconcileSourceKind.PROVIDER_CAPABILITY,
            }:
                statement = statement.where(
                    RDBWorkspaceRuntimeProfile.provider_id == source_id
                )
            else:
                raise AssertionError(
                    f"Unsupported reconcile source type: {source_type}"
                )
        if after_agent_id is not None:
            statement = statement.where(RDBAgent.id > after_agent_id)
        result = await session.execute(statement)
        return list(result.scalars())

    async def create_recreation_operation(
        self,
        session: AsyncSession,
        *,
        target_kind: RuntimeRecreationTargetKind,
        target_id: str,
        target_version: str,
        concurrency_limit: int,
        actor_user_id: str | None,
        actor_workspace_user_id: str | None,
    ) -> RuntimeRecreationOperation:
        """Create one empty authority-scoped recreation operation."""
        if concurrency_limit < 1:
            raise ValueError("Recreation concurrency limit must be positive.")
        if actor_user_id is not None and actor_workspace_user_id is not None:
            raise ValueError("Recreation operation must have one authority scope.")
        rdb = RDBRuntimeRecreationOperation(
            target_kind=target_kind,
            target_id=target_id,
            target_version=target_version,
            status=RuntimeRecreationOperationStatus.PENDING,
            concurrency_limit=concurrency_limit,
            actor_user_id=actor_user_id,
            actor_workspace_user_id=actor_workspace_user_id,
            total_count=0,
            pending_count=0,
            running_count=0,
            succeeded_count=0,
            skipped_count=0,
            failed_count=0,
            started_at=None,
            completed_at=None,
        )
        session.add(rdb)
        await session.flush()
        return self._build_recreation_operation(rdb)

    async def add_recreation_items(
        self,
        session: AsyncSession,
        *,
        operation_id: str,
        items: list[tuple[str, str]],
    ) -> list[RuntimeRecreationOperationItem]:
        """Attach a stable Runtime and expected-revision target set."""
        operation = await session.get(
            RDBRuntimeRecreationOperation,
            operation_id,
            with_for_update=True,
        )
        if (
            operation is None
            or operation.status is not RuntimeRecreationOperationStatus.PENDING
        ):
            raise ValueError("Recreation operation cannot accept more items.")
        created = [
            RDBRuntimeRecreationOperationItem(
                operation_id=operation_id,
                runtime_id=runtime_id,
                expected_configuration_revision_id=revision_id,
                status=RuntimeRecreationItemStatus.PENDING,
                attempt=0,
                failure_code=None,
                failure_message=None,
            )
            for runtime_id, revision_id in items
        ]
        session.add_all(created)
        operation.total_count += len(created)
        operation.pending_count += len(created)
        await session.flush()
        return [self._build_recreation_item(item) for item in created]

    async def claim_recreation_items(
        self,
        session: AsyncSession,
        *,
        operation_id: str,
        limit: int,
    ) -> list[RuntimeRecreationOperationItem]:
        """Claim pending recreation items without blocking peer workers."""
        if limit < 1:
            raise ValueError("Recreation claim limit must be positive.")
        operation = await session.get(
            RDBRuntimeRecreationOperation,
            operation_id,
            with_for_update=True,
        )
        if operation is None:
            return []
        if operation.status is RuntimeRecreationOperationStatus.PENDING:
            operation.status = RuntimeRecreationOperationStatus.RUNNING
            operation.started_at = tznow()
        elif operation.status is not RuntimeRecreationOperationStatus.RUNNING:
            return []
        remaining_capacity = operation.concurrency_limit - operation.running_count
        if remaining_capacity <= 0:
            return []
        result = await session.execute(
            sa.select(RDBRuntimeRecreationOperationItem)
            .where(
                RDBRuntimeRecreationOperationItem.operation_id == operation_id,
                RDBRuntimeRecreationOperationItem.status
                == RuntimeRecreationItemStatus.PENDING,
            )
            .order_by(RDBRuntimeRecreationOperationItem.id)
            .limit(min(limit, remaining_capacity))
            .with_for_update(skip_locked=True)
        )
        items = list(result.scalars())
        claimed_at = tznow()
        for item in items:
            item.status = RuntimeRecreationItemStatus.RUNNING
            item.attempt += 1
            item.failure_code = None
            item.failure_message = None
            item.updated_at = claimed_at
        operation.pending_count -= len(items)
        operation.running_count += len(items)
        await session.flush()
        return [self._build_recreation_item(item) for item in items]

    @staticmethod
    def _build_infrastructure_profile(
        rdb: RDBRuntimeInfrastructureProfile,
    ) -> RuntimeInfrastructureProfile:
        return RuntimeInfrastructureProfile(
            id=rdb.id,
            provider_id=rdb.provider_id,
            profile_kind=rdb.profile_kind,
            display_name=rdb.display_name,
            description=rdb.description,
            lifecycle=rdb.lifecycle,
            contract_family=rdb.contract_family,
            schema_version=rdb.schema_version,
            spec=rdb.spec,
            required_capabilities=tuple(rdb.required_capabilities),
            version=rdb.version,
            digest=rdb.digest,
            created_by_user_id=rdb.created_by_user_id,
            updated_by_user_id=rdb.updated_by_user_id,
            created_at=rdb.created_at,
            updated_at=rdb.updated_at,
        )

    @staticmethod
    def _build_workspace_profile(
        rdb: RDBWorkspaceRuntimeProfile,
    ) -> WorkspaceRuntimeProfile:
        return WorkspaceRuntimeProfile(
            id=rdb.id,
            workspace_id=rdb.workspace_id,
            provider_id=rdb.provider_id,
            infrastructure_profile_id=rdb.infrastructure_profile_id,
            display_name=rdb.display_name,
            description=rdb.description,
            lifecycle=rdb.lifecycle,
            policy=rdb.policy,
            version=rdb.version,
            digest=rdb.digest,
            created_by_workspace_user_id=rdb.created_by_workspace_user_id,
            updated_by_workspace_user_id=rdb.updated_by_workspace_user_id,
            created_at=rdb.created_at,
            updated_at=rdb.updated_at,
        )

    @staticmethod
    def _build_configuration_revision(
        rdb: RDBRuntimeConfigurationRevision,
    ) -> RuntimeConfigurationRevision:
        return RuntimeConfigurationRevision(
            id=rdb.id,
            runtime_id=rdb.runtime_id,
            provider_id=rdb.provider_id,
            provider_capability_revision_id=rdb.provider_capability_revision_id,
            infrastructure_profile_id=rdb.infrastructure_profile_id,
            infrastructure_profile_version=rdb.infrastructure_profile_version,
            workspace_runtime_profile_id=rdb.workspace_runtime_profile_id,
            workspace_runtime_profile_version=rdb.workspace_runtime_profile_version,
            agent_selection_version=rdb.agent_selection_version,
            resolution_status=rdb.resolution_status,
            reason_code=rdb.reason_code,
            required_capabilities=tuple(rdb.required_capabilities),
            missing_capabilities=tuple(rdb.missing_capabilities),
            resolved_configuration=rdb.resolved_configuration,
            source_trace=rdb.source_trace,
            digest=rdb.digest,
            target_desired_generation=rdb.target_desired_generation,
            provider_reported_digest=rdb.provider_reported_digest,
            runner_reported_digest=rdb.runner_reported_digest,
            provider_acknowledged_at=rdb.provider_acknowledged_at,
            runtime_observed_at=rdb.runtime_observed_at,
            created_at=rdb.created_at,
        )

    @staticmethod
    def _build_reconcile_task(
        rdb: RDBRuntimeConfigurationReconcileTask,
    ) -> RuntimeConfigurationReconcileTask:
        return RuntimeConfigurationReconcileTask(
            id=rdb.id,
            source_type=rdb.source_type,
            source_id=rdb.source_id,
            source_version=rdb.source_version,
            cursor=rdb.cursor,
            status=rdb.status,
            attempt=rdb.attempt,
            available_at=rdb.available_at,
            failure_code=rdb.failure_code,
            created_at=rdb.created_at,
            updated_at=rdb.updated_at,
        )

    @staticmethod
    def _build_recreation_operation(
        rdb: RDBRuntimeRecreationOperation,
    ) -> RuntimeRecreationOperation:
        return RuntimeRecreationOperation(
            id=rdb.id,
            target_kind=rdb.target_kind,
            target_id=rdb.target_id,
            target_version=rdb.target_version,
            status=rdb.status,
            concurrency_limit=rdb.concurrency_limit,
            actor_user_id=rdb.actor_user_id,
            actor_workspace_user_id=rdb.actor_workspace_user_id,
            total_count=rdb.total_count,
            pending_count=rdb.pending_count,
            running_count=rdb.running_count,
            succeeded_count=rdb.succeeded_count,
            skipped_count=rdb.skipped_count,
            failed_count=rdb.failed_count,
            created_at=rdb.created_at,
            started_at=rdb.started_at,
            completed_at=rdb.completed_at,
        )

    @staticmethod
    def _build_recreation_item(
        rdb: RDBRuntimeRecreationOperationItem,
    ) -> RuntimeRecreationOperationItem:
        return RuntimeRecreationOperationItem(
            id=rdb.id,
            operation_id=rdb.operation_id,
            runtime_id=rdb.runtime_id,
            expected_configuration_revision_id=(rdb.expected_configuration_revision_id),
            status=rdb.status,
            attempt=rdb.attempt,
            failure_code=rdb.failure_code,
            failure_message=rdb.failure_message,
            created_at=rdb.created_at,
            updated_at=rdb.updated_at,
        )


def _configuration_evidence_matches(
    revision: RDBRuntimeConfigurationRevision,
    evidence: RuntimeExecutionPolicyEvidence,
) -> bool:
    """Validate the transitional transport envelope against one revision."""
    return (
        revision.id == evidence.snapshot_id
        and revision.target_desired_generation == evidence.desired_generation
        and revision.resolution_status is RuntimeConfigurationResolutionStatus.READY
        and revision.resolved_configuration is not None
        and evidence.digest
        == digest_runtime_execution_policy(standard_runtime_execution_policy())
        and dict(evidence.module_versions) == {"docker": 1, "runtime.resources": 1}
        and dict(evidence.source_versions)
        == {
            "profile": revision.infrastructure_profile_version,
            "workspace": revision.workspace_runtime_profile_version,
            "agent": revision.agent_selection_version,
        }
    )
