"""Typed Runtime Web persistence data."""

import datetime
import hashlib

from pydantic import BaseModel, Field

from azents.rdb.models.runtime_web import (
    RuntimeWebAuthMode,
    RuntimeWebCycleEndReason,
    RuntimeWebOperationKind,
    RuntimeWebRequesterKind,
    RuntimeWebRequestState,
)


class RuntimeWebEndpoint(BaseModel):
    """Stable endpoint identity."""

    id: str
    workspace_id: str
    agent_id: str
    agent_session_id: str
    port: int
    hostname_key: str
    label: str | None
    authority_revision: int
    close_barrier: int
    current_pending_request_id: str | None
    current_cycle_id: str | None
    created_at: datetime.datetime
    updated_at: datetime.datetime


class RuntimeWebRequest(BaseModel):
    """Durable exposure request."""

    id: str
    endpoint_id: str
    requester_kind: RuntimeWebRequesterKind
    operation_key: str
    state: RuntimeWebRequestState
    revision: int
    requester_user_id: str | None
    requester_agent_id: str | None
    requester_execution_id: str | None
    requester_call_id: str | None
    label_snapshot: str | None
    decided_by_user_id: str | None
    decided_at: datetime.datetime | None
    created_at: datetime.datetime
    updated_at: datetime.datetime


class RuntimeWebCycle(BaseModel):
    """Finite approved exposure cycle."""

    id: str
    endpoint_id: str
    request_id: str
    approver_user_id: str
    duration_seconds: int
    duration_configuration_revision: int
    approved_at: datetime.datetime
    expires_at: datetime.datetime
    close_barrier: int
    ended_at: datetime.datetime | None
    end_reason: RuntimeWebCycleEndReason | None
    created_at: datetime.datetime


class RuntimeWebConfiguration(BaseModel):
    """Current durable Runtime Web configuration authority."""

    enabled: bool
    mode: RuntimeWebAuthMode
    configuration_version: int
    fingerprint: str
    active_epoch: int
    duration_configuration_revision: int
    active_duration_seconds: int


class RuntimeWebOperationIdentity(BaseModel):
    """Idempotency identity for one control operation."""

    actor_kind: RuntimeWebRequesterKind
    actor_id: str = Field(min_length=1, max_length=32)
    execution_id: str = Field(min_length=1, max_length=32)
    operation_key: str = Field(min_length=1, max_length=128)


class RuntimeWebOperationReceipt(BaseModel):
    """Recorded operation result."""

    operation_kind: RuntimeWebOperationKind
    result: dict[str, object]
    endpoint_id: str | None
    request_id: str | None
    cycle_id: str | None


class RuntimeWebProjectionPage(BaseModel):
    """Bounded endpoint projection page."""

    items: list[RuntimeWebEndpoint]
    total_count: int


class RuntimeWebMutationResult(BaseModel):
    """Resources returned by one idempotent mutation."""

    endpoint: RuntimeWebEndpoint
    request: RuntimeWebRequest | None
    cycle: RuntimeWebCycle | None


class RuntimeWebTunnelAuthority(BaseModel):
    """Exact approval and Runtime authority for one data-plane tunnel."""

    tunnel_id: str = Field(min_length=1, max_length=128)
    endpoint_id: str = Field(min_length=1, max_length=32)
    cycle_id: str = Field(min_length=1, max_length=32)
    endpoint_authority_revision: int = Field(ge=0)
    close_barrier: int = Field(ge=0)
    runtime_id: str = Field(min_length=1, max_length=32)
    desired_generation: int = Field(ge=1)
    runner_generation: int = Field(ge=1)
    port: int = Field(ge=1, le=65_535)
    join_nonce: str = Field(min_length=1, max_length=128)
    registration_deadline_at: datetime.datetime
    approval_deadline_at: datetime.datetime
    transport_deadline_at: datetime.datetime


class RuntimeWebTunnelRoute(BaseModel):
    """Current renewable owner route for one tunnel."""

    authority: RuntimeWebTunnelAuthority
    owner_replica_id: str
    owner_boot_id: str
    owner_address: str
    route_lease_id: str
    lease_generation: int
    lease_expires_at: datetime.datetime
    admission_lease_id: str


def derived_operation_key(operation_key: str, suffix: str) -> str:
    """Derive a bounded collision-resistant key from one complete parent key."""
    material = f"{len(operation_key)}:{operation_key}:{suffix}"
    return hashlib.sha256(material.encode()).hexdigest()
