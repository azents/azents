"""Owner-scoped persistence for User-owned canonical Toolkit records."""

import dataclasses
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert

from azents.core.enums import AgentLifecycleStatus, AgentType, WorkspaceUserRole
from azents.core.personal_toolkit import (
    PersonalToolkitAccessConflict,
    PersonalToolkitAccessMutation,
    PersonalToolkitAgentIneligible,
    PersonalToolkitNotFound,
)
from azents.core.toolkit_ownership import (
    PersonalToolkitAccess,
    PersonalToolkitAccessMode,
    ToolkitOwnerKind,
    UserToolkitOwner,
)
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_admin import RDBAgentAdmin
from azents.rdb.models.toolkit import RDBPersonalToolkitAgent, RDBToolkitConfig
from azents.rdb.models.user import RDBUser
from azents.rdb.models.workspace_user import RDBWorkspaceUser
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import ReadSession, WriteSession
from azents.repos.toolkit import ToolkitRepository
from azents.repos.toolkit.data import (
    PersonalToolkitConfig,
    ToolkitCreation,
    ToolkitUpdate,
)


def active_owner_predicate(user_id: str, workspace_id: str) -> sa.ColumnElement[bool]:
    """Require exact active User ownership and ordinary Workspace membership."""
    return sa.and_(
        RDBToolkitConfig.owner_kind == ToolkitOwnerKind.USER,
        RDBToolkitConfig.owner_user_id == user_id,
        RDBToolkitConfig.workspace_id == workspace_id,
        RDBToolkitConfig.owner_agent_id.is_(None),
        sa.select(RDBUser.id)
        .where(RDBUser.id == user_id, RDBUser.access_disabled_at.is_(None))
        .exists(),
        sa.select(RDBWorkspaceUser.id)
        .where(
            RDBWorkspaceUser.workspace_id == workspace_id,
            RDBWorkspaceUser.user_id == user_id,
        )
        .exists(),
    )


def eligible_personal_agent_ids(
    user_id: str, workspace_id: str
) -> sa.Select[tuple[str]]:
    """Select ordinary-access Agents within the personal Toolkit's Workspace."""
    admin = (
        sa.select(RDBAgentAdmin.id)
        .where(
            RDBAgentAdmin.agent_id == RDBAgent.id,
            RDBAgentAdmin.workspace_user_id == RDBWorkspaceUser.id,
        )
        .correlate(RDBAgent, RDBWorkspaceUser)
        .exists()
    )
    return (
        sa.select(RDBAgent.id)
        .join(RDBWorkspaceUser, RDBWorkspaceUser.workspace_id == RDBAgent.workspace_id)
        .join(RDBUser, RDBUser.id == RDBWorkspaceUser.user_id)
        .where(
            RDBUser.id == user_id,
            RDBUser.access_disabled_at.is_(None),
            RDBAgent.workspace_id == workspace_id,
            RDBAgent.lifecycle_status == AgentLifecycleStatus.ACTIVE,
            sa.or_(
                RDBWorkspaceUser.role == WorkspaceUserRole.OWNER,
                RDBAgent.type == AgentType.PUBLIC,
                admin,
            ),
        )
    )


