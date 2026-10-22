"""Real PostgreSQL Picker authority, rotation preservation and current-state fences."""

import asyncio
import dataclasses
from typing import NamedTuple
from unittest.mock import NonCallableMock, create_autospec

import pytest
import sqlalchemy as sa

from azents.core.google_oauth import (
    GoogleConnectionStatus,
    GoogleOAuthError,
    GoogleReconnectSettings,
    GoogleSetup,
)
from azents.core.google_picker import GooglePickerState
from azents.core.google_policy import GoogleService
from azents.core.google_system_setting import (
    GoogleApplicationConfig,
    GooglePickerApplication,
)
from azents.core.google_tool_groups import groups_for_services
from azents.core.google_workspace_policy import GOOGLE_PICKER_SCOPE
from azents.core.system_setting import ResolvedSystemSetting, SystemSettingFieldSource
from azents.rdb.models.google_oauth import RDBGoogleConnection
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.google_oauth.management_test import (
    Harness,
    _candidate,
    _google,
    _settings,
)
from azents.services.google_application.service import GoogleApplicationService
from azents.services.google_oauth.data import GooglePickerTokenInput
from azents.services.google_oauth.picker import GooglePickerService
from azents.services.google_oauth.provider import (
    GoogleOAuthProvider,
    GoogleTokenResponse,
)


class PickerHarness(NamedTuple):
    root: Harness
    snapshot: GooglePickerState


async def _harness(manager: SessionManager[WriteSession]) -> PickerHarness:
    h = await _google(manager)
    setup = GoogleSetup.model_validate(
        {
            **h.setup.model_dump(),
            "services": (GoogleService.DRIVE,),
            "oauth_request_scopes": (GOOGLE_PICKER_SCOPE,),
            "tool_groups": [
                item.value for item in groups_for_services((GoogleService.DRIVE,))
            ],
        }
    )
    h = h._replace(setup=setup)
    payloads = h.repo.payloads
    assert isinstance(payloads, NonCallableMock)
    current = payloads.resolve_current.return_value
    assert isinstance(current, ResolvedSystemSetting)
    payloads.resolve_current.return_value = dataclasses.replace(
        current,
        config=GoogleApplicationConfig(
            client_id="client", picker_api_key="browser-key", picker_app_id="123456789"
        ),
        field_sources={
            **current.field_sources,
            "picker_api_key": SystemSettingFieldSource.ADMIN,
            "picker_app_id": SystemSettingFieldSource.ADMIN,
        },
    )
    attempt = await h.repo.start(
        h.subject, registration=h.registration, setup=setup, target_toolkit_id=None
    )
    await h.repo.claim(
        h.subject,
        attempt_id=attempt.id,
        nonce=setup.state_nonce,
        registration=h.registration,
    )
    candidate = _candidate("MAIN-PICKER-ACCESS")
    candidate = candidate.model_copy(
        update={
            "tokens": candidate.tokens.model_copy(
                update={
                    "granted_scopes": (
                        GOOGLE_PICKER_SCOPE,
                        "https://www.googleapis.com/auth/drive.readonly",
                    )
                }
            ),
            "requested_scopes": setup.oauth_request_scopes,
        }
    )
    await h.repo.stage(
        h.subject,
        attempt_id=attempt.id,
        registration=h.registration,
        candidate=candidate,
    )
    settings = _settings().model_copy(
        update={
            "services": setup.services,
            "oauth_request_scopes": setup.oauth_request_scopes,
            "tool_groups": groups_for_services(setup.services),
        }
    )
    published = await h.repo.confirm(
        h.subject, attempt_id=attempt.id, registration=h.registration, settings=settings
    )
    saved = await h.repo.saved(h.subject, published.toolkit_id)
    snapshot = await h.repo.admit_picker(
        h.subject,
        toolkit_id=published.toolkit_id,
        expected_revision=saved.revision,
        connection_id=published.connection_id,
        application=GooglePickerApplication(h.registration, "browser-key", "123456789"),
    )
    return PickerHarness(h, snapshot)


