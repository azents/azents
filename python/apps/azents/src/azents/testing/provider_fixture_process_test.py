"""Keep synthetic first-account discovery inside the explicit fixture process."""

import datetime
from base64 import urlsafe_b64encode
from collections.abc import Callable

import pytest
from azcommon import di
from fastapi import FastAPI

from azents.app import create_admin_api_app, create_public_api_app
from azents.core.config import Config, Settings
from azents.core.credentials import (
    ChatGPTOAuthSecrets,
    KimiOAuthSecrets,
    XaiOAuthSecrets,
)
from azents.core.enums import LLMProvider
from azents.engine.model_factories import get_model_sdk_factories
from azents.repos.llm_provider_integration.data import LLMProviderIntegrationWithSecrets
from azents.services.llm_catalog import get_integration_model_listing
from azents.services.model_listing.data import ModelListingOutput
from azents.testing.provider_fixture_process import (
    _attach_fixture_constructors,
    fixture_integration_model_listing,
)
from azents.testing.provider_sdk_factories import fixture_model_sdk_factories


@pytest.mark.parametrize(
    ("provider", "model"),
    [
        (LLMProvider.CHATGPT_OAUTH, "gpt-5.5"),
        (LLMProvider.XAI_OAUTH, "grok-4"),
        (LLMProvider.KIMI_OAUTH, "kimi-k2.5"),
    ],
)
async def test_first_oauth_catalog_discovery_uses_synthetic_credentials_not_name(
    provider: LLMProvider,
    model: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Initial device completion cannot hit an account endpoint before renaming."""
    token = "e2e-provider-cutover-account"
    expires = datetime.datetime.now(datetime.UTC) + datetime.timedelta(hours=1)
    if provider is LLMProvider.CHATGPT_OAUTH:
        secrets = ChatGPTOAuthSecrets(
            access_token=token, refresh_token="synthetic-refresh", expires_at=expires
        )
    elif provider is LLMProvider.XAI_OAUTH:
        secrets = XaiOAuthSecrets(
            access_token=token, refresh_token="synthetic-refresh", expires_at=expires
        )
    else:
        secrets = KimiOAuthSecrets(
            access_token=token,
            refresh_token="synthetic-refresh",
            expires_at=expires,
            device_id="synthetic-device",
        )
    integration = LLMProviderIntegrationWithSecrets(
        id="i" * 32,
        workspace_id="w" * 32,
        provider=provider,
        name="New provider account",
        enabled=True,
        catalog_configuration_version=1,
        created_at=datetime.datetime.now(datetime.UTC),
        updated_at=datetime.datetime.now(datetime.UTC),
        secrets=secrets,
        config=None,
    )

    async def forbidden_remote(
        integration: LLMProviderIntegrationWithSecrets,
    ) -> ModelListingOutput:
        raise AssertionError("Synthetic first discovery must remain local")

    monkeypatch.setattr(
        "azents.testing.provider_fixture_process.get_integration_model_listing",
        lambda: forbidden_remote,
    )
    result = await fixture_integration_model_listing()(integration)
    assert model in {candidate.model_identifier for candidate in result.models}


@pytest.mark.parametrize("creator", [create_public_api_app, create_admin_api_app])
def test_fixture_uses_production_owned_container_binding(
    creator: Callable[[Config], FastAPI],
) -> None:
    """Inject before preload while preserving the ordinary app resource owner."""
    settings = Settings(
        _env_file=None,
        rdb_host="fixture.invalid",
        rdb_user="synthetic",
        rdb_db_name="synthetic",
        auth_jwt_secret_key="synthetic-model-fixture-key-32-characters",
        credential_encryption_key=urlsafe_b64encode(b"0" * 32).decode(),
        testenv_api_enabled=True,
    )
    config = Config.from_settings(settings)
    app = creator(config)
    assert _attach_fixture_constructors(app) is app
    container = app.state.di_container
    assert isinstance(container, di.Container)
    assert container.dependency_overrides[get_model_sdk_factories] is (
        fixture_model_sdk_factories
    )
    assert container.dependency_overrides[get_integration_model_listing] is (
        fixture_integration_model_listing
    )
    assert app.dependency_overrides[get_model_sdk_factories] is (
        fixture_model_sdk_factories
    )
    assert app.dependency_overrides[get_integration_model_listing] is (
        fixture_integration_model_listing
    )