class PersonalToolkitRepository(ToolkitRepository):
    """Reuse canonical configuration/encryption with exact User ownership guards."""

    async def create_personal(
        self,
        session: WriteSession,
        *,
        user_id: str,
        workspace_id: str,
        create: ToolkitCreation,
    ) -> PersonalToolkitConfig:
        """Create a canonical record with an explicit dynamic All policy."""
        active = await session.read_session.scalar(
            sa.select(RDBUser.id)
            .join(RDBWorkspaceUser, RDBWorkspaceUser.user_id == RDBUser.id)
            .where(
                RDBUser.id == user_id,
                RDBUser.access_disabled_at.is_(None),
                RDBWorkspaceUser.workspace_id == workspace_id,
            )
        )
        if active is None:
            raise PersonalToolkitNotFound("Active personal Toolkit owner not found")
        row = RDBToolkitConfig(
            workspace_id=workspace_id,
            owner_kind=ToolkitOwnerKind.USER,
            owner_agent_id=None,
            owner_user_id=user_id,
            personal_access_mode=PersonalToolkitAccessMode.ALL,
            toolkit_type=create.toolkit_type,
            slug=create.slug,
            name=create.name,
            config=create.config,
            description=create.description,
            prompt=create.prompt,
            encrypted_credentials=self._encrypt(create.credentials),
            enabled=create.enabled,
            always_expose_tools=create.always_expose_tools,
        )
        session.write_session.add(row)
        await session.write_session.flush()
        return self._build_personal(row)

    async def list_personal(
        self, session: ReadSession, *, user_id: str, workspace_id: str
    ) -> list[PersonalToolkitConfig]:
        """List this owner's personal connections in this Workspace."""
        rows = await session.read_session.scalars(
            sa.select(RDBToolkitConfig)
            .where(active_owner_predicate(user_id, workspace_id))
            .order_by(RDBToolkitConfig.created_at.desc(), RDBToolkitConfig.id)
        )
        return [self._build_personal(row) for row in rows]

    async def get_personal(
        self, session: ReadSession, *, user_id: str, workspace_id: str, toolkit_id: str
    ) -> PersonalToolkitConfig | None:
        """Read one exact personal target, excluding shared and foreign IDs."""
        row = await session.read_session.scalar(
            sa.select(RDBToolkitConfig).where(
                RDBToolkitConfig.id == toolkit_id,
                active_owner_predicate(user_id, workspace_id),
            )
        )
        return None if row is None else self._build_personal(row)

    async def lock_personal(
        self, session: WriteSession, *, user_id: str, workspace_id: str, toolkit_id: str
    ) -> RDBToolkitConfig:
        """Serialize policy and later dispatch admission on the canonical parent."""
        row = await session.write_session.scalar(
            sa.select(RDBToolkitConfig)
            .where(
                RDBToolkitConfig.id == toolkit_id,
                active_owner_predicate(user_id, workspace_id),
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if row is None:
            raise PersonalToolkitNotFound("Personal Toolkit not found")
        return row

    async def update_personal(
        self,
        session: WriteSession,
        *,
        user_id: str,
        workspace_id: str,
        toolkit_id: str,
        update: ToolkitUpdate,
    ) -> PersonalToolkitConfig:
        """Update common configuration while preserving owner and permission state."""
        row = await self.lock_personal(
            session, user_id=user_id, workspace_id=workspace_id, toolkit_id=toolkit_id
        )
        values = dict(update)
        if "credentials" in values:
            credentials = update["credentials"]
            del values["credentials"]
            values["encrypted_credentials"] = self._encrypt(credentials)
        values["revision"] = RDBToolkitConfig.revision + 1
        result = await session.write_session.scalar(
            sa.update(RDBToolkitConfig)
            .where(
                RDBToolkitConfig.id == row.id,
                active_owner_predicate(user_id, workspace_id),
            )
            .values(**values)
            .returning(RDBToolkitConfig)
            .execution_options(populate_existing=True)
        )
        if result is None:
            raise PersonalToolkitNotFound("Personal Toolkit not found")
        return self._build_personal(result)

    async def delete_personal(
        self, session: WriteSession, *, user_id: str, workspace_id: str, toolkit_id: str
    ) -> None:
        """Delete the exact owned parent and its dependent grants/memberships."""
        row = await self.lock_personal(
            session, user_id=user_id, workspace_id=workspace_id, toolkit_id=toolkit_id
        )
        await session.write_session.delete(row)
        await session.write_session.flush()

    async def read_access(
        self, session: ReadSession, *, user_id: str, workspace_id: str, toolkit_id: str
    ) -> PersonalToolkitAccess | None:
        """Read parent and membership in one statement-consistent snapshot."""
        rows = (
            await session.read_session.execute(
                sa.select(
                    RDBToolkitConfig.personal_access_mode,
                    RDBPersonalToolkitAgent.agent_id,
                )
                .outerjoin(
                    RDBPersonalToolkitAgent,
                    RDBPersonalToolkitAgent.toolkit_id == RDBToolkitConfig.id,
                )
                .where(
                    RDBToolkitConfig.id == toolkit_id,
                    active_owner_predicate(user_id, workspace_id),
                )
                .order_by(RDBPersonalToolkitAgent.agent_id)
            )
        ).all()
        if not rows:
            return None
        mode = rows[0].personal_access_mode
        if mode is None:
            raise ValueError("User-owned Toolkit requires a personal access mode")
        return PersonalToolkitAccess(
            toolkit_id=toolkit_id,
            owner_user_id=user_id,
            workspace_id=workspace_id,
            mode=mode,
            selected_agent_ids=tuple(
                row.agent_id for row in rows if row.agent_id is not None
            ),
        )

    async def mutate_access(
        self,
        session: WriteSession,
        *,
        user_id: str,
        workspace_id: str,
        mutation: PersonalToolkitAccessMutation,
    ) -> PersonalToolkitAccess:
        """Apply intent, snapshotting All under the parent lock on restriction."""
        row = await self.lock_personal(
            session,
            user_id=user_id,
            workspace_id=workspace_id,
            toolkit_id=mutation.toolkit_id,
        )
        if row.personal_access_mode is not mutation.expected_mode:
            raise PersonalToolkitAccessConflict(
                "Personal Toolkit access mode changed; reload before saving"
            )
        eligible = set(
            await session.read_session.scalars(
                eligible_personal_agent_ids(user_id, workspace_id)
            )
        )
        if not (mutation.allow_agent_ids | mutation.restrict_agent_ids) <= eligible:
            raise PersonalToolkitAgentIneligible("Agent is not currently accessible")
        if mutation.mode is PersonalToolkitAccessMode.ALL:
            await session.write_session.execute(
                sa.delete(RDBPersonalToolkitAgent).where(
                    RDBPersonalToolkitAgent.toolkit_id == row.id
                )
            )
            row.personal_access_mode = PersonalToolkitAccessMode.ALL
        else:
            transition = row.personal_access_mode is PersonalToolkitAccessMode.ALL and (
                mutation.mode is PersonalToolkitAccessMode.SELECTED
                or bool(mutation.restrict_agent_ids)
            )
            if transition:
                row.personal_access_mode = PersonalToolkitAccessMode.SELECTED
                additions = eligible - mutation.restrict_agent_ids
            elif row.personal_access_mode is PersonalToolkitAccessMode.SELECTED:
                additions = mutation.allow_agent_ids
            else:
                additions = frozenset()
            if mutation.restrict_agent_ids:
                await session.write_session.execute(
                    sa.delete(RDBPersonalToolkitAgent).where(
                        RDBPersonalToolkitAgent.toolkit_id == row.id,
                        RDBPersonalToolkitAgent.agent_id.in_(
                            mutation.restrict_agent_ids
                        ),
                    )
                )
            if additions:
                await session.write_session.execute(
                    insert(RDBPersonalToolkitAgent)
                    .values(
                        [
                            {
                                "toolkit_id": row.id,
                                "owner_user_id": user_id,
                                "workspace_id": workspace_id,
                                "agent_id": agent_id,
                            }
                            for agent_id in sorted(additions)
                        ]
                    )
                    .on_conflict_do_nothing(index_elements=["toolkit_id", "agent_id"])
                )
        row.revision += 1
        await session.write_session.flush()
        access = await self.read_access(
            session, user_id=user_id, workspace_id=workspace_id, toolkit_id=row.id
        )
        if access is None:
            raise PersonalToolkitNotFound("Personal Toolkit not found")
        return access

    def _build_personal(self, row: RDBToolkitConfig) -> PersonalToolkitConfig:
        if row.owner_user_id is None or row.personal_access_mode is None:
            raise ValueError("Expected a User-owned Toolkit")
        return PersonalToolkitConfig(
            id=row.id,
            owner=UserToolkitOwner(
                kind=ToolkitOwnerKind.USER,
                user_id=row.owner_user_id,
                workspace_id=row.workspace_id,
            ),
            access_mode=row.personal_access_mode,
            toolkit_type=row.toolkit_type,
            slug=row.slug,
            name=row.name,
            description=row.description,
            config=row.config,
            prompt=row.prompt,
            credentials=self._decrypt(row.encrypted_credentials),
            enabled=row.enabled,
            always_expose_tools=row.always_expose_tools,
            revision=row.revision,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )


@dataclasses.dataclass(frozen=True)
class PersonalToolkitOperations:
    """Own completed database-only transactions for both personal editors."""

    session_manager: SessionManager[WriteSession]
    repository: PersonalToolkitRepository

    async def create(
        self, *, user_id: str, workspace_id: str, create: ToolkitCreation
    ) -> PersonalToolkitConfig:
        """Commit one owner-scoped canonical creation."""
        async with self.session_manager() as session:
            return await self.repository.create_personal(
                session, user_id=user_id, workspace_id=workspace_id, create=create
            )

    async def list_personal(
        self, *, user_id: str, workspace_id: str
    ) -> list[PersonalToolkitConfig]:
        """Return detached User-owned configuration after closing the read."""
        async with self.session_manager() as session:
            return await self.repository.list_personal(
                session, user_id=user_id, workspace_id=workspace_id
            )

    async def get(
        self, *, user_id: str, workspace_id: str, toolkit_id: str
    ) -> PersonalToolkitConfig | None:
        """Return only the exact owner's current target."""
        async with self.session_manager() as session:
            return await self.repository.get_personal(
                session,
                user_id=user_id,
                workspace_id=workspace_id,
                toolkit_id=toolkit_id,
            )

    async def update(
        self, *, user_id: str, workspace_id: str, toolkit_id: str, update: ToolkitUpdate
    ) -> PersonalToolkitConfig:
        """Commit configuration without replacing permission state."""
        async with self.session_manager() as session:
            return await self.repository.update_personal(
                session,
                user_id=user_id,
                workspace_id=workspace_id,
                toolkit_id=toolkit_id,
                update=update,
            )

    async def delete(self, *, user_id: str, workspace_id: str, toolkit_id: str) -> None:
        """Commit exact-owner deletion and existing dependent cascades."""
        async with self.session_manager() as session:
            await self.repository.delete_personal(
                session,
                user_id=user_id,
                workspace_id=workspace_id,
                toolkit_id=toolkit_id,
            )

    async def read_access(
        self, *, user_id: str, workspace_id: str, toolkit_id: str
    ) -> PersonalToolkitAccess | None:
        """Return one statement-consistent snapshot after closing the read."""
        async with self.session_manager() as session:
            return await self.repository.read_access(
                session,
                user_id=user_id,
                workspace_id=workspace_id,
                toolkit_id=toolkit_id,
            )

    async def mutate_access(
        self,
        *,
        user_id: str,
        workspace_id: str,
        mutations: Sequence[PersonalToolkitAccessMutation],
    ) -> list[PersonalToolkitAccess]:
        """Commit every requested connection or none, locking parents in ID order."""
        by_id = {mutation.toolkit_id: mutation for mutation in mutations}
        if len(by_id) != len(mutations):
            raise ValueError("Duplicate Toolkit mutation")
        async with self.session_manager() as session:
            results = [
                await self.repository.mutate_access(
                    session,
                    user_id=user_id,
                    workspace_id=workspace_id,
                    mutation=by_id[toolkit_id],
                )
                for toolkit_id in sorted(by_id)
            ]
        return results
