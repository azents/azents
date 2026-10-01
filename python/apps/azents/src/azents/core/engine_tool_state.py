"""Pure persisted state models for Engine Toolkits."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from azents.core.toolkit_state import ToolkitStateModel

TOOL_SEARCH_TOOLKIT_NAMESPACE = "tool_search"
TOOL_SEARCH_WORKING_SET_STATE_NAME = "working_set"
TOOL_SEARCH_STATE_SCHEMA_VERSION = 1

AGENTS_TOOLKIT_NAMESPACE = "builtin"
AGENTS_APPENDIX_DEDUPE_TOOLKIT_STATE_NAME = "agents_md_appendix_dedupe"

CLAUDE_RULES_TOOLKIT_NAMESPACE = "claude_rules"
CLAUDE_RULES_APPENDIX_DEDUPE_TOOLKIT_STATE_NAME = "claude_rules_appendix_dedupe"

TODO_TOOLKIT_NAMESPACE = "todo"
TODO_TOOLKIT_STATE_NAME = "todo"
TODO_STATE_SCHEMA_VERSION = 1
TodoStatus = Literal["pending", "in_progress", "completed"]

MCP_TOOL_SNAPSHOT_SCHEMA_VERSION = 1
MCP_TOOL_SNAPSHOT_STATE_NAME = "tool_snapshot"

GITHUB_TOOLKIT_STATE_NAMESPACE = "github"
GITHUB_SELECTED_INSTALLATION_STATE_NAME = "selected_installation"


class ToolWorkingSetState(ToolkitStateModel):
    """Session-scoped deferred-tool recency state, most recent first."""

    schema_version: int = TOOL_SEARCH_STATE_SCHEMA_VERSION
    tool_names: list[str] = Field(default_factory=list)

    @field_validator("tool_names")
    @classmethod
    def validate_tool_names(cls, value: list[str]) -> list[str]:
        """Reject blanks and normalize duplicate names to first occurrence."""
        normalized: list[str] = []
        seen: set[str] = set()
        for name in value:
            if not name.strip():
                raise ValueError("Tool working-set names cannot be blank")
            if name not in seen:
                normalized.append(name)
                seen.add(name)
        return normalized


class AgentsAppendixDedupeState(ToolkitStateModel):
    """AGENTS.md read-result appendix dedupe Toolkit State payload."""

    schema_version: int = 1
    appended_paths: list[str] = Field(default_factory=list)


class ClaudeRulesAppendixDedupeState(ToolkitStateModel):
    """Claude rules read-result appendix dedupe Toolkit State payload."""

    schema_version: int = 1
    appended_paths: list[str] = Field(default_factory=list)


class TodoItem(BaseModel):
    """Persisted Todo item payload."""

    content: str = Field(min_length=1, max_length=500, description="Todo text")
    status: TodoStatus = Field(description="Todo status")


class TodoState(ToolkitStateModel):
    """Session-scoped todo list Toolkit State payload."""

    schema_version: int = TODO_STATE_SCHEMA_VERSION
    items: list[TodoItem] = Field(default_factory=list)


class McpToolSnapshotItem(BaseModel):
    """Serializable MCP tool snapshot item."""

    raw_name: str
    model_name: str
    description: str
    input_schema: dict[str, object]
    server_url: str
    use_streamable_http: bool = False


class McpToolSnapshotState(ToolkitStateModel):
    """Latest successful MCP tool snapshot."""

    schema_version: int = MCP_TOOL_SNAPSHOT_SCHEMA_VERSION
    loaded_at: str | None = None
    server_url: str = ""
    tool_hash: str = ""
    tools: list[McpToolSnapshotItem] = Field(default_factory=list)


class GitHubSelectedInstallationState(ToolkitStateModel):
    """Selected GitHub installation for Runtime environment defaults."""

    schema_version: int = 1
    installation_id: str = Field(
        min_length=1,
        description="GitHub installation ID",
    )
