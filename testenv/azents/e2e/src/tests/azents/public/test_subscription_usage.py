"""Credential-free subscription usage product-path E2E coverage."""

import datetime
import json
from dataclasses import dataclass

import azentsadminclient
import azentspublicclient
import pytest
import requests
from azentspublicclient.api.invitation_v1_api import InvitationV1Api
from azentspublicclient.api.llm_provider_integration_v1_api import (
    LLMProviderIntegrationV1Api,
)
from azentspublicclient.api.workspace_v1_api import WorkspaceV1Api
from azentspublicclient.models.chat_gpto_auth_config import ChatGPTOAuthConfig
from azentspublicclient.models.chat_gpto_auth_secrets import ChatGPTOAuthSecrets
from azentspublicclient.models.create_invitation_request import CreateInvitationRequest
from azentspublicclient.models.create_workspace_request import CreateWorkspaceRequest
from azentspublicclient.models.llm_provider import LLMProvider
from azentspublicclient.models.llm_provider_integration_create_request import (
    LLMProviderIntegrationCreateRequest,
)
from azentspublicclient.models.llm_provider_integration_create_request_config import (
    LLMProviderIntegrationCreateRequestConfig,
)
from azentspublicclient.models.secrets import Secrets
from azentspublicclient.models.subscription_usage_unavailable_reason import (
    SubscriptionUsageUnavailableReason,
)
from azentspublicclient.models.subscription_usage_unavailable_response import (
    SubscriptionUsageUnavailableResponse,
)
from azentspublicclient.models.xai_o_auth_config import XaiOAuthConfig
from azentspublicclient.models.xai_o_auth_secrets import XaiOAuthSecrets
from pydantic import TypeAdapter
from testcontainers.core.container import DockerContainer

from support.utils import authenticate_user, unique

_SUBSCRIPTION_USAGE_JOURNAL_PATH = "/v1/_subscription_usage_requests"
_JSON_OBJECT = TypeAdapter(dict[str, object])
_JSON_OBJECT_LIST = TypeAdapter(list[dict[str, object]])


@dataclass(frozen=True)
class SubscriptionWorkspace:
    """Workspace credentials used by subscription usage scenarios."""

    handle: str
    owner_email: str
    owner_token: str
    member_token: str


def _headers(token: str) -> dict[str, str]:
    """Build bearer headers."""
    return {"Authorization": f"Bearer {token}"}


def _json_object(value: dict[str, object]) -> dict[str, object]:
    """Convert generated-client dictionaries into JSON-compatible values."""
    return _JSON_OBJECT.validate_python(_JSON_OBJECT.dump_python(value, mode="json"))


def test_json_object_normalizes_generated_datetime_values() -> None:
    """Serialize generated-client datetime fields without using broken to_json."""
    response = SubscriptionUsageUnavailableResponse(
        type="unavailable",
        integration_id="integration-id",
        provider="chatgpt_oauth",
        fetched_at=datetime.datetime(2026, 7, 19, tzinfo=datetime.UTC),
        reason=SubscriptionUsageUnavailableReason.DISABLED,
        message="Enable this integration to refresh subscription usage.",
        retryable=False,
    )

    assert _json_object(response.to_dict()) == {
        "type": "unavailable",
        "integration_id": "integration-id",
        "provider": "chatgpt_oauth",
        "fetched_at": "2026-07-19T00:00:00Z",
        "reason": "disabled",
        "message": "Enable this integration to refresh subscription usage.",
        "retryable": False,
    }


def setup_subscription_workspace(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
) -> SubscriptionWorkspace:
    """Create one workspace and regular member through public APIs."""
    suffix = unique()
    owner_token, _, owner_email = authenticate_user(
        public_api_client,
        admin_api_client,
        email=f"subscription-owner-{suffix}@example.com",
    )
    member_email = f"subscription-member-{suffix}@example.com"
    member_token, _, _ = authenticate_user(
        public_api_client,
        admin_api_client,
        email=member_email,
    )
    handle = f"subscription-usage-{suffix}"
    WorkspaceV1Api(public_api_client).workspace_v1_create_workspace(
        CreateWorkspaceRequest(
            workspace_name=f"Subscription Usage {suffix}",
            workspace_handle=handle,
            owner_name=f"Owner {suffix}",
        ),
        _headers=_headers(owner_token),
    )
    invitation_api = InvitationV1Api(public_api_client)
    invitation = invitation_api.invitation_v1_create_invitation(
        handle,
        CreateInvitationRequest(email=member_email),
        _headers=_headers(owner_token),
    )
    invitation_api.invitation_v1_accept_invitation(
        invitation.id,
        _headers=_headers(member_token),
    )
    return SubscriptionWorkspace(
        handle=handle,
        owner_email=owner_email,
        owner_token=owner_token,
        member_token=member_token,
    )


