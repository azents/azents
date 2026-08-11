"""Agent Runtime addition receipt data models."""

import datetime

from pydantic import BaseModel, Field


class AgentRuntimeAddReceipt(BaseModel):
    """Committed idempotency evidence for one Runtime addition."""

    id: str = Field(description="Receipt ID")
    agent_id: str = Field(description="Agent ID")
    workspace_id: str = Field(description="Workspace ID")
    idempotency_key: str = Field(description="Addition request idempotency key")
    workspace_runtime_profile_id: str = Field(
        description="Explicit Workspace Runtime Profile ID"
    )
    expected_capability_version: int = Field(
        description="Capability version supplied by the requester"
    )
    committed_capability_version: int = Field(
        description="Capability version committed by the transition"
    )
    committed_runtime_profile_selection_version: int = Field(
        description="Runtime Profile selection version committed by the transition"
    )
    agent_runtime_id: str = Field(description="Stable logical Agent Runtime ID")
    runtime_configuration_sequence: int = Field(
        ge=1, description="Configuration sequence committed by the transition"
    )
    runtime_configuration_digest: str = Field(
        min_length=64,
        max_length=64,
        description="Configuration digest committed by the transition",
    )
    runtime_desired_generation: int = Field(
        description="Desired Runtime generation committed by the transition"
    )
    created_at: datetime.datetime = Field(description="Receipt creation time")


class AgentRuntimeAddReceiptCreate(BaseModel):
    """Creation input for a committed Runtime addition receipt."""

    agent_id: str = Field(description="Agent ID")
    workspace_id: str = Field(description="Workspace ID")
    idempotency_key: str = Field(min_length=1, max_length=120)
    workspace_runtime_profile_id: str = Field(
        description="Explicit Workspace Runtime Profile ID"
    )
    expected_capability_version: int = Field(ge=1)
    committed_capability_version: int = Field(ge=2)
    committed_runtime_profile_selection_version: int = Field(ge=2)
    agent_runtime_id: str = Field(description="Stable logical Agent Runtime ID")
    runtime_configuration_sequence: int = Field(
        ge=1, description="Configuration sequence committed by the transition"
    )
    runtime_configuration_digest: str = Field(
        min_length=64,
        max_length=64,
        description="Configuration digest committed by the transition",
    )
    runtime_desired_generation: int = Field(ge=0)


class AgentRuntimeAddReceiptCreateResult(BaseModel):
    """Creation outcome for one Runtime addition receipt."""

    receipt: AgentRuntimeAddReceipt
    created: bool = Field(description="Whether this call created the receipt")
