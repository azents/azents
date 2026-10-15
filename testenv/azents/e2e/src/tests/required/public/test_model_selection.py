"""Workspace model selection readiness E2E test."""

from typing import NamedTuple

import azentsadminclient
import azentspublicclient
import requests
from azentspublicclient.api.llm_provider_integration_v1_api import (
    LLMProviderIntegrationV1Api,
)
from azentspublicclient.api.workspace_v1_api import (
    WorkspaceV1Api as PublicWorkspaceV1Api,
)
from azentspublicclient.models.agent_response import AgentResponse
from azentspublicclient.models.agent_session_response import AgentSessionResponse
from azentspublicclient.models.api_key_secrets import ApiKeySecrets
from azentspublicclient.models.create_workspace_request import (
    CreateWorkspaceRequest as PublicCreateWorkspaceRequest,
)
from azentspublicclient.models.image_generation_model_catalog_response import (
    ImageGenerationModelCatalogResponse,
)
from azentspublicclient.models.llm_provider import LLMProvider
from azentspublicclient.models.llm_provider_integration_create_request import (
    LLMProviderIntegrationCreateRequest,
)
from azentspublicclient.models.model_capabilities import ModelCapabilities
from azentspublicclient.models.model_catalog_entry_list_response import (
    ModelCatalogEntryListResponse,
)
from azentspublicclient.models.model_catalog_entry_response import (
    ModelCatalogEntryResponse,
)
from azentspublicclient.models.model_catalog_sync_status_response import (
    ModelCatalogSyncStatusResponse,
)
from azentspublicclient.models.model_context_window import ModelContextWindow
from azentspublicclient.models.model_modalities import ModelModalities
from azentspublicclient.models.secrets import Secrets
from azentspublicclient.models.workspace_model_settings_response import (
    WorkspaceModelSettingsResponse,
)
from pydantic import ConfigDict

from support.observations import (
    TurnMarkerObservation,
    decode_history_page,
    decode_session,
)
from support.runtime_profiles import (
    create_workspace_runtime_profile,
    start_and_wait_for_agent_runtime,
)
from support.utils import authenticate_user, unique, wait_until


class _DeterministicWorkspace(NamedTuple):
    """Workspace and integration created for deterministic model-listing tests."""

    token: str
    handle: str
    integration_id: str


class _CatalogSyncObservation(ModelCatalogSyncStatusResponse):
    """Retain wire extensions for sync-status absence and equality evidence."""

    model_config = ConfigDict(extra="allow")


class _ModalitiesObservation(ModelModalities):
    """Preserve every wire key for the existing whole-object equality check."""

    model_config = ConfigDict(extra="allow")


class _ContextWindowObservation(ModelContextWindow):
    """Preserve omitted, null, and extra keys in whole-object equality evidence."""

    model_config = ConfigDict(extra="allow")


class _CapabilitiesObservation(ModelCapabilities):
    """Keep typed capability fields and equality-checked wire extensions."""

    modalities: _ModalitiesObservation | None = None
    context_window: _ContextWindowObservation | None = None


class _CatalogEntryObservation(ModelCatalogEntryResponse):
    """Retain generated entry fields and typed nested capability observations."""

    normalized_capabilities: _CapabilitiesObservation


class _CatalogObservation(ModelCatalogEntryListResponse):
    """Generated catalog fields while retaining sync-status wire extensions."""

    latest_sync: _CatalogSyncObservation | None
    entries: list[_CatalogEntryObservation]


def _workspace_with_deterministic_integration(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    *,
    variant: str,
    provider: LLMProvider = LLMProvider.OPENAI,
) -> _DeterministicWorkspace:
    """Create a workspace with one deterministic model-listing integration."""
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
    return _DeterministicWorkspace(
        token=token,
        handle=handle,
        integration_id=integration.id,
    )


def _headers(token: str) -> dict[str, str]:
    """Return the bearer authorization header."""
    return {"Authorization": f"Bearer {token}"}


def _wait_for_initial_catalog_sync(
    server_url: str,
    token: str,
    handle: str,
    integration_id: str,
) -> _CatalogObservation:
    """Wait for the create-triggered deterministic catalog sync to finish."""

    def terminal_sync() -> _CatalogObservation | None:
        response = requests.get(
            f"{server_url}/llm-provider-integration/v1/workspaces/"
            f"{handle}/llm-provider-integrations/{integration_id}/catalog-entries",
            headers=_headers(token),
            timeout=10,
        )
        if response.status_code != 200:
            return None
        payload = _CatalogObservation.model_validate(response.json())
        if payload.catalog_scope != "integration":
            return None
        if payload.latest_sync is None or payload.latest_sync.status not in {
            "succeeded",
            "failed",
        }:
            return None
        return payload

    response = wait_until(
        terminal_sync,
        timeout=10,
        interval=0.2,
        message="Create-triggered catalog sync did not finish",
    )
    if response is None:
        raise AssertionError("Catalog sync wait returned no response.")
    return response


