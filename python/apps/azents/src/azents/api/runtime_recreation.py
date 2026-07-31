"""Shared Runtime recreation API schemas."""

import datetime

from pydantic import BaseModel, Field

from azents.core.runtime_profile import (
    RuntimeRecreationItemStatus,
    RuntimeRecreationOperationStatus,
    RuntimeRecreationTargetKind,
)
from azents.repos.runtime_profile.data import (
    RuntimeRecreationOperation,
    RuntimeRecreationOperationItem,
)
from azents.services.runtime_recreation.service import RuntimeRecreationProjection


class RuntimeRecreationCreateRequest(BaseModel):
    """Create one optimistic bounded recreation operation."""

    expected_version: int = Field(ge=0)
    concurrency_limit: int = Field(default=5, ge=1, le=100)


class RuntimeRecreationItemResponse(BaseModel):
    """One non-success recreation item detail."""

    runtime_id: str
    status: RuntimeRecreationItemStatus
    attempt: int
    dispatched_generation: int | None
    failure_code: str | None
    failure_message: str | None
    updated_at: datetime.datetime

    @classmethod
    def convert_from(
        cls,
        item: RuntimeRecreationOperationItem,
    ) -> "RuntimeRecreationItemResponse":
        """Convert one bounded item projection."""
        return cls(
            runtime_id=item.runtime_id,
            status=item.status,
            attempt=item.attempt,
            dispatched_generation=item.dispatched_generation,
            failure_code=item.failure_code,
            failure_message=item.failure_message,
            updated_at=item.updated_at,
        )


class RuntimeRecreationOperationResponse(BaseModel):
    """Durable recreation operation progress and bounded item details."""

    id: str
    target_kind: RuntimeRecreationTargetKind
    target_id: str
    target_version: str
    status: RuntimeRecreationOperationStatus
    concurrency_limit: int
    total_count: int
    pending_count: int
    running_count: int
    succeeded_count: int
    skipped_count: int
    failed_count: int
    created_at: datetime.datetime
    started_at: datetime.datetime | None
    completed_at: datetime.datetime | None
    items: list[RuntimeRecreationItemResponse]

    @classmethod
    def convert_operation(
        cls,
        operation: RuntimeRecreationOperation,
    ) -> "RuntimeRecreationOperationResponse":
        """Convert a newly created operation without terminal item details."""
        return cls._convert(operation, ())

    @classmethod
    def convert_projection(
        cls,
        projection: RuntimeRecreationProjection,
    ) -> "RuntimeRecreationOperationResponse":
        """Convert operation progress with bounded non-success items."""
        return cls._convert(projection.operation, projection.items)

    @classmethod
    def _convert(
        cls,
        operation: RuntimeRecreationOperation,
        items: tuple[RuntimeRecreationOperationItem, ...],
    ) -> "RuntimeRecreationOperationResponse":
        return cls(
            id=operation.id,
            target_kind=operation.target_kind,
            target_id=operation.target_id,
            target_version=operation.target_version,
            status=operation.status,
            concurrency_limit=operation.concurrency_limit,
            total_count=operation.total_count,
            pending_count=operation.pending_count,
            running_count=operation.running_count,
            succeeded_count=operation.succeeded_count,
            skipped_count=operation.skipped_count,
            failed_count=operation.failed_count,
            created_at=operation.created_at,
            started_at=operation.started_at,
            completed_at=operation.completed_at,
            items=[RuntimeRecreationItemResponse.convert_from(item) for item in items],
        )
