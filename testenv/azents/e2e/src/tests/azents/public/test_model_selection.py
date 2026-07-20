"""Workspace model selection readiness E2E test."""

from typing import cast

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
    provider: LLMProvider = LLMProvider.OPENAI,
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
            provider=provider,
            name=f"__testenv_model_listing:{variant}",
            secrets=Secrets(ApiKeySecrets(api_key="sk-test-key")),
        ),
        _headers={"Authorization": f"Bearer {token}"},
    )
    return token, handle, integration.id


def _headers(token: str) -> dict[str, str]:
    """Bearer auth header t t."""
    return {"Authorization": f"Bearer {token}"}


def _wait_for_initial_catalog_sync(
    server_url: str,
    token: str,
    handle: str,
    integration_id: str,
) -> requests.Response:
    """Wait for the create-triggered deterministic catalog sync to finish."""

    def terminal_attempt() -> requests.Response | None:
        response = requests.get(
            f"{server_url}/llm-provider-integration/v1/workspaces/"
            f"{handle}/llm-provider-integrations/{integration_id}/catalog-entries",
            headers=_headers(token),
            timeout=10,
        )
        if response.status_code != 200:
            return None
        payload = cast("dict[str, object]", response.json())
        if payload.get("catalog_scope") != "integration":
            return None
        latest_attempt_payload = payload.get("latest_attempt")
        if not isinstance(latest_attempt_payload, dict):
            return None
        latest_attempt = cast("dict[str, object]", latest_attempt_payload)
        if latest_attempt.get("status") not in {"succeeded", "failed"}:
            return None
        return response

    response = wait_until(
        terminal_attempt,
        timeout=10,
        interval=0.2,
        message="Create-triggered catalog sync did not finish",
    )
    if response is None:
        raise AssertionError("Catalog sync wait returned no response.")
    return response


