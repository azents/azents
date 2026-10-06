"""Exact scope and common execution bindings for summary-only Memory work."""

import datetime
import enum
from dataclasses import dataclass
from typing import assert_never

from pydantic import BaseModel, ConfigDict, Field, model_validator

from azents.core.historical_memory_system_setting import HistoricalMemoryExecutionConfig
from azents.core.session_resource_authority import SessionExecutionOwner


class ConsolidationScope(enum.StrEnum):
    """One independently maintained Team or personal result."""

    TEAM = "team"
    USER = "user"


class ConsolidationWorkKind(enum.StrEnum):
    """Scheduling changes, not source-body versions or authored dispositions."""

    PREPARED = "prepared"
    REMOVED = "removed"
    RESTORED = "restored"


class ConsolidationUnitKey(BaseModel):
    """Server-bound scope, never selected from model tool arguments."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    agent_id: str = Field(min_length=32, max_length=32)
    workspace_id: str = Field(min_length=32, max_length=32)
    scope: ConsolidationScope
    associated_user_id: str | None = Field(min_length=32, max_length=32)

    @model_validator(mode="after")
    def validate_scope_owner(self) -> "ConsolidationUnitKey":
        match self.scope:
            case ConsolidationScope.TEAM:
                if self.associated_user_id is not None:
                    raise ValueError("Team Memory must not bind a personal User.")
            case ConsolidationScope.USER:
                if self.associated_user_id is None:
                    raise ValueError("Personal Memory requires its associated User.")
            case _:
                assert_never(self.scope)
        return self


@dataclass(frozen=True)
class MemoryAcceptedOutcome:
    session_id: str
    tool_call_id: str
    accepted_at: datetime.datetime
    rendered_bytes: int
    settled_work_count: int


@dataclass(frozen=True)
class MemoryExecutionBinding:
    unit_id: str
    unit: ConsolidationUnitKey
    session_id: str
    deadline_at: datetime.datetime
    execution_policy: HistoricalMemoryExecutionConfig
    started_turns: int
    accepted: MemoryAcceptedOutcome | None


@dataclass(frozen=True)
class MemoryExecutionPrincipal:
    binding: MemoryExecutionBinding
    owner: SessionExecutionOwner
    run_id: str


@dataclass(frozen=True)
class FreshMemoryAdmission:
    deadline_at: datetime.datetime
    execution_policy: HistoricalMemoryExecutionConfig


@dataclass(frozen=True)
class TakeoverMemoryAdmission:
    predecessor_session_id: str
    expected_owner_generation: int


@dataclass(frozen=True)
class CurrentMemoryResult:
    unit: ConsolidationUnitKey
    markdown: str
    rendered_block: str
    accepted_at: datetime.datetime


@dataclass(frozen=True)
class ProvidedSummary:
    path: str
    source_session_id: str
    content: str


@dataclass(frozen=True)
class ProvisionedMemoryInputs:
    binding: MemoryExecutionBinding
    files: tuple[ProvidedSummary, ...]


class MemoryExecutionAuthorityError(PermissionError):
    """The exact common execution or domain binding is unavailable."""


class MemorySubmissionUncertainError(RuntimeError):
    """The original submission commit outcome requires independent inspection."""
