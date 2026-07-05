"""Chat action message models."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


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

    action: ChatAction = Field(description="Selected action")
    message: str = Field(description="User-authored action input")
