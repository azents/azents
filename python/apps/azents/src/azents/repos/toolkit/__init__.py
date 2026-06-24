"""Toolkit repository."""

import sqlalchemy as sa
from azcommon.result import Failure, Result, Success
from azcommon.sqlalchemy.postgres import is_constrained_by
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.crypto import CredentialCipher
from azents.core.enums import ToolkitScopeType
from azents.rdb.models.toolkit import (
    RDBAgentToolkit,
    RDBToolkitConfig,
    RDBToolkitScope,
)
from azents.rdb.models.workspace_user import RDBWorkspaceUser

from .data import (
    AgentToolkit,
    AgentToolkitCreate,
    AgentToolkitNotFound,
    DuplicateAgentToolkit,
    DuplicateScope,
    DuplicateSlug,
    NotFound,
    ScopeNotFound,
    ToolkitConfig,
    ToolkitCreate,
    ToolkitScope,
    ToolkitScopeCreate,
    ToolkitUpdate,
)


class ToolkitRepository:
    """Toolkit CRUD repository."""

    def __init__(self, cipher: CredentialCipher | None = None) -> None:
        """
        :param cipher: Credential encryption/decryption object. Required for
            credentials read/write.
        """
        self._cipher = cipher

    async def create(
        self,
        session: AsyncSession,
        create: ToolkitCreate,
    ) -> Result[ToolkitConfig, DuplicateSlug]:
        """Create Toolkit.

        :param session: Database session
        :param create: Create data
        :return: Created Toolkit or error
        """
        try:
            rdb_toolkit = RDBToolkitConfig(
                workspace_id=create.workspace_id,
                toolkit_type=create.toolkit_type,
                slug=create.slug,
                name=create.name,
                description=create.description,
                config=create.config,
                prompt=create.prompt,
                encrypted_credentials=self._encrypt(create.credentials),
                enabled=create.enabled,
            )
            session.add(rdb_toolkit)
            await session.flush()
            return Success(self._build(rdb_toolkit))
        except IntegrityError as e:
            await session.rollback()
            if is_constrained_by(e, RDBToolkitConfig.UQ_WORKSPACE_SLUG):
                return Failure(
                    DuplicateSlug(
                        workspace_id=create.workspace_id,
                        slug=create.slug,
                    )
                )
            raise

    async def get_by_id(
        self, session: AsyncSession, toolkit_id: str
    ) -> ToolkitConfig | None:
        """Fetch Toolkit by ID.

        :param session: Database session
        :param toolkit_id: Toolkit ID
        :return: Toolkit or None
        """
        rdb = await session.get(RDBToolkitConfig, toolkit_id)
        if rdb is None:
            return None
        return self._build(rdb)

    async def list_by_workspace(
        self, session: AsyncSession, workspace_id: str
    ) -> list[ToolkitConfig]:
        """Fetch all Toolkits in workspace.

        :param session: Database session
        :param workspace_id: Workspace ID
        :return: Toolkit list
        """
        result = await session.execute(
            sa.select(RDBToolkitConfig)
            .where(RDBToolkitConfig.workspace_id == workspace_id)
            .order_by(RDBToolkitConfig.created_at.desc())
        )
        return [self._build(rdb) for rdb in result.scalars().all()]

    async def update_by_id(
        self,
        session: AsyncSession,
        toolkit_id: str,
        update: ToolkitUpdate,
    ) -> Result[ToolkitConfig, NotFound | DuplicateSlug]:
        """Update Toolkit by ID.

        :param session: Database session
        :param toolkit_id: Toolkit ID
        :param update: Update data
        :return: Updated Toolkit or error
        """
        if not update:
            toolkit = await self.get_by_id(session, toolkit_id)
            if toolkit is None:
                return Failure(NotFound(toolkit_id=toolkit_id))
            return Success(toolkit)

        try:
            values = dict(update)
            if "credentials" in values:
                raw: str | None = values.pop("credentials")  # type: ignore[assignment]  # Value type is inferred as object when converting TypedDict to dict
                values["encrypted_credentials"] = self._encrypt(raw)
            result = await session.execute(
                sa.update(RDBToolkitConfig)
                .where(RDBToolkitConfig.id == toolkit_id)
                .values(**values)
                .returning(RDBToolkitConfig)
            )
            rdb = result.scalar_one_or_none()
            if rdb is None:
                return Failure(NotFound(toolkit_id=toolkit_id))
            return Success(self._build(rdb))
        except IntegrityError as e:
            await session.rollback()
            if is_constrained_by(e, RDBToolkitConfig.UQ_WORKSPACE_SLUG):
                slug = update.get("slug", "")
                return Failure(DuplicateSlug(workspace_id="", slug=slug or ""))
            raise

    async def delete_by_id(self, session: AsyncSession, toolkit_id: str) -> None:
        """Delete Toolkit by ID.

        :param session: Database session
        :param toolkit_id: Toolkit ID
        """
        await session.execute(
            sa.delete(RDBToolkitConfig).where(RDBToolkitConfig.id == toolkit_id)
        )

    async def update_credentials(
        self,
        session: AsyncSession,
        toolkit_id: str,
        credentials: BaseModel,
    ) -> None:
        """Update encrypted credentials of Toolkit.

        :param session: Database session
        :param toolkit_id: Toolkit ID
        :param credentials: New credentials model
        """
        encrypted = self._encrypt(credentials.model_dump_json())
        stmt = (
            sa.update(RDBToolkitConfig)
            .where(RDBToolkitConfig.id == toolkit_id)
            .values(encrypted_credentials=encrypted)
        )
        await session.execute(stmt)

    async def list_available_for_workspace_user(
        self,
        session: AsyncSession,
        workspace_id: str,
        user_id: str,
    ) -> list[ToolkitConfig]:
        """Fetch Toolkits available to workspace user.

        Return enabled WORKSPACE-scoped Toolkits for workspace members.

        :param session: Database session
        :param workspace_id: Workspace ID
        :param user_id: User ID
        :return: Available Toolkit list
        """
        workspace_user_exists = (
            sa.select(RDBWorkspaceUser.id)
            .where(
                RDBWorkspaceUser.user_id == user_id,
                RDBWorkspaceUser.workspace_id == workspace_id,
            )
            .exists()
        )
        stmt = (
            sa.select(RDBToolkitConfig)
            .join(RDBToolkitScope, RDBToolkitScope.toolkit_id == RDBToolkitConfig.id)
            .where(
                workspace_user_exists,
                RDBToolkitConfig.workspace_id == workspace_id,
                RDBToolkitConfig.enabled == True,  # noqa: E712
                RDBToolkitScope.scope_type == ToolkitScopeType.WORKSPACE,
                RDBToolkitScope.scope_id == workspace_id,
            )
            .distinct()
            .order_by(RDBToolkitConfig.created_at.desc())
        )
        result = await session.execute(stmt)
        return [self._build(rdb) for rdb in result.scalars().all()]

    def _encrypt(self, plaintext: str | None) -> str | None:
        """Encrypt plaintext. Return None when None."""
        if plaintext is None:
            return None
        if self._cipher is None:
            msg = "cipher is required to encrypt credentials"
            raise RuntimeError(msg)
        return self._cipher.encrypt(plaintext)

    def _decrypt(self, ciphertext: str | None) -> str | None:
        """Decrypt ciphertext. Return None when None."""
        if ciphertext is None:
            return None
        if self._cipher is None:
            return None
        return self._cipher.decrypt(ciphertext)

    def _build(self, rdb: RDBToolkitConfig) -> ToolkitConfig:
        """Convert RDB model to domain model."""
        return ToolkitConfig(
            id=rdb.id,
            workspace_id=rdb.workspace_id,
            toolkit_type=rdb.toolkit_type,
            slug=rdb.slug,
            name=rdb.name,
            description=rdb.description,
            config=rdb.config,
            prompt=rdb.prompt,
            credentials=self._decrypt(rdb.encrypted_credentials),
            enabled=rdb.enabled,
            created_at=rdb.created_at,
            updated_at=rdb.updated_at,
        )


