"""Workspace environment editing and redacted selection contracts."""

from pydantic import BaseModel, ConfigDict, Field

from azents.core.runtime_environment import RuntimeEnvironmentEntryEdit


class WorkspaceEnvironmentEntryEdit(RuntimeEnvironmentEntryEdit):
    """Exact stored identity or new entry, preventing name-based stale consent."""

    id: str | None


class WorkspaceEnvironmentEntry(BaseModel):
    """Public catalog metadata without a secret value."""

    id: str
    name: str
    has_value: bool


class WorkspaceEnvironmentSettings(BaseModel):
    """Redacted shared configuration and editing authority."""

    entries: list[WorkspaceEnvironmentEntry]
    can_manage: bool


class AgentWorkspaceEnvironmentSettings(BaseModel):
    """Catalog and explicit selection; defaults contain no selected IDs."""

    entries: list[WorkspaceEnvironmentEntry]
    selected_ids: list[str]
    overridden_names: list[str]
    can_manage: bool


class WorkspaceEnvironmentReplace(BaseModel):
    """Complete desired catalog."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    entries: list[WorkspaceEnvironmentEntryEdit] = Field(max_length=50)


class AgentWorkspaceEnvironmentReplace(BaseModel):
    """Complete explicit opt-in set."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    selected_ids: list[str] = Field(max_length=50)
