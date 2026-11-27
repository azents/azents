"""Agent Vault persistence and management policy."""

from collections.abc import Mapping, Set
from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated

import sqlalchemy as sa
from cryptography.fernet import InvalidToken
from fastapi import Depends
from pydantic import SecretStr
from sqlalchemy.dialects.postgresql import insert

from azents.core.crypto import CredentialCipher
from azents.core.deps import get_credential_cipher
from azents.core.enums import AgentLifecycleStatus, WorkspaceUserRole
from azents.core.session_resource_authority import SessionResourceAuthority
from azents.rdb.deps import get_read_only_session_manager, get_session_manager
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_admin import RDBAgentAdmin
from azents.rdb.models.agent_vault_entry import RDBAgentVaultEntry
from azents.rdb.models.workspace_user import RDBWorkspaceUser
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import ReadSession, WriteSession
from azents.repos.agent_execution import AgentRunRepository
from azents.repos.agent_mutation_guard import require_active_agent
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.file_metadata_authority import (
    FileMetadataAuthorityRepository,
    FileResourceAuthority,
)


@dataclass(frozen=True)
class VaultManager:
    """Authenticated Workspace principal supplied by the management boundary."""

    workspace_id: str
    user_id: str


@dataclass(frozen=True)
class VaultEntryMetadata:
    """Safe projection without value or ciphertext."""

    name: str
    contributor_label: str


class VaultEntryMutation(StrEnum):
    """Management operation with an explicit existence precondition."""

    CREATE = "create"
    REPLACE = "replace"
    DELETE = "delete"


class VaultAccessDenied(Exception):
    """The exact target is missing or not available to this caller."""


class VaultEntryConflict(Exception):
    """An entry with this name already exists."""


class VaultEntryUnavailable(Exception):
    """The selected entry is absent or cannot be opened."""


class InvalidVaultEntry(Exception):
    """An entry could not be represented safely in the Vault."""


def _validate_name(name: str) -> None:
    if not name.strip() or len(name) > 255 or not name.isprintable():
        raise InvalidVaultEntry("Invalid Vault entry name")