def create_chatgpt_subscription_integration(
    api: LLMProviderIntegrationV1Api,
    workspace: SubscriptionWorkspace,
    *,
    scenario: str,
    enabled: bool = True,
    access_token: str = "test-chatgpt-access-token",
    refresh_token: str = "test-chatgpt-refresh-token",
) -> str:
    """Create one deterministic ChatGPT OAuth integration."""
    now = datetime.datetime.now(datetime.UTC)
    integration = api.llm_provider_integration_v1_create_integration(
        handle=workspace.handle,
        llm_provider_integration_create_request=LLMProviderIntegrationCreateRequest(
            provider=LLMProvider.CHATGPT_OAUTH,
            name=f"ChatGPT {scenario}",
            enabled=enabled,
            secrets=Secrets(
                ChatGPTOAuthSecrets(
                    access_token=access_token,
                    refresh_token=refresh_token,
                    expires_at=now + datetime.timedelta(hours=2),
                )
            ),
            config=LLMProviderIntegrationCreateRequestConfig(
                ChatGPTOAuthConfig(
                    account_id=scenario,
                    email=f"{scenario}@example.com",
                    plan_type="Pro",
                    connection_method="device",
                    status="connected",
                    connected_at=now,
                    last_refreshed_at=now,
                )
            ),
        ),
        _headers=_headers(workspace.owner_token),
    )
    return integration.id


def create_xai_subscription_integration(
    api: LLMProviderIntegrationV1Api,
    workspace: SubscriptionWorkspace,
    *,
    scenario: str,
    enabled: bool = True,
) -> str:
    """Create one deterministic xAI OAuth integration."""
    now = datetime.datetime.now(datetime.UTC)
    integration = api.llm_provider_integration_v1_create_integration(
        handle=workspace.handle,
        llm_provider_integration_create_request=LLMProviderIntegrationCreateRequest(
            provider=LLMProvider.XAI_OAUTH,
            name=f"xAI {scenario}",
            enabled=enabled,
            secrets=Secrets(
                XaiOAuthSecrets(
                    access_token="test-xai-subscription-access-token",
                    refresh_token="test-xai-subscription-refresh-token",
                    expires_at=now + datetime.timedelta(hours=2),
                )
            ),
            config=LLMProviderIntegrationCreateRequestConfig(
                XaiOAuthConfig(
                    account_id=scenario,
                    email=f"{scenario}@example.com",
                    connection_method="device",
                    status="connected",
                    connected_at=now,
                    last_refreshed_at=now,
                )
            ),
        ),
        _headers=_headers(workspace.owner_token),
    )
    return integration.id


def _usage(
    api: LLMProviderIntegrationV1Api,
    workspace: SubscriptionWorkspace,
    integration_id: str,
    *,
    token: str,
) -> dict[str, object]:
    """Read and JSON-normalize one generated-client usage response."""
    response = api.llm_provider_integration_v1_get_subscription_usage(
        integration_id=integration_id,
        handle=workspace.handle,
        _headers=_headers(token),
    )
    actual = response.actual_instance
    assert actual is not None
    return _json_object(actual.to_dict())


def subscription_usage_journal(proxy_url: str) -> list[dict[str, object]]:
    """Read the sanitized subscription usage proxy journal."""
    response = requests.get(
        f"{proxy_url}{_SUBSCRIPTION_USAGE_JOURNAL_PATH}",
        timeout=10,
    )
    response.raise_for_status()
    return _JSON_OBJECT_LIST.validate_python(response.json())


def clear_subscription_usage_journal(proxy_url: str) -> None:
    """Clear usage journal entries and sequence counters."""
    requests.delete(
        f"{proxy_url}{_SUBSCRIPTION_USAGE_JOURNAL_PATH}",
        timeout=10,
    ).raise_for_status()


def _assert_no_sensitive_source_values(value: object) -> None:
    """Reject deterministic credentials and account metadata from output."""
    serialized = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    for forbidden in (
        "test-chatgpt-access-token",
        "test-chatgpt-refresh-token",
        "test-chatgpt-refresh-initial",
        "test-chatgpt-refresh-success",
        "test-chatgpt-refreshed",
        "test-xai-subscription-access-token",
        "test-xai-subscription-refresh-token",
        "@example.com",
        "test-chatgpt-normal",
        "test-xai-normal",
    ):
        assert forbidden not in serialized


