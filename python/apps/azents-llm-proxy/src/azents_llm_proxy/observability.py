"""Allowlisted operational projection of the original Proxy logging callbacks."""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import uuid4

from azents_llm_contract.authority import TargetBinding
from litellm._logging import JsonFormatter
from litellm.types.llms.openai import ResponsesAPIResponse
from pydantic import BaseModel, ConfigDict, ValidationError

LOGGER = logging.getLogger("azents_llm_proxy.operations")


class UsageCounts(BaseModel):
    model_config = ConfigDict(extra="ignore", from_attributes=True)
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


@dataclass
class Operation:
    request_id: str
    agent_id: str
    workspace_id: str
    integration_id: str
    model: str
    emitted: bool

    @classmethod
    def from_binding(cls, binding: TargetBinding) -> "Operation":
        return cls(
            request_id=uuid4().hex,
            agent_id=binding.identity.agent_id,
            workspace_id=binding.identity.workspace_id,
            integration_id=binding.integration_id,
            model=binding.public_model,
            emitted=False,
        )

    def emit(
        self,
        *,
        outcome: Literal["success", "failure"],
        response: object,
        start: datetime,
        end: datetime,
    ) -> None:
        if self.emitted:
            return
        self.emitted = True
        usage = UsageCounts()
        if isinstance(response, ResponsesAPIResponse) and response.usage is not None:
            try:
                usage = UsageCounts.model_validate(response.usage)
            except ValidationError:
                # A missing/unknown usage shape is explicitly unknown, never a
                # guessed bill, and raw validation/provider values are not logged.
                usage = UsageCounts()
        LOGGER.info(
            "Inference request completed.",
            extra={
                "request_id": self.request_id,
                "agent_id": self.agent_id,
                "workspace_id": self.workspace_id,
                "integration_id": self.integration_id,
                "model": self.model,
                "outcome": outcome,
                "latency_ms": max(0.0, (end - start).total_seconds() * 1000),
                "failure_classification": "upstream_provider"
                if outcome == "failure"
                else None,
                **usage.model_dump(),
            },
        )


def configure_operations_logging() -> None:
    """Use the vendor's JSON formatter, with no external exporters or ledger."""
    if not LOGGER.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
        LOGGER.addHandler(handler)
    LOGGER.setLevel(logging.INFO)