class ToolkitScopeRepository:
    """ToolkitScope repository."""

    async def create(
        self,
        session: AsyncSession,
        create: ToolkitScopeCreate,
    ) -> Result[ToolkitScope, DuplicateScope]:
        """Create ToolkitScope.

        :param session: Database session
        :param create: Create data
        :return: Created ToolkitScope or error
        """
        try:
            rdb_scope = RDBToolkitScope(
                toolkit_id=create.toolkit_id,
                scope_type=create.scope_type,
                scope_id=create.scope_id,
            )
            session.add(rdb_scope)
            await session.flush()
            return Success(self._build(rdb_scope))
        except IntegrityError as e:
            await session.rollback()
            if is_constrained_by(e, RDBToolkitScope.UQ_TOOLKIT_SCOPE):
                return Failure(
                    DuplicateScope(
                        toolkit_id=create.toolkit_id,
                        scope_type=create.scope_type,
                        scope_id=create.scope_id,
                    )
                )
            raise

    async def list_by_toolkit(
        self, session: AsyncSession, toolkit_id: str
    ) -> list[ToolkitScope]:
        """Fetch all Scopes of Toolkit.

        :param session: Database session
        :param toolkit_id: Toolkit ID
        :return: ToolkitScope list
        """
        result = await session.execute(
            sa.select(RDBToolkitScope)
            .where(RDBToolkitScope.toolkit_id == toolkit_id)
            .order_by(RDBToolkitScope.created_at.asc())
        )
        return [self._build(rdb) for rdb in result.scalars().all()]

    async def get_by_id(
        self, session: AsyncSession, scope_id: str
    ) -> ToolkitScope | None:
        """Fetch ToolkitScope by ID.

        :param session: Database session
        :param scope_id: Scope ID
        :return: ToolkitScope or None
        """
        rdb = await session.get(RDBToolkitScope, scope_id)
        if rdb is None:
            return None
        return self._build(rdb)

    async def delete_by_id(self, session: AsyncSession, scope_id: str) -> None:
        """Delete ToolkitScope by ID.

        :param session: Database session
        :param scope_id: Scope ID
        """
        await session.execute(
            sa.delete(RDBToolkitScope).where(RDBToolkitScope.id == scope_id)
        )

    def _build(self, rdb: RDBToolkitScope) -> ToolkitScope:
        """Convert RDB model to domain model."""
        return ToolkitScope(
            id=rdb.id,
            toolkit_id=rdb.toolkit_id,
            scope_type=rdb.scope_type,
            scope_id=rdb.scope_id,
            created_at=rdb.created_at,
        )


