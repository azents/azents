"""Historical Memory persistence contracts."""

import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from azents.core.model_operation import ModelOperationKind, ModelOperationSnapshot


def _require_aware(value: datetime.datetime) -> datetime.datetime:
    """Require a timezone-aware timestamp."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Historical Memory timestamps must be timezone-aware.")
    return value


def _require_historical_operation(
    value: ModelOperationSnapshot | None,
) -> ModelOperationSnapshot | None:
    """Require Historical Memory operation state in the dedicated source record."""
    if value is not None and value.kind is not ModelOperationKind.HISTORICAL_MEMORY:
        raise ValueError(
            "Historical Memory progress requires a historical_memory operation."
        )
    return value


class HistoricalMemorySource(BaseModel):
    """One admitted source with latest result and retry progress."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_session_id: str = Field(min_length=32, max_length=32)
    admitted_at: datetime.datetime
    last_attempt_at: datetime.datetime | None
    next_retry_at: datetime.datetime | None
    failure_count: int = Field(ge=0)
    last_failure_code: str | None
    model_operation_state: ModelOperationSnapshot | None
    completed_source_activity_at: datetime.datetime | None
    completed_source_tail_event_id: str | None = Field(
        min_length=32,
        max_length=32,
    )
    prepared_at: datetime.datetime | None
    source_title_snapshot: str | None
    summary: str | None
    created_at: datetime.datetime
    updated_at: datetime.datetime

    _validate_model_operation_state = field_validator("model_operation_state")(
        _require_historical_operation
    )

    @model_validator(mode="after")
    def validate_completed_result(self) -> "HistoricalMemorySource":
        """Require completed result markers to be all present or absent."""
        completed = (
            self.completed_source_activity_at,
            self.completed_source_tail_event_id,
            self.prepared_at,
        )
        if any(value is None for value in completed) and any(
            value is not None for value in completed
        ):
            raise ValueError(
                "Historical Memory completed result markers must be all present "
                "or absent."
            )
        for value in (
            self.admitted_at,
            self.last_attempt_at,
            self.next_retry_at,
            self.completed_source_activity_at,
            self.prepared_at,
            self.created_at,
            self.updated_at,
        ):
            if value is not None:
                _require_aware(value)
        return self


class HistoricalMemoryDueSource(BaseModel):
    """One admitted source that is due for preparation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_session_id: str = Field(min_length=32, max_length=32)
    agent_id: str = Field(min_length=32, max_length=32)
    workspace_id: str = Field(min_length=32, max_length=32)
    source_activity_at: datetime.datetime
    source_tail_event_id: str = Field(min_length=32, max_length=32)
    source_title: str | None
    admitted_at: datetime.datetime
    prepared_at: datetime.datetime | None
    completed_source_activity_at: datetime.datetime | None
    next_retry_at: datetime.datetime | None
    failure_count: int = Field(ge=0)
    model_operation_state: ModelOperationSnapshot | None

    _validate_model_operation_state = field_validator("model_operation_state")(
        _require_historical_operation
    )

    @model_validator(mode="after")
    def validate_timestamps(self) -> "HistoricalMemoryDueSource":
        """Require timezone-aware due-source timestamps."""
        for value in (
            self.source_activity_at,
            self.admitted_at,
            self.prepared_at,
            self.completed_source_activity_at,
            self.next_retry_at,
        ):
            if value is not None:
                _require_aware(value)
        return self


class HistoricalMemoryFailure(BaseModel):
    """Failure progress for one source preparation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    attempted_at: datetime.datetime
    next_retry_at: datetime.datetime
    failure_code: str = Field(min_length=1, max_length=120)
    model_operation_state: ModelOperationSnapshot | None

    _validate_model_operation_state = field_validator("model_operation_state")(
        _require_historical_operation
    )

    @model_validator(mode="after")
    def validate_retry(self) -> "HistoricalMemoryFailure":
        """Require aware ordered attempt and retry timestamps."""
        _require_aware(self.attempted_at)
        _require_aware(self.next_retry_at)
        if self.next_retry_at < self.attempted_at:
            raise ValueError("Historical Memory retry cannot precede the attempt.")
        return self


class HistoricalMemoryCompletion(BaseModel):
    """Successful empty or non-empty preparation result."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_activity_at: datetime.datetime
    source_tail_event_id: str = Field(min_length=32, max_length=32)
    prepared_at: datetime.datetime
    source_title_snapshot: str | None
    summary: str | None

    @model_validator(mode="after")
    def validate_timestamps(self) -> "HistoricalMemoryCompletion":
        """Require aware source and preparation timestamps."""
        _require_aware(self.source_activity_at)
        _require_aware(self.prepared_at)
        return self
