"""Agent-owned browser choice, application evidence and mutation denials."""

import enum
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

from azents_runtime_control.browser_configuration import BrowserImplementation
from pydantic import BaseModel, ConfigDict


class AgentBrowserApplicationState(enum.StrEnum):
    APPLYING = "applying"
    READY = "ready"
    FAILED = "failed"


class BrowserConfigurationDenial(enum.StrEnum):
    NOT_FOUND = "not_found"
    ADMIN_REQUIRED = "admin_required"
    STALE_INTENT = "stale_intent"
    AGENT_INACTIVE = "agent_inactive"


class AgentBrowserConfiguration(BaseModel):
    model_config = ConfigDict(frozen=True)

    agent_id: str
    intent_id: str
    requested: BrowserImplementation
    applied: BrowserImplementation | None
    state: Literal["offline", "applying", "ready", "failed"]
    reason_code: str | None
    runtime_id: str | None
    runner_generation: int | None


@dataclass(frozen=True)
class BrowserApplicationClaim:
    agent_id: str
    intent_id: str
    implementation: BrowserImplementation
    claim_id: str
    runtime_id: str
    runner_generation: int
    desired_generation: int
    configuration_sequence: int
    lease_until: datetime


class BrowserConfigurationIntentReader(Protocol):
    async def current_intent(
        self, runtime_id: str, runner_generation: int, *, require_ready: bool
    ) -> str | None: ...


class BrowserConfigurationReconciler(Protocol):
    async def reconcile_runtime(
        self, runtime_id: str, runner_generation: int
    ) -> None: ...