def _wait_for_image_catalog_sync(
    server_url: str,
    token: str,
    handle: str,
    integration_id: str,
) -> ImageGenerationModelCatalogResponse:
    """Wait for the create-triggered image catalog projection."""

    def populated_catalog() -> ImageGenerationModelCatalogResponse | None:
        response = requests.get(
            f"{server_url}/llm-provider-integration/v1/workspaces/"
            f"{handle}/llm-provider-integrations/{integration_id}/"
            "image-generation-model-catalog",
            headers=_headers(token),
            timeout=10,
        )
        if response.status_code != 200:
            return None
        payload = ImageGenerationModelCatalogResponse.model_validate(response.json())
        if not payload.usable:
            return None
        identifiers = [entry.provider_model_identifier for entry in payload.entries]
        if identifiers != ["gpt-image-2.5-flare", "gpt-image-2.5-sunburst"]:
            return None
        return payload

    payload = wait_until(
        populated_catalog,
        timeout=15,
        interval=0.2,
        message="Create-triggered image catalog sync did not finish",
    )
    if payload is None:
        raise AssertionError("Image catalog sync wait returned no response.")
    return payload


def _wait_for_turn_context(
    *,
    server_url: str,
    token: str,
    agent_id: str,
    session_id: str,
    target: str,
    expected_effective: int,
) -> None:
    """Wait for one completed turn with the expected prepared context window."""

    def matching_turn() -> TurnMarkerObservation | None:
        session = requests.get(
            f"{server_url}/chat/v1/agents/{agent_id}/sessions/{session_id}",
            headers=_headers(token),
            timeout=10,
        )
        session.raise_for_status()
        if decode_session(session.json()).run_state != "idle":
            return None
        history = requests.get(
            f"{server_url}/chat/v1/sessions/{session_id}/history?limit=100",
            headers=_headers(token),
            timeout=10,
        )
        history.raise_for_status()
        for event in reversed(decode_history_page(history.json()).items):
            if event.kind != "turn_marker":
                continue
            payload = TurnMarkerObservation.model_validate(event.payload)
            profile = payload.applied_inference_profile
            if profile is not None and profile.model_target_label == target:
                return payload
        return None

    payload = wait_until(
        matching_turn,
        timeout=120,
        interval=0.5,
        message=f"Prepared turn context was not observed for {target}",
    )
    assert payload is not None
    assert payload.effective_context_window_tokens == expected_effective
    assert payload.effective_auto_compaction_threshold_tokens == int(
        expected_effective * 0.9
    )


