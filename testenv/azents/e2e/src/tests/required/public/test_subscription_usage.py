"""Credential-free subscription usage product-path E2E coverage."""

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
from azentspublicclient.models.create_invitation_request import CreateInvitationRequest
from azentspublicclient.models.create_workspace_request import CreateWorkspaceRequest
from azentspublicclient.models.subscription_usage_available_response import (
    SubscriptionUsageAvailableResponse,
)
from azentspublicclient.models.subscription_usage_external_response import (
    SubscriptionUsageExternalResponse,
)
from azentspublicclient.models.subscription_usage_limit_response import (
    SubscriptionUsageLimitResponse,
)
from azentspublicclient.models.subscription_usage_unavailable_response import (
    SubscriptionUsageUnavailableResponse,
)
from pydantic import (
    BaseModel,
    ConfigDict,
    StrictBool,
    StrictInt,
    StrictStr,
    TypeAdapter,
)
from testcontainers.core.container import DockerContainer

from support.oauth_connections import connect_chatgpt_oauth, connect_xai_oauth
from support.subscription_usage_evidence import (
    subscription_usage_log_records as _subscription_usage_log_records,
)
from support.utils import authenticate_user, unique

_SUBSCRIPTION_USAGE_JOURNAL_PATH = "/v1/_subscription_usage_requests"


