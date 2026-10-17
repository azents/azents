"""Personal Google current source admission surrounds real grant refresh CAS."""

import datetime
from unittest.mock import AsyncMock, Mock, create_autospec

import pytest
from sqlalchemy import select

from azents.core.google_oauth import (
    GoogleConnectionStatus,
    GoogleOAuthError,
    GoogleTokens,
)
from azents.core.google_policy import GoogleService, GoogleTask, permitted_tools
from azents.core.google_system_setting import (
    GoogleApplicationConfig,
    GoogleApplicationRegistration,
    GoogleApplicationSecrets,
)
from azents.core.personal_toolkit import PersonalToolkitAccessMutation
from azents.core.system_setting import (
    ResolvedSystemSetting,
    SystemSettingFieldSource,
    SystemSettingSection,
)
from azents.core.system_setting_payload import SystemSettingPayloadResolver
from azents.core.system_setting_registry import get_system_setting_registry
from azents.core.toolkit_ownership import PersonalToolkitAccessMode as Mode
from azents.rdb.models.google_oauth import RDBGoogleConnection
from azents.repos.google_oauth.management_test import _candidate
from azents.repos.google_oauth.runtime import GoogleRuntimeRepository
from azents.repos.system_setting.repository import SystemSettingRepository
from azents.repos.toolkit import ToolkitRepository
from azents.repos.toolkit.personal_runtime_test import Harness
from azents.repos.toolkit.personal_runtime_test import (
    fixture as fixture,  # noqa: PLC0414 -- committed ownership database fixture
)
from azents.repos.toolkit.personal_runtime_test import (
    runtime as runtime,  # noqa: PLC0414 -- current canonical root and source
)
from azents.repos.toolkit.personal_test import creation
from azents.services.google_application.service import GoogleApplicationService
from azents.services.google_oauth.provider import GoogleOAuthProvider
from azents.services.google_oauth.runtime import GoogleRuntimeService


@pytest.mark.parametrize("outcome", ["success", "invalid_grant", "transient"])
@pytest.mark.parametrize("withdrawal", ["before", "during", "none"])
async def test_google_personal_current_admission_and_post_gap_refresh_publication(
    runtime: Harness,
    outcome: str,
    withdrawal: str,
) -> None:
    h = runtime
    f = h.foundation
    saved = await f.operations.create(
        user_id=f.user_id,
        create=creation().model_copy(
            update={
                "toolkit_type": "google",
                "config": {
                    "tasks": [GoogleTask.CALENDAR_READ.value],
                    "security_risk_acknowledged": True,
                },
                "credentials": None,
            }
        ),
    )
    assert f.repository.cipher is not None
    cipher = f.repository.cipher
    candidate = _candidate("fixture-old-token")
    candidate = candidate.model_copy(
        update={
            "tokens": candidate.tokens.model_copy(
                update={
                    "expires_at": datetime.datetime.now(datetime.UTC)
                    - datetime.timedelta(seconds=1),
                }
            )
        }
    )
    async with f.writes() as session:
        session.write_session.add(
            RDBGoogleConnection(
                toolkit_id=saved.id,
                client_id="client",
                encrypted_payload=cipher.encrypt(candidate.model_dump_json()),
                status=GoogleConnectionStatus.CONNECTED,
            )
        )
    root = await h.root(f.user_id, 0)
    [source] = await h.sources(root)
    registration = GoogleApplicationRegistration(
        "client",
        "fixture-secret",
        "generation",
        "https://app.test/oauth/google/callback",
    )
    payloads = Mock(spec=SystemSettingPayloadResolver)
    payloads.registry = get_system_setting_registry()
    payloads.resolve_current.return_value = ResolvedSystemSetting(
        SystemSettingSection.GOOGLE_OAUTH,
        1,
        0,
        GoogleApplicationConfig(client_id="client"),
        GoogleApplicationSecrets(client_secret="fixture-secret"),
        {
            "client_id": SystemSettingFieldSource.ADMIN,
            "client_secret": SystemSettingFieldSource.ADMIN,
        },
        "generation",
    )
    repository = GoogleRuntimeRepository(
        f.writes, cipher, ToolkitRepository(cipher), SystemSettingRepository(), payloads
    ).for_personal(source.target)
    application = create_autospec(GoogleApplicationService, instance=True)
    application.resolve.return_value = registration
    provider = create_autospec(GoogleOAuthProvider, instance=True)
    service = GoogleRuntimeService(repository, application, provider)

    async def withdraw() -> None:
        await f.operations.mutate_access(
            user_id=f.user_id,
            mutations=[
                PersonalToolkitAccessMutation(
                    saved.id,
                    None,
                    frozenset(),
                    frozenset([root.agent_id]),
                    Mode.ALL,
                )
            ],
        )

    async def refresh(*args: object) -> GoogleTokens:
        del args
        if withdrawal == "during":
            await withdraw()
        if outcome != "success":
            raise GoogleOAuthError(
                "invalid_grant"
                if outcome == "invalid_grant"
                else "provider_unavailable",
                "fixture bounded failure",
            )
        return candidate.tokens.model_copy(
            update={
                "access_token": "fixture-new-token",
                "expires_at": datetime.datetime.now(datetime.UTC)
                + datetime.timedelta(hours=1),
            }
        )

    provider.refresh = AsyncMock(side_effect=refresh)
    if withdrawal == "before":
        await withdraw()
    raw_name = next(
        iter(
            permitted_tools(
                (GoogleTask.CALENDAR_READ,),
                candidate.tokens.granted_scopes,
                GoogleService.CALENDAR,
            )
        )
    )
    if withdrawal == "none" and outcome == "success":
        admitted = await service.authorize_tool(
            root.owner, saved.id, GoogleService.CALENDAR, raw_name
        )
        assert admitted.access_token == "fixture-new-token"
    else:
        with pytest.raises(GoogleOAuthError):
            await service.authorize_tool(
                root.owner, saved.id, GoogleService.CALENDAR, raw_name
            )
    async with f.writes() as session:
        row = await session.read_session.scalar(
            select(RDBGoogleConnection).where(
                RDBGoogleConnection.toolkit_id == saved.id
            )
        )
        assert row is not None
        if withdrawal != "none":
            assert cipher.decrypt(row.encrypted_payload) == candidate.model_dump_json()
            assert row.status is GoogleConnectionStatus.CONNECTED
        elif outcome == "invalid_grant":
            assert row.status is GoogleConnectionStatus.RECONNECT_REQUIRED
    if withdrawal == "before":
        provider.refresh.assert_not_awaited()
    else:
        provider.refresh.assert_awaited_once()
