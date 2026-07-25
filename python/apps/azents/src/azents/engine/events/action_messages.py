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


ChatAction = Annotated[
    CommandAction | GoalAction | SkillAction | CreateGitWorktreeAction,
    Field(discriminator="type"),
]
TurnAction = Annotated[
    GoalAction | SkillAction | CreateGitWorktreeAction,
    Field(discriminator="type"),
]


class ActionMessagePayload(BaseModel):
    """Action message payload stored in transcript."""

    model_config = ConfigDict(frozen=True)

    sender_user_id: str | None = Field(
        description="Human sender User ID, or null when provenance is unavailable",
    )
    action: ChatAction = Field(description="Selected action")
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