def _subscription_usage_log_records(logs: str) -> list[dict[str, object]]:
    """Return structured log records emitted by subscription usage services."""
    records: list[dict[str, object]] = []
    for line in logs.splitlines():
        try:
            record = _JSON_OBJECT.validate_python(json.loads(line))
        except ValueError:
            continue
        name = record.get("name")
        if isinstance(name, str) and name.startswith(
            "azents.services.subscription_usage"
        ):
            records.append(record)
    assert records
    return records


def test_subscription_usage_log_records_ignore_unrelated_service_logs() -> None:
    """Scope source-value checks to the subscription usage logging boundary."""
    usage_record = {
        "name": "azents.services.subscription_usage.service",
        "operation": "subscription_usage_read",
        "outcome": "available",
    }
    logs = "\n".join(
        [
            json.dumps(
                {
                    "name": "azents.core.email.service",
                    "to_email": "unrelated@example.com",
                }
            ),
            json.dumps(usage_record),
            "non-json process output",
        ]
    )

    assert _subscription_usage_log_records(logs) == [usage_record]


def _assert_safe_subscription_usage_journal(journal: list[dict[str, object]]) -> None:
    """Verify the proxy journal contains classifications, not source values."""
    _assert_no_sensitive_source_values(journal)
    serialized = json.dumps(journal, ensure_ascii=False, sort_keys=True)
    for forbidden in (
        "120 credits",
        "500 credits",
        "180 credits",
        "SuperGrok",
        "https://grok.com/usage",
        "https://example.com/rejected",
        "2540",
        "1275",
        "10000",
    ):
        assert forbidden not in serialized
    allowed_keys = {"scenario", "path", "sequence", "status", "required_headers"}
    assert all(set(entry) == allowed_keys for entry in journal)


def _limits(payload: dict[str, object]) -> list[dict[str, object]]:
    """Return validated normalized usage limits."""
    return _JSON_OBJECT_LIST.validate_python(payload.get("limits"))


