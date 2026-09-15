"""Typed Runtime Web persistence data."""

import datetime

from pydantic import BaseModel, Field

from azents.rdb.models.runtime_web import (
    RuntimeWebActorKind,
    RuntimeWebAuthMode,
    RuntimeWebOperationKind,
)


class RuntimeWebServiceRecord(BaseModel):
    """Stable Agent-port service identity and current exposure authority."""

    id: str
    workspace_id: str
    agent_id: str
    port: int
    hostname_key: str
    label: str | None
    selected_duration_seconds: int
    exposure_deadline_at: datetime.datetime | None
    revision: int
    created_at: datetime.datetime
    updated_at: datetime.datetime


class RuntimeWebConfiguration(BaseModel):
    """Current durable Runtime Web authentication configuration."""

    enabled: bool
    mode: RuntimeWebAuthMode
    fingerprint: str


class RuntimeWebOperationIdentity(BaseModel):
    """Idempotency identity for one control operation."""

    actor_kind: RuntimeWebActorKind
    actor_id: str = Field(min_length=1, max_length=32)
    execution_id: str = Field(min_length=1, max_length=32)
    operation_key: str = Field(min_length=1, max_length=128)


class RuntimeWebOperationReceipt(BaseModel):
    """Recorded operation result."""

    operation_kind: RuntimeWebOperationKind
    input_fingerprint: str = Field(min_length=64, max_length=64)
    result: dict[str, object]
    service_id: str | None


class RuntimeWebProjectionPage(BaseModel):
    """Bounded service projection page."""

    items: list[RuntimeWebServiceRecord]
    total_count: int


class RuntimeWebMutationResult(BaseModel):
    """Service returned by one idempotent mutation."""

    service: RuntimeWebServiceRecord


class RuntimeWebSessionRoute(BaseModel):
    """Current exact Owner lease for one Runtime generation."""

    runtime_id: str = Field(min_length=1, max_length=32)
    desired_generation: int = Field(ge=1)
    runner_generation: int = Field(ge=1)
    owner_replica_id: str = Field(min_length=1, max_length=255)
    owner_boot_id: str = Field(min_length=1, max_length=128)
    owner_address: str = Field(min_length=1, max_length=255)
    session_lease_id: str = Field(min_length=1, max_length=32)
    lease_generation: int = Field(ge=1)
    join_nonce_hash: str = Field(min_length=64, max_length=64)
    protocol_fingerprint: str = Field(min_length=64, max_length=64)
    lease_expires_at: datetime.datetime
    draining_at: datetime.datetime | None
