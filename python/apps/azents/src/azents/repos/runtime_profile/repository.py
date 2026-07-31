"""Runtime Profile, reconciliation, and recreation persistence."""

import datetime

import sqlalchemy as sa
from azcommon.datetime import tznow
from azcommon.uuid import uuid7
from azents_runtime_control.runtime_configuration import RuntimeConfigurationEvidence
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

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

    async def configuration_evidence_matches_current(
        self,
        session: AsyncSession,
        *,
        runtime_id: str,
        provider_id: str,
        evidence: RuntimeConfigurationEvidence,
    ) -> bool:
        """Return whether evidence identifies the exact current desired revision."""
        runtime_result = await session.execute(
            sa.select(RDBAgentRuntime.id).where(
                RDBAgentRuntime.id == runtime_id,
                RDBAgentRuntime.runtime_provider_resource_id == provider_id,
                RDBAgentRuntime.desired_runtime_configuration_revision_id
                == evidence.revision_id,
                RDBAgentRuntime.desired_generation == evidence.desired_generation,
            )
        )
        if runtime_result.scalar_one_or_none() is None:
            return False
        revision = await self.get_configuration_revision(
            session,
            revision_id=evidence.revision_id,
        )
        return revision is not None and _configuration_evidence_matches(
            revision,
            runtime_id=runtime_id,
            provider_id=provider_id,
            evidence=evidence,
        )

    async def configuration_evidence_matches_applied(
        self,
        session: AsyncSession,
        *,
        runtime_id: str,
        provider_id: str,
        evidence: RuntimeConfigurationEvidence,
    ) -> bool:
        """Return whether evidence identifies the exact applied revision."""
        runtime_result = await session.execute(
            sa.select(RDBAgentRuntime.id).where(
                RDBAgentRuntime.id == runtime_id,
                RDBAgentRuntime.runtime_provider_resource_id == provider_id,
                RDBAgentRuntime.applied_runtime_configuration_revision_id
                == evidence.revision_id,
                RDBAgentRuntime.desired_generation == evidence.desired_generation,
            )
        )
        if runtime_result.scalar_one_or_none() is None:
            return False
        revision = await self.get_configuration_revision(
            session,
            revision_id=evidence.revision_id,
        )
        return revision is not None and _configuration_evidence_matches(
            revision,
            runtime_id=runtime_id,
            provider_id=provider_id,
            evidence=evidence,
        )

    async def record_provider_configuration_evidence(
        self,
        session: AsyncSession,
        *,
        runtime_id: str,
        provider_id: str,
        evidence: RuntimeConfigurationEvidence,
        acknowledged_at: datetime.datetime,
    ) -> RuntimeConfigurationRevision | None:
        """Record exact Provider evidence and promote after Runner evidence."""
        revision = await self._lock_current_configuration_evidence(
            session,
            runtime_id=runtime_id,
            provider_id=provider_id,
            evidence=evidence,
        )
        if revision is None:
            return None
        await session.execute(
            sa.update(RDBRuntimeConfigurationRevision)
            .where(RDBRuntimeConfigurationRevision.id == evidence.revision_id)
            .values(
                provider_reported_digest=evidence.digest,
                provider_acknowledged_at=acknowledged_at,
            )
        )
        await self._promote_configuration_if_complete(
            session,
            runtime_id=runtime_id,
            provider_id=provider_id,
            evidence=evidence,
        )
        await session.flush()
        return await self.get_configuration_revision(
            session,
            revision_id=evidence.revision_id,
        )

    async def record_runner_configuration_evidence(
        self,
        session: AsyncSession,
        *,
        runtime_id: str,
        provider_id: str,
        evidence: RuntimeConfigurationEvidence,
        observed_at: datetime.datetime,
    ) -> RuntimeConfigurationRevision | None:
        """Record exact Runner evidence and promote after Provider evidence."""
        revision = await self._lock_current_configuration_evidence(
            session,
            runtime_id=runtime_id,
            provider_id=provider_id,
            evidence=evidence,
        )
        if revision is None:
            return None
        await session.execute(
            sa.update(RDBRuntimeConfigurationRevision)
            .where(RDBRuntimeConfigurationRevision.id == evidence.revision_id)
            .values(
                runner_reported_digest=evidence.digest,
                runtime_observed_at=observed_at,
            )
        )
        await self._promote_configuration_if_complete(
            session,
            runtime_id=runtime_id,
            provider_id=provider_id,
            evidence=evidence,
        )
        await session.flush()
        return await self.get_configuration_revision(
            session,
            revision_id=evidence.revision_id,
        )

    async def _lock_current_configuration_evidence(
        self,
        session: AsyncSession,
        *,
        runtime_id: str,
        provider_id: str,
        evidence: RuntimeConfigurationEvidence,
    ) -> RuntimeConfigurationRevision | None:
        runtime_result = await session.execute(
            sa.select(RDBAgentRuntime.id)
            .where(
                RDBAgentRuntime.id == runtime_id,
                RDBAgentRuntime.runtime_provider_resource_id == provider_id,
                RDBAgentRuntime.desired_runtime_configuration_revision_id
                == evidence.revision_id,
                RDBAgentRuntime.desired_generation == evidence.desired_generation,
            )
            .with_for_update()
        )
        if runtime_result.scalar_one_or_none() is None:
            return None
        revision_result = await session.execute(
            sa.select(RDBRuntimeConfigurationRevision)
            .where(RDBRuntimeConfigurationRevision.id == evidence.revision_id)
            .with_for_update()
        )
        rdb = revision_result.scalar_one_or_none()
        if rdb is None:
            return None
        revision = self._build_configuration_revision(rdb)
        if not _configuration_evidence_matches(
            revision,
            runtime_id=runtime_id,
            provider_id=provider_id,
            evidence=evidence,
        ):
            return None
        return revision

    async def _promote_configuration_if_complete(
        self,
        session: AsyncSession,
        *,
        runtime_id: str,
        provider_id: str,
        evidence: RuntimeConfigurationEvidence,
    ) -> None:
        revision_result = await session.execute(
            sa.select(RDBRuntimeConfigurationRevision.id).where(
                RDBRuntimeConfigurationRevision.id == evidence.revision_id,
                RDBRuntimeConfigurationRevision.runtime_id == runtime_id,
                RDBRuntimeConfigurationRevision.provider_id == provider_id,
                RDBRuntimeConfigurationRevision.target_desired_generation
                == evidence.desired_generation,
                RDBRuntimeConfigurationRevision.digest == evidence.digest,
                RDBRuntimeConfigurationRevision.provider_reported_digest
                == evidence.digest,
                RDBRuntimeConfigurationRevision.runner_reported_digest
                == evidence.digest,
                RDBRuntimeConfigurationRevision.provider_acknowledged_at.is_not(None),
                RDBRuntimeConfigurationRevision.runtime_observed_at.is_not(None),
            )
        )
        if revision_result.scalar_one_or_none() is None:
            return
        promoted = await session.execute(
            sa.update(RDBAgentRuntime)
            .where(
                RDBAgentRuntime.id == runtime_id,
                RDBAgentRuntime.runtime_provider_resource_id == provider_id,
                RDBAgentRuntime.desired_runtime_configuration_revision_id
                == evidence.revision_id,
                RDBAgentRuntime.desired_generation == evidence.desired_generation,
            )
            .values(
                applied_runtime_configuration_revision_id=evidence.revision_id,
            )
            .returning(RDBAgentRuntime.id)
        )
        if promoted.scalar_one_or_none() is None:
            raise RuntimeError("Applied Runtime configuration target became stale.")

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

    async def get_recreation_target_version(
        self,
        session: AsyncSession,
        *,
        target_kind: RuntimeRecreationTargetKind,
        target_id: str,
        for_share: bool,
    ) -> str | None:
        """Read one recreation target version, optionally blocking mutations."""
        if target_kind is RuntimeRecreationTargetKind.PROVIDER:
            statement = sa.select(
                RDBRuntimeProvider.admin_version,
                RDBRuntimeProvider.current_contract_revision_id,
            ).where(RDBRuntimeProvider.id == target_id)
        elif target_kind is RuntimeRecreationTargetKind.INFRASTRUCTURE_PROFILE:
            statement = sa.select(RDBRuntimeInfrastructureProfile.version).where(
                RDBRuntimeInfrastructureProfile.id == target_id
            )
        elif target_kind is RuntimeRecreationTargetKind.WORKSPACE_RUNTIME_PROFILE:
            statement = sa.select(RDBWorkspaceRuntimeProfile.version).where(
                RDBWorkspaceRuntimeProfile.id == target_id
            )
        else:
            raise AssertionError(f"Unsupported recreation target kind: {target_kind}")
        if for_share:
            statement = statement.with_for_update(read=True)
        result = await session.execute(statement)
        row = result.one_or_none()
        if row is None:
            return None
        if target_kind is RuntimeRecreationTargetKind.PROVIDER:
            admin_version, capability_revision_id = row
            return _provider_recreation_target_version(
                admin_version=admin_version,
                capability_revision_id=capability_revision_id,
            )
        return str(row[0])

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
                dispatched_generation=None,
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

    async def list_recreation_target_items(
        self,
        session: AsyncSession,
        *,
        target_kind: RuntimeRecreationTargetKind,
        target_id: str,
    ) -> list[tuple[str, str]]:
        """Snapshot configured physical Runtimes under one exact authority target."""
        statement = (
            sa.select(
                RDBAgentRuntime.id,
                RDBAgentRuntime.desired_runtime_configuration_revision_id,
            )
            .where(
                RDBAgentRuntime.desired_runtime_configuration_revision_id.is_not(None),
                RDBAgentRuntime.applied_runtime_configuration_revision_id.is_not(None),
            )
            .order_by(RDBAgentRuntime.id)
        )
        if target_kind is RuntimeRecreationTargetKind.PROVIDER:
            statement = statement.where(
                RDBAgentRuntime.runtime_provider_resource_id == target_id
            )
        elif target_kind is RuntimeRecreationTargetKind.INFRASTRUCTURE_PROFILE:
            statement = statement.where(
                RDBAgentRuntime.infrastructure_profile_id == target_id
            )
        elif target_kind is RuntimeRecreationTargetKind.WORKSPACE_RUNTIME_PROFILE:
            statement = statement.where(
                RDBAgentRuntime.workspace_runtime_profile_id == target_id
            )
        else:
            raise AssertionError(f"Unsupported recreation target kind: {target_kind}")
        result = await session.execute(statement)
        return [
            (runtime_id, revision_id)
            for runtime_id, revision_id in result.tuples()
            if revision_id is not None
        ]

    async def get_recreation_operation(
        self,
        session: AsyncSession,
        *,
        operation_id: str,
    ) -> RuntimeRecreationOperation | None:
        """Fetch one durable recreation operation."""
        rdb = await session.get(RDBRuntimeRecreationOperation, operation_id)
        return self._build_recreation_operation(rdb) if rdb is not None else None

    async def list_active_recreation_operation_ids(
        self,
        session: AsyncSession,
        *,
        limit: int,
    ) -> list[str]:
        """List pending or running operations in stable creation order."""
        if limit < 1:
            raise ValueError("Recreation operation limit must be positive.")
        result = await session.execute(
            sa.select(RDBRuntimeRecreationOperation.id)
            .where(
                RDBRuntimeRecreationOperation.status.in_(
                    (
                        RuntimeRecreationOperationStatus.PENDING,
                        RuntimeRecreationOperationStatus.RUNNING,
                    )
                )
            )
            .order_by(
                RDBRuntimeRecreationOperation.created_at,
                RDBRuntimeRecreationOperation.id,
            )
            .limit(limit)
        )
        return list(result.scalars())

    async def list_recreation_items(
        self,
        session: AsyncSession,
        *,
        operation_id: str,
        offset: int,
        limit: int,
        statuses: tuple[RuntimeRecreationItemStatus, ...] | None = None,
    ) -> list[RuntimeRecreationOperationItem]:
        """List bounded operation items, optionally filtered by status."""
        if offset < 0 or limit < 1:
            raise ValueError("Recreation item pagination is invalid.")
        statement = (
            sa.select(RDBRuntimeRecreationOperationItem)
            .where(RDBRuntimeRecreationOperationItem.operation_id == operation_id)
            .order_by(RDBRuntimeRecreationOperationItem.id)
            .offset(offset)
            .limit(limit)
        )
        if statuses is not None:
            statement = statement.where(
                RDBRuntimeRecreationOperationItem.status.in_(statuses)
            )
        result = await session.execute(statement)
        return [self._build_recreation_item(item) for item in result.scalars()]

    async def complete_empty_recreation_operation(
        self,
        session: AsyncSession,
        *,
        operation_id: str,
    ) -> bool:
        """Complete a sealed operation whose stable target set is empty."""
        result = await session.execute(
            sa.update(RDBRuntimeRecreationOperation)
            .where(
                RDBRuntimeRecreationOperation.id == operation_id,
                RDBRuntimeRecreationOperation.status
                == RuntimeRecreationOperationStatus.PENDING,
                RDBRuntimeRecreationOperation.total_count == 0,
            )
            .values(
                status=RuntimeRecreationOperationStatus.COMPLETED,
                started_at=sa.func.now(),
                completed_at=sa.func.now(),
            )
            .returning(RDBRuntimeRecreationOperation.id)
        )
        return result.scalar_one_or_none() is not None

    async def lock_recreation_item(
        self,
        session: AsyncSession,
        *,
        item_id: str,
        expected_attempt: int,
    ) -> RuntimeRecreationOperationItem | None:
        """Lock one exact running attempt without waiting on a peer worker."""
        result = await session.execute(
            sa.select(RDBRuntimeRecreationOperationItem)
            .where(
                RDBRuntimeRecreationOperationItem.id == item_id,
                RDBRuntimeRecreationOperationItem.status
                == RuntimeRecreationItemStatus.RUNNING,
                RDBRuntimeRecreationOperationItem.attempt == expected_attempt,
            )
            .with_for_update(skip_locked=True)
        )
        item = result.scalar_one_or_none()
        return self._build_recreation_item(item) if item is not None else None

    async def update_recreation_item_dispatch(
        self,
        session: AsyncSession,
        *,
        item_id: str,
        expected_attempt: int,
        configuration_revision_id: str,
        dispatched_generation: int,
    ) -> bool:
        """Record exact evidence for one generation-fenced restart dispatch."""
        result = await session.execute(
            sa.update(RDBRuntimeRecreationOperationItem)
            .where(
                RDBRuntimeRecreationOperationItem.id == item_id,
                RDBRuntimeRecreationOperationItem.status
                == RuntimeRecreationItemStatus.RUNNING,
                RDBRuntimeRecreationOperationItem.attempt == expected_attempt,
            )
            .values(
                expected_configuration_revision_id=configuration_revision_id,
                dispatched_generation=dispatched_generation,
                failure_code=None,
                failure_message=None,
                updated_at=sa.func.now(),
            )
            .returning(RDBRuntimeRecreationOperationItem.id)
        )
        return result.scalar_one_or_none() is not None

    async def finish_recreation_item(
        self,
        session: AsyncSession,
        *,
        item_id: str,
        expected_attempt: int,
        status: RuntimeRecreationItemStatus,
        failure_code: str | None,
        failure_message: str | None,
    ) -> bool:
        """Finish one running item and atomically advance aggregate counts."""
        if status not in {
            RuntimeRecreationItemStatus.SUCCEEDED,
            RuntimeRecreationItemStatus.SKIPPED,
            RuntimeRecreationItemStatus.FAILED,
        }:
            raise ValueError("Recreation item terminal status is required.")
        item = await session.scalar(
            sa.select(RDBRuntimeRecreationOperationItem)
            .where(
                RDBRuntimeRecreationOperationItem.id == item_id,
                RDBRuntimeRecreationOperationItem.status
                == RuntimeRecreationItemStatus.RUNNING,
                RDBRuntimeRecreationOperationItem.attempt == expected_attempt,
            )
            .with_for_update()
        )
        if item is None:
            return False
        operation = await session.get(
            RDBRuntimeRecreationOperation,
            item.operation_id,
            with_for_update=True,
        )
        if operation is None:
            return False
        item.status = status
        item.failure_code = failure_code
        item.failure_message = failure_message
        item.updated_at = tznow()
        operation.running_count -= 1
        if status is RuntimeRecreationItemStatus.SUCCEEDED:
            operation.succeeded_count += 1
        elif status is RuntimeRecreationItemStatus.SKIPPED:
            operation.skipped_count += 1
        else:
            operation.failed_count += 1
        self._complete_recreation_operation_if_finished(operation)
        await session.flush()
        return True

    async def retry_recreation_item(
        self,
        session: AsyncSession,
        *,
        item_id: str,
        expected_attempt: int,
        maximum_attempts: int,
        failure_code: str,
        failure_message: str,
    ) -> bool:
        """Requeue a running item or fail it after bounded attempts."""
        if maximum_attempts < 1:
            raise ValueError("Recreation maximum attempts must be positive.")
        item = await session.scalar(
            sa.select(RDBRuntimeRecreationOperationItem)
            .where(
                RDBRuntimeRecreationOperationItem.id == item_id,
                RDBRuntimeRecreationOperationItem.status
                == RuntimeRecreationItemStatus.RUNNING,
                RDBRuntimeRecreationOperationItem.attempt == expected_attempt,
            )
            .with_for_update()
        )
        if item is None:
            return False
        operation = await session.get(
            RDBRuntimeRecreationOperation,
            item.operation_id,
            with_for_update=True,
        )
        if operation is None:
            return False
        operation.running_count -= 1
        item.dispatched_generation = None
        item.failure_code = failure_code
        item.failure_message = failure_message
        item.updated_at = tznow()
        if item.attempt >= maximum_attempts:
            item.status = RuntimeRecreationItemStatus.FAILED
            operation.failed_count += 1
            self._complete_recreation_operation_if_finished(operation)
        else:
            item.status = RuntimeRecreationItemStatus.PENDING
            operation.pending_count += 1
        await session.flush()
        return True

    @staticmethod
    def _complete_recreation_operation_if_finished(
        operation: RDBRuntimeRecreationOperation,
    ) -> None:
        if operation.pending_count != 0 or operation.running_count != 0:
            return
        operation.status = (
            RuntimeRecreationOperationStatus.COMPLETED_WITH_FAILURES
            if operation.failed_count
            else RuntimeRecreationOperationStatus.COMPLETED
        )
        operation.completed_at = tznow()

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
            dispatched_generation=rdb.dispatched_generation,
            failure_code=rdb.failure_code,
            failure_message=rdb.failure_message,
            created_at=rdb.created_at,
            updated_at=rdb.updated_at,
        )


def _configuration_evidence_matches(
    revision: RuntimeConfigurationRevision,
    *,
    runtime_id: str,
    provider_id: str,
    evidence: RuntimeConfigurationEvidence,
) -> bool:
    return (
        revision.id == evidence.revision_id
        and revision.runtime_id == runtime_id
        and revision.provider_id == provider_id
        and revision.target_desired_generation == evidence.desired_generation
        and revision.digest == evidence.digest
        and revision.resolution_status is RuntimeConfigurationResolutionStatus.READY
        and revision.resolved_configuration is not None
    )


def _provider_recreation_target_version(
    *,
    admin_version: int,
    capability_revision_id: str | None,
) -> str:
    return f"{admin_version}:{capability_revision_id or '-'}"
