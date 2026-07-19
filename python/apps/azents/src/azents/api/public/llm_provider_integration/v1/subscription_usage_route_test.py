"""Subscription usage public route and schema tests."""

import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from azcommon.result import Failure, Success
from fastapi import HTTPException

from azents.core.auth.deps import WorkspaceMember
from azents.core.auth.permissions import Permission, Permissions
from azents.core.enums import LLMProvider, WorkspaceUserRole
from azents.services.subscription_usage.data import (
    ChatGPTSubscriptionFinancialDetails,
    SubscriptionUsageAvailable,
    SubscriptionUsageExternal,
    SubscriptionUsageLimit,
    SubscriptionUsageNotFound,
    SubscriptionUsageNotInWorkspace,
    SubscriptionUsageUnavailable,
    SubscriptionUsageUnavailableReason,
    SubscriptionUsageUnsupportedProvider,
)

from . import get_subscription_usage, list_integrations
from .data import (
    ChatGPTSubscriptionFinancialDetailsResponse,
    SubscriptionUsageAvailableResponse,
    SubscriptionUsageExternalResponse,
    SubscriptionUsageUnavailableResponse,
    XaiSubscriptionFinancialDetailsResponse,
    convert_subscription_usage_response,
)


def _member(*permissions: Permission) -> WorkspaceMember:
    return WorkspaceMember(
        user_id="user-1",
        workspace_id="workspace-1",
        workspace_user_id="workspace-user-1",
        role=WorkspaceUserRole.OWNER,
        permissions=set(permissions),
        session_id="session-1",
    )


def _available(*, financial: bool) -> SubscriptionUsageAvailable:
    now = datetime.datetime.now(datetime.UTC)
    return SubscriptionUsageAvailable(
        integration_id="integration-1",
        provider=LLMProvider.CHATGPT_OAUTH,
        fetched_at=now,
        plan_label="Pro",
        limits=(
            SubscriptionUsageLimit(
                id="primary",
                label="5-hour limit",
                used_percent=30.0,
                window_minutes=300,
                resets_at=now + datetime.timedelta(hours=1),
                primary=True,
            ),
        ),
        financial_details=(
            ChatGPTSubscriptionFinancialDetails(
                has_credits=True,
                unlimited=False,
                balance="12.50",
                spend_limit=None,
                spend_used=None,
                spend_remaining_percent=None,
                spend_resets_at=None,
                reached_type=None,
            )
            if financial
            else None
        ),
    )


async def test_integration_list_remains_provider_call_free() -> None:
    """Keep live subscription reads out of the existing integration list route."""
    service = AsyncMock()
    service.list_by_workspace.return_value = SimpleNamespace(items=[])

    response = await list_integrations(
        member=_member(Permissions.LLM_INTEGRATIONS_READ),
        service=service,
    )

    assert response.items == []
    service.list_by_workspace.assert_awaited_once_with("workspace-1")


async def test_missing_read_permission_returns_forbidden() -> None:
    """Require the existing integration read permission before usage reads."""
    service = AsyncMock()

    with pytest.raises(HTTPException) as captured:
        await get_subscription_usage(
            member=_member(),
            service=service,
            integration_id="integration-1",
        )

    assert captured.value.status_code == 403
    service.read.assert_not_awaited()


async def test_read_only_route_requests_financial_projection_removal() -> None:
    """Read-only callers receive operational quota data without financial details."""
    service = AsyncMock()
    service.read.return_value = Success(_available(financial=False))

    response = await get_subscription_usage(
        member=_member(Permissions.LLM_INTEGRATIONS_READ),
        service=service,
        integration_id="integration-1",
    )

    assert isinstance(response, SubscriptionUsageAvailableResponse)
    assert response.financial_details is None
    service.read.assert_awaited_once_with(
        integration_id="integration-1",
        workspace_id="workspace-1",
        include_financial_details=False,
    )


