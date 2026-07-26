"""Persistence for current Runtime execution policy and metadata audit."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.runtime_execution_policy import (
    RUNTIME_EXECUTION_PLATFORM_POLICY_ID,
    RuntimeExecutionManagementLayer,
    RuntimeExecutionPolicyDocument,
    RuntimeExecutionPolicyRestriction,
    RuntimeExecutionProfileLifecycle,
)
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.runtime_execution_policy import (
    RDBAgentRuntimeExecutionSetting,
    RDBRuntimeExecutionPlatformPolicy,
    RDBRuntimeExecutionPolicyAuditEvent,
    RDBRuntimeExecutionProfile,
    RDBWorkspaceRuntimeExecutionPolicy,
    RDBWorkspaceRuntimeExecutionProfileAllowance,
)

from .data import (
    AgentRuntimeExecutionSetting,
    RuntimeExecutionPlatformPolicy,
    RuntimeExecutionPolicyAuditEvent,
    RuntimeExecutionPolicyAuditEventCreate,
    RuntimeExecutionProfile,
    RuntimeExecutionProfileCreate,
    WorkspaceRuntimeExecutionPolicy,
)


class RuntimeExecutionPolicyRepository:
    """Own SQLAlchemy access for the execution-policy domain."""

    async def get_platform(
        self,
        session: AsyncSession,
        *,
        for_update: bool,
    ) -> RuntimeExecutionPlatformPolicy | None:
        """Fetch the singleton Platform policy."""
        statement = sa.select(RDBRuntimeExecutionPlatformPolicy).where(
            RDBRuntimeExecutionPlatformPolicy.id == RUNTIME_EXECUTION_PLATFORM_POLICY_ID
        )
        if for_update:
            statement = statement.with_for_update()
        row = (await session.execute(statement)).scalar_one_or_none()
        return self._build_platform(row) if row is not None else None

    async def replace_platform(
        self,
        session: AsyncSession,
        *,
        expected_version: int,
        policy: RuntimeExecutionPolicyDocument,
        digest: str,
        updated_by_user_id: str | None,
    ) -> RuntimeExecutionPlatformPolicy | None:
        """Replace Platform policy only at the expected current version."""
        result = await session.execute(
            sa.update(RDBRuntimeExecutionPlatformPolicy)
            .where(
                RDBRuntimeExecutionPlatformPolicy.id
                == RUNTIME_EXECUTION_PLATFORM_POLICY_ID,
                RDBRuntimeExecutionPlatformPolicy.version == expected_version,
            )
            .values(
                version=RDBRuntimeExecutionPlatformPolicy.version + 1,
                policy=policy.model_dump(mode="json"),
                digest=digest,
                updated_by_user_id=updated_by_user_id,
            )
            .returning(RDBRuntimeExecutionPlatformPolicy)
        )
        row = result.scalar_one_or_none()
        return self._build_platform(row) if row is not None else None

    async def get_profile(
        self,
        session: AsyncSession,
        *,
        profile_id: str,
        for_update: bool,
    ) -> RuntimeExecutionProfile | None:
        """Fetch one stable Profile."""
        statement = sa.select(RDBRuntimeExecutionProfile).where(
            RDBRuntimeExecutionProfile.id == profile_id
        )
        if for_update:
            statement = statement.with_for_update()
        row = (await session.execute(statement)).scalar_one_or_none()
        return self._build_profile(row) if row is not None else None

    async def list_profiles(
        self,
        session: AsyncSession,
        *,
        include_retired: bool,
        profile_ids: frozenset[str] | None,
        offset: int,
        limit: int,
    ) -> list[RuntimeExecutionProfile]:
        """List stable Profiles with optional lifecycle and identity filters."""
        if profile_ids is not None and not profile_ids:
            return []
        statement = sa.select(RDBRuntimeExecutionProfile)
        if not include_retired:
            statement = statement.where(
                RDBRuntimeExecutionProfile.lifecycle
                == RuntimeExecutionProfileLifecycle.ACTIVE
            )
        if profile_ids is not None:
            statement = statement.where(RDBRuntimeExecutionProfile.id.in_(profile_ids))
        rows = (
            await session.scalars(
                statement.order_by(RDBRuntimeExecutionProfile.id.asc())
                .offset(offset)
                .limit(limit)
            )
        ).all()
        return [self._build_profile(row) for row in rows]

    async def create_profile(
        self,
        session: AsyncSession,
        *,
        create: RuntimeExecutionProfileCreate,
    ) -> RuntimeExecutionProfile:
        """Create an ordinary active Profile."""
        row = RDBRuntimeExecutionProfile(
            id=create.id,
            display_name=create.display_name,
            description=create.description,
            lifecycle=RuntimeExecutionProfileLifecycle.ACTIVE,
            version=1,
            policy=create.policy.model_dump(mode="json"),
            digest=create.digest,
            reserved=False,
            system_key=None,
            updated_by_user_id=create.updated_by_user_id,
        )
        session.add(row)
        await session.flush()
        return self._build_profile(row)

    async def profile_ids_exist(
        self,
        session: AsyncSession,
        *,
        profile_ids: frozenset[str],
    ) -> bool:
        """Return whether every requested Profile identity exists."""
        if not profile_ids:
            return True
        found = await session.scalars(
            sa.select(RDBRuntimeExecutionProfile.id).where(
                RDBRuntimeExecutionProfile.id.in_(profile_ids)
            )
        )
        return frozenset(found) == profile_ids

    async def replace_profile(
        self,
        session: AsyncSession,
        *,
        profile_id: str,
        expected_version: int,
        display_name: str,
        description: str,
        policy: RuntimeExecutionPolicyDocument,
        digest: str,
        updated_by_user_id: str | None,
    ) -> RuntimeExecutionProfile | None:
        """Replace one Profile only at the expected current version."""
        result = await session.execute(
            sa.update(RDBRuntimeExecutionProfile)
            .where(
                RDBRuntimeExecutionProfile.id == profile_id,
                RDBRuntimeExecutionProfile.version == expected_version,
            )
            .values(
                display_name=display_name,
                description=description,
                version=RDBRuntimeExecutionProfile.version + 1,
                policy=policy.model_dump(mode="json"),
                digest=digest,
                updated_by_user_id=updated_by_user_id,
            )
            .returning(RDBRuntimeExecutionProfile)
        )
        row = result.scalar_one_or_none()
        return self._build_profile(row) if row is not None else None

    async def retire_profile(
        self,
        session: AsyncSession,
        *,
        profile_id: str,
        expected_version: int,
        updated_by_user_id: str | None,
    ) -> RuntimeExecutionProfile | None:
        """Retire one active Profile using optimistic concurrency."""
        result = await session.execute(
            sa.update(RDBRuntimeExecutionProfile)
            .where(
                RDBRuntimeExecutionProfile.id == profile_id,
                RDBRuntimeExecutionProfile.version == expected_version,
                RDBRuntimeExecutionProfile.lifecycle
                == RuntimeExecutionProfileLifecycle.ACTIVE,
            )
            .values(
                lifecycle=RuntimeExecutionProfileLifecycle.RETIRED,
                version=RDBRuntimeExecutionProfile.version + 1,
                updated_by_user_id=updated_by_user_id,
            )
            .returning(RDBRuntimeExecutionProfile)
        )
        row = result.scalar_one_or_none()
        return self._build_profile(row) if row is not None else None

    async def get_workspace(
        self,
        session: AsyncSession,
        *,
        workspace_id: str,
        for_update: bool,
    ) -> WorkspaceRuntimeExecutionPolicy | None:
        """Fetch Workspace policy and its complete allowance set."""
        statement = sa.select(RDBWorkspaceRuntimeExecutionPolicy).where(
            RDBWorkspaceRuntimeExecutionPolicy.workspace_id == workspace_id
        )
        if for_update:
            statement = statement.with_for_update()
        row = (await session.execute(statement)).scalar_one_or_none()
        if row is None:
            return None
        allowed = await session.scalars(
            sa.select(RDBWorkspaceRuntimeExecutionProfileAllowance.profile_id).where(
                RDBWorkspaceRuntimeExecutionProfileAllowance.workspace_id
                == workspace_id
            )
        )
        return self._build_workspace(row, frozenset(allowed))

    async def replace_workspace(
        self,
        session: AsyncSession,
        *,
        workspace_id: str,
        expected_version: int,
        restriction: RuntimeExecutionPolicyRestriction,
        digest: str,
        allowed_profile_ids: frozenset[str],
        updated_by_workspace_user_id: str | None,
    ) -> WorkspaceRuntimeExecutionPolicy | None:
        """Atomically replace Workspace restrictions and allowances."""
        if expected_version == 0:
            statement = (
                insert(RDBWorkspaceRuntimeExecutionPolicy)
                .values(
                    workspace_id=workspace_id,
                    version=1,
                    restriction=restriction.model_dump(mode="json"),
                    digest=digest,
                    updated_by_workspace_user_id=updated_by_workspace_user_id,
                )
                .on_conflict_do_nothing(index_elements=["workspace_id"])
                .returning(RDBWorkspaceRuntimeExecutionPolicy)
            )
        else:
            statement = (
                sa.update(RDBWorkspaceRuntimeExecutionPolicy)
                .where(
                    RDBWorkspaceRuntimeExecutionPolicy.workspace_id == workspace_id,
                    RDBWorkspaceRuntimeExecutionPolicy.version == expected_version,
                )
                .values(
                    version=RDBWorkspaceRuntimeExecutionPolicy.version + 1,
                    restriction=restriction.model_dump(mode="json"),
                    digest=digest,
                    updated_by_workspace_user_id=updated_by_workspace_user_id,
                )
                .returning(RDBWorkspaceRuntimeExecutionPolicy)
            )
        row = (await session.execute(statement)).scalar_one_or_none()
        if row is None:
            return None
        await session.execute(
            sa.delete(RDBWorkspaceRuntimeExecutionProfileAllowance).where(
                RDBWorkspaceRuntimeExecutionProfileAllowance.workspace_id
                == workspace_id
            )
        )
        session.add_all(
            [
                RDBWorkspaceRuntimeExecutionProfileAllowance(
                    workspace_id=workspace_id,
                    profile_id=profile_id,
                )
                for profile_id in sorted(allowed_profile_ids)
            ]
        )
        await session.flush()
        return self._build_workspace(row, allowed_profile_ids)

    async def get_agent_setting(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        for_update: bool,
    ) -> AgentRuntimeExecutionSetting | None:
        """Fetch one Agent execution intent."""
        statement = sa.select(RDBAgentRuntimeExecutionSetting).where(
            RDBAgentRuntimeExecutionSetting.agent_id == agent_id
        )
        if for_update:
            statement = statement.with_for_update()
        row = (await session.execute(statement)).scalar_one_or_none()
        return self._build_agent(row) if row is not None else None

    async def get_agent_workspace_id(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
    ) -> str | None:
        """Fetch the Workspace owning one Agent execution setting."""
        return await session.scalar(
            sa.select(RDBAgent.workspace_id).where(RDBAgent.id == agent_id)
        )

    async def replace_agent_setting(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        expected_version: int,
        profile_id: str,
        restriction: RuntimeExecutionPolicyRestriction,
        digest: str,
        updated_by_workspace_user_id: str | None,
    ) -> AgentRuntimeExecutionSetting | None:
        """Replace Agent execution intent only at the expected version."""
        result = await session.execute(
            sa.update(RDBAgentRuntimeExecutionSetting)
            .where(
                RDBAgentRuntimeExecutionSetting.agent_id == agent_id,
                RDBAgentRuntimeExecutionSetting.version == expected_version,
            )
            .values(
                profile_id=profile_id,
                version=RDBAgentRuntimeExecutionSetting.version + 1,
                restriction=restriction.model_dump(mode="json"),
                digest=digest,
                updated_by_workspace_user_id=updated_by_workspace_user_id,
            )
            .returning(RDBAgentRuntimeExecutionSetting)
        )
        row = result.scalar_one_or_none()
        return self._build_agent(row) if row is not None else None

    async def append_audit_event(
        self,
        session: AsyncSession,
        *,
        create: RuntimeExecutionPolicyAuditEventCreate,
    ) -> RuntimeExecutionPolicyAuditEvent:
        """Append one metadata-only execution-policy audit event."""
        row = RDBRuntimeExecutionPolicyAuditEvent(
            event_type=create.event_type,
            management_layer=create.management_layer,
            target_id=create.target_id,
            correlation_id=create.correlation_id,
            classification=create.classification,
            changed_paths=list(create.changed_paths),
            impact_counts=create.impact_counts,
            reason_code=create.reason_code,
            outcome_code=create.outcome_code,
            metadata_=create.metadata,
            workspace_id=create.workspace_id,
            agent_id=create.agent_id,
            runtime_id=create.runtime_id,
            actor_user_id=create.actor_user_id,
            actor_workspace_user_id=create.actor_workspace_user_id,
            system_authority=create.system_authority,
            before_digest=create.before_digest,
            after_digest=create.after_digest,
        )
        session.add(row)
        await session.flush()
        return self._build_audit(row)

    async def list_audit_events(
        self,
        session: AsyncSession,
        *,
        management_layer: RuntimeExecutionManagementLayer | None,
        target_id: str | None,
        workspace_id: str | None,
        agent_id: str | None,
        offset: int,
        limit: int,
    ) -> list[RuntimeExecutionPolicyAuditEvent]:
        """List metadata-only audit events within an authorization scope."""
        statement = sa.select(RDBRuntimeExecutionPolicyAuditEvent)
        if management_layer is not None:
            statement = statement.where(
                RDBRuntimeExecutionPolicyAuditEvent.management_layer == management_layer
            )
        if target_id is not None:
            statement = statement.where(
                RDBRuntimeExecutionPolicyAuditEvent.target_id == target_id
            )
        if workspace_id is not None:
            statement = statement.where(
                RDBRuntimeExecutionPolicyAuditEvent.workspace_id == workspace_id
            )
        if agent_id is not None:
            statement = statement.where(
                RDBRuntimeExecutionPolicyAuditEvent.agent_id == agent_id
            )
        rows = (
            await session.scalars(
                statement.order_by(
                    RDBRuntimeExecutionPolicyAuditEvent.created_at.desc(),
                    RDBRuntimeExecutionPolicyAuditEvent.id.desc(),
                )
                .offset(offset)
                .limit(limit)
            )
        ).all()
        return [self._build_audit(row) for row in rows]

    @staticmethod
    def _build_platform(
        row: RDBRuntimeExecutionPlatformPolicy,
    ) -> RuntimeExecutionPlatformPolicy:
        return RuntimeExecutionPlatformPolicy(
            id=row.id,
            version=row.version,
            policy=RuntimeExecutionPolicyDocument.model_validate(row.policy),
            digest=row.digest,
            updated_by_user_id=row.updated_by_user_id,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    @staticmethod
    def _build_profile(row: RDBRuntimeExecutionProfile) -> RuntimeExecutionProfile:
        return RuntimeExecutionProfile(
            id=row.id,
            display_name=row.display_name,
            description=row.description,
            lifecycle=row.lifecycle,
            version=row.version,
            policy=RuntimeExecutionPolicyDocument.model_validate(row.policy),
            digest=row.digest,
            reserved=row.reserved,
            system_key=row.system_key,
            updated_by_user_id=row.updated_by_user_id,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    @staticmethod
    def _build_workspace(
        row: RDBWorkspaceRuntimeExecutionPolicy,
        allowed_profile_ids: frozenset[str],
    ) -> WorkspaceRuntimeExecutionPolicy:
        return WorkspaceRuntimeExecutionPolicy(
            workspace_id=row.workspace_id,
            version=row.version,
            restriction=RuntimeExecutionPolicyRestriction.model_validate(
                row.restriction
            ),
            digest=row.digest,
            allowed_profile_ids=allowed_profile_ids,
            updated_by_workspace_user_id=row.updated_by_workspace_user_id,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    @staticmethod
    def _build_agent(
        row: RDBAgentRuntimeExecutionSetting,
    ) -> AgentRuntimeExecutionSetting:
        return AgentRuntimeExecutionSetting(
            agent_id=row.agent_id,
            profile_id=row.profile_id,
            version=row.version,
            restriction=RuntimeExecutionPolicyRestriction.model_validate(
                row.restriction
            ),
            digest=row.digest,
            updated_by_workspace_user_id=row.updated_by_workspace_user_id,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    @staticmethod
    def _build_audit(
        row: RDBRuntimeExecutionPolicyAuditEvent,
    ) -> RuntimeExecutionPolicyAuditEvent:
        return RuntimeExecutionPolicyAuditEvent(
            id=row.id,
            event_type=row.event_type,
            management_layer=row.management_layer,
            target_id=row.target_id,
            correlation_id=row.correlation_id,
            classification=row.classification,
            changed_paths=tuple(row.changed_paths),
            impact_counts=row.impact_counts,
            reason_code=row.reason_code,
            outcome_code=row.outcome_code,
            metadata=row.metadata_,
            workspace_id=row.workspace_id,
            agent_id=row.agent_id,
            runtime_id=row.runtime_id,
            actor_user_id=row.actor_user_id,
            actor_workspace_user_id=row.actor_workspace_user_id,
            system_authority=row.system_authority,
            before_digest=row.before_digest,
            after_digest=row.after_digest,
            created_at=row.created_at,
        )
