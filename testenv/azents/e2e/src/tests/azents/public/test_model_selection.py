"""Workspace model selection readiness E2E test."""

import time

import azentsadminclient
import azentspublicclient
import requests
from azentspublicclient.api.llm_provider_integration_v1_api import (
    LLMProviderIntegrationV1Api,
)
from azentspublicclient.api.workspace_v1_api import (
    WorkspaceV1Api as PublicWorkspaceV1Api,
)
from azentspublicclient.models.api_key_secrets import ApiKeySecrets
from azentspublicclient.models.create_workspace_request import (
    CreateWorkspaceRequest as PublicCreateWorkspaceRequest,
)
from azentspublicclient.models.llm_provider import LLMProvider
from azentspublicclient.models.llm_provider_integration_create_request import (
    LLMProviderIntegrationCreateRequest,
)
from azentspublicclient.models.secrets import Secrets

from support.utils import authenticate_user, unique, wait_until


def _workspace_with_deterministic_integration(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    *,
    variant: str,
) -> tuple[str, str, str]:
    """Deterministic listing integration t t workspace t createt."""
    uniq = unique()
    token, _, _ = authenticate_user(
        public_api_client,
        admin_api_client,
        email=f"model-selection-{uniq}@example.com",
    )
    handle = f"ws-ms-{uniq}"
    PublicWorkspaceV1Api(public_api_client).workspace_v1_create_workspace(
        PublicCreateWorkspaceRequest(
            workspace_name=f"Model Selection WS {uniq}",
            workspace_handle=handle,
            owner_name=f"Owner {uniq}",
        ),
        _headers={"Authorization": f"Bearer {token}"},
    )
    integration = LLMProviderIntegrationV1Api(
        public_api_client
    ).llm_provider_integration_v1_create_integration(
        handle=handle,
        llm_provider_integration_create_request=LLMProviderIntegrationCreateRequest(
            provider=LLMProvider.OPENAI,
            name=f"__testenv_model_listing:{variant}",
            secrets=Secrets(ApiKeySecrets(api_key="sk-test-key")),
        ),
        _headers={"Authorization": f"Bearer {token}"},
    )
    return token, handle, integration.id


def _headers(token: str) -> dict[str, str]:
    """Bearer auth header t t."""
    return {"Authorization": f"Bearer {token}"}


def _sync_catalog(
    server_url: str,
    token: str,
    handle: str,
    integration_id: str,
) -> None:
    """Sync stored catalog for deterministic integration."""
    last_response: requests.Response | None = None
    for _ in range(3):
        response = requests.post(
            f"{server_url}/llm-provider-integration/v1/workspaces/"
            f"{handle}/llm-provider-integrations/{integration_id}/catalog-sync",
            headers=_headers(token),
            timeout=10,
        )
        last_response = response
        if response.status_code < 500:
            break
        time.sleep(0.2)
    if last_response is None or last_response.status_code >= 400:
        message = "" if last_response is None else last_response.text
        raise AssertionError(f"Catalog sync failed: {message}")


class TestModelSelectionReadiness:
    """Model selection API readiness t."""

    def test_deterministic_listing_exposes_candidates_and_skips(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
        azents_public_server_url: str,
    ) -> None:
        """Deterministic listing t t skip summary t returnt."""
        token, handle, integration_id = _workspace_with_deterministic_integration(
            public_api_client,
            admin_api_client,
            variant="deterministic-success",
        )
        _sync_catalog(azents_public_server_url, token, handle, integration_id)

        response = wait_until(
            lambda: requests.get(
                f"{azents_public_server_url}/llm-provider-integration/v1/workspaces/"
                f"{handle}/llm-provider-integrations/{integration_id}/catalog-entries",
                headers=_headers(token),
                timeout=10,
            ),
            timeout=10,
            interval=0.2,
            message="Stored catalog entries did not become readable",
        )

        assert response.status_code == 200
        body = response.json()
        assert [entry["provider_model_identifier"] for entry in body["entries"]] == [
            "gpt-5.5",
            "gpt-5.5-mini",
        ]
        assert body["latest_attempt"]["status"] == "succeeded"
        assert body["latest_attempt"]["skipped_count"] == 1

    def test_user_catalog_failure_is_visible_without_snapshot(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
        azents_public_server_url: str,
    ) -> None:
        """Failed user catalog sync exposes latest attempt without snapshot."""
        token, handle, integration_id = _workspace_with_deterministic_integration(
            public_api_client,
            admin_api_client,
            variant="deterministic-failure",
        )
        _sync_catalog(azents_public_server_url, token, handle, integration_id)

        response = requests.get(
            f"{azents_public_server_url}/llm-provider-integration/v1/workspaces/"
            f"{handle}/llm-provider-integrations/{integration_id}/catalog-entries",
            headers=_headers(token),
            timeout=10,
        )

        assert response.status_code == 200
        body = response.json()
        assert body["current_snapshot_id"] is None
        assert body["entries"] == []
        assert body["latest_attempt"]["status"] == "failed"
        assert body["latest_attempt"]["action_hint"]

    def test_workspace_model_settings_update_from_listing_candidate(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
        azents_public_server_url: str,
    ) -> None:
        """Listing t workspace default model selection t settingst."""
        token, handle, integration_id = _workspace_with_deterministic_integration(
            public_api_client,
            admin_api_client,
            variant="deterministic-success",
        )
        _sync_catalog(azents_public_server_url, token, handle, integration_id)
        listing = wait_until(
            lambda: requests.get(
                f"{azents_public_server_url}/llm-provider-integration/v1/workspaces/"
                f"{handle}/llm-provider-integrations/{integration_id}/catalog-entries",
                headers=_headers(token),
                timeout=10,
            ),
            timeout=10,
            interval=0.2,
            message="Stored catalog entries did not become readable",
        )
        listing.raise_for_status()
        candidate = listing.json()["entries"][0]
        selection = {
            "llm_provider_integration_id": integration_id,
            "model_identifier": candidate["provider_model_identifier"],
        }

        update = requests.put(
            f"{azents_public_server_url}/workspace-model-settings/v1/workspaces/{handle}",
            headers=_headers(token),
            json={
                "default_model_selection": selection,
                "default_lightweight_model_selection": selection,
            },
            timeout=10,
        )
        assert update.status_code == 200

        fetched = requests.get(
            f"{azents_public_server_url}/workspace-model-settings/v1/workspaces/{handle}",
            headers=_headers(token),
            timeout=10,
        )
        assert fetched.status_code == 200
        body = fetched.json()
        assert body["default_model_selection"]["model_identifier"] == "gpt-5.5"
        assert body["default_lightweight_model_selection"]["model_identifier"] == (
            "gpt-5.5"
        )