async def test_writer_route_receives_financial_details() -> None:
    """Integration managers receive the provider-specific financial projection."""
    service = AsyncMock()
    service.read.return_value = Success(_available(financial=True))

    response = await get_subscription_usage(
        member=_member(
            Permissions.LLM_INTEGRATIONS_READ,
            Permissions.LLM_INTEGRATIONS_WRITE,
        ),
        service=service,
        integration_id="integration-1",
    )

    assert isinstance(response, SubscriptionUsageAvailableResponse)
    assert response.financial_details is not None
    assert response.financial_details.type == "chatgpt"
    service.read.assert_awaited_once_with(
        integration_id="integration-1",
        workspace_id="workspace-1",
        include_financial_details=True,
    )


@pytest.mark.parametrize(
    "failure",
    [
        SubscriptionUsageNotFound(integration_id="integration-1"),
        SubscriptionUsageNotInWorkspace(integration_id="integration-1"),
    ],
)
async def test_missing_or_cross_workspace_integration_returns_not_found(
    failure: SubscriptionUsageNotFound | SubscriptionUsageNotInWorkspace,
) -> None:
    """Avoid leaking whether an integration belongs to another workspace."""
    service = AsyncMock()
    service.read.return_value = Failure(failure)

    with pytest.raises(HTTPException) as captured:
        await get_subscription_usage(
            member=_member(Permissions.LLM_INTEGRATIONS_READ),
            service=service,
            integration_id="integration-1",
        )

    assert captured.value.status_code == 404


async def test_unsupported_provider_returns_conflict() -> None:
    """Keep unsupported provider classes separate from unavailable usage states."""
    service = AsyncMock()
    service.read.return_value = Failure(
        SubscriptionUsageUnsupportedProvider(provider=LLMProvider.OPENAI)
    )

    with pytest.raises(HTTPException) as captured:
        await get_subscription_usage(
            member=_member(Permissions.LLM_INTEGRATIONS_READ),
            service=service,
            integration_id="integration-1",
        )

    assert captured.value.status_code == 409


def test_all_response_variants_serialize_discriminators_and_aware_times() -> None:
    """Keep the public availability union explicit for OpenAPI and clients."""
    now = datetime.datetime.now(datetime.UTC)
    external = SubscriptionUsageExternal(
        integration_id="integration-1",
        provider=LLMProvider.XAI_OAUTH,
        fetched_at=now,
        url="https://grok.com/usage",
        message="Usage is managed on xAI.",
    )
    unavailable = SubscriptionUsageUnavailable(
        integration_id="integration-1",
        provider=LLMProvider.CHATGPT_OAUTH,
        fetched_at=now,
        reason=SubscriptionUsageUnavailableReason.TEMPORARILY_UNAVAILABLE,
        message="Subscription usage is temporarily unavailable.",
        retryable=True,
    )

    available_response = convert_subscription_usage_response(
        _available(financial=False)
    )
    external_response = convert_subscription_usage_response(external)
    unavailable_response = convert_subscription_usage_response(unavailable)

    assert isinstance(available_response, SubscriptionUsageAvailableResponse)
    assert isinstance(external_response, SubscriptionUsageExternalResponse)
    assert isinstance(unavailable_response, SubscriptionUsageUnavailableResponse)
    assert available_response.type == "available"
    assert external_response.type == "external"
    assert unavailable_response.type == "unavailable"
    assert available_response.fetched_at.tzinfo is not None
    assert external_response.fetched_at.tzinfo is not None
    assert unavailable_response.fetched_at.tzinfo is not None


def test_all_public_union_discriminators_are_required() -> None:
    """Require explicit wire discriminators in OpenAPI and generated clients."""
    models = [
        ChatGPTSubscriptionFinancialDetailsResponse,
        XaiSubscriptionFinancialDetailsResponse,
        SubscriptionUsageAvailableResponse,
        SubscriptionUsageExternalResponse,
        SubscriptionUsageUnavailableResponse,
    ]

    for model in models:
        schema = model.model_json_schema()
        assert "type" in schema["required"]