class TestModelSelectionReadiness:
    """Model selection API readiness tests."""

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
        )
        initial_sync = initial.latest_sync
        assert initial_sync is not None
        initial_catalog = initial
        assert initial_catalog.latest_sync is not None
        initial_started_at = initial_catalog.latest_sync.started_at
        assert initial_started_at is not None
        assert "id" not in initial_sync.model_dump()
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
        assert (
            _CatalogObservation.model_validate(after_rename.json()).latest_sync
            == initial_sync
        )

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

        def refreshed_sync() -> requests.Response | None:
            response = requests.get(
                catalog_url,
                headers=_headers(token),
                timeout=10,
            )
            if response.status_code != 200:
                return None
            sync = _CatalogObservation.model_validate(response.json()).latest_sync
            if sync is None or sync.started_at == initial_started_at:
                return None
            if sync.status != "succeeded":
                return None
            return response

        wait_until(
            refreshed_sync,
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
        """Deterministic listing returns candidates and a typed skip summary."""
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
        body = _CatalogObservation.model_validate(response.json())
        assert [entry.provider_model_identifier for entry in body.entries] == [
            "gpt-5.5",
            "gpt-5.5-mini",
        ]
        assert body.latest_sync is not None
        assert body.latest_sync.status == "succeeded"
        assert body.latest_sync.skipped_count == 1

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
        body = _CatalogObservation.model_validate(listing.json())
        entries = {entry.provider_model_identifier: entry for entry in body.entries}

        assert body.catalog_scope == "integration"
        assert body.latest_sync is not None
        assert body.latest_sync.status == "succeeded"
        assert body.latest_sync.skipped_count == 1
        assert set(entries) == {
            "anthropic/claude-sonnet-4.6",
            "new-publisher/frontier-text",
        }
        assert entries["anthropic/claude-sonnet-4.6"].publisher == "anthropic"
        unknown = entries["new-publisher/frontier-text"]
        assert unknown.provider == "openrouter"
        assert unknown.publisher == "other"
        assert unknown.provider_model_identifier == "new-publisher/frontier-text"
        assert unknown.normalized_capabilities.modalities is not None
        assert unknown.normalized_capabilities.built_in_tools is not None
        assert unknown.normalized_capabilities.modalities.model_dump(
            mode="json", exclude_unset=True
        ) == {
            "input": ["text", "image"],
            "output": ["text"],
        }
        assert unknown.normalized_capabilities.built_in_tools.supported == [
            "web_search"
        ]

        searched = requests.get(
            catalog_url,
            headers=_headers(token),
            params={"search": "new-publisher", "limit": 1, "offset": 0},
            timeout=10,
        )
        searched.raise_for_status()
        assert _CatalogObservation.model_validate(searched.json()).total == 1
        assert _CatalogObservation.model_validate(searched.json()).entries[
            0
        ].provider_model_identifier == ("new-publisher/frontier-text")

        selection = {
            "llm_provider_integration_id": integration_id,
            "model_identifier": "new-publisher/frontier-text",
        }
        workspace_update = requests.put(
            f"{azents_public_server_url}/workspace-model-settings/v1/workspaces/{handle}",
            headers=_headers(token),
            json={
                "default_selectable_model_options": [
                    {
                        "label": "default",
                        "candidates": [{"model_selection": selection}],
                        "subagent_enabled": True,
                        "subagent_guidance": None,
                    }
                ],
                "default_main_model_label": "default",
                "default_lightweight_model_label": "default",
            },
            timeout=10,
        )
        assert workspace_update.status_code == 200
        workspace_settings = WorkspaceModelSettingsResponse.model_validate(
            workspace_update.json()
        )
        assert workspace_settings.default_selectable_model_options is not None
        workspace_selection = (
            workspace_settings.default_selectable_model_options[0]
            .candidates[0]
            .model_selection
        )
        assert workspace_selection.provider == "openrouter"
        assert workspace_selection.model_identifier == "new-publisher/frontier-text"
        assert workspace_selection.model_developer == "other"

        created = requests.post(
            f"{azents_public_server_url}/agent/v1/workspaces/{handle}/agents",
            headers=_headers(token),
            json={"name": "OpenRouter Unknown Publisher Agent", "type": "public"},
            timeout=10,
        )
        assert created.status_code == 201
        agent_selection = (
            AgentResponse.model_validate(created.json())
            .selectable_model_options[0]
            .candidates[0]
            .model_selection
        )
        assert agent_selection.provider == "openrouter"
        assert agent_selection.model_identifier == "new-publisher/frontier-text"
        assert agent_selection.model_developer == "other"

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
        body = _CatalogObservation.model_validate(response.json())
        assert body.last_success_at is None
        assert body.entries == []
        assert body.latest_sync is not None
        assert body.latest_sync.status == "failed"
        assert body.latest_sync.action_hint

    def test_workspace_model_settings_update_from_listing_candidate(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
        azents_public_server_url: str,
    ) -> None:
        """Listing updates Workspace default model selection and settings."""
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
        candidate = _CatalogObservation.model_validate(listing.json()).entries[0]
        selection = {
            "llm_provider_integration_id": integration_id,
            "model_identifier": candidate.provider_model_identifier,
        }

        update = requests.put(
            f"{azents_public_server_url}/workspace-model-settings/v1/workspaces/{handle}",
            headers=_headers(token),
            json={
                "default_selectable_model_options": [
                    {
                        "label": "default",
                        "candidates": [{"model_selection": selection}],
                        "subagent_enabled": True,
                        "subagent_guidance": None,
                    }
                ],
                "default_main_model_label": "default",
                "default_lightweight_model_label": "default",
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
        body = WorkspaceModelSettingsResponse.model_validate(fetched.json())
        assert body.default_selectable_model_options is not None
        candidate = body.default_selectable_model_options[0].candidates[0]
        assert candidate.model_selection.model_identifier == "gpt-5.5"

    def test_catalog_context_reaches_prepared_turn(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
        azents_public_server_url: str,
    ) -> None:
        """One assembled turn retains the catalog default and prepared threshold."""
        token, handle, integration_id = _workspace_with_deterministic_integration(
            public_api_client,
            admin_api_client,
            variant="deterministic-context-ranges",
        )
        _wait_for_initial_catalog_sync(
            azents_public_server_url, token, handle, integration_id
        )
        listing = requests.get(
            f"{azents_public_server_url}/llm-provider-integration/v1/workspaces/"
            f"{handle}/llm-provider-integrations/{integration_id}/catalog-entries",
            headers=_headers(token),
            timeout=10,
        )
        listing.raise_for_status()
        entries = {
            entry.provider_model_identifier: entry
            for entry in _CatalogObservation.model_validate(listing.json()).entries
        }
        main = entries["gpt-5.5"]
        lightweight = entries["gpt-5.5-mini"]
        assert main.normalized_capabilities.context_window is not None
        assert lightweight.normalized_capabilities.context_window is not None
        assert main.normalized_capabilities.context_window.model_dump(
            mode="json", exclude_unset=True
        ) == {
            "default_input_tokens": 96_000,
            "max_input_tokens": 256_000,
            "max_output_tokens": 16_000,
        }
        assert lightweight.normalized_capabilities.context_window.model_dump(
            mode="json", exclude_unset=True
        ) == {
            "default_input_tokens": None,
            "max_input_tokens": 512_000,
            "max_output_tokens": 16_000,
        }

        def selection(identifier: str) -> dict[str, str]:
            return {
                "llm_provider_integration_id": integration_id,
                "model_identifier": identifier,
            }

        runtime_profile_id = create_workspace_runtime_profile(
            public_api_client,
            token=token,
            workspace_handle=handle,
            provider_id="system-docker",
        )
        created = requests.post(
            f"{azents_public_server_url}/agent/v1/workspaces/{handle}/agents",
            headers=_headers(token),
            json={
                "name": "Context Range Agent",
                "type": "public",
                "selectable_model_options": [
                    {
                        "label": label,
                        "candidates": [
                            {
                                "model_selection": selection(identifier),
                                "settings": {
                                    "context_window_tokens": None,
                                    "builtin_tools": [],
                                },
                            }
                        ],
                        "subagent_enabled": True,
                        "subagent_guidance": None,
                    }
                    for label, identifier in (
                        ("default", "gpt-5.5"),
                        ("legacy", "gpt-5.5-mini"),
                    )
                ],
                "main_model_label": "default",
                "lightweight_model_label": "legacy",
                "runtime_profile_id": runtime_profile_id,
            },
            timeout=10,
        )

        assert created.status_code == 201, created.text
        body = AgentResponse.model_validate(created.json())
        assert body.effective_context_window_tokens == 96_000
        agent_id = body.id
        start_and_wait_for_agent_runtime(
            public_api_client,
            token=token,
            workspace_handle=handle,
            agent_id=agent_id,
        )
        session = requests.get(
            f"{azents_public_server_url}/chat/v1/agents/{agent_id}/team-primary-session",
            headers=_headers(token),
            timeout=10,
        )
        session.raise_for_status()
        session_id = AgentSessionResponse.model_validate(session.json()).id

        submitted = requests.post(
            f"{azents_public_server_url}/chat/v1/sessions/{session_id}/inputs",
            headers=_headers(token),
            json={
                "agent_id": agent_id,
                "client_request_id": f"context-range-default-{unique()}",
                "message": "Verify prepared context for default.",
                "inference_profile": {
                    "model_target_label": "default",
                    "reasoning_effort": None,
                    "enabled_execution_options": [],
                },
            },
            timeout=10,
        )
        submitted.raise_for_status()
        _wait_for_turn_context(
            server_url=azents_public_server_url,
            token=token,
            agent_id=agent_id,
            session_id=session_id,
            target="default",
            expected_effective=96_000,
        )

    def test_selectable_model_candidate_chains_copy_and_remain_independent(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
        azents_public_server_url: str,
    ) -> None:
        """Workspace candidate chains deep-copy to Agents and remain independent."""
        token, handle, integration_id = _workspace_with_deterministic_integration(
            public_api_client,
            admin_api_client,
            variant="deterministic-model-settings",
        )
        _wait_for_initial_catalog_sync(
            azents_public_server_url, token, handle, integration_id
        )
        image_catalog = _wait_for_image_catalog_sync(
            azents_public_server_url,
            token,
            handle,
            integration_id,
        )
        assert image_catalog.default_available is True
        assert image_catalog.explicit_selection_supported is True
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
        entries = {
            entry.provider_model_identifier: entry
            for entry in _CatalogObservation.model_validate(listing.json()).entries
        }
        main_selection = {
            "llm_provider_integration_id": integration_id,
            "model_identifier": entries["gpt-5.5"].provider_model_identifier,
        }
        lightweight_selection = {
            "llm_provider_integration_id": integration_id,
            "model_identifier": entries["gpt-5.5-mini"].provider_model_identifier,
        }

        default_option = {
            "label": "default",
            "candidates": [
                {
                    "model_selection": main_selection,
                    "settings": {
                        "context_window_tokens": 100_000,
                        "max_output_tokens": 12_000,
                        "builtin_tools": [
                            {"name": "web_search"},
                            {
                                "name": "image_generation",
                                "config": {
                                    "model": "gpt-image-2.5-sunburst",
                                    "quality": "high",
                                },
                            },
                        ],
                    },
                },
                {
                    "model_selection": lightweight_selection,
                    "settings": {
                        "context_window_tokens": 32_000,
                        "max_output_tokens": 4_000,
                        "builtin_tools": [],
                    },
                },
            ],
            "subagent_enabled": False,
            "subagent_guidance": "Reserve for complex synthesis.",
        }
        lightweight_option = {
            "label": "lightweight",
            "candidates": [
                {
                    "model_selection": lightweight_selection,
                    "settings": {
                        "context_window_tokens": 32_000,
                        "max_output_tokens": 4_000,
                        "builtin_tools": [],
                    },
                }
            ],
            "subagent_enabled": True,
            "subagent_guidance": "Prefer for bounded investigation.",
        }
        workspace_settings_payload: dict[str, object] = {
            "default_selectable_model_options": [
                default_option,
                lightweight_option,
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
        settings = WorkspaceModelSettingsResponse.model_validate(update.json())
        assert settings.default_selectable_model_options is not None
        assert [
            option.label for option in settings.default_selectable_model_options
        ] == ["default", "lightweight"]
        stored_default = settings.default_selectable_model_options[0]
        assert len(stored_default.candidates) == 2
        assert stored_default.candidates[0].settings.context_window_tokens == 100_000
        assert (
            stored_default.candidates[1].model_selection.model_identifier
            == "gpt-5.5-mini"
        )
        assert stored_default.subagent_enabled is False
        assert stored_default.subagent_guidance == ("Reserve for complex synthesis.")

        created = requests.post(
            f"{azents_public_server_url}/agent/v1/workspaces/{handle}/agents",
            headers=_headers(token),
            json={"name": "Selectable Options Agent", "type": "public"},
            timeout=10,
        )
        assert created.status_code == 201
        agent = AgentResponse.model_validate(created.json())
        assert [option.label for option in agent.selectable_model_options] == [
            "default",
            "lightweight",
        ]
        agent_default = agent.selectable_model_options[0]
        assert len(agent_default.candidates) == 2
        assert agent_default.candidates[0].model_selection.model_identifier == "gpt-5.5"
        assert (
            agent_default.candidates[1].model_selection.model_identifier
            == "gpt-5.5-mini"
        )
        assert agent.main_model_label == "default"
        assert agent.lightweight_model_label == "lightweight"

        changed_defaults = requests.put(
            f"{azents_public_server_url}/workspace-model-settings/v1/workspaces/{handle}",
            headers=_headers(token),
            json={
                "default_selectable_model_options": [lightweight_option],
                "default_main_model_label": "lightweight",
                "default_lightweight_model_label": "lightweight",
            },
            timeout=10,
        )
        changed_defaults.raise_for_status()
        unchanged_agent = requests.get(
            f"{azents_public_server_url}/agent/v1/workspaces/{handle}/agents/{agent.id}",
            headers=_headers(token),
            timeout=10,
        )
        unchanged_agent.raise_for_status()
        assert (
            len(
                AgentResponse.model_validate(unchanged_agent.json())
                .selectable_model_options[0]
                .candidates
            )
            == 2
        )

        normalization_update = requests.patch(
            f"{azents_public_server_url}/agent/v1/workspaces/{handle}/agents/{agent.id}",
            headers=_headers(token),
            json={
                "selectable_model_options": [
                    {
                        "label": "fast",
                        "candidates": [{"model_selection": lightweight_selection}],
                        "subagent_enabled": True,
                        "subagent_guidance": None,
                    },
                    {
                        "label": "default",
                        "candidates": [{"model_selection": main_selection}],
                        "subagent_enabled": True,
                        "subagent_guidance": None,
                    },
                ],
                "main_model_label": "removed-label",
                "lightweight_model_label": "removed-label",
            },
            timeout=10,
        )
        assert normalization_update.status_code == 200
        updated_agent = AgentResponse.model_validate(normalization_update.json())
        assert updated_agent.main_model_label == "fast"
        assert updated_agent.lightweight_model_label == "fast"
        assert (
            updated_agent.selectable_model_options[0]
            .candidates[0]
            .model_selection.model_identifier
            == "gpt-5.5-mini"
        )