class _UsageJournalEntry(BaseModel):
    """Sanitized fixture journal has exactly these authoritative fields."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    scenario: StrictStr
    path: StrictStr
    sequence: StrictInt
    status: StrictInt
    required_headers: dict[str, StrictBool]


_USAGE_JOURNAL = TypeAdapter(list[_UsageJournalEntry])
type _UsageResponse = (
    SubscriptionUsageAvailableResponse
    | SubscriptionUsageUnavailableResponse
    | SubscriptionUsageExternalResponse
)


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
    public_api_client: azentspublicclient.ApiClient,
    workspace: SubscriptionWorkspace,
    *,
    proxy_url: str,
    scenario: str,
    enabled: bool = True,
    access_token: str = "test-chatgpt-access-token",
    refresh_token: str = "test-chatgpt-refresh-token",
) -> str:
    """Create one deterministic ChatGPT OAuth integration."""
    return connect_chatgpt_oauth(
        public_api_client=public_api_client,
        proxy_url=proxy_url,
        handle=workspace.handle,
        token=workspace.owner_token,
        scenario=scenario,
        access_token=access_token,
        refresh_token=refresh_token,
        name=f"ChatGPT {scenario}",
        enabled=enabled,
    )


def create_xai_subscription_integration(
    public_api_client: azentspublicclient.ApiClient,
    workspace: SubscriptionWorkspace,
    *,
    proxy_url: str,
    scenario: str,
    enabled: bool = True,
) -> str:
    """Create one deterministic xAI OAuth integration."""
    return connect_xai_oauth(
        public_api_client=public_api_client,
        proxy_url=proxy_url,
        handle=workspace.handle,
        token=workspace.owner_token,
        scenario=scenario,
        access_token="test-xai-subscription-access-token",
        refresh_token="test-xai-subscription-refresh-token",
        name=f"xAI {scenario}",
        enabled=enabled,
    )


def _usage(
    api: LLMProviderIntegrationV1Api,
    workspace: SubscriptionWorkspace,
    integration_id: str,
    *,
    token: str,
) -> _UsageResponse:
    """Retain the operation-specific generated usage response at ingress."""
    response = api.llm_provider_integration_v1_get_subscription_usage(
        integration_id=integration_id,
        handle=workspace.handle,
        _headers=_headers(token),
    )
    actual = response.actual_instance
    assert actual is not None
    return actual


def subscription_usage_journal(proxy_url: str) -> list[_UsageJournalEntry]:
    """Read the sanitized subscription usage proxy journal."""
    response = requests.get(
        f"{proxy_url}{_SUBSCRIPTION_USAGE_JOURNAL_PATH}",
        timeout=10,
    )
    response.raise_for_status()
    return _USAGE_JOURNAL.validate_python(response.json())


def clear_subscription_usage_journal(proxy_url: str) -> None:
    """Clear usage journal entries and sequence counters."""
    requests.delete(
        f"{proxy_url}{_SUBSCRIPTION_USAGE_JOURNAL_PATH}",
        timeout=10,
    ).raise_for_status()


def _assert_no_sensitive_source_values(value: object) -> None:
    """Reject deterministic credentials and account metadata from output."""
    if isinstance(
        value,
        (
            SubscriptionUsageAvailableResponse,
            SubscriptionUsageUnavailableResponse,
            SubscriptionUsageExternalResponse,
        ),
    ):
        value = value.to_dict()
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


def _assert_safe_subscription_usage_journal(journal: list[_UsageJournalEntry]) -> None:
    """Verify the proxy journal contains classifications, not source values."""
    wire = [entry.model_dump(mode="json") for entry in journal]
    _assert_no_sensitive_source_values(wire)
    serialized = json.dumps(wire, ensure_ascii=False, sort_keys=True)
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
    assert all(set(entry.model_dump()) == allowed_keys for entry in journal)


def _limits(payload: _UsageResponse) -> list[SubscriptionUsageLimitResponse]:
    """Return declared limits only from an available usage response."""
    assert isinstance(payload, SubscriptionUsageAvailableResponse)
    return payload.limits


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
            public_api_client,
            workspace,
            proxy_url=openai_proxy_url,
            scenario="test-chatgpt-normal",
        )
        exhausted_id = create_chatgpt_subscription_integration(
            public_api_client,
            workspace,
            proxy_url=openai_proxy_url,
            scenario="test-chatgpt-exhausted",
        )

        owner = _usage(api, workspace, normal_id, token=workspace.owner_token)
        member = _usage(api, workspace, normal_id, token=workspace.member_token)
        exhausted = _usage(api, workspace, exhausted_id, token=workspace.owner_token)

        assert isinstance(owner, SubscriptionUsageAvailableResponse)
        assert isinstance(member, SubscriptionUsageAvailableResponse)
        assert owner.type == "available"
        assert owner.provider == "chatgpt_oauth"
        assert owner.plan_label == "Pro"
        assert len(_limits(owner)) == 2
        assert owner.financial_details is not None
        assert owner.financial_details.to_dict() == {
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
        assert member.type == "available"
        assert member.plan_label == owner.plan_label
        assert member.limits == owner.limits
        assert member.financial_details is None
        exhausted_limits = _limits(exhausted)
        assert exhausted_limits[0].used_percent == 100.0
        assert all("remaining" not in limit.to_dict() for limit in exhausted_limits)
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
            public_api_client,
            workspace,
            proxy_url=openai_proxy_url,
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

        assert isinstance(payload, SubscriptionUsageAvailableResponse)
        assert payload.type == "available"
        assert _limits(payload)[0].used_percent == 35.0
        journal = subscription_usage_journal(openai_proxy_url)
        assert [(entry.path, entry.status) for entry in journal] == [
            ("/backend-api/wham/usage", 401),
            ("/chatgpt/oauth/token", 200),
            ("/backend-api/wham/usage", 200),
        ]
        assert [entry.sequence for entry in journal] == [1, 1, 2]
        _assert_no_sensitive_source_values(payload)
        _assert_safe_subscription_usage_journal(journal)

    def test_transport_failure_reaches_public_unavailable_result(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
        openai_proxy_url: str,
    ) -> None:
        """Project a real provider transport failure without exposing payloads."""
        clear_subscription_usage_journal(openai_proxy_url)
        workspace = setup_subscription_workspace(public_api_client, admin_api_client)
        api = LLMProviderIntegrationV1Api(public_api_client)
        integration_id = create_chatgpt_subscription_integration(
            public_api_client,
            workspace,
            proxy_url=openai_proxy_url,
            scenario="test-chatgpt-transport",
        )

        payload = _usage(
            api,
            workspace,
            integration_id,
            token=workspace.owner_token,
        )

        assert isinstance(payload, SubscriptionUsageUnavailableResponse)
        assert payload.type == "unavailable"
        assert payload.reason == "temporarily_unavailable"
        assert payload.retryable is True
        assert "error" not in json.dumps(payload.to_dict(), sort_keys=True).lower()
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
            public_api_client,
            workspace,
            proxy_url=openai_proxy_url,
            scenario="test-xai-normal",
        )

        owner = _usage(api, workspace, integration_id, token=workspace.owner_token)
        member = _usage(api, workspace, integration_id, token=workspace.member_token)

        assert isinstance(owner, SubscriptionUsageAvailableResponse)
        assert isinstance(member, SubscriptionUsageAvailableResponse)
        assert owner.type == "available"
        assert owner.provider == "xai_oauth"
        assert owner.plan_label == "SuperGrok"
        assert len(_limits(owner)) == 1
        assert _limits(owner)[0].used_percent == 42.0
        assert owner.financial_details is not None
        assert owner.financial_details.to_dict() == {
            "type": "xai",
            "prepaid_balance_cents": 2540,
            "payg_cap_cents": 10000,
            "payg_used_cents": 1275,
            "auto_top_up_enabled": True,
            "auto_top_up_amount_cents": 2000,
            "auto_top_up_monthly_maximum_cents": 10000,
        }
        assert member.limits == owner.limits
        assert member.financial_details is None
        journal = subscription_usage_journal(openai_proxy_url)
        assert [entry.path for entry in journal] == [
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
                "test-xai-billing-denied",
                "unavailable",
                "entitlement_unavailable",
                ["/v1/settings", "/v1/billing"],
            ),
        ],
    )
    def test_external_redirect_and_billing_denial_preserve_integration(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
        openai_proxy_url: str,
        scenario: str,
        expected_type: str,
        expected_reason: str | None,
        expected_paths: list[str],
    ) -> None:
        """Verify external short-circuit and persisted authority after denial."""
        clear_subscription_usage_journal(openai_proxy_url)
        workspace = setup_subscription_workspace(public_api_client, admin_api_client)
        api = LLMProviderIntegrationV1Api(public_api_client)
        integration_id = create_xai_subscription_integration(
            public_api_client, workspace, proxy_url=openai_proxy_url, scenario=scenario
        )

        payload = _usage(
            api,
            workspace,
            integration_id,
            token=workspace.owner_token,
        )

        assert payload.type == expected_type
        if expected_reason is not None:
            assert isinstance(payload, SubscriptionUsageUnavailableResponse)
            assert payload.reason == expected_reason
            assert "url" not in payload.to_dict()
        if scenario == "test-xai-external":
            assert isinstance(payload, SubscriptionUsageExternalResponse)
            assert payload.url == "https://grok.com/usage"
            assert "financial_details" not in payload.to_dict()
        if scenario == "test-xai-billing-denied":
            integration = api.llm_provider_integration_v1_get_integration(
                integration_id=integration_id,
                handle=workspace.handle,
                _headers=_headers(workspace.owner_token),
            )
            assert integration.enabled is True
        journal = subscription_usage_journal(openai_proxy_url)
        assert [entry.path for entry in journal] == expected_paths
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
            public_api_client,
            workspace,
            proxy_url=openai_proxy_url,
            scenario="test-chatgpt-normal",
            enabled=False,
        )
        broken_id = create_chatgpt_subscription_integration(
            public_api_client,
            workspace,
            proxy_url=openai_proxy_url,
            scenario="test-chatgpt-malformed",
        )
        healthy_id = create_xai_subscription_integration(
            public_api_client,
            workspace,
            proxy_url=openai_proxy_url,
            scenario="test-xai-normal",
        )

        disabled = _usage(
            api,
            workspace,
            disabled_id,
            token=workspace.owner_token,
        )
        assert isinstance(disabled, SubscriptionUsageUnavailableResponse)
        assert disabled.type == "unavailable"
        assert disabled.reason == "disabled"
        assert subscription_usage_journal(openai_proxy_url) == []

        broken = _usage(api, workspace, broken_id, token=workspace.owner_token)
        healthy = _usage(api, workspace, healthy_id, token=workspace.owner_token)
        assert isinstance(broken, SubscriptionUsageUnavailableResponse)
        assert broken.type == "unavailable"
        assert broken.reason == "invalid_provider_response"
        assert healthy.type == "available"
        journal = subscription_usage_journal(openai_proxy_url)
        assert [entry.scenario for entry in journal] == [
            "chatgpt_malformed",
            "xai_normal",
            "xai_normal",
            "xai_normal",
        ]
        _assert_safe_subscription_usage_journal(journal)

        stdout, stderr = azents_public_server_container.get_logs()
        logs = stdout.decode(errors="replace") + stderr.decode(errors="replace")
        _assert_no_sensitive_source_values(_subscription_usage_log_records(logs))