async def test_valid_picker_finalization_does_not_replace_main_credential(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    h, snapshot = await _harness(rdb_session_manager)
    await h.repo.finalize_picker(snapshot, rotated_refresh=None, rejected=False)
    saved = await h.repo.saved(h.subject, snapshot.toolkit_id)
    assert saved.connection == snapshot.connection
    assert saved.revision == snapshot.revision


async def test_rotation_preserves_only_renewal_and_requires_reconnect(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    h, snapshot = await _harness(rdb_session_manager)
    await h.repo.finalize_picker(
        snapshot, rotated_refresh="ROTATED-PICKER-REFRESH", rejected=False
    )
    saved = await h.repo.saved(h.subject, snapshot.toolkit_id)
    assert saved.connection is not None
    assert saved.connection.id == snapshot.connection.id
    assert saved.connection.status is GoogleConnectionStatus.RECONNECT_REQUIRED
    previous = snapshot.connection.candidate
    current = saved.connection.candidate
    assert current.tokens.refresh_token == "ROTATED-PICKER-REFRESH"
    assert current.tokens.access_token == previous.tokens.access_token
    assert current.tokens.granted_scopes == previous.tokens.granted_scopes
    assert current.tokens.expires_at == previous.tokens.expires_at
    assert current.identity == previous.identity
    assert current.requested_scopes == previous.requested_scopes
    with pytest.raises(GoogleOAuthError) as error:
        await h.repo.finalize_picker(snapshot, rotated_refresh=None, rejected=True)
    assert error.value.code == "stale"


@pytest.mark.parametrize(
    "scopes",
    [
        None,
        (),
        ("https://www.googleapis.com/auth/drive",),
        ("https://www.googleapis.com/auth/drive.readonly",),
    ],
)
async def test_actual_file_scope_is_required_even_for_semantically_broad_grant(
    rdb_session_manager: SessionManager[WriteSession],
    scopes: tuple[str, ...] | None,
) -> None:
    h, snapshot = await _harness(rdb_session_manager)
    candidate = snapshot.connection.candidate
    changed = candidate.model_copy(
        update={
            "tokens": candidate.tokens.model_copy(update={"granted_scopes": scopes})
        }
    )
    async with rdb_session_manager() as session:
        await session.write_session.execute(
            sa.update(RDBGoogleConnection)
            .where(RDBGoogleConnection.id == snapshot.connection.id)
            .values(encrypted_payload=h.repo.cipher.encrypt(changed.model_dump_json()))
        )
    with pytest.raises(GoogleOAuthError) as error:
        await h.repo.admit_picker(
            h.subject,
            toolkit_id=snapshot.toolkit_id,
            expected_revision=snapshot.revision,
            connection_id=snapshot.connection.id,
            application=snapshot.application,
        )
    assert error.value.code == "picker_scope_required"
    saved = await h.repo.saved(h.subject, snapshot.toolkit_id)
    assert (
        saved.connection is not None
        and saved.connection.status is GoogleConnectionStatus.CONNECTED
    )


async def test_real_service_rechecks_switch_after_provider_io_outside_transactions(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    h, snapshot = await _harness(rdb_session_manager)
    application = create_autospec(GoogleApplicationService, instance=True)
    application.picker.return_value = snapshot.application
    provider = create_autospec(GoogleOAuthProvider, instance=True)

    async def issue(registration: object, refresh: str) -> GoogleTokenResponse:
        # This independent write would block if provider I/O retained the
        # admission transaction and its Toolkit/Workspace locks.
        await h.repo.update_services(
            h.subject,
            toolkit_id=snapshot.toolkit_id,
            expected_revision=snapshot.revision,
            services=(),
            tool_groups=groups_for_services(("calendar", "drive", "gmail")),
        )
        return GoogleTokenResponse.model_validate(
            {
                "access_token": "NARROW-UNDELIVERED",
                "token_type": "Bearer",
                "scope": GOOGLE_PICKER_SCOPE,
                "expires_in": 3600,
            }
        )

    provider.refresh_picker.side_effect = issue
    service = GooglePickerService(h.repo, application, provider)
    async with asyncio.timeout(5):
        with pytest.raises(GoogleOAuthError) as error:
            await service.issue(
                h.subject,
                snapshot.toolkit_id,
                GooglePickerTokenInput(
                    expected_revision=snapshot.revision,
                    connection_id=snapshot.connection.id,
                ),
            )
    assert error.value.code == "stale"
    provider.refresh_picker.assert_awaited_once()
    saved = await h.repo.saved(h.subject, snapshot.toolkit_id)
    assert saved.services == () and saved.connection == snapshot.connection


async def test_older_rotation_cannot_invalidate_or_overwrite_reconnected_grant(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    h, snapshot = await _harness(rdb_session_manager)
    attempt = await h.repo.start(
        h.subject,
        registration=h.registration,
        setup=h.setup,
        target_toolkit_id=snapshot.toolkit_id,
    )
    await h.repo.claim(
        h.subject,
        attempt_id=attempt.id,
        nonce=h.setup.state_nonce,
        registration=h.registration,
    )
    new = _candidate("NEW-CONNECTION-ACCESS")
    new = new.model_copy(
        update={
            "tokens": new.tokens.model_copy(
                update={"granted_scopes": (GOOGLE_PICKER_SCOPE,)}
            ),
            "requested_scopes": h.setup.oauth_request_scopes,
        }
    )
    await h.repo.stage(
        h.subject, attempt_id=attempt.id, registration=h.registration, candidate=new
    )
    publication = await h.repo.confirm(
        h.subject,
        attempt_id=attempt.id,
        registration=h.registration,
        settings=GoogleReconnectSettings(
            services=h.setup.services,
            oauth_request_scopes=h.setup.oauth_request_scopes,
            timeout=h.setup.timeout,
            tool_groups=groups_for_services(h.setup.services),
        ),
    )
    with pytest.raises(GoogleOAuthError) as error:
        await h.repo.finalize_picker(
            snapshot, rotated_refresh="OLD-ROTATED-REFRESH", rejected=False
        )
    assert error.value.code == "stale"
    saved = await h.repo.saved(h.subject, snapshot.toolkit_id)
    assert (
        saved.connection is not None
        and saved.connection.id == publication.connection_id
    )
    assert saved.connection.status is GoogleConnectionStatus.CONNECTED
    assert saved.connection.candidate == new


async def test_saved_owner_context_and_expected_identity_are_not_borrowable(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    h, snapshot = await _harness(rdb_session_manager)
    with pytest.raises(GoogleOAuthError):
        await h.repo.admit_picker(
            dataclasses.replace(h.subject, workspace_id="other-workspace"),
            toolkit_id=snapshot.toolkit_id,
            expected_revision=snapshot.revision,
            connection_id=snapshot.connection.id,
            application=snapshot.application,
        )
    with pytest.raises(GoogleOAuthError) as error:
        await h.repo.admit_picker(
            h.subject,
            toolkit_id=snapshot.toolkit_id,
            expected_revision=snapshot.revision,
            connection_id="other-grant",
            application=snapshot.application,
        )
    assert error.value.code == "stale"
