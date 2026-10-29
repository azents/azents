"""Allowlisted operational projection of the original Proxy logging callbacks."""

import logging
from dataclasses import dataclass
from time import monotonic
from typing import Literal
from uuid import uuid4

from azents_llm_contract.authority import TargetBinding
from litellm._logging import JsonFormatter
from litellm.types.llms.openai import (
    ErrorEvent,
    ResponseCompletedEvent,
    ResponseFailedEvent,
    ResponseIncompleteEvent,
    ResponsesAPIResponse,
)
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, ValidationError

LOGGER = logging.getLogger("azents_llm_proxy.operations")


class UsageCounts(BaseModel):
    model_config = ConfigDict(extra="ignore", from_attributes=True)
    input_tokens: int | None = Field(
        default=None, validation_alias=AliasChoices("input_tokens", "prompt_tokens")
    )
    output_tokens: int | None = Field(
        default=None,
        validation_alias=AliasChoices("output_tokens", "completion_tokens"),
    )
    total_tokens: int | None = None


@dataclass
class Operation:
    request_id: str
    agent_id: str
    workspace_id: str
    integration_id: str
    model: str
    emitted: bool
    started: float
    dispatched: bool
    terminal: Literal["success", "failure", "incomplete"] | None
    usage: UsageCounts

    @classmethod
    def from_binding(cls, binding: TargetBinding) -> "Operation":
        return cls(
            request_id=uuid4().hex,
            agent_id=binding.identity.agent_id,
            workspace_id=binding.identity.workspace_id,
            integration_id=binding.integration_id,
            model=binding.public_model,
            emitted=False,
            started=monotonic(),
            dispatched=False,
            terminal=None,
            usage=UsageCounts(),
        )

    def observe(self, response: object) -> None:
        """Read typed SDK results, never parse or retain provider wire content."""
        if self.emitted:
            return
        if isinstance(response, ErrorEvent):
            self.terminal = "failure"
            return
        if isinstance(
            response,
            ResponseCompletedEvent | ResponseFailedEvent | ResponseIncompleteEvent,
        ):
            self.observe(response.response)
            if isinstance(response, ResponseFailedEvent):
                self.terminal = "failure"
            elif isinstance(response, ResponseIncompleteEvent):
                self.terminal = "incomplete"
            return
        if isinstance(response, ResponsesAPIResponse):
            if response.status == "completed":
                self.terminal = "success"
            elif response.status == "failed":
                self.terminal = "failure"
            elif response.status in {"incomplete", "cancelled"}:
                self.terminal = "incomplete"
            self.observe_usage(response)

    def observe_usage(self, response: object) -> None:
        """SDK accounting callbacks contribute counts, never completion."""
        if self.emitted:
            return
        if isinstance(
            response,
            ResponseCompletedEvent | ResponseFailedEvent | ResponseIncompleteEvent,
        ):
            response = response.response
        if isinstance(response, ResponsesAPIResponse) and response.usage is not None:
            try:
                self.usage = UsageCounts.model_validate(response.usage)
            except ValidationError:
                # Unknown SDK usage stays unknown; no raw provider values.
                self.usage = UsageCounts()

    def finish(
        self,
        *,
        disconnected: bool,
        cancelled: bool,
        status: int | None,
        delivered: bool,
    ) -> None:
        if self.emitted:
            return
        self.emitted = True
        if disconnected:
            outcome = "disconnected"
        elif cancelled:
            outcome = "cancelled"
        elif status is None or status >= 400:
            outcome = "failure"
        elif self.terminal == "success":
            outcome = "success" if delivered else "incomplete"
        else:
            outcome = self.terminal or "incomplete"
        classification = None
        if outcome == "failure":
            classification = "upstream_provider" if self.dispatched else "preparation"
        elif outcome != "success":
            classification = outcome
        LOGGER.info(
            "Inference request ended.",
            extra={
                "request_id": self.request_id,
                "agent_id": self.agent_id,
                "workspace_id": self.workspace_id,
                "integration_id": self.integration_id,
                "model": self.model,
                "outcome": outcome,
                "latency_ms": max(0.0, (monotonic() - self.started) * 1000),
                "failure_classification": classification,
                **self.usage.model_dump(),
            },
        )


def configure_operations_logging() -> None:
    """Use the vendor's JSON formatter, with no external exporters or ledger."""
    if not LOGGER.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
        LOGGER.addHandler(handler)
    LOGGER.setLevel(logging.INFO)
