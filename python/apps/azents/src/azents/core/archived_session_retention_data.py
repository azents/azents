"""Neutral archive retention operation results and errors."""

import dataclasses

from azents.repos.archived_session_retention.data import (
    ArchivedSessionRetentionApplication,
    SystemFileLifecycleSettings,
)


class RetentionRevisionConflict(Exception):
    """Expected settings revision does not match current state."""


class RetentionApplicationInProgress(Exception):
    """An existing-archive recalculation is already active."""


class RetentionApplicationLeaseLost(Exception):
    """A recalculation worker no longer owns the durable application lease."""


@dataclasses.dataclass(frozen=True)
class RetentionSettingsReadResult:
    """Current settings and recoverable recalculation progress."""

    settings: SystemFileLifecycleSettings
    active_application: ArchivedSessionRetentionApplication | None


@dataclasses.dataclass(frozen=True)
class RetentionSettingsUpdateResult:
    """Result of updating archive-retention settings."""

    settings: SystemFileLifecycleSettings
    application: ArchivedSessionRetentionApplication | None


@dataclasses.dataclass(frozen=True)
class RetentionRecalculationSummary:
    """One scheduler recalculation pass summary."""

    claimed: bool
    application_id: str | None
    affected_count: int
    immediately_eligible_count: int
    cancelled_count: int
    scheduled_count: int
    skipped_count: int
    completed: bool
