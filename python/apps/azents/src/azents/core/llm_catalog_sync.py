"""Integration model catalog synchronization policy."""

import dataclasses
import datetime
import enum

from azents.core.enums import LLMCatalogAttemptStatus

INTEGRATION_CATALOG_STALE_AFTER = datetime.timedelta(minutes=15)
INTEGRATION_CATALOG_SYNC_COOLDOWN = datetime.timedelta(seconds=30)
WORKSPACE_CATALOG_SYNC_COOLDOWN = datetime.timedelta(seconds=5)
INTEGRATION_CATALOG_FAILURE_BACKOFF = datetime.timedelta(minutes=5)
INTEGRATION_CATALOG_RUNNING_TIMEOUT = datetime.timedelta(minutes=15)


class IntegrationCatalogSyncTrigger(enum.StrEnum):
    """Reason an integration catalog synchronization was requested."""

    CREATE = "create"
    CONFIG_UPDATE = "config_update"
    EXPLICIT = "explicit"
    STALE_REFRESH = "stale_refresh"


class IntegrationCatalogSyncDenialReason(enum.StrEnum):
    """Reason a catalog synchronization request cannot start."""

    ALREADY_RUNNING = "already_running"
    THROTTLED = "throttled"
    AUTOMATIC_RETRY_BLOCKED = "automatic_retry_blocked"
    NOT_STALE = "not_stale"


@dataclasses.dataclass(frozen=True)
class CatalogSyncAttemptState:
    """Attempt fields used to evaluate synchronization policy."""

    id: str
    status: LLMCatalogAttemptStatus
    started_at: datetime.datetime
    finished_at: datetime.datetime | None
    automatic_retry_blocked: bool


@dataclasses.dataclass(frozen=True)
class IntegrationCatalogSyncPolicyInput:
    """Inputs required to decide whether a synchronization may start."""

    trigger: IntegrationCatalogSyncTrigger
    now: datetime.datetime
    current_snapshot_created_at: datetime.datetime | None
    latest_catalog_attempt: CatalogSyncAttemptState | None
    latest_workspace_attempt: CatalogSyncAttemptState | None


@dataclasses.dataclass(frozen=True)
class IntegrationCatalogSyncPolicyDecision:
    """Synchronization policy decision."""

    allowed: bool
    stale: bool
    denial_reason: IntegrationCatalogSyncDenialReason | None
    retry_at: datetime.datetime | None
    blocking_attempt_id: str | None
    expired_running_attempt_id: str | None


def evaluate_integration_catalog_sync_policy(
    policy_input: IntegrationCatalogSyncPolicyInput,
) -> IntegrationCatalogSyncPolicyDecision:
    """Evaluate integration and workspace synchronization limits."""
    stale = _snapshot_stale(
        current_snapshot_created_at=policy_input.current_snapshot_created_at,
        now=policy_input.now,
    )
    trigger = policy_input.trigger
    latest = policy_input.latest_catalog_attempt

    if trigger == IntegrationCatalogSyncTrigger.STALE_REFRESH and not stale:
        return _denied(
            stale=stale,
            reason=IntegrationCatalogSyncDenialReason.NOT_STALE,
        )

    expired_running_attempt_id: str | None = None
    if latest is not None and latest.status == LLMCatalogAttemptStatus.RUNNING:
        running_expires_at = latest.started_at + INTEGRATION_CATALOG_RUNNING_TIMEOUT
        if running_expires_at > policy_input.now:
            return _denied(
                stale=stale,
                reason=IntegrationCatalogSyncDenialReason.ALREADY_RUNNING,
                retry_at=running_expires_at,
                blocking_attempt_id=latest.id,
            )
        expired_running_attempt_id = latest.id

    state_change_trigger = trigger in {
        IntegrationCatalogSyncTrigger.CREATE,
        IntegrationCatalogSyncTrigger.CONFIG_UPDATE,
    }
    if state_change_trigger:
        return _allowed(
            stale=stale,
            expired_running_attempt_id=expired_running_attempt_id,
        )

    if (
        trigger == IntegrationCatalogSyncTrigger.STALE_REFRESH
        and latest is not None
        and latest.status == LLMCatalogAttemptStatus.FAILED
        and latest.automatic_retry_blocked
    ):
        return _denied(
            stale=stale,
            reason=IntegrationCatalogSyncDenialReason.AUTOMATIC_RETRY_BLOCKED,
        )

    retry_candidates: list[datetime.datetime] = []
    if latest is not None and expired_running_attempt_id is None:
        retry_candidates.append(latest.started_at + INTEGRATION_CATALOG_SYNC_COOLDOWN)
        if (
            latest.status == LLMCatalogAttemptStatus.FAILED
            and not latest.automatic_retry_blocked
            and latest.finished_at is not None
        ):
            retry_candidates.append(
                latest.finished_at + INTEGRATION_CATALOG_FAILURE_BACKOFF
            )
    workspace_latest = policy_input.latest_workspace_attempt
    if (
        workspace_latest is not None
        and workspace_latest.id != expired_running_attempt_id
    ):
        retry_candidates.append(
            workspace_latest.started_at + WORKSPACE_CATALOG_SYNC_COOLDOWN
        )
    retry_at = max(retry_candidates, default=None)
    if retry_at is not None and retry_at > policy_input.now:
        return _denied(
            stale=stale,
            reason=IntegrationCatalogSyncDenialReason.THROTTLED,
            retry_at=retry_at,
        )
    return _allowed(
        stale=stale,
        expired_running_attempt_id=expired_running_attempt_id,
    )


def _snapshot_stale(
    *,
    current_snapshot_created_at: datetime.datetime | None,
    now: datetime.datetime,
) -> bool:
    if current_snapshot_created_at is None:
        return True
    return current_snapshot_created_at + INTEGRATION_CATALOG_STALE_AFTER <= now


def _allowed(
    *,
    stale: bool,
    expired_running_attempt_id: str | None,
) -> IntegrationCatalogSyncPolicyDecision:
    return IntegrationCatalogSyncPolicyDecision(
        allowed=True,
        stale=stale,
        denial_reason=None,
        retry_at=None,
        blocking_attempt_id=None,
        expired_running_attempt_id=expired_running_attempt_id,
    )


def _denied(
    *,
    stale: bool,
    reason: IntegrationCatalogSyncDenialReason,
    retry_at: datetime.datetime | None = None,
    blocking_attempt_id: str | None = None,
) -> IntegrationCatalogSyncPolicyDecision:
    return IntegrationCatalogSyncPolicyDecision(
        allowed=False,
        stale=stale,
        denial_reason=reason,
        retry_at=retry_at,
        blocking_attempt_id=blocking_attempt_id,
        expired_running_attempt_id=None,
    )
