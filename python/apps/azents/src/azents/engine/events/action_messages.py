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


ChatAction = Annotated[
    CommandAction | GoalAction | SkillAction,
    Field(discriminator="type"),
]
TurnAction = Annotated[
    GoalAction | SkillAction,
    Field(discriminator="type"),
]


class ActionMessagePayload(BaseModel):
    """Action message payload stored in transcript."""

    model_config = ConfigDict(frozen=True)

    action: ChatAction = Field(description="Selected action")
    message: str = Field(description="User-authored action input")
