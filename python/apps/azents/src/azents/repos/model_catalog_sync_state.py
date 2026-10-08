"""One current source/catalog operational state, without attempt history."""

import datetime
from typing import Any

from azcommon.uuid import uuid7

from azents.core.enums import LLMCatalogAttemptStatus
from azents.rdb.models.llm_catalog import RDBLLMCatalog
from azents.rdb.models.model_metadata_source import RDBModelMetadataSource
from azents.repos.llm_catalog.data import LLMCatalogSyncStatus


def current_sync_status(
    owner: RDBLLMCatalog | RDBModelMetadataSource,
) -> LLMCatalogSyncStatus | None:
    """Detach a coherent current state from its already locked owner."""
    if owner.sync_status is None:
        return None
    if owner.sync_started_at is None:
        raise ValueError("Current synchronization state is missing its start time.")
    return LLMCatalogSyncStatus(
        owner_id=owner.id if isinstance(owner, RDBLLMCatalog) else owner.source_key,
        work_token=owner.sync_work_token,
        status=owner.sync_status,
        started_at=owner.sync_started_at,
        finished_at=owner.sync_finished_at,
        failure_code=owner.sync_failure_code,
        failure_message=owner.sync_failure_message,
        action_hint=owner.sync_action_hint,
        fetched_count=owner.sync_fetched_count,
        matched_count=owner.sync_matched_count,
        skipped_count=owner.sync_skipped_count,
        hidden_count=owner.sync_hidden_count,
        diagnostics=owner.sync_diagnostics,
    )


def start_sync(
    owner: RDBLLMCatalog | RDBModelMetadataSource,
    *,
    work_token: str | None,
    started_at: datetime.datetime,
    diagnostics: dict[str, Any] | None,
) -> str:
    """Replace only current operational state; preserve last successful data."""
    token = uuid7().hex if work_token is None else work_token
    owner.sync_work_token = token
    owner.sync_status = LLMCatalogAttemptStatus.RUNNING
    owner.sync_started_at = started_at
    owner.sync_finished_at = None
    owner.sync_failure_code = None
    owner.sync_failure_message = None
    owner.sync_action_hint = None
    owner.sync_fetched_count = 0
    owner.sync_matched_count = 0
    owner.sync_skipped_count = 0
    owner.sync_hidden_count = 0
    owner.sync_diagnostics = diagnostics
    return token


def fail_sync(
    owner: RDBLLMCatalog | RDBModelMetadataSource,
    *,
    work_token: str,
    finished_at: datetime.datetime,
    failure_code: str,
    failure_message: str,
    action_hint: str | None,
    diagnostics: dict[str, Any] | None,
) -> bool:
    """A superseded worker cannot mutate newer operational state."""
    if (
        owner.sync_work_token != work_token
        or owner.sync_status != LLMCatalogAttemptStatus.RUNNING
    ):
        return False
    owner.sync_work_token = None
    owner.sync_status = LLMCatalogAttemptStatus.FAILED
    owner.sync_finished_at = finished_at
    owner.sync_failure_code = failure_code
    owner.sync_failure_message = failure_message
    owner.sync_action_hint = action_hint
    owner.sync_diagnostics = diagnostics
    return True


def succeed_sync(
    owner: RDBLLMCatalog | RDBModelMetadataSource,
    *,
    work_token: str,
    finished_at: datetime.datetime,
    fetched_count: int,
    matched_count: int,
    skipped_count: int,
    hidden_count: int,
    diagnostics: dict[str, Any] | None,
) -> None:
    """Complete authorized work and clear its token, not its success timestamp."""
    if (
        owner.sync_work_token != work_token
        or owner.sync_status != LLMCatalogAttemptStatus.RUNNING
    ):
        raise ValueError("Synchronization no longer owns publication.")
    owner.sync_work_token = None
    owner.sync_status = LLMCatalogAttemptStatus.SUCCEEDED
    owner.sync_finished_at = finished_at
    owner.sync_failure_code = None
    owner.sync_failure_message = None
    owner.sync_action_hint = None
    owner.sync_fetched_count = fetched_count
    owner.sync_matched_count = matched_count
    owner.sync_skipped_count = skipped_count
    owner.sync_hidden_count = hidden_count
    owner.sync_diagnostics = diagnostics