class TestChatGPTSubscriptionUsage:
    """Validate ChatGPT usage, permissions, retry, and typed failures."""

    def test_owner_member_and_exhausted_snapshots(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
        openai_proxy_url: str,
    ) -> None:
        """Expose operational windows to members and financials only to owners."""
        clear_subscription_usage_journal(openai_proxy_url)
        workspace = setup_subscription_workspace(public_api_client, admin_api_client)
        api = LLMProviderIntegrationV1Api(public_api_client)
        normal_id = create_chatgpt_subscription_integration(
            api,
            workspace,
            scenario="test-chatgpt-normal",
        )
        exhausted_id = create_chatgpt_subscription_integration(
            api,
            workspace,
            scenario="test-chatgpt-exhausted",
        )

        owner = _usage(api, workspace, normal_id, token=workspace.owner_token)
        member = _usage(api, workspace, normal_id, token=workspace.member_token)
        exhausted = _usage(api, workspace, exhausted_id, token=workspace.owner_token)

        assert owner["type"] == "available"
        assert owner["provider"] == "chatgpt_oauth"
        assert owner["plan_label"] == "Pro"
        assert len(_limits(owner)) == 2
        assert owner["financial_details"] == {
            "type": "chatgpt",
            "has_credits": True,
            "unlimited": False,
            "balance": "120 credits",
            "spend_limit": "500 credits",
            "spend_used": "180 credits",
            "spend_remaining_percent": 64.0,
            "spend_resets_at": "2026-08-01T00:00:00Z",
            "reached_type": None,
        }
        assert member["type"] == "available"
        assert member["plan_label"] == owner["plan_label"]
        assert member["limits"] == owner["limits"]
        assert member["financial_details"] is None
        exhausted_limits = _limits(exhausted)
        assert exhausted_limits[0]["used_percent"] == 100.0
        assert "remaining" not in json.dumps(exhausted, sort_keys=True).lower()
        _assert_no_sensitive_source_values(owner)
        _assert_no_sensitive_source_values(member)
        _assert_safe_subscription_usage_journal(
            subscription_usage_journal(openai_proxy_url)
        )

    def test_unauthorized_refreshes_once_and_retries_once(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
        openai_proxy_url: str,
    ) -> None:
        """Refresh one ChatGPT token after 401 and retry usage exactly once."""
        clear_subscription_usage_journal(openai_proxy_url)
        workspace = setup_subscription_workspace(public_api_client, admin_api_client)
        api = LLMProviderIntegrationV1Api(public_api_client)
        integration_id = create_chatgpt_subscription_integration(
            api,
            workspace,
            scenario="test-chatgpt-refresh",
            access_token="test-chatgpt-refresh-initial",
            refresh_token="test-chatgpt-refresh-success",
        )

        payload = _usage(
            api,
            workspace,
            integration_id,
            token=workspace.owner_token,
        )

        assert payload["type"] == "available"
        assert _limits(payload)[0]["used_percent"] == 35.0
        journal = subscription_usage_journal(openai_proxy_url)
        assert [(entry["path"], entry["status"]) for entry in journal] == [
            ("/backend-api/wham/usage", 401),
            ("/chatgpt/oauth/token", 200),
            ("/backend-api/wham/usage", 200),
        ]
        assert [entry["sequence"] for entry in journal] == [1, 1, 2]
        _assert_no_sensitive_source_values(payload)
        _assert_safe_subscription_usage_journal(journal)

    @pytest.mark.parametrize(
        ("scenario", "reason", "retryable"),
        [
            ("test-chatgpt-transport", "temporarily_unavailable", True),
            ("test-chatgpt-rate-limited", "rate_limited", True),
            ("test-chatgpt-unavailable", "temporarily_unavailable", True),
            ("test-chatgpt-malformed", "invalid_provider_response", False),
        ],
    )
    def test_typed_unavailable_outcomes(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
        openai_proxy_url: str,
        scenario: str,
        reason: str,
        retryable: bool,
    ) -> None:
        """Normalize provider and transport failures without exposing payloads."""
        clear_subscription_usage_journal(openai_proxy_url)
        workspace = setup_subscription_workspace(public_api_client, admin_api_client)
        api = LLMProviderIntegrationV1Api(public_api_client)
        integration_id = create_chatgpt_subscription_integration(
            api, workspace, scenario=scenario
        )

        payload = _usage(
            api,
            workspace,
            integration_id,
            token=workspace.owner_token,
        )

        assert payload["type"] == "unavailable"
        assert payload["reason"] == reason
        assert payload["retryable"] is retryable
        assert "error" not in json.dumps(payload, sort_keys=True).lower()
        _assert_no_sensitive_source_values(payload)
        _assert_safe_subscription_usage_journal(
            subscription_usage_journal(openai_proxy_url)
        )