class TestModelSelectionReadiness:
    """Model selection API readiness t."""

    def test_explicit_sync_is_throttled_after_initial_sync(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
        azents_public_server_url: str,
    ) -> None:
        """A recent initial sync throttles repeated explicit provider work."""
        token, handle, integration_id = _workspace_with_deterministic_integration(
            public_api_client,
            admin_api_client,
            variant="deterministic-success",
        )
        _wait_for_initial_catalog_sync(
            azents_public_server_url,
            token,
            handle,
            integration_id,
        )

        response = requests.post(
            f"{azents_public_server_url}/llm-provider-integration/v1/workspaces/"
            f"{handle}/llm-provider-integrations/{integration_id}/catalog-sync",
            headers=_headers(token),
            timeout=10,
        )

        assert response.status_code == 429
        assert response.headers.get("Retry-After")

    def test_only_catalog_affecting_update_triggers_initial_sync(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
        azents_public_server_url: str,
    ) -> None:
        """Name-only updates do not sync, while credential updates do."""
        token, handle, integration_id = _workspace_with_deterministic_integration(
            public_api_client,
            admin_api_client,
            variant="deterministic-success",
        )
        initial = _wait_for_initial_catalog_sync(
            azents_public_server_url,
            token,
            handle,
            integration_id,
        ).json()
        initial_attempt_id = initial["latest_attempt"]["id"]
        integration_url = (
            f"{azents_public_server_url}/llm-provider-integration/v1/workspaces/"
            f"{handle}/llm-provider-integrations/{integration_id}"
        )
        catalog_url = f"{integration_url}/catalog-entries"

        renamed = requests.patch(
            integration_url,
            headers=_headers(token),
            json={"name": "__testenv_model_listing:deterministic-success"},
            timeout=10,
        )
        renamed.raise_for_status()
        after_rename = requests.get(
            catalog_url,
            headers=_headers(token),
            timeout=10,
        )
        after_rename.raise_for_status()
        assert after_rename.json()["latest_attempt"]["id"] == initial_attempt_id

        updated = requests.patch(
            integration_url,
            headers=_headers(token),
            json={
                "secrets": {
                    "type": "api_key",
                    "api_key": "sk-updated-test-key",
                }
            },
            timeout=10,
        )
        updated.raise_for_status()

        def refreshed_attempt() -> requests.Response | None:
            response = requests.get(
                catalog_url,
                headers=_headers(token),
                timeout=10,
            )
            if response.status_code != 200:
                return None
            attempt = response.json().get("latest_attempt")
            if attempt is None or attempt.get("id") == initial_attempt_id:
                return None
            if attempt.get("status") != "succeeded":
                return None
            return response

        wait_until(
            refreshed_attempt,
            timeout=10,
            interval=0.2,
            message="Credential update did not trigger catalog sync",
        )

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
        _wait_for_initial_catalog_sync(
            azents_public_server_url, token, handle, integration_id
        )

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

    def test_openrouter_catalog_and_unknown_publisher_selection(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
        azents_public_server_url: str,
    ) -> None:
        """OpenRouter exposes exact account model ids without publisher allowlists."""
        token, handle, integration_id = _workspace_with_deterministic_integration(
            public_api_client,
            admin_api_client,
            variant="deterministic-openrouter",
            provider=LLMProvider.OPENROUTER,
        )
        _wait_for_initial_catalog_sync(
            azents_public_server_url, token, handle, integration_id
        )
        catalog_url = (
            f"{azents_public_server_url}/llm-provider-integration/v1/workspaces/"
            f"{handle}/llm-provider-integrations/{integration_id}/catalog-entries"
        )

        listing = requests.get(catalog_url, headers=_headers(token), timeout=10)
        listing.raise_for_status()
        body = listing.json()
        entries = {
            entry["provider_model_identifier"]: entry for entry in body["entries"]
        }

        assert body["catalog_scope"] == "integration"
        assert body["latest_attempt"]["status"] == "succeeded"
        assert body["latest_attempt"]["skipped_count"] == 1
        assert set(entries) == {
            "anthropic/claude-sonnet-4.6",
            "new-publisher/frontier-text",
        }
        assert entries["anthropic/claude-sonnet-4.6"]["publisher"] == "anthropic"
        unknown = entries["new-publisher/frontier-text"]
        assert unknown["provider"] == "openrouter"
        assert unknown["publisher"] == "other"
        assert unknown["runtime_model_identifier"] == (
            "openrouter/new-publisher/frontier-text"
        )
        assert unknown["normalized_capabilities"]["modalities"] == {
            "input": ["text", "image"],
            "output": ["text"],
        }
        assert unknown["normalized_capabilities"]["built_in_tools"]["supported"] == [
            "web_search"
        ]

        searched = requests.get(
            catalog_url,
            headers=_headers(token),
            params={"search": "new-publisher", "limit": 1, "offset": 0},
            timeout=10,
        )
        searched.raise_for_status()
        assert searched.json()["total"] == 1
        assert searched.json()["entries"][0]["provider_model_identifier"] == (
            "new-publisher/frontier-text"
        )

        selection = {
            "llm_provider_integration_id": integration_id,
            "model_identifier": "new-publisher/frontier-text",
        }
        workspace_update = requests.put(
            f"{azents_public_server_url}/workspace-model-settings/v1/workspaces/{handle}",
            headers=_headers(token),
            json={
                "default_model_selection": selection,
                "default_lightweight_model_selection": selection,
            },
            timeout=10,
        )
        assert workspace_update.status_code == 200
        workspace_selection = workspace_update.json()["default_model_selection"]
        assert workspace_selection["provider"] == "openrouter"
        assert workspace_selection["model_identifier"] == "new-publisher/frontier-text"
        assert workspace_selection["model_developer"] == "other"

        created = requests.post(
            f"{azents_public_server_url}/agent/v1/workspaces/{handle}/agents",
            headers=_headers(token),
            json={"name": "OpenRouter Unknown Publisher Agent", "type": "public"},
            timeout=10,
        )
        assert created.status_code == 201
        agent_selection = created.json()["model_selection"]
        assert agent_selection["provider"] == "openrouter"
        assert agent_selection["model_identifier"] == "new-publisher/frontier-text"
        assert agent_selection["model_developer"] == "other"

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
        _wait_for_initial_catalog_sync(
            azents_public_server_url, token, handle, integration_id
        )

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
        _wait_for_initial_catalog_sync(
            azents_public_server_url, token, handle, integration_id
        )
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

    def test_selectable_model_options_copy_to_agent_and_fallback(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
        azents_public_server_url: str,
    ) -> None:
        """Workspace selectable model options copy to Agent and fallback by order."""
        token, handle, integration_id = _workspace_with_deterministic_integration(
            public_api_client,
            admin_api_client,
            variant="deterministic-model-settings",
        )
        _wait_for_initial_catalog_sync(
            azents_public_server_url, token, handle, integration_id
        )
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
        entries = listing.json()["entries"]
        main_selection = {
            "llm_provider_integration_id": integration_id,
            "model_identifier": entries[0]["provider_model_identifier"],
        }
        lightweight_selection = {
            "llm_provider_integration_id": integration_id,
            "model_identifier": entries[1]["provider_model_identifier"],
        }

        workspace_settings_payload: dict[str, object] = {
            "default_selectable_model_options": [
                {
                    "label": "default",
                    "model_selection": main_selection,
                    "settings": {
                        "context_window_tokens": 100_000,
                        "max_output_tokens": 12_000,
                        "builtin_tools": [{"name": "web_search"}],
                        "subagent_enabled": False,
                        "subagent_guidance": "Reserve for complex synthesis.",
                    },
                },
                {
                    "label": "lightweight",
                    "model_selection": lightweight_selection,
                    "settings": {
                        "context_window_tokens": 32_000,
                        "max_output_tokens": 4_000,
                        "builtin_tools": [],
                        "subagent_enabled": True,
                        "subagent_guidance": "Prefer for bounded investigation.",
                    },
                },
            ],
            "default_main_model_label": "default",
            "default_lightweight_model_label": "lightweight",
        }
        update = requests.put(
            f"{azents_public_server_url}/workspace-model-settings/v1/workspaces/{handle}",
            headers=_headers(token),
            json=workspace_settings_payload,
            timeout=10,
        )
        assert update.status_code == 200
        settings = update.json()
        assert [
            option["label"] for option in settings["default_selectable_model_options"]
        ] == ["default", "lightweight"]
        assert settings["default_selectable_model_options"][0]["settings"] == {
            "context_window_tokens": 100_000,
            "max_output_tokens": 12_000,
            "builtin_tools": [{"name": "web_search", "config": {}}],
            "subagent_enabled": False,
            "subagent_guidance": "Reserve for complex synthesis.",
        }
        assert settings["default_selectable_model_options"][1]["settings"] == {
            "context_window_tokens": 32_000,
            "max_output_tokens": 4_000,
            "builtin_tools": [],
            "subagent_enabled": True,
            "subagent_guidance": "Prefer for bounded investigation.",
        }
        assert settings["default_model_selection"]["model_identifier"] == "gpt-5.5"
        assert (
            settings["default_lightweight_model_selection"]["model_identifier"]
            == "gpt-5.5-mini"
        )

        created = requests.post(
            f"{azents_public_server_url}/agent/v1/workspaces/{handle}/agents",
            headers=_headers(token),
            json={"name": "Selectable Options Agent", "type": "public"},
            timeout=10,
        )
        assert created.status_code == 201
        agent = created.json()
        assert [option["label"] for option in agent["selectable_model_options"]] == [
            "default",
            "lightweight",
        ]
        assert [option["settings"] for option in agent["selectable_model_options"]] == [
            {
                "context_window_tokens": 100_000,
                "max_output_tokens": 12_000,
                "builtin_tools": [{"name": "web_search", "config": {}}],
                "subagent_enabled": False,
                "subagent_guidance": "Reserve for complex synthesis.",
            },
            {
                "context_window_tokens": 32_000,
                "max_output_tokens": 4_000,
                "builtin_tools": [],
                "subagent_enabled": True,
                "subagent_guidance": "Prefer for bounded investigation.",
            },
        ]
        assert agent["main_model_label"] == "default"
        assert agent["lightweight_model_label"] == "lightweight"
        assert agent["model_selection"]["model_identifier"] == "gpt-5.5"
        assert (
            agent["lightweight_model_selection"]["model_identifier"] == "gpt-5.5-mini"
        )

        fallback_update = requests.patch(
            f"{azents_public_server_url}/agent/v1/workspaces/{handle}/agents/{agent['id']}",
            headers=_headers(token),
            json={
                "selectable_model_options": [
                    {"label": "fast", "model_selection": lightweight_selection},
                    {"label": "default", "model_selection": main_selection},
                ],
                "main_model_label": "removed-label",
                "lightweight_model_label": "removed-label",
            },
            timeout=10,
        )
        assert fallback_update.status_code == 200
        updated_agent = fallback_update.json()
        assert updated_agent["main_model_label"] == "fast"
        assert updated_agent["lightweight_model_label"] == "fast"
        assert updated_agent["model_selection"]["model_identifier"] == "gpt-5.5-mini"
        assert (
            updated_agent["lightweight_model_selection"]["model_identifier"]
            == "gpt-5.5-mini"
        )