class AgentToolkitRepository:
    """AgentToolkit repository."""

    async def create(
        self,
        session: AsyncSession,
        create: AgentToolkitCreate,
    ) -> Result[AgentToolkit, DuplicateAgentToolkit]:
        """AgentCreate Toolkit.

        :param session: Database session
        :param create: Create data
        :return: Created AgentToolkit or error
        """
        try:
            rdb_agent_toolkit = RDBAgentToolkit(
                agent_id=create.agent_id,
                toolkit_id=create.toolkit_id,
                toolkit_type=create.toolkit_type,
            )
            session.add(rdb_agent_toolkit)
            await session.flush()
            return Success(self._build(rdb_agent_toolkit))
        except IntegrityError as e:
            await session.rollback()
            if is_constrained_by(e, RDBAgentToolkit.UQ_AGENT_TOOLKIT):
                return Failure(
                    DuplicateAgentToolkit(
                        agent_id=create.agent_id,
                        toolkit_id=create.toolkit_id,
                    )
                )
            raise

    async def list_by_agent(
        self, session: AsyncSession, agent_id: str
    ) -> list[AgentToolkit]:
        """Fetch all AgentToolkits of agent.

        :param session: Database session
        :param agent_id: Agent ID
        :return: AgentToolkit list
        """
        result = await session.execute(
            sa.select(RDBAgentToolkit)
            .where(RDBAgentToolkit.agent_id == agent_id)
            .order_by(RDBAgentToolkit.created_at.asc())
        )
        return [self._build(rdb) for rdb in result.scalars().all()]

    async def get_by_id(
        self, session: AsyncSession, agent_toolkit_id: str
    ) -> AgentToolkit | None:
        """Fetch AgentToolkit by ID.

        :param session: Database session
        :param agent_toolkit_id: AgentToolkit ID
        :return: AgentToolkit or None
        """
        rdb = await session.get(RDBAgentToolkit, agent_toolkit_id)
        if rdb is None:
            return None
        return self._build(rdb)

    async def delete_by_id(self, session: AsyncSession, agent_toolkit_id: str) -> None:
        """Delete AgentToolkit by ID.

        :param session: Database session
        :param agent_toolkit_id: AgentToolkit ID
        """
        await session.execute(
            sa.delete(RDBAgentToolkit).where(RDBAgentToolkit.id == agent_toolkit_id)
        )

    def _build(self, rdb: RDBAgentToolkit) -> AgentToolkit:
        """Convert RDB model to domain model."""
        return AgentToolkit(
            id=rdb.id,
            agent_id=rdb.agent_id,
            toolkit_id=rdb.toolkit_id,
            toolkit_type=rdb.toolkit_type,
            created_at=rdb.created_at,
        )


# Re-export AgentToolkitNotFound as repo-layer error
__all__ = [
    "AgentToolkitRepository",
    "ToolkitRepository",
    "ToolkitScopeRepository",
    "AgentToolkitNotFound",
    "DuplicateAgentToolkit",
    "ScopeNotFound",
]
