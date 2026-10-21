"""Current operation admission and detached fenced renewal behavior."""

import dataclasses
import datetime
from typing import NamedTuple
from unittest.mock import Mock, create_autospec

import pytest

from azents.core.google_oauth import (
    GoogleConnection,
    GoogleConnectionStatus,
    GoogleOAuthError,
    GoogleTokens,
)
from azents.core.google_policy import GoogleService
from azents.core.google_runtime import GoogleExecutionState
from azents.core.google_system_setting import GoogleApplicationRegistration
from azents.core.google_workspace_policy import GoogleWorkspaceOperation as Op
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
            services=(GoogleService.CALENDAR,),
            oauth_request_scopes=(
                "https://www.googleapis.com/auth/calendar.events.readonly",
                "https://www.googleapis.com/auth/calendar.events",
            ),
            timeout=30.0,
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
        1,
    )
    repo.load.return_value = current
    return Harness(
        GoogleRuntimeService(repo, app, provider),
        repo,
        provider,
        current,
        SessionExecutionOwner("session", 7),
    )


async def test_ungranted_write_rejected_before_renewal() -> None:
    h = _harness(expired=True)
    with pytest.raises(GoogleOAuthError) as caught:
        await h.service.authorize_operation(
            h.owner, "toolkit", Op.CALENDAR_DELETE_EVENT, ()
        )
    assert caught.value.code == "capability_unavailable"
    h.provider.refresh.assert_not_awaited()


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
    h.repo.load.side_effect = [h.current, reduced, reduced]
    h.repo.finalize_refresh.return_value = True
    h.provider.refresh.return_value = reduced_tokens
    with pytest.raises(GoogleOAuthError) as caught:
        await h.service.authorize_operation(
            h.owner, "toolkit", Op.CALENDAR_LIST_EVENTS, ()
        )
    assert caught.value.code == "capability_unavailable"
    h.provider.refresh.assert_awaited_once()


async def test_transient_renewal_failure_does_not_invalidate_saved_grant() -> None:
    h = _harness(expired=True)
    h.provider.refresh.side_effect = GoogleOAuthError(
        "provider_unavailable", "Remote unavailable."
    )
    with pytest.raises(GoogleOAuthError):
        await h.service.authorize_operation(
            h.owner, "toolkit", Op.CALENDAR_LIST_EVENTS, ()
        )
    h.repo.finalize_refresh.assert_not_awaited()


async def test_stale_invalid_grant_yields_to_newer_reconnect() -> None:
    h = _harness(expired=True)
    replacement = dataclasses.replace(
        h.current,
        connection=dataclasses.replace(
            h.current.connection,
            id="replacement",
            candidate=_candidate("replacement-token"),
        ),
    )
    h.repo.load.side_effect = [h.current, replacement, replacement]
    h.provider.refresh.side_effect = GoogleOAuthError("invalid_grant", "Rejected.")
    h.repo.finalize_refresh.return_value = False
    admitted = await h.service.authorize_operation(
        h.owner, "toolkit", Op.CALENDAR_LIST_EVENTS, ()
    )
    assert admitted.snapshot == replacement


async def test_model_projection_does_not_trigger_google_refresh() -> None:
    h = _harness(expired=True)
    assert await h.service.direct_operations(h.owner, "toolkit")
    h.provider.refresh.assert_not_awaited()
