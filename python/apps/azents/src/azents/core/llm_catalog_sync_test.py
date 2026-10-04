"""Existing synchronization policy evaluated from one current state."""

import datetime

import pytest

from azents.core.enums import LLMCatalogAttemptStatus
from azents.core.llm_catalog_sync import (
    CatalogProjectionVersion,
    CatalogSyncState,
    IntegrationCatalogSyncDenialReason,
    IntegrationCatalogSyncPolicyDecision,
    IntegrationCatalogSyncPolicyInput,
    IntegrationCatalogSyncTrigger,
    evaluate_integration_catalog_sync_policy,
)

_NOW = datetime.datetime(2026, 10, 3, 12, tzinfo=datetime.UTC)


def _sync(
    *,
    owner_id: str = "catalog",
    status: LLMCatalogAttemptStatus = LLMCatalogAttemptStatus.SUCCEEDED,
    started_at: datetime.datetime | None = None,
    finished_at: datetime.datetime | None = None,
    automatic_retry_blocked: bool = False,
) -> CatalogSyncState:
    return CatalogSyncState(
        owner_id=owner_id,
        work_token="active-work" if status == LLMCatalogAttemptStatus.RUNNING else None,
        status=status,
        started_at=started_at or _NOW - datetime.timedelta(hours=1),
        finished_at=finished_at,
        automatic_retry_blocked=automatic_retry_blocked,
    )


def _evaluate(
    *,
    trigger: IntegrationCatalogSyncTrigger,
    last_success_at: datetime.datetime | None = None,
    latest: CatalogSyncState | None = None,
    workspace_latest: CatalogSyncState | None = None,
) -> IntegrationCatalogSyncPolicyDecision:
    return evaluate_integration_catalog_sync_policy(
        IntegrationCatalogSyncPolicyInput(
            trigger=trigger,
            now=_NOW,
            last_success_at=last_success_at,
            current_projection_version=None,
            required_projection_version=None,
            latest_catalog_sync=latest,
            latest_workspace_sync=workspace_latest,
        )
    )


@pytest.mark.parametrize(
    "trigger",
    [IntegrationCatalogSyncTrigger.CREATE, IntegrationCatalogSyncTrigger.CONFIG_UPDATE],
)
def test_state_change_triggers_bypass_cooldown(
    trigger: IntegrationCatalogSyncTrigger,
) -> None:
    recent = _sync(started_at=_NOW - datetime.timedelta(seconds=1))
    assert _evaluate(trigger=trigger, latest=recent, workspace_latest=recent).allowed


def test_explicit_sync_is_throttled_per_integration() -> None:
    decision = _evaluate(
        trigger=IntegrationCatalogSyncTrigger.EXPLICIT,
        latest=_sync(started_at=_NOW - datetime.timedelta(seconds=10)),
    )
    assert not decision.allowed
    assert decision.denial_reason == IntegrationCatalogSyncDenialReason.THROTTLED
    assert decision.retry_at == _NOW + datetime.timedelta(seconds=20)


def test_completed_work_still_throttles_workspace_without_a_token() -> None:
    decision = _evaluate(
        trigger=IntegrationCatalogSyncTrigger.EXPLICIT,
        workspace_latest=_sync(
            owner_id="other-integration",
            started_at=_NOW - datetime.timedelta(seconds=2),
        ),
    )
    assert not decision.allowed
    assert decision.denial_reason == IntegrationCatalogSyncDenialReason.THROTTLED
    assert decision.retry_at == _NOW + datetime.timedelta(seconds=3)


def test_transient_failure_applies_existing_backoff() -> None:
    decision = _evaluate(
        trigger=IntegrationCatalogSyncTrigger.EXPLICIT,
        latest=_sync(
            status=LLMCatalogAttemptStatus.FAILED,
            started_at=_NOW - datetime.timedelta(minutes=1),
            finished_at=_NOW - datetime.timedelta(minutes=1),
        ),
    )
    assert not decision.allowed
    assert decision.denial_reason == IntegrationCatalogSyncDenialReason.THROTTLED
    assert decision.retry_at == _NOW + datetime.timedelta(minutes=4)


def test_credential_failure_blocks_only_automatic_retry() -> None:
    failure = _sync(
        status=LLMCatalogAttemptStatus.FAILED,
        finished_at=_NOW - datetime.timedelta(hours=1),
        automatic_retry_blocked=True,
    )
    automatic = _evaluate(
        trigger=IntegrationCatalogSyncTrigger.STALE_REFRESH, latest=failure
    )
    explicit = _evaluate(trigger=IntegrationCatalogSyncTrigger.EXPLICIT, latest=failure)
    assert not automatic.allowed
    assert (
        automatic.denial_reason
        == IntegrationCatalogSyncDenialReason.AUTOMATIC_RETRY_BLOCKED
    )
    assert explicit.allowed