@dataclass(frozen=True)
class AgentVaultRepository:
    """Own completed Vault operations and compose transactional entry writes."""

    session_manager: Annotated[
        SessionManager[WriteSession], Depends(get_session_manager)
    ]
    read_session_manager: Annotated[
        SessionManager[ReadSession], Depends(get_read_only_session_manager)
    ]
    cipher: Annotated[CredentialCipher, Depends(get_credential_cipher)]

    @staticmethod
    def _manager_agent(agent_id: str, manager: VaultManager) -> sa.Select[tuple[str]]:
        admin = sa.exists().where(
            RDBAgentAdmin.agent_id == RDBAgent.id,
            RDBAgentAdmin.workspace_user_id == RDBWorkspaceUser.id,
        )
        return (
            sa.select(RDBAgent.id)
            .join(
                RDBWorkspaceUser, RDBWorkspaceUser.workspace_id == RDBAgent.workspace_id
            )
            .where(
                RDBAgent.id == agent_id,
                RDBAgent.workspace_id == manager.workspace_id,
                RDBAgent.lifecycle_status == AgentLifecycleStatus.ACTIVE,
                RDBWorkspaceUser.user_id == manager.user_id,
                sa.or_(RDBWorkspaceUser.role == WorkspaceUserRole.OWNER, admin),
            )
        )

    async def _require_manager(
        self, session: ReadSession, *, agent_id: str, manager: VaultManager
    ) -> None:
        permitted = await session.read_session.scalar(
            self._manager_agent(agent_id, manager)
        )
        if permitted is None:
            raise VaultAccessDenied("Agent Vault not found")

    async def fence_manager_write_in_session(
        self, session: WriteSession, *, agent_id: str, manager: VaultManager
    ) -> str:
        """Lock the Agent and current membership before accepting a manager write.

        Composing request writers acquire this fence before checking their deadline.
        Agent admin changes share the Agent fence. Membership removal and role
        changes write the membership row itself.
        """
        await require_active_agent(
            session, agent_id=agent_id, allow_foreign_key_reads=True
        )
        membership = await session.write_session.scalar(
            sa.select(RDBWorkspaceUser.name)
            .where(
                RDBWorkspaceUser.workspace_id == manager.workspace_id,
                RDBWorkspaceUser.user_id == manager.user_id,
            )
            .with_for_update(of=RDBWorkspaceUser, read=True)
        )
        if membership is None:
            raise VaultAccessDenied("Agent Vault not found")
        await self._require_manager(session, agent_id=agent_id, manager=manager)
        return membership

    async def list_entries(
        self, agent_id: str, *, manager: VaultManager
    ) -> list[VaultEntryMetadata]:
        """Return only metadata for the exact Agent and current manager."""
        async with self.read_session_manager() as session:
            authority = self._manager_agent(agent_id, manager).subquery()
            rows = (
                await session.read_session.execute(
                    sa.select(
                        RDBAgentVaultEntry.name, RDBAgentVaultEntry.contributor_label
                    )
                    .select_from(authority)
                    .outerjoin(
                        RDBAgentVaultEntry,
                        RDBAgentVaultEntry.agent_id == authority.c.id,
                    )
                    .order_by(RDBAgentVaultEntry.name)
                )
            ).all()
            if not rows:
                raise VaultAccessDenied("Agent Vault not found")
            return [
                VaultEntryMetadata(row.name, row.contributor_label)
                for row in rows
                if row.name is not None and row.contributor_label is not None
            ]

    async def mutate_entry(
        self,
        agent_id: str,
        name: str,
        *,
        manager: VaultManager,
        mutation: VaultEntryMutation,
        value: SecretStr | None,
    ) -> None:
        """Perform a manager mutation without returning the value."""
        _validate_name(name)
        if (mutation is VaultEntryMutation.DELETE) != (value is None):
            raise InvalidVaultEntry("Invalid Vault mutation")
        encrypted = self._encrypt(value) if value is not None else None
        async with self.session_manager() as session:
            await self._require_manager(session, agent_id=agent_id, manager=manager)
            contributor_label = await self.fence_manager_write_in_session(
                session, agent_id=agent_id, manager=manager
            )
            if mutation is VaultEntryMutation.CREATE:
                assert encrypted is not None
                await self._insert_entry(
                    session,
                    agent_id,
                    name,
                    encrypted,
                    contributor_label=contributor_label,
                )
                return
            matches = (
                RDBAgentVaultEntry.agent_id == agent_id,
                RDBAgentVaultEntry.name == name,
            )
            if mutation is VaultEntryMutation.DELETE:
                statement = sa.delete(RDBAgentVaultEntry).where(*matches)
            else:
                statement = (
                    sa.update(RDBAgentVaultEntry)
                    .where(*matches)
                    .values(
                        encrypted_value=encrypted, contributor_label=contributor_label
                    )
                )
            found = await session.write_session.scalar(
                statement.returning(RDBAgentVaultEntry.name)
            )
            if found is None:
                raise VaultEntryUnavailable("Vault entry not found")

    def _encrypt(self, value: SecretStr) -> str:
        try:
            return self.cipher.encrypt(value.get_secret_value())
        except UnicodeError:
            raise InvalidVaultEntry("Vault value is not valid UTF-8") from None

    async def _insert_entry(
        self,
        session: WriteSession,
        agent_id: str,
        name: str,
        encrypted: str,
        *,
        contributor_label: str,
    ) -> None:
        created = await session.write_session.scalar(
            insert(RDBAgentVaultEntry)
            .values(
                agent_id=agent_id,
                name=name,
                encrypted_value=encrypted,
                contributor_label=contributor_label,
            )
            .on_conflict_do_nothing(index_elements=["agent_id", "name"])
            .returning(RDBAgentVaultEntry.name)
        )
        if created is None:
            raise VaultEntryConflict("Vault entry already exists")

    async def insert_from_execution_in_session(
        self,
        session: WriteSession,
        agent_id: str,
        name: str,
        value: SecretStr,
        *,
        contributor_label: str,
    ) -> None:
        """Insert after the caller fences the originating execution."""
        _validate_name(name)
        await require_active_agent(session, agent_id=agent_id)
        await self._insert_entry(
            session,
            agent_id,
            name,
            self._encrypt(value),
            contributor_label=contributor_label,
        )

    async def register_runtime_value(
        self, authority: SessionResourceAuthority, name: str, value: SecretStr
    ) -> VaultEntryMetadata:
        """Fence the originating run and create only under its own Agent."""
        _validate_name(name)
        authority_repository = FileMetadataAuthorityRepository(
            agent_session_repository=AgentSessionRepository(),
            agent_run_repository=AgentRunRepository(),
        )
        file_authority = FileResourceAuthority(
            workspace_id=authority.workspace_id,
            agent_id=authority.agent_id,
            session_id=authority.session_id,
            root_session_id=authority.root_session_id,
            run_id=authority.run_id,
            run_index=authority.run_index,
            owner_generation=authority.owner_generation,
        )
        async with self.session_manager() as session:
            await require_active_agent(
                session, agent_id=authority.agent_id, allow_foreign_key_reads=True
            )
            if not await authority_repository.validate(
                session, file_authority, lock=True
            ):
                raise VaultAccessDenied("Vault execution authority is unavailable")
            label = await session.read_session.scalar(
                sa.select(RDBAgent.name).where(RDBAgent.id == authority.agent_id)
            )
            if label is None:
                raise VaultAccessDenied("Vault execution authority is unavailable")
            await self._insert_entry(
                session,
                authority.agent_id,
                name,
                self._encrypt(value),
                contributor_label=label,
            )
        return VaultEntryMetadata(name, label)

    async def apply_manager_batch_in_session(
        self,
        session: WriteSession,
        agent_id: str,
        values: Mapping[str, SecretStr],
        *,
        manager: VaultManager,
        contributor_label: str,
    ) -> None:
        """Upsert after the caller holds Agent and request lifecycle fences."""
        await self.fence_manager_write_in_session(
            session, agent_id=agent_id, manager=manager
        )
        entries = []
        for name, value in values.items():
            _validate_name(name)
            entries.append(
                {
                    "agent_id": agent_id,
                    "name": name,
                    "encrypted_value": self._encrypt(value),
                    "contributor_label": contributor_label,
                }
            )
        if not entries:
            raise InvalidVaultEntry("No Vault entries supplied")
        statement = insert(RDBAgentVaultEntry).values(entries)
        await session.write_session.execute(
            statement.on_conflict_do_update(
                index_elements=["agent_id", "name"],
                set_={
                    "encrypted_value": statement.excluded.encrypted_value,
                    "contributor_label": statement.excluded.contributor_label,
                    "updated_at": sa.func.now(),
                },
            )
        )

    async def resolve_for_execution(
        self, agent_id: str, names: Set[str]
    ) -> dict[str, SecretStr]:
        """Resolve all or none for an already admitted execution of the exact Agent."""
        if not names:
            return {}
        for name in names:
            _validate_name(name)
        async with self.read_session_manager() as session:
            rows = (
                await session.read_session.execute(
                    sa.select(
                        RDBAgentVaultEntry.name, RDBAgentVaultEntry.encrypted_value
                    )
                    .join(RDBAgent, RDBAgent.id == RDBAgentVaultEntry.agent_id)
                    .where(
                        RDBAgent.id == agent_id,
                        RDBAgent.lifecycle_status == AgentLifecycleStatus.ACTIVE,
                        RDBAgentVaultEntry.name.in_(names),
                    )
                )
            ).all()
        if len(rows) != len(names):
            raise VaultEntryUnavailable("Vault entry unavailable")
        try:
            return {
                row.name: SecretStr(self.cipher.decrypt(row.encrypted_value))
                for row in rows
            }
        except InvalidToken, UnicodeError:
            raise VaultEntryUnavailable("Vault entry unavailable") from None
