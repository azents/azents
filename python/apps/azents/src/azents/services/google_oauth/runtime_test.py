"""Exact raw-tool admission, permission loss on renewal and stale 401 protection."""

import dataclasses
import datetime
from typing import NamedTuple
from unittest.mock import Mock, create_autospec

import pytest

from azents.core.google_oauth import (
    GoogleAuthorization,
    GoogleConnection,
    GoogleConnectionStatus,
    GoogleOAuthError,
    GoogleTokens,
)
from azents.core.google_policy import GoogleService, GoogleTask
from azents.core.google_runtime import GoogleExecutionState
from azents.core.google_system_setting import GoogleApplicationRegistration
from azents.core.session_resource_authority import SessionExecutionOwner
from azents.core.tools import GoogleToolkitConfig
from azents.repos.google_oauth.management_test import _candidate
from azents.repos.google_oauth.runtime import GoogleRuntimeRepository
from azents.services.google_application.service import GoogleApplicationService
from azents.services.google_oauth.provider import GoogleOAuthProvider
from azents.services.google_oauth.runtime import GoogleRuntimeService


class Harness(NamedTuple):
    service: GoogleRuntimeService
    repo: Mock
    provider: Mock
    current: GoogleExecutionState
    owner: SessionExecutionOwner


def _harness(*, expired: bool) -> Harness:
    repo = create_autospec(GoogleRuntimeRepository, instance=True)
    app = create_autospec(GoogleApplicationService, instance=True)
    provider = create_autospec(GoogleOAuthProvider, instance=True)
    registration = GoogleApplicationRegistration(
        "client", "secret", "g", "https://app.invalid/cb"
    )
    app.resolve.return_value = registration
    candidate = _candidate("current-token")
    if expired:
        candidate = candidate.model_copy(
            update={
                "tokens": candidate.tokens.model_copy(
                    update={
                        "expires_at": datetime.datetime.now(datetime.UTC)
                        - datetime.timedelta(minutes=1)
                    }
                )
            }
        )
    current = GoogleExecutionState(
        GoogleToolkitConfig(
            tasks=[GoogleTask.CALENDAR_READ, GoogleTask.CALENDAR_EDIT],
            timeout=30.0,
            security_risk_acknowledged=True,
        ),
        GoogleConnection(
            "connection",
            "toolkit",
            "client",
            candidate,
            GoogleConnectionStatus.CONNECTED,
            datetime.datetime.now(datetime.UTC),
            "encrypted",
        ),
        registration,
    )
    repo.load.return_value = current
    return Harness(
        GoogleRuntimeService(repo, app, provider),
        repo,
        provider,
        current,
        SessionExecutionOwner("session", 7),
    )


@pytest.mark.asyncio
async def test_ungranted_write_rejected_before_renewal() -> None:
    h = _harness(expired=True)
    with pytest.raises(GoogleOAuthError) as caught:
        await h.service.authorize_tool(
            h.owner, "toolkit", GoogleService.CALENDAR, "delete_event"
        )
    assert caught.value.code == "capability_unavailable"
    h.provider.refresh.assert_not_awaited()


@pytest.mark.asyncio
async def test_grant_reduction_during_renewal_denies_formerly_permitted_call() -> None:
    h = _harness(expired=True)
    reduced_tokens = GoogleTokens(
        access_token="fresh",
        refresh_token="renewal",
        granted_scopes=(),
        expires_at=datetime.datetime.now(datetime.UTC) + datetime.timedelta(hours=1),
    )
    reduced = dataclasses.replace(
        h.current,
        connection=dataclasses.replace(
            h.current.connection,
            candidate=h.current.connection.candidate.model_copy(
                update={"tokens": reduced_tokens}
            ),
        ),
    )
    h.repo.load.side_effect = [h.current, reduced]
    h.repo.finalize_refresh.return_value = True
    h.provider.refresh.return_value = reduced_tokens
    with pytest.raises(GoogleOAuthError) as caught:
        await h.service.authorize_tool(
            h.owner, "toolkit", GoogleService.CALENDAR, "list_events"
        )
    assert caught.value.code == "capability_unavailable"
    h.provider.refresh.assert_awaited_once()


@pytest.mark.asyncio
async def test_transient_renewal_failure_does_not_invalidate_saved_grant() -> None:
    h = _harness(expired=True)
    h.provider.refresh.side_effect = GoogleOAuthError(
        "provider_unavailable", "Remote unavailable."
    )
    with pytest.raises(GoogleOAuthError):
        await h.service.authorize_tool(
            h.owner, "toolkit", GoogleService.CALENDAR, "list_events"
        )
    h.repo.finalize_refresh.assert_not_awaited()


@pytest.mark.asyncio
async def test_stale_invalid_grant_yields_to_newer_reconnect() -> None:
    h = _harness(expired=True)
    candidate = _candidate("replacement-token")
    replacement = dataclasses.replace(
        h.current,
        connection=dataclasses.replace(
            h.current.connection,
            id="replacement",
            candidate=candidate,
        ),
    )
    h.repo.load.side_effect = [h.current, replacement]
    h.provider.refresh.side_effect = GoogleOAuthError("invalid_grant", "Rejected.")
    h.repo.finalize_refresh.return_value = False
    admitted = await h.service.authorize_tool(
        h.owner,
        "toolkit",
        GoogleService.CALENDAR,
        "list_events",
    )
    assert admitted == GoogleAuthorization("replacement-token", "replacement")


@pytest.mark.asyncio
@pytest.mark.parametrize("changed", ["id", "token"])
async def test_late_401_cannot_invalidate_changed_credentials(changed: str) -> None:
    h = _harness(expired=False)
    admitted = GoogleAuthorization("old-token", "old-connection")
    if changed == "id":
        admitted = GoogleAuthorization("current-token", "old-connection")
    else:
        admitted = GoogleAuthorization("old-token", "connection")
    await h.service.authentication_failed(h.owner, "toolkit", admitted)
    h.repo.finalize_refresh.assert_not_awaited()


@pytest.mark.asyncio
async def test_matching_401_finalizes_under_exact_snapshot_and_owner() -> None:
    h = _harness(expired=False)
    await h.service.authentication_failed(
        h.owner, "toolkit", GoogleAuthorization("current-token", "connection")
    )
    h.repo.finalize_refresh.assert_awaited_once_with(
        h.owner,
        snapshot=h.current,
        refreshed=None,
        rejected=True,
    )


@pytest.mark.asyncio
async def test_model_projection_does_not_trigger_google_refresh() -> None:
    h = _harness(expired=True)
    assert await h.service.permitted_tools(h.owner, "toolkit", GoogleService.CALENDAR)
    h.provider.refresh.assert_not_awaited()
