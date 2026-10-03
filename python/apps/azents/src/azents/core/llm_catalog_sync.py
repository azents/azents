"""Integration model catalog current synchronization policy."""

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
class CatalogSyncState:
    """Current operational facts used to evaluate synchronization policy."""

    owner_id: str
    work_token: str | None
    status: LLMCatalogAttemptStatus
    started_at: datetime.datetime
    finished_at: datetime.datetime | None
    automatic_retry_blocked: bool


@dataclasses.dataclass(frozen=True)
class IntegrationCatalogSyncPolicyInput:
    """Current success and sync state required to decide whether work may start."""

    trigger: IntegrationCatalogSyncTrigger
    now: datetime.datetime
    last_success_at: datetime.datetime | None
    latest_catalog_sync: CatalogSyncState | None
    latest_workspace_sync: CatalogSyncState | None


@dataclasses.dataclass(frozen=True)
class IntegrationCatalogSyncPolicyDecision:
    """Synchronization decision; tokens identify active work only."""

    allowed: bool
    stale: bool
    denial_reason: IntegrationCatalogSyncDenialReason | None
    retry_at: datetime.datetime | None
    blocking_work_token: str | None
    expired_work_token: str | None


def evaluate_integration_catalog_sync_policy(
    policy_input: IntegrationCatalogSyncPolicyInput,
) -> IntegrationCatalogSyncPolicyDecision:
    """Preserve existing integration/workspace cooldown, backoff and lease policy."""
    stale = (
        policy_input.last_success_at is None
        or policy_input.last_success_at + INTEGRATION_CATALOG_STALE_AFTER
        <= policy_input.now
    )
    trigger = policy_input.trigger
    latest = policy_input.latest_catalog_sync
    if trigger == IntegrationCatalogSyncTrigger.STALE_REFRESH and not stale:
        return _denied(stale=stale, reason=IntegrationCatalogSyncDenialReason.NOT_STALE)
    expired_work_token = None
    if latest is not None and latest.status == LLMCatalogAttemptStatus.RUNNING:
        if latest.work_token is None:
            raise ValueError("Running catalog synchronization must own a work token.")
        running_expires_at = latest.started_at + INTEGRATION_CATALOG_RUNNING_TIMEOUT
        if running_expires_at > policy_input.now:
            return _denied(
                stale=stale,
                reason=IntegrationCatalogSyncDenialReason.ALREADY_RUNNING,
                retry_at=running_expires_at,
                blocking_work_token=latest.work_token,
            )
        expired_work_token = latest.work_token
    if trigger in {
        IntegrationCatalogSyncTrigger.CREATE,
        IntegrationCatalogSyncTrigger.CONFIG_UPDATE,
    }:
        return _allowed(stale=stale, expired_work_token=expired_work_token)
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
    if latest is not None and expired_work_token is None:
        retry_candidates.append(latest.started_at + INTEGRATION_CATALOG_SYNC_COOLDOWN)
        if (
            latest.status == LLMCatalogAttemptStatus.FAILED
            and not latest.automatic_retry_blocked
            and latest.finished_at is not None
        ):
            retry_candidates.append(
                latest.finished_at + INTEGRATION_CATALOG_FAILURE_BACKOFF
            )
    workspace_latest = policy_input.latest_workspace_sync
    if workspace_latest is not None and (
        expired_work_token is None or workspace_latest.work_token != expired_work_token
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
    return _allowed(stale=stale, expired_work_token=expired_work_token)


def _allowed(
    *, stale: bool, expired_work_token: str | None
) -> IntegrationCatalogSyncPolicyDecision:
    return IntegrationCatalogSyncPolicyDecision(
        allowed=True,
        stale=stale,
        denial_reason=None,
        retry_at=None,
        blocking_work_token=None,
        expired_work_token=expired_work_token,
    )


def _denied(
    *,
    stale: bool,
    reason: IntegrationCatalogSyncDenialReason,
    retry_at: datetime.datetime | None = None,
    blocking_work_token: str | None = None,
) -> IntegrationCatalogSyncPolicyDecision:
    return IntegrationCatalogSyncPolicyDecision(
        allowed=False,
        stale=stale,
        denial_reason=reason,
        retry_at=retry_at,
        blocking_work_token=blocking_work_token,
        expired_work_token=None,
    )
