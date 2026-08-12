"""Chat action message models."""

from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SerializerFunctionWrapHandler,
    model_serializer,
    model_validator,
)

from azents.core.inference_profile import RequestedInferenceProfile


class CommandAction(BaseModel):
    """Idle-only prioritized command action."""

    model_config = ConfigDict(frozen=True)

    type: Literal["command"] = "command"
    name: str = Field(min_length=1, description="Command name")


class GoalAction(BaseModel):
    """Session goal creation turn action."""

    model_config = ConfigDict(frozen=True)

    type: Literal["goal"] = "goal"


class SkillAction(BaseModel):
    """Skill invocation turn action."""

    model_config = ConfigDict(frozen=True)

    type: Literal["skill"] = "skill"
    skill_path: str = Field(min_length=1, description="Exact SKILL.md path")


class CreateGitWorktreeAction(BaseModel):
    """Create an Azents-owned Git worktree and register it as a session Project."""

    model_config = ConfigDict(frozen=True)

    type: Literal["create_git_worktree"] = "create_git_worktree"
    source_project_path: str = Field(
        min_length=1,
        description="Existing source Project path under the Agent Workspace",
    )
    starting_ref: str = Field(
        min_length=1,
        description="Starting Git ref for the new worktree branch",
    )


class CleanupOrphanGitWorktreesAction(BaseModel):
    """Remove orphaned Git worktrees from the current Agent Runtime."""

    model_config = ConfigDict(frozen=True)

    type: Literal["cleanup_orphan_git_worktrees"] = "cleanup_orphan_git_worktrees"


class CreateSessionWorkingFolderAction(BaseModel):
    """Materialize the current Session context's owned working folder."""

    model_config = ConfigDict(frozen=True)

    type: Literal["create_session_working_folder"] = "create_session_working_folder"


class AgentCreateGitWorktreeAction(BaseModel):
    """Create a managed worktree from an admission-pinned Session Project."""

    model_config = ConfigDict(frozen=True)

    type: Literal["agent_create_git_worktree"] = "agent_create_git_worktree"
    bridge_identity: str = Field(min_length=1)
    originating_run_id: str = Field(min_length=1)
    client_tool_call_id: str = Field(min_length=1)
    session_agent_context_id: str = Field(min_length=1)
    originating_agent_session_id: str = Field(min_length=1)
    source_project_id: str = Field(min_length=1)
    source_project_path: str = Field(min_length=1)
    starting_ref: str | None
    branch_name: str | None


class AgentRemoveGitWorktreeAction(BaseModel):
    """Remove an admission-pinned managed worktree while preserving its branch."""

    model_config = ConfigDict(frozen=True)

    type: Literal["agent_remove_git_worktree"] = "agent_remove_git_worktree"
    bridge_identity: str = Field(min_length=1)
    originating_run_id: str = Field(min_length=1)
    client_tool_call_id: str = Field(min_length=1)
    session_agent_context_id: str = Field(min_length=1)
    originating_agent_session_id: str = Field(min_length=1)
    worktree_project_id: str = Field(min_length=1)
    worktree_allocation_id: str = Field(min_length=1)
    worktree_path: str = Field(min_length=1)
    force: bool


ChatAction = Annotated[
    CommandAction
    | GoalAction
    | SkillAction
    | CreateGitWorktreeAction
    | CleanupOrphanGitWorktreesAction,
    Field(discriminator="type"),
]
PersistedChatAction = Annotated[
    CommandAction
    | GoalAction
    | SkillAction
    | CreateGitWorktreeAction
    | CleanupOrphanGitWorktreesAction
    | CreateSessionWorkingFolderAction
    | AgentCreateGitWorktreeAction
    | AgentRemoveGitWorktreeAction,
    Field(discriminator="type"),
]
TurnAction = Annotated[
    GoalAction
    | SkillAction
    | CreateGitWorktreeAction
    | CleanupOrphanGitWorktreesAction
    | CreateSessionWorkingFolderAction
    | AgentCreateGitWorktreeAction
    | AgentRemoveGitWorktreeAction,
    Field(discriminator="type"),
]


class ActionMessagePayload(BaseModel):
    """Action message payload stored in transcript."""

    model_config = ConfigDict(frozen=True)

    sender_user_id: str | None = Field(
        description="Human sender User ID, or null when provenance is unavailable",
    )
    action: PersistedChatAction = Field(description="Selected action")
    message: str = Field(description="User-authored action input")
    requested_inference_profile: RequestedInferenceProfile | None = Field(
        default=None,
        description="Requested profile for a model-producing action",
        exclude_if=lambda value: value is None,
    )

    @model_validator(mode="before")
    @classmethod
    def default_missing_sender_provenance(cls, data: object) -> object:
        """Decode historical missing sender provenance as unavailable."""
        if not isinstance(data, dict) or "sender_user_id" in data:
            return data
        return {**data, "sender_user_id": None}

    @model_serializer(mode="wrap")
    def serialize_sender_provenance(
        self,
        handler: SerializerFunctionWrapHandler,
    ) -> dict[str, object]:
        """Preserve unavailable sender provenance in canonical event JSON."""
        serialized: dict[str, object] = handler(self)
        serialized["sender_user_id"] = self.sender_user_id
        return serialized
