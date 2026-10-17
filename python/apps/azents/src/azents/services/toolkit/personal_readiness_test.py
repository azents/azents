"""Personal Google management uses current safe grant and registration semantics."""

import dataclasses
import datetime

import pytest

from azents.core.google_oauth import (
    GoogleConnection,
    GoogleConnectionStatus,
    GoogleOAuthError,
    GooglePersonalSubject,
    GoogleSavedConnection,
)
from azents.repos.google_oauth.management_test import _candidate, _settings
from azents.repos.toolkit.data import ToolkitCreation
from azents.repos.toolkit.personal_management_test import Harness
from azents.repos.toolkit.personal_management_test import (
    fixture as fixture,  # noqa: PLC0414 -- shared PostgreSQL foundation
)
from azents.repos.toolkit.personal_management_test import (
    harness as harness,  # noqa: PLC0414 -- current account and owner repository
)
from azents.services.google_oauth.service_test import _harness as google_harness


@pytest.mark.parametrize(
    "state",
    [
        "connected",
        "not_connected",
        "reconnect_required",
        "client_changed",
        "operator_setup_required",
    ],
)
@pytest.mark.parametrize("enabled", [True, False])
async def test_google_readiness_in_detail_list_and_agent_choices(
    harness: Harness, state: str, enabled: bool
) -> None:
    h = harness
    google = google_harness()
    service = dataclasses.replace(h.service, google=google.service)
    settings = _settings()
    saved = await h.repository.create(
        h.subject,
        ToolkitCreation(
            toolkit_type="google",
            name="Personal Google",
            slug="google",
            config={
                "tasks": [task.value for task in settings.tasks],
                "timeout": settings.timeout,
                "security_risk_acknowledged": True,
            },
            enabled=enabled,
            always_expose_tools=False,
        ),
        platform_authority=None,
    )
    candidate = _candidate("fixture-readiness-token")
    connection = GoogleConnection(
        "fixture-grant",
        saved.toolkit.id,
        "client",
        candidate,
        GoogleConnectionStatus.RECONNECT_REQUIRED
        if state == "reconnect_required"
        else GoogleConnectionStatus.CONNECTED,
        datetime.datetime.now(datetime.UTC),
        "fixture-encrypted-payload",
    )
    google.repo.saved.return_value = GoogleSavedConnection(
        saved.toolkit.id,
        settings.tasks,
        settings.timeout,
        None if state == "not_connected" else connection,
    )
    if state == "client_changed":
        google.application.resolve.return_value = dataclasses.replace(
            google.application.resolve.return_value, client_id="changed-client"
        )
    if state == "operator_setup_required":
        google.application.resolve.side_effect = GoogleOAuthError(
            "operator_setup_required", "Google registration is unavailable."
        )
    expected = (
        "disabled"
        if not enabled
        else "ready"
        if state == "connected"
        else "authorization_required"
    )
    detail = await service.get(h.subject, saved.toolkit.id)
    [listed] = await service.list(h.subject)
    [choice] = await service.agent_connections(h.subject, h.foundation.agent_ids[0])
    assert detail.readiness == listed.readiness == choice.readiness == expected
    google.repo.saved.assert_awaited_with(
        GooglePersonalSubject(
            h.subject.user_id, h.subject.session_id, saved.toolkit.owner
        ),
        saved.toolkit.id,
    )
    # Readiness uses saved evidence only, never token renewal or a remote access probe.
    assert google.provider.mock_calls == []