class TestXaiSubscriptionUsage:
    """Validate xAI billing, redirects, enrichment, and typed failures."""

    def test_owner_member_financial_visibility_and_optional_enrichment(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
        openai_proxy_url: str,
    ) -> None:
        """Expose normalized period to members and billing details only to owners."""
        clear_subscription_usage_journal(openai_proxy_url)
        workspace = setup_subscription_workspace(public_api_client, admin_api_client)
        api = LLMProviderIntegrationV1Api(public_api_client)
        integration_id = create_xai_subscription_integration(
            api, workspace, scenario="test-xai-normal"
        )

        owner = _usage(api, workspace, integration_id, token=workspace.owner_token)
        member = _usage(api, workspace, integration_id, token=workspace.member_token)

        assert owner["type"] == "available"
        assert owner["provider"] == "xai_oauth"
        assert owner["plan_label"] == "SuperGrok"
        assert len(_limits(owner)) == 1
        assert _limits(owner)[0]["used_percent"] == 42.0
        assert owner["financial_details"] == {
            "type": "xai",
            "prepaid_balance_cents": 2540,
            "payg_cap_cents": 10000,
            "payg_used_cents": 1275,
            "auto_top_up_enabled": True,
            "auto_top_up_amount_cents": 2000,
            "auto_top_up_monthly_maximum_cents": 10000,
        }
        assert member["limits"] == owner["limits"]
        assert member["financial_details"] is None
        journal = subscription_usage_journal(openai_proxy_url)
        assert [entry["path"] for entry in journal] == [
            "/v1/settings",
            "/v1/billing",
            "/v1/auto-topup-rule",
            "/v1/settings",
            "/v1/billing",
            "/v1/auto-topup-rule",
        ]
        _assert_no_sensitive_source_values(owner)
        _assert_no_sensitive_source_values(member)
        _assert_safe_subscription_usage_journal(journal)

    @pytest.mark.parametrize(
        ("scenario", "expected_type", "expected_reason", "expected_paths"),
        [
            ("test-xai-external", "external", None, ["/v1/settings"]),
            (
                "test-xai-invalid-redirect",
                "unavailable",
                "invalid_provider_response",
                ["/v1/settings"],
            ),
            (
                "test-xai-settings-failure",
                "available",
                None,
                ["/v1/settings", "/v1/billing", "/v1/auto-topup-rule"],
            ),
            (
                "test-xai-billing-denied",
                "unavailable",
                "entitlement_unavailable",
                ["/v1/settings", "/v1/billing"],
            ),
            (
                "test-xai-transport",
                "unavailable",
                "temporarily_unavailable",
                ["/v1/settings", "/v1/billing"],
            ),
            (
                "test-xai-unavailable",
                "unavailable",
                "temporarily_unavailable",
                ["/v1/settings", "/v1/billing"],
            ),
            (
                "test-xai-malformed",
                "unavailable",
                "invalid_provider_response",
                ["/v1/settings", "/v1/billing"],
            ),
        ],
    )
    def test_redirect_enrichment_and_failure_outcomes(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
        openai_proxy_url: str,
        scenario: str,
        expected_type: str,
        expected_reason: str | None,
        expected_paths: list[str],
    ) -> None:
        """Validate xAI short-circuit, best-effort, and required-read behavior."""
        clear_subscription_usage_journal(openai_proxy_url)
        workspace = setup_subscription_workspace(public_api_client, admin_api_client)
        api = LLMProviderIntegrationV1Api(public_api_client)
        integration_id = create_xai_subscription_integration(
            api, workspace, scenario=scenario
        )

        payload = _usage(
            api,
            workspace,
            integration_id,
            token=workspace.owner_token,
        )

        assert payload["type"] == expected_type
        if expected_reason is not None:
            assert payload["reason"] == expected_reason
            assert "url" not in payload
        if scenario == "test-xai-external":
            assert payload["url"] == "https://grok.com/usage"
            assert "financial_details" not in payload
        if scenario == "test-xai-settings-failure":
            assert payload["plan_label"] == "SuperGrok"
        if scenario == "test-xai-billing-denied":
            integration = api.llm_provider_integration_v1_get_integration(
                integration_id=integration_id,
                handle=workspace.handle,
                _headers=_headers(workspace.owner_token),
            )
            assert integration.enabled is True
        journal = subscription_usage_journal(openai_proxy_url)
        assert [entry["path"] for entry in journal] == expected_paths
        _assert_no_sensitive_source_values(payload)
        _assert_safe_subscription_usage_journal(journal)


class TestSubscriptionUsageIsolation:
    """Validate disabled and integration-local subscription usage behavior."""

    def test_disabled_issues_no_provider_request_and_cards_are_independent(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
        openai_proxy_url: str,
        azents_public_server_container: DockerContainer,
    ) -> None:
        """Keep disabled and failing reads local to their integration state."""
        clear_subscription_usage_journal(openai_proxy_url)
        workspace = setup_subscription_workspace(public_api_client, admin_api_client)
        api = LLMProviderIntegrationV1Api(public_api_client)
        disabled_id = create_chatgpt_subscription_integration(
            api,
            workspace,
            scenario="test-chatgpt-normal",
            enabled=False,
        )
        broken_id = create_chatgpt_subscription_integration(
            api,
            workspace,
            scenario="test-chatgpt-malformed",
        )
        healthy_id = create_xai_subscription_integration(
            api, workspace, scenario="test-xai-normal"
        )

        disabled = _usage(
            api,
            workspace,
            disabled_id,
            token=workspace.owner_token,
        )
        assert disabled["type"] == "unavailable"
        assert disabled["reason"] == "disabled"
        assert subscription_usage_journal(openai_proxy_url) == []

        broken = _usage(api, workspace, broken_id, token=workspace.owner_token)
        healthy = _usage(api, workspace, healthy_id, token=workspace.owner_token)
        assert broken["type"] == "unavailable"
        assert broken["reason"] == "invalid_provider_response"
        assert healthy["type"] == "available"
        journal = subscription_usage_journal(openai_proxy_url)
        assert [entry["scenario"] for entry in journal] == [
            "chatgpt_malformed",
            "xai_normal",
            "xai_normal",
            "xai_normal",
        ]
        _assert_safe_subscription_usage_journal(journal)

        stdout, stderr = azents_public_server_container.get_logs()
        logs = stdout.decode(errors="replace") + stderr.decode(errors="replace")
        _assert_no_sensitive_source_values(_subscription_usage_log_records(logs))
