"""Redacted preparation and one current operator authority."""

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
    assert not detail.preview_verified
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