def test_stale_refresh_requires_stale_success() -> None:
    decision = _evaluate(
        trigger=IntegrationCatalogSyncTrigger.STALE_REFRESH,
        last_success_at=_NOW - datetime.timedelta(minutes=14),
    )
    assert not decision.allowed
    assert decision.denial_reason == IntegrationCatalogSyncDenialReason.NOT_STALE
    assert not decision.stale


def test_stale_refresh_starts_after_existing_threshold() -> None:
    decision = _evaluate(
        trigger=IntegrationCatalogSyncTrigger.STALE_REFRESH,
        last_success_at=_NOW - datetime.timedelta(minutes=15),
    )
    assert decision.allowed
    assert decision.stale


def test_active_running_work_blocks_duplicate() -> None:
    running = _sync(
        status=LLMCatalogAttemptStatus.RUNNING,
        started_at=_NOW - datetime.timedelta(minutes=1),
    )
    decision = _evaluate(
        trigger=IntegrationCatalogSyncTrigger.CONFIG_UPDATE, latest=running
    )
    assert not decision.allowed
    assert decision.denial_reason == IntegrationCatalogSyncDenialReason.ALREADY_RUNNING
    assert decision.blocking_work_token == running.work_token


def test_expired_running_work_can_be_recovered() -> None:
    running = _sync(
        status=LLMCatalogAttemptStatus.RUNNING,
        started_at=_NOW - datetime.timedelta(minutes=16),
    )
    decision = _evaluate(
        trigger=IntegrationCatalogSyncTrigger.EXPLICIT,
        latest=running,
        workspace_latest=running,
    )
    assert decision.allowed
    assert decision.expired_work_token == running.work_token


@pytest.mark.parametrize(
    ("current", "required", "stale"),
    [
        (None, CatalogProjectionVersion("2", "5"), True),
        (
            CatalogProjectionVersion(None, None),
            CatalogProjectionVersion("2", "5"),
            True,
        ),
        (CatalogProjectionVersion("1", "5"), CatalogProjectionVersion("2", "5"), True),
        (CatalogProjectionVersion("2", "4"), CatalogProjectionVersion("2", "5"), True),
        (CatalogProjectionVersion("2", "5"), CatalogProjectionVersion("2", "5"), False),
        (CatalogProjectionVersion("1", "4"), None, False),
    ],
)
def test_current_code_compatibility_and_age_only_image_policy(
    current: CatalogProjectionVersion | None,
    required: CatalogProjectionVersion | None,
    stale: bool,
) -> None:
    decision = evaluate_integration_catalog_sync_policy(
        IntegrationCatalogSyncPolicyInput(
            trigger=IntegrationCatalogSyncTrigger.STALE_REFRESH,
            now=_NOW,
            last_success_at=_NOW,
            current_projection_version=current,
            required_projection_version=required,
            latest_catalog_sync=None,
            latest_workspace_sync=None,
        )
    )
    assert decision.stale is stale
    assert decision.allowed is stale
    if not stale:
        assert decision.denial_reason is IntegrationCatalogSyncDenialReason.NOT_STALE


@pytest.mark.parametrize(
    ("latest", "workspace_latest", "reason"),
    [
        (
            _sync(status=LLMCatalogAttemptStatus.RUNNING, started_at=_NOW),
            None,
            IntegrationCatalogSyncDenialReason.ALREADY_RUNNING,
        ),
        (
            _sync(started_at=_NOW - datetime.timedelta(seconds=1)),
            None,
            IntegrationCatalogSyncDenialReason.THROTTLED,
        ),
        (
            None,
            _sync(started_at=_NOW - datetime.timedelta(seconds=1)),
            IntegrationCatalogSyncDenialReason.THROTTLED,
        ),
        (
            _sync(
                status=LLMCatalogAttemptStatus.FAILED,
                started_at=_NOW - datetime.timedelta(minutes=1),
                finished_at=_NOW - datetime.timedelta(seconds=30),
            ),
            None,
            IntegrationCatalogSyncDenialReason.THROTTLED,
        ),
        (
            _sync(
                status=LLMCatalogAttemptStatus.FAILED,
                automatic_retry_blocked=True,
            ),
            None,
            IntegrationCatalogSyncDenialReason.AUTOMATIC_RETRY_BLOCKED,
        ),
    ],
)
def test_code_compatibility_refresh_preserves_all_existing_guards(
    latest: CatalogSyncState | None,
    workspace_latest: CatalogSyncState | None,
    reason: IntegrationCatalogSyncDenialReason,
) -> None:
    decision = evaluate_integration_catalog_sync_policy(
        IntegrationCatalogSyncPolicyInput(
            trigger=IntegrationCatalogSyncTrigger.STALE_REFRESH,
            now=_NOW,
            last_success_at=_NOW,
            current_projection_version=CatalogProjectionVersion("1", "4"),
            required_projection_version=CatalogProjectionVersion("2", "5"),
            latest_catalog_sync=latest,
            latest_workspace_sync=workspace_latest,
        )
    )
    assert decision.stale
    assert not decision.allowed
    assert decision.denial_reason is reason
