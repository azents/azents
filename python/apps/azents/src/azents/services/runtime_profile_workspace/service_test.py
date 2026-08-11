"""Workspace Runtime Profile deletion service tests."""

import datetime
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.runtime_profile import RuntimeProfileLifecycle
from azents.repos.runtime_profile.data import (
    WorkspaceRuntimeProfile,
    WorkspaceRuntimeProfileDeleteOutcome,
    WorkspaceRuntimeProfileDeletion,
)

from .service import (
    RuntimeProfileWorkspaceService,
    RuntimeProfileWorkspaceUnavailable,
)


def _profile(*, version: int = 8) -> WorkspaceRuntimeProfile:
    """Build current optimistic Profile evidence."""
    now = datetime.datetime(2026, 8, 11, tzinfo=datetime.UTC)
    return WorkspaceRuntimeProfile(
        id="profile-1",
        workspace_id="workspace-1",
        provider_id="provider-1",
        infrastructure_profile_id="infrastructure-1",
        display_name="Profile",
        description="Profile",
        lifecycle=RuntimeProfileLifecycle.ACTIVE,
        policy={"schema_version": 1},
        version=version,
        digest="a" * 64,
        created_by_workspace_user_id=None,
        updated_by_workspace_user_id=None,
        created_at=now,
        updated_at=now,
    )


def _deletion() -> WorkspaceRuntimeProfileDeletion:
    """Build one committed bounded deletion result."""
    return WorkspaceRuntimeProfileDeletion(
        profile_id="profile-1",
        cleared_workspace_default=True,
        cleared_agent_count=2,
        affected_running_runtime_count=1,
        superseded_recreation_operation_count=1,
    )


def _service(
    outcome: WorkspaceRuntimeProfileDeleteOutcome | None = None,
) -> tuple[RuntimeProfileWorkspaceService, AsyncMock, dict[str, bool]]:
    """Build the service with transaction-state tracking dependencies."""
    transaction = {"committed": False, "rolled_back": False}

    @asynccontextmanager
    async def session_manager() -> AsyncGenerator[AsyncSession, None]:
        try:
            yield AsyncMock(spec=AsyncSession)
        except Exception:
            transaction["rolled_back"] = True
            raise
        else:
            transaction["committed"] = True

    profile_repository = AsyncMock()
    if outcome is not None:
        profile_repository.delete_workspace_runtime_profile.return_value = outcome
    service = RuntimeProfileWorkspaceService(
        session_manager=session_manager,
        profile_repository=profile_repository,
        provider_repository=cast(Any, AsyncMock()),
        policy_repository=cast(Any, AsyncMock()),
        control_repository=cast(Any, AsyncMock()),
        workspace_repository=cast(Any, AsyncMock()),
    )
    return service, profile_repository, transaction


async def test_delete_profile_returns_committed_impact_and_logs_actor(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Successful deletion commits before emitting bounded audit context."""
    deletion = _deletion()
    service, repository, transaction = _service(
        WorkspaceRuntimeProfileDeleteOutcome(
            deletion=deletion,
            current_profile=None,
        )
    )

    with caplog.at_level(logging.INFO):
        result = await service.delete_profile(
            "workspace-1",
            "profile-1",
            expected_version=7,
            actor_workspace_user_id="workspace-user-1",
        )

    assert result == deletion
    assert transaction == {"committed": True, "rolled_back": False}
    repository.delete_workspace_runtime_profile.assert_awaited_once()
    record = next(
        record
        for record in caplog.records
        if record.message == "Workspace Runtime Profile deleted"
    )
    context = vars(record)
    assert context["workspace_id"] == "workspace-1"
    assert context["profile_id"] == "profile-1"
    assert context["profile_version"] == 7
    assert context["actor_workspace_user_id"] == "workspace-user-1"
    assert context["cleared_agent_count"] == 2
    assert context["affected_running_runtime_count"] == 1


@pytest.mark.parametrize(
    ("outcome", "expected_code", "expected_current"),
    [
        (
            WorkspaceRuntimeProfileDeleteOutcome(
                deletion=None,
                current_profile=None,
            ),
            "runtime_profile_not_found",
            None,
        ),
        (
            WorkspaceRuntimeProfileDeleteOutcome(
                deletion=None,
                current_profile=_profile(version=8),
            ),
            "runtime_profile_version_conflict",
            8,
        ),
    ],
)
async def test_delete_profile_maps_exact_optimistic_failure(
    outcome: WorkspaceRuntimeProfileDeleteOutcome,
    expected_code: str,
    expected_current: int | None,
) -> None:
    """Absence and stale versions remain distinct service failures."""
    service, _repository, transaction = _service(outcome)

    with pytest.raises(RuntimeProfileWorkspaceUnavailable) as captured:
        await service.delete_profile(
            "workspace-1",
            "profile-1",
            expected_version=7,
            actor_workspace_user_id="workspace-user-1",
        )

    assert captured.value.code == expected_code
    assert (
        captured.value.current_profile.version
        if captured.value.current_profile is not None
        else None
    ) == expected_current
    assert transaction == {"committed": False, "rolled_back": True}


async def test_delete_profile_rolls_back_repository_integrity_conflict() -> None:
    """A DB conflict leaves the service transaction through its rollback path."""
    service, repository, transaction = _service()
    repository.delete_workspace_runtime_profile.side_effect = IntegrityError(
        "delete Runtime Profile",
        {},
        Exception("concurrent selection"),
    )

    with pytest.raises(RuntimeProfileWorkspaceUnavailable) as captured:
        await service.delete_profile(
            "workspace-1",
            "profile-1",
            expected_version=7,
            actor_workspace_user_id="workspace-user-1",
        )

    assert captured.value.code == "runtime_profile_delete_conflict"
    assert transaction == {"committed": False, "rolled_back": True}
