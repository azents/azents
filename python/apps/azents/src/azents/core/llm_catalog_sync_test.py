"""Tests for integration model catalog synchronization policy."""

import datetime

import pytest

from azents.core.enums import LLMCatalogAttemptStatus
from azents.core.llm_catalog_sync import (
    CatalogSyncAttemptState,
    IntegrationCatalogSyncDenialReason,
    IntegrationCatalogSyncPolicyDecision,
    IntegrationCatalogSyncPolicyInput,
    IntegrationCatalogSyncTrigger,
    evaluate_integration_catalog_sync_policy,
)

_NOW = datetime.datetime(2026, 7, 16, 12, 0, tzinfo=datetime.UTC)


def _attempt(
    *,
    attempt_id: str = "attempt",
    status: LLMCatalogAttemptStatus = LLMCatalogAttemptStatus.SUCCEEDED,
    started_at: datetime.datetime | None = None,
    finished_at: datetime.datetime | None = None,
    automatic_retry_blocked: bool = False,
) -> CatalogSyncAttemptState:
    return CatalogSyncAttemptState(
        id=attempt_id,
        status=status,
        started_at=started_at or _NOW - datetime.timedelta(hours=1),
        finished_at=finished_at,
        automatic_retry_blocked=automatic_retry_blocked,
    )


def _evaluate(
    *,
    trigger: IntegrationCatalogSyncTrigger,
    snapshot_created_at: datetime.datetime | None = None,
    latest: CatalogSyncAttemptState | None = None,
    workspace_latest: CatalogSyncAttemptState | None = None,
) -> IntegrationCatalogSyncPolicyDecision:
    return evaluate_integration_catalog_sync_policy(
        IntegrationCatalogSyncPolicyInput(
            trigger=trigger,
            now=_NOW,
            current_snapshot_created_at=snapshot_created_at,
            latest_catalog_attempt=latest,
            latest_workspace_attempt=workspace_latest,
        )
    )


@pytest.mark.parametrize(
    "trigger",
    [
        IntegrationCatalogSyncTrigger.CREATE,
        IntegrationCatalogSyncTrigger.CONFIG_UPDATE,
    ],
)
def test_state_change_triggers_bypass_cooldown(
    trigger: IntegrationCatalogSyncTrigger,
) -> None:
    recent = _attempt(started_at=_NOW - datetime.timedelta(seconds=1))

    decision = _evaluate(
        trigger=trigger,
        latest=recent,
        workspace_latest=recent,
    )

    assert decision.allowed


def test_explicit_sync_is_throttled_per_integration() -> None:
    decision = _evaluate(
        trigger=IntegrationCatalogSyncTrigger.EXPLICIT,
        latest=_attempt(started_at=_NOW - datetime.timedelta(seconds=10)),
    )

    assert not decision.allowed
    assert decision.denial_reason == IntegrationCatalogSyncDenialReason.THROTTLED
    assert decision.retry_at == _NOW + datetime.timedelta(seconds=20)


def test_explicit_sync_is_throttled_per_workspace() -> None:
    decision = _evaluate(
        trigger=IntegrationCatalogSyncTrigger.EXPLICIT,
        workspace_latest=_attempt(
            attempt_id="other-integration",
            started_at=_NOW - datetime.timedelta(seconds=2),
        ),
    )

    assert not decision.allowed
    assert decision.denial_reason == IntegrationCatalogSyncDenialReason.THROTTLED
    assert decision.retry_at == _NOW + datetime.timedelta(seconds=3)


def test_transient_failure_applies_backoff() -> None:
    decision = _evaluate(
        trigger=IntegrationCatalogSyncTrigger.EXPLICIT,
        latest=_attempt(
            status=LLMCatalogAttemptStatus.FAILED,
            started_at=_NOW - datetime.timedelta(minutes=1),
            finished_at=_NOW - datetime.timedelta(minutes=1),
        ),
    )

    assert not decision.allowed
    assert decision.denial_reason == IntegrationCatalogSyncDenialReason.THROTTLED
    assert decision.retry_at == _NOW + datetime.timedelta(minutes=4)


def test_credential_failure_blocks_only_automatic_retry() -> None:
    failure = _attempt(
        status=LLMCatalogAttemptStatus.FAILED,
        started_at=_NOW - datetime.timedelta(hours=1),
        finished_at=_NOW - datetime.timedelta(hours=1),
        automatic_retry_blocked=True,
    )

    automatic = _evaluate(
        trigger=IntegrationCatalogSyncTrigger.STALE_REFRESH,
        latest=failure,
    )
    explicit = _evaluate(
        trigger=IntegrationCatalogSyncTrigger.EXPLICIT,
        latest=failure,
    )

    assert not automatic.allowed
    assert (
        automatic.denial_reason
        == IntegrationCatalogSyncDenialReason.AUTOMATIC_RETRY_BLOCKED
    )
    assert explicit.allowed


def test_stale_refresh_requires_stale_snapshot() -> None:
    decision = _evaluate(
        trigger=IntegrationCatalogSyncTrigger.STALE_REFRESH,
        snapshot_created_at=_NOW - datetime.timedelta(minutes=14),
    )

    assert not decision.allowed
    assert decision.denial_reason == IntegrationCatalogSyncDenialReason.NOT_STALE
    assert not decision.stale


def test_stale_refresh_starts_after_threshold() -> None:
    decision = _evaluate(
        trigger=IntegrationCatalogSyncTrigger.STALE_REFRESH,
        snapshot_created_at=_NOW - datetime.timedelta(minutes=15),
    )

    assert decision.allowed
    assert decision.stale


def test_active_running_attempt_blocks_duplicate() -> None:
    running = _attempt(
        status=LLMCatalogAttemptStatus.RUNNING,
        started_at=_NOW - datetime.timedelta(minutes=1),
    )

    decision = _evaluate(
        trigger=IntegrationCatalogSyncTrigger.CONFIG_UPDATE,
        latest=running,
    )

    assert not decision.allowed
    assert decision.denial_reason == IntegrationCatalogSyncDenialReason.ALREADY_RUNNING


def test_expired_running_attempt_can_be_recovered() -> None:
    running = _attempt(
        status=LLMCatalogAttemptStatus.RUNNING,
        started_at=_NOW - datetime.timedelta(minutes=16),
    )

    decision = _evaluate(
        trigger=IntegrationCatalogSyncTrigger.EXPLICIT,
        latest=running,
        workspace_latest=running,
    )

    assert decision.allowed
    assert decision.expired_running_attempt_id == running.id
