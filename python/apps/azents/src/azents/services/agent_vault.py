"""Agent Vault settings operations."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated

from fastapi import Depends
from pydantic import BaseModel, SecretStr

from azents.repos.agent_vault import (
    AgentVaultRepository,
    InvalidVaultEntry,
    VaultAccessDenied,
    VaultEntryConflict,
    VaultEntryMutation,
    VaultEntryUnavailable,
    VaultManager,
)


class AgentVaultEntryMetadata(BaseModel):
    """Vault entry metadata without a value."""

    name: str
    contributor_label: str


class AgentVaultSettings(BaseModel):
    """Authorized Vault settings projection."""

    entries: list[AgentVaultEntryMetadata]


class VaultSettingsDenial(StrEnum):
    """Value-free settings failure classifications."""

    NOT_FOUND = "not_found"
    CONFLICT = "conflict"
    INVALID = "invalid"


class VaultSettingsError(Exception):
    """Expected, sanitized Vault settings failure."""

    def __init__(self, reason: VaultSettingsDenial) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class AgentVaultService:
    """Expose only redacted Agent Vault management operations."""

    repository: Annotated[AgentVaultRepository, Depends(AgentVaultRepository)]

    async def list_entries(
        self, agent_id: str, *, workspace_id: str, user_id: str
    ) -> AgentVaultSettings:
        """Read metadata for an authorized principal."""
        try:
            entries = await self.repository.list_entries(
                agent_id, manager=VaultManager(workspace_id, user_id)
            )
        except VaultAccessDenied:
            raise VaultSettingsError(VaultSettingsDenial.NOT_FOUND) from None
        return AgentVaultSettings(
            entries=[
                AgentVaultEntryMetadata(
                    name=entry.name, contributor_label=entry.contributor_label
                )
                for entry in entries
            ]
        )

    async def create_entry(
        self,
        agent_id: str,
        name: str,
        value: SecretStr,
        *,
        workspace_id: str,
        user_id: str,
    ) -> None:
        """Create a new named record without returning its value."""
        await self._mutate(
            agent_id, name, value, VaultEntryMutation.CREATE, workspace_id, user_id
        )

    async def replace_entry(
        self,
        agent_id: str,
        name: str,
        value: SecretStr,
        *,
        workspace_id: str,
        user_id: str,
    ) -> None:
        """Replace the value of an existing named record."""
        await self._mutate(
            agent_id, name, value, VaultEntryMutation.REPLACE, workspace_id, user_id
        )

    async def delete_entry(
        self, agent_id: str, name: str, *, workspace_id: str, user_id: str
    ) -> None:
        """Delete the existing record by exact name."""
        await self._mutate(
            agent_id, name, None, VaultEntryMutation.DELETE, workspace_id, user_id
        )

    async def _mutate(
        self,
        agent_id: str,
        name: str,
        value: SecretStr | None,
        mutation: VaultEntryMutation,
        workspace_id: str,
        user_id: str,
    ) -> None:
        try:
            await self.repository.mutate_entry(
                agent_id,
                name,
                manager=VaultManager(workspace_id, user_id),
                mutation=mutation,
                value=value,
            )
        except VaultAccessDenied, VaultEntryUnavailable:
            raise VaultSettingsError(VaultSettingsDenial.NOT_FOUND) from None
        except VaultEntryConflict:
            raise VaultSettingsError(VaultSettingsDenial.CONFLICT) from None
        except InvalidVaultEntry:
            raise VaultSettingsError(VaultSettingsDenial.INVALID) from None
