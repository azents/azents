"""Agent run input and resolution error data models."""

import dataclasses
from typing import Literal

from azents.engine.events.types import FileOutputPart
from azents.engine.run.types import TokenUsage


@dataclasses.dataclass(frozen=True)
class InputMessage:
    """Individual input message to be converted to model input."""

    text: str
    headers: list[tuple[str, str]]
    metadata: dict[str, str]
    attachments: list[str]
    file_parts: list[FileOutputPart] = dataclasses.field(default_factory=list)
    type: Literal["input"] = "input"


@dataclasses.dataclass(frozen=True)
class InvokeInput:
    """Agent call input."""

    agent_id: str
    session_id: str
    messages: list[InputMessage]


@dataclasses.dataclass(frozen=True)
class InvokeOutput:
    """Agent call output."""

    content: str
    usage: TokenUsage | None


@dataclasses.dataclass(frozen=True)
class AgentNotFound:
    """Agent not found."""

    agent_id: str


@dataclasses.dataclass(frozen=True)
class AgentDisabled:
    """Agent disabled."""

    agent_id: str


@dataclasses.dataclass(frozen=True)
class ModelSelectionNotFound:
    """Agent model selection snapshot missing."""

    agent_id: str


@dataclasses.dataclass(frozen=True)
class InvalidModelParameters:
    """Agent model parameters are invalid."""

    agent_id: str
    errors: list[str]


@dataclasses.dataclass(frozen=True)
class IntegrationNotFound:
    """LLM integration not found."""

    integration_id: str | None


@dataclasses.dataclass(frozen=True)
class IntegrationDisabled:
    """LLM integration disabled."""

    integration_id: str


@dataclasses.dataclass(frozen=True)
class ParentModelUnavailable:
    """Parent agent model unavailable."""

    parent_agent_id: str
