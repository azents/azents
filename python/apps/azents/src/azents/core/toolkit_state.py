"""Pure Session-bound Toolkit State models."""

from typing import TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ToolkitStateIdentity(BaseModel):
    """Session-bound Toolkit State identity."""

    model_config = ConfigDict(frozen=True)

    agent_id: str = Field(min_length=1, description="Agent ID")
    session_id: str = Field(min_length=1, description="AgentSession ID")
    toolkit_namespace: str = Field(min_length=1, description="Toolkit namespace")
    state_name: str = Field(min_length=1, description="State name")

    @field_validator("agent_id", "session_id", "toolkit_namespace", "state_name")
    @classmethod
    def _reject_blank(cls, value: str) -> str:
        """Deny identity string that is only whitespace."""
        if not value.strip():
            raise ValueError("Toolkit state identity fields must not be blank")
        return value


class ToolkitStateModel(BaseModel):
    """Common base model for Toolkit State payload."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(ge=1, description="Payload schema version")


class ToolkitStateSaved(BaseModel):
    """Stored Toolkit State metadata."""

    id: str = Field(description="Toolkit State ID")
    version: int = Field(description="Row version")
    schema_version: int = Field(description="Payload schema version")


ToolkitStateModelT = TypeVar("ToolkitStateModelT", bound=ToolkitStateModel)
