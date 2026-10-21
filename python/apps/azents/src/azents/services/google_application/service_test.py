"""Redacted preparation and one current operator authority."""

import dataclasses
from unittest.mock import create_autospec

import pytest

from azents.core.config import Config
from azents.core.google_system_setting import (
    GoogleApplicationConfig,
    GoogleApplicationSecrets,
    GoogleApplicationUnavailable,
)
from azents.core.system_setting import (
    ResolvedSystemSetting,
    SystemSettingFieldSource,
    SystemSettingSection,
)
from azents.services.google_application.service import GoogleApplicationService
from azents.services.system_setting.service import SystemSettingsService


def _current(client: str | None, secret: str | None) -> ResolvedSystemSetting:
    return ResolvedSystemSetting(
        section=SystemSettingSection.GOOGLE_OAUTH,
        schema_version=1,
        admin_version=4,
        config=GoogleApplicationConfig(client_id=client),
        secrets=GoogleApplicationSecrets(client_secret=secret),
        field_sources={
            "client_id": SystemSettingFieldSource.ADMIN,
            "client_secret": SystemSettingFieldSource.ENVIRONMENT,
            "picker_api_key": SystemSettingFieldSource.UNSET,
            "picker_app_id": SystemSettingFieldSource.UNSET,
        },
        effective_generation="INTERNAL-GENERATION",
    )


@pytest.mark.asyncio
async def test_detail_never_projects_secret_or_generation_or_claims_live_access() -> (
    None
):
    settings = create_autospec(SystemSettingsService, instance=True)
    settings.resolve.return_value = _current("client", "SECRET-ONLY")
    config = create_autospec(Config, instance=True)
    config.web_url = "https://app.example.invalid/"
    detail = await GoogleApplicationService(settings, config).detail()
    encoded = detail.model_dump_json()
    assert detail.status == "configured_unverified"
    assert detail.client_secret_configured
    assert detail.client_secret_source is SystemSettingFieldSource.ENVIRONMENT
    assert detail.callback_url == "https://app.example.invalid/oauth/google/callback"
    assert detail.picker_status == "not_configured"
    assert not detail.service_access_verified
    assert "SECRET-ONLY" not in encoded
    assert "INTERNAL-GENERATION" not in encoded


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "client,secret,status",
    [
        (None, None, "not_configured"),
        ("client", None, "incomplete"),
        (None, "secret", "incomplete"),
    ],
)
async def test_absent_registration_is_preparation_not_user_denial(
    client: str | None,
    secret: str | None,
    status: str,
) -> None:
    settings = create_autospec(SystemSettingsService, instance=True)
    settings.resolve.return_value = _current(client, secret)
    config = create_autospec(Config, instance=True)
    config.web_url = "https://app.example.invalid"
    application = GoogleApplicationService(settings, config)
    assert (await application.preparation()).status == status
    with pytest.raises(GoogleApplicationUnavailable):
        await application.resolve()


@pytest.mark.asyncio
async def test_missing_web_url_is_actionable_without_hiding_configuration() -> None:
    settings = create_autospec(SystemSettingsService, instance=True)
    settings.resolve.return_value = _current("client", "secret")
    config = create_autospec(Config, instance=True)
    config.web_url = None
    application = GoogleApplicationService(settings, config)
    preparation = await application.preparation()
    assert preparation.status == "incomplete"
    assert preparation.callback_url is None
    assert (await application.detail()).client_secret_configured
    with pytest.raises(GoogleApplicationUnavailable):
        await application.resolve()


@pytest.mark.asyncio
async def test_explicit_null_patch_is_distinct_from_omission() -> None:
    settings = create_autospec(SystemSettingsService, instance=True)
    settings.resolve.return_value = _current(None, "secret")
    config = create_autospec(Config, instance=True)
    config.web_url = "https://app.example.invalid"
    await GoogleApplicationService(settings, config).patch(
        expected_version=4,
        config_patch={"client_id": None},
        secret_action=None,
        actor_user_id="admin",
    )
    mutation = settings.mutate.call_args.args[0]
    assert mutation.config_patch == {"client_id": None}
    assert mutation.secret_actions == {}
    assert mutation.actor_user_id == "admin"


@pytest.mark.parametrize(
    "key,app_id,picker_status",
    [
        (None, None, "not_configured"),
        ("BROWSER-KEY", None, "incomplete"),
        (None, "123456789", "incomplete"),
        ("BROWSER-KEY", "123456789", "configured_unverified"),
    ],
)
async def test_optional_picker_preparation_preserves_normal_oauth_readiness(
    key: str | None,
    app_id: str | None,
    picker_status: str,
) -> None:
    current = _current("client", "SERVER-SECRET")
    current = dataclasses.replace(
        current,
        config=GoogleApplicationConfig(
            client_id="client", picker_api_key=key, picker_app_id=app_id
        ),
        field_sources={
            **current.field_sources,
            "picker_api_key": SystemSettingFieldSource.UNSET
            if key is None
            else SystemSettingFieldSource.ADMIN,
            "picker_app_id": SystemSettingFieldSource.UNSET
            if app_id is None
            else SystemSettingFieldSource.ADMIN,
        },
    )
    settings = create_autospec(SystemSettingsService, instance=True)
    settings.resolve.return_value = current
    config = create_autospec(Config, instance=True)
    config.web_url = "https://app.example.invalid"
    application = GoogleApplicationService(settings, config)
    assert (await application.resolve()).client_id == "client"
    assert await application.creation_available()
    preparation = await application.preparation()
    assert preparation.status == "configured_unverified"
    assert preparation.picker_status == picker_status
    assert "BROWSER-KEY" not in preparation.model_dump_json()
    if key is None or app_id is None:
        with pytest.raises(GoogleApplicationUnavailable, match="Picker"):
            await application.picker()
    else:
        picker = await application.picker()
        assert picker.api_key == key and picker.app_id == app_id
        assert picker.registration.effective_generation == current.effective_generation
        assert "BROWSER-KEY" not in repr(picker)
        assert "SERVER-SECRET" not in repr(picker)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "client,secret,web_url,available",
    [
        (None, None, "https://app.example.invalid", False),
        ("client", None, "https://app.example.invalid", False),
        (None, "secret", "https://app.example.invalid", False),
        ("client", "secret", None, False),
        ("client", "secret", "https://app.example.invalid?bad=callback", False),
        ("client", "secret", "https://app.example.invalid", True),
    ],
)
async def test_creation_requires_complete_effective_local_preparation(
    client: str | None,
    secret: str | None,
    web_url: str | None,
    available: bool,
) -> None:
    settings = create_autospec(SystemSettingsService, instance=True)
    settings.resolve.return_value = _current(client, secret)
    config = create_autospec(Config, instance=True)
    config.web_url = web_url
    assert await GoogleApplicationService(settings, config).creation_available() is (
        available
    )


@pytest.mark.asyncio
async def test_invalid_registration_hides_creation() -> None:
    application = create_autospec(GoogleApplicationService, instance=True)
    application.preparation.side_effect = GoogleApplicationUnavailable("Invalid.")
    assert not await GoogleApplicationService.creation_available(application)


@pytest.mark.asyncio
async def test_unexpected_preparation_failure_stays_visible() -> None:
    application = create_autospec(GoogleApplicationService, instance=True)
    application.preparation.side_effect = RuntimeError("Unexpected storage failure.")
    with pytest.raises(RuntimeError, match="Unexpected storage failure"):
        await GoogleApplicationService.creation_available(application)
